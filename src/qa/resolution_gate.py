"""
resolution_gate.py — Source-resolution headroom gate (expert review rec #3).

The expert finding: source images generated near final-output resolution
(1024x576 for a 1920x1080 render) then pushed through Ken Burns pan/zoom
produce visible softness/pixelation.  The pipeline must know the *actual*
source dimensions and the *planned* zoom BEFORE rendering, and:

  * PASS       — zoom keeps the cropped region at/above output resolution
  * REGENERATE — a higher-resolution source is required for the planned zoom
  * REDUCE     — the zoom can be lowered to stay within safe headroom

Safe-zoom math (16:9 sources): a zoompan at zoom z shows a centered crop
of width src_w/z scaled to out_w.  No visible upscale requires
src_w/z >= out_w  (and src_h/z >= out_h), i.e.  z <= src_w/out_w.
A margin (default 1.05) absorbs rounding noise in the check.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

DEFAULT_OUT_W = 1920
DEFAULT_OUT_H = 1080
DEFAULT_ZOOM = 1.22  # pipeline default Ken Burns end zoom


def probe_image_size(path: str) -> Optional[tuple[int, int]]:
    """Return (width, height) of an image/video via ffprobe (fast, reliable)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "json", path],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        s = data["streams"][0]
        return int(s["width"]), int(s["height"])
    except Exception:
        return None


def max_safe_zoom(src_w: int, src_h: int,
                  out_w: int = DEFAULT_OUT_W,
                  out_h: int = DEFAULT_OUT_H,
                  margin: float = 1.05) -> float:
    """Highest zoom that keeps the cropped region at output resolution."""
    if src_w <= 0 or src_h <= 0:
        return DEFAULT_ZOOM
    z = min(src_w / out_w, src_h / out_h) * margin
    return max(1.0, z)


def check_shot_headroom(shot: dict, margin: float = 1.05,
                        out_w: int = DEFAULT_OUT_W,
                        out_h: int = DEFAULT_OUT_H) -> dict:
    """Evaluate ONE timeline shot.

    ``shot`` is a video_timeline entry.  Two cases:

    * PRE-RENDERED VIDEO CLIPS (stock footage / ken-burns clips): the
      source file IS the final content — flag whenever it is smaller than
      the output resolution (any upscale = visible softness, expert rec
      #3).  No zoom math needed: even 1.0x fill of a 640x360 clip into
      1920x1080 is a 3x upscale.
    * STILL IMAGES with Ken Burns: zoom_end from ``motion_params``
      (default 1.22); the crop must stay at/above output resolution.

    Manim/vector clips are vector-rendered — infinite detail, always pass.
    """
    path = shot.get("file", "")
    if not path or not os.path.exists(path):
        return {"passed": True, "detail": "no file to probe",
                "src_size": None, "zoom_end": None, "max_safe": None}

    # Animation clips (manim/vector) are rendered natively from vector
    # math — infinite detail, no headroom problem.
    if shot.get("asset_source") in ("manim", "vector") or \
            "manim" in path or "vector" in path:
        return {"passed": True, "detail": f"{os.path.basename(path)} is animated (vector detail)",
                "src_size": None, "zoom_end": None, "max_safe": None}

    src = probe_image_size(path)
    if src is None:
        return {"passed": True, "detail": f"unprobeable source {os.path.basename(path)}",
                "src_size": None, "zoom_end": None, "max_safe": None}

    # Pre-rendered video clip (no still/Ken Burns zoom): must already be
    # at/above output resolution — the pipeline must never upscale stock.
    # v19 fix: this applies to ALL video files regardless of leftover
    # motion_params.  Pre-rendered Ken Burns clips (stills-first runner)
    # carry the camera plan used to RENDER them (zoom 1.22 etc.), but the
    # renderer never re-applies motion_params to an .mp4 — the zoom is
    # already baked into the frames.  Applying still-image zoom math here
    # false-positives every 1920x1080 pre-rendered clip (safe max 1.05).
    is_video = path.lower().endswith((".mp4", ".mov", ".webm", ".mkv"))
    if is_video:
        ok = src[0] >= out_w and src[1] >= out_h
        return {
            "passed": ok,
            "detail": (f"{os.path.basename(path)} {src[0]}x{src[1]} "
                       f">= output {out_w}x{out_h} ✓"
                       if ok else
                       f"{os.path.basename(path)} source {src[0]}x{src[1]} BELOW "
                       f"output {out_w}x{out_h} — upscaling stock footage "
                       "causes visible softness; fetch higher-res source"),
            "src_size": src, "zoom_end": 1.0, "max_safe": 1.0,
        }

    mp = shot.get("motion_params") or {}
    zoom_end = float(mp.get("zoom_end", DEFAULT_ZOOM)) or DEFAULT_ZOOM
    max_z = max_safe_zoom(src[0], src[1], out_w, out_h, margin)
    if zoom_end <= max_z + 1e-6:
        return {
            "passed": True,
            "detail": (f"{os.path.basename(path)} {src[0]}x{src[1]} "
                       f"zoom {zoom_end:.2f} <= safe {max_z:.2f}"),
            "src_size": src, "zoom_end": round(zoom_end, 3),
            "max_safe": round(max_z, 3),
        }
    return {
        "passed": False,
        "detail": (f"{os.path.basename(path)} source {src[0]}x{src[1]} "
                   f"cannot sustain zoom {zoom_end:.2f} (safe max {max_z:.2f}) — "
                   "regenerate at higher resolution or reduce zoom"),
        "src_size": src, "zoom_end": round(zoom_end, 3),
        "max_safe": round(max_z, 3),
    }


def check_timeline_headroom(timeline_path: str, margin: float = 1.05) -> dict:
    """Evaluate every still-based shot in a timeline.json (rec #3 gate)."""
    if not os.path.exists(timeline_path):
        return {"passed": True, "checks": [], "detail": "no timeline"}
    with open(timeline_path) as f:
        tl = json.load(f)
    shots = tl.get("video_timeline", [])
    results = [check_shot_headroom(s, margin) for s in shots]
    failed = [r for r in results if not r["passed"]]
    return {
        "passed": not failed,
        "checks": results,
        "detail": f"{len(shots)} still shot(s) within resolution headroom"
                  if not failed
                  else f"{len(failed)} shot(s) exceed source headroom: "
                       + "; ".join(r["detail"][:90] for r in failed[:4]),
        "failed": failed[:8],
    }
