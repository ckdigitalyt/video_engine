"""V13 M6b — SVG evidence layer (docs/directives/JADE_V13_RICH_VISUAL_DIRECTIVE.md P1).

Emits the crisp evidence overlays that sit ON TOP of rich plates: callouts,
labeled arrows, measurement marks, and board diagrams. Per the directive,
SVG becomes the scientific/evidence layer above rich imagery — upgraded from
flat fills to gradients / masking / clip-paths / soft glow so evidence reads
as authored craft, not clip-art.

Two emit paths, selected ONLY by the flag:

  upgraded (V13_SVG on, default)
      <defs> hold one accent + parchment-neutral linearGradients (fills and
      strokes), a radialGradient emphasis pool, an edge-fade <mask> for soft
      fade-ins at the layer boundary, one <clipPath> per declared rect
      (reused from planv8 key_number_rect / plate sidecar
      annotation_rects_px when available), and a feGaussianBlur glow filter.
      Glow is applied ONLY to emphasis marks (arrows, keystone dots) — blur
      on text is forbidden, and body text is never filtered.

  legacy (V13_SVG=0)
      Flat-fill SVG with zero <defs>, byte-identical to the pre-M6b emit.
      The legacy emit function is separate and untouched by the upgrade, so
      rollback is exact.

Text rendering rules are intact: both paths share one text emitter, so the
serialized <text> elements are identical across flag states (asserted by the
self-test). Bebas tofu / caption-band QA live downstream and are unaffected.

Evidence spec (all coordinates in the evidence layer's own px space):

    {
      "id": "beat07-evidence",
      "canvas": [1080, 1744],
      "palette": {"background": ..., "muted": ..., "text": ..., "accent": ...},
      "clip_rects": [{"id": "key_number", "rect": [x0, y0, x1, y1]}, ...],
      "items": [
        {"kind": "callout", "at": [x, y], "tip": [x, y], "label": "TEXT"},
        {"kind": "arrow",   "from": [x, y], "to": [x, y], "label": "..."},
        {"kind": "measure", "from": [x, y], "to": [x, y], "value": "20 KM"},
        {"kind": "board",   "rect": [x, y, w, h], "cells": [x, y, w, h], ...},
      ],
    }

Emit is fully deterministic (no clock, no randomness).
"""

from __future__ import annotations

import re

from engine.flags import svg13

_SAFE = re.compile(r"[^A-Za-z0-9_-]+")

# Parchment-adjacent neutrals + one accent. Used when the spec carries no
# palette (e.g. offline self-tests); production callers pass bible palette.
_DEFAULT_PALETTE = {
    "background": "#EDE4D3",   # parchment field
    "background_hi": "#F7F1E3",  # parchment highlight (gradient top)
    "background_lo": "#DED2B8",  # parchment shade (gradient bottom)
    "muted": "#8A8073",        # secondary stroke / ticks
    "text": "#23303F",         # ink
    "accent": "#B4552D",       # THE one accent (rust)
}

_GLOW_ID = "evGlow"
_EDGE_MASK_ID = "evEdgeFade"
_FILL_GRAD_ID = "evFillGrad"
_STROKE_GRAD_ID = "evStrokeGrad"
_POOL_GRAD_ID = "evPoolGrad"


def _uid(spec_id: str, name: str) -> str:
    return _SAFE.sub("-", f"{spec_id or 'ev'}") + "-" + name


def _fmt(v) -> str:
    if isinstance(v, float):
        s = f"{v:.1f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return str(v)


def _pt(v) -> str:
    return f"{_fmt(v[0])},{_fmt(v[1])}"


def _hex(pal: dict, key: str) -> str:
    v = pal.get(key) or _DEFAULT_PALETTE[key]
    v = str(v).strip()
    return v if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else _DEFAULT_PALETTE[key]


def _arrow_head(tip, src, size=14.0):
    """Unit arrowhead points at tip, oriented away from src."""
    dx, dy = tip[0] - src[0], tip[1] - src[1]
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / n, dy / n
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    px, py = -uy, ux
    w = size * 0.45
    return [(tip[0], tip[1]), (bx + px * w, by + py * w),
            (bx - px * w, by - py * w)]


def _bbox_inside(rect, bounds) -> bool:
    if rect is None:
        return False
    x0, y0, x1, y1 = bounds
    rx0, ry0, rx1, ry1 = rect
    return rx0 <= x0 and ry0 <= y0 and rx1 >= x1 and ry1 >= y1


def _clip_for(item: dict, clip_rects: list, canvas) -> str | None:
    """First declared rect that fully contains the item geometry."""
    k = item.get("kind")
    if k in ("arrow", "measure"):
        a, b = item.get("from"), item.get("to")
        if not a or not b:
            return None
        bounds = (min(a[0], b[0]), min(a[1], b[1]),
                  max(a[0], b[0]), max(a[1], b[1]))
    elif k == "callout":
        a, b = item.get("at"), item.get("tip")
        if not a or not b:
            return None
        bounds = (min(a[0], b[0]), min(a[1], b[1]),
                  max(a[0], b[0]), max(a[1], b[1]))
    elif k == "board":
        r = item.get("rect")
        if not r or len(r) != 4:
            return None
        bounds = (r[0], r[1], r[0] + r[2], r[1] + r[3])
    else:
        return None
    for cr in clip_rects:
        if _bbox_inside(cr.get("rect"), bounds):
            return cr.get("id")
    return None


def clip_rects_from_plan(beat: dict, sidecar: dict | None = None) -> list:
    """Declared rects from planv8 + plate sidecar, reused when available."""
    out = []
    r = beat.get("key_number_rect")
    if r and len(r) == 4:
        out.append({"id": "key_number", "rect": [float(v) for v in r]})
    for a in ((sidecar or {}).get("annotation_rects_px") or []):
        if isinstance(a, dict) and a.get("id") and len(a.get("bbox") or []) == 4:
            out.append({"id": f"annot-{a['id']}",
                        "rect": [float(v) for v in a["bbox"]]})
    return out


# --------------------------------------------------------------- text ----
# ONE text emitter for both paths: text elements are byte-identical across
# flag states. Never filtered, never gradient-filled.

def _text_el(x, y, label, size, pal, anchor="start", opacity="1") -> str:
    op = "" if opacity == "1" else f' opacity="{opacity}"'
    return (f'<text x="{_fmt(x)}" y="{_fmt(y)}" '
            f'font-family="Bebas Neue, Arial Narrow, sans-serif" '
            f'font-size="{_fmt(size)}" fill="{_hex(pal, "text")}" '
            f'text-anchor="{anchor}" letter-spacing="1"{op}>'
            f'{label}</text>')


def _text_nodes(items: list, pal: dict) -> list[str]:
    out = []
    for it in items:
        k = it.get("kind")
        if k == "callout":
            t, tip = it.get("at"), it.get("tip", it.get("at"))
            if t:
                out.append(_text_el(t[0] + 6, t[1] - 10, it.get("label", ""),
                                    30, pal))
        elif k == "arrow":
            t = it.get("to")
            if t:
                out.append(_text_el(t[0] + 12, t[1] - 12, it.get("label", ""),
                                    28, pal))
        elif k == "measure":
            a, b = it.get("from", [0, 0]), it.get("to", [0, 0])
            out.append(_text_el((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 14,
                                it.get("value", ""), 26, pal, anchor="middle"))
        elif k == "board":
            r = it.get("rect")
            if r and len(r) == 4:
                out.append(_text_el(r[0] + 16, r[1] + 44,
                                    it.get("title", ""), 34, pal))
    return out


# ------------------------------------------------------------- legacy ----

def _emit_legacy(spec: dict) -> str:
    """Pre-M6b flat-fill emit. Zero defs. Rollback target — do not upgrade
    this function; changes belong in _emit_upgraded only."""
    pal = spec.get("palette") or {}
    canvas = spec.get("canvas") or [1080, 1744]
    ink = _hex(pal, "text")
    accent = _hex(pal, "accent")
    muted = _hex(pal, "muted")
    body: list[str] = []
    for it in spec.get("items") or []:
        k = it.get("kind")
        if k == "callout":
            t, tip = it.get("at"), it.get("tip")
            if t and tip:
                body.append(f'<line x1="{_fmt(tip[0])}" y1="{_fmt(tip[1])}" '
                            f'x2="{_fmt(t[0])}" y2="{_fmt(t[1])}" '
                            f'stroke="{ink}" stroke-width="2"/>')
                body.append(f'<circle cx="{_fmt(t[0])}" cy="{_fmt(t[1])}" '
                            f'r="5" fill="{accent}"/>')
        elif k == "arrow":
            a, b = it.get("from"), it.get("to")
            if a and b:
                pts = " ".join(_pt(p) for p in _arrow_head(b, a))
                body.append(f'<line x1="{_fmt(a[0])}" y1="{_fmt(a[1])}" '
                            f'x2="{_fmt(b[0])}" y2="{_fmt(b[1])}" '
                            f'stroke="{accent}" stroke-width="5"/>')
                body.append(f'<polygon points="{pts}" fill="{accent}"/>')
        elif k == "measure":
            a, b = it.get("from"), it.get("to")
            if a and b:
                body.append(f'<line x1="{_fmt(a[0])}" y1="{_fmt(a[1])}" '
                            f'x2="{_fmt(b[0])}" y2="{_fmt(b[1])}" '
                            f'stroke="{muted}" stroke-width="3"/>')
                body.append(f'<line x1="{_fmt(a[0])}" y1="{_fmt(a[1] - 10)}" '
                            f'x2="{_fmt(a[0])}" y2="{_fmt(a[1] + 10)}" '
                            f'stroke="{muted}" stroke-width="3"/>')
                body.append(f'<line x1="{_fmt(b[0])}" y1="{_fmt(b[1] - 10)}" '
                            f'x2="{_fmt(b[0])}" y2="{_fmt(b[1] + 10)}" '
                            f'stroke="{muted}" stroke-width="3"/>')
        elif k == "board":
            r = it.get("rect")
            if r and len(r) == 4:
                body.append(f'<rect x="{_fmt(r[0])}" y="{_fmt(r[1])}" '
                            f'width="{_fmt(r[2])}" height="{_fmt(r[3])}" '
                            f'fill="{_hex(pal, "background")}" '
                            f'stroke="{muted}" stroke-width="2"/>')
                for c in it.get("cells") or []:
                    body.append(f'<rect x="{_fmt(c[0])}" y="{_fmt(c[1])}" '
                                f'width="{_fmt(c[2])}" height="{_fmt(c[3])}" '
                                f'fill="{_hex(pal, "background")}" '
                                f'stroke="{muted}" stroke-width="2"/>')
    body.extend(_text_nodes(spec.get("items") or [], pal))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_fmt(canvas[0])} {_fmt(canvas[1])}" '
            f'width="{_fmt(canvas[0])}" height="{_fmt(canvas[1])}">'
            + "".join(body) + "</svg>")


# ----------------------------------------------------------- upgraded ----

def _defs(spec_id: str, pal: dict, clip_rects: list, canvas) -> str:
    w, h = canvas
    fill_g = _uid(spec_id, _FILL_GRAD_ID)
    stroke_g = _uid(spec_id, _STROKE_GRAD_ID)
    pool_g = _uid(spec_id, _POOL_GRAD_ID)
    fade = _uid(spec_id, _EDGE_MASK_ID)
    hi, lo = _hex(pal, "background_hi"), _hex(pal, "background_lo")
    accent = _hex(pal, "accent")
    clips = "".join(
        f'<clipPath id="{_uid(spec_id, "clip-" + cr["id"])}"><rect '
        f'x="{_fmt(cr["rect"][0])}" y="{_fmt(cr["rect"][1])}" '
        f'width="{_fmt(cr["rect"][2] - cr["rect"][0])}" '
        f'height="{_fmt(cr["rect"][3] - cr["rect"][1])}"/></clipPath>'
        for cr in clip_rects if len(cr.get("rect") or []) == 4)
    # Edge fade: horizontal + vertical gradients stacked in one mask; white
    # core, soft falloff inside the outer 4% of each edge (fade-in zone).
    e = min(w, h) * 0.04
    return (
        "<defs>"
        f'<linearGradient id="{fill_g}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{hi}"/>'
        f'<stop offset="1" stop-color="{lo}"/></linearGradient>'
        f'<linearGradient id="{stroke_g}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{_hex(pal, "text")}"/>'
        f'<stop offset="1" stop-color="{_hex(pal, "muted")}"/></linearGradient>'
        f'<radialGradient id="{pool_g}" cx="0.5" cy="0.5" r="0.5">'
        f'<stop offset="0" stop-color="{accent}" stop-opacity="0.30"/>'
        f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/>'
        "</radialGradient>"
        f'<mask id="{fade}">'
        f'<rect x="0" y="0" width="{_fmt(w)}" height="{_fmt(h)}" '
        'fill="#fff"/>'
        f'<rect x="0" y="0" width="{_fmt(w)}" height="{_fmt(e)}" '
        f'fill="url(#{fade}g)"/>'
        f'<rect x="0" y="{_fmt(h - e)}" width="{_fmt(w)}" height="{_fmt(e)}" '
        f'fill="url(#{fade}g)" transform="rotate(180 {_fmt(w / 2)} '
        f'{_fmt(h / 2)})"/>'
        f'<rect x="0" y="0" width="{_fmt(e)}" height="{_fmt(h)}" '
        f'fill="url(#{fade}gv)"/>'
        f'<rect x="{_fmt(w - e)}" y="0" width="{_fmt(e)}" height="{_fmt(h)}" '
        f'fill="url(#{fade}gv)" transform="rotate(180 {_fmt(w / 2)} '
        f'{_fmt(h / 2)})"/>'
        f'<linearGradient id="{fade}g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#000"/>'
        '<stop offset="1" stop-color="#fff"/></linearGradient>'
        f'<linearGradient id="{fade}gv" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#000"/>'
        '<stop offset="1" stop-color="#fff"/></linearGradient>'
        "</mask>"
        f'<filter id="{_uid(spec_id, _GLOW_ID)}" x="-60%" y="-60%" '
        'width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="6" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/>'
        "</feMerge></filter>"
        + clips +
        "</defs>")


def _emit_upgraded(spec: dict) -> str:
    pal = spec.get("palette") or {}
    canvas = spec.get("canvas") or [1080, 1744]
    spec_id = str(spec.get("id") or "ev")
    clip_rects = [cr for cr in (spec.get("clip_rects") or [])
                  if cr.get("id") and len(cr.get("rect") or []) == 4]
    fill_g = _uid(spec_id, _FILL_GRAD_ID)
    stroke_g = _uid(spec_id, _STROKE_GRAD_ID)
    pool_g = _uid(spec_id, _POOL_GRAD_ID)
    fade = _uid(spec_id, _EDGE_MASK_ID)
    glow = _uid(spec_id, _GLOW_ID)
    accent = _hex(pal, "accent")
    marks: list[str] = []
    keystone: list[str] = []
    for it in spec.get("items") or []:
        k = it.get("kind")
        cp = _clip_for(it, clip_rects, canvas)
        clip = f' clip-path="url(#{_uid(spec_id, "clip-" + cp)})"' if cp else ""
        if k == "callout":
            t, tip = it.get("at"), it.get("tip")
            if t and tip:
                marks.append(f'<g{clip}>'
                             f'<line x1="{_fmt(tip[0])}" y1="{_fmt(tip[1])}" '
                             f'x2="{_fmt(t[0])}" y2="{_fmt(t[1])}" '
                             f'stroke="url(#{stroke_g})" stroke-width="2"/>'
                             f'<circle cx="{_fmt(t[0])}" cy="{_fmt(t[1])}" '
                             f'r="5" fill="{accent}"/></g>')
                keystone.append(f'<circle cx="{_fmt(t[0])}" '
                                f'cy="{_fmt(t[1])}" r="5" fill="{accent}"/>')
        elif k == "arrow":
            a, b = it.get("from"), it.get("to")
            if a and b:
                pts = " ".join(_pt(p) for p in _arrow_head(b, a))
                marks.append(f'<g{clip}>'
                             f'<line x1="{_fmt(a[0])}" y1="{_fmt(a[1])}" '
                             f'x2="{_fmt(b[0])}" y2="{_fmt(b[1])}" '
                             f'stroke="url(#{stroke_g})" stroke-width="5"/>'
                             f'<polygon points="{pts}" fill="{accent}"/></g>')
        elif k == "measure":
            a, b = it.get("from"), it.get("to")
            if a and b:
                tick = (f'stroke="url(#{stroke_g})" stroke-width="3"')
                marks.append(f'<g{clip}>'
                             f'<line x1="{_fmt(a[0])}" y1="{_fmt(a[1])}" '
                             f'x2="{_fmt(b[0])}" y2="{_fmt(b[1])}" {tick}/>'
                             f'<line x1="{_fmt(a[0])}" y1="{_fmt(a[1] - 10)}" '
                             f'x2="{_fmt(a[0])}" y2="{_fmt(a[1] + 10)}" '
                             f'{tick}/>'
                             f'<line x1="{_fmt(b[0])}" y1="{_fmt(b[1] - 10)}" '
                             f'x2="{_fmt(b[0])}" y2="{_fmt(b[1] + 10)}" '
                             f'{tick}/></g>')
        elif k == "board":
            r = it.get("rect")
            if r and len(r) == 4:
                cell_fill = (f'fill="url(#{fill_g})"')
                marks.append(f'<g{clip}>'
                             f'<rect x="{_fmt(r[0])}" y="{_fmt(r[1])}" '
                             f'width="{_fmt(r[2])}" height="{_fmt(r[3])}" '
                             f'{cell_fill} stroke="url(#{stroke_g})" '
                             f'stroke-width="2"/>')
                for c in it.get("cells") or []:
                    marks.append(f'<rect x="{_fmt(c[0])}" y="{_fmt(c[1])}" '
                                 f'width="{_fmt(c[2])}" height="{_fmt(c[3])}" '
                                 f'{cell_fill} stroke="url(#{stroke_g})" '
                                 'stroke-width="2"/>')
                marks.append("</g>")
    texts = _text_nodes(spec.get("items") or [], pal)
    pool = (f'<circle cx="{_fmt(canvas[0] / 2)}" '
            f'cy="{_fmt(canvas[1] / 2)}" r="{_fmt(min(canvas) * 0.42)}" '
            f'fill="url(#{pool_g})"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {_fmt(canvas[0])} {_fmt(canvas[1])}" '
            f'width="{_fmt(canvas[0])}" height="{_fmt(canvas[1])}">'
            + _defs(spec_id, pal, clip_rects, canvas)
            + f'<g mask="url(#{fade})">'
            + pool
            + f'<g filter="url(#{glow})">' + "".join(keystone) + "</g>"
            + "".join(marks)
            + "</g>"
            + "".join(texts) + "</svg>")


def emit_evidence(spec: dict) -> str:
    """Emit the evidence-layer SVG. V13_SVG=0 -> byte-identical legacy emit;
    default -> upgraded emit (gradients + edge-fade mask + clip-paths +
    glow on emphasis marks only)."""
    if svg13():
        return _emit_upgraded(spec)
    return _emit_legacy(spec)
