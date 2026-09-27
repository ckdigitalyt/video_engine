"""V14 Stage 9 — captions/audio/final FFmpeg assembly (directive §21, §37 Stage 9).

Assembles scene renders (Scene IR -> backend MP4s from the Stage 5 adapter)
into the final video:

1. concat scene renders -> common-codec re-encode (libx264 crf18 yuv420p)
2. kinetic captions burned AFTER composition (V13B binding) via the V13 caption
   state machine (captions.normalize_cues) + chunk_png carriers — one PNG per
   (cue, word) with that word active, overlaid with enable=between(t0,t1)
3. audio: per-scene procedural bed (procedural_audio.ambience per grammar,
   weighted by intensity) + narration (tts.tts_beat, cached per beat) placed at
   scene starts, bed ducked under voice (procedural_audio.duck_gain), stems
   summed to the exact total duration
4. mux audio onto the captioned video; assembly report with per-scene
   durations, caption repairs, narration overruns, sha256-16 of the final MP4

Narration longer than its scene is a recorded warning (bleed), never silent.
Missing TTS capability degrades to an explicit narration_skipped warning.
Unknown bed grammar degrades to an explicit bed_skipped warning.

CLI: python3 -m engine.v14_assembly assemble <plan.json> [--work DIR]
Plan paths resolve against the plan file's directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from engine.captions import band_rect, chunk_png, normalize_cues
from engine.procedural_audio import (SR, ambience, duck_gain, load_wav,
                                     save_wav)

OVERLAY_PASS_CAP = 120  # max caption overlays per ffmpeg pass; more -> passes
DEFAULT_BIBLE = {
    "typography": {"display": "BebasNeue-Regular.ttf"},
    "palette": {"text": "#F5F2EB", "accent": "#FFC857"},
}


def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       **kw)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): "
                           f"{' '.join(map(str, cmd[:6]))}...\n{p.stderr[-800:]}")
    return p


def _probe(path: Path) -> dict:
    p = _run(["ffprobe", "-v", "error", "-print_format", "json",
              "-show_format", "-show_streams", path])
    return json.loads(p.stdout)


def _dur(path: Path) -> float:
    return float(_probe(path)["format"]["duration"])


def _sha16(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:16]


def _stereo(y: np.ndarray) -> np.ndarray:
    if y.ndim == 1:
        y = np.stack([y, y], axis=1)
    return y


def _word_windows(words: list, t0: float, t1: float) -> list:
    """Proportional per-word timing across the cue window (kinetic cadence)."""
    weights = [max(len(w), 1) for w in words]
    total = sum(weights)
    span = t1 - t0
    out, cur = [], t0
    for wt in weights:
        d = span * wt / total
        out.append((cur, cur + d))
        cur += d
    return out


def _caption_key(words: list, active: int, bible: dict, zone_top) -> str:
    blob = json.dumps({"w": words, "a": active, "z": zone_top,
                       "t": bible.get("typography"), "p": bible.get("palette"),
                       "v": 2}, sort_keys=True)
    return "cap_" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def build_caption_inputs(cues: list, bible: dict, png_dir: Path,
                         offset: float = 0.0) -> tuple:
    """Scene-local cues -> absolute overlay inputs via the V13 state machine.

    Returns (inputs, repairs). inputs: [{png, t0, t1, cue}] in time order —
    one PNG per (cue, word) with that word active, windows non-overlapping
    inside the cue (asserted, same invariant as build_shot_captions).
    """
    from engine.bible import rgb255
    rgb255(bible, "text")  # loud early failure on a bad palette
    abs_cues = [dict(c, t0=float(c["t0"]) + offset, t1=float(c["t1"]) + offset)
                for c in (cues or [])]
    norm, repairs = normalize_cues(abs_cues)
    png_dir.mkdir(parents=True, exist_ok=True)
    zone_top = band_rect()[0]
    inputs = []
    for ci, cue in enumerate(norm):
        lines = cue.get("lines")
        words = []
        for line in (lines or [str(cue.get("text", "")).split()]):
            words += [w for w in (line if isinstance(line, list)
                                  else str(line).split()) if str(w).strip()]
        if not words:
            continue
        chunk = {"lines": [words]}
        windows = _word_windows(words, float(cue["t0"]), float(cue["t1"]))
        ws = cue.get("word_starts")
        if isinstance(ws, list) and len(ws) == len(words):
            # V15: highlight follows the narration's measured word times
            # (v15_timing), clipped into the (possibly repaired) cue window
            c0, c1 = float(cue["t0"]), float(cue["t1"])
            st = [min(max(float(w) + offset, c0), c1) for w in ws]
            st[0] = c0
            for k in range(1, len(st)):
                st[k] = max(st[k], st[k - 1])
            windows = [(st[k], st[k + 1] if k + 1 < len(st) else c1)
                       for k in range(len(st))]
        prev_end = -1.0
        for wi, (wt0, wt1) in enumerate(windows):
            assert wt0 >= prev_end - 1e-9, "caption word windows overlap"
            prev_end = wt1
            # V15: content-addressed carrier name. The V14 name
            # cue{ci}_w{wi} restarted per scene in ONE shared dir, so every
            # scene overwrote the previous scene's PNGs and the whole video
            # burned the LAST beat's captions. Identical content -> same
            # file (safe reuse); different content can never collide.
            png = png_dir / (_caption_key(words, wi, bible, zone_top)
                             + ".png")
            if not png.exists():
                chunk_png(chunk, bible, png, active=wi, zone_top=zone_top)
            inputs.append({"png": str(png), "t0": round(wt0, 3),
                           "t1": round(wt1, 3), "cue": ci,
                           "text": " ".join(words), "word": words[wi]})
    return inputs, repairs


def _burn_pass(video: Path, inputs: list, out: Path) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video]
    for item in inputs:
        cmd += ["-i", item["png"]]
    y = band_rect()[0]
    fl, base = "", "0:v"
    for i, item in enumerate(inputs):
        lbl = f"b{i + 1}"
        fl += (f"[{base}][{i + 1}:v]"
               f"overlay=x=0:y={y}:eof_action=repeat:"
               f"enable='between(t,{item['t0']},{item['t1']})'[{lbl}];")
        base = lbl
    cmd += ["-filter_complex", fl.rstrip(";"), "-map", f"[{base}]",
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-r", "30", "-an", out]
    _run(cmd)


def burn_captions(video: Path, inputs: list, out: Path) -> dict:
    """Burn caption overlays AFTER composition; >cap inputs -> sequential passes."""
    passes, src, todo = 0, video, list(inputs)
    while todo:
        passes += 1
        chunk, todo = todo[:OVERLAY_PASS_CAP], todo[OVERLAY_PASS_CAP:]
        dst = out if not todo else out.parent / f"{out.stem}_p{passes}.mp4"
        _burn_pass(src, chunk, dst)
        src = dst
    if src != out:
        src.replace(out)
    for p in out.parent.glob(f"{out.stem}_p*.mp4"):
        p.unlink(missing_ok=True)
    return {"passes": passes, "overlays": len(inputs)}


def _concat_scenes(videos: list, out: Path) -> dict:
    sizes = set()
    for v in videos:
        info = _probe(v)
        vs = [s for s in info["streams"] if s["codec_type"] == "video"]
        if len(vs) != 1:
            raise RuntimeError(f"expected one video stream in {v}")
        sizes.add((vs[0]["width"], vs[0]["height"]))
    if len(sizes) != 1:
        raise RuntimeError(f"scene frame sizes differ: {sorted(sizes)}")
    (w, h) = sizes.pop()
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for v in videos:
        cmd += ["-i", v]
    fl = "".join(f"[{i}:v]fps=30,format=yuv420p[v{i}];"
                 for i in range(len(videos)))
    fl += "".join(f"[v{i}]" for i in range(len(videos)))
    fl += f"concat=n={len(videos)}:v=1:a=0[out]"
    cmd += ["-filter_complex", fl, "-map", "[out]", "-c:v", "libx264",
            "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", "-an", out]
    _run(cmd)
    return {"scenes": len(videos), "frame": f"{w}x{h}"}


def concat_and_burn(videos: list, inputs: list, out: Path,
                    fps: int = 30) -> dict:
    """V15 single-encode assembly: scene concat (same concat FILTER, same
    per-input fps/format normalization) + captions burned AFTER composition
    in ONE libx264 pass. The caption strip is streamed from Python as raw
    RGBA (one pre-rendered carrier PNG active per frame, same windows and
    band as burn_captions) — replaces concat.mp4 + N overlay inputs, which
    cost two full re-encodes (~4-5 min for a 50 s video on 4 cores)."""
    from PIL import Image
    sizes, total = set(), 0.0
    for v in videos:
        info = _probe(v)
        vs = [s for s in info["streams"] if s["codec_type"] == "video"]
        sizes.add((vs[0]["width"], vs[0]["height"]))
        total += float(info["format"]["duration"])
    if len(sizes) != 1:
        raise RuntimeError(f"scene frame sizes differ: {sorted(sizes)}")
    (w, h) = sizes.pop()
    band_y = band_rect()[0]
    strip_h = 192
    n_frames = int(round(total * fps))
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for v in videos:
        cmd += ["-i", str(v)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{strip_h}",
            "-r", str(fps), "-i", "pipe:0"]
    k = len(videos)
    fl = "".join(f"[{i}:v]fps={fps},format=yuv420p[v{i}];" for i in range(k))
    fl += "".join(f"[v{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0[cat];"
    fl += f"[cat][{k}:v]overlay=x=0:y={band_y}:eof_action=pass[out]"
    cmd += ["-filter_complex", fl, "-map", "[out]", "-c:v", "libx264",
            "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-an", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    blank = bytes(w * strip_h * 4)
    cache: dict = {}
    items = sorted(inputs, key=lambda i: i["t0"])
    j, shown = 0, 0
    try:
        for f in range(n_frames):
            t = f / fps
            while j < len(items) and items[j]["t1"] < t:
                j += 1
            cur = None
            for it in items[j:j + 3]:  # windows are non-overlapping
                if it["t0"] <= t <= it["t1"] and it["t1"] > it["t0"]:
                    cur = it
            if cur is None:
                proc.stdin.write(blank)
                continue
            b = cache.get(cur["png"])
            if b is None:
                im = Image.open(cur["png"]).convert("RGBA")
                if im.size != (w, strip_h):
                    im = im.resize((w, strip_h))
                b = cache[cur["png"]] = im.tobytes()
            proc.stdin.write(b)
            shown += 1
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"single-pass assembly failed: {err[-800:]}")
    return {"scenes": k, "frame": f"{w}x{h}", "frames": n_frames,
            "caption_frames": shown, "overlays": len(inputs), "passes": 1}


def build_bed_track(scenes: list, total_s: float, out: Path,
                    warnings: list) -> Path:
    """Per-scene procedural ambience placed on one total-length stereo track."""
    n = int(round(total_s * SR))
    bed = np.zeros((n, 2), dtype=np.float32)
    for sc in scenes:
        bd = sc.get("bed") or {}
        if not bd:
            continue
        start = int(round(float(sc["_start"]) * SR))
        m = int(round(float(sc["_dur"]) * SR))
        try:
            seg = _stereo(np.asarray(ambience(sc["_dur"], bd["grammar"]),
                                     dtype=np.float32))
        except Exception as e:  # unknown grammar / synth failure -> reported
            warnings.append({"scene": sc["scene_id"],
                             "warning": "bed_skipped",
                             "reason": str(e)[:160]})
            continue
        seg = seg[:m] * float(bd.get("intensity", 0.5))
        bed[start:start + len(seg)] += seg
    return save_wav(out, np.clip(bed, -0.98, 0.98))


def build_voice_track(scenes: list, story_dir: Path, total_s: float,
                      out: Path, warnings: list) -> tuple:
    """Narration per scene at scene start. Returns (path, placements)."""
    from engine.tts import tts_beat
    n = int(round(total_s * SR))
    voice = np.zeros((n, 2), dtype=np.float32)
    placements = []
    for sc in scenes:
        nar = sc.get("narration") or {}
        if not nar:
            continue
        # V15: narration may start after a lead-in (offset) and may span
        # several shot-scenes of one beat (span_s) — overrun is judged
        # against the span, not the first shot alone.
        start = int(round((float(sc["_start"])
                           + float(nar.get("offset", 0.0))) * SR))
        span = float(nar.get("span_s", sc["_dur"]))
        try:
            if nar.get("audio"):
                wav = Path(nar["audio"])
                nd = _dur(wav)
                rel = str(wav)
            else:
                res = tts_beat(story_dir, nar["beat_id"], nar["text"])
                wav = story_dir / res["file"]
                nd = float(res["duration"])
                rel = res["file"]
            y = _stereo(load_wav(wav)).astype(np.float32)
            m = min(len(y), n - start)
            voice[start:start + m] += y[:m]
            placements.append({"scene": sc["scene_id"], "file": rel,
                               "duration_s": round(nd, 3)})
            if nd + float(nar.get("offset", 0.0)) > span + 0.05:
                warnings.append({"scene": sc["scene_id"],
                                 "warning": "narration_overrun",
                                 "narration_s": round(nd, 3),
                                 "scene_s": round(span, 3)})
        except Exception as e:
            warnings.append({"scene": sc["scene_id"],
                             "warning": "narration_skipped",
                             "reason": str(e)[:160]})
    return save_wav(out, np.clip(voice, -0.98, 0.98)), placements


def build_underscore_track(scenes: list, total_s: float, out: Path,
                           music: dict) -> Path:
    """V15: one continuous procedural underscore (pad + soft pulse) with a
    per-scene intensity envelope — replaces the per-scene ambience hum whose
    level (~-54 dBFS) made the V14 bed effectively silent."""
    from engine.procedural_audio import underscore
    ints = [float(sc.get("intensity", music.get("default_intensity", 0.6)))
            for sc in scenes]
    y = underscore(total_s, ints, [sc["_dur"] for sc in scenes])
    return save_wav(out, y * float(music.get("gain", 0.9)))


def build_sfx_track(scenes: list, total_s: float, out: Path,
                    warnings: list) -> tuple:
    """V15: procedural SFX at scene-local times (shot cuts, on-word
    reveals). Returns (path, placements)."""
    from engine.procedural_audio import sfx
    n = int(round(total_s * SR))
    track = np.zeros((n, 2), dtype=np.float32)
    placed = []
    for sc in scenes:
        for ev in sc.get("sfx") or []:
            try:
                y = sfx(ev["kind"]) * float(ev.get("gain", 1.0))
            except Exception as e:
                warnings.append({"scene": sc["scene_id"],
                                 "warning": "sfx_skipped",
                                 "reason": str(e)[:120]})
                continue
            at = float(sc["_start"]) + float(ev["t"])
            i0 = max(0, int(round(at * SR)))
            m = min(len(y), n - i0)
            if m > 0:
                track[i0:i0 + m] += y[:m]
                placed.append({"t": round(at, 3), "kind": ev["kind"]})
    return save_wav(out, np.clip(track, -0.98, 0.98)), placed


def mix_audio(bed_path: Path, voice_path: Path, out: Path,
              sfx_path: Path | None = None) -> Path:
    """Bed ducked under voice (duck_gain envelope) + voice (+ SFX), clipped."""
    bed = load_wav(bed_path).astype(np.float32)
    voice = load_wav(voice_path).astype(np.float32)
    fx = load_wav(sfx_path).astype(np.float32) if sfx_path else None
    n = max(len(bed), len(voice), len(fx) if fx is not None else 0)
    b = np.zeros((n, 2), dtype=np.float32)
    v = np.zeros((n, 2), dtype=np.float32)
    b[:len(bed)], v[:len(voice)] = bed, voice
    env = duck_gain(v.mean(axis=1))
    mixed = b * env[:, None] + v
    if fx is not None:
        mixed[:len(fx)] += fx
    return save_wav(out, np.clip(mixed, -0.98, 0.98))


LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"  # short-form delivery loudness


def _mux(video: Path, audio: Path, out: Path) -> None:
    # additive filter only (no FFmpeg redesign): loudness-normalize the mix
    _run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio,
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-af", LOUDNORM, "-ar", "48000",
          "-c:a", "aac", "-b:a", "192k", out])


def assemble(plan: dict, work_dir: Path, plan_dir: Path | None = None) -> dict:
    """Full Stage 9 assembly. plan: story_id, bible?, scenes[{scene_id, video,
    captions?, narration?, audio?, bed?}], out. Returns the assembly report."""
    work_dir = Path(work_dir)
    (work_dir / "captions").mkdir(parents=True, exist_ok=True)
    bible = dict(DEFAULT_BIBLE, **(plan.get("bible") or {}))
    warnings: list = []

    def rp(p) -> Path:
        p = Path(p)
        return p if p.is_absolute() else (plan_dir or Path.cwd()) / p

    scenes = []
    for sc in plan["scenes"]:
        scenes.append(dict(sc, video=rp(sc["video"]), _dur=_dur(rp(sc["video"]))))
    t = 0.0
    for sc in scenes:
        sc["_start"] = round(t, 3)
        t = round(t + sc["_dur"], 3)
    total_s = t

    report: dict = {"story_id": plan.get("story_id", "v14"),
                    "total_s": round(total_s, 3), "scenes": [], "warnings": []}

    single = bool(plan.get("single_pass"))
    # 1. concat scene renders (V15 single_pass: concat happens in step 2)
    concat = work_dir / "concat.mp4"
    if not single:
        report["concat"] = _concat_scenes([sc["video"] for sc in scenes],
                                          concat)

    # 2. captions AFTER composition
    inputs, all_repairs = [], []
    for sc in scenes:
        cin, reps = build_caption_inputs(sc.get("captions"), bible,
                                         work_dir / "captions",
                                         offset=sc["_start"])
        inputs += cin
        all_repairs += [dict(r, scene=sc["scene_id"]) for r in reps]
        report["scenes"].append({"scene_id": sc["scene_id"],
                                 "duration_s": round(sc["_dur"], 3),
                                 "start_s": sc["_start"],
                                 "cues": len(sc.get("captions") or []),
                                 "words": sum(1 for i in inputs
                                              if False) or None})
    for row in report["scenes"]:
        row.pop("words", None)
    cap_video = work_dir / "captioned.mp4"
    if single:
        report["captions"] = concat_and_burn([sc["video"] for sc in scenes],
                                             inputs, cap_video)
    else:
        report["captions"] = burn_captions(concat, inputs, cap_video)
    # V15: exact overlay record (png, text, active word, window) so the gate
    # can prove caption text == narration per scene from the artifact list
    report["caption_overlays"] = inputs
    report["caption_repairs"] = all_repairs
    report["scenes"] = [{**row,
                         "caption_words": sum(1 for i in inputs
                                              if i["cue"] is not None
                                              and _in_scene(i, row))}
                        for row in report["scenes"]]

    # 3. audio
    story_dir = rp(plan.get("story_dir", work_dir))
    if plan.get("music"):
        bed = build_underscore_track(scenes, total_s, work_dir / "bed.wav",
                                     plan["music"])
    else:
        bed = build_bed_track(scenes, total_s, work_dir / "bed.wav", warnings)
    voice, placements = build_voice_track(scenes, story_dir, total_s,
                                          work_dir / "voice.wav", warnings)
    fx_path = None
    if any(sc.get("sfx") for sc in scenes):
        fx_path, report["sfx"] = build_sfx_track(
            scenes, total_s, work_dir / "sfx.wav", warnings)
    mix = mix_audio(bed, voice, work_dir / "mix.wav", fx_path)
    report["narration"] = placements
    report["audio_mix"] = {"bed": str(bed), "voice": str(voice),
                           "mix": str(mix), "ducked": True}

    # 4. mux
    out = rp(plan["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    _mux(cap_video, mix, out)
    fin = _probe(out)
    report["final"] = {"path": str(out), "sha256_16": _sha16(out),
                       "duration_s": round(float(fin["format"]["duration"]), 3),
                       "streams": [s["codec_name"] for s in fin["streams"]]}
    report["warnings"] = warnings
    return report


def _in_scene(item: dict, row: dict) -> bool:
    return row["start_s"] - 1e-6 <= item["t0"] < row["start_s"] + row["duration_s"]


def main() -> int:
    ap = argparse.ArgumentParser(description="V14 Stage 9 assembly")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap_a = sub.add_parser("assemble")
    ap_a.add_argument("plan")
    ap_a.add_argument("--work", default=None)
    args = ap.parse_args()
    if args.cmd == "assemble":
        plan_path = Path(args.plan).resolve()
        plan = json.loads(plan_path.read_text())
        work = Path(args.work) if args.work else plan_path.parent / "assembly_work"
        rep = assemble(plan, work, plan_dir=plan_path.parent)
        print(json.dumps(rep, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
