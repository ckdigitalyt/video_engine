"""sahara_greening — deterministic plates + diagram cards + bed/SFX.

Parchment-map family per the shared visual bible.  V7 chrome policy: NO baked
title bars (episode title is a compose overlay fading by 2.5s); subtle
footer section markers only.  Label/big_number calls use literal positions
so the planner's plate manifest can anchor choreography events.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, BUILD, CREAM, H, INK, MUTED, NAVY, NAVY_D, PARCH,
                         PARCH_L, RUST, W, arrow, bgrid, bebas, big_number,
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

# Africa outline (very simplified, hand-authored polygon points)
AFRICA = [
    (520, 120), (640, 140), (720, 220), (760, 300), (720, 380),
    (740, 460), (720, 560), (700, 660), (640, 760), (560, 800),
    (480, 760), (420, 700), (400, 620), (380, 540), (400, 460),
    (420, 380), (380, 320), (360, 240), (400, 180), (460, 140),
]


def sahara_mask(d, fill_color, fill_alpha, x0=380, x1=780, y0=280, y1=540):
    """Approximate Sahara box (northern African bulk) over the continent."""
    d.rectangle((x0, y0, x1, y1), fill=fill_color + (fill_alpha,))


def sahel_strip(d, color=RUST, alpha=160, x0=380, x1=780, y0=540, y1=600):
    d.rectangle((x0, y0, x1, y1), fill=color + (alpha,))


# ---------------------------------------------------------------- plates ---

def b1_sahara_hero():
    img = parchment(901)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 30))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, W // 2, 980, 620, RUST)
    d.polygon(AFRICA, fill=PARCH_L + (200,), outline=NAVY + (255,), width=5)
    sahara_mask(d, RUST, 70)
    sahel_strip(d, RUST, 200)
    label(d, "SAHARA", (580, 360), (200, 300))
    label(d, "THE GREENING", (W // 2, 600), (W // 2 - 200, 640))
    return finish_plate(img, 902, 0.22)


def b2_sahara_map():
    img = parchment(911)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 28))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 580, 460, 460, RUST)
    d.polygon(AFRICA, fill=PARCH_L + (200,), outline=NAVY + (255,), width=5)
    sahara_mask(d, RUST, 60)
    sahel_strip(d, RUST, 200)
    # scale bar
    d.rectangle((1080, 820, 1340, 832), fill=INK + (255,))
    for u in range(5):
        x = 1080 + u * 52
        d.line(((x, 812), (x, 820)), fill=INK + (255,), width=3)
    big_number(d, "9.2 MILLION KM²", (250, 220), 80)
    label(d, "SAHEL RIM", (W // 2, 600), (W // 2 - 160, 640))
    footer_band(d, "THE SCALE")
    return finish_plate(img, 912, 0.18)


def b3_time_series():
    img = parchment(921)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 30))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, W // 2, 460, 500, RUST)
    labels = ("1980s", "2000s", "2010s", "NOW")
    greens = (60, 110, 160, 200)
    for i, (lab, gr) in enumerate(zip(labels, greens)):
        x0 = 160 + i * 320
        d.rectangle((x0, 200, x0 + 280, 620), fill=PARCH_L + (200,),
                    outline=NAVY + (255,), width=4)
        d.polygon([(x0 + 20, 580), (x0 + 260, 580), (x0 + 260, 580 - gr),
                   (x0 + 20, 580 - gr // 2)], fill=RUST + (gr,),
                  outline=NAVY + (255,), width=3)
        hatch_polygon(img, [(x0 + 20, 580), (x0 + 260, 580),
                            (x0 + 260, 580 - gr), (x0 + 20, 580 - gr // 2)],
                      RUST, 50, 14, seed=3 + i)
        label(d, lab, (x0 + 140, 660), (x0 + 40, 690))
    # timeline ruler
    d.line(((140, 760), (1420, 760)), fill=INK + (255,), width=5)
    for u in range(5):
        x = 140 + u * 320
        d.line(((x, 752), (x, 768)), fill=INK + (255,), width=3)
    label(d, "SATELLITE RECORD", (W // 2, 760), (W // 2 - 380, 790))
    footer_band(d, "THE TIMELINE")
    return finish_plate(img, 922, 0.18)


def b4_drivers():
    img = parchment(931)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 32))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, W // 2, 540, 520, RUST)
    # central green Sahel block
    d.rectangle((520, 440, 1080, 660), fill=RUST + (180,),
                outline=NAVY + (255,), width=5)
    hatch_polygon(img, [(520, 440), (1080, 440), (1080, 660), (520, 660)],
                  RUST, 50, 14, seed=4)
    label(d, "SAHEL", (800, 550), (740, 510))
    # driver arrows into the block
    arrow(d, (240, 360), (560, 460), col=NAVY, w=11, head=26)
    arrow(d, (240, 740), (560, 640), col=NAVY, w=11, head=26)
    label(d, "RAINFALL", (360, 340), (220, 280))
    label(d, "CO2", (360, 760), (300, 780))
    # rain-glyph (cloud + drops) above rainfall label
    for k in range(3):
        d.ellipse((120 + k * 50, 240, 180 + k * 50, 300), fill=PARCH_L + (230,),
                  outline=NAVY + (200,), width=2)
        d.line(((150 + k * 50, 310), (140 + k * 50, 340)), fill=NAVY + (220,), width=3)
    # CO2 label glyph
    d.ellipse((110, 660, 190, 740), fill=PARCH_L + (230,),
              outline=NAVY + (220,), width=2)
    label(d, "CO2", (150, 700), (90, 750))
    footer_band(d, "THE DRIVERS")
    return finish_plate(img, 932, 0.18)


def b5_rim_vs_core():
    img = parchment(941)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 30))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, W // 2, 520, 520, RUST)
    # left panel: green rim
    d.rectangle((140, 200, 760, 720), fill=PARCH_L + (200,),
                outline=NAVY + (255,), width=5)
    africa_shifted = [(x - 220, y) for x, y in AFRICA]
    d.polygon(africa_shifted, fill=PARCH_L + (150,),
              outline=NAVY + (200,), width=3)
    d.rectangle((220, 460, 660, 540), fill=RUST + (200,))  # green rim
    label(d, "GREENING RIM", (450, 200), (180, 130))
    # divider
    d.line(((780, 200), (780, 740)), fill=INK + (255,), width=5)
    # right panel: unchanged core
    d.rectangle((800, 200, 1420, 720), fill=PARCH_L + (200,),
                outline=NAVY + (255,), width=5)
    d.polygon([(x + 240, y) for x, y in AFRICA], fill=PARCH_L + (150,),
              outline=NAVY + (200,), width=3)
    d.rectangle((880, 380, 1320, 460), fill=RUST + (60,))  # unchanged
    label(d, "UNCHANGED CORE", (1110, 200), (840, 130))
    footer_band(d, "RIM VS CORE")
    return finish_plate(img, 942, 0.18)


def b6_sahara_payoff():
    img = parchment(951)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 40))
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, W // 2, 980, 620, RUST)
    glow(d, W // 2 - 60, 960, 420, RUST)
    d.polygon(AFRICA, fill=PARCH_L + (200,), outline=NAVY + (255,), width=5)
    sahara_mask(d, RUST, 80)
    sahel_strip(d, RUST, 220)
    label(d, "THE BRIGHTER FRINGE", (W // 2, 600), (W // 2 - 200, 640))
    footer_band(d, "THE PAYOFF")
    return finish_plate(img, 952, 0.24)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_sahara_africa_map_hero": b1_sahara_hero(),
        "B2_sahara_map": b2_sahara_map(),
        "B3_time_series": b3_time_series(),
        "B4_drivers": b4_drivers(),
        "B5_rim_vs_core": b5_rim_vs_core(),
        "B6_sahara_payoff": b6_sahara_payoff(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_sahara_map", "B3_time_series", "B4_drivers", "B5_rim_vs_core"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_sahara_map", "diagram"),
                    ("B3_time_series", "diagram"),
                    ("B4_drivers", "diagram"),
                    ("B5_rim_vs_core", "diagram")])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=103, base_hz=72.0, dur=60.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=113, kind="swell", dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
