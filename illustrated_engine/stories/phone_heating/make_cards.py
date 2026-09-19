"""phone_heating — deterministic plates + diagram cards + bed/SFX.

All art Pillow-drawn (no image-model calls, no network), parchment family
per the shared visual bible.  V7 chrome policy: NO baked title bars — the
episode title is a compose overlay that fades by 2.5s; cards carry only
subtle footer section markers.  Label/big_number calls use literal
positions so the planner's plate manifest can anchor choreography events.
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

def rounded(d, box, r, **kw):
    d.rounded_rectangle(box, radius=r, **kw)


def heat_waves(d, x0, y0, x1, n=3, col=RUST):
    for k in range(n):
        yy = y0 + k * 26
        pts = [(x0 + (x1 - x0) * u / 24.0,
                yy - 10 * math.sin(u / 3.2 + k * 1.4)) for u in range(25)]
        d.line(pts, fill=col + (150 - k * 30,), width=5)


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def phone_body(d, x0, y0, x1, y1, screen=True):
    rounded(d, (x0, y0, x1, y1), 42, fill=NAVY_D + (255,), outline=INK + (255,), width=5)
    if screen:
        rounded(d, (x0 + 18, y0 + 18, x1 - 18, y1 - 18), 30, fill=PARCH + (235,))


# ---------------------------------------------------------------- plates ---

def b1_phone_hero():
    img = parchment(701)
    d = ImageDraw.Draw(img, "RGBA")
    px0, py0, px1, py1 = W // 2 - 165, 190, W // 2 + 165, 860
    phone_body(d, px0, py0, px1, py1)
    # battery block with warm glow inside the phone
    bx0, by0, bx1, by1 = px0 + 60, 470, px1 - 60, 700
    glow(d, (bx0 + bx1) // 2, (by0 + by1) // 2, 240, RUST)
    rounded(d, (bx0, by0, bx1, by1), 18, fill=RUST + (160,), outline=INK + (220,), width=4)
    d.line(((bx0 + 24, (by0 + by1) // 2), (bx1 - 24, (by0 + by1) // 2)),
           fill=CREAM + (200,), width=4)
    # charge cable entering from the left
    d.line(((60, 792), (px0 - 40, 792), (px0 - 40, 830)), fill=NAVY + (255,), width=10)
    d.line(((px0 - 40, 830), (px0 + 60, 860)), fill=NAVY + (255,), width=10)
    d.rectangle((30, 772, 78, 812), fill=NAVY + (255,))
    # dotted charge path into the battery
    for u in range(0, 11):
        x = px0 - 40 + u * 14
        d.ellipse((x - 4, 830 - 4, x + 4, 830 + 4), fill=RUST + (200,))
    # heat shimmer above the phone
    heat_waves(d, px0 + 40, 150, px1 - 40, 2)
    label(d, "CHARGE PATH", (140, 700), (110, 610))
    label(d, "BATTERY", ((bx0 + bx1) // 2, by1 + 6), (px1 - 320, 890))
    return finish_plate(img, 702, 0.22)


def b2_battery_ions():
    img = parchment(711)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    cell = (230, 330, W - 230, 780)
    rounded(d, cell, 26, fill=PARCH_L + (200,), outline=INK + (255,), width=6)
    # electrodes
    rounded(d, (280, 392, 500, 718), 14, fill=NAVY + (210,), outline=INK + (255,), width=4)
    rounded(d, (W - 500, 392, W - 280, 718), 14, fill=RUST + (190,), outline=INK + (255,), width=4)
    # ions crossing right -> left (charging)
    for row in range(3):
        yy = 470 + row * 80
        for u in range(7):
            x = W // 2 - 180 + u * 52
            d.ellipse((x - 13, yy - 13, x + 13, yy + 13), fill=CREAM + (235,),
                      outline=NAVY + (255,), width=3)
            d.text((x - 7, yy - 12), "+", font=inter(20), fill=NAVY + (255,))
        arrow(d, (W // 2 + 120, yy), (W // 2 - 120, yy), col=RUST, w=6, head=20)
    label(d, "ANODE", (390, 392), (250, 262))
    label(d, "CATHODE", (W - 390, 392), (W - 520, 262))
    label(d, "Li+ IONS", (W // 2, 545), (W // 2 + 180, 545))
    footer_band(d, "INSIDE THE CELL")
    return finish_plate(img, 712, 0.18)


def b3_resistance_path():
    img = parchment(721)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    y = 520
    # main path with three resistor zigzags
    segs = [(200, 560), (760, 1000), (1180, 1330)]

    def zigzag(x0, x1, yy):
        pts = [(x0, yy)]
        n = 8
        for u in range(1, n + 1):
            xx = x0 + (x1 - x0) * u / n
            pts.append((xx, yy + (26 if u % 2 else -26)))
        pts.append((x1, yy))
        d.line(pts, fill=RUST + (235,), width=6)
        heat_waves(d, x0 + 20, yy - 165, x1 - 20, 3)

    d.line(((110, y), (segs[0][0], y)), fill=NAVY + (255,), width=8)
    zigzag(*segs[0], y)
    d.line(((segs[0][1], y), (segs[1][0], y)), fill=NAVY + (255,), width=8)
    zigzag(*segs[1], y)
    d.line(((segs[1][1], y), (segs[2][0], y)), fill=NAVY + (255,), width=8)
    zigzag(*segs[2], y)
    d.line(((segs[2][1], y), (1420, y)), fill=NAVY + (255,), width=8)
    # nodes: plug, chip, cell
    d.rectangle((80, y - 40, 140, y + 40), fill=NAVY + (210,))
    rounded(d, (880, y - 55, 1000, y + 55), 12, fill=NAVY + (200,),
            outline=INK + (255,), width=4)
    rounded(d, (1270, y - 60, 1440, y + 60), 14, fill=RUST + (150,),
            outline=INK + (255,), width=5)
    label(d, "PLUG", (110, y - 40), (70, 380))
    label(d, "CABLE", (480, y), (420, 620))
    label(d, "CHARGE CHIP", (940, y - 55), (830, 380))
    label(d, "CELL", (1355, y - 60), (1230, 380))
    footer_band(d, "EVERYTHING RESISTS")
    return finish_plate(img, 722, 0.18)


def b4_power_split():
    img = parchment(731)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    jx, jy = 470, 520
    # incoming power
    arrow(d, (120, jy), (jx - 14, jy), col=NAVY, w=12, head=28)
    label(d, "POWER IN", (280, jy), (120, 410))
    # stored branch (thicker, upward)
    arrow(d, (jx, jy - 10), (900, 380), col=NAVY, w=11, head=26)
    rounded(d, (920, 320, 1150, 440), 14, fill=NAVY + (150,), outline=INK + (255,), width=5)
    d.line(((950, 380), (1120, 380)), fill=CREAM + (220,), width=5)
    label(d, "STORED", (1035, 380), (930, 250))
    # heat branch (smaller, downward)
    arrow(d, (jx, jy + 10), (860, 690), col=RUST, w=11, head=24)
    glow(d, 1070, 690, 220, RUST)
    heat_waves(d, 890, 650, 1250, 4)
    label(d, "WASTE HEAT", (1070, 690), (900, 760))
    hatch_polygon(img, [(jx - 10, jy - 40), (jx + 60, jy - 40), (jx + 60, jy + 40),
                        (jx - 10, jy + 40)], RUST, 40, 12, seed=9)
    footer_band(d, "THE LEAK")
    return finish_plate(img, 732, 0.18)


def b5_throttle_curve():
    img = parchment(741)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    ax0, ay0, ax1, ay1 = 230, 300, 1360, 800
    d.line(((ax0, ay0), (ax0, ay1)), fill=INK + (255,), width=6)
    d.line(((ax0, ay1), (ax1, ay1)), fill=INK + (255,), width=6)
    # tapering current curve (two steps down)
    curve = [(ax0 + 30, 380), (600, 380), (600, 500), (950, 500), (950, 620),
             (ax1 - 30, 620)]
    d.line(curve, fill=NAVY + (255,), width=9, joint="curve")
    # thermal limit (dashed) + warm wash over the over-limit zone
    d.rectangle((ax0 + 2, ay0, ax1 - 2, 440), fill=RUST + (36,))
    for u in range(30):
        x = ax0 + 20 + u * 38
        d.line(((x, 440), (min(x + 20, ax1), 440)), fill=RUST + (230,), width=5)
    # temperature strip: parchment band with rust tick marks (warm end ticks denser)
    d.rectangle((ax0, 820, ax1, 848), fill=PARCH_L + (220,), outline=INK + (160,), width=2)
    for u in range(0, 60, 2):
        x = ax0 + u * 19
        a = 120 + int(110 * (u / 59.0))
        d.line(((x, 824), (x, 844)), fill=RUST + (a,), width=3)
    label(d, "CURRENT", (ax0, 340), (60, 250))
    label(d, "THERMAL LIMIT", (1050, 440), (980, 470))
    label(d, "TIME", (1300, 800), (1240, 860))
    footer_band(d, "SELF-DEFENSE")
    return finish_plate(img, 742, 0.18)


def b6_phone_payoff():
    img = parchment(751)
    tint = Image.new("RGBA", (W, H), (212, 148, 84, 34))  # dusk warmth
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    px0, py0, px1, py1 = W // 2 - 165, 190, W // 2 + 165, 860
    # warm dusk horizon behind the phone
    glow(d, W // 2, 980, 620, RUST)
    glow(d, W // 2 - 60, 960, 420, RUST)
    phone_body(d, px0, py0, px1, py1)
    glow(d, (px0 + px1) // 2, 540, 250, RUST)
    # calm battery icon with a check
    rounded(d, (px0 + 70, 430, px1 - 70, 640), 20, fill=RUST + (110,),
            outline=INK + (200,), width=4)
    d.line(((px0 + 130, 540), (px0 + 180, 590), (px0 + 280, 470)),
           fill=CREAM + (255,), width=12, joint="curve")
    # coiled cable aside
    for k, r in enumerate((30, 58, 86)):
        d.arc((250 - r, 700 - r, 250 + r, 700 + r), start=0, end=360,
              fill=NAVY + (255 - k * 30,), width=8)
    # one small heat wisp
    heat_waves(d, px0 + 60, 150, px0 + 240, 2)
    label(d, "THE TOLL", (W // 2, 880), (W // 2 - 300, 880))
    footer_band(d, "PAYING THE TOLL")
    return finish_plate(img, 752, 0.24)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_phone_hero": b1_phone_hero(),
        "B2_battery_ions": b2_battery_ions(),
        "B3_resistance_path": b3_resistance_path(),
        "B4_power_split": b4_power_split(),
        "B5_throttle_curve": b5_throttle_curve(),
        "B6_phone_payoff": b6_phone_payoff(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_battery_ions", "B3_resistance_path", "B4_power_split",
                 "B5_throttle_curve"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_battery_ions", "diagram"),
                    ("B3_resistance_path", "diagram"),
                    ("B4_power_split", "diagram"),
                    ("B5_throttle_curve", "diagram")])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=73, base_hz=98.0, dur=60.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=83, kind="swell", dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
