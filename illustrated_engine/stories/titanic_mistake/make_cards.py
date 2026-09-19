"""titanic_mistake — deterministic plates + diagram cards + bed/SFX.

Parchment engraving family per the shared visual bible.  V7 chrome policy:
NO baked title bars (episode title is a compose overlay fading by 2.5s);
subtle footer section markers only.  Label/big_number calls use literal
positions so the planner's plate manifest can anchor choreography events.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, BUILD, CREAM, H, INK, MUTED, NAVY, NAVY_D, PARCH,
                         PARCH_L, RUST, W, arrow, bgrid, bebas, big_number, clock_face,
                         finish_plate, footer_band, grain, hatch_polygon, inter, label,
                         parchment, register_diagram, save_plate, synth_bed, synth_sfx,
                         vignette, write_manifest, mottle, vgrad)
from PIL import Image, ImageChops, ImageDraw, ImageFilter

import numpy as np

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)


# ------------------------------------------------------------ helpers ---

def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def sea_band(d, y0, col=NAVY_D, alpha=230):
    d.rectangle((0, y0, W, H), fill=col + (alpha,))
    for u in range(18):
        x = 40 + u * 90
        d.arc((x, y0 + 26 + (u % 3) * 18, x + 120, y0 + 62 + (u % 3) * 18),
              start=200, end=340, fill=CREAM + (60,), width=3)


def ship_silhouette(d, cx, cy, scale=1.0, tilt=0.0, col=NAVY_D):
    """Side-profile hull with four funnels; tilt>0 sinks the bow (right)."""
    s = scale

    def P(x, y):
        a = math.radians(tilt)
        dx, dy = x * s, y * s
        return (cx + dx * math.cos(a) - dy * math.sin(a),
                cy + dx * math.sin(a) + dy * math.cos(a))

    hull = [P(-560, -20), P(-560, -70), P(-500, -78), P(430, -95), P(560, -30),
            P(560, 20), P(-560, 20)]
    d.polygon([P(*_xy) for _xy in hull], fill=col + (255,))
    for fx in (-430, -190, 60, 310):
        top, bottom = P(fx, -78), P(fx + 62 * s, -190)
        d.polygon([top, (top[0] + 54 * s, top[1]), bottom, (bottom[0] + 54 * s, bottom[1])],
                  fill=col + (255,))
    for ux in range(-520, 520, 80):
        a, b2 = P(ux, -40), P(ux + 26, -40)
        d.line((a, b2), fill=CREAM + (90,), width=3)


# ---------------------------------------------------------------- plates ---

def b1_titanic_hero():
    img = parchment(801)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 36))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, W // 2, 980, 580, RUST)
    sea_band(d, 660, col=NAVY, alpha=140)
    # iceberg standing off on the horizon (bigger, warmer)
    berg = [(980, 660), (1060, 380), (1140, 440), (1220, 340), (1330, 450), (1380, 660)]
    d.polygon(berg, fill=PARCH_L + (245,), outline=NAVY + (220,), width=4)
    ship_silhouette(d, W // 2 - 120, 700, 1.0, tilt=4.0, col=NAVY)
    label(d, "RMS TITANIC", (W // 2 - 120, 700), (110, 280))
    label(d, "APRIL 1912", (1200, 700), (1130, 720))
    return finish_plate(img, 802, 0.24)


def b2_timeline_card():
    img = parchment(811)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 30))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 420, 520, 360, RUST)
    glow(d, 1040, 520, 200, RUST)
    clock_face(d, 420, 520, 170, face_col=(195, 150, 90))
    # timeline: sighting -> 37 s -> impact
    y = 520
    d.line(((700, y), (1380, y)), fill=INK + (255,), width=6)
    d.ellipse((700 - 14, y - 14, 700 + 14, y + 14), fill=NAVY + (220,))
    for u in range(1, 8):
        x = 700 + u * 62
        d.line(((x, y - 10), (x, y + 10)), fill=INK + (140,), width=3)
    d.ellipse((1380 - 16, y - 16, 1380 + 16, y + 16), fill=RUST + (240,))
    arrow(d, (700, 620), (1310, 620), col=RUST, w=7, head=22)
    label(d, "SPOTTED 11:40 PM", (420, 520), (240, 280))
    label(d, "IMPACT +37 S", (1380, y), (1080, 620))
    big_number(d, "37 S", (960, 300), 150)
    footer_band(d, "THE TIMELINE")
    return finish_plate(img, 812, 0.18)


def b3_hull_wound():
    img = parchment(821)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 32))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    y = 560
    glow(d, 580, y - 60, 600, RUST)
    d.line(((110, y), (1420, y)), fill=NAVY + (255,), width=8)
    d.polygon([(110, y), (110, y - 120), (1420, y - 150), (1420, y)],
              fill=PARCH_L + (180,), outline=NAVY + (255,))
    for u in range(6):
        x = 180 + u * 150
        d.line(((x, y - 4), (x, y - 116 - (x - 110) * 0.02)), fill=NAVY + (255,), width=5)
    wound = [(150, y - 30), (1020, y - 52)]
    d.line(wound, fill=RUST + (255,), width=9)
    for u in range(9):
        x = 200 + u * 100
        yy = y - 34 - (x - 110) * 0.02
        d.line(((x - 16, yy - 16), (x, yy), (x - 16, yy + 16)), fill=RUST + (255,), width=5)
    hatch_polygon(img, [(150, y - 116), (1020, y - 130), (1020, y - 40), (150, y - 40)],
                  RUST, 46, 14, seed=5)
    label(d, "SIX COMPARTMENTS", (560, y - 80), (180, 320))
    label(d, "BUCKLED PLATES", (700, y - 20), (620, 640))
    footer_band(d, "THE WOUND")
    return finish_plate(img, 822, 0.18)


def b4_overflow_chain():
    img = parchment(831)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 34))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    deck_y = 420
    glow(d, W // 2, deck_y + 160, 580, RUST)
    for u in range(30):
        x = 180 + u * 38
        d.line(((x, deck_y), (min(x + 20, 1340), deck_y)), fill=RUST + (220,), width=4)
    label(d, "D DECK", (1260, deck_y), (1150, 330))
    levels = (0.86, 1.0, 1.0, 0.72)
    for i, lv in enumerate(levels):
        x0, x1 = 200 + i * 290, 440 + i * 290
        by0, by1 = deck_y + 30, deck_y + 330
        d.rectangle((x0, by0, x1, by1), fill=PARCH_L + (150,), outline=INK + (255,), width=5)
        wl = by0 + (by1 - by0) * min(1.0, lv)
        wl2 = min(wl, by1 - 2)
        d.rectangle((x0 + 4, wl2, x1 - 4, by1 - 2), fill=NAVY + (130,))
        if lv >= 1.0 and i < 3:
            arrow(d, (x1 + 4, deck_y + 44), (x1 + 60, deck_y + 44), col=RUST, w=9, head=24)
    label(d, "WATERTIGHT DOOR", (490, deck_y + 300), (180, 800))
    label(d, "SPILL", (790, deck_y + 44), (700, 240))
    footer_band(d, "THE CHAIN")
    return finish_plate(img, 832, 0.18)


def b5_design_cut():
    img = parchment(841)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 32))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 640, 350, 380, RUST)
    base = 760
    # designed: taller bulkheads (dashed extension)
    d.line(((300, base), (300, 330)), fill=NAVY + (255,), width=9)
    for u in range(9):
        y = 200 + u * 15
        d.line(((288, y), (312, y)), fill=NAVY + (150,), width=4)
    # approved: cut height
    d.line(((980, base), (980, 480)), fill=RUST + (255,), width=9)
    d.rectangle((240, base - 8, 360, base + 8), fill=INK + (255,))
    d.rectangle((920, base - 8, 1040, base + 8), fill=INK + (255,))
    d.line(((340, 208), (940, 208)), fill=NAVY + (120,), width=3)
    d.line(((340, 478), (940, 478)), fill=RUST + (150,), width=3)
    arrow(d, (640, 208), (640, 470), col=RUST, w=6, head=20)
    big_number(d, "-10 FT", (640, 330), 110)
    label(d, "DESIGNED", (300, base), (200, 810))
    label(d, "APPROVED", (980, base), (880, 810))
    footer_band(d, "THE DECISION")
    return finish_plate(img, 842, 0.18)


def b6_count_card():
    img = parchment(851)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 34))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 640, 500, 560, RUST)
    base = 820
    # aboard column: dense mark block
    for row in range(22):
        for c in range(6):
            x = 260 + c * 34
            y = base - 40 - row * 30
            d.ellipse((x - 8, y - 8, x + 8, y + 8), fill=NAVY + (180,))
    # survived column: short mark block
    for row in range(7):
        for c in range(6):
            x = 940 + c * 34
            y = base - 40 - row * 30
            d.ellipse((x - 8, y - 8, x + 8, y + 8), fill=RUST + (220,))
    big_number(d, "2,200", (390, 260), 120)
    big_number(d, "705", (1030, 520), 120)
    label(d, "ABOARD", (390, base), (280, 860))
    label(d, "SURVIVED", (1030, base), (900, 860))
    footer_band(d, "THE COUNT")
    return finish_plate(img, 852, 0.18)


def b7_payoff_card():
    img = parchment(861)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 38))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, W // 2, 980, 620, RUST)
    glow(d, W // 2 - 60, 960, 420, RUST)
    sea_band(d, 700, col=NAVY, alpha=120)
    ship_silhouette(d, W // 2, 730, 1.0, tilt=0.0)
    d.line(((W // 2 - 40, 736), (W // 2 + 500, 736)), fill=RUST + (255,), width=10)
    for u in range(7):
        x = W // 2 + u * 70
        d.line(((x, 700), (x, 772)), fill=RUST + (190,), width=4)
    label(d, "THE MARGIN", (W // 2 + 300, 736), (1010, 830))
    footer_band(d, "HER OWN FLAW")
    return finish_plate(img, 862, 0.22)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_titanic_hero": b1_titanic_hero(),
        "B2_timeline_card": b2_timeline_card(),
        "B3_hull_wound": b3_hull_wound(),
        "B4_overflow_chain": b4_overflow_chain(),
        "B5_design_cut": b5_design_cut(),
        "B6_count_card": b6_count_card(),
        "B7_payoff_card": b7_payoff_card(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_timeline_card", "B3_hull_wound", "B4_overflow_chain",
                 "B5_design_cut", "B6_count_card"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_timeline_card", "diagram"),
                    ("B3_hull_wound", "diagram"),
                    ("B4_overflow_chain", "diagram"),
                    ("B5_design_cut", "diagram"),
                    ("B6_count_card", "diagram")])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=87, base_hz=82.0, dur=65.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=97, kind="swell", dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
