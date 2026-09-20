"""cell_scale_dive — deterministic plates + diagram cards + bed/SFX.

All art Pillow-drawn (no image-model calls, no network), vintage parchment /
cellular-diagram family per the story's visual bible. Big fills stay in
desaturated chrome (GREY_NAVY) so they drop out of the S>0.15 hue mask;
saturated NAVY/RUST only as small accents + 1-2 rust glows per plate.
"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, BANDC, CREAM, INK, NAVY, NAVY_D, PARCH, RUST,
                         W, H, arrow, bebas, big_number, finish_plate,
                         footer_band, grain, label, mottle, parchment,
                         register_diagram, save_plate, synth_bed, synth_sfx,
                         title_bar, vignette, write_manifest)
from PIL import Image, ImageDraw, ImageFilter

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

GREY_NAVY = (70, 74, 84)   # desaturated chrome — drops out of the hue mask
DARK_WARM = (58, 44, 36)   # deep warm ground (hue bin 1 family)


def _glow(img, cx, cy, r, color=RUST, alpha=52):
    """Warm rust glow — adds bin-1-2 mass for continuity."""
    g = Image.new("RGB", img.size, (0, 0, 0))
    d = ImageDraw.Draw(g, "RGBA")
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (alpha,))
    g = g.filter(ImageFilter.GaussianBlur(r * 0.45))
    img.paste(g, (0, 0))
    return img


def _hair(d, y, x0=60, x1=None, width=26, alpha=235):
    """One hair shaft: slightly waving tapered band."""
    x1 = x1 or W - 60
    pts_top, pts_bot = [], []
    for k in range(40):
        t = k / 39
        x = x0 + t * (x1 - x0)
        yy = y + 34 * math.sin(t * 5.2 + 0.7)
        w2 = width * (0.35 + 0.65 * math.sin(t * math.pi) ** 0.5)
        pts_top.append((x, yy - w2))
        pts_bot.append((x, yy + w2))
    d.polygon(pts_top + pts_bot[::-1], fill=NAVY + (alpha,),
              outline=NAVY_D + (255,))
    return [((pts_top[k][0] + pts_bot[k][0]) / 2,
             (pts_top[k][1] + pts_bot[k][1]) / 2) for k in range(0, 40, 8)]


def _mito(d, cx, cy, rw, rh, fill_alpha=140, cristae=True):
    pts = []
    for i in range(80):
        a = 2 * math.pi * i / 80
        r = 1 + 0.06 * math.cos(3 * a)
        pts.append((cx + rw * r * math.cos(a), cy + rh * r * math.sin(a)))
    d.polygon(pts, fill=RUST + (fill_alpha,), outline=NAVY + (255,), width=5)
    if cristae:
        for k in range(6):
            t = 0.18 + 0.11 * k
            fx = cx - rw * 0.7 + t * 2 * rw * 0.72
            top = cy - rh * 0.55 * (1 - abs(t - 0.5) * 0.7)
            bot = cy + rh * 0.55 * (1 - abs(t - 0.5) * 0.7)
            mid = (top + bot) / 2
            if k % 2 == 0:
                d.line((fx, top, fx - 22, mid, fx, bot), fill=NAVY + (200,), width=5)
            else:
                d.line((fx, bot, fx + 22, mid, fx, top), fill=NAVY + (170,), width=5)


def _helix(d, x0, y0, x1, y1, amp=40, turns=4, width=7, alpha=225):
    """Small double helix between two points."""
    for phase in (0.0, math.pi):
        pts = []
        for k in range(60):
            t = k / 59
            x = x0 + t * (x1 - x0)
            y = y0 + t * (y1 - y0) + amp * math.sin(t * turns * 2 * math.pi + phase)
            pts.append((x, y))
        col = RUST if phase == 0.0 else NAVY
        d.line(pts, fill=col + (alpha,), width=width)


def b1_hair_hook():
    img = mottle(Image.new("RGB", (W, H), PARCH), 301)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((110, 240, W - 110, 470), fill=RUST + (26,))
    d.rectangle((110, 780, W - 110, 880), fill=GREY_NAVY + (34,))
    _glow(img, W // 2, 800, 260)
    d = ImageDraw.Draw(img, "RGBA")
    spine = _hair(d, 340, 60, W - 60, 30)
    # faint hinted organelles under the strand (the hidden world)
    for cx, cy, rw, rh in ((620, 800, 170, 92), (1000, 870, 150, 82),
                           (340, 905, 120, 68)):
        _mito(d, cx, cy, rw, rh, fill_alpha=60)
    label(d, "HAIR SHAFT: 80 MICROMETERS", (900, 430), (600, 520), col=INK)
    label(d, "THE UNSEEN WORLD BELOW", (920, 830), (150, 700), col=INK)
    img = grain(img, 302)
    return vignette(img, 0.28)


def b2_eye_limit():
    img = mottle(Image.new("RGB", (W, H), PARCH), 311)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((90, 260, W - 90, 700), fill=GREY_NAVY + (30,))
    _glow(img, W - 320, 480, 240)
    d = ImageDraw.Draw(img, "RGBA")
    spine = _hair(d, 460, 80, W - 80, 34)
    # resolution ticks dissolve to the right: sharp -> blank
    for k in range(9):
        x = 200 + k * 110
        a = 235 - k * 26
        d.line((x, 640, x, 640 + 70), fill=NAVY + (max(a, 0),), width=6)
        d.line((x, 640 + 90 + 8, x, 640 + 90 + 78), fill=NAVY + (max(a - 60, 0),), width=4)
    d.ellipse((W - 430, 300, W - 60, 670), outline=RUST + (200,), width=8)
    label(d, "EYE LIMIT: 0.1 MM", (W - 300, 390), (740, 330), col=INK)
    label(d, "DETAIL DISSOLVES", (560, 700), (140, 900), col=INK)
    img = grain(img, 312)
    return vignette(img, 0.3)


def b3_dive_rings():
    img = parchment(321)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "THE DIVE", sub="HAIR - CELL - MITOCHONDRION - DNA")
    _glow(img, W // 2, 560, 300)
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = W // 2, 560
    rings = ((430, NAVY + (120,), GREY_NAVY + (40,)),
             (300, NAVY + (160,), GREY_NAVY + (52,)),
             (185, RUST + (200,), None),
             (78, NAVY + (235,), None))
    for r, edge, fill in rings:
        if fill:
            d.ellipse((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8),
                      fill=fill, outline=edge, width=7)
        else:
            d.ellipse((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8),
                      outline=edge, width=7)
    _helix(d, cx - 58, cy, cx + 58, cy, amp=24, turns=2, width=6)
    label(d, "HAIR WIDTH", (cx - 400, cy - 300), (150, 300), col=INK)
    label(d, "CELL 30 UM", (cx - 270, cy - 190), (150, 470), col=INK)
    label(d, "MITOCHONDRION", (cx - 160, cy - 100), (1080, 470), col=INK)
    label(d, "DNA 2 NM", (cx + 55, cy + 35), (1080, 760), col=INK)
    big_number(d, "2 NM", (W - 300, 280), 110)
    return finish_plate(img, 322, 0.18)


def b4_mito_macro():
    img = Image.new("RGB", (W, H), DARK_WARM)
    d = ImageDraw.Draw(img, "RGBA")
    for k in range(6):
        d.ellipse((200 - k * 55, 260 - k * 40, W + k * 40, H + k * 30),
                  outline=CREAM + (12,), width=2)
    _glow(img, W // 2, H // 2, 380)
    d = ImageDraw.Draw(img, "RGBA")
    _mito(d, W // 2, H // 2 - 60, 560, 320, fill_alpha=170)
    d.ellipse((W // 2 - 610, H // 2 - 400, W // 2 + 610, H // 2 + 290),
              outline=CREAM + (150,), width=5)
    label(d, "CRISTAE FOLDS", (W // 2 - 160, H // 2 - 220), (150, 330), col=INK)
    label(d, "ATP OUT", (W // 2 + 240, H // 2 + 140), (1080, 760), col=INK)
    img = finish_plate(img, 332, 0.34)
    return img


def b5_dna_thread():
    img = parchment(341)
    d = ImageDraw.Draw(img, "RGBA")
    title_bar(d, "ONE NUCLEUS, TWO METERS", sub="COILED - AND 2 NM THIN")
    d.rectangle((110, 260, W - 110, 380), fill=GREY_NAVY + (30,))
    # small cell outline spilling a long coiled thread
    d.ellipse((140, 470, 520, 850), fill=GREY_NAVY + (46,), outline=NAVY + (255,), width=7)
    pts = []
    x, y = 430, 660
    rng = random.Random(45)
    for k in range(260):
        x += 4.2
        y += rng.uniform(-16, 16)
        y = max(420, min(980, y))
        pts.append((x, y))
    d.line(pts, fill=NAVY + (200,), width=6)
    # magnified helix at the thread's end
    _glow(img, 1120, 840, 210)
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse((900, 660, 1340, 1010), outline=RUST + (220,), width=8)
    _helix(d, 950, 835, 1290, 835, amp=48, turns=3, width=8)
    label(d, "COILED: 2 METERS", (560, 560), (600, 420), col=INK)
    label(d, "STRAND: 2 NM WIDE", (1120, 730), (980, 330), col=INK)
    big_number(d, "40,000X THINNER", (W // 2, 950), 88)
    return finish_plate(img, 342, 0.18)


def b6_hair_universe():
    img = Image.new("RGB", (W, H), DARK_WARM)
    d = ImageDraw.Draw(img, "RGBA")
    _glow(img, W // 2, 420, 330)
    _glow(img, W // 2, 820, 240, alpha=38)
    d = ImageDraw.Draw(img, "RGBA")
    spine = _hair(d, 400, 80, W - 80, 26, alpha=210)
    rng = random.Random(57)
    for k in range(34):
        x, y = rng.randint(140, W - 140), rng.randint(680, H - 120)
        r = rng.randint(8, 20)
        d.ellipse((x - r, y - r, x + r, y + r),
                  outline=CREAM + (rng.randint(60, 150),), width=3)
    label(d, "30 TRILLION WORLDS", (900, 470), (600, 560), col=INK)
    img = finish_plate(img, 352, 0.36)
    return img


def main():
    plates = {
        "SD_B1_hair_hook": b1_hair_hook(),
        "SD_B2_eye_limit": b2_eye_limit(),
        "SD_B3_dive_rings": b3_dive_rings(),
        "SD_B4_mito_macro": b4_mito_macro(),
        "SD_B5_dna_thread": b5_dna_thread(),
        "SD_B6_hair_universe": b6_hair_universe(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("SD_B3_dive_rings", "SD_B5_dna_thread"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest(list(plates.keys()))
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=51, base_hz=98.0, dur=75.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=61, kind="swell", dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    if d_scores and min(d_scores) < 75:
        print("LOW DENSITY")
        raise SystemExit(1)
    print("cell_scale_dive cards OK")


if __name__ == "__main__":
    main()
