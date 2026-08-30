"""conform.py — ffmpeg normalization for external footage (§13).

Any stock/archival clip or image is conformed to the shot target: scaled and
center-cropped to the aspect size, trimmed to duration_sec, normalized to
constant fps, silent H.264 mp4. Deterministic given (input, duration, aspect,
fps).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from engine.renderers.media.kenburns import ASPECT_SIZES

SILENT_CODEC_ARGS = [
    "-an",  # strip audio: narration/music are mastered downstream (§18)
]


class ConformError(RuntimeError):
    """ffmpeg conform failed."""


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise ConformError(f"ffmpeg conform failed ({proc.returncode}): {tail}")


def conform_clip(
    src: str | Path,
    out_path: str | Path,
    *,
    duration: float,
    aspect: str = "16:9",
    fps: int = 30,
    crf: int = 20,
) -> Path:
    """Normalize *src* (video) to target aspect/duration/fps/codec."""
    src, out = Path(src), Path(out_path)
    if not src.exists():
        raise ConformError(f"source clip not found: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["16:9"])
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},format=yuv420p"
    )
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vf", vf, *SILENT_CODEC_ARGS,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        str(out),
    ])
    return out


def conform_image(
    src: str | Path,
    out_path: str | Path,
    *,
    duration: float,
    aspect: str = "16:9",
    fps: int = 30,
    crf: int = 20,
) -> Path:
    """Turn an archival still into a fixed clip (static frame, exact specs)."""
    src, out = Path(src), Path(out_path)
    if not src.exists():
        raise ConformError(f"source image not found: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["16:9"])
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},format=yuv420p"
    )
    _run([
        "ffmpeg", "-y", "-loop", "1", "-t", f"{duration:.3f}", "-i", str(src),
        "-vf", vf, *SILENT_CODEC_ARGS,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        str(out),
    ])
    return out
