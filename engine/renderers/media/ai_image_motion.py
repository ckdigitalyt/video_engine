"""ai_image_motion.py — AI_IMAGE → MOTION renderer body (directive §12).

Generates (or receives) an AI still via the AI Media Broker, then applies
deterministic procedural motion: ffmpeg zoompan Ken Burns, optional 2-layer
parallax (foreground/background split) and a subtle atmospheric brightness
pulse. Offline smoke path: when the broker has no image provider configured,
the renderer falls back to a locally generated solid/gradient PNG so the
motion pipeline itself is always verifiable offline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engine.renderers.base import (
    RenderContext,
    Renderer,
    RendererCapability,
    ShotRenderResult,
)

logger = logging.getLogger(__name__)


def make_solid_still(out_path: Path, width: int = 1280, height: int = 720,
                     color: str = "0x1a2a4a") -> Path:
    """Offline-safe deterministic test still (solid colour PNG)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c={color}:s={width}x{height}",
         "-frames:v", "1", str(out_path)],
        capture_output=True, timeout=60, check=True,
    )
    return out_path


class AIImageMotionRenderer(Renderer):
    """AI still + procedural motion (§12 path, AI_IMAGE_MOTION id)."""

    id = "AI_IMAGE_MOTION"

    def __init__(self, capability: RendererCapability | None = None,
                 broker: Any | None = None) -> None:
        self._capability = capability
        self._broker = broker

    def capabilities(self) -> RendererCapability:
        from engine.renderers.registry import get_capability

        return self._capability or get_capability(self.id)

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        issues: list[str] = []
        if not isinstance(shot, dict):
            return ["shot must be a dict"]
        if shot.get("renderer") not in (None, self.id):
            issues.append(f"shot.renderer is {shot.get('renderer')!r}, not {self.id!r}")
        if not shot.get("duration_sec"):
            issues.append("missing required shot field: duration_sec")
        prompt = shot.get("subject") or shot.get("visual_goal")
        if not prompt:
            issues.append("AI_IMAGE_MOTION needs subject or visual_goal as image prompt")
        return issues

    def _broker_instance(self) -> Any:
        if self._broker is not None:
            return self._broker
        from engine.broker.broker import MediaBroker

        self._broker = MediaBroker()
        return self._broker

    def render(self, shot: dict, style: dict | None, ctx: RenderContext) -> ShotRenderResult:
        issues = self.validate(shot, style)
        if issues:
            raise ValueError(f"AI_IMAGE_MOTION validate failed: {'; '.join(issues)}")

        from engine.renderers.media.kenburns import (
            motion_plan,
            render_kenburns,
        )
        from engine.v4.microevents import derive_micro_events
        from engine.v4.motion_toolkit import kenburns_ops, micro_event_ops

        out_dir = Path(ctx.output_dir)
        shot_id = shot.get("shot_id", "shot")
        duration = float(shot.get("duration_sec", 4.0))
        prompt = shot.get("subject") or shot.get("visual_goal") or ""
        seed = int(ctx.seed or shot.get("seed", 0) or 0)
        motion_cfg = shot.get("motion") or {}
        if isinstance(motion_cfg, str):
            motion_cfg = {}
        want_parallax = bool(motion_cfg.get("parallax"))
        want_atmos = bool(motion_cfg.get("atmosphere", True))

        still: Path | None = None
        foreground: Path | None = None
        provider_note = "offline_solid"
        # Explicit still provided (offline / pre-generated path).
        inline_still = (shot.get("asset_requirements") or {}).get("still_path") \
            if isinstance(shot.get("asset_requirements"), dict) else None
        if inline_still and Path(inline_still).exists():
            still = Path(inline_still)
            provider_note = "provided_still"
        else:
            try:
                result = self._broker_instance().generate_image(
                    prompt, style=style, aspect=ctx.aspect, seed=seed,
                    renderer_version="w2_ai_image_motion",
                )
                still = Path(result.path)
                provider_note = result.provider
            except Exception as exc:  # broker down → offline fallback still
                logger.warning("AI_IMAGE_MOTION: broker image failed (%s); "
                               "using offline solid still", exc)
                still = make_solid_still(
                    out_dir / f"{shot_id}_fallback_still.png",
                    color=f"0x{seed % 0xFFFFFF:06x}",
                )
            if want_parallax:
                # 2-layer parallax: generate a distinct foreground plate.
                try:
                    fg = self._broker_instance().generate_image(
                        f"{prompt}, foreground subject layer, isolated on plain "
                        f"background, centered",
                        style=style, aspect=ctx.aspect, seed=seed + 1,
                        renderer_version="w2_ai_image_motion",
                    )
                    foreground = Path(fg.path)
                except Exception as exc:
                    logger.warning("AI_IMAGE_MOTION: parallax fg layer failed "
                                   "(%s); rendering flat Ken Burns", exc)
                    want_parallax = False

        plan = motion_plan(prompt, seed, duration, ctx.aspect,
                           parallax=want_parallax, atmosphere=want_atmos)
        # V4 §4/§15/§16: implement the shot's micro events as REAL discrete
        # perceptual events via the motion toolkit — exposure/grade steps,
        # camera-accel zoom kicks, crop shakes and procedural overlay layers
        # (flock/rain/dust/silhouettes) composited over the Ken Burns base.
        # Shots without declared events get a deterministic derived timeline
        # so a still can never degrade to a 7s slide.
        micro = shot.get("micro_events") or derive_micro_events(shot)
        ops = micro_event_ops(micro, duration=duration, fps=ctx.fps,
                              seed=seed, subject=prompt,
                              fill_spacing=3.0)
        events = kenburns_ops(ops, duration=duration, fps=ctx.fps,
                              work_dir=out_dir / f"{shot_id}_toolkit")
        out_path = out_dir / f"{shot_id}_aivimgmotion.mp4"
        render_kenburns(
            still, out_path, duration=duration, aspect=ctx.aspect, fps=ctx.fps,
            plan=plan, foreground=foreground, prompt=prompt, seed=seed,
            events=events, overlays=events.get("overlays") or [],
        )

        # QA frames: first / middle / last.
        qa_frames = _extract_qa_frames(out_path, out_dir / f"{shot_id}_qa", ctx.fps)
        return ShotRenderResult(
            path=str(out_path),
            metadata={
                "renderer": self.id,
                "image_provider": provider_note,
                "motion": plan.direction,
                "parallax": plan.parallax and foreground is not None,
                "atmosphere": plan.atmosphere,
                "micro_events": len(micro),
                "event_ops": len(ops),
                "zoom_pulses": len(events["zoom"]),
                "brightness_pulses": len(events["brightness"]),
                "shake_events": len(events["shake"]),
                "overlay_layers": [o.get("kind") for o in
                                   events.get("overlays") or []],
                "duration_sec": duration,
            },
            qa_frames=[str(p) for p in qa_frames],
        )


def _extract_qa_frames(video: Path, prefix_dir: Path, fps: int) -> list[Path]:
    """First + last frame of the encoded clip (cheap vision-QA input)."""
    import subprocess

    prefix_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    try:
        first = prefix_dir / "frame_0.png"
        if subprocess.run(
            ["ffmpeg", "-y", "-i", str(video), "-frames:v", "1", str(first)],
            capture_output=True, timeout=60,
        ).returncode == 0 and first.exists():
            frames.append(first)
        last = prefix_dir / "frame_last.png"
        if subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video),
             "-update", "1", "-frames:v", "1", str(last)],
            capture_output=True, timeout=60,
        ).returncode == 0 and last.exists():
            frames.append(last)
    except Exception:
        pass
    return frames
