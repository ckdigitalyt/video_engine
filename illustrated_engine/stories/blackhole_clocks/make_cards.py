"""blackhole_clocks — deterministic plates + diagram cards + bed/SFX.

All art Pillow-drawn (no image-model calls, no network), dark-ground physics
family with parchment graph cards per the story's visual bible.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, BANDC, CREAM, H, INK, MUTED, NAVY, NAVY_D,
                         PARCH, PARCH_L, RUST, W, arrow, bgrid, bebas,
                         big_number, clock_face, finish_plate, footer_band,
                         grain, hatch_polygon, inter, label, mottle,
                         parchment, register_diagram, save_plate, synth_bed,
                         synth_sfx, title_bar, vignette, vgrad, write_manifest)
from PIL import Image, ImageDraw, ImageFilter

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

DARK_WARM = (52, 40, 33)


def starfield(d, seed, n=80, ymax=None):
    import random
    rnd = random.Random(seed)
    for _ in range(n):
        x = rnd.randint(20, W - 20)
        y = rnd.randint(20, ymax or H - 20)
        v = rnd.randint(110, 210)
        d.ellipse((x, y, x + rnd.choice((2, 2, 3)), y + rnd.choice((2, 2, 3))),
                  fill=(239, 230, 212, v))


def b1_bh_hero():
    img = vgrad(W, H, (18, 22, 38), (52, 40, 33)).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    starfield(d, 401, 90, 700)
    cx, cy = W // 2, 470
    # accretion ring
    for r, w, a in ((330, 46, 235), (282, 26, 200), (372, 18, 170)):
        d.arc((cx - r, cy - r * 0.36, cx + r, cy + r * 0.36), 0, 360,
              fill=(205, 130, 70, a), width=w)
    d.arc((cx - 356, cy - 130, cx + 356, cy + 130), 200, 340, fill=RUST + (230,), width=12)
    # hole
    d.ellipse((cx - 240, cy - 240, cx + 240, cy + 240), fill=(8, 8, 10, 255),
              outline=(239, 230, 212, 60), width=3)
    # parked clock silhouette
    clock_face(d, cx + 470, cy + 120, 84, hour_angle=210, minute_angle=95)
    img = finish_plate(img, 402, 0.32)
    return img


def b2_two_clocks():
    img = parchment(411)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "TWO CLOCKS", sub="SAME GEARS - DIFFERENT DEPTH")
    d.rectangle((110, 820, W - 110, 980), fill=BANDC + (255,))
    d.rectangle((110, 260, W - 110, 420), fill=RUST + (26,))
    # dark mass edge lower-right
    d.ellipse((W - 640, 560, W + 420, 1500), fill=BANDC + (255,))
    d.arc((W - 640, 560, W + 420, 1500), 170, 250, fill=(205, 130, 70, 220), width=10)
    # far clock (upper-left, on parchment sky)
    clock_face(d, 380, 560, 130, tick_col=NAVY, face_col=PARCH_L, hand_col=NAVY)
    d.arc((250, 430, 510, 690), 140, 400, fill=RUST + (255,), width=9)
    # near clock (lower-right, on the dark mass)
    clock_face(d, W - 340, 830, 130, hour_angle=220, minute_angle=110)
    d.arc((W - 470, 700, W - 210, 960), 160, 220, fill=RUST + (255,), width=9)
    label(d, "FAR", (380, 430), (140, 300))
    label(d, "NEAR", (W - 340, 700), (W - 560, 620))
    big_number(d, "SAME CLOCKS", (W // 2, 170), 100)
    return finish_plate(img, 412, 0.18)


def d1_spacetime_funnel():
    img = parchment(421)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "THE WELL", sub="CURVED TIME - DRAWN AS DEPTH")
    d.rectangle((110, 350, W - 110, 470), fill=RUST + (26,))
    # funnel grid: horizontal lines sagging toward the center bottom
    cx = W // 2
    for k in range(9):
        y0 = 260 + k * 62
        pts = []
        for x in range(90, W - 80, 24):
            depth = 190 * math.exp(-((x - cx) ** 2) / (2 * (240 + 90 * (y0 - 260) / 62) ** 2))
            pts.append((x, y0 + depth))
        d.line(pts, fill=NAVY + (200 - k * 12,), width=4)
    # vertical grid guides
    for gx in (cx - 380, cx - 190, cx, cx + 190, cx + 380):
        pts = []
        for k in range(9):
            y0 = 260 + k * 62
            depth = 190 * math.exp(-((gx - cx) ** 2) / (2 * (240 + 90 * (y0 - 260) / 62) ** 2))
            pts.append((gx, y0 + depth))
        d.line(pts, fill=NAVY + (120,), width=3)
    # hole at the bottom
    d.ellipse((cx - 150, 830, cx + 150, 1000), fill=BANDC + (255,))
    d.arc((cx - 150, 830, cx + 150, 1000), 200, 340, fill=RUST + (240,), width=8)
    # clocks at depths
    clock_face(d, cx - 430, 420, 64, tick_col=NAVY, face_col=PARCH_L, hand_col=NAVY)
    clock_face(d, cx + 430, 540, 64, tick_col=NAVY, face_col=PARCH_L, hand_col=NAVY)
    clock_face(d, cx, 760, 64, hour_angle=230)
    big_number(d, "DEEPER = SLOWER", (W // 2, 180), 92)
    return finish_plate(img, 422, 0.18)


def b3_horizon_detail():
    img = Image.new("RGB", (W, H), DARK_WARM)
    d = ImageDraw.Draw(img, "RGBA")
    starfield(d, 431, 60)
    cx, cy = W // 2, H // 2
    d.ellipse((cx - 300, cy - 300, cx + 300, cy + 300), fill=(8, 8, 10, 255))
    for k in range(7):
        r = 330 + k * 34
        d.arc((cx - r, cy - r, cx + r, cy + r), 110, 250,
              fill=(239, 230, 212, 220 - k * 22), width=6 if k < 3 else 3)
    d.arc((cx - 318, cy - 318, cx + 318, cy + 318), 160, 200, fill=RUST + (240,), width=10)
    img = finish_plate(img, 432, 0.34)
    return img


def d2_dilation_curve():
    img = parchment(441)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "THE RATE CURVE", sub="CLOCK RATE VS DEPTH IN THE FIELD")
    d.rectangle((110, 350, W - 110, 460), fill=RUST + (26,))
    x0, y0, x1, y1 = 220, 330, 1380, 880
    # axes
    d.line((x0, y0, x0, y1), fill=BANDC + (255,), width=10)
    d.line((x0, y1, x1, y1), fill=BANDC + (255,), width=10)
    # shaded region under the curve
    pts = [(x0, y1)]
    for i in range(60):
        u = i / 59.0
        x = x0 + u * (x1 - x0 - 60)
        y = y0 + (1 - 1 / (1 + 2.6 * u)) * (y1 - y0 - 60)
        pts.append((x, y))
    pts.append((x1 - 60, y1))
    d.polygon(pts, fill=NAVY + (46,))
    # the curve
    curve = [(x0 + u * (x1 - x0 - 60), y0 + (1 - 1 / (1 + 2.6 * u)) * (y1 - y0 - 60))
             for u in (i / 59.0 for i in range(60))]
    d.line(curve, fill=RUST + (255,), width=10)
    for u in (0.15, 0.4, 0.75):
        x, y = curve[int(u * 59)]
        d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=RUST + (255,))
    # ticks + labels
    for k in range(5):
        x = x0 + k * (x1 - x0) // 4
        d.line((x, y1, x, y1 + 22), fill=BANDC + (255,), width=5)
        d.line((x0 - 22, y0 + k * (y1 - y0) // 4, x0, y0 + k * (y1 - y0) // 4),
               fill=BANDC + (255,), width=5)
    d.text((x0, y1 + 40), "DEPTH IN THE FIELD", font=inter(30), fill=INK + (240,))
    d.text((x0 - 150, y0 - 60), "CLOCK RATE", font=inter(30), fill=INK + (240,))
    big_number(d, "RATE DROPS", (W - 330, 180), 104)
    return finish_plate(img, 442, 0.18)


def b4_probe_clock():
    img = vgrad(W, H, (18, 22, 38), (52, 40, 33)).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    starfield(d, 451, 60, 500)
    # glowing disk below
    for k in range(5):
        r = 900 - k * 60
        d.arc((W // 2 - r, 1050 - 200 + k * 30, W // 2 + r, 1050 + 500), 200, 340,
              fill=(205, 130, 70, 235 - k * 30), width=26)
    # probe silhouette
    px, py = W // 2, 520
    d.rounded_rectangle((px - 150, py - 70, px + 150, py + 70), radius=40,
                        fill=BANDC + (255,), outline=CREAM + (200,), width=5)
    d.rectangle((px - 340, py - 26, px - 170, py + 26), fill=BANDC + (255,),
                outline=CREAM + (150,), width=4)
    d.rectangle((px + 170, py - 26, px + 340, py + 26), fill=BANDC + (255,),
                outline=CREAM + (150,), width=4)
    clock_face(d, px, py, 52, hour_angle=215, minute_angle=100)
    for k in range(3):
        d.arc((px - 200 - k * 40, py - 200 - k * 40, px + 200 + k * 40, py + 200 + k * 40),
              90, 150, fill=RUST + (220 - k * 40,), width=6)
    img = finish_plate(img, 452, 0.32)
    return img


def b5_gps_card():
    img = parchment(461)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "MEASURED EVERY DAY", sub="THE GPS CONSTELLATION'S CLOCKS")
    d.rectangle((110, 350, W - 110, 470), fill=RUST + (26,))
    cx, cy = W // 2, 660
    # Earth with grid
    d.ellipse((cx - 260, cy - 260, cx + 260, cy + 260), fill=NAVY + (150,),
              outline=NAVY + (255,), width=6)
    for k in range(5):
        yo = -200 + k * 100
        d.arc((cx - 260, cy + yo - 60, cx + 260, cy + yo + 60 + 2 * 260), 20, 160,
              fill=CREAM + (110,), width=3)
    # orbit ring + satellites
    d.ellipse((cx - 560, cy - 210, cx + 560, cy + 210), outline=RUST + (230,), width=7)
    for k in range(6):
        a = 2 * math.pi * k / 6
        x, y = cx + 560 * math.cos(a), cy + 210 * math.sin(a)
        d.ellipse((x - 18, y - 18, x + 18, y + 18), fill=RUST + (255,))
    label(d, "20,200 KM ORBIT", (cx + 480, cy - 130), (1130, 350))
    big_number(d, "38", (W - 300, 640), 200)
    d.text((W - 420, 860), "MICROSECONDS / DAY", font=inter(34), fill=RUST + (255,))
    return finish_plate(img, 462, 0.18)


def b6_freeze_frame():
    img = parchment(471)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "THE HORIZON", sub="TWO VIEWS OF ONE FALL")
    mid = W // 2
    d.rectangle((110, 250, W - 110, 330), fill=RUST + (28,))
    d.line((mid, 200, mid, 960), fill=BANDC + (255,), width=5)
    # left: local view - probe crossing the edge
    d.rounded_rectangle((80, 260, mid - 50, 940), radius=16, fill=NAVY + (36,),
                        outline=BANDC + (255,), width=4)
    d.ellipse((mid - 340, 430, mid + 40, 900), fill=BANDC + (255,))
    d.rounded_rectangle((mid - 520, 560, mid - 360, 660), radius=30,
                        fill=RUST + (200,), outline=CREAM + (220,), width=4)
    label(d, "LOCAL", (mid - 440, 700), (150, 350))
    # right: distant view - frozen ghost on the rim
    d.rounded_rectangle((mid + 50, 260, W - 80, 940), radius=16, fill=BANDC + (235,),
                        outline=BANDC + (255,), width=4)
    d.ellipse((mid + 60, 430, mid + 440, 900), fill=(8, 8, 10, 255),
              outline=(239, 230, 212, 70), width=3)
    d.rounded_rectangle((mid + 210, 545, mid + 300, 610), radius=18,
                        fill=(120, 96, 80, 190), outline=(205, 130, 70, 200), width=3)
    label(d, "DISTANT", (mid + 255, 700), (W - 300, 350))
    big_number(d, "FROZEN FROM AFAR", (W // 2, 160), 108)
    return finish_plate(img, 472, 0.18)


def b7_clock_sky():
    img = vgrad(W, H, (16, 20, 36), (60, 44, 34)).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    starfield(d, 481, 100)
    # horizon glow ring
    for k in range(4):
        r = 760 - k * 50
        d.arc((W // 2 - r, 620, W // 2 + r, 620 + r * 0.7), 200, 340,
              fill=(205, 130, 70, 190 - k * 35), width=30)
    clock_face(d, W // 2, 470, 240, tick_col=CREAM, face_col=(24, 26, 34),
               hand_col=CREAM, hour_angle=205, minute_angle=70)
    img = finish_plate(img, 482, 0.32)
    return img


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_bh_hero": b1_bh_hero(),
        "B2_two_clocks": b2_two_clocks(),
        "D1_spacetime_funnel": d1_spacetime_funnel(),
        "B3_horizon_detail": b3_horizon_detail(),
        "D2_dilation_curve": d2_dilation_curve(),
        "B4_probe_clock": b4_probe_clock(),
        "B5_gps_card": b5_gps_card(),
        "B6_freeze_frame": b6_freeze_frame(),
        "B7_clock_sky": b7_clock_sky(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("D1_spacetime_funnel", "D2_dilation_curve", "B5_gps_card"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("D1_spacetime_funnel", "diagram"),
                    ("D2_dilation_curve", "diagram"),
                    ("B5_gps_card", "diagram")])
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=71, base_hz=82.4, dur=75.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=81, kind="swell", dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    if min(d_scores) < 75:
        print("LOW DENSITY")
        raise SystemExit(1)
    print("blackhole_clocks cards OK")


if __name__ == "__main__":
    main()
