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
