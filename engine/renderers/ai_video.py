"""ai_video.py — AI_VIDEO renderer body (directive §11).

Hero-shot renderer: text/image → AI video via the AI Media Broker's video
providers (Wan 2.2 I2V, LTX — free HF ZeroGPU Spaces; MiniMax H3 registered
but paid-disabled). Input strategy for a shot:
1. explicit ``asset_requirements.image_path`` (planner-provided keyframe), or
2. broker-generated keyframe (generate_image) when image providers are up,
3. else text-to-video via ``broker.generate_video`` when a kind="video"
   provider is available.

The broker handles cache-first, ordered failover and quota; this renderer
conforms the result to the shot (fps/duration) and emits QA frames.
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


class AIVideoRenderer(Renderer):
    """AI-generated video (HERO cost tier; remote GPU required)."""

    id = "AI_VIDEO"

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
        if not (shot.get("subject") or shot.get("visual_goal")):
            issues.append("AI_VIDEO needs subject or visual_goal as prompt")
        cap = self.capabilities()
        if shot.get("duration_sec") and cap.max_duration_sec:
            if shot["duration_sec"] > cap.max_duration_sec:
                issues.append(
                    f"duration {shot['duration_sec']}s exceeds AI_VIDEO max "
                    f"{cap.max_duration_sec}s")
        return issues

    def _broker_instance(self) -> Any:
        if self._broker is not None:
            return self._broker
        from engine.broker.broker import MediaBroker

        self._broker = MediaBroker()
        return self._broker

    def render(self, shot: dict, style: dict | None,
               ctx: RenderContext) -> ShotRenderResult:
        issues = self.validate(shot, style)
        if issues:
            raise ValueError(f"AI_VIDEO validate failed: {'; '.join(issues)}")

        from engine.renderers.media.conform import conform_clip

        out_dir = Path(ctx.output_dir)
        shot_id = shot.get("shot_id", "shot")
        duration = float(shot.get("duration_sec", 4.0))
        prompt = shot.get("subject") or shot.get("visual_goal") or ""
        seed = int(ctx.seed or shot.get("seed", 0) or 0)
        broker = self._broker_instance()

        # 1. Keyframe: explicit → generated → none (pure t2v).
        req = shot.get("asset_requirements") or {}
        keyframe: Path | None = None
        if isinstance(req, dict) and req.get("image_path"):
            keyframe = Path(req["image_path"])
        elif keyframe is None:
            try:
                img = broker.generate_image(
                    prompt, style=style, aspect=ctx.aspect, seed=seed,
                    renderer_version="w2_ai_video_keyframe")
                keyframe = Path(img.path)
                logger.info("AI_VIDEO %s: keyframe via %s", shot_id,
                            img.provider)
            except Exception as exc:
                logger.warning("AI_VIDEO %s: keyframe generation failed (%s)",
                               shot_id, exc)

        # 2. Generation: i2v with keyframe when available, else t2v.
        if keyframe is not None:
            result = broker.image_to_video(
                keyframe, prompt, duration=min(duration, 6.0),
                seed=seed, aspect=ctx.aspect)
        else:
            result = broker.generate_video(
                prompt, duration=min(duration, 6.0), aspect=ctx.aspect,
                seed=seed, style=style)

        # 3. Conform to exact shot specs (trim/extend to duration).
        out_path = out_dir / f"{shot_id}_aivideo.mp4"
        if abs(duration - _duration_of(result.path)) > 0.05:
            conform_clip(result.path, out_path, duration=duration,
                         aspect=ctx.aspect, fps=ctx.fps)
        else:
            import shutil

            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(result.path, out_path)

        return ShotRenderResult(
            path=str(out_path),
            metadata={
                "renderer": self.id,
                "provider": result.provider,
                "prompt": prompt,
                "keyframe": str(keyframe) if keyframe else None,
                "duration_sec": duration,
            },
            qa_frames=[],
        )


def _duration_of(path: str | Path) -> float:
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return -1.0
