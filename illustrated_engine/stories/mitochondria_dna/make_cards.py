"""mitochondria_dna — deterministic plates + diagram cards + bed/SFX.

All art Pillow-drawn (no image-model calls, no network), vintage parchment /
cellular-diagram family per the story's visual bible.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, BANDC, CREAM, H, INK, MUTED, NAVY, NAVY_D,
                         PARCH, PARCH_L, RUST, W, arrow, bgrid, bebas,
                         big_number, finish_plate, footer_band, grain,
                         hatch_polygon, inter, label, mottle, parchment,
                         register_diagram, save_plate, synth_bed, synth_sfx,
                         title_bar, vignette, vgrad, write_manifest)
from PIL import Image, ImageDraw, ImageFilter

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

DARK_WARM = (58, 44, 36)  # deep warm matrix ground (hue bin 1 family)


def mito(d, cx, cy, rw, rh, fill_alpha=150, cristae=True, outline_alpha=255):
    """Bean-shaped mitochondrion with folded cristae."""
    pts = []
    for i in range(80):
        a = 2 * math.pi * i / 80
        r = 1 + 0.06 * math.cos(3 * a)
        pts.append((cx + rw * r * math.cos(a), cy + rh * r * math.sin(a)))
    d.polygon(pts, fill=NAVY + (fill_alpha,), outline=NAVY + (outline_alpha,), width=5)
    if cristae:
        for k in range(6):
            t = 0.18 + 0.11 * k
            fx = cx - rw * 0.7 + t * 2 * rw * 0.72
            top = cy - rh * 0.55 * (1 - abs(t - 0.5) * 0.7)
            bot = cy + rh * 0.55 * (1 - abs(t - 0.5) * 0.7)
            mid = (top + bot) / 2
            if k % 2 == 0:
                d.line((fx, top, fx - 26, mid, fx, bot), fill=RUST + (200,), width=6)
            else:
                d.line((fx, bot, fx + 26, mid, fx, top), fill=RUST + (170,), width=6)
    return pts


def b1_cell_hero():
    img = mottle(Image.new("RGB", (W, H), PARCH), 301)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((110, 260, W - 110, 520), fill=RUST + (30,))
    d.rectangle((110, 640, W - 110, 800), fill=NAVY + (26,))
    d.rectangle((110, 860, W - 110, 950), fill=RUST + (30,))
    # nucleus
    d.ellipse((180, 220, 560, 600), fill=NAVY + (150,), outline=NAVY + (255,), width=6)
    d.ellipse((300, 340, 440, 480), fill=NAVY + (220,))
    # ER squiggles
    for k in range(4):
        y = 200 + k * 60
        pts = [(x, y + 30 * math.sin(x / 90 + k)) for x in range(600, W - 80, 24)]
        d.line(pts, fill=NAVY + (160 - k * 20,), width=4)
    # mitochondria (the strangers that stand out)
    for cx, cy, rw, rh in ((880, 420, 190, 110), (1180, 640, 210, 120),
                           (560, 800, 170, 100), (1050, 860, 160, 92)):
        mito(d, cx, cy, rw, rh, fill_alpha=110)
    # vesicles
    for _ in range(26):
        import random as _r
        x, y = _r.Random(_).randint(150, W - 150), _r.Random(_ + 7).randint(180, H - 150)
        d.ellipse((x, y, x + 16, y + 16), fill=RUST + (210,))
    img = grain(img, 302)
    return vignette(img, 0.28)


def b2_mito_macro():
    img = mottle(Image.new("RGB", (W, H), PARCH), 311)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((90, 240, W - 90, 900), fill=RUST + (24,))
    mito(d, W // 2, 560, 560, 300, fill_alpha=120, outline_alpha=255)
    # inner membrane (second outline)
    d.ellipse((W // 2 - 500, 320, W // 2 + 500, 800), outline=NAVY + (170,), width=4)
    img = grain(img, 312)
    return vignette(img, 0.3)


def d1_mito_cutaway():
    img = parchment(321)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "INSIDE THE MITOCHONDRION", sub="CUTAWAY - WHAT THE SECRET LOOKS LIKE")
    d.rectangle((110, 330, W - 110, 520), fill=RUST + (26,))
    cx, cy = W // 2, 620
    mito(d, cx, cy, 520, 260, fill_alpha=60, outline_alpha=255)
    # DNA ring highlighted
    rx, ry = cx + 210, cy + 30
    d.ellipse((rx - 70, ry - 46, rx + 70, ry + 46), outline=RUST + (255,), width=9)
    for k in range(10):
        a = 2 * math.pi * k / 10
        d.line((rx + 60 * math.cos(a), ry + 38 * math.sin(a),
                rx + 74 * math.cos(a), ry + 48 * math.sin(a)), fill=RUST + (230,), width=4)
    label(d, "DNA RING", (rx, ry - 50), (1210, 380))
    label(d, "CRISTAE", (cx - 160, cy - 100), (150, 380))
    label(d, "MATRIX", (cx - 60, cy + 150), (170, 850))
    label(d, "OUTER MEMBRANE", (cx - 420, cy - 190), (620, 850))
    big_number(d, "37 GENES", (W - 320, 200), 120)
    return finish_plate(img, 322, 0.18)


def b3_dna_loop():
    img = Image.new("RGB", (W, H), DARK_WARM)
    d = ImageDraw.Draw(img, "RGBA")
    # matrix shading
    for k in range(6):
        d.ellipse((200 - k * 60, 200 - k * 40, W + k * 40, H + k * 30),
                  outline=CREAM + (14,), width=2)
    cx, cy, r = W // 2, H // 2, 300
    d.ellipse((cx - r, cy - r * 0.72, cx + r, cy + r * 0.72), outline=CREAM + (235,), width=8)
    d.ellipse((cx - r + 26, cy - r * 0.72 + 20, cx + r - 26, cy + r * 0.72 - 20),
              outline=RUST + (220,), width=5)
    for k in range(36):
        a = 2 * math.pi * k / 36
        x, y = cx + r * math.cos(a), cy + r * 0.72 * math.sin(a)
        d.line((x, y, x + 18 * math.cos(a), y + 13 * math.sin(a)),
               fill=CREAM + (190,), width=4)
    for k in range(9):
        a = 2 * math.pi * k / 9 + 0.3
        x, y = cx + r * 0.55 * math.cos(a), cy + r * 0.4 * math.sin(a)
        d.ellipse((x - 8, y - 8, x + 8, y + 8), fill=RUST + (200,))
    img = finish_plate(img, 332, 0.34)
    return img


def d2_endosymbiosis():
    img = parchment(341)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "ENDOSYMBIOSIS", sub="SWALLOWED - AND KEPT")
    d.rectangle((110, 250, W - 110, 350), fill=RUST + (30,))
    panels = ((90, "THE BACTERIUM"), (590, "THE ENGULFING"), (1090, "THE TENANT"))
    for x0, cap in panels:
        d.rounded_rectangle((x0, 260, x0 + 356, 850), radius=18,
                            fill=RUST + (22,), outline=BANDC + (255,), width=4)
        d.text((x0 + 24, 880), cap, font=bebas(40), fill=NAVY + (255,))
    # p1: rod bacterium alone
    d.rounded_rectangle((150, 480, 386, 620), radius=70, fill=RUST + (200,),
                        outline=NAVY + (255,), width=5)
    for k in range(4):
        d.line((386, 520 + k * 26, 440, 530 + k * 26), fill=NAVY + (200,), width=4)
    # p2: host folding around the rod
    d.ellipse((640, 330, 930, 780), fill=NAVY + (40,), outline=BANDC + (255,), width=5)
    d.rounded_rectangle((700, 500, 890, 610), radius=55, fill=RUST + (200,),
                        outline=NAVY + (255,), width=5)
    d.arc((640, 330, 930, 780), 300, 60, fill=RUST + (230,), width=8)
    # p3: settled organelle inside host
    d.ellipse((1140, 330, 1420, 780), fill=NAVY + (40,), outline=BANDC + (255,), width=5)
    mito(d, 1280, 555, 120, 90, fill_alpha=95)
    arrow(d, (470, 560), (560, 560), RUST, 10, 26)
    arrow(d, (980, 560), (1070, 560), RUST, 10, 26)
    big_number(d, "KEPT, NOT DIGESTED", (W // 2, 140), 104)
    return finish_plate(img, 342, 0.18)


def b4_engulf_detail():
    img = mottle(Image.new("RGB", (W, H), PARCH), 351)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((90, 260, W - 90, 520), fill=RUST + (24,))
    # membrane band folding
    pts_top = [(x, 300 + 180 * math.exp(-((x - 700) ** 2) / 90000)) for x in range(100, W - 60, 20)]
    pts_bot = [(x, y + 210) for x, y in pts_top]
    d.line(pts_top, fill=NAVY + (255,), width=16)
    d.line(pts_bot, fill=NAVY + (255,), width=16)
    hatch_polygon(img, pts_top + pts_bot[::-1], NAVY, 60, 18)
    # rod guest inside the fold
    d.rounded_rectangle((560, 470, 920, 640), radius=85, fill=RUST + (140,),
                        outline=NAVY + (255,), width=6)
    for k in range(5):
        d.line((920, 500 + k * 30, 990, 512 + k * 30), fill=NAVY + (210,), width=5)
    img = grain(img, 352)
    return vignette(img, 0.3)


def b5_kept_traits():
    img = parchment(361)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "WHAT IT KEPT", sub="BACTERIAL TRAITS THAT NEVER LEFT")
    d.rectangle((110, 360, W - 110, 540), fill=RUST + (26,))
    cx, cy = W // 2, 640
    mito(d, cx, cy, 460, 230, fill_alpha=60, outline_alpha=255)
    d.ellipse((cx - 400, cy - 180, cx + 400, cy + 180), outline=NAVY + (220,), width=5)
    # ribosome dots
    for k in range(16):
        a = 2 * math.pi * k / 16
        x, y = cx + 240 * math.cos(a), cy + 120 * math.sin(a)
        d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=RUST + (235,))
    label(d, "OUTER MEMBRANE", (cx - 380, cy - 165), (140, 380))
    label(d, "INNER MEMBRANE", (cx - 310, cy - 130), (120, 820))
    label(d, "RIBOSOMES", (cx + 170, cy - 60), (1210, 380))
    big_number(d, "2 MEMBRANES", (W - 350, 190), 110)
    return finish_plate(img, 362, 0.18)


def b6_maternal_card():
    img = parchment(371)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "THE MATERNAL LINE", sub="WHOSE MITOCHONDRIA YOU CARRY")
    mid = W // 2
    d.rectangle((110, 260, W - 110, 330), fill=RUST + (28,))
    d.rectangle((110, 760, mid - 40, 950), fill=RUST + (26,))
    d.line((mid, 200, mid, 950), fill=BANDC + (255,), width=5)
    # egg side: rich in mitochondria
    d.ellipse((150, 300, 570, 720), fill=NAVY + (40,), outline=NAVY + (230,), width=6)
    for k in range(12):
        a = 2 * math.pi * k / 12
        x, y = 360 + 150 * math.cos(a), 510 + 150 * math.sin(a)
        d.ellipse((x - 20, y - 14, x + 20, y + 14), fill=RUST + (225,))
    label(d, "EGG", (360, 740), (150, 820))
    arrow(d, (360, 800), (360, 900), RUST, 10, 26)
    d.text((300, 930), "PASSED ON", font=bebas(44), fill=RUST + (255,))
    # sperm side: none
    d.ellipse((mid + 190, 420, mid + 250, 480), fill=NAVY + (90,),
              outline=NAVY + (200,), width=4)
    d.line((mid + 250, 450, mid + 460, 450), fill=NAVY + (160,), width=10)
    for k in range(5):
        d.line((mid + 380 + k * 20, 428, mid + 390 + k * 20, 472), fill=NAVY + (120,), width=3)
    label(d, "SPERM", (mid + 300, 740), (W - 260, 820))
    arrow(d, (mid + 300, 800), (mid + 300, 900), NAVY, 8, 22)
    d.text((mid + 170, 930), "NOT PASSED ON", font=bebas(44), fill=NAVY + (255,))
    big_number(d, "MOTHER'S LINE", (W // 2, 150), 110)
    return finish_plate(img, 372, 0.18)


def b7_cell_glow():
    img = Image.new("RGB", (W, H), DARK_WARM)
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse((180, 120, W - 180, H - 100), fill=(30, 26, 24, 255),
              outline=CREAM + (90,), width=5)
    for cx, cy, rw, rh in ((480, 420, 200, 110), (980, 340, 190, 105),
                           (1150, 700, 210, 115)):
        mito(d, cx, cy, rw, rh, fill_alpha=90)
        d.ellipse((cx - rw, cy - rh, cx + rw, cy + rh), outline=CREAM + (150,), width=4)
    # dividing mitochondrion
    d.ellipse((380, 640, 620, 800), fill=RUST + (110,), outline=CREAM + (200,), width=5)
    d.ellipse((560, 640, 800, 800), fill=RUST + (110,), outline=CREAM + (200,), width=5)
    d.ellipse((540, 660, 640, 780), fill=(30, 26, 24, 255))
    img = finish_plate(img, 382, 0.32)
    return img


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_cell_hero": b1_cell_hero(),
        "B2_mito_macro": b2_mito_macro(),
        "D1_mito_cutaway": d1_mito_cutaway(),
        "B3_dna_loop": b3_dna_loop(),
        "D2_endosymbiosis": d2_endosymbiosis(),
        "B4_engulf_detail": b4_engulf_detail(),
        "B5_kept_traits": b5_kept_traits(),
        "B6_maternal_card": b6_maternal_card(),
        "B7_cell_glow": b7_cell_glow(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("D1_mito_cutaway", "D2_endosymbiosis", "B5_kept_traits"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("D1_mito_cutaway", "diagram"),
                    ("D2_endosymbiosis", "diagram"),
                    ("B5_kept_traits", "diagram")])
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=51, base_hz=98.0, dur=75.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=61, kind="swell", dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    if min(d_scores) < 75:
        print("LOW DENSITY")
        raise SystemExit(1)
    print("mitochondria_dna cards OK")


if __name__ == "__main__":
    main()
