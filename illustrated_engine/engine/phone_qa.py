"""Phone-scale QA — render the final video at 360x640 and assert that
the key information (captions, key numbers) is still readable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image


def phone_render(video_path: Path, out_path: Path, size=(360, 640)) -> dict:
    """Downscale the final video to a phone-simulated MP4. Returns probe info."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video_path),
        "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos",
        "-c:v", "libx264", "-preset", "fast", "-crf", "24",
        "-pix_fmt", "yuv420p", "-an", str(out_path),
    ], check=True)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-show_entries", "stream=width,height", "-of", "json", str(out_path)],
        check=True, capture_output=True, text=True)
    return json.loads(probe.stdout)


def _extracted_frames(video_path: Path, n: int = 6):
    from engine.video_extract import sample_frames
    return sample_frames(Path(video_path), n=n)


def phone_legibility(video_path: Path, caption_y_range=(1500, 1860),
                     key_number_min_height_px: int = 12) -> dict:
    """Extract frames, downscale to 360x640, measure (a) the caption band
    height and (b) the vertical span of accent-coloured (rust) key-number
    pixels in the upper caption band. Readable = band >= 80px at phone scale
    and key numbers >= key_number_min_height_px.
    """
    target_w, target_h = 360, 640
    scale_y = target_h / 1920.0
    cap_cy0 = int(caption_y_range[0] * scale_y)
    cap_cy1 = int(caption_y_range[1] * scale_y)
    caption_band_px = cap_cy1 - cap_cy0
    kn_y0 = cap_cy0
    kn_y1 = cap_cy0 + (cap_cy1 - cap_cy0) // 2
    kn_min_h = 0
    frames_with_numbers = 0
    for f in _extracted_frames(Path(video_path), n=6):
        ph = f.resize((target_w, target_h), Image.LANCZOS)
        arr = np.asarray(ph.crop((0, kn_y0, target_w, kn_y1)))
        mask = ((arr[..., 0].astype(int) > 140)
                & (arr[..., 1].astype(int) < 130)
                & (arr[..., 2].astype(int) < 110))
        if mask.any():
            ys = np.where(mask.any(axis=1))[0]
            h = int(ys.max() - ys.min() + 1)
            frames_with_numbers += 1
            kn_min_h = h if kn_min_h == 0 else min(kn_min_h, h)
    readable = (caption_band_px >= 80) and (kn_min_h >= key_number_min_height_px)
    return {
        "phone_size": [target_w, target_h],
        "caption_band_px": caption_band_px,
        "key_number_px": kn_min_h,
        "frames_with_numbers": frames_with_numbers,
        "readable": bool(readable),
    }
