"""V13 M1b: 4-stage rich-visual-plate generation pipeline.

Implements Contract 1 of docs/v13/V13_PLAN.md — generates a 2160x3840
RICH_VISUAL_PLATE plus a ``v13-plate-sidecar@1`` sidecar JSON recording
per-stage provenance.

Stages
------
1. composition     text→img (or multi-ref when refs provided, via
                   ``generate_multi_ref_with_fallback``); on provider failure
                   degrades to a deterministic PIL placeholder plate.
2. detail/material edit pass via ``edit_image_with_fallback``; degrades
                   gracefully (edited=False, composition preserved).
3. semantic-edit   edit pass placing/reserving annotation areas; same
                   degradation contract.
4. depth/edge      deferred to M3 — sidecar records depth_map=null and
                   status="deferred_to_M3".

Offline-safe: provider quota/failure/dry_run never raises — the pipeline
falls back to the deterministic placeholder and records it in
``generation.composition`` (provider="placeholder").
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from src.providers.image_gen import (  # noqa: E402
    ImageGenFactory,
    ImageGenProvider,
    deterministic_seed,
    edit_image_with_fallback,
    generate_multi_ref_with_fallback,
)

SCHEMA = "v13-plate-sidecar@1"
ASSET_CLASS = "RICH_VISUAL_PLATE"
PLATE_W, PLATE_H = 2160, 3840
DEFAULT_ASPECT = "9:16"

_LAYER_NAMES = {"BACKGROUND", "MIDGROUND", "SUBJECT", "FOREGROUND",
                "ATMOSPHERE", "EFFECTS", "ANNOTATION"}
_ANNOT_KINDS = {"label", "number", "arrowhead", "annotation", "diagram"}

_FACTORY: ImageGenFactory | None = None


# ── helpers ───────────────────────────────────────────────────────────── #

def _get_factory() -> ImageGenFactory:
    global _FACTORY
    if _FACTORY is None:
        _FACTORY = ImageGenFactory()
    return _FACTORY


def _model_of(provider: ImageGenProvider) -> str:
    return (getattr(provider, "model", None)
            or getattr(provider, "_model", None)
            or provider.name)


def _rel(p) -> str:
    """Path relative to repo root when inside it, else absolute."""
    s = str(p)
    try:
        r = os.path.relpath(s, REPO_ROOT)
        return r if not r.startswith("..") else s
    except ValueError:
        return s


def _placeholder_image(seed: int, width: int = PLATE_W,
                       height: int = PLATE_H) -> Image.Image:
    """Deterministic kitlib-style placeholder: gradient + mottle + vignette."""
    rng = random.Random(seed)
    top, bottom = (47, 56, 74), (17, 20, 28)
    strip = Image.new("RGB", (1, 512))
    for y in range(512):
        t = y / 511
        strip.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t)
                                     for i in range(3)))
    img = strip.resize((width, height))

    # mottle: warm speckle field
    mw, mh = max(64, width // 8), max(64, height // 8)
    mottle = Image.new("L", (mw, mh), 0)
    md = ImageDraw.Draw(mottle)
    for _ in range(mw * mh // 600):
        x, y = rng.randint(-20, mw + 20), rng.randint(-20, mh + 20)
        r = rng.randint(2, 26)
        md.ellipse((x - r, y - r, x + r, y + r), fill=rng.randint(10, 30))
    mottle = mottle.resize((width, height), Image.BILINEAR)
    img.paste((214, 202, 176), (0, 0),
              mottle.filter(ImageFilter.GaussianBlur(6)))

    # subtle vignette
    vw, vh = max(48, width // 16), max(48, height // 16)
    vig = Image.new("L", (vw, vh), 0)
    vd = ImageDraw.Draw(vig)
    cx, cy = (vw - 1) / 2, (vh - 1) / 2
    maxd = (cx * cx + cy * cy) ** 0.5
    for y in range(vh):
        for x in range(vw):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            if d > 0.62:
                vig.putpixel((x, y), min(110, int((d - 0.62) / 0.38 * 110)))
    img.paste((0, 0, 0), (0, 0),
              vig.resize((width, height), Image.BILINEAR)
              .filter(ImageFilter.GaussianBlur(24)))
    return img


def _compose(provider, spec, seed, gen_w, gen_h, out_dir):
    """Stage 1: exactly one composition attempt. Returns (img|None, rec).

    Never raises; any provider failure degrades to the placeholder path.
    """
    prompt = spec["prompt"]
    refs = spec.get("refs") or []
    rec = {"provider": provider.name, "model": _model_of(provider),
           "seed": seed, "resolution": f"{gen_w}x{gen_h}"}
    try:
        if refs:
            path, composed = generate_multi_ref_with_fallback(
                provider, prompt, refs, aspect=DEFAULT_ASPECT, seed=seed)
            rec["mode"] = "multi_ref" if composed else "text_to_img_fallback"
            rec["degraded"] = not composed
        else:
            src = Path(out_dir) / f"{spec.get('asset', 'plate')}_comp_src.png"
            path = provider.generate(prompt, str(src), width=gen_w,
                                     height=gen_h, seed=seed)
            rec["mode"] = "text_to_img"
            rec["degraded"] = False
        img = Image.open(path).convert("RGB")
        rec["source"] = _rel(path)
        return img, rec
    except Exception as e:  # noqa: BLE001 — provider errors must never crash
        rec["mode"] = "placeholder"
        rec["degraded"] = True
        rec["error"] = str(e)[:200]
        return None, rec


def _edit_stage(provider, prompt, image_path, seed):
    """Stages 2/3: one edit pass; (rec, edited). Never raises.

    Degraded fallback output is DISCARDED so the composition from stage 1
    is never replaced by an unrelated single-pass image.
    """
    rec = {"provider": provider.name, "model": _model_of(provider),
           "seed": seed}
    # cheap capability probe: base-class edit_image is the unsupported stub
    if type(provider).edit_image is ImageGenProvider.edit_image:
        rec.update(edited=False, degraded=True,
                   note="edit op unsupported; stage skipped")
        return rec, False
    try:
        path, edited = edit_image_with_fallback(
            provider, prompt, image_path, aspect=DEFAULT_ASPECT, seed=seed)
        rec["edited"] = bool(edited)
        rec["degraded"] = not edited
        if edited:
            rec["source"] = _rel(path)
            return rec, True
        rec["note"] = "degraded to single-pass; output discarded, composition kept"
        return rec, False
    except Exception as e:  # noqa: BLE001
        rec.update(edited=False, degraded=True, error=str(e)[:200])
        return rec, False


def _adopt(path, plate_path, width, height):
    img = Image.open(path).convert("RGB")
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    img.save(plate_path)


# ── sidecar validation (Contract 1: v13-plate-sidecar@1) ──────────────── #

def _rect_ok(r) -> bool:
    return (isinstance(r, (list, tuple)) and len(r) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in r)
            and r[0] < r[2] and r[1] < r[3])


def validate_sidecar(d: dict) -> list[str]:
    """Return a list of schema errors ([] = valid) for a plate sidecar."""
    errors: list[str] = []

    if d.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not isinstance(d.get("plate"), str) or not d.get("plate"):
        errors.append("plate must be a non-empty path string")
    if d.get("asset_class") != ASSET_CLASS:
        errors.append(f"asset_class must be {ASSET_CLASS}")

    gen = d.get("generation")
    if not isinstance(gen, dict):
        errors.append("generation must be an object")
    else:
        for key in ("composition", "detail", "semantic_edit", "depth"):
            g = gen.get(key)
            if not isinstance(g, dict):
                errors.append(f"generation.{key} must be an object")
                continue
            if key == "depth":
                if g.get("status") != "deferred_to_M3":
                    errors.append("generation.depth.status must be "
                                  "deferred_to_M3 in M1b")
            elif not isinstance(g.get("provider"), str) or not g["provider"]:
                errors.append(f"generation.{key}.provider must be a "
                              "non-empty string")

    layers = d.get("layers")
    if not isinstance(layers, list) or not layers:
        errors.append("layers must be a non-empty list")
    else:
        for i, layer in enumerate(layers):
            if not isinstance(layer, dict):
                errors.append(f"layers[{i}] must be an object")
                continue
            if layer.get("name") not in _LAYER_NAMES:
                errors.append(f"layers[{i}].name invalid: {layer.get('name')!r}")
            mask = layer.get("mask")
            if mask is not None and not isinstance(mask, str):
                errors.append(f"layers[{i}].mask must be a path or null")
            if not _rect_ok(layer.get("bbox_px")):
                errors.append(f"layers[{i}].bbox_px must be [x0,y0,x1,y1]")
            pw = layer.get("parallax_weight")
            if (not isinstance(pw, (int, float)) or isinstance(pw, bool)
                    or not 0.0 <= pw <= 1.0):
                errors.append(f"layers[{i}].parallax_weight must be 0..1")

    if not _rect_ok(d.get("subject_bbox_px")):
        errors.append("subject_bbox_px must be [x0,y0,x1,y1] with x0<x1, y0<y1")

    anns = d.get("annotation_rects_px")
    if not isinstance(anns, list):
        errors.append("annotation_rects_px must be a list")
    else:
        for i, a in enumerate(anns):
            if not isinstance(a, dict):
                errors.append(f"annotation_rects_px[{i}] must be an object")
                continue
            if not isinstance(a.get("id"), str) or not a["id"]:
                errors.append(f"annotation_rects_px[{i}].id must be non-empty")
            if a.get("kind") not in _ANNOT_KINDS:
                errors.append(f"annotation_rects_px[{i}].kind invalid: "
                              f"{a.get('kind')!r}")
            if not _rect_ok(a.get("bbox")):
                errors.append(f"annotation_rects_px[{i}].bbox must be "
                              "[x0,y0,x1,y1]")

    if d.get("depth_map") is not None and not isinstance(d.get("depth_map"), str):
        errors.append("depth_map must be a path or null")

    zs = d.get("zoom_safe")
    if (not isinstance(zs, dict)
            or not isinstance(zs.get("max_scale"), (int, float))
            or isinstance(zs.get("max_scale"), bool)
            or zs.get("max_scale", 0) < 1.0):
        errors.append("zoom_safe.max_scale must be a number >= 1")

    sm = d.get("safe_margin_px")
    if not isinstance(sm, int) or isinstance(sm, bool) or sm < 0:
        errors.append("safe_margin_px must be a non-negative int")

    tags = d.get("texture_tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors.append("texture_tags must be a list of strings")

    if not isinstance(d.get("lighting"), str) or not d.get("lighting"):
        errors.append("lighting must be a non-empty string")

    return errors


# ── pipeline ──────────────────────────────────────────────────────────── #

def generate_plate(spec: dict, out_dir) -> tuple[str, dict]:
    """Generate a rich visual plate + sidecar. Returns (plate_path, sidecar).

    spec keys: story, beat, asset, prompt (required); refs, seed, provider,
    dry_run, gen_width/gen_height (provider call resolution, default
    720x1280 low-res), width/height (final plate, default 2160x3840),
    detail_prompt, semantic_prompt, subject_bbox_px, annotations,
    texture_tags, lighting, max_scale, safe_margin_px.
    """
    prompt = spec.get("prompt")
    if not prompt:
        raise ValueError("spec.prompt is required")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asset = spec.get("asset", "plate")
    seed = spec.get("seed") or deterministic_seed(prompt)
    width = int(spec.get("width", PLATE_W))
    height = int(spec.get("height", PLATE_H))
    gen_w = int(spec.get("gen_width", 720))
    gen_h = int(spec.get("gen_height", 1280))
    dry_run = bool(spec.get("dry_run", False))

    gen: dict = {}
    img: Image.Image | None = None

    # ── stage 1: composition ────────────────────────────────────────────
    if dry_run:
        img = _placeholder_image(seed, width, height)
        gen["composition"] = {"provider": "placeholder",
                              "model": "deterministic-kitlib", "seed": seed,
                              "mode": "placeholder", "degraded": True,
                              "note": "dry_run: deterministic placeholder requested"}
    else:
        provider = _get_factory().get(spec.get("provider", "pollinations"))
        img, rec = _compose(provider, spec, seed, gen_w, gen_h, out_dir)
        if img is None:
            attempted, rec["attempted_provider"] = rec.get("provider"), rec.get("provider")
            rec["provider"], rec["model"] = "placeholder", "deterministic-kitlib"
            rec["note"] = f"provider failed ({attempted}); deterministic placeholder"
            img = _placeholder_image(seed, width, height)
        gen["composition"] = rec

    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    plate_path = out_dir / f"{asset}.png"
    img.save(plate_path)

    placeholder_composed = gen["composition"]["provider"] == "placeholder"

    # ── stage 2: detail / material ──────────────────────────────────────
    if dry_run or placeholder_composed:
        gen["detail"] = {"provider": "skipped", "edited": False,
                         "degraded": True, "note": "skipped: placeholder composition"}
    else:
        provider = _get_factory().get(spec.get("provider", "pollinations"))
        detail_prompt = spec.get(
            "detail_prompt",
            f"enhance surface materials and fine texture detail while preserving "
            f"the exact composition and framing: {prompt}")
        rec, edited = _edit_stage(provider, detail_prompt, str(plate_path),
                                  (seed + 1) % 1_000_000)
        if edited:
            stage_png = out_dir / f"{asset}_detail.png"
            _adopt(rec["source"] if os.path.isabs(rec["source"])
                   else str(REPO_ROOT / rec["source"]), stage_png, width, height)
            rec["source"] = _rel(stage_png)
            _adopt(str(stage_png), plate_path, width, height)
        gen["detail"] = rec

    # ── stage 3: semantic edit (annotation placement) ───────────────────
    if dry_run or placeholder_composed:
        gen["semantic_edit"] = {"provider": "skipped", "edited": False,
                                "degraded": True, "note": "skipped: placeholder composition"}
    else:
        provider = _get_factory().get(spec.get("provider", "pollinations"))
        sem_prompt = spec.get(
            "semantic_prompt",
            "reserve clean uncluttered margins along all plate edges for "
            "annotation callouts; do not alter the central subject")
        rec, edited = _edit_stage(provider, sem_prompt, str(plate_path),
                                  (seed + 2) % 1_000_000)
        if edited:
            stage_png = out_dir / f"{asset}_semantic.png"
            _adopt(rec["source"] if os.path.isabs(rec["source"])
                   else str(REPO_ROOT / rec["source"]), stage_png, width, height)
            rec["source"] = _rel(stage_png)
            _adopt(str(stage_png), plate_path, width, height)
        gen["semantic_edit"] = rec

    # ── stage 4: depth / edge (deferred to M3) ──────────────────────────
    gen["depth"] = {"provider": None, "model": None, "seed": None,
                    "status": "deferred_to_M3", "depth_map": None,
                    "note": "depth/edge conditioning deferred to M3"}

    # ── sidecar (Contract 1) ────────────────────────────────────────────
    subject = spec.get("subject_bbox_px") or [int(0.2 * width), int(0.3 * height),
                                              int(0.8 * width), int(0.7 * height)]
    sidecar = {
        "schema": SCHEMA,
        "plate": _rel(plate_path),
        "asset_class": ASSET_CLASS,
        "generation": gen,
        "layers": [
            {"name": "BACKGROUND", "mask": None,
             "bbox_px": [0, 0, width, height], "parallax_weight": 0.15},
            {"name": "MIDGROUND", "mask": None,
             "bbox_px": [int(0.1 * width), int(0.2 * height),
                         int(0.9 * width), int(0.8 * height)],
             "parallax_weight": 0.45},
            {"name": "SUBJECT", "mask": None, "bbox_px": list(subject),
             "parallax_weight": 0.85},
        ],
        "subject_bbox_px": list(subject),
        "annotation_rects_px": list(spec.get("annotations") or []),
        "depth_map": None,
        "zoom_safe": {"max_scale": float(spec.get("max_scale", 1.6))},
        "safe_margin_px": int(spec.get("safe_margin_px", 40)),
        "texture_tags": list(spec.get("texture_tags")
                             or (["gradient", "mottle", "vignette"]
                                 if placeholder_composed else ["illustration"])),
        "lighting": spec.get("lighting", "soft ambient"),
    }

    errors = validate_sidecar(sidecar)
    if errors:
        raise ValueError(f"sidecar validation failed: {errors}")

    sidecar_path = plate_path.with_name(f"{asset}.sidecar.json")
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n")
    return _rel(plate_path), sidecar


# ── self-test ─────────────────────────────────────────────────────────── #

def _self_test() -> int:
    import tempfile
    import time

    out = Path(tempfile.mkdtemp(prefix="v13_m1b_selftest_"))
    specs = (
        ("live", {  # ONE low-res live composition attempt via Pollinations
            "story": "selftest", "beat": "b01", "asset": "plate_live",
            "prompt": "cutaway technical illustration of a brass orrery on a "
                      "walnut desk, rich engraved detail, deep teal backdrop, "
                      "vertical 9:16 composition",
            "seed": 4242, "provider": "pollinations",
            "gen_width": 720, "gen_height": 1280,
            "texture_tags": ["brass", "walnut", "engraving"],
            "lighting": "warm key from upper left, soft ambient falloff",
            "annotations": [{"id": "label-1", "kind": "label",
                             "bbox": [120, 300, 900, 460]}],
        }),
        ("dry", {  # deterministic placeholder path, zero network
            "story": "selftest", "beat": "b02", "asset": "plate_dry",
            "prompt": "schematic diagram of a tidal lock system, minimal line art",
            "seed": 777, "dry_run": True,
            "texture_tags": ["ink", "paper"],
            "lighting": "flat even light",
            "annotations": [{"id": "num-1", "kind": "number",
                             "bbox": [1600, 3400, 2000, 3600]}],
        }),
    )

    failures = 0
    for label, spec in specs:
        t0 = time.time()
        try:
            plate, sc = generate_plate(spec, out / label)
            errs = validate_sidecar(sc)
            comp = sc["generation"]["composition"]
            detail = sc["generation"]["detail"]
            sem = sc["generation"]["semantic_edit"]
            exists = Path(plate).exists()
            w, h = Image.open(plate).size
            ok = not errs and exists and (w, h) == (PLATE_W, PLATE_H)
            print(f"[{label}] composition={comp['provider']}/{comp['mode']} "
                  f"degraded={comp['degraded']} detail_edited={detail['edited']} "
                  f"semantic_edited={sem['edited']}")
            print(f"[{label}] plate={plate} {w}x{h} exists={exists} "
                  f"depth={sc['generation']['depth']['status']} "
                  f"annotations={len(sc['annotation_rects_px'])} "
                  f"validate_errors={len(errs)}"
                  + (f" {errs[:3]}" if errs else ""))
            print(f"[{label}] {'PASS' if ok else 'FAIL'} "
                  f"({time.time() - t0:.1f}s)")
            failures += 0 if ok else 1
        except Exception as e:  # noqa: BLE001
            print(f"[{label}] FAIL exception: {e}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_self_test())
