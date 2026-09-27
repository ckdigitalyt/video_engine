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
        prev_end = -1.0
        for wi, (wt0, wt1) in enumerate(windows):
            assert wt0 >= prev_end - 1e-9, "caption word windows overlap"
            prev_end = wt1
            png = png_dir / f"cue{ci:03d}_w{wi:02d}.png"
            chunk_png(chunk, bible, png, active=wi, zone_top=zone_top)
            inputs.append({"png": str(png), "t0": round(wt0, 3),
                           "t1": round(wt1, 3), "cue": ci})
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
        start = int(round(float(sc["_start"]) * SR))
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
            if nd > float(sc["_dur"]) + 0.05:
                warnings.append({"scene": sc["scene_id"],
                                 "warning": "narration_overrun",
                                 "narration_s": round(nd, 3),
                                 "scene_s": round(float(sc["_dur"]), 3)})
        except Exception as e:
            warnings.append({"scene": sc["scene_id"],
                             "warning": "narration_skipped",
                             "reason": str(e)[:160]})
    return save_wav(out, np.clip(voice, -0.98, 0.98)), placements


def mix_audio(bed_path: Path, voice_path: Path, out: Path) -> Path:
    """Bed ducked under voice (duck_gain envelope) + voice, clipped."""
    bed = load_wav(bed_path).astype(np.float32)
    voice = load_wav(voice_path).astype(np.float32)
    n = max(len(bed), len(voice))
    b = np.zeros((n, 2), dtype=np.float32)
    v = np.zeros((n, 2), dtype=np.float32)
    b[:len(bed)], v[:len(voice)] = bed, voice
    env = duck_gain(v.mean(axis=1))
    return save_wav(out, np.clip(b * env[:, None] + v, -0.98, 0.98))


def _mux(video: Path, audio: Path, out: Path) -> None:
    _run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio,
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
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

    # 1. concat scene renders
    concat = work_dir / "concat.mp4"
    report["concat"] = _concat_scenes([sc["video"] for sc in scenes], concat)

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
    report["captions"] = burn_captions(concat, inputs, cap_video)
    report["caption_repairs"] = all_repairs
    report["scenes"] = [{**row,
                         "caption_words": sum(1 for i in inputs
                                              if i["cue"] is not None
                                              and _in_scene(i, row))}
                        for row in report["scenes"]]

    # 3. audio
    story_dir = rp(plan.get("story_dir", work_dir))
    bed = build_bed_track(scenes, total_s, work_dir / "bed.wav", warnings)
    voice, placements = build_voice_track(scenes, story_dir, total_s,
                                          work_dir / "voice.wav", warnings)
    mix = mix_audio(bed, voice, work_dir / "mix.wav")
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
