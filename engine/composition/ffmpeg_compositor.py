"""FFmpeg delivery compositor (directive §16, §28).

FFmpeg is the PRIMARY compositor: concatenation, audio mixing, ducking,
subtitle burn-in, normalization, encoding, muxing.  MoviePy is NOT used for
heavy final composition.  This module combines beat clips + audio tracks into
a final mastered video.

Pipeline per beat:
    - incremental beat clips (rendered independently, §31) -> concat
    - narration, music (ducked), SFX -> mixed audio
    - subtitles burned in (ASS/SRT)
    - loudness normalization (Gate 8: LUFS + true peak)
    - final mux
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from engine.audio.timeline import (
    duck_music_under_narration,
    ffmpeg,
    measure_loudness,
    normalize_to_target,
)

TARGET_LUFS = -14.0  # YouTube dialnorm delivery target


def _exists_list(paths: list[Path]) -> Path:
    """Write a concat list file for FFmpeg -f concat."""
    lst = Path("concat_list.txt")
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in paths) + "\n",
                   encoding="utf-8")
    return lst


def concat_clips(beat_clips: list[Path], out: Path,
                 resolution: tuple[int, int] = (1920, 1080),
                 fps: int = 30) -> Path:
    """Concatenate beat clips (same codec/res) with hard cuts into one video."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lst = _exists_list(beat_clips)
    cmd = [
        ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-vf", f"scale={resolution[0]}:{resolution[1]}:force_original_aspect_ratio=decrease,"
               f"pad={resolution[0]}:{resolution[1]}:(ow-iw)/2:(oh-ih)/2",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def burn_subtitles(video: Path, subs: Path, out: Path) -> Path:
    """Burn ASS/SRT subtitles into the video (Gate: captions layer)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg(), "-y", "-i", str(video),
        "-vf", f"subtitles={subs.resolve()}:force_style='FontSize=20,PrimaryColour=&H00FFFFFF,"
               f"BorderStyle=3,Outline=1,Shadow=1'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "copy", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def compose_final(beat_clips: list[Path],
                  narration: Optional[Path],
                  music: Optional[Path],
                  subtitles: Optional[Path],
                  out: Path,
                  resolution: tuple[int, int] = (1920, 1080),
                  fps: int = 30) -> dict:
    """Full composition: concat beats, mix audio (ducked music), master to
    target loudness, burn subs, mux.  Returns final QA audio metrics."""
    workdir = out.parent
    workdir.mkdir(parents=True, exist_ok=True)

    # 1) concat visuals
    silent_video = workdir / "_concat_silent.mp4"
    concat_clips(beat_clips, silent_video, resolution, fps)

    # 2) build audio mix
    mixed = workdir / "_mix.mp4"
    if narration and music:
        duck_music_under_narration(narration, music, mixed)
    elif narration:
        shutil.copy(narration, mixed)
    else:
        # no narration — silence so video/audio mux cleanly
        mixed = None

    # 3) master loudness
    mastered: Optional[Path] = None
    if mixed is not None:
        mastered = workdir / "_mastered.aac"
        normalize_to_target(mixed, mastered, TARGET_LUFS)
    else:
        # generate silent audio track of correct duration
        dur = _probe_duration(silent_video)
        silent = workdir / "_silence.aac"
        subprocess.run([
            ffmpeg(), "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
            "-t", str(dur), "-c:a", "aac", str(silent),
        ], check=True, capture_output=True)
        mastered = silent

    # 4) burn subtitles (if provided)
    if subtitles and subtitles.exists():
        burned = workdir / "_burned.mp4"
        burn_subtitles(silent_video, subtitles, burned)
        video_with_v = burned
    else:
        video_with_v = silent_video

    # 5) final mux: video + mastered audio (pad audio to video length so a
    #    shorter narration never truncates the visuals, §21 voice-dominant)
    final = workdir / "final.mp4" if out.name == "final.mp4" else out
    vid_dur = _probe_duration(video_with_v)
    subprocess.run([
        ffmpeg(), "-y", "-i", str(video_with_v), "-i", str(mastered),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-af", "apad", "-t", str(vid_dur),
        str(final),
    ], check=True, capture_output=True)

    # 6) audio QA metrics on final
    audio_metrics = measure_loudness(final)

    if final.resolve() != out.resolve():
        shutil.move(str(final), str(out))

    return {"audio": audio_metrics, "path": str(out)}


def _probe_duration(video: Path) -> float:
    cmd = [
        ffmpeg(), "-i", str(video), "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dur = 0.0
    for line in proc.stderr.splitlines():
        if "Duration:" in line:
            ts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = ts.split(":")
            dur = int(h) * 3600 + int(m) * 60 + float(s)
            break
    return dur or 10.0


def generate_srt(entries: list[dict], out: Path) -> Path:
    """Write SRT from [{start, end, text}]."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    def _fmt(t: float) -> str:
        ms = int((t - int(t)) * 1000)
        s = int(t) % 60
        m = (int(t) // 60) % 60
        h = int(t) // 3600
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{_fmt(e['start'])} --> {_fmt(e['end'])}")
        lines.append(e["text"])
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


if __name__ == "__main__":
    print("compositor ffmpeg:", ffmpeg())
    print("target LUFS:", TARGET_LUFS)
