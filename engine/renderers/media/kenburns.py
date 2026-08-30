"""kenburns.py — Deterministic ffmpeg procedural motion for stills (§12).

AI_IMAGE → MOTION path: a still image becomes a shot via ffmpeg zoompan
(Ken Burns), optional 2-layer parallax (foreground/background overlay with
different zoom rates) and a subtle atmospheric pass (slow-brightness pulse).
Everything derives from a hash of (prompt, seed, duration, aspect, fps) so
identical inputs produce byte-identical motion — no randomness, no LLM.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


class KenBurnsError(RuntimeError):
    """ffmpeg motion generation failed."""


@dataclass
class MotionPlan:
    """Resolved motion parameters for one shot."""

    direction: str          # in | out | left | right | up | down
    zoom_start: float
    zoom_end: float
    pan_x: float            # -1..1 normalized drift across the clip
    pan_y: float
    parallax: bool
    atmosphere: bool


def motion_plan(prompt: str, seed: int, duration: float, aspect: str,
                parallax: bool = False, atmosphere: bool = False) -> MotionPlan:
    """Derive a deterministic motion plan from the shot inputs.

    Same (prompt, seed, duration, aspect) → same plan, every run/process.
    """
    digest = hashlib.sha256(
        f"{prompt}|{seed}|{duration:.3f}|{aspect}".encode("utf-8")
    ).digest()
    word = int.from_bytes(digest[:4], "big")
    direction = ("in", "out", "left", "right", "up", "down")[word % 6]
    # Zoom range 1.0→1.18 .. 1.0→1.35 (or reversed for "out").
    zoom_span = 1.18 + (digest[4] % 18) / 100.0
    zoom_start = 1.0
    zoom_end = zoom_span
    if direction == "out":
        zoom_start, zoom_end = zoom_end, zoom_start
        direction = "in"  # zoompan only needs the span; pan carries direction
    pan_x = ((digest[5] / 255.0) * 2 - 1) * 0.04
    pan_y = ((digest[6] / 255.0) * 2 - 1) * 0.04
    if direction == "left":
        pan_x, pan_y = -0.06, 0.0
    elif direction == "right":
        pan_x, pan_y = 0.06, 0.0
    elif direction == "up":
        pan_x, pan_y = 0.0, -0.06
    elif direction == "down":
        pan_x, pan_y = 0.0, 0.06
    return MotionPlan(
        direction=direction,
        zoom_start=zoom_start,
        zoom_end=zoom_end,
        pan_x=pan_x,
        pan_y=pan_y,
        parallax=parallax,
        atmosphere=atmosphere,
    )


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise KenBurnsError(f"ffmpeg failed ({proc.returncode}): {tail}")


def _upscale_to(src: Path, dst: Path, width: int, height: int) -> None:
    """Upscale the still well past output size so zoompan never hits edges."""
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
               f"crop={width * 2}:{height * 2}",
        "-frames:v", "1", str(dst),
    ])


def _zoompan_filter(plan: MotionPlan, width: int, height: int, fps: int,
                    duration: float, zoom_rate: float = 1.0) -> str:
    frames = max(1, int(round(duration * fps)))
    z0, z1 = plan.zoom_start, min(plan.zoom_end * zoom_rate, 1.5)
    dz = (z1 - z0) / frames
    # Center anchor with slight drift; x/y in input pixels via on-the-fly expr.
    px, py = plan.pan_x, plan.pan_y
    return (
        f"zoompan=z='{z0}+{dz:.8f}*on':"
        f"x='iw/2-(iw/zoom/2)+{px}*iw*on/{frames}':"
        f"y='ih/2-(ih/zoom/2)+{py}*ih*on/{frames}':"
        f"d={frames}:s={width}x{height}:fps={fps}"
    )


def render_kenburns(
    still: str | Path,
    out_path: str | Path,
    *,
    duration: float,
    aspect: str = "16:9",
    fps: int = 30,
    plan: MotionPlan | None = None,
    foreground: str | Path | None = None,
    prompt: str = "",
    seed: int = 0,
    crf: int = 20,
) -> Path:
    """Encode a still into an H.264 silent mp4 with Ken Burns motion.

    With *foreground* provided, a 2-layer parallax is built: background zooms
    at base rate, foreground layer (PNG with alpha) zooms ~1.35x faster,
    composited via overlay. With ``plan.atmosphere`` a subtle brightness
    pulse adds life. Deterministic end to end.
    """
    src = Path(still)
    if not src.exists():
        raise KenBurnsError(f"still not found: {src}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["16:9"])
    plan = plan or motion_plan(prompt, seed, duration, aspect)

    work = out.parent / f".kb_{out.stem}_work"
    work.mkdir(parents=True, exist_ok=True)
    try:
        bg = work / "bg.png"
        _upscale_to(src, bg, width, height)

        fg_layer: Path | None = None
        if plan.parallax and foreground and Path(foreground).exists():
            fg_layer = work / "fg.png"
            _upscale_to(Path(foreground), fg_layer, width, height)

        frames = max(1, int(round(duration * fps)))
        atmos = (
            f",eq=brightness='0.015*sin(2*PI*n/{max(frames, 1)})':eval=frame"
            if plan.atmosphere
            else ""
        )

        if fg_layer is not None:
            # Parallax: background (base zoom) + foreground (faster zoom),
            # scaled slightly smaller over time → depth separation.
            bg_filt = _zoompan_filter(plan, width, height, fps, duration)
            fg_plan = MotionPlan(
                direction=plan.direction, zoom_start=plan.zoom_start,
                zoom_end=plan.zoom_end, pan_x=plan.pan_x * 1.6,
                pan_y=plan.pan_y * 1.6, parallax=False, atmosphere=False,
            )
            fg_filt = _zoompan_filter(fg_plan, width, height, fps, duration,
                                      zoom_rate=1.35)
            graph = (
                f"[0:v]{bg_filt}[bg];"
                f"[1:v]{fg_filt},format=rgba[fg];"
                f"[bg][fg]overlay=0:0{atmos},format=yuv420p[v]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(bg),
                "-i", str(fg_layer),
                "-filter_complex", graph, "-map", "[v]",
                "-r", str(fps), "-c:v", "libx264", "-crf", str(crf),
                "-preset", "medium", "-pix_fmt", "yuv420p",
                str(out),
            ]
        else:
            filt = _zoompan_filter(plan, width, height, fps, duration) + atmos
            cmd = [
                "ffmpeg", "-y",
                "-i", str(bg),
                "-vf", filt + ",format=yuv420p",
                "-r", str(fps), "-c:v", "libx264", "-crf", str(crf),
                "-preset", "medium", str(out),
            ]
        _run(cmd)
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
    return out
