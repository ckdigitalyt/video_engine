"""aircraft_wing_lift — deterministic plates + diagram cards + bed/SFX.

All art Pillow-drawn (no image-model calls, no network), vintage parchment /
blueprint family per the story's visual bible.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, BUILD, CREAM, H, INK, MUTED, NAVY, NAVY_D, PARCH,
                         PARCH_L, RUST, W, arrow, bgrid, bebas, big_number, clock_face,
                         finish_plate, footer_band, grain, hatch_polygon, inter, label,
                         parchment, register_diagram, save_plate, synth_bed, synth_sfx,
                         title_bar, vignette, write_manifest, mottle, vgrad)
from PIL import Image, ImageChops, ImageDraw, ImageFilter

import numpy as np

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)


# ---------------------------------------------------------------- plates ---

def wing_plate(dusk_seed, horizon_y, rim_col=(212, 148, 84), stars=False):
    """Dusk sky + 747 wing seen from below with two nacelles."""
    top = (24, 30, 48)
    bot = (96, 70, 58)
    img = vgrad(W, H, top, bot).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    # cloud bands
    rnd = __import__("random").Random(dusk_seed)
    for _ in range(7):
        cy = rnd.randint(int(horizon_y * 0.4), int(horizon_y * 1.4))
        cx = rnd.randint(0, W)
        rw = rnd.randint(260, 620)
        d.ellipse((cx - rw, cy - rnd.randint(18, 40), cx + rw, cy + rnd.randint(14, 34)),
                  fill=(14, 18, 32, rnd.randint(50, 90)))
    if stars:
        for _ in range(70):
            x, y = rnd.randint(0, W), rnd.randint(0, int(horizon_y * 0.55))
            v = rnd.randint(120, 210)
            d.ellipse((x, y, x + 2, y + 2), fill=(239, 230, 212, v))
    # horizon glow band
    glow = vgrad(W, 200, (0, 0, 0), rim_col)
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band.paste(glow.convert("RGBA"), (0, horizon_y - 150))
    band = band.filter(ImageFilter.GaussianBlur(70))
    img = Image.alpha_composite(img, ImageChops.multiply(img, band))
    d = ImageDraw.Draw(img, "RGBA")
    # wing from lower-left toward upper-right
    wing = [(0, 980), (300, 830), (700, 690), (1080, 585), (1420, 505), (W, 470),
            (W, 640), (1200, 690), (900, 780), (560, 900), (0, 1060)]
    d.polygon(wing, fill=(16, 20, 34, 255))
    # rim light along leading edge (one polyline)
    d.line([(0, 980), (300, 830), (700, 690), (1080, 585), (W, 470)],
           fill=rim_col + (225,), width=8, joint="curve")
    # flap track fairings
    for fx in (520, 830, 1120):
        d.polygon([(fx, 720), (fx + 60, 700), (fx + 78, 800), (fx + 20, 830)],
                  fill=(12, 15, 26, 255), outline=(239, 230, 212, 60))
    # nacelles under the wing
    for nx, ny in ((620, 830), (980, 700)):
        d.rounded_rectangle((nx, ny, nx + 210, ny + 110), radius=48,
                            fill=(14, 18, 30, 255), outline=(239, 230, 212, 120), width=4)
        d.ellipse((nx + 158, ny + 12, nx + 214, ny + 98), fill=(28, 24, 22, 255),
                  outline=(239, 230, 212, 140), width=4)
        d.line((nx + 30, ny + 55, nx + 150, ny + 55), fill=rim_col + (170,), width=4)
    img = finish_plate(img, dusk_seed, 0.3)
    return img


def b1_wing_hero():
    img = wing_plate(101, 640)
    return img


def b7_wing_dusk():
    img = wing_plate(107, 760)
    d = ImageDraw.Draw(img, "RGBA")
    # calmer dusk: warm haze band low
    haze = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dh = ImageDraw.Draw(haze)
    dh.rectangle((0, 700, W, 860), fill=(180, 110, 66, 40))
    img = Image.alpha_composite(img.convert("RGBA"), haze.filter(ImageFilter.GaussianBlur(60)))
    img = grain(img, 108)
    return vignette(img, 0.28)


# ------------------------------------------------------- diagram cards -----

def airfoil_pts(cx, cy, span, thick=1.0):
    """Closed airfoil curve: cambered top, near-flat bottom. Returns pts."""
    pts = []
    for i in range(120):
        u = i / 119.0            # 0 = trailing edge -> 1 = nose? keep LE at left
        x = cx - span * 0.5 + u * span
        # thickness distribution (NACA-ish rounded nose, sharp tail)
        th = thick * 62 * (1.9 * math.sqrt(max(u, 1e-6)) - 1.02 * u - 0.20 * u ** 2 + 0.32 * u ** 3)
        # camber: curved top bias
        cam = -46 * math.sin(math.pi * min(1.0, u * 1.15)) ** 1.2
        pts.append((x, cy + cam - th * 0.5))
    for i in range(120):
        u = 1 - i / 119.0
        x = cx - span * 0.5 + u * span
        th = thick * 62 * (1.9 * math.sqrt(max(u, 1e-6)) - 1.02 * u - 0.20 * u ** 2 + 0.32 * u ** 3)
        cam = -46 * math.sin(math.pi * min(1.0, u * 1.15)) ** 1.2
        pts.append((x, cy + cam + th * 0.62))
    return pts


def b2_wing_blueprint():
    img = parchment(201)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    title_bar(d, "WING SECTION", sub="EDGE-ON SLICE - STRUCTURAL BLUEPRINT")
    # chord line
    cx, cy, span = W // 2, 560, 1050
    d.rectangle((110, 440, W - 110, 600), fill=RUST + (26,))
    d.line((cx - span // 2, cy, cx + span // 2, cy), fill=RUST + (200,), width=4)
    for u in range(0, 101, 10):
        x = cx - span // 2 + span * u / 100
        d.line((x, cy - 12, x, cy + 12), fill=RUST + (170,), width=3)
    pts = airfoil_pts(cx, cy, span, 1.05)
    d.polygon(pts, fill=NAVY + (150,), outline=NAVY + (255,))
    hatch_polygon(img, pts, CREAM, 70, 18)
    d.line((cx - span // 2, cy, cx + span // 2, cy), fill=RUST + (230,), width=4)
    label(d, "CHORD LINE", (cx + 260, cy), (1180, 300))
    label(d, "CAMBER", (cx - 210, cy - 52), (150, 250))
    label(d, "NOSE", (cx - span // 2 + 8, cy), (120, 700))
    label(d, "TAIL", (cx + span // 2 - 8, cy - 4), (1180, 760))
    # solid ruler strip under the chord
    d.rectangle((cx - span // 2, cy + 90, cx + span // 2, cy + 150), fill=NAVY + (200,))
    for u in range(0, 101, 5):
        x = cx - span // 2 + span * u / 100
        d.line((x, cy + 90, x, cy + (120 if u % 10 else 140)), fill=CREAM + (210,), width=3)
    big_number(d, "1 SLICE", (W - 280, 205), 150)

    return finish_plate(img, 202, 0.18)


def b3_airfoil_card():
    img = parchment(211)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "THE AIRFOIL", sub="FLOW LEFT TO RIGHT")
    cx, cy, span = W // 2, 600, 1000
    d.rectangle((110, 350, W - 110, 490), fill=RUST + (26,))
    # streamlines bending over the top
    for k in range(6):
        y0 = 150 + k * 44
        pts = []
        for i in range(90):
            u = i / 89.0
            x = 90 + u * (W - 180)
            sag = 150 * math.exp(-((u - 0.42) ** 2) / 0.028) * (1.0 - 0.09 * k)
            pts.append((x, y0 + sag))
        d.line(pts, fill=NAVY + (200 - k * 18,), width=5 if k < 3 else 3)
    for k in range(3):
        y0 = 700 + k * 52
        pts = [(90 + u * (W - 180), y0 - 16 * math.sin(math.pi * u) * (1 - k * 0.3))
               for u in (i / 59.0 for i in range(60))]
        d.line(pts, fill=NAVY + (150 - k * 25,), width=3)
    pts = airfoil_pts(cx, cy, span, 1.0)
    d.polygon(pts, fill=NAVY + (150,), outline=NAVY + (255,))
    hatch_polygon(img, pts, CREAM, 70, 18)
    label(d, "CURVED TOP", (cx - 120, cy - 120), (140, 320))
    label(d, "FLAT BACK", (cx + 380, cy + 26), (1150, 760))
    big_number(d, "SQUEEZED", (W - 320, 165), 128)

    return finish_plate(img, 212, 0.18)


def b3_pressure_card():
    img = parchment(221)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "PRESSURE FIELD", sub="ABOVE VS BELOW THE SECTION")
    cx, cy, span = W // 2, 560, 950
    d.rectangle((70, 150, W - 70, 380), fill=RUST + (26,))
    d.rectangle((70, 740, W - 70, 950), fill=NAVY + (34,))
    pts = airfoil_pts(cx, cy, span, 1.0)
    d.polygon(pts, fill=NAVY + (95,), outline=NAVY + (255,))
    # sparse LONG suction arrows above (band kept clear of text)
    for k in range(5):
        x = 220 + k * 150
        arrow(d, (x, 375), (x, 170), RUST, 13, 38)
    # dense short push arrows below (band kept clear of text)
    for k in range(11):
        x = 180 + k * 88
        arrow(d, (x, 946), (x, 800), NAVY, 9, 26)
    big_number(d, "LOW", (1265, 235), 100)
    big_number(d, "HIGH", (1265, 815), 100, col=CREAM)
    d.text((70, H - 130), "MORE ARROWS BELOW = MORE PUSH FROM BELOW",
           font=inter(28), fill=INK + (230,))
    return finish_plate(img, 222, 0.18)


def b4_bernoulli_card():
    img = parchment(231)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    title_bar(d, "SPEED VS PRESSURE", sub="THE STREAMTUBE OVER THE CURVE")
    cx, cy = W // 2, 600
    d.rectangle((110, 350, W - 110, 490), fill=RUST + (26,))
    # streamtube: two boundary curves squeezing over the camber
    top, bot = [], []
    for i in range(80):
        u = i / 79.0
        x = 90 + u * (W - 180)
        pinch = 120 * math.exp(-((u - 0.45) ** 2) / 0.02)
        top.append((x, 300 + 150 * math.exp(-((u - 0.45) ** 2) / 0.03) - pinch * 0.4))
        bot.append((x, 720 - 170 * math.exp(-((u - 0.45) ** 2) / 0.03)))
    d.line(top, fill=NAVY + (230,), width=6)
    d.line(bot, fill=NAVY + (230,), width=6)
    d.polygon(top + bot[::-1], fill=NAVY + (28,))
    pts = airfoil_pts(cx, cy, 780, 0.8)
    d.polygon(pts, fill=NAVY + (80,), outline=NAVY + (255,))
    # slow arrows at entry (small), fast arrows at throat (long)
    for k in range(3):
        y = 380 + k * 90
        arrow(d, (150, y), (260, y), MUTED, 7, 18)
        arrow(d, (700, y - 40), (1010, y - 40), RUST, 11, 28)
    d.rectangle((110, 780, W - 110, 880), fill=RUST + (26,))
    label(d, "SLOW", (200, 560), (110, 820))
    label(d, "FASTER", (860, 330), (1120, 250))
    big_number(d, "V UP = P DOWN", (W // 2, 130), 120)
    return finish_plate(img, 232, 0.18)


def b4_streamline_detail():
    img = mottle(Image.new("RGB", (W, H), PARCH), 241)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((90, 280, W - 90, 500), fill=RUST + (24,))
    d.rectangle((90, 560, W - 90, 720), fill=NAVY + (26,))
    for k in range(11):
        y0 = 90 + k * 60
        pts = []
        for i in range(110):
            u = i / 109.0
            x = u * (W + 60) - 30
            sag = 160 * math.exp(-((u - 0.5) ** 2) / 0.045) * (0.55 + 0.45 * (1 - abs(k - 5) / 6))
            pts.append((x, y0 + sag))
        col = INK if k % 2 == 0 else NAVY
        d.line(pts, fill=col + (215,), width=5 if k % 2 == 0 else 3)
        # engraving hatch under each streamline
        for i in range(8, 100, 10):
            x, y = pts[i]
            d.line((x, y + 6, x - 10, y + 22), fill=col + (90,), width=2)
    # cambered surface below the flow (engraved wing section, no text)
    surf = airfoil_pts(W // 2, 856, 680, 0.85)
    d.polygon(surf, fill=NAVY + (55,), outline=INK + (255,))
    hatch_polygon(img, surf, INK, 60, 12)
    img = grain(img, 242)
    return vignette(img, 0.3)


def b5_newton_card():
    img = parchment(251)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "NEWTON'S SIDE", sub="ACTION DOWN  -  REACTION UP")
    cx, cy = W // 2, 520
    d.rectangle((110, 350, W - 110, 500), fill=RUST + (26,))
    ang = math.radians(9)
    pts = airfoil_pts(cx, cy, 880, 0.95)

    def rot(p):
        x, y = p[0] - cx, p[1] - cy
        return (cx + x * math.cos(ang) - y * math.sin(ang),
                cy + x * math.sin(ang) + y * math.cos(ang))
    rpts = [rot(p) for p in pts]
    d.polygon(rpts, fill=NAVY + (150,), outline=NAVY + (255,))
    hatch_polygon(img, rpts, CREAM, 70, 18)
    # deflected streamlines behind the wing
    for k in range(4):
        y0 = 360 + k * 60
        pts2 = []
        for i in range(70):
            u = i / 69.0
            x = 120 + u * (W - 240)
            drop = 0.0 if u < 0.45 else (u - 0.45) * 300 * (1 - k * 0.12)
            pts2.append((x, y0 + drop))
        d.line(pts2, fill=NAVY + (190 - k * 20,), width=4)
    # downwash arrow + reaction arrow
    arrow(d, (cx + 240, cy + 120), (cx + 320, cy + 420), NAVY, 14, 36)
    label(d, "DOWNWASH", (cx + 300, cy + 380), (1150, 880))
    arrow(d, (cx - 260, cy - 60), (cx - 260, cy - 430), RUST, 16, 44)
    label(d, "LIFT", (cx - 260, cy - 470), (170, 200))
    big_number(d, "EQUAL - OPPOSITE", (W // 2, 860), 112)

    return finish_plate(img, 252, 0.18)


def b6_stall_card():
    img = parchment(261)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "THE TWIST", sub="SAME CURVE - PUSHED TOO FAR")
    mid = W // 2
    d.rectangle((90, 310, mid - 40, 450), fill=RUST + (26,))
    d.rectangle((mid + 40, 310, W - 90, 450), fill=NAVY + (30,))
    d.line((mid, 150, mid, 950), fill=INK + (150,), width=4)
    for k, (x0, ang_deg, sep) in enumerate(((90, 7, False), (mid + 80, 19, True))):
        cx, cy = x0 + 330, 540
        ang = math.radians(ang_deg)
        pts = airfoil_pts(cx, cy, 620, 0.9)

        def rot(p):
            x, y = p[0] - cx, p[1] - cy
            return (cx + x * math.cos(ang) - y * math.sin(ang),
                    cy + x * math.sin(ang) + y * math.cos(ang))
        rpts = [rot(p) for p in pts]
        d.polygon(rpts, fill=NAVY + (150,), outline=NAVY + (255,))
        for i in range(4):
            y0 = 340 + i * 62
            pts2 = []
            for j in range(60):
                u = j / 59.0
                x = x0 + 40 + u * 560
                base = y0 + (u - 0.45) * (2.2 * ang_deg)
                if sep and u > 0.42:
                    swirl = 46 * math.sin(u * 34 + i * 2.1) * (u - 0.42)
                    pts2.append((x, base + swirl + (u - 0.42) * 130))
                else:
                    pts2.append((x, base - 60 * math.exp(-((u - 0.45) ** 2) / 0.02)))
            col = NAVY + (200 - i * 25,) if not sep else RUST + (200 - i * 25,)
            d.line(pts2, fill=col, width=4)
    label(d, "LIFTING", (330, 320), (150, 210))
    label(d, "STALLED", (mid + 380, 320), (W - 330, 210))
    big_number(d, "7 DEG", (330, 795), 112)
    big_number(d, "19 DEG", (mid + 340, 795), 112)

    return finish_plate(img, 262, 0.18)


# ----------------------------------------------------------------- main ----

def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_wing_hero": b1_wing_hero(),
        "B2_wing_blueprint": b2_wing_blueprint(),
        "B3_airfoil_card": b3_airfoil_card(),
        "B3_pressure_card": b3_pressure_card(),
        "B4_bernoulli_card": b4_bernoulli_card(),
        "B4_streamline_detail": b4_streamline_detail(),
        "B5_newton_card": b5_newton_card(),
        "B6_stall_card": b6_stall_card(),
        "B7_wing_dusk": b7_wing_dusk(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_wing_blueprint", "B3_airfoil_card", "B4_bernoulli_card",
                 "B5_newton_card"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_wing_blueprint", "diagram"),
                    ("B3_airfoil_card", "diagram"),
                    ("B4_bernoulli_card", "diagram"),
                    ("B5_newton_card", "diagram")])
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=31, base_hz=110.0, dur=75.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=41, kind="swell", dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    if min(d_scores) < 75:
        print("LOW DENSITY")
        raise SystemExit(1)
    print("aircraft_wing_lift cards OK")


if __name__ == "__main__":
    main()
