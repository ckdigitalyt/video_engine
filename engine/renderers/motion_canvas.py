"""motion_canvas.py — MOTION_CANVAS renderer body (directive §6).

Maps Shot v3 (+ style_spec_v2) → template JSON (mc-json-v1), writes the
generated scene file, invokes the headless node renderer (motion/render.mjs)
and verifies the encoded mp4.

IMPLEMENTATION NOTE (2026-08-30, Wave 2): Motion Canvas 3.x ships no
first-class headless CLI — its render path requires driving a browser
(puppeteer/vite editor). On this CPU-only arm64 box that harness is fragile
and heavy, so the template library executes on a minimal node-canvas 2D
engine with the SAME template JSON contract (motion/templates/*.mjs). A
later migration to true Motion Canvas keeps the Python adapter and scene
JSON unchanged — only the node runner swaps. See design doc §6.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from engine.renderers.base import (
    RenderContext,
    Renderer,
    RendererCapability,
    ShotRenderResult,
)

logger = logging.getLogger(__name__)

MOTION_DIR = Path(__file__).resolve().parent.parent.parent / "motion"
RENDER_SCRIPT = MOTION_DIR / "render.mjs"

# Shot payload keys that map onto template props.
_TEMPLATE_ALIASES = {
    # shot field → template prop
    "text_overlay": "title",
}


class MotionCanvasError(RuntimeError):
    """Template render failed."""


def template_json_from_shot(
    shot: dict,
    style: dict | None = None,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> dict:
    """Derive mc-json-v1 scene JSON from a Shot v3 payload.

    The shot may specify ``motion.template`` (+ ``motion.props``). When
    absent, a template is chosen deterministically from the narrative role
    and available payload.
    """
    motion_cfg = shot.get("motion") or {}
    template = motion_cfg.get("template")
    props = dict(motion_cfg.get("props") or {})

    if not template:
        template, props = _default_template(shot)

    # Merge useful shot fields as prop fallbacks (explicit props win).
    title = shot.get("text_overlay")
    if isinstance(title, dict):
        title = title.get("text") or title.get("title")
    if title and "title" not in props:
        props["title"] = title
    if shot.get("visual_goal") and "label" not in props and "title" not in props:
        props.setdefault("label", shot["visual_goal"])
    if shot.get("subject") and template in ("map_zoom",):
        props.setdefault("label", props.get("label", shot["subject"]))

    return {
        "version": "mc-json-v1",
        "template": template,
        "props": props,
        "duration_sec": float(shot.get("duration_sec", 3.0)),
        "width": width,
        "height": height,
        "fps": fps,
        "style": {
            "palette": (style or {}).get("palette", {}),
            "typography": (style or {}).get("typography", {}),
        },
    }


def _default_template(shot: dict) -> tuple[str, dict]:
    """Deterministic template choice from narrative_role + payload."""
    role = shot.get("narrative_role", "")
    data = shot.get("data") or {}
    if role in ("hook", "reveal") and shot.get("text_overlay"):
        return "kinetic_title", {"mode": "slide"}
    if data.get("events"):
        return "timeline", {"events": data["events"]}
    if data.get("rows"):
        return "infographic", {"rows": data["rows"]}
    if data.get("nodes"):
        return "diagram", {"nodes": data["nodes"], "edges": data.get("edges", [])}
    if data.get("from") is not None or data.get("to") is not None:
        return "number_counter", {
            "from": data.get("from", 0), "to": data.get("to", 100)}
    if data.get("left") and data.get("right"):
        return "comparison", {"left": data["left"], "right": data["right"]}
    if data.get("quote"):
        return "quote_card", {"quote": data["quote"]}
    if role in ("explanation", "context"):
        return "callout", {"keyword": shot.get("subject", "KEY")}
    return "kinetic_title", {"mode": "scale"}


class MotionCanvasRenderer(Renderer):
    """Kinetic typography / infographic renderer (template JSON driven)."""

    id = "MOTION_CANVAS"

    def __init__(self, capability: RendererCapability | None = None,
                 motion_dir: Path | None = None) -> None:
        self._capability = capability
        self._motion_dir = Path(motion_dir) if motion_dir else MOTION_DIR

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
        if not self._motion_dir.exists():
            issues.append(f"motion project missing: {self._motion_dir}")
        elif not (self._motion_dir / "render.mjs").exists():
            issues.append("motion project missing render.mjs")
        elif not (self._motion_dir / "node_modules").exists():
            issues.append("motion node_modules missing (run: npm --prefix motion install)")
        template = (shot.get("motion") or {}).get("template")
        if template and template not in _KNOWN_TEMPLATES:
            issues.append(f"unknown motion template: {template!r}")
        return issues

    def render(self, shot: dict, style: dict | None,
               ctx: RenderContext) -> ShotRenderResult:
        issues = self.validate(shot, style)
        if issues:
            raise ValueError(f"MOTION_CANVAS validate failed: {'; '.join(issues)}")

        out_dir = Path(ctx.output_dir)
        shot_id = shot.get("shot_id", "shot")
        # Render at most 1080p (templates are vector-drawn; assembly can
        # upscale without artefacts) while respecting smaller ctx targets.
        scale = min(1.0, 1920 / ctx.resolution[0], 1080 / ctx.resolution[1])
        scene = template_json_from_shot(
            shot, style or ctx.style,
            width=_even(ctx.resolution[0] * scale),
            height=_even(ctx.resolution[1] * scale),
            fps=ctx.fps,
        )

        scene_path = out_dir / f"{shot_id}_mc_scene.json"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")

        out_path = out_dir / f"{shot_id}_motioncanvas.mp4"
        node = shutil.which("node")
        if not node:
            raise MotionCanvasError("node not found on PATH")
        proc = subprocess.run(
            [node, str(self._motion_dir / "render.mjs"),
             str(scene_path), str(out_path)],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            raise MotionCanvasError(
                f"motion render failed ({proc.returncode}): "
                f"{(proc.stderr or proc.stdout)[-1200:]}")
        if not out_path.exists() or out_path.stat().st_size < 1000:
            raise MotionCanvasError("motion render produced no usable output")

        return ShotRenderResult(
            path=str(out_path),
            metadata={
                "renderer": self.id,
                "template": scene["template"],
                "scene_json": str(scene_path),
                "duration_sec": scene["duration_sec"],
            },
            qa_frames=[],
        )


def _even(n: int) -> int:
    return int(n) - int(n) % 2


_KNOWN_TEMPLATES: set[str] = {
    "kinetic_title", "timeline", "map_zoom", "infographic", "comparison",
    "diagram", "callout", "number_counter", "quote_card", "before_after",
    "reveal", "zoom_sequence", "scientific_process", "character_intro",
}
