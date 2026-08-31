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
from engine.v4.microevents import events_to_motion_canvas, shot_index_of

logger = logging.getLogger(__name__)

MOTION_DIR = Path(__file__).resolve().parent.parent.parent / "motion"
RENDER_SCRIPT = MOTION_DIR / "render.mjs"

# Shot payload keys that map onto template props.
_TEMPLATE_ALIASES = {
    # shot field → template prop
    "text_overlay": "title",
}

# ── De-templating (V4 §14 audit finding: six Motion Canvas infographics
# were dhash-identical — one visual template repeated six times). Every
# shot now receives a deterministic per-shot VARIANT: palette accent,
# layout, and motif rotate with the shot index, so two Motion Canvas shots
# can never render the same composition again.
_VARIANT_LAYOUTS = ("left", "right", "center", "bottom_bar")
_VARIANT_MOTIFS = ("underline", "dots", "frame", "sweep", "corner")
_VARIANT_ACCENTS = ("#e0533d", "#3da5e0", "#e0a53d", "#5b3de0", "#3de08a",
                    "#e03d9c", "#8ae03d", "#3dc9e0")


def variant_for_index(index: int, palette: dict | None = None) -> dict:
    """Deterministic per-shot variation block (palette/layout/motif)."""
    accent = _VARIANT_ACCENTS[index % len(_VARIANT_ACCENTS)]
    base = (palette or {}).get("accent") or (palette or {}).get("primary")
    return {
        "index": index,
        "layout": _VARIANT_LAYOUTS[index % len(_VARIANT_LAYOUTS)],
        "motif": _VARIANT_MOTIFS[index % len(_VARIANT_MOTIFS)],
        "accent": str(base) if (index % 3 == 0 and base) else accent,
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
    """Derive mc-json-v1 scene JSON from a Shot v3/v4 payload.

    The shot may specify ``motion.template`` (+ ``motion.props``). When
    absent, a template is chosen deterministically from the narrative role
    and available payload.

    V4 additions (directive §4/§14):
      * ``props["variant"]`` — per-shot palette/layout/motif variation so
        repeated templates are never dhash-identical (SHOT_DIVERSITY);
      * ``props["micro_events"]`` — renderer-visible micro-event cues.
    """
    motion_cfg = shot.get("motion") or {}
    if isinstance(motion_cfg, str):
        # shot_v3 schema types motion as a string description; template
        # selection then falls to the role-based default.
        motion_cfg = {"description": motion_cfg}
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

    # ── V4: de-templating variant + micro events ──
    style_palette = (style or {}).get("palette") or {}
    props["variant"] = variant_for_index(shot_index_of(shot), style_palette)
    # plan-time stage override (repair passes): keep the deterministic
    # variant but allow the edit layer to pin a different stage mix.
    _ovr = (motion_cfg.get("props") or {}).get("variant")
    if isinstance(_ovr, dict) and isinstance(_ovr.get("stage_override"), int):
        props["variant"]["stage_override"] = _ovr["stage_override"]
    micro = shot.get("micro_events") or []
    if micro:
        props["micro_events"] = events_to_motion_canvas(micro)
        # V4 §4/§16: compiled toolkit ops — discrete, frame-timed events
        # the node event layer renders (flashes, shakes, silhouettes).
        from engine.v4.motion_toolkit import canvas_event_cues, micro_event_ops
        seed = shot.get("seed", 0) or 0
        ops = micro_event_ops(
            micro, duration=float(shot.get("duration_sec", 3.0)),
            fps=fps, seed=int(seed),
            subject=str(shot.get("subject") or ""),
            fill_spacing=2.2)
        props["event_cues"] = canvas_event_cues(ops, fps)
    if shot.get("camera_move") and shot.get("camera_move") != "static":
        props.setdefault("camera", {"move": shot["camera_move"]})

    return {
        "version": "mc-json-v1",
        "template": template,
        "props": props,
        "duration_sec": float(shot.get("duration_sec", 3.0)),
        "width": width,
        "height": height,
        "fps": fps,
        "style": {
            "palette": style_palette,
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


# ── SHOT_DIVERSITY self-check hook (V4 §19) ───────────────────────────────

def diversity_signature(scene_json: dict) -> str:
    """Stable identity of what a Motion Canvas scene will *look like*.

    Two scenes with the same signature render the same imagery (template +
    variant + content) — the dino_v1 failure where six infographics shared
    one visual template. Deliberately excludes duration/width/fps."""
    import hashlib

    props = scene_json.get("props") or {}
    identity = {
        "template": scene_json.get("template"),
        "variant": props.get("variant"),
        "title": props.get("title"),
        "label": props.get("label"),
        "keyword": props.get("keyword"),
        "micro_events": [
            (e.get("anim"), round(float(e.get("t", 0)), 1))
            for e in (props.get("micro_events") or [])
        ],
    }
    blob = json.dumps(identity, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def self_check_diversity(signatures: dict[str, str]) -> list[dict]:
    """Flag shots whose scenes would look identical (SHOT_DIVERSITY hook).

    ``signatures``: {shot_id: diversity_signature}. Returns duplicate
    groups [{signature, shot_ids}] with >= 2 members (empty = diverse)."""
    groups: dict[str, list[str]] = {}
    for sid, sig in (signatures or {}).items():
        groups.setdefault(sig, []).append(sid)
    return [{"signature": sig, "shot_ids": sorted(ids)}
            for sig, ids in sorted(groups.items()) if len(ids) >= 2]


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
        _m = shot.get("motion")
        _m = {} if isinstance(_m, str) else (_m or {})
        template = _m.get("template")
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
                "variant": scene["props"].get("variant"),
                "diversity_signature": diversity_signature(scene),
                "micro_events": len(scene["props"].get("micro_events") or []),
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
