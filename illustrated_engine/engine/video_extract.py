"""Frame sampling helper (V3) — evenly-spaced frames from a rendered video."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def sample_frames(video_path: Path, n: int = 6) -> list:
    """Return n evenly-spaced PIL RGB frames from video_path."""
    video_path = Path(video_path)
    tmp = Path(tempfile.mkdtemp(prefix="vframes_"))
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video_path)],
        check=True, capture_output=True, text=True).stdout.strip())
    out = []
    for i in range(n):
        t = (i + 0.5) / n * dur
        p = tmp / f"f{i}.png"
        for _attempt in range(3):  # ffmpeg can exit 0 with no frame under load
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}",
                            "-i", str(video_path), "-frames:v", "1", str(p)],
                           check=True)
            if p.exists():
                break
        out.append(Image.open(p).convert("RGB"))
    return out
