"""V14 Stage 6 — grammar base + shared emitters (directive §9).

A grammar is a composition grammar, not a template: it reads story content and
generates a complete, validated Scene IR document — layer structure, depth
plan, continuous purposeful camera, semantic overlays, typography. Every
build() ends in validate_scene_spec, so a grammar can never emit invalid IR.

Coordinate conventions:
- background/gradient and centered procedural shapes draw at frame center;
  their layer.position is the offset from center.
- `primitives` payloads and screen-space overlays use absolute frame coords
  with layer.position [0, 0].
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from engine.scene_ir import SCHEMA_VERSION, validate_scene_spec
except ImportError:  # direct-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from engine.scene_ir import SCHEMA_VERSION, validate_scene_spec

WORLD_W, WORLD_H = 1080.0, 1920.0
DEFAULT_STOPS = ["#12405C", "#0A1D33"]
INK, INK_DIM, LINE = "#E8EEF4", "#9FB3C8", "#2A4E6E"
WARM, COOL = "#F2A65A", "#3E7CB1"
TEXT_MARGIN = 70.0  # min horizontal inset for on-screen text
CAPTION_SAFE_DEFAULT = [{"x": 90.0, "y": 1560.0, "w": 900.0, "h": 280.0}]


class GrammarError(ValueError):
    """Raised when content is missing keys or a grammar emits invalid IR."""


def require(content: dict, keys: list, grammar: str) -> None:
    missing = [k for k in keys if k not in content]
    if missing:
        raise GrammarError(f"{grammar}: content missing required keys {missing}")


def layer(lid: str, ltype: str, semantic_role: str, source: str, *,
          position=(0.0, 0.0), scale: float = 1.0, rotation: float = 0.0,
          opacity: float = 1.0, z: int = 0, anchor: str = "center",
          depth: float = 0.0, visibility=None, payload=None) -> dict:
    l = {
        "id": lid, "type": ltype, "semantic_role": semantic_role,
        "source": source,
        "position": [float(position[0]), float(position[1])],
        "scale": float(scale), "rotation": float(rotation),
        "opacity": float(opacity), "z": int(z), "anchor": anchor,
        "depth": float(depth),
    }
    if visibility is not None:
        l["visibility"] = [float(visibility[0]), float(visibility[1])]
    if payload:
        l["payload"] = payload
    return l


def camera_track(cam_type: str, kfs: list, purpose: str, *,
                 value_space: str = "linear_scale",
                 aperture_layers=None) -> dict:
    """Continuous camera with semantic purpose (§15, §16). kfs entries:
    {t, scale, x?, y?, easing?} — never a jump-cut between them."""
    out_kfs = []
    for kf in kfs:
        k = {
            "t": float(kf["t"]),
            "value": {"scale": float(kf.get("scale", 1.0)),
                      "x": float(kf.get("x", 0.0)),
                      "y": float(kf.get("y", 0.0))},
        }
        if kf.get("easing"):
            k["easing"] = kf["easing"]
        out_kfs.append(k)
    cam = {"type": cam_type, "purpose": purpose, "keyframes": out_kfs,
           "value_space": value_space}
    if aperture_layers:
        cam["aperture_layers"] = list(aperture_layers)
    return cam


def animation(target_layer: str, prop: str, kfs: list, purpose: str) -> dict:
    out_kfs = []
    for kf in kfs:
        k = {"t": float(kf["t"]), "value": kf["value"]}
        if kf.get("easing"):
            k["easing"] = kf["easing"]
        out_kfs.append(k)
    return {"target_layer": target_layer, "property": prop,
            "keyframes": out_kfs, "purpose": purpose}


def leader_annotation(lid: str, at, title: str, sub: str | None = None, *,
                      side: str = "left", z: int = 40,
                      visibility=None) -> dict:
    """Leader-line callout anchored at world point `at` (screen-space text)."""
    x, y = float(at[0]), float(at[1])
    sx = -1.0 if side == "left" else 1.0
    payload = {
        "leader_from": [x, y],
        "elbow": [x + sx * 70.0, y - 55.0],
        "text_at": [x + sx * 150.0, y - 55.0],
        "title": title,
        "text_anchor": "end" if side == "left" else "start",
    }
    if sub:
        payload["sub"] = sub
    return layer(lid, "semantic_annotation", "key_callout", "vector",
                 z=z, visibility=visibility, payload=payload)


def title_text(lid: str, text: str, *, y: float = 260.0, size: float = 54.0,
               x: float = WORLD_W / 2, fill: str | None = None, z: int = 45,
               visibility=None, weight: int = 700) -> dict:
    # V15: fit with real font metrics (wrap to 2 lines, shrink); V14 drew a
    # fixed size with no measurement and titles ran off the frame.
    from engine.textfit import BODY, TextFitError, fit_text
    try:
        # Inter is variable: PIL measures the default instance, the renderer
        # draws weight 700 (~8% wider) -> shrink the measure accordingly
        fit = fit_text(text, max_w=(WORLD_W - 2 * TEXT_MARGIN)
                       / (1.1 if weight >= 600 else 1.0), size=int(size),
                       min_size=24, max_lines=2, font=BODY)
        lines, size = fit["lines"], fit["size"]
    except TextFitError:
        lines = fit_text(" ".join(str(text).split()[:6]) + "…",
                         max_w=WORLD_W - 2 * TEXT_MARGIN, size=int(size),
                         min_size=18, max_lines=2, font=BODY)["lines"]
        size = 18
    payload = {"text": text, "lines": lines, "font": "body",
               "position": [x, y], "anchor": "middle",
               "size": size, "weight": weight}
    if fill:
        payload["fill"] = fill
    return layer(lid, "text", "scene_title", "vector", z=z,
                 visibility=visibility, payload=payload)


def mag_readout(lid: str, *, prefix: str = "MAGNIFICATION",
                position=(990.0, 180.0), size: float = 40.0, z: int = 50) -> dict:
    """Live camera-scale readout — {S} is substituted with cam scale."""
    return layer(lid, "semantic_annotation", "scale_readout", "vector", z=z,
                 payload={"format": f"{prefix} ×{{S}}", "position": list(position),
                          "anchor": "end", "size": size})


def stage_label(lid: str, stages: list, *, position=(90.0, 1700.0),
                z: int = 50) -> dict:
    """Scale-band label that switches with camera magnification:
    stages = [{until_scale?, title, sub}]."""
    return layer(lid, "semantic_annotation", "scale_stage_label", "vector",
                 z=z, payload={"stages": stages, "position": list(position),
                               "anchor": "start"})


def base_spec(grammar_name: str, content: dict, *, layers: list, camera: dict,
              animations=None, caption_safe=None) -> dict:
    """Assemble + validate a full Scene IR document. Raises GrammarError on
    any validator failure — grammars cannot emit invalid IR."""
    scene_id = content.get("scene_id")
    if not (isinstance(scene_id, str) and scene_id.strip()):
        raise GrammarError(f"{grammar_name}: content.scene_id required (non-empty string)")
    spec = {
        "schema_version": SCHEMA_VERSION,
        "scene_id": scene_id,
        "visual_grammar": grammar_name,
        "duration_s": float(content.get("duration_s", 7.0)),
        "fps": int(content.get("fps", 30)),
        "size": [int(content.get("width", WORLD_W)),
                 int(content.get("height", WORLD_H))],
        "seed": int(content.get("seed", 7)),
        "layers": layers,
        "camera": camera,
        "animations": animations or [],
        "caption_safe_regions": caption_safe or CAPTION_SAFE_DEFAULT,
        "meta": {
            "grammar": grammar_name,
            "backend_hint": content.get("backend_hint", "remotion"),
            "generated_by": "engine.grammars",
        },
        "style_bible_ref": content.get("style_bible_ref"),
    }
    ok, errors = validate_scene_spec(spec)
    if not ok:
        raise GrammarError(f"{grammar_name} generated invalid Scene IR: "
                           + "; ".join(errors[:8]))
    return spec


class Grammar:
    """Base class — subclasses set name/summary and implement build()."""

    name = "ABSTRACT"
    summary = ""

    def build(self, content: dict) -> dict:
        raise NotImplementedError
