"""technical.py — Technical shot QA gates (directive §19 technical).

ffprobe-based gates: codec, resolution, fps, duration vs plan (±0.3s),
black-frame detection (ffmpeg blackdetect), silence detection for
audio-bearing shots, decode integrity. No network, fully deterministic.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DURATION_TOLERANCE_SEC = 0.3
FPS_TARGET = 30.0
FPS_TOLERANCE = 1.0
BLACK_FRACTION_MAX = 0.5
SILENCE_FRACTION_MAX = 0.9
# Mean-chroma deviation from neutral (128) that counts as a uniform cast —
# r5 shipped S23/S24 at U≈75/V≈78 (green monochrome) unnoticed.
CHROMA_CAST_LIMIT = 25.0


class FFProbeError(RuntimeError):
    pass


def ffprobe(path: str | Path) -> dict:
    """ffprobe JSON for a media file (video stream + format)."""
    exe = shutil.which("ffprobe")
    if not exe:
        raise FFProbeError("ffprobe not found")
    out = subprocess.run(
        [exe, "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", str(path)],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise FFProbeError(f"ffprobe failed for {path}: {out.stderr[:200]}")
    info = json.loads(out.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return {
        "video": video,
        "audio": audio,
        "format": info.get("format", {}),
        "duration": _float(info.get("format", {}).get("duration")),
        "nb_streams": len(streams),
    }


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def black_stats(path: str | Path, duration: float | None = None) -> dict:
    """Total black time + longest black run via ffmpeg blackdetect."""
    if duration is None:
        duration = ffprobe(path).get("duration") or 0.0
    exe = shutil.which("ffmpeg")
    proc = subprocess.run(
        [exe, "-hide_banner", "-i", str(path),
         "-vf", "blackdetect=d=0.05:pix_th=0.10", "-an",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    total = 0.0
    longest = 0.0
    for line in proc.stderr.splitlines():
        if "black_start" not in line:
            continue
        try:
            seg = line.split("black_start:")[1]
            start = _float(seg.split("black_end:")[0].strip()) or 0.0
            end = _float(seg.split("black_end:")[1]
                         .split("black_duration:")[0].strip()) or 0.0
            run = max(end - start, 0.0)
            total += run
            longest = max(longest, run)
        except (IndexError, ValueError):
            continue
    frac = total / duration if duration else 0.0
    return {"black_total": round(total, 3), "longest_run": round(longest, 3),
            "fraction": round(frac, 4)}


def silence_stats(path: str | Path, duration: float | None = None) -> dict:
    """Total silence via ffmpeg silencedetect (audio-bearing shots only)."""
    if duration is None:
        duration = ffprobe(path).get("duration") or 0.0
    exe = shutil.which("ffmpeg")
    proc = subprocess.run(
        [exe, "-hide_banner", "-i", str(path),
         "-af", "silencedetect=noise=-40dB:d=0.5", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    total = 0.0
    prev_start = None
    for line in proc.stderr.splitlines():
        if "silence_start" in line:
            try:
                prev_start = _float(line.split("silence_start:")[1]
                                    .split()[0].strip())
            except (IndexError, ValueError):
                prev_start = None
        elif "silence_end" in line and prev_start is not None:
            try:
                end = _float(line.split("silence_end:")[1].split()[0].strip())
                total += max(end - prev_start, 0.0)
            except (IndexError, ValueError):
                pass
            prev_start = None
    frac = total / duration if duration else 0.0
    return {"silence_total": round(total, 3),
            "fraction": round(frac, 4)}


def chroma_stats(path: str | Path) -> dict:
    """Mean chroma (U/V) over a clip/still — detects uniform color casts.

    Neutral chroma is 128; a whole-frame green cast (the r5 S23/S24
    green-screen-bleed class) shows both channels depressed together.
    """
    exe = shutil.which("ffprobe") or "ffprobe"
    src = Path(path).resolve()
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-f", "lavfi",
             "-i", f"movie={src},signalstats",
             "-show_entries",
             "frame_tags=lavfi.signalstats.UAVG,lavfi.signalstats.VAVG",
             "-of", "csv=p=0"],
            capture_output=True, text=True, timeout=120)
        us: list[float] = []
        vs: list[float] = []
        for line in proc.stdout.splitlines():
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    us.append(float(parts[0]))
                    vs.append(float(parts[1]))
                except ValueError:
                    continue
        if not us:
            return {"available": False}
        u = sum(us) / len(us)
        v = sum(vs) / len(vs)
        return {"available": True, "u": round(u, 1), "v": round(v, 1),
                "frames": len(us),
                "cast": max(abs(u - 128.0), abs(v - 128.0))
                > CHROMA_CAST_LIMIT}
    except Exception:  # noqa: BLE001 — a probe must never break QA
        return {"available": False}


def decode_errors(path: str | Path) -> int:
    """Count decode errors (file integrity)."""
    exe = shutil.which("ffmpeg")
    proc = subprocess.run(
        [exe, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    return len([ln for ln in proc.stderr.splitlines() if ln.strip()])


def technical_qa(path: str | Path, expected_duration: float, *,
                 expect_audio: bool = False, fps: float = FPS_TARGET,
                 min_height: int = 0) -> dict:
    """Run all technical gates on one shot file.

    Returns {"pass", "issues", "gates": {...}, "probe": {...}}.
    """
    p = Path(path)
    issues: list[str] = []
    gates: dict[str, dict] = {}

    def gate(name: str, ok: bool, detail: str) -> None:
        gates[name] = {"pass": bool(ok), "detail": detail}
        if not ok:
            issues.append(f"{name}: {detail}")

    if not p.exists() or p.stat().st_size == 0:
        gate("exists", False, f"missing or empty file: {p.name}")
        return {"pass": False, "issues": issues, "gates": gates, "probe": {}}

    try:
        probe = ffprobe(p)
    except FFProbeError as exc:
        gate("probe", False, str(exc))
        return {"pass": False, "issues": issues, "gates": gates, "probe": {}}

    video = probe.get("video") or {}
    dur = probe.get("duration") or 0.0

    # Codec compatibility (YouTube: H.264).
    codec = video.get("codec_name")
    gate("codec", codec == "h264", f"codec={codec}")

    # fps.
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        measured_fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        measured_fps = 0.0
    gate("fps", abs(measured_fps - fps) <= FPS_TOLERANCE,
         f"fps={measured_fps:.2f} target={fps}")

    # Resolution.
    w = int(video.get("width") or 0)
    h = int(video.get("height") or 0)
    gate("resolution", h >= min_height and w > 0,
         f"{w}x{h} (min_height={min_height})")

    # Duration vs plan ±0.3s.
    gate("duration", dur > 0 and abs(dur - expected_duration)
         <= DURATION_TOLERANCE_SEC,
         f"duration={dur:.2f}s expected={expected_duration:.2f}s")

    # Black frames.
    blacks = black_stats(p, dur)
    gate("black_frames", blacks["fraction"] <= BLACK_FRACTION_MAX,
         f"black {blacks['fraction'] * 100:.1f}% "
         f"(longest {blacks['longest_run']}s)")

    # Uniform color cast (r5 S23/S24 green-bleed class).
    chroma = chroma_stats(p)
    if chroma.get("available"):
        gate("color_cast", not chroma["cast"],
             f"mean chroma U={chroma['u']} V={chroma['v']} "
             f"(cast limit ±{CHROMA_CAST_LIMIT})")

    # Silence (audio-bearing shots only — v3 shots are silent by design).
    if expect_audio:
        probe_audio = probe.get("audio")
        gate("audio_stream", probe_audio is not None,
             "audio stream presence")
        sil = silence_stats(p, dur)
        gate("silence", sil["fraction"] <= SILENCE_FRACTION_MAX,
             f"silence {sil['fraction'] * 100:.1f}%")

    # File integrity.
    errs = decode_errors(p)
    gate("integrity", errs == 0, f"{errs} decode errors")

    return {
        "pass": not issues,
        "issues": issues,
        "gates": gates,
        "probe": {
            "codec": codec, "width": w, "height": h,
            "fps": round(measured_fps, 3), "duration": round(dur, 3),
            "bytes": p.stat().st_size,
            "has_audio": probe.get("audio") is not None,
        },
    }
