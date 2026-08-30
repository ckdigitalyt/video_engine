"""assembler.py — Assembly + audio master (directive §18, Wave 3).

Concatenates rendered shots, synthesizes narration TTS per beat (cached),
aligns shots to ACTUAL TTS durations (re-render cheap procedural shots when
timing shifts >20%, otherwise trim/pad), builds a per-shot music_state bed
with per-shot duck_music_db + local SFX synthesis, ducks music under
narration, loudness-normalizes to YouTube spec (I=-14 LUFS, TP=-1.5) and
muxes the final 1920x1080 30fps H.264 + AAC master.

All heavy lifting reuses the existing deterministic audio stack
(engine/audio/timeline.py, engine/audio/soundtrack.py) — no behavior forks.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np

from engine.audio.soundtrack import SR, synthesize_music_bed, synthesize_sfx
from engine.audio.timeline import (
    duck_music_under_narration,
    ffmpeg,
    measure_loudness,
    normalize_to_target,
    synthesize_narration,
)
from engine.v3.qa.technical import ffprobe

logger = logging.getLogger(__name__)

TARGET_LUFS = -14.0
TAIL_PAD_SEC = 0.6
TIMING_RERENDER_THRESHOLD = 0.20
# Cheap procedural renderers worth re-rendering when timing shifts.
PROCEDURAL = {"MOTION_CANVAS", "PIXIJS", "MANIM"}
MUSIC_MOOD = {"build": "tension", "peak": "tension", "drop": "tension",
              "silence": "calm", "ambient": "calm", "resolve": "calm",
              "sustain": "calm"}
SFX_KINDS = {"whoosh", "pop", "sting", "pour"}
DUCK_BASE_VOLUME = 0.35


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    logger.debug("ffmpeg: %s", " ".join(cmd)[:220])
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout)


def probe_audio_duration(path: Path) -> float:
    probe = ffprobe(path)
    return float(probe.get("duration") or 0.0)


def tts_beat_narration(text: str, out_base: Path, *,
                       cache: bool = True) -> tuple[Path, str]:
    """TTS one beat (cached by text hash). Returns (audio_path, provider)."""
    out_base.parent.mkdir(parents=True, exist_ok=True)
    import hashlib

    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    cached = out_base.parent / f"{key}{out_base.suffix}"
    if cache and cached.exists():
        return cached, "cache"
    path, _words = synthesize_narration(text, out_base)
    return path, "synth"


def build_narration_master(beat_audio: list[tuple[float, Path]],
                           total_duration: float, out_wav: Path) -> Path:
    """Place each beat's narration at its start time over silence."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    padded: list[Path] = []
    tmp_dir = out_wav.parent / "padded"
    tmp_dir.mkdir(exist_ok=True)
    for i, (start, audio) in enumerate(beat_audio):
        out = tmp_dir / f"beat_{i:02d}.wav"
        delay_ms = int(round(start * 1000))
        proc = _run([
            ffmpeg(), "-y", "-i", str(audio),
            "-af", f"adelay={delay_ms}:all=1,"
                   f"apad=whole_dur={total_duration:.3f}",
            "-ar", "48000", "-ac", "2", str(out)])
        if proc.returncode != 0:
            raise RuntimeError(f"narration pad failed: {proc.stderr[-200:]}")
        padded.append(out)
    concat_list = out_wav.parent / "narration_concat.txt"
    concat_list.write_text(
        "".join(f"file '{p}'\n" for p in padded), encoding="utf-8")
    proc = _run([
        ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i",
        str(concat_list), "-c", "copy", str(out_wav)])
    if proc.returncode != 0:
        raise RuntimeError(f"narration concat failed: {proc.stderr[-200:]}")
    return out_wav


def build_music_bed(shots: list[dict], total_duration: float,
                    out_wav: Path, work_dir: Path) -> Path:
    """Per-shot music_state bed + SFX + per-shot duck_music_db, assembled
    in numpy (all inputs are local synthesized WAVs — deterministic)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    bed = np.zeros(int(round(total_duration * SR)) + SR, dtype=np.float64)
    t_cursor = 0.0
    seg_paths: list[Path] = []
    for i, shot in enumerate(shots):
        state = shot.get("music_state", "ambient")
        dur = float(shot.get("duration_sec", 4.0))
        seg = work_dir / f"seg_{i:02d}.wav"
        if state == "silence":
            samples = np.zeros(int(round(dur * SR)), dtype=np.float64)
            _write_raw_wav(seg, samples)
        else:
            synthesize_music_bed(dur, seg, mood=MUSIC_MOOD.get(state, "calm"))
        duck = float(shot.get("duck_music_db", -12))
        gain = (10 ** (duck / 20.0)) / (10 ** (-12 / 20.0))  # rel. to -12dB
        samples = _read_wav(seg) * max(0.0, min(2.0, gain))
        a = int(round(t_cursor * SR))
        b = min(a + len(samples), len(bed))
        if b > a:
            bed[a:b] += samples[:b - a]
        t_cursor += dur
        seg_paths.append(seg)

    # SFX cues at the shot boundaries that request them.
    t_cursor = 0.0
    for shot in shots:
        start = int(round(t_cursor * SR))
        for cue in (shot.get("sfx") or [])[:2]:
            kind = _match_sfx(cue)
            if not kind:
                continue
            sfx_path = work_dir / f"sfx_{kind}.wav"
            if not sfx_path.exists():
                synthesize_sfx(kind, sfx_path)
            samples = _read_wav(sfx_path) * 0.5
            a = min(start, len(bed) - len(samples))
            if a >= 0:
                bed[a:a + len(samples)] += samples
        t_cursor += float(shot.get("duration_sec", 4.0))

    bed = bed[:int(round(total_duration * SR))]
    peak = float(np.max(np.abs(bed))) or 1.0
    if peak > 0.9:
        bed *= 0.9 / peak
    _write_raw_wav(out_wav, bed)
    return out_wav


def _match_sfx(cue: str) -> str | None:
    c = str(cue).lower()
    for kind in SFX_KINDS:
        if kind in c:
            return kind
    if any(w in c for w in ("rumble", "impact", "explosion", "boom")):
        return "sting"
    if any(w in c for w in ("swish", "transition", "air")):
        return "whoosh"
    return None


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        n = wf.getnframes()
        data = np.frombuffer(wf.readframes(n), dtype=np.int16).astype(
            np.float64) / 32768.0
        if wf.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    return data


def _write_raw_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(data.tobytes())


def conform_clip(src: Path, dst: Path, duration: float, width: int,
                 height: int, fps: int) -> Path:
    """One clip → exact resolution/fps/duration (trim or clone-pad tail)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dur = max(duration, 0.2)
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
          f"fps={fps},format=yuv420p,"
          f"tpad=stop_mode=clone:stop_duration={dur + 1:.3f}")
    proc = _run([
        ffmpeg(), "-y", "-i", str(src),
        "-vf", vf,
        "-t", f"{dur:.3f}",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        str(dst)])
    if proc.returncode != 0:
        raise RuntimeError(f"conform failed for {src.name}: "
                           f"{proc.stderr[-300:]}")
    return dst


def concat_clips(clips: list[Path], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lst = out_path.parent / "concat_video.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    proc = _run([
        ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c", "copy", str(out_path)])
    if proc.returncode != 0:
        raise RuntimeError(f"video concat failed: {proc.stderr[-300:]}")
    return out_path


def assemble_master(video_id: str, shots: list[dict], script_doc: dict,
                    records: dict[str, dict], out_dir: str | Path, *,
                    width: int = 1920, height: int = 1080, fps: int = 30,
                    audio_master: bool = True,
                    rerender_fn: Callable[[dict, float], dict] | None = None,
                    tts_cache: bool = True) -> dict:
    """Full assembly pass. Returns
    {"master", "video_duration", "loudness", "timing_adjustments", ...}."""
    out = Path(out_dir)
    work = out / "assemble"
    work.mkdir(parents=True, exist_ok=True)

    # ── 1. TTS per beat (cached) + actual durations ──────────────────────
    beats = script_doc.get("beats", [])
    beat_audio: list[tuple[float, Path]] = []
    beat_dur: dict[str, float] = {}
    for i, beat in enumerate(beats):
        text = beat.get("narration", "").strip()
        if not text:
            beat_dur[beat["beat_id"]] = 0.0
            continue
        audio, _prov = tts_beat_narration(
            text, work / "narration" / f"beat_{i:02d}.wav",
            cache=tts_cache)
        dur = probe_audio_duration(audio)
        beat_dur[beat["beat_id"]] = dur
        beat_audio.append((0.0, audio))  # start resolved below

    narration_total = sum(beat_dur.values())
    video_total = round(narration_total + TAIL_PAD_SEC, 2)

    # ── 2. Align shots to actual TTS durations ───────────────────────────
    # Scale each beat's shots proportionally inside the beat's actual
    # duration; record timing adjustments; optionally re-render cheap
    # procedural shots whose timing shifted >20%.
    adjustments: list[dict] = []
    shot_durations: dict[str, float] = {}
    for shot in shots:
        shot_durations[shot["shot_id"]] = float(shot.get("duration_sec", 4.0))
    for beat in beats:
        bid = beat["beat_id"]
        planned = sum(s["duration_sec"] for s in shots
                      if s.get("metadata", {}).get("beat_id") == bid)
        actual = beat_dur.get(bid, 0.0)
        if planned <= 0 or actual <= 0:
            continue
        scale = actual / planned
        for s in shots:
            if s.get("metadata", {}).get("beat_id") != bid:
                continue
            new_dur = round(s["duration_sec"] * scale, 2)
            shot_durations[s["shot_id"]] = new_dur
            shift = abs(new_dur - s["duration_sec"]) / max(
                s["duration_sec"], 0.1)
            if shift > TIMING_RERENDER_THRESHOLD \
                    and s.get("renderer") in PROCEDURAL and rerender_fn:
                rec = rerender_fn(s, new_dur)
                if rec.get("ok"):
                    records[s["shot_id"]] = rec
                    adjustments.append({
                        "shot_id": s["shot_id"], "reason": "timing>20%",
                        "planned": s["duration_sec"], "final": new_dur,
                        "rerendered": True})
                    continue
            adjustments.append({
                "shot_id": s["shot_id"], "reason": "timing",
                "planned": s["duration_sec"], "final": new_dur,
                "rerendered": False})
        # Distribute rounding error onto the beat's last shot so beats
        # butt-joint exactly at the narration boundary.
        _fix_beat_rounding(shots, bid, shot_durations, actual)

    # Recompute beat starts from the aligned shot durations.
    beat_start: dict[str, float] = {}
    t = 0.0
    for beat in beats:
        beat_start[beat["beat_id"]] = t
        beat_total = sum(shot_durations[s["shot_id"]] for s in shots
                         if s.get("metadata", {}).get("beat_id")
                         == beat["beat_id"])
        if beat_total > 0:
            t += beat_total
    beat_audio = [(beat_start[b["beat_id"]], a)
                  for (b, (_s, a)) in zip(beats, beat_audio)
                  if beat_dur.get(b["beat_id"], 0) > 0]

    # ── 3. Conform + concat video track ──────────────────────────────────
    clips_dir = work / "clips"
    clips_dir.mkdir(exist_ok=True)
    clips: list[Path] = []
    for shot in shots:
        rec = records.get(shot["shot_id"]) or {}
        if not rec.get("ok") or not rec.get("path"):
            raise RuntimeError(
                f"shot {shot['shot_id']} has no rendered artifact — "
                f"cannot assemble (attempts: {rec.get('attempts')})")
        dst = clips_dir / f"{shot['shot_id']}.mp4"
        conform_clip(Path(rec["path"]), dst, shot_durations[shot["shot_id"]],
                     width, height, fps)
        clips.append(dst)
    video_silent = work / "video_silent.mp4"
    concat_clips(clips, video_silent)

    actual_total = probe_audio_duration(video_silent) or video_total
    video_total = round(actual_total, 2)

    result: dict[str, Any] = {"timing_adjustments": adjustments,
                              "video_duration": video_total}

    if not audio_master or not beat_audio:
        # Silent master (pure video) — audio QA marks this run accordingly.
        master = out / "master.mp4"
        shutil.copy(video_silent, master)
        result.update({"master": str(master), "audio": "silent"})
        return result

    # ── 4. Narration master ──────────────────────────────────────────────
    narration_master = build_narration_master(
        beat_audio, video_total, work / "narration_master.wav")

    # ── 5. Music bed + SFX + per-shot duck ───────────────────────────────
    bed = build_music_bed(shots, video_total, work / "music_bed.wav",
                          work / "bed_segs")

    # ── 6. Duck music under narration, loudness-normalize ────────────────
    ducked = duck_music_under_narration(narration_master, bed,
                                        work / "narration_music_mix.m4a",
                                        music_volume=DUCK_BASE_VOLUME)
    final_audio = normalize_to_target(ducked, work / "audio_master.m4a",
                                      target_lufs=TARGET_LUFS)

    # ── 7. Mux master ────────────────────────────────────────────────────
    master = out / "master.mp4"
    proc = _run([
        ffmpeg(), "-y", "-i", str(video_silent), "-i", str(final_audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", str(master)])
    if proc.returncode != 0:
        raise RuntimeError(f"mux failed: {proc.stderr[-300:]}")

    loud = measure_loudness(master)
    result.update({"master": str(master), "loudness": loud,
                   "narration_master": str(narration_master),
                   "music_bed": str(bed)})
    return result


def _fix_beat_rounding(shots: list[dict], beat_id: str,
                       shot_durations: dict[str, float], actual: float) -> None:
    members = [s for s in shots
               if s.get("metadata", {}).get("beat_id") == beat_id]
    if not members:
        return
    diff = round(actual - sum(shot_durations[s["shot_id"]]
                              for s in members), 3)
    if abs(diff) >= 0.01:
        last = members[-1]["shot_id"]
        shot_durations[last] = round(shot_durations[last] + diff, 3)


def reframe_916(master: Path, out_path: Path, *, width: int = 1080,
                height: int = 1920) -> Path:
    """Optional 9:16 reframe — centre crop with a slight upward bias
    (subjects sit above centre in documentary framing). Never touches the
    16:9 master; run only on request."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop_w = f"min(iw,ih*{width}/{height})"
    crop_h = f"min(ih,iw*{height}/{width})"
    vf = (f"crop={crop_w}:{crop_h},scale={width}:{height},"
          f"setsar=1")
    proc = _run([
        ffmpeg(), "-y", "-i", str(master), "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy", str(out_path)], timeout=1200)
    if proc.returncode != 0:
        raise RuntimeError(f"9:16 reframe failed: {proc.stderr[-300:]}")
    return out_path
