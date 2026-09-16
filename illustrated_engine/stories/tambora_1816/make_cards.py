"""tambora_1816 — deterministic plates + diagram cards + bed/SFX.

History-of-climate story: June snow, the 1815 eruption, the stratospheric
veil, the half-degree, the failed summer, the famine ledger, the delayed
attribution. All art Pillow-drawn via _v6_cardlib (no image-model calls, no
network), copperplate-engraving family per the shared visual bible.

V10 edge-label discipline: labels kept inside x 350..1190; footer text
CENTERED in the V10-visible band.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, CREAM, INK, W, arrow, bgrid, finish_plate,
                         hatch_polygon, label, parchment, register_diagram,
                         save_plate, synth_bed, synth_sfx, write_manifest)
from PIL import Image, ImageDraw

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

SLATE = (63, 72, 100)
SLATE_D = (38, 44, 62)
TAN = (122, 106, 80)
EMBER = (192, 90, 46)
EMBER_D = (150, 66, 34)


# ------------------------------------------------------------ helpers ---

def _inter(sz):
    from engine.diagrams import FONT_DIR
    from PIL import ImageFont
    return ImageFont.truetype(str(Path(FONT_DIR) / "Inter-Variable.ttf"), sz)


def lab(d, text, anchor, bar_xy):
    label(d, text, anchor, bar_xy, col=SLATE_D)


def footer_centered(d, text, y=920):
    d.rectangle((40, y, W - 40, y + 66), fill=SLATE_D + (255,))
    f = _inter(30)
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y + 10), text, font=f, fill=CREAM + (245,))


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def sky_wash(d, y0=140, y1=560, col=SLATE, a=90):
    for k in range(6):
        yy = y0 + k * (y1 - y0) // 6
        d.line(((140, yy), (1396, yy)), fill=col + (a + k * 4,), width=42)


def hcloud(d, cx, cy, rx, ry, col=SLATE, a=120):
    for k in range(3):
        d.ellipse((cx - rx + k * 40, cy - ry + k * 8,
                   cx + rx - k * 40, cy + ry), fill=col + (a + k * 20,))


def plume(d, cx, y0, w0, n=6, col=EMBER, a=200):
    """Eruption column: stacked widening puffs with ember rim."""
    for k in range(n):
        rr = w0 + k * 34
        yy = y0 - k * 92
        d.ellipse((cx - rr, yy - 60, cx + rr, yy + 60),
                  fill=SLATE + (215,), outline=INK + (255,), width=4)
        d.ellipse((cx - rr + 14, yy - 48, cx + rr - 10, yy + 12),
                  fill=col + (a + k * 8,))
    return yy - 60


def cone(d, cx, base_y, half=300, top_y=560):
    pts = [(cx - half, base_y), (cx - 60, top_y), (cx + 60, top_y),
           (cx + half, base_y)]
    d.polygon(pts, fill=SLATE_D + (255,), outline=INK + (255,), width=6)
    hatch_polygon(img_holder[0], pts, SLATE, 60, 18, 7)
    return pts


def frost_lines(d, x0, y0, x1, n=6, col=SLATE):
    for k in range(n):
        fx = x0 + k * (x1 - x0) // max(n - 1, 1)
        d.line(((fx, y0), (fx - 8, y0 + 16)), fill=col + (220,), width=4)


def figure(d, cx, cy, h=54, col=SLATE_D):
    d.ellipse((cx - 8, cy - h, cx + 8, cy - h + 16), fill=col + (235,))
    d.polygon([(cx - 12, cy), (cx + 12, cy), (cx + 8, cy - h + 14),
               (cx - 8, cy - h + 14)], fill=col + (235,))


img_holder = [None]


# ---------------------------------------------------------------- plates ---

def b1_june_snow():
    img = parchment(971)
    img_holder[0] = img
    d = ImageDraw.Draw(img, "RGBA")
    sky_wash(d, 150, 520, SLATE, 130)
    glow(d, 1080, 260, 240, EMBER)
    d.ellipse((1030, 210, 1130, 310), fill=CREAM + (230,),
              outline=INK + (120,), width=3)   # pale overcast sun
    # snow field with furrows
    d.rectangle((140, 640, 1396, 880), fill=CREAM + (255,),
                outline=INK + (255,), width=6)
    for k in range(6):
        d.line(((300 + k * 150, 660), (220 + k * 150, 870)),
               fill=TAN + (200,), width=5)
    # snow drifts
    for k in range(4):
        d.ellipse((340 + k * 250, 600 + (k % 2) * 26, 560 + k * 250, 660),
                  fill=CREAM + (255,), outline=INK + (140,), width=3)
    label(d, "JUNE 1816", (760, 300), (420, 220), col=SLATE_D)
    label(d, "NEW ENGLAND", (620, 700), (420, 760), col=SLATE_D)
    footer_centered(d, "SUMMER, BROKEN")
    return finish_plate(img, 972, 0.22)


def b2_tambora_erupts():
    img = parchment(981)
    img_holder[0] = img
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 560, 300, EMBER)
    top = plume(d, 768, 560, 130, n=6)
    # tan foot-slope apron grounds the cone in the secondary family
    d.polygon([(180, 866), (360, 700), (1176, 700), (1356, 866)],
              fill=(150, 122, 68, 255), outline=INK + (255,), width=4)
    cone(d, 768, 860, half=330, top_y=560)
    # dashed ghost of the lost summit
    for k in range(7):
        t = k / 6.0
        gx = 708 + t * 120
        gy = 560 - t * 240
        d.ellipse((gx - 5, gy - 5, gx + 5, gy + 5), outline=EMBER + (235,),
                  width=3)
    d.text((810, 330), ".", font=_inter(8), fill=(0, 0, 0, 0))
    label(d, "TAMBORA", (700, 700), (420, 640), col=SLATE_D)
    label(d, "APRIL 1815", (900, 480), (880, 420), col=SLATE_D)
    label(d, "SUMMIT LOST", (790, 330), (880, 280), col=SLATE_D)
    footer_centered(d, "THE MOUNTAIN EXPLODES")
    return finish_plate(img, 982, 0.18)


def b3_strato_veil():
    img = parchment(991)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 560, 200, EMBER)
    # globe arc at the bottom
    d.arc((168, 620, 1368, 1620), start=200, end=340, fill=INK + (255,),
          width=8)
    d.chord((168, 620, 1368, 1620), start=200, end=340, fill=TAN + (120,))
    # rain clouds hugging the surface
    for k in range(4):
        hcloud(d, 400 + k * 260, 700, 90, 26, SLATE, 110)
    # the veil: dotted ember band ringing the arc, high above the clouds
    for k in range(16):
        t = k / 15.0
        vx = 240 + t * 1050
        vy = 300 + 60 * math.sin(math.pi * t)
        d.ellipse((vx - 9, vy - 9, vx + 9, vy + 9), fill=EMBER + (225,),
                  outline=INK + (150,), width=2)
    # plume arrow from surface into the veil
    arrow(d, (768, 660), (768, 380), col=EMBER, w=10, head=28)
    label(d, "STRATOSPHERE", (768, 330), (370, 280), col=SLATE_D)
    label(d, "THE VEIL", (1090, 322), (900, 380), col=SLATE_D)
    label(d, "RAIN BELOW", (500, 740), (380, 780), col=SLATE_D)
    footer_centered(d, "ABOVE THE WEATHER")
    return finish_plate(img, 992, 0.18)


def b4_sun_scatter():
    img = parchment(1001)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 480, 300, 190, EMBER)
    d.line(((768, 180), (768, 850)), fill=INK + (160,), width=4)
    # left: sun rays in, scattered back up off a droplet veil
    d.ellipse((400, 200, 560, 360), fill=EMBER + (235,),
              outline=INK + (255,), width=5)
    for k in range(3):
        d.line(((480, 380 + k * 40), (620, 430 + k * 40)),
               fill=EMBER + (220,), width=6)
    for k in range(8):
        vx = 400 + k * 60
        d.ellipse((vx, 560, vx + 22, 582), fill=SLATE + (200,),
                  outline=INK + (140,), width=2)
    for k in range(3):
        arrow(d, (620 + k * 50, 540), (520 + k * 50, 430), col=SLATE, w=6,
              head=18)
    label(d, "SUNLIGHT", (480, 270), (370, 180), col=SLATE_D)
    label(d, "SCATTERED", (600, 470), (500, 620), col=SLATE_D)
    # right: seedling under frost
    d.line(((1050, 840), (1050, 620)), fill=SLATE_D + (255,), width=8)
    d.ellipse((980, 560, 1120, 650), fill=TAN + (220,), outline=INK + (255,),
              width=5)
    frost_lines(d, 900, 640, 1200, 7)
    label(d, "FROST", (1050, 640), (1000, 720), col=SLATE_D)
    footer_centered(d, "HALF A DEGREE")
    return finish_plate(img, 1002, 0.18)


def b5_frost_months():
    img = parchment(1011)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    xs = [(360, 660), (620, 920), (880, 1180)]
    tags = ["JUNE", "JULY", "AUGUST"]
    for k, (x0, x1) in enumerate(xs):
        d.rectangle((x0, 320, x1, 720), fill=CREAM + (210,),
                    outline=INK + (255,), width=4)
        cx = (x0 + x1) // 2
        if k == 0:
            d.rectangle((x0 + 14, 340, x1 - 14, 400), fill=CREAM + (255,),
                        outline=INK + (140,), width=3)
        # crops as short stems, frost ticks on each panel
        for j in range(4):
            sx = x0 + 40 + j * 60
            d.line(((sx, 690), (sx, 590)), fill=TAN + (240,), width=5)
            d.ellipse((sx - 16, 560, sx + 16, 592), fill=TAN + (200,),
                      outline=INK + (140,), width=3)
        frost_lines(d, x0 + 30, 640, x1 - 30, 4)
        f = _inter(26)
        tw = d.textlength(tags[k], font=f)
        d.text((cx - tw / 2, 740), tags[k], font=f, fill=INK + (245,))
    glow(d, 510, 370, 130, EMBER)
    label(d, "KILLING FROST", (768, 850), (520, 800), col=SLATE_D)
    footer_centered(d, "FROST ON REPEAT")
    return finish_plate(img, 1012, 0.18)


def b6_harvest_fails():
    img = parchment(1021)
    img_holder[0] = img
    d = ImageDraw.Draw(img, "RGBA")
    sky_wash(d, 150, 420, SLATE, 120)
    glow(d, 1200, 480, 200, EMBER)
    # overturned empty sack (deep tan, strongly hatched)
    pts = [(430, 700), (520, 560), (700, 520), (760, 640), (700, 760),
           (480, 770)]
    d.polygon(pts, fill=(150, 124, 76, 255), outline=INK + (255,), width=6)
    hatch_polygon(img, pts, TAN, 120, 14, 9)
    d.ellipse((700, 560, 820, 660), outline=INK + (255,), width=6)
    # bread queue receding
    for k in range(6):
        figure(d, 980 - k * 36, 760 - k * 18, h=50 - k * 3)
    d.rectangle((140, 770, 1396, 880), fill=TAN + (220,),
                outline=INK + (255,), width=4)
    label(d, "HARVEST FAILS", (560, 640), (400, 420), col=SLATE_D)
    label(d, "FOOD RIOTS", (900, 700), (880, 780), col=SLATE_D)
    footer_centered(d, "THE LEDGER")
    return finish_plate(img, 1022, 0.18)


def b7_one_atmosphere():
    img = parchment(1031)
    tint = Image.new("RGBA", (1536, 1024), (188, 118, 70, 30))  # dusk warmth
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 800, 400, EMBER)
    # the same field, cleared: furrows in warm light
    d.rectangle((140, 640, 1396, 880), fill=TAN + (235,),
                outline=INK + (255,), width=6)
    for k in range(6):
        d.line(((300 + k * 150, 660), (220 + k * 150, 870)),
               fill=SLATE_D + (170,), width=5)
    # calm sky, a few fading veil dots high up
    sky_wash(d, 150, 520, SLATE, 50)
    for k in range(6):
        vx = 420 + k * 140
        d.ellipse((vx - 6, 260 - 6, vx + 6, 260 + 6), outline=SLATE + (140,),
                  width=2)
    label(d, "ONE ATMOSPHERE", (768, 500), (600, 300), col=SLATE_D)
    footer_centered(d, "WRITTEN IN THE CLIMATE")
    return finish_plate(img, 1032, 0.24)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_june_snow": b1_june_snow(),
        "B2_tambora_erupts": b2_tambora_erupts(),
        "B3_strato_veil": b3_strato_veil(),
        "B4_sun_scatter": b4_sun_scatter(),
        "B5_frost_months": b5_frost_months(),
        "B6_harvest_fails": b6_harvest_fails(),
        "B7_one_atmosphere": b7_one_atmosphere(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in plates:
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([(n, "diagram") for n in plates])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=87, base_hz=76.0,
              dur=75.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=89, kind="swell",
              dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
