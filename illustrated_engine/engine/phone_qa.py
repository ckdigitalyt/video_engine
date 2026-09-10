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


def _frames_at(video_path: Path, times: list) -> list:
    """Deterministic frame pulls at event times."""
    import io
    out = []
    for t in times:
        p2 = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0.05, t):.2f}",
             "-i", str(video_path), "-frames:v", "1",
             "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True)
        if p2.returncode == 0 and p2.stdout:
            try:
                out.append(Image.open(io.BytesIO(p2.stdout)).convert("RGB"))
            except Exception:
                continue
    return out


def _accent_span(img, rect=None, target=(360, 640)) -> int:
    """Tallest accent(rust)-pixel row span in a frame (optionally cropped to a
    fractional rect) after phone-scale resize. 0 if no accent pixels."""
    ph = img.resize(target, Image.LANCZOS)
    if rect:
        x0 = int(rect[0] * target[0]); y0 = int(rect[1] * target[1])
        x1 = int((rect[0] + rect[2]) * target[0]); y1 = int((rect[1] + rect[3]) * target[1])
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(target[0], x1), min(target[1], y1)
        if x1 <= x0 or y1 <= y0:
            return 0
        arr = np.asarray(ph.crop((x0, y0, x1, y1)))
    else:
        arr = np.asarray(ph)
    mask = ((arr[..., 0].astype(int) > 140)
            & (arr[..., 1].astype(int) < 130)
            & (arr[..., 2].astype(int) < 110))
    if not mask.any():
        return 0
    ys = np.where(mask.any(axis=1))[0]
    # Longest contiguous run (gap <= 3 rows): first-to-last extent bridges
    # incidental accent-colored plate art and overstates real text height
    # (evidence 2026-09-04: green_sahara S03 "49px" was text sliver + art).
    runs = []
    start = prev = int(ys[0])
    for y in ys[1:]:
        y = int(y)
        if y - prev > 3:
            runs.append(prev - start + 1)
            start = y
        prev = y
    runs.append(prev - start + 1)
    return int(max(runs))


def _zone_rect(rect):
    """Plan rects are visual-zone relative (layout.VISUAL_RECT = y 176-1504 of
    the 1920 frame) — same transform composev2._abs_rect applies when drawing.
    Evidence 2026-09-04: raw-fraction probes sat ~20 phone-px below the real
    glyphs (green_sahara pops measured at phone-y 262-293) -> false P0.
    V10 — under the native 9:16 pass the plan card is the portrait panel
    (planv5 CARD_Y0=288, CARD_H=1152), not the legacy visual zone; map card
    fractions through the active geometry (evidence 2026-09-10: ice_slippery
    S06 pop drawn at frame-y 587-714 = 288+0.26*1152, legacy mapping probed
    y 520-666 -> key_number_px=0 false P0)."""
    from engine import flags as _flags
    x, y, w, h = rect
    if _flags.vertical10():
        from engine.planv5 import CARD_H, CARD_Y0
        return (x, (CARD_Y0 + y * CARD_H) / 1920.0,
                w, (h * CARD_H) / 1920.0)
    from engine.layout import VISUAL_RECT
    vx, vy, vw, vh = VISUAL_RECT
    return ((vx + x * vw) / 1080.0, (vy + y * vh) / 1920.0,
            (w * vw) / 1080.0, (h * vh) / 1920.0)


def phone_legibility(video_path: Path, caption_y_range=(1500, 1860),
                     key_number_min_height_px: int = 12,
                     plan_shots: list = None,
                     stage_pngs: list = None) -> dict:
    """Phone-scale QA (360x640): is every key number readable?

    V4: key numbers are (a) number pops rendered inside their plan rects and
    (b) big numbers on programmatic diagram cards. Pops are probed AT their
    event times inside their actual rects (even sampling misses 2.6 s pops);
    diagram cards are measured directly from the rendered stage frames.
    readable = caption band >= 80px AND every pop >= 12px AND every diagram
    key number >= 12px at phone scale."""
    target_w, target_h = 360, 640
    scale_y = target_h / 1920.0
    cap_cy0 = int(caption_y_range[0] * scale_y)
    cap_cy1 = int(caption_y_range[1] * scale_y)
    caption_band_px = cap_cy1 - cap_cy0

    pop_heights, probes = [], []
    if plan_shots:
        acc = 0.0
        for s in plan_shots:
            dur = float(s.get("duration_s", 4.0))
            for e in s.get("events", []) or []:
                if str(e.get("kind", "")).lower() == "number_pop":
                    rect = (e.get("spec") or {}).get("rect")
                    if rect:
                        probes.append((acc + float(e.get("t", 0.0)) + 0.5,
                                       _zone_rect(rect)))
            acc += dur
    if probes:
        frames = _frames_at(Path(video_path), [t for t, _ in probes])
        for (t, rect), fr in zip(probes, frames):
            if fr is not None:
                h = _accent_span(fr, rect=rect, target=(target_w, target_h))
                if h:
                    pop_heights.append(h)

    diag_heights = []
    for sp in (stage_pngs or []):
        try:
            img = Image.open(sp).convert("RGB")
        except Exception:
            continue
        h = _accent_span(img, rect=(0, 176.0 / 1920.0, 1.0, 1744.0 / 1920.0),
                         target=(target_w, target_h))
        if h:
            diag_heights.append({"asset": Path(sp).name, "px": h})

    kn_min_h = min(pop_heights) if pop_heights else 0
    diag_min_h = min(d["px"] for d in diag_heights) if diag_heights else 0
    readable = (caption_band_px >= 80 and kn_min_h >= key_number_min_height_px
                and (diag_min_h >= key_number_min_height_px or not diag_heights))
    return {
        "phone_size": [target_w, target_h],
        "caption_band_px": caption_band_px,
        "key_number_px": kn_min_h,
        "pop_heights": pop_heights,
        "probes": len(probes),
        "diagram_key_number_px": diag_min_h,
        "diagram_heights": diag_heights,
        "key_number_min_height_px": key_number_min_height_px,
        "readable": bool(readable),
    }
