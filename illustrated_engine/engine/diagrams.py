"""Programmatic diagram plates (P2-9 / P7) — deterministic, born on-palette.

Scientific concepts that are clearer as diagrams get drawn, not generated:
scale comparison, hotspot timeline, above/below-waterline comparison, payoff
scale visualisation. All drawn in the Visual Bible palette on parchment
(inverse-video chrome stays out of the artwork, matching graded plates).
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from engine.layout import FONT_DIR, VISUAL_RECT

VW, VH = VISUAL_RECT[2], VISUAL_RECT[3]  # 1080x1328


def _fonts(bible):
    typ = bible.get("typography", {})
    disp = lambda s: ImageFont.truetype(str(FONT_DIR / typ.get("display", "BebasNeue-Regular.ttf")), s)
    body = lambda s: ImageFont.truetype(str(FONT_DIR / typ.get("body", "Inter-Variable.ttf")), s)
    return disp, body


def _card(bible) -> tuple:
    """Parchment card filling the visual zone + ink/accent colours."""
    from engine import bible as B
    paper = B.rgb255(bible, "muted")  # placeholder, overridden below
    paper = (233, 223, 200)           # parchment matches the plate family
    ink = B.rgb255(bible, "text")
    navy = B.rgb255(bible, "primary")
    accent = B.rgb255(bible, "accent")
    img = Image.new("RGB", (VW, VH), paper)
    # subtle paper mottling (seeded)
    rng = np.random.default_rng(23)
    arr = np.asarray(img).astype(np.float32)
    arr += rng.normal(0, 3.0, arr.shape).astype(np.float32)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return img, ImageDraw.Draw(img, "RGBA"), ink, navy, accent


def _ridge(cx, base_y, peak_y, half_w, sharp=2.2, n=64):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = cx - half_w + 2 * half_w * t
        y = base_y - (base_y - peak_y) * (1 - abs(2 * t - 1) ** sharp)
        pts.append((x, y))
    return pts


def _dashed_line(d, p0, p1, fill, width=3, dash=14):
    x0, y0 = p0
    x1, y1 = p1
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 1:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    t = 0.0
    while t < L:
        e = min(t + dash, L)
        d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e)], fill=fill, width=width)
        t += 2 * dash


def scale_compare(bible) -> Image.Image:
    """Mauna Kea (base-to-peak) vs Everest (sea-to-peak), shared sea level."""
    img, d, ink, navy, accent = _card(bible)
    disp, body = _fonts(bible)
    sea_y = int(VH * 0.42)
    floor_y = int(VH * 0.90)
    top_mk = int(VH * 0.10)          # 10,210 m top
    top_ev = sea_y - int((sea_y - top_mk) * (8849 / 10210))

    d.line([(70, sea_y), (VW - 70, sea_y)], fill=navy + (255,), width=4)
    d.text((80, sea_y + 8), "SEA LEVEL", font=body(26), fill=navy + (230,))

    # Everest (left): above sea only
    pts = _ridge(VW * 0.28, sea_y, top_ev, 210, sharp=2.6)
    d.polygon(pts, fill=ink + (235,))
    d.line(pts + [pts[0]], fill=ink + (255,), width=3)
    # Mauna Kea (right): above + dashed below sea
    pts_mk = _ridge(VW * 0.72, floor_y, top_mk, 330, sharp=1.25)
    d.polygon([(x, max(y, sea_y)) for x, y in pts_mk], fill=ink + (225,))
    d.line([(x, y) for x, y in pts_mk if y <= sea_y], fill=ink + (255,), width=3)
    below = [(x, y) for x, y in pts_mk if y > sea_y]
    for i in range(len(below) - 1):
        _dashed_line(d, below[i], below[i + 1], ink + (170,), width=3)
    # ocean fill hint below sea line, behind nothing (light navy wash)
    wash = Image.new("RGBA", (VW, VH), navy + (26,))
    img.paste(Image.alpha_composite(img.convert("RGBA"), wash).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    d.line([(70, sea_y), (VW - 70, sea_y)], fill=navy + (255,), width=4)

    # measurement bars
    d.line([(VW * 0.28, top_ev), (VW * 0.28, sea_y)], fill=accent + (255,), width=4)
    d.text((VW * 0.28 - 90, (top_ev + sea_y) / 2 - 22), "8,849 m", font=disp(46), fill=accent + (255,))
    d.line([(VW * 0.72 + 300, top_mk), (VW * 0.72 + 300, floor_y)], fill=accent + (255,), width=4)
    d.text((VW * 0.72 + 140, (top_mk + floor_y) / 2 - 22), "10,210 m", font=disp(46), fill=accent + (255,))

    d.text((VW * 0.28, sea_y + 26), "EVEREST", font=body(30), fill=navy + (255,))
    d.text((VW * 0.72 - 60, top_mk - 46), "MAUNA KEA", font=body(30), fill=navy + (255,))
    d.text((80, floor_y - 44), "OCEAN FLOOR", font=body(24), fill=navy + (200,))
    return img


def timeline_diagram(bible) -> Image.Image:
    """Hotspot island-building timeline: 4 stages, left to right."""
    img, d, ink, navy, accent = _card(bible)
    disp, body = _fonts(bible)
    stages = [
        ("~1M YEARS AGO", "Seafloor eruption", 0.12),
        ("SHIELD BUILDING", "Layer upon layer", 0.36),
        ("SUMMIT EMERGES", "Breaks the surface", 0.62),
        ("TODAY", "4,207 m above sea", 0.86),
    ]
    axis_y = int(VH * 0.72)
    d.line([(80, axis_y), (VW - 80, axis_y)], fill=navy + (255,), width=5)
    for i, (t, s, fx) in enumerate(stages):
        cx = int(VW * fx)
        h = int(VH * (0.10 + 0.05 * i))
        base = axis_y - 10
        pts = _ridge(cx, base, base - h, 120, sharp=1.4)
        d.polygon(pts, fill=navy + (170,))
        d.ellipse([cx - 12, axis_y - 12, cx + 12, axis_y + 12], fill=accent + (255,))
        # staggered label rows: adjacent stages never share a baseline, so
        # each label gets the full card width — no horizontal crowding
        row = i % 2
        ly = axis_y + 26 + row * 84
        ft, fs = body(25), body(23)
        tw = max(d.textlength(t, font=ft), d.textlength(s, font=fs))
        lx = min(max(cx - tw / 2, 40), VW - 40 - tw)
        if row:  # tick from the axis dot down to the offset label row
            d.line([(cx, axis_y + 14), (cx, ly - 8)], fill=navy + (120,), width=3)
        d.text((lx, ly), t, font=ft, fill=navy + (235,))
        d.text((lx, ly + 34), s, font=fs, fill=navy + (220,))
        if i < 3:  # drawn arrow — Bebas has no "→" glyph (renders as tofu)
            ax, ay = cx + 60, axis_y - 60
            d.line([(ax, ay), (ax + 52, ay)], fill=accent + (255,), width=7)
            d.line([(ax + 34, ay - 16), (ax + 52, ay)], fill=accent + (255,), width=7)
            d.line([(ax + 34, ay + 16), (ax + 52, ay)], fill=accent + (255,), width=7)
    d.text((80, int(VH * 0.08)), "ONE HOTSPOT, ONE MILLION YEARS",
           font=disp(56), fill=navy + (255,))
    return img


def split_compare(bible, plate_img: Image.Image) -> Image.Image:
    """Above/below-waterline comparison from one plate (reuse, no new asset)."""
    img, d, ink, navy, accent = _card(bible)
    disp, body = _fonts(bible)
    wl = int(VH * 0.46)  # waterline
    from engine.layout import smart_crop
    top = smart_crop(plate_img, VW, wl, bias_y=0.35)
    bot = smart_crop(plate_img, VW, VH - wl, bias_y=0.75)
    img.paste(top, (0, 0))
    # underwater treatment: navy multiply + darken
    bot_a = np.asarray(bot).astype(np.float32)
    tint = np.array([0.30, 0.45, 0.85], np.float32)[None, None, :]
    bot_a = bot_a * 0.55 * (1 - 0.45) + bot_a * 0.45 * 0 + (bot_a * tint) * 0.45
    bot = Image.fromarray(np.clip(bot_a, 0, 255).astype(np.uint8))
    img.paste(bot, (0, wl))
    d = ImageDraw.Draw(img, "RGBA")
    d.line([(0, wl), (VW, wl)], fill=(233, 223, 200, 255), width=6)
    d.text((70, wl - 60), "ABOVE: 4,207 m", font=disp(52), fill=(233, 223, 200, 255))
    d.text((70, wl + 28), "BELOW: 6,003 m", font=disp(52), fill=(200, 214, 236, 255))
    d.text((VW - 330, wl - 44), "SEA LEVEL", font=body(28), fill=(233, 223, 200, 230))
    return img


def payoff_diagram(bible) -> Image.Image:
    """Final scale visualisation: highest vs tallest, overlaid + typography."""
    img, d, ink, navy, accent = _card(bible)
    disp, body = _fonts(bible)
    sea_y = int(VH * 0.58)
    floor_y = int(VH * 0.86)
    top_mk = int(VH * 0.16)
    top_ev = sea_y - int((sea_y - top_mk) * (8849 / 10210))

    pts_ev = _ridge(VW * 0.34, sea_y, top_ev, 190, sharp=2.6)
    d.polygon(pts_ev, fill=(110, 127, 145, 235))
    pts_mk = _ridge(VW * 0.62, floor_y, top_mk, 300, sharp=1.25)
    d.polygon([(x, max(y, sea_y)) for x, y in pts_mk], fill=navy + (200,))
    d.line([(x, y) for x, y in pts_mk if y <= sea_y], fill=navy + (255,), width=3)
    below = [(x, y) for x, y in pts_mk if y > sea_y]
    for i in range(len(below) - 1):
        _dashed_line(d, below[i], below[i + 1], navy + (160,), width=3)
    d.line([(70, sea_y), (VW - 70, sea_y)], fill=navy + (255,), width=4)

    # drawn "≠" — Bebas lacks the glyph (tofu); two bars + slash in accent
    ty = int(VH * 0.05)
    f84 = disp(84)
    w_h = d.textlength("HIGHEST", font=f84)
    w_t = d.textlength("TALLEST", font=f84)
    gap, sym_w = 34, 70
    xs = 70 + w_h + gap
    d.text((70, ty), "HIGHEST", font=f84, fill=accent + (255,))
    d.text((xs + sym_w + gap, ty), "TALLEST", font=f84, fill=accent + (255,))
    cy = ty + 46
    for dy in (-16, 16):
        d.line([(xs, cy + dy), (xs + sym_w, cy + dy)], fill=accent + (255,), width=9)
    d.line([(xs + 8, cy + 30), (xs + sym_w - 8, cy - 30)], fill=accent + (255,), width=9)
    d.text((VW * 0.34 - 110, top_ev - 54), "EVEREST 8,849 m", font=body(30), fill=navy + (245,))
    d.text((VW * 0.62 - 120, top_mk - 54), "MAUNA KEA 10,210 m", font=body(30), fill=navy + (245,))
    d.text((70, floor_y + 18), "THE TALLEST MOUNTAIN ON EARTH HIDES 59% OF ITSELF.",
           font=body(28), fill=navy + (230,))
    return img
