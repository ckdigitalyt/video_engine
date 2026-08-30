"""Adapters wrapping the EXISTING renderers behind the formal Renderer
interface — no behavior change (Wave-1 rule).

- ManimRenderer: delegates to engine.renderers.manim.compiler.compile_to_file
  (VisualSpec v2 → deterministic scene file), exactly as the current engine
  uses it.
- MediaRenderer / VectorRenderer: the existing engine/renderers/media and
  engine/renderers/vector packages are placeholders; the adapters register
  them, validate shots, and their render() raises RendererNotImplemented
  until Wave 2 wires their bodies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.renderers.base import (
    RenderContext,
    Renderer,
    RendererCapability,
    RendererNotImplemented,
    ShotRenderResult,
)

_REQUIRED_SHOT_FIELDS = ("shot_id", "duration_sec", "visual_goal")


def _basic_shot_issues(shot: dict, renderer_id: str) -> list[str]:
    issues: list[str] = []
    if not isinstance(shot, dict):
        return ["shot must be a dict"]
    if shot.get("renderer") not in (None, renderer_id):
        issues.append(
            f"shot.renderer is {shot.get('renderer')!r}, not {renderer_id!r}"
        )
    for key in _REQUIRED_SHOT_FIELDS:
        if not shot.get(key):
            issues.append(f"missing required shot field: {key}")
    return issues


class ManimRenderer(Renderer):
    """Adapter around the existing VisualSpec → Manim compiler.

    The shot must carry its VisualSpec v2 document either inline
    (``shot["visualspec"]``) or via ``ctx.extra["visualspec"]``.  Compilation
    is delegated 1:1 to ``compile_to_file`` — identical output to the current
    engine, no behavior change.
    """

    id = "MANIM"

    def __init__(self, capability: RendererCapability | None = None) -> None:
        self._capability = capability

    def capabilities(self) -> RendererCapability:
        from engine.renderers.registry import get_capability

        return self._capability or get_capability(self.id)

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        issues = _basic_shot_issues(shot, self.id)
        vs = shot.get("visualspec")
        if vs is None:
            issues.append("MANIM requires a VisualSpec v2 document (shot['visualspec'])")
        else:
            from engine.validation.schema import validate as validate_schema

            errors = validate_schema(vs, "visualspec_v2")
            issues.extend(f"visualspec: {e}" for e in errors)
        return issues

    def render(self, shot: dict, style: dict | None, ctx: RenderContext) -> ShotRenderResult:
        issues = self.validate(shot, style)
        if issues:
            raise ValueError(f"MANIM validate failed: {'; '.join(issues)}")
        from engine.renderers.manim.compiler import compile_to_file

        vs = shot.get("visualspec") or ctx.extra.get("visualspec")
        out_path = Path(ctx.output_dir) / f"{shot.get('shot_id', 'shot')}_manim_scene.py"
        scene_file = compile_to_file(vs, out_path)
        return ShotRenderResult(
            path=str(scene_file),
            metadata={
                "renderer": self.id,
                "artifact": "scene_file",
                "scene_name": vs.get("metadata", {}).get("topic", "BenchScene"),
            },
            qa_frames=[],
        )


class MediaRenderer(Renderer):
    """Adapter for the media/footage pipeline (Ken Burns, clip assembly).

    Wave-2 body: renders provided stills (``asset_requirements.still_path``
    or ``ctx.extra["stills"]``) into Ken Burns motion clips — fully offline
    and deterministic. Multiple stills become concatenated segments trimmed
    to the shot duration.
    """

    id = "MEDIA"

    def __init__(self, capability: RendererCapability | None = None) -> None:
        self._capability = capability

    def capabilities(self) -> RendererCapability:
        from engine.renderers.registry import get_capability

        return self._capability or get_capability(self.id)

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        issues = _basic_shot_issues(shot, self.id)
        if not shot.get("asset_requirements") and not shot.get("subject"):
            issues.append("MEDIA needs asset_requirements or a subject to search for")
        return issues

    def render(self, shot: dict, style: dict | None, ctx: RenderContext) -> ShotRenderResult:
        issues = self.validate(shot, style)
        if issues:
            raise ValueError(f"MEDIA validate failed: {'; '.join(issues)}")

        from engine.renderers.media.kenburns import render_kenburns

        out_dir = Path(ctx.output_dir)
        shot_id = shot.get("shot_id", "shot")
        duration = float(shot.get("duration_sec", 4.0))

        stills: list[Path] = []
        req = shot.get("asset_requirements")
        if isinstance(req, dict) and req.get("still_path"):
            stills.append(Path(req["still_path"]))
        elif isinstance(req, list):
            stills.extend(Path(p) for p in req if isinstance(p, (str, Path)) and Path(p).exists())
        for p in (ctx.extra.get("stills") or []):
            if Path(p).exists() and Path(p) not in stills:
                stills.append(Path(p))
        if not stills:
            raise ValueError(
                "MEDIA render needs at least one existing still "
                "(asset_requirements.still_path or ctx.extra['stills'])"
            )

        out_path = out_dir / f"{shot_id}_media.mp4"
        if len(stills) == 1:
            render_kenburns(
                stills[0], out_path, duration=duration, aspect=ctx.aspect,
                fps=ctx.fps, prompt=shot.get("visual_goal", ""),
                seed=int(ctx.seed),
            )
        else:
            # One segment per still, trimmed/concatenated to the duration.
            seg_dur = duration / len(stills)
            segments: list[Path] = []
            for i, still in enumerate(stills):
                seg = out_dir / f"{shot_id}_media_seg{i}.mp4"
                render_kenburns(
                    still, seg, duration=seg_dur, aspect=ctx.aspect,
                    fps=ctx.fps, prompt=f"{shot.get('visual_goal', '')}:{i}",
                    seed=int(ctx.seed) + i,
                )
                segments.append(seg)
            import subprocess

            list_file = out_dir / f"{shot_id}_media_concat.txt"
            list_file.write_text(
                "".join(f"file '{p.resolve()}'\n" for p in segments),
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(list_file), "-c", "copy", str(out_path)],
                capture_output=True, timeout=300,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"MEDIA concat failed: {proc.stderr.decode()[-500:]}")
            for seg in segments:
                seg.unlink(missing_ok=True)
            list_file.unlink(missing_ok=True)

        return ShotRenderResult(
            path=str(out_path),
            metadata={
                "renderer": self.id,
                "stills_used": len(stills),
                "duration_sec": duration,
            },
            qa_frames=[],
        )


class VectorRenderer(Renderer):
    """Adapter for the vector illustration package."""

    id = "VECTOR"

    def __init__(self, capability: RendererCapability | None = None) -> None:
        self._capability = capability

    def capabilities(self) -> RendererCapability:
        from engine.renderers.registry import get_capability

        return self._capability or get_capability(self.id)

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        return _basic_shot_issues(shot, self.id)

    def render(self, shot: dict, style: dict | None, ctx: RenderContext) -> ShotRenderResult:
        raise RendererNotImplemented(
            "VECTOR render body lands in Wave 2 (adapter registered in Wave 1)"
        )


class StubRenderer(Renderer):
    """Registered-but-not-implemented renderer (Wave 2 fills the body).

    Capabilities and validate() are fully functional so the router and shot
    planners can already target these renderers; render() raises
    RendererNotImplemented.
    """

    def __init__(self, renderer_id: str, capability: RendererCapability | None = None) -> None:
        self._id = renderer_id
        self._capability = capability

    @property
    def id(self) -> str:  # noqa: D102 — instance-level id for generic stubs
        return self._id

    def capabilities(self) -> RendererCapability:
        return self._capability or get_capability(self._id)

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        issues = _basic_shot_issues(shot, self._id)
        cap = self.capabilities()
        if cap.max_duration_sec and shot.get("duration_sec"):
            if shot["duration_sec"] > cap.max_duration_sec:
                issues.append(
                    f"duration {shot['duration_sec']}s exceeds {self._id} max "
                    f"{cap.max_duration_sec}s"
                )
        return issues

    def render(self, shot: dict, style: dict | None, ctx: RenderContext) -> ShotRenderResult:
        raise RendererNotImplemented(
            f"{self._id} renderer is registered but not implemented yet (Wave 2)"
        )


def make_renderer(renderer_id: str, capability: RendererCapability) -> Renderer:
    """Factory: live adapters where a body exists, generic stubs otherwise."""
    # Imported lazily: registry imports this module to build instances.
    if renderer_id == "MANIM":
        return ManimRenderer(capability)
    if renderer_id == "MEDIA":
        return MediaRenderer(capability)
    if renderer_id == "VECTOR":
        return VectorRenderer(capability)
    if renderer_id == "AI_IMAGE_MOTION":
        from engine.renderers.media.ai_image_motion import AIImageMotionRenderer

        return AIImageMotionRenderer(capability)
    if renderer_id == "STOCK_VIDEO":
        from engine.renderers.media.stock_video import StockVideoRenderer

        return StockVideoRenderer(capability)
    if renderer_id == "ARCHIVAL":
        from engine.renderers.media.stock_video import ArchivalRenderer

        return ArchivalRenderer(capability)
    if renderer_id == "MOTION_CANVAS":
        from engine.renderers.motion_canvas import MotionCanvasRenderer

        return MotionCanvasRenderer(capability)
    return StubRenderer(renderer_id, capability)
