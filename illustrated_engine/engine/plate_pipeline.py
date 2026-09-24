"""V13 M1b: 4-stage rich-visual-plate generation pipeline.

Implements Contract 1 of docs/v13/V13_PLAN.md — generates a 2160x3840
RICH_VISUAL_PLATE plus a ``v13-plate-sidecar@1`` sidecar JSON recording
per-stage provenance.

Stages
------
1. composition     V13B M3 tiered rich-asset descent (directive P0 "RICH
                   ASSET FALLBACK HIERARCHY"): tier1 rich AI plate (text→img
                   or multi-ref via ``generate_multi_ref_with_fallback``) →
                   tier2 rich procedural FULL-FRAME scene → tier3 layered
                   hybrid (environment base + overlay evidence) → tier4
                   subject-specific technical diagram → tier5 simple
                   diagram (only when the shot's M2 visual_grammar
                   composition is a justified panel).  A failed tier
                   descends to the next; the bare PIL gradient placeholder
                   is RETIRED as publishable — reaching it records
                   asset_tier="failed" in the sidecar.
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

import math
import json
import os
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_ROOT = Path(__file__).resolve().parents[1]
# V13B M3: the ``engine`` package must resolve to illustrated_engine/engine
# (the repo-root ``engine`` package is a different project).
for _p in (REPO_ROOT, _ENGINE_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

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


# ── V13B M3 — tiered rich-asset fallback (directive P0) ─────────────────
#
# docs/directives/JADE_V13B_STORY_SPECIFIC_VISUAL_GRAMMAR.md:
#   "RICH ASSET FALLBACK HIERARCHY"  tier1 rich plate → tier2 rich
#     procedural reconstruction → tier3 layered hybrid → tier4
#     subject-specific technical diagram → tier5 simple diagram (only when
#     the concept genuinely requires it / justified panel).
#   "RICH VISUALS MUST BE PRIMARY"   procedural art composes a FULL-FRAME
#     scene with texture/depth/lighting — never a small centered diagram
#     card (tier2/3).
#   "NO EMPTY VISUAL CONTAINERS"     every drawn container carries real
#     payload (label/measure/state) or is not drawn (_callout refuses).
# The bare PIL gradient placeholder is RETIRED as publishable: a shot that
# reaches it records asset_tier="failed" in the sidecar.

TIER_METHODS = {
    "tier1": "ai_composition",
    "tier2": "procedural_fullframe_scene",
    "tier3": "procedural_layered_hybrid",
    "tier4": "domain_technical_diagram",
    "tier5": "panel_simple_diagram",
    "failed": "placeholder_gradient_retired",
}

_TIER_TAGS = {
    "tier1": ["illustration"],
    "tier2": ["procedural_scene", "gradient", "grain", "glow", "vignette"],
    "tier3": ["procedural_hybrid", "overlay_evidence", "gradient", "grain"],
    "tier4": ["parchment", "ink_linework", "mottle"],
    "tier5": ["parchment", "ink_linework"],
    "failed": ["gradient", "mottle", "vignette"],
}

# Deep full-frame scene tints per M2 story domain: (sky top, sky bottom,
# ground).  Procedural scenes render as world-bleed environments.
_SCENE_TINTS = {
    "biology": ((8, 34, 38), (22, 78, 66), (16, 58, 42)),
    "physics_mechanism": ((20, 28, 40), (48, 60, 76), (38, 46, 58)),
    "geography_environment": ((38, 66, 86), (106, 110, 84), (94, 84, 54)),
    "history": ((30, 24, 18), (90, 70, 46), (66, 52, 34)),
    "engineering": ((24, 26, 30), (58, 62, 68), (46, 50, 56)),
    "everyday_science": ((36, 28, 22), (100, 82, 62), (76, 62, 46)),
    "general": ((22, 26, 36), (52, 58, 72), (42, 46, 58)),
}

# M2 composition class -> tier2 subject-form family.
_FORM_FAMILY = {
    "macro_world": "facet", "macro_zoom": "facet", "macro_reveal": "facet",
    "cutaway": "vessel", "machine_cutaway": "vessel", "exploded": "vessel",
    "process_zoom": "bodies", "mechanism_reveal": "bodies",
    "interaction": "bodies", "object_contact": "bodies",
    "force_deformation": "bodies", "deformation": "bodies",
    "load_path": "bodies",
    "landscape": "terrain", "map": "terrain",
    "atmosphere_reconstruction": "terrain", "place_reconstruction": "terrain",
    "before_after": "terrain", "timeline": "terrain",
    "real_object": "object",
}

# M2 overlay vocabulary -> real payload text for callouts.
_OVERLAY_TEXT = {
    "scale_bar": "SCALE", "structure_label": "STRUCTURE",
    "membrane_callout": "MEMBRANE", "process_arrow": "PROCESS",
    "magnitude_compare": "RELATIVE SIZE", "force_arrow": "FORCE",
    "contact_point": "CONTACT", "friction_vector": "FRICTION",
    "state_label": "STATE", "cause_chain": "CAUSE",
    "region_label": "REGION", "climate_band": "CLIMATE BAND",
    "wind_arrow": "WIND", "elevation_tint": "ELEVATION",
    "flow_path": "FLOW", "date_marker": "DATE", "site_label": "SITE",
    "route_line": "ROUTE", "before_after_pair": "BEFORE / AFTER",
    "impact_radius": "IMPACT", "load_path_line": "LOAD PATH",
    "material_callout": "MATERIAL", "measurement": "MEASURE",
    "failure_point": "FAILURE POINT", "section_label": "SECTION",
    "object_label": "OBJECT", "state_change": "STATE CHANGE",
    "temperature_tag": "TEMPERATURE", "cause_arrow": "CAUSE",
    "result_tag": "RESULT",
}

_STOPWORDS = frozenset("""
a an the of on in at to for with and or is are was were be been being it its
this that these those from by as into over under near very more most than
then when while during about across between vertical horizontal rich detail
composition illustration style cinematic closeup wide shot view scene frame
plate generated rendered new
""".split())

_MEASURE_RE = re.compile(
    r"(-?\d+(?:[.,]\d+)?)\s?(km|mm|cm|µm|um|nm|°c|°f|°|mpa|kpa|psi|bar|%|"
    r"m/s|km/h|mph|million|billion|k|m|g)\b", re.IGNORECASE)


def _overlay_text(kind: str) -> str:
    return _OVERLAY_TEXT.get(str(kind or "").strip(),
                             str(kind or "").replace("_", " ").upper())


def _key_terms(text, limit: int = 4) -> list:
    out = []
    for w in re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", str(text or "")):
        lw = w.lower()
        if lw in _STOPWORDS or lw in out:
            continue
        out.append(lw)
        if len(out) >= limit:
            break
    return out


def _measure_of(text) -> str:
    m = _MEASURE_RE.search(str(text or ""))
    if not m:
        return ""
    unit = m.group(2)
    if unit.lower() == "°c":
        unit = "°C"
    elif unit.lower() == "°f":
        unit = "°F"
    return f"{m.group(1).replace(',', '.')} {unit}"


def _vg(spec: dict) -> dict:
    """Normalize the shot's M2 visual_grammar for the procedural tiers."""
    raw = spec.get("visual_grammar") if isinstance(spec.get("visual_grammar"),
                                                   dict) else {}
    domain = str(raw.get("domain") or "general").strip().lower() or "general"
    composition = str(raw.get("composition") or raw.get("world") or "").strip().lower() \
        or "real_object"
    overlays = [str(o).strip() for o in (raw.get("overlays") or [])
                if str(o).strip()]

    def _rgb(v):
        if (isinstance(v, (list, tuple)) and len(v) == 3
                and all(isinstance(c, (int, float)) and not isinstance(c, bool)
                        for c in v)):
            return tuple(int(max(0, min(255, c))) for c in v)
        return None

    accent = _rgb((raw.get("accent") or {}).get("rgb"))
    if accent is None:
        try:
            from engine.visual_grammar import accent_for
            accent = _rgb(accent_for(domain).get("rgb"))
        except Exception:  # noqa: BLE001 — resolver unavailable → brand fallback
            accent = None
    return {"domain": domain, "composition": composition,
            "overlays": overlays, "accent": accent or (194, 91, 51)}


def _tier_fonts():
    from engine.diagrams import _fonts
    return _fonts({"typography": {"display": "BebasNeue-Regular.ttf",
                                  "body": "Inter-Variable.ttf"}})


def _subject_anchor(spec: dict, width: int, height: int) -> tuple:
    b = spec.get("subject_bbox_px")
    cx, cy = width * 0.5, height * 0.42
    if (isinstance(b, (list, tuple)) and len(b) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in b)):
        if all(abs(v) <= 1.5 for v in b):        # planv9 stores fractions
            cx, cy = (b[0] + b[2]) / 2 * width, (b[1] + b[3]) / 2 * height
        else:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return (int(max(0.12 * width, min(0.88 * width, cx))),
            int(max(0.14 * height, min(0.72 * height, cy))))


def _gradient_canvas(width: int, height: int, top, bottom) -> Image.Image:
    strip = Image.new("RGB", (1, 512))
    for y in range(512):
        t = y / 511
        strip.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t)
                                     for i in range(3)))
    return strip.resize((width, height))


def _glow(img: Image.Image, cx, cy, r, color, strength: int = 120):
    """Radial key light (rendered quarter-size; deterministic)."""
    w, h = img.size
    s = 4
    small = Image.new("RGBA", (max(1, w // s), max(1, h // s)), (0, 0, 0, 0))
    ImageDraw.Draw(small).ellipse([(cx - r) / s, (cy - r) / s,
                                   (cx + r) / s, (cy + r) / s],
                                  fill=color + (strength,))
    small = small.filter(ImageFilter.GaussianBlur(max(2, int(r / s * 0.6))))
    return Image.alpha_composite(img.convert("RGBA"),
                                 small.resize(img.size, Image.BILINEAR)
                                 ).convert("RGB")


def _haze(d, width: int, horizon: int, tint, unit: int) -> None:
    """Soft atmospheric depth band above the horizon (alpha strips)."""
    for i in range(18):
        t = i / 17
        y = horizon - int(unit * 0.16 * t)
        d.line([(0, y), (width, y)], fill=tint + (int(26 * (1 - t)),),
               width=max(2, int(unit * 0.012)))


def _grain(img: Image.Image, seed) -> Image.Image:
    """Seeded film grain (numpy PRNG, quarter res — deterministic)."""
    import numpy as np
    w, h = img.size
    rng_np = np.random.default_rng((int(seed) or 0) ^ 0x60A1)
    small = rng_np.normal(0, 14.0, (max(2, h // 4), max(2, w // 4)))
    mask = Image.fromarray(np.clip(128 + small, 0, 255).astype("uint8"), "L") \
        .resize(img.size, Image.BILINEAR)
    hi = mask.point(lambda v: 255 if v > 150 else 0)
    lo = mask.point(lambda v: 255 if v < 106 else 0)
    img = Image.composite(Image.new("RGB", img.size, (236, 229, 212)), img, hi)
    return Image.composite(Image.new("RGB", img.size, (12, 12, 14)), img, lo)


def _vignette(img: Image.Image, strength: int = 110, start: float = 0.62):
    w, h = img.size
    vw, vh = max(48, w // 16), max(48, h // 16)
    vig = Image.new("L", (vw, vh), 0)
    vd = ImageDraw.Draw(vig)
    cx, cy = (vw - 1) / 2, (vh - 1) / 2
    maxd = (cx * cx + cy * cy) ** 0.5
    for y in range(vh):
        for x in range(vw):
            dd = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            if dd > start:
                vig.putpixel((x, y), min(strength, int(
                    (dd - start) / (1 - start + 1e-6) * strength)))
    img.paste((0, 0, 0), (0, 0), vig.resize(img.size, Image.BILINEAR)
              .filter(ImageFilter.GaussianBlur(24)))
    return img


def _finish_scene(img: Image.Image, seed) -> Image.Image:
    return _vignette(_grain(img, seed))


def _shadow_text(d, xy, text, font, fill, shadow=(0, 0, 0, 200)) -> None:
    d.text((xy[0] + 4, xy[1] + 4), text, font=font, fill=shadow)
    d.text(xy, text, font=font, fill=fill)


def _callout(d, anchor, tip, text, font, accent,
             text_fill=(240, 234, 218), shadow=(0, 0, 0, 200),
             frame=None, measure=None) -> bool:
    """Leader + accent dot + payload text.  NO EMPTY VISUAL CONTAINERS:
    a callout without label/measure payload is NOT drawn."""
    payload = " ".join(str(text or "").split())
    if measure:
        payload = f"{payload} {measure}".strip()
    if not payload:
        return False
    ax, ay = float(anchor[0]), float(anchor[1])
    tx, ty = float(tip[0]), float(tip[1])
    d.line([(ax, ay), (tx, ty)], fill=accent + (225,), width=6)
    d.ellipse([ax - 13, ay - 13, ax + 13, ay + 13], fill=accent + (255,))
    if frame:
        tw = d.textlength(payload, font=font)
        if tx + tw + 24 > frame[0] - 24:
            tx = max(24.0, frame[0] - 24 - tw)
        ty = min(max(24.0, ty), frame[1] - 80)
    _shadow_text(d, (tx, ty), payload, font, text_fill, shadow)
    return True


def _parchment(size, seed) -> Image.Image:
    img = Image.new("RGB", size, (233, 223, 200))
    rng = random.Random((int(seed) or 0) ^ 0x0DD5)
    w, h = size
    blot = Image.new("RGB", size, (233, 223, 200))
    bd = ImageDraw.Draw(blot)
    for _ in range(46):
        x, y = rng.randrange(w), rng.randrange(h)
        r = int(min(w, h) * rng.uniform(0.02, 0.09))
        col = (216, 204, 178) if rng.random() < 0.55 else (240, 231, 208)
        bd.ellipse([x - r, y - r, x + r, y + r], fill=col)
    blot = blot.filter(ImageFilter.GaussianBlur(max(4, min(w, h) // 24)))
    return Image.blend(img, blot, 0.5)


# ── tier2 subject-form painters (full-frame, never a centered card) ─────

def _facet_subject(size, cx, cy, radius, base, accent, rng) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lite = tuple(min(255, c + 70) for c in base)
    n = 8
    outer, inner = [], []
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.22, 0.22)
        rr = radius * rng.uniform(0.74, 1.06)
        outer.append((cx + rr * math.cos(a), cy + rr * math.sin(a) * 0.9))
        a2 = 2 * math.pi * i / n + 0.45
        rr2 = radius * rng.uniform(0.30, 0.44)
        inner.append((cx + rr2 * math.cos(a2), cy + rr2 * math.sin(a2) * 0.9))
    for i in range(n):
        j = (i + 1) % n
        t = rng.uniform(0.16, 0.52)
        fill = tuple(int(accent[k] * t + lite[k] * (1 - t)) for k in range(3))
        d.polygon([outer[i], outer[j], inner[j], inner[i]], fill=fill + (245,))
        d.line([outer[i], outer[j]], fill=(18, 16, 14, 210), width=5)
        d.line([inner[i], inner[j]], fill=(18, 16, 14, 120), width=3)
    for _ in range(3):  # specular glints — lighting
        gx = rng.uniform(cx - radius * 0.5, cx + radius * 0.5)
        gy = rng.uniform(cy - radius * 0.5, cy + radius * 0.3)
        gr = radius * rng.uniform(0.03, 0.07)
        d.ellipse([gx - gr, gy - gr, gx + gr, gy + gr],
                  fill=(255, 250, 238, 190))
    return layer


def _vessel_subject(size, cx, cy, hw, hh, accent, rng) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    rad = int(min(hw, hh) * 0.42)
    box = [cx - hw, cy - hh, cx + hw, cy + hh]
    body = Image.new("RGBA", size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bd.rounded_rectangle(box, radius=rad, fill=(210, 202, 188, 250))
    for i in range(4):  # cutaway strata (scene content; labels via callouts)
        f = 0.30 + 0.18 * i
        col = tuple(int(accent[k] * f + 226 * (1 - f)) for k in range(3))
        y0 = cy - hh + (2 * hh) * (0.12 + 0.20 * i)
        y1 = cy - hh + (2 * hh) * (0.12 + 0.20 * i + 0.14)
        bd.rectangle([cx - hw + hw * 0.12, y0, cx + hw - hw * 0.12, y1],
                     fill=col + (235,))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=rad, fill=255)
    body.putalpha(Image.composite(body.split()[3], Image.new("L", size, 0),
                                  mask))
    layer = Image.alpha_composite(layer, body)
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=rad,
                                            outline=(18, 16, 14, 230), width=7)
    return layer


def _bodies_subject(size, cx, cy, spread, radius, accent, rng) -> Image.Image:
    from engine.diagrams_v4 import _arrow
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lx, rx = cx - spread / 2, cx + spread / 2
    d.rounded_rectangle([lx - radius, cy - radius * 0.72,
                         lx + radius * 0.86, cy + radius * 0.72],
                        radius=int(radius * 0.4), fill=(206, 214, 224, 250),
                        outline=(18, 16, 14, 220), width=6)
    d.rounded_rectangle([rx - radius * 0.86, cy - radius * 0.62,
                         rx + radius, cy + radius * 0.62],
                        radius=int(radius * 0.4), fill=(120, 130, 142, 250),
                        outline=(18, 16, 14, 220), width=6)
    _arrow(d, int(lx), int(cy - radius * 1.25), int(rx - radius * 0.5),
           int(cy - radius * 1.25), accent, w=10)
    d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=accent + (255,))
    return layer


def _terrain_subject(size, cx, cy, accent, rng) -> Image.Image:
    from engine.diagrams import _ridge
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    base_y = int(h * 0.72)
    pts = _ridge(int(w * 0.42), base_y, int(h * 0.30), int(w * 0.55), sharp=2.6)
    d.polygon([(pts[0][0], base_y)] + pts + [(pts[-1][0], base_y)],
              fill=(46, 54, 48, 255))
    pts2 = _ridge(int(w * 0.78), base_y, int(h * 0.46), int(w * 0.36),
                  sharp=2.2)
    d.polygon([(pts2[0][0], base_y)] + pts2 + [(pts2[-1][0], base_y)],
              fill=(66, 74, 64, 255))
    my = base_y - int(h * 0.16)
    d.ellipse([cx - 16, my - 16, cx + 16, my + 16], fill=accent + (255,))
    return layer


def _object_subject(size, cx, cy, hw, hh, accent, rng) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rad = int(min(hw, hh) * 0.32)
    d.rounded_rectangle([cx - hw, cy - hh, cx + hw, cy + hh], radius=rad,
                        fill=(198, 190, 176, 250), outline=(18, 16, 14, 225),
                        width=7)
    d.rounded_rectangle([cx - hw, cy - hh, cx + hw, cy - hh + hh * 0.4],
                        radius=rad, fill=(232, 226, 212, 120))
    return layer


def _tier2_fullframe_scene(spec: dict, width: int, height: int,
                           seed) -> Image.Image:
    """tier2 — rich procedural reconstruction: a FULL-FRAME scene with
    texture/depth/lighting composed from the shot's M2 visual_grammar
    (world/composition/accent), using the diagram painters' vocabulary
    (_ridge/_arrow/_fonts).  Raises on failure (descends); deterministic."""
    vg = _vg(spec)
    accent = vg["accent"]
    top, bottom, ground = _SCENE_TINTS.get(vg["domain"],
                                           _SCENE_TINTS["general"])
    disp, body = _tier_fonts()
    rng = random.Random((int(seed) or 0) ^ 0x13B3)
    unit = min(width, height)
    cx, cy = _subject_anchor(spec, width, height)
    fam = _FORM_FAMILY.get(vg["composition"], "object")

    img = _gradient_canvas(width, height, top, bottom)
    d = ImageDraw.Draw(img, "RGBA")
    horizon = int(height * (0.62 if fam == "terrain" else 0.78))
    d.rectangle([0, horizon, width, height],
                fill=tuple(int(c * 0.9) for c in ground) + (255,))
    _haze(d, width, horizon, bottom, unit)
    img = _glow(img, cx, cy - unit * 0.08, unit * 0.55, accent, 60)

    if fam == "facet":
        r = unit * 0.30
        layer = _facet_subject(img.size, cx, cy, r, bottom, accent, rng)
        anchors = ((cx - r * 0.55, cy - r * 0.45), (cx + r * 0.5, cy),
                   (cx, cy + r * 0.72))
    elif fam == "vessel":
        hw, hh = unit * 0.34, unit * 0.52
        layer = _vessel_subject(img.size, cx, cy, hw, hh, accent, rng)
        anchors = ((cx - hw * 0.55, cy - hh * 0.6), (cx + hw * 0.5, cy - hh * 0.15),
                   (cx, cy + hh * 0.6))
    elif fam == "bodies":
        layer = _bodies_subject(img.size, cx, cy, unit * 0.40, unit * 0.24,
                                accent, rng)
        anchors = ((cx - unit * 0.2, cy - unit * 0.30), (cx, cy),
                   (cx + unit * 0.2, cy))
    elif fam == "terrain":
        layer = _terrain_subject(img.size, cx, cy, accent, rng)
        anchors = ((cx, int(height * 0.56)), (cx - unit * 0.22, int(height * 0.66)),
                   (cx + unit * 0.2, int(height * 0.70)))
    else:
        hw, hh = unit * 0.30, unit * 0.40
        layer = _object_subject(img.size, cx, cy, hw, hh, accent, rng)
        anchors = ((cx - hw * 0.6, cy - hh * 0.5), (cx + hw * 0.6, cy),
                   (cx, cy + hh * 0.6))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")

    terms = _key_terms(spec.get("title") or spec.get("claim")
                       or spec.get("prompt"), 3)
    subject_txt = " ".join(terms).upper()
    if subject_txt:
        _shadow_text(d, (int(width * 0.07), int(height * 0.86)), subject_txt,
                     disp(max(28, int(unit * 0.05))), accent)
    ovs = (vg["overlays"] * 3)[:3] or ["object_label", "state_label",
                                       "cause_arrow"]
    small = body(max(16, int(unit * 0.026)))
    m = _measure_of(spec.get("prompt"))
    tips = ((int(width * 0.07), cy - int(unit * 0.30)),
            (int(width * 0.68), cy - int(unit * 0.16)),
            (int(width * 0.60), cy + int(unit * 0.34)))
    for anchor, tip, kind in zip(anchors, tips, ovs):
        _callout(d, anchor, tip, _overlay_text(kind), small, accent,
                 frame=img.size, measure=m if kind is ovs[1] else None)
    return _finish_scene(img, seed)


def _tier3_layered_hybrid(spec: dict, width: int, height: int,
                          seed) -> Image.Image:
    """tier3 — layered hybrid: procedural environment base (gradient,
    terrain depth, haze, key light) + a separate transparent overlay-evidence
    layer (payload callouts + markers).  Raises on failure; deterministic."""
    vg = _vg(spec)
    accent = vg["accent"]
    top, bottom, ground = _SCENE_TINTS.get(vg["domain"],
                                           _SCENE_TINTS["general"])
    disp, body = _tier_fonts()
    rng = random.Random((int(seed) or 0) ^ 0x13B4)
    unit = min(width, height)

    img = _gradient_canvas(width, height, top, bottom)
    d = ImageDraw.Draw(img, "RGBA")
    horizon = int(height * 0.64)
    d.rectangle([0, horizon, width, height], fill=ground + (255,))
    from engine.diagrams import _ridge
    pts = _ridge(int(width * 0.5), horizon, horizon - int(unit * 0.12),
                 int(width * 0.60), sharp=2.0)
    d.polygon([(pts[0][0], horizon)] + pts + [(pts[-1][0], horizon)],
              fill=tuple(int(c * 0.74) for c in ground) + (255,))
    _haze(d, width, horizon, bottom, unit)
    img = _glow(img, width * 0.5, height * 0.30, unit * 0.62, accent, 55)
    base = img.convert("RGBA")

    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    cx, cy = _subject_anchor(spec, width, height)
    r = int(unit * 0.05)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent + (255,))
    d.ellipse([cx - 2 * r, cy - 2 * r, cx + 2 * r, cy + 2 * r],
              outline=accent + (170,), width=6)
    ly = cy - int(unit * 0.10)
    mx = int(width * 0.76)
    step = max(8, int(unit * 0.05))
    for xseg in range(cx + 3 * r, mx - 3 * r, step):  # relation/flow evidence
        d.line([(xseg, ly), (xseg + max(4, int(unit * 0.022)), ly)],
               fill=(240, 234, 218, 235), width=6)
    d.ellipse([mx - int(r * 0.7), ly - int(r * 0.7),
               mx + int(r * 0.7), ly + int(r * 0.7)], outline=accent + (255,),
              width=7)

    terms = _key_terms(spec.get("title") or spec.get("claim")
                       or spec.get("prompt"), 3)
    label = " ".join(terms).upper()
    if label:
        _shadow_text(d, (int(width * 0.07), int(height * 0.80)), label,
                     disp(max(28, int(unit * 0.05))), accent)
    ovs = (vg["overlays"] * 2)[:2] or ["object_label", "cause_arrow"]
    small = body(max(16, int(unit * 0.026)))
    m = _measure_of(spec.get("prompt"))
    _callout(d, (cx, cy), (int(width * 0.08), int(height * 0.30)),
             _overlay_text(ovs[0]), small, accent, frame=img.size,
             measure=m or None)
    _callout(d, (mx, ly), (int(width * 0.58), ly - int(unit * 0.14)),
             _overlay_text(ovs[1]), small, accent, frame=img.size)
    return _finish_scene(Image.alpha_composite(base, ov).convert("RGB"), seed)


def _tier4_technical_diagram(spec: dict, width: int, height: int,
                             seed) -> Image.Image:
    """tier4 — subject-specific technical diagram: full parchment technical
    plate with a domain-aware schematic; every part carries a label/measure
    payload (no empty containers).  Reuses the diagram painters' vocabulary
    (engine.diagrams._ridge/_fonts, engine.diagrams_v4._arrow)."""
    vg = _vg(spec)
    accent = vg["accent"]
    ink, navy = (43, 38, 34), (34, 44, 60)
    paper_shadow = (233, 223, 200, 160)
    disp, body = _tier_fonts()
    unit = min(width, height)
    img = _parchment((width, height), seed)
    d = ImageDraw.Draw(img, "RGBA")
    cx = width // 2
    cy = int(height * 0.46)
    terms = _key_terms(spec.get("title") or spec.get("claim")
                       or spec.get("prompt"), 3)
    big = disp(max(28, int(unit * 0.05)))
    small = body(max(16, int(unit * 0.024)))
    d.text((int(width * 0.07), int(height * 0.08)),
           " ".join(terms).upper() or "TECHNICAL DIAGRAM", font=big,
           fill=navy + (255,))
    d.line([(int(width * 0.07), int(height * 0.08) + int(unit * 0.07)),
            (int(width * 0.07) + int(unit * 0.34),
             int(height * 0.08) + int(unit * 0.07))], fill=accent + (255,),
           width=6)
    ovs = (vg["overlays"] * 3)[:3] or ["structure_label", "measurement",
                                       "state_label"]
    t0, t1, t2 = (_overlay_text(k) for k in ovs)
    m = _measure_of(spec.get("prompt"))
    dark = {"text_fill": navy, "shadow": paper_shadow}

    if vg["domain"] == "biology":
        rx, ry = int(unit * 0.34), int(unit * 0.44)
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                  fill=(214, 226, 214, 90), outline=navy + (255,), width=8)
        nx = int(unit * 0.12)
        d.ellipse([cx - nx, cy - nx, cx + nx, cy + nx],
                  outline=accent + (255,), width=7)
        ox, oy = cx + int(rx * 0.5), cy + int(ry * 0.3)
        d.ellipse([ox - 12, oy - 12, ox + 12, oy + 12], fill=accent + (255,))
        _callout(d, (cx - nx, cy), (int(width * 0.10), cy - int(unit * 0.30)),
                 "NUCLEUS", small, accent, frame=img.size, **dark)
        _callout(d, (cx + int(rx * 0.92), cy - int(ry * 0.5)),
                 (int(width * 0.72), cy - int(unit * 0.34)), "MEMBRANE",
                 small, accent, frame=img.size, measure=m or None, **dark)
        _callout(d, (ox, oy), (int(width * 0.68), cy + int(unit * 0.28)),
                 t2, small, accent, frame=img.size, **dark)
    elif vg["domain"] == "physics_mechanism":
        from engine.diagrams_v4 import _arrow
        surf = cy + int(unit * 0.20)
        bw, bh = int(unit * 0.30), int(unit * 0.18)
        d.line([(int(width * 0.10), surf), (int(width * 0.90), surf)],
               fill=navy + (255,), width=9)
        d.rounded_rectangle([cx - bw, surf - bh, cx + bw * 0.2, surf],
                            radius=int(bh * 0.25), fill=(210, 202, 188, 250),
                            outline=navy + (255,), width=6)
        _arrow(d, cx, surf - bh - int(unit * 0.16), cx, surf - bh, accent, w=10)
        _arrow(d, cx + int(unit * 0.06), surf - bh - int(unit * 0.05),
               cx + int(unit * 0.30), surf - bh - int(unit * 0.05), accent, w=8)
        _callout(d, (cx, surf - bh - int(unit * 0.16)),
                 (int(width * 0.66), surf - bh - int(unit * 0.30)), t0,
                 small, accent, frame=img.size, measure=m or None, **dark)
        _callout(d, (cx + int(unit * 0.30), surf - bh - int(unit * 0.05)),
                 (int(width * 0.70), surf + int(unit * 0.08)), t1, small,
                 accent, frame=img.size, **dark)
        _callout(d, (cx + int(bw * 0.1), surf),
                 (int(width * 0.20), surf + int(unit * 0.16)), t2, small,
                 accent, frame=img.size, **dark)
    elif vg["domain"] == "engineering":
        from engine.diagrams_v4 import _arrow
        by = cy
        bx0, bx1, bh = int(width * 0.14), int(width * 0.86), int(unit * 0.07)
        d.rounded_rectangle([bx0, by, bx1, by + bh], radius=bh // 3,
                            fill=(206, 198, 184, 250), outline=navy + (255,),
                            width=6)
        d.polygon([(bx0, by + bh),
                   (bx0 - int(unit * 0.06), by + bh + int(unit * 0.10)),
                   (bx0 + int(unit * 0.06), by + bh + int(unit * 0.10))],
                  outline=navy + (255,), width=5)
        ax = int(width * 0.72)
        _arrow(d, ax, by - int(unit * 0.18), ax, by, accent, w=11)
        fx = int(width * 0.44)
        d.line([(fx - 18, by + bh + 18), (fx + 18, by + bh - 18)],
               fill=accent + (255,), width=8)
        d.line([(fx - 18, by + bh - 18), (fx + 18, by + bh + 18)],
               fill=accent + (255,), width=8)
        _callout(d, (ax, by - int(unit * 0.18)),
                 (int(width * 0.76), by - int(unit * 0.30)), t0, small,
                 accent, frame=img.size, measure=m or None, **dark)
        _callout(d, (fx, by + bh), (int(width * 0.18), by + int(unit * 0.20)),
                 t1, small, accent, frame=img.size, **dark)
        _callout(d, (bx0 + (bx1 - bx0) // 2, by + bh // 2),
                 (int(width * 0.20), by - int(unit * 0.18)), t2, small,
                 accent, frame=img.size, **dark)
    elif vg["domain"] == "geography_environment":
        base_y = cy + int(unit * 0.26)
        pts = _ridge4(cx, base_y, cy - int(unit * 0.22), int(width * 0.40))
        d.polygon([(pts[0][0], base_y)] + pts + [(pts[-1][0], base_y)],
                  fill=(146, 130, 96, 255), outline=navy + (255,), width=6)
        d.line([(int(width * 0.08), base_y), (int(width * 0.92), base_y)],
               fill=navy + (255,), width=6)
        for i in range(4):
            tx = int(width * (0.16 + 0.22 * i))
            d.line([(tx, base_y), (tx, base_y - int(unit * 0.03))],
                   fill=navy + (220,), width=4)
        _callout(d, (cx, cy - int(unit * 0.10)),
                 (int(width * 0.66), cy - int(unit * 0.26)), t0, small,
                 accent, frame=img.size, measure=m or None, **dark)
        _callout(d, (int(width * 0.20), base_y),
                 (int(width * 0.10), base_y + int(unit * 0.10)), t1, small,
                 accent, frame=img.size, **dark)
        _callout(d, (int(width * 0.84), base_y),
                 (int(width * 0.70), base_y + int(unit * 0.10)), t2, small,
                 accent, frame=img.size, **dark)
    elif vg["domain"] == "history":
        ay = cy
        x0, x1 = int(width * 0.12), int(width * 0.88)
        d.line([(x0, ay), (x1, ay)], fill=navy + (255,), width=8)
        for i in range(3):
            mx = x0 + int((x1 - x0) * (0.12 + 0.38 * i))
            d.ellipse([mx - 14, ay - 14, mx + 14, ay + 14],
                      fill=(accent if i == 1 else navy) + (255,))
            tip_y = ay - int(unit * (0.16 if i == 1 else 0.08))
            d.line([(mx, ay), (mx, tip_y)], fill=navy + (200,), width=4)
            _shadow_text(d, (mx - int(unit * 0.06), tip_y - int(unit * 0.05)),
                         f"PHASE {i + 1}" + (f" · {m}" if i == 1 and m else ""),
                         small, navy)
    elif vg["domain"] == "everyday_science":
        from engine.diagrams_v4 import _arrow
        hw, hh = int(unit * 0.26), int(unit * 0.30)
        d.rounded_rectangle([cx - hw, cy - hh, cx + hw, cy + hh],
                            radius=int(min(hw, hh) * 0.3),
                            fill=(206, 198, 184, 250), outline=navy + (255,),
                            width=7)
        _arrow(d, cx - int(unit * 0.4), cy, cx - hw - 12, cy, accent, w=9)
        _arrow(d, cx + hw + 12, cy, cx + int(unit * 0.4), cy, accent, w=9)
        _callout(d, (cx - hw - 12, cy), (int(width * 0.10), cy - int(unit * 0.18)),
                 t0, small, accent, frame=img.size, **dark)
        _callout(d, (cx + hw + 12, cy), (int(width * 0.70), cy - int(unit * 0.18)),
                 t1, small, accent, frame=img.size, measure=m or None, **dark)
        _callout(d, (cx, cy + hh), (int(width * 0.62), cy + int(unit * 0.24)),
                 t2, small, accent, frame=img.size, **dark)
    else:
        hw, hh = int(unit * 0.30), int(unit * 0.22)
        d.rounded_rectangle([cx - hw, cy - hh, cx + hw, cy + hh],
                            radius=int(min(hw, hh) * 0.28),
                            fill=(206, 198, 184, 250), outline=navy + (255,),
                            width=7)
        ex, ey = cx - int(hw * 0.35), cy
        er = int(hh * 0.5)
        d.ellipse([ex - er, cy - er, ex + er, cy + er],
                  outline=accent + (255,), width=6)
        _callout(d, (cx - int(hw * 0.2), cy - hh),
                 (int(width * 0.14), cy - int(unit * 0.24)), t0, small,
                 accent, frame=img.size, **dark)
        _callout(d, (ex, cy), (int(width * 0.66), cy - int(unit * 0.20)),
                 t1, small, accent, frame=img.size, **dark)
        _callout(d, (cx + int(hw * 0.6), cy + hh),
                 (int(width * 0.70), cy + int(unit * 0.18)), t2, small,
                 accent, frame=img.size, measure=m or None, **dark)
    _shadow_text(d, (int(width * 0.07), int(height * 0.90)),
                 f"TECHNICAL DIAGRAM · {vg['domain'].upper()}", small,
                 (122, 106, 82))
    return _vignette(img, strength=70)


def _ridge4(cx, base_y, peak_y, half_w):
    """_ridge re-exported lazily so a diagrams import failure raises inside
    the tier (and descends) rather than at module import."""
    from engine.diagrams import _ridge
    return _ridge(cx, base_y, peak_y, half_w, sharp=2.4)


def _tier5_simple_diagram(spec: dict, width: int, height: int,
                          seed) -> Image.Image:
    """tier5 — simple diagram.  Allowed ONLY when the shot's M2
    visual_grammar composition is the justified presentation panel."""
    vg = _vg(spec)
    comp = vg["composition"]
    if not comp.endswith("panel"):
        raise ValueError(f"tier5 gate: composition '{comp}' is not a "
                         f"justified panel — simple diagram not allowed")
    img = _parchment((width, height), seed)
    d = ImageDraw.Draw(img, "RGBA")
    navy = (34, 44, 60)
    disp, body = _tier_fonts()
    unit = min(width, height)
    cx, cy = width // 2, int(height * 0.44)
    terms = _key_terms(spec.get("title") or spec.get("claim")
                       or spec.get("prompt"), 3)
    label = " ".join(terms).upper() or "DIAGRAM"
    hw, hh = int(unit * 0.26), int(unit * 0.16)
    d.rounded_rectangle([cx - hw, cy - hh, cx + hw, cy + hh],
                        radius=int(min(hw, hh) * 0.3),
                        fill=(206, 198, 184, 250), outline=navy + (255,),
                        width=6)
    _shadow_text(d, (cx - hw, cy - hh - int(unit * 0.08)), label,
                 body(max(18, int(unit * 0.028))), navy)
    m = _measure_of(spec.get("prompt"))
    _callout(d, (cx + hw, cy), (int(width * 0.66), cy + int(unit * 0.14)),
             _overlay_text((vg["overlays"] or ["object_label"])[0]),
             body(max(16, int(unit * 0.024))), vg["accent"],
             text_fill=navy, shadow=(233, 223, 200, 160), frame=img.size,
             measure=m or None)
    return _vignette(img, strength=60)


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
                if g.get("status") not in ("deferred_to_M3", "derived"):
                    errors.append("generation.depth.status must be "
                                  "deferred_to_M3 or derived")
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

def _descend_tiers(spec: dict, width: int, height: int, seed,
                   tier: dict) -> Image.Image:
    """V13B M3 - directive P0 tier descent.  Try tier2 through tier5 in
    order and return the first success; every attempt (ok or failed) is
    appended to tier["attempts"].  tier5 self-gates on justified panel
    compositions.  Raises RuntimeError when no allowed tier produces an
    image (caller records asset_tier="failed")."""
    chain = (("tier2_rich_procedural", _tier2_fullframe_scene),
             ("tier3_layered_hybrid", _tier3_layered_hybrid),
             ("tier4_technical_diagram", _tier4_technical_diagram),
             ("tier5_simple_diagram", _tier5_simple_diagram))
    last: Exception | None = None
    for name, fn in chain:
        try:
            img = fn(spec, width, height, seed)
        except Exception as exc:  # noqa: BLE001 - descent survives tier failures
            tier["attempts"].append({"tier": name, "ok": False,
                                     "note": str(exc)[:160]})
            last = exc
            continue
        tier["attempts"].append({"tier": name, "ok": True})
        tier["asset_tier"] = name
        tier["tier_method"] = f"{name} (deterministic fallback)"
        return img
    raise RuntimeError(f"all V13B tiers failed; last error: {last}")


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
    tier: dict = {"asset_tier": None, "tier_method": None, "attempts": []}

    # ── stage 1: composition ────────────────────────────────────────────
    if dry_run:
        img = _placeholder_image(seed, width, height)
        gen["composition"] = {"provider": "placeholder",
                              "model": "deterministic-kitlib", "seed": seed,
                              "mode": "placeholder", "degraded": True,
                              "note": "dry_run: deterministic placeholder requested"}
        tier["asset_tier"] = "failed"
        tier["tier_method"] = "dry_run placeholder (not publishable)"
    else:
        provider = _get_factory().get(spec.get("provider", "pollinations"))
        img, rec = _compose(provider, spec, seed, gen_w, gen_h, out_dir)
        if img is None:
            # V13B M3 tier descent (directive P0): the bare gradient
            # placeholder is retired as publishable - descend deterministic
            # tiers; every attempt is recorded for QA visibility.
            attempted, rec["attempted_provider"] = rec.get("provider"), rec.get("provider")
            tier["attempts"].append({"tier": "tier1_rich_plate", "ok": False,
                                     "note": f"provider failed ({attempted})"})
            try:
                img = _descend_tiers(spec, width, height, seed, tier)
                rec["provider"], rec["model"] = "procedural", tier["tier_method"]
                rec["mode"] = tier["asset_tier"]
                rec["degraded"] = True
                rec["note"] = (f"AI composition failed ({attempted}); "
                               f"descended to {tier['asset_tier']}")
            except Exception as _texc:  # noqa: BLE001 - publish-block, not silent
                img = _placeholder_image(seed, width, height)
                rec["provider"], rec["model"] = "placeholder", "deterministic-kitlib"
                rec["mode"] = "placeholder"
                rec["degraded"] = True
                rec["note"] = (f"provider failed ({attempted}) AND tier descent "
                               f"failed ({_texc}); unpublishable placeholder")
                tier["asset_tier"] = "failed"
                tier["tier_method"] = "all tiers failed (unpublishable)"
        gen["composition"] = rec

    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    plate_path = out_dir / f"{asset}.png"
    img.save(plate_path)

    procedural_fallback = tier["asset_tier"] not in (None, "tier1_rich_plate")

    # ── stage 2: detail / material ──────────────────────────────────────
    if dry_run or tier["asset_tier"] != "tier1_rich_plate":
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
    if dry_run or tier["asset_tier"] != "tier1_rich_plate":
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

    # ── stage 4: depth / edge (V13 M3 real-mask derivation) ─────────────
    _depth_result = None
    try:
        from engine.depth_layers import derive_masks as _derive_masks
        _depth_result = _derive_masks(plate_path)
    except Exception:
        _depth_result = None
    if _depth_result and (_depth_result.get("masks") or {}):
        gen["depth"] = {"provider": "depth_layers",
                        "model": _depth_result.get("method"), "seed": None,
                        "status": "derived", "depth_map": None,
                        "seconds": _depth_result.get("seconds"),
                        "note": "V13 M3 real-mask 2.5D derivation "
                                "(CPU, deterministic)"}
    else:
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
        "asset_tier": tier["asset_tier"],
        "tier_method": tier["tier_method"],
        "tier_attempts": tier["attempts"],
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
                                 if tier["asset_tier"] == "failed"
                                 else (["procedural_scene"]
                                       if procedural_fallback
                                       else ["illustration"]))),
        "lighting": spec.get("lighting", "soft ambient"),
    }

    # V13 M3 — stamp derived masks onto the declared layers (empty coverage
    # earns no parallax weight, mirroring depth_layers._apply_to_sidecar).
    if _depth_result:
        _masks = _depth_result.get("masks") or {}
        _cov = _depth_result.get("coverage") or {}
        for _layer in sidecar["layers"]:
            _m = _masks.get(_layer["name"])
            _layer["mask"] = _rel(_m) if _m else None
            if _m and _cov.get(_layer["name"], 0.0) < 0.005:
                _layer["parallax_weight"] = 0.0

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
