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

Delivery spec (hard-enforced): H.264 video @ requested resolution/fps +
AAC audio @ 48000 Hz STEREO (2ch).  The narration is converted to stereo
48 kHz on ingest; every audio encode step forces `-ar 48000 -ac 2`.
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
AUDIO_SR = 48000     # delivery sample rate (AAC)
AUDIO_CH = 2         # delivery channels (stereo)

# freeze the pad fallback: pad with BLACK frames (tpad stop_mode=add), never
# clone the last frame — a frozen frame is unacceptable for an explainer.
PAD_MODE = "add"


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


def _convert_narration_to_mix(narration: Path, out_aac: Path) -> Path:
    """Ingest narration as 48 kHz stereo AAC (mono wav from TTS -> stereo)."""
    out = Path(out_aac)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg(), "-y", "-i", str(narration),
        "-af", f"aresample={AUDIO_SR},pan=stereo|c0=c0|c1=c0",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SR), "-ac", str(AUDIO_CH),
        str(out),
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
    target loudness, burn subs, mux.  Returns final QA audio metrics.

    Video duration is designed to match narration: the CLI sizes beats around
    narration before rendering, so this path normally never pads.  If the
    narration STILL runs longer than the video, the video is extended with
    BLACK frames (not a frozen clone) so the voice is never cut and there is
    no frozen tail.
    """
    workdir = out.parent
    workdir.mkdir(parents=True, exist_ok=True)

    # 1) concat visuals
    silent_video = workdir / "_concat_silent.mp4"
    concat_clips(beat_clips, silent_video, resolution, fps)

    # 2) build audio mix — ALWAYS 48 kHz stereo AAC
    mixed: Optional[Path] = None
    if narration and Path(narration).exists():
        if music and Path(music).exists():
            mixed = workdir / "_mix.aac"
            duck_music_under_narration(narration, music, mixed)
        else:
            mixed = _convert_narration_to_mix(narration, workdir / "_mix.aac")
    elif music and Path(music).exists():
        mixed = workdir / "_mix.aac"
        subprocess.run([
            ffmpeg(), "-y", "-i", str(music),
            "-af", f"aresample={AUDIO_SR},pan=stereo|c0=c0|c1=c0",
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SR), "-ac", str(AUDIO_CH),
            str(mixed),
        ], check=True, capture_output=True)

    # 3) master loudness (also forced 48 kHz stereo)
    mastered: Optional[Path] = None
    if mixed is not None:
        mastered = workdir / "_mastered.aac"
        normalize_to_target(mixed, mastered, TARGET_LUFS)
    else:
        dur = _probe_duration(silent_video)
        mastered = workdir / "_silence.aac"
        subprocess.run([
            ffmpeg(), "-y", "-f", "lavfi", "-i",
            f"anullsrc=r={AUDIO_SR}:cl=stereo",
            "-t", str(dur), "-c:a", "aac", "-ar", str(AUDIO_SR), "-ac", str(AUDIO_CH),
            str(mastered),
        ], check=True, capture_output=True)

    # 4) burn subtitles (if provided)
    if subtitles and subtitles.exists():
        burned = workdir / "_burned.mp4"
        burn_subtitles(silent_video, subtitles, burned)
        video_with_v = burned
    else:
        video_with_v = silent_video

    # 5) final mux: video + mastered audio.  Voice-dominant (§21): narration
    #    is never truncated.  If narration is LONGER than the video, extend
    #    the video with black frames (pad_mode=add) — NO frozen last frame.
    final = workdir / "final.mp4" if out.name == "final.mp4" else out
    vid_dur = _probe_duration(video_with_v)
    nar_dur = _probe_duration(mastered) if mastered is not None else 0.0
    final_dur = max(vid_dur, nar_dur + 0.2)
    vf_args: list[str] = []
    vcodec_args = ["-c:v", "copy"]
    pad_dur = 0.0
    if final_dur > vid_dur + 0.05:
        pad_dur = final_dur - vid_dur
        # black tail, not a frozen clone: tpad stop_mode=add
        vf_args = ["-vf", f"tpad=stop_mode={PAD_MODE}:stop_duration={pad_dur:.2f}"]
        vcodec_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
                       "-pix_fmt", "yuv420p"]
    subprocess.run([
        ffmpeg(), "-y", "-i", str(video_with_v), "-i", str(mastered),
        "-map", "0:v:0", "-map", "1:a:0",
        *vcodec_args,
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SR), "-ac", str(AUDIO_CH),
        "-af", "apad", "-t", str(final_dur),
        *vf_args,
        str(final),
    ], check=True, capture_output=True)

    # 6) audio QA metrics on final
    audio_metrics = measure_loudness(final)

    if final.resolve() != out.resolve():
        shutil.move(str(final), str(out))

    return {"audio": audio_metrics, "path": str(out),
            "video_duration_s": vid_dur, "narration_duration_s": nar_dur,
            "final_duration_s": final_dur, "padded_video_s": round(pad_dur, 2)}


def build_contact_sheet(video_path: Path, out_jpg: Path,
                        cols: int = 6, rows: int = 3,
                        thumb_w: int = 320, fps: int = 30) -> Path:
    """Sample N frames from the video and tile them into a contact-sheet
    JPEG for visual QA inspection (ffmpeg tile filter).

    Samples ~cols*rows frames evenly across the clip.
    """
    out = Path(out_jpg)
    out.parent.mkdir(parents=True, exist_ok=True)
    dur = _probe_duration(video_path)
    n = cols * rows
    total_frames = max(1, int(round(dur * fps)))
    intv = max(1, total_frames // n)
    cmd = [
        ffmpeg(), "-y", "-i", str(video_path),
        "-vf",
        f"select='not(mod(n\\,{intv}))',scale={thumb_w}:-2,tile={cols}x{rows}",
        "-frames:v", "1", "-q:v", "3", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _probe_duration(video: Path) -> float:
    """Real duration from ffprobe (falls back to ffmpeg -i parse)."""
    probe = shutil.which("ffprobe")
    if probe:
        try:
            proc = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
                capture_output=True, text=True, timeout=30)
            return float(proc.stdout.strip())
        except (ValueError, subprocess.SubprocessError):
            pass
    cmd = [ffmpeg(), "-i", str(video), "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    for line in proc.stderr.splitlines():
        if "Duration:" in line:
            ts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = ts.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 10.0


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
    print("delivery audio:", AUDIO_SR, "Hz", AUDIO_CH, "ch")
