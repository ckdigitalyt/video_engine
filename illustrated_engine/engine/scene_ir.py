"""V14 Stage 4 — Scene IR: formal scene_spec.json schema + validator.

The story planner produces Scene IR; renderers consume it (directive §8, §22).
This module is deterministic, stdlib-only, and the schema is plain JSON so any
backend adapter (RemotionRenderer, FallbackRenderer, future specialists) can
consume scene specs without importing this module.

Spec doc: docs/v14/SCENE_IR_SPEC.md
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCHEMA_VERSION = "v14.scene_ir/1.0"

# Directive §9 grammar library (composition grammars, not templates).
GRAMMAR_LIBRARY = {
    "RICH_ILLUSTRATED_SCENE", "CHARACTER_SCENE", "OBJECT_SCENE",
    "MICROSCOPIC_WORLD", "BIOLOGICAL_CUTAWAY", "TECHNICAL_CUTAWAY",
    "ENVIRONMENT_RECONSTRUCTION", "GEOGRAPHIC_WORLD", "MAP_TRANSFORMATION",
    "HISTORICAL_RECONSTRUCTION", "ENGINEERING_MECHANISM",
    "MATERIAL_DEFORMATION", "FORCE_FIELD", "PROCESS_FLOW", "TIMELINE",
    "COMPARISON", "DATA_GRAPHIC", "SCALE_DIVE", "CAUSAL_CHAIN",
    "VISUAL_CONTRADICTION",
}

LAYER_TYPES = {
    "background", "environment", "subject", "secondary_subject", "foreground",
    "atmosphere", "texture", "lighting", "scientific_layer",
    "semantic_annotation", "text", "mask", "effect",
}

ASSET_SOURCES = {
    "ai_image", "procedural_svg", "vector", "raster", "generated_gradient",
    "generated_shape", "procedural_particles", "audio",
}

EASINGS = {"linear", "ease_in_out_cubic", "ease_out_cubic", "ease_in_cubic"}

CAMERA_TYPES = {
    "static", "push_in", "pull_out", "pan", "travel", "scale_dive",
    "focus_shift", "reveal",
}

_NUM = (int, float)


def _err(errors: list[str], path: str, msg: str) -> None:
    errors.append(f"{path}: {msg}")


def _check_num_range(errors: list[str], v: _NUM, lo: float, hi: float,
                     path: str) -> None:
    if not (isinstance(v, _NUM) and lo <= v <= hi):
        _err(errors, path, f"expected number in [{lo}, {hi}], got {v!r}")


def _validate_layer(layer: dict, idx: int, errors: list[str]) -> None:
    p = f"layers[{idx}]"
    if not isinstance(layer, dict):
        _err(errors, p, "layer must be an object")
        return
    lid = layer.get("id")
    if not (isinstance(lid, str) and lid):
        _err(errors, p, "missing required 'id' (non-empty string)")
    for req in ("type", "semantic_role", "source"):
        if not (isinstance(layer.get(req), str) and layer[req]):
            _err(errors, p, f"missing required '{req}' (non-empty string)")
    if layer.get("type") not in LAYER_TYPES:
        _err(errors, p, f"type must be one of {sorted(LAYER_TYPES)}")
    if layer.get("source") not in ASSET_SOURCES:
        _err(errors, p, f"source must be one of {sorted(ASSET_SOURCES)}")
    # §20: no empty visual containers — annotations/text must carry payload
    if layer.get("type") in ("semantic_annotation", "text") and not (
            isinstance(layer.get("payload"), dict) and layer["payload"]):
        _err(errors, p, "semantic_annotation/text layers require a non-empty "
                        "'payload' (object) — no empty containers (directive §20)")
    pos = layer.get("position", [0.0, 0.0])
    if not (isinstance(pos, list) and len(pos) == 2
            and all(isinstance(c, _NUM) for c in pos)):
        _err(errors, p, "'position' must be [x, y] numbers")
    for key, lo, hi in (("scale", 0.0, 100.0), ("opacity", 0.0, 1.0),
                        ("depth", 0.0, 1.0)):
        if key in layer:
            _check_num_range(errors, layer[key], lo, hi, f"{p}.{key}")
    if "z" in layer and not isinstance(layer["z"], int):
        _err(errors, p, "'z' must be an integer")
    vis = layer.get("visibility")
    if vis is not None:
        if not (isinstance(vis, list) and len(vis) == 2
                and all(isinstance(c, _NUM) and c >= 0 for c in vis)
                and vis[0] < vis[1]):
            _err(errors, p, "'visibility' must be [start_s, end_s], start < end")


def _validate_keyframes(kfs: object, path: str, errors: list[str]) -> None:
    if not (isinstance(kfs, list) and len(kfs) >= 2):
        _err(errors, path, "keyframes must be a list of >= 2 entries")
        return
    for i, kf in enumerate(kfs):
        if not (isinstance(kf, dict) and isinstance(kf.get("t"), _NUM)
                and "value" in kf):
            _err(errors, f"{path}[{i}]", "keyframe needs {'t': number, 'value': any}")
        elif "easing" in kf and kf["easing"] not in EASINGS:
            _err(errors, f"{path}[{i}]", f"easing must be one of {sorted(EASINGS)}")
    ts = [kf.get("t") for kf in kfs if isinstance(kf, dict)]
    if ts != sorted(ts):
        _err(errors, path, "keyframe times must be non-decreasing")


def validate_scene_spec(spec: object) -> tuple[bool, list[str]]:
    """Validate a Scene IR document. Returns (ok, errors)."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return False, ["scene spec must be a JSON object"]
    if spec.get("schema_version") != SCHEMA_VERSION:
        _err(errors, "schema_version", f"must be {SCHEMA_VERSION!r}")
    for req in ("scene_id", "visual_grammar"):
        if not (isinstance(spec.get(req), str) and spec[req]):
            _err(errors, req, "missing required non-empty string")
    if spec.get("visual_grammar") not in GRAMMAR_LIBRARY:
        _err(errors, "visual_grammar",
             f"must be one of the §9 grammar library: {sorted(GRAMMAR_LIBRARY)}")
    for req in ("duration_s", "fps"):
        v = spec.get(req)
        if not (isinstance(v, _NUM) and v > 0):
            _err(errors, req, "must be a positive number")
    size = spec.get("size")
    if not (isinstance(size, list) and len(size) == 2
            and all(isinstance(c, int) and c > 0 for c in size)):
        _err(errors, "size", "must be [width, height] positive integers")
    layers = spec.get("layers")
    if not (isinstance(layers, list) and layers):
        _err(errors, "layers", "must be a non-empty list")
    else:
        seen_ids: set[str] = set()
        for i, layer in enumerate(layers):
            _validate_layer(layer, i, errors)
            if isinstance(layer, dict) and isinstance(layer.get("id"), str):
                if layer["id"] in seen_ids:
                    _err(errors, f"layers[{i}]", f"duplicate layer id {layer['id']!r}")
                seen_ids.add(layer["id"])
        # §7: a scene must establish a world — require background or environment
        if not any(isinstance(l, dict) and l.get("type") in ("background", "environment")
                   for l in layers if isinstance(l, dict)):
            _err(errors, "layers", "scene needs a 'background' or 'environment' layer")
    cam = spec.get("camera")
    if not isinstance(cam, dict):
        _err(errors, "camera", "missing required camera object")
    else:
        if cam.get("type") not in CAMERA_TYPES:
            _err(errors, "camera.type", f"must be one of {sorted(CAMERA_TYPES)}")
        if not (isinstance(cam.get("purpose"), str) and cam["purpose"].strip()):
            _err(errors, "camera.purpose",
                 "required — camera motion must have semantic purpose (directive §15)")
        if "keyframes" in cam:
            _validate_keyframes(cam["keyframes"], "camera.keyframes", errors)
    anims = spec.get("animations", [])
    if not isinstance(anims, list):
        _err(errors, "animations", "must be a list")
    else:
        for i, a in enumerate(anims):
            if not isinstance(a, dict):
                _err(errors, f"animations[{i}]", "must be an object")
                continue
            if not (isinstance(a.get("target_layer"), str) and a["target_layer"]):
                _err(errors, f"animations[{i}]", "missing 'target_layer'")
            elif isinstance(layers, list) and a.get("target_layer") not in {
                    l.get("id") for l in layers if isinstance(l, dict)}:
                _err(errors, f"animations[{i}]",
                     f"target_layer {a['target_layer']!r} not found in layers")
            if not (isinstance(a.get("purpose"), str) and a["purpose"].strip()):
                _err(errors, f"animations[{i}]",
                     "required — animation must have semantic purpose (§15)")
            if "keyframes" in a:
                _validate_keyframes(a["keyframes"], f"animations[{i}].keyframes",
                                    errors)
    csr = spec.get("caption_safe_regions", [])
    if not isinstance(csr, list):
        _err(errors, "caption_safe_regions", "must be a list")
    else:
        for i, r in enumerate(csr):
            if not (isinstance(r, dict)
                    and all(k in r and isinstance(r[k], _NUM)
                            for k in ("x", "y", "w", "h"))):
                _err(errors, f"caption_safe_regions[{i}]",
                     "must be {x, y, w, h} numbers")
    return (len(errors) == 0), errors


def normalize_scene_spec(spec: dict) -> dict:
    """Fill defaults for optional fields so renderers see a complete doc."""
    out = json.loads(json.dumps(spec))  # deep copy via canonical json
    for layer in out.get("layers", []):
        layer.setdefault("position", [0.0, 0.0])
        layer.setdefault("scale", 1.0)
        layer.setdefault("rotation", 0.0)
        layer.setdefault("opacity", 1.0)
        layer.setdefault("z", 0)
        layer.setdefault("anchor", "center")
        layer.setdefault("depth", 0.0)
    out.setdefault("animations", [])
    out.setdefault("annotations", [])
    out.setdefault("caption_safe_regions", [])
    out.setdefault("style_bible_ref", None)
    out.setdefault("meta", {})
    return out


def spec_hash(spec: dict) -> str:
    """Canonical hash for cache keys (directive §24): stable across key order
    and float noise at 1e-6."""
    def _canon(o: object) -> object:
        if isinstance(o, dict):
            return {k: _canon(v) for k, v in sorted(o.items())}
        if isinstance(o, list):
            return [_canon(v) for v in o]
        if isinstance(o, float):
            return round(o, 6)
        return o

    canonical = json.dumps(_canon(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("validate", "hash"):
        print("usage: scene_ir.py validate <spec.json>... | hash <spec.json>",
              file=sys.stderr)
        return 2
    rc = 0
    for path in argv[1:]:
        try:
            spec = json.loads(Path(path).read_text())
        except Exception as exc:  # noqa: BLE001 — CLI boundary
            print(f"FAIL {path}: unreadable json ({exc})")
            rc = 1
            continue
        ok, errors = validate_scene_spec(spec)
        if argv[0] == "hash":
            print(f"{spec_hash(spec) if ok else 'invalid'} {path}")
        else:
            print(("PASS " if ok else "FAIL ") + path)
        for e in errors:
            print(f"  - {e}")
            rc = 1 if not ok else rc
    return rc


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
