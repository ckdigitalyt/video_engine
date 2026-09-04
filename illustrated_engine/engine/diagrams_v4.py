"""V4 staged diagrams — progressive argument, not empty-then-tiny (§5).

D1_collapse: baseline (giant star) -> collapse (cores shrink) -> scale
(20 km vs city) -> annotation (1.4 Suns -> 20 km).
D2_pyramid: baseline (the cube) -> comparison (pyramid stack x170) ->
conclusion (fingertip scale note).

Same 1080x1744 card system as diagrams_v3.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from engine.diagrams_v3 import _card3
from engine.diagrams import _fonts, _ridge
from engine.layout import CANVAS_W, CANVAS_H, VISUAL_RECT

VW3, VH3 = 1080, 1744
OFF_Y = VISUAL_RECT[1]


def _copy(img):
    return img.copy()


# ------------------------------------------------------------- collapse ----

def collapse_stages(bible) -> list:
    out = []
    img, d, ink, navy, accent = _card3(bible)
    disp, body = _fonts(bible)
    d.text((80, 96), "GRAVITY WINS", font=disp(58), fill=navy + (255,))
    d.text((80, 168), "THE DEATH OF A GIANT STAR", font=body(24), fill=navy + (210,))
    cy = int(VH3 * 0.50)
    pts = _ridge(int(VW3 * 0.5), cy, int(VH3 * 0.20), 430, sharp=1.8)
    d.polygon([(x, min(y, cy)) for x, y in pts], fill=navy + (190,))
    d.text((80, cy + 150), "A GIANT STAR — 1,000,000 KM ACROSS", font=body(26),
           fill=navy + (230,))
    out.append(_copy(img))                                     # s0 baseline
    # s1: collapse — shrinking cores with arrows
    d.line([(410, cy - 250), (410, cy - 150)], fill=accent + (240,), width=6)
    d.polygon([(398, cy - 158), (422, cy - 158), (410, cy - 138)], fill=accent + (255,))
    d.ellipse([VW3 * 0.38 - 60, cy - 60, VW3 * 0.38 + 60, cy + 60], fill=navy + (210,))
    d.line([(540, cy - 250), (540, cy - 190)], fill=accent + (240,), width=5)
    d.polygon([(530, cy - 198), (550, cy - 198), (540, cy - 182)], fill=accent + (255,))
    d.ellipse([VW3 * 0.5 - 34, cy - 34, VW3 * 0.5 + 34, cy + 34], fill=navy + (230,))
    d.text((80, cy + 210), "THE CORE COLLAPSES IN SECONDS", font=body(26),
           fill=accent + (255,))
    out.append(_copy(img))                                     # s1 subject
    # s2: scale — 20 km vs city silhouette
    d.ellipse([VW3 * 0.62 - 46, cy - 46, VW3 * 0.62 + 46, cy + 46], fill=navy + (255,))
    d.line([(VW3 * 0.62 - 46, cy + 70), (VW3 * 0.62 + 46, cy + 70)],
           fill=accent + (255,), width=5)
    d.text((VW3 * 0.62 - 90, cy + 84), "20 KM — ONE CITY", font=body(26),
           fill=navy + (240,))
    out.append(_copy(img))                                     # s2 scale
    # s3: key annotation
    d.text((80, int(VH3 * 0.70)), "MORE MASS THAN THE SUN", font=disp(48),
           fill=accent + (255,))
    d.text((80, int(VH3 * 0.70) + 76), "PRESSED INTO A 20 KM SPHERE",
           font=body(30), fill=navy + (240,))
    out.append(_copy(img))                                     # s3 annotation
    return out


# ------------------------------------------------------------- pyramids ----

def pyramid_stages(bible) -> list:
    out = []
    img, d, ink, navy, accent = _card3(bible)
    disp, body = _fonts(bible)
    d.text((80, 96), "ONE SUGAR CUBE", font=disp(58), fill=navy + (255,))
    cy = int(VH3 * 0.52)
    # the cube
    s = 120
    d.rounded_rectangle([VW3 * 0.5 - s, cy - s, VW3 * 0.5 + s, cy + s],
                        radius=14, fill=(250, 246, 236, 255),
                        outline=navy + (255,), width=6)
    d.text((VW3 * 0.5 - 118, cy + s + 24), "NEUTRON-STAR MATTER", font=body(25),
           fill=navy + (235,))
    out.append(_copy(img))                                     # s0 baseline
    # s1: comparison — pyramid stack
    def pyr(cx, base, w=110, h=88, fill=None):
        d.polygon([(cx - w, base), (cx + w, base), (cx, base - h)],
                  fill=fill or (122, 106, 82, 230))
    base_y = cy + s + 130
    for cx in range(int(VW3 * 0.14), int(VW3 * 0.66), 165):
        pyr(cx, base_y, w=90, h=76)
    d.text((int(VW3 * 0.68), base_y - 160), "x 170", font=disp(52), fill=accent + (255,))
    d.text((80, base_y + 20), "GREAT PYRAMIDS: 5.9 MILLION TONNES EACH",
           font=body(24), fill=navy + (225,))
    out.append(_copy(img))                                     # s1 comparison
    # s2: key number
    d.text((80, int(VH3 * 0.72)), "1,000,000,000 TONS", font=disp(72),
           fill=accent + (255,))
    d.line([(80, int(VH3 * 0.72) + 92), (80 + 620, int(VH3 * 0.72) + 92)],
           fill=accent + (220,), width=5)
    out.append(_copy(img))                                     # s2 conclusion
    return out



# ------------------------------------------------------------ distance ----

def _hexrgb(h: str, a: int = 255) -> tuple:
    h = h.lstrip("#")
    return (*[int(h[i:i + 2], 16) for i in (0, 2, 4)], a)


def distance_stages(bible) -> list:
    """V4 §6 annotation/evidence overlays for the payoff shot.

    Transparent PNGs so the night-sky plate stays visible underneath:
    s0 marks the star, s1 adds the key number (400 light-years)."""
    disp, body = _fonts(bible)
    pal = bible.get("palette", {}) if isinstance(bible, dict) else {}
    txt = _hexrgb(pal.get("text", "#EFE6D4"))
    accent = _hexrgb(pal.get("accent", "#C25B33"))
    shadow = (0, 0, 0, 200)
    out = []
    # s0 - mark the star
    img = Image.new("RGBA", (VW3, VH3), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sx, sy = int(VW3 * 0.50), int(VH3 * 0.34)
    d.ellipse([sx - 9, sy - 9, sx + 9, sy + 9], fill=accent)
    d.ellipse([sx - 20, sy - 20, sx + 20, sy + 20],
              outline=(*accent[:3], 170), width=4)
    d.line([(sx - 14, sy - 10), (sx - 60, sy - 88)],
           fill=(*accent[:3], 220), width=4)

    def shadow_text(xy, s2, font, fill):
        d.text((xy[0] + 3, xy[1] + 3), s2, font=font, fill=shadow)
        d.text(xy, s2, font=font, fill=fill)

    shadow_text((80, sy - 128), "THE NEAREST KNOWN NEUTRON STAR",
                body(26), txt)
    out.append(_copy(img))                                     # s0 marker
    # s1 - key number
    y = int(VH3 * 0.60)
    shadow_text((80, y), "400 LIGHT-YEARS", disp(64), accent)
    d.line([(80, y + 88), (80 + 640, y + 88)],
           fill=(*accent[:3], 210), width=5)
    shadow_text((80, y + 112), "7 MILLION YEARS AT VOYAGER 1 SPEED",
                body(28), txt)
    out.append(_copy(img))                                     # s1 key number
    return out


DIAGRAMS_V4 = {
    "D1_collapse": collapse_stages,
    "D2_pyramid": pyramid_stages,
}

DIAGRAMS_V4_KINDS = {
    "D1_collapse": (collapse_stages, "diagram"),
    "D2_pyramid": (pyramid_stages, "diagram"),
    "D3_distance": (distance_stages, "annotation"),
}


def write_stages(paths, bible, story_id: str = None) -> dict:
    assets = Path(paths.assets)
    build = Path(paths.build)
    out_dir = build / "diag_stages"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (fn, kind) in DIAGRAMS_V4_KINDS.items():
        stages = fn(bible)
        manifest[name] = []
        for i, card in enumerate(stages):
            apath = assets / f"{name}_s{i}.png"
            card.save(apath, "PNG")
            frame = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
            frame.paste(card.convert("RGBA"), (0, OFF_Y))
            frame.save(out_dir / f"{name}_s{i}_full.png", "PNG")
            manifest[name].append({"stage": i, "asset": f"{name}_s{i}",
                                   "kind": kind})
    (build / "diag_stages" / "manifest_v4.json").write_text(json.dumps(manifest, indent=2))
    return manifest


# --------------------------------------------------------------- venus ----

def race_stages(bible) -> list:
    """V4 D1_race — lap vs turn: s0 baseline orbit, s1 lap done + spin
    dial 27 deg short, s2 verdict."""
    out = []
    img, d, ink, navy, accent = _card3(bible)
    disp, body = _fonts(bible)
    d.text((80, 96), "THE RACE", font=disp(58), fill=navy + (255,))
    d.text((80, 168), "ONE LAP OF THE SUN VS ONE SPIN", font=body(24),
           fill=navy + (210,))
    cx = VW3 // 2
    cy = int(VH3 * 0.38)
    R = 300
    box = [cx - R, cy - R, cx + R, cy + R]
    # s0 baseline: sun + dashed orbit + Venus dot on the start line
    d.ellipse([cx - 50, cy - 50, cx + 50, cy + 50], fill=accent + (255,))
    for deg in range(0, 360, 18):
        d.arc(box, deg, deg + 11, fill=navy + (200,), width=5)
    d.ellipse([cx - 16, cy - R - 16, cx + 16, cy - R + 16], fill=navy + (255,))
    d.text((cx + 44, cy - R - 12), "START", font=body(22), fill=navy + (200,))
    d.text((80, cy + R + 54), "ONE LAP = 225 EARTH DAYS", font=body(26),
           fill=navy + (235,))
    out.append(_copy(img))                                     # s0 baseline
    # s1: lap complete (accent ring + flag), spin dial 27 deg short
    d.arc(box, 0, 360, fill=accent + (255,), width=9)
    d.line([(cx, cy - R - 34), (cx, cy - R - 86)], fill=accent + (255,), width=7)
    d.polygon([(cx - 60, cy - R - 86), (cx + 4, cy - R - 86), (cx - 28, cy - R - 60)],
              fill=accent + (255,))
    dy = cy + R + 130
    for dcx, frac, col, lab in ((VW3 * 0.32, 1.0, accent, "LAP — DONE"),
                                (VW3 * 0.68, 0.925, navy, "TURN — 27 DEG SHORT")):
        dr = 74
        d.ellipse([dcx - dr, dy - dr, dcx + dr, dy + dr], outline=navy + (120,), width=4)
        d.arc([dcx - dr, dy - dr, dcx + dr, dy + dr], -90, -90 + int(360 * frac),
              fill=col + (255,), width=10)
        d.text((dcx - 110, dy + dr + 18), lab, font=body(24), fill=navy + (235,))
    out.append(_copy(img))                                     # s1 race state
    # s2: verdict
    d.text((80, int(VH3 * 0.78)), "THE YEAR WINS", font=disp(60),
           fill=accent + (255,))
    d.line([(80, int(VH3 * 0.78) + 90), (80 + 560, int(VH3 * 0.78) + 90)],
           fill=accent + (220,), width=5)
    d.text((80, int(VH3 * 0.78) + 116), "1.08 LAPS EVERY SINGLE TURN",
           font=body(30), fill=navy + (240,))
    out.append(_copy(img))                                     # s2 verdict
    return out


def compare_stages(bible) -> list:
    """V4 D2_compare — Earth baseline bars vs Venus bars, one scale."""
    out = []
    img, d, ink, navy, accent = _card3(bible)
    disp, body = _fonts(bible)
    d.text((80, 96), "TWO CLOCKS", font=disp(58), fill=navy + (255,))
    d.text((80, 168), "EARTH VS VENUS — ONE HONEST SCALE", font=body(24),
           fill=navy + (210,))
    x0, W = 80, 900
    k = W / 365.0
    y = int(VH3 * 0.32)
    # s0 Earth baseline
    d.text((80, y - 46), "EARTH", font=body(30), fill=navy + (255,))
    d.rectangle([x0, y, x0 + 12, y + 46], fill=accent + (255,))
    d.text((x0 + 28, y + 6), "DAY = 24 HOURS", font=body(26), fill=navy + (235,))
    y2 = y + 100
    d.rectangle([x0, y2, x0 + W, y2 + 46], fill=navy + (190,))
    d.text((x0 + 28, y2 + 6), "YEAR = 365 DAYS", font=body(26),
           fill=(233, 223, 200, 255))
    out.append(_copy(img))                                     # s0 Earth
    # s1 Venus bars — the day bar overtakes the year bar
    y3 = y2 + 150
    d.text((80, y3 - 46), "VENUS", font=body(30), fill=accent + (255,))
    d.rectangle([x0, y3, x0 + int(243 * k), y3 + 46], fill=accent + (255,))
    d.text((x0 + 28, y3 + 6), "DAY = 243 EARTH DAYS", font=body(26),
           fill=(233, 223, 200, 255))
    y4 = y3 + 100
    d.rectangle([x0, y4, x0 + int(225 * k), y4 + 46], fill=navy + (230,))
    d.text((x0 + 28, y4 + 6), "YEAR = 225 EARTH DAYS", font=body(26),
           fill=(233, 223, 200, 255))
    d.text((80, int(VH3 * 0.74)), "A DAY LONGER THAN ITS YEAR",
           font=disp(46), fill=accent + (255,))
    d.line([(80, int(VH3 * 0.74) + 76), (80 + 700, int(VH3 * 0.74) + 76)],
           fill=accent + (210,), width=5)
    out.append(_copy(img))                                     # s1 Venus
    return out


def dawncount_stages(bible) -> list:
    """V4 D3_dawncount — sunrise-to-sunrise timeline + dawns-per-year
    conclusion. Transparent annotation over the dawn plate."""
    disp, body = _fonts(bible)
    pal = bible.get("palette", {}) if isinstance(bible, dict) else {}
    txt = _hexrgb(pal.get("text", "#EFE6D4"))
    accent = _hexrgb(pal.get("accent", "#C25B33"))
    shadow = (0, 0, 0, 200)

    def shadow_text(xy, s2, font, fill):
        d.text((xy[0] + 3, xy[1] + 3), s2, font=font, fill=shadow)
        d.text(xy, s2, font=font, fill=fill)

    out = []
    img = Image.new("RGBA", (VW3, VH3), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = int(VH3 * 0.60)
    # s0 - sunrise-to-sunrise dashed timeline
    shadow_text((120, y - 116), "SUNRISE TO SUNRISE", body(30), txt)
    d.ellipse([120, y - 34, 188, y + 34], outline=accent, width=6)
    d.ellipse([892, y - 34, 960, y + 34], outline=accent, width=6)
    for xseg in range(214, 880, 40):
        d.line([(xseg, y), (xseg + 22, y)], fill=(*txt[:3], 235), width=5)
    shadow_text((120, y + 58), "117 EARTH DAYS", disp(56), accent)
    out.append(_copy(img))                                     # s0 timeline
    # s1 - the year conclusion
    y2 = int(VH3 * 0.76)
    shadow_text((120, y2), "BARELY TWO SUNRISES PER YEAR", disp(46), accent)
    shadow_text((120, y2 + 82), "1.92 DAWNS EVERY VENUS YEAR", body(28), txt)
    out.append(_copy(img))                                     # s1 conclusion
    return out


DIAGRAMS_V4_KINDS.update({
    "D1_race": (race_stages, "diagram"),
    "D2_compare": (compare_stages, "diagram"),
    "D3_dawncount": (dawncount_stages, "annotation"),
})
