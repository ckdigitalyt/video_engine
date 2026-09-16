"""baikal_deep — deterministic plates + diagram cards + bed/SFX.

Geography-of-water story: the wrong first answer, the sounding line, the
volume ledger, the rift engine, the ancient ark, the freshwater seal, the
living archive. All art Pillow-drawn via _v6_cardlib (no image-model calls,
no network), bathymetric-chart family per the shared visual bible.

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

TEAL = (31, 78, 82)
TEAL_D = (20, 48, 52)
TEAL_DD = (12, 32, 36)
GLAC = (127, 163, 168)
CYAN = (46, 126, 140)
TAN = (122, 106, 80)

img_holder = [None]


# ------------------------------------------------------------ helpers ---

def _inter(sz):
    from engine.diagrams import FONT_DIR
    from PIL import ImageFont
    return ImageFont.truetype(str(Path(FONT_DIR) / "Inter-Variable.ttf"), sz)


def lab(d, text, anchor, bar_xy):
    label(d, text, anchor, bar_xy, col=TEAL_D)


def footer_centered(d, text, y=920):
    d.rectangle((40, y, W - 40, y + 66), fill=TEAL_D + (255,))
    f = _inter(30)
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y + 10), text, font=f, fill=CREAM + (245,))


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def water_bands(d, x0, y0, x1, y1, n=5):
    """Depth-banded water: teal bands darken with depth + sound ticks."""
    bh = (y1 - y0) // n
    for k in range(n):
        col = (TEAL[0] - k * 8, TEAL[1] - k * 9, TEAL[2] - k * 9)
        d.rectangle((x0, y0 + k * bh, x1, y0 + (k + 1) * bh),
                    fill=col + (255,))
    for gy in range(y0 + 30, y1 - 10, 52):
        d.line(((x0 + 30, gy), (x0 + 70, gy)), fill=CREAM + (150,), width=3)


def hills(d, base_y, col=TEAL_D):
    d.polygon([(140, base_y), (330, base_y - 170), (520, base_y),
               (1396, base_y), (1396, base_y - 120), (1120, base_y - 210),
               (900, base_y)], fill=col + (255,))
    d.polygon([(700, base_y), (980, base_y - 150), (1396, base_y)],
              fill=(TEAL_DD[0], TEAL_DD[1], TEAL_DD[2]) + (255,))


def dashed(d, p0, p1, col, w=5, dash=22, gap=14):
    x0, y0 = p0
    x1, y1 = p1
    L = math.hypot(x1 - x0, y1 - y0)
    n = int(L // (dash + gap)) + 1
    for k in range(n):
        t0 = k * (dash + gap) / L
        t1 = min(t0 + dash / L, 1.0)
        d.line(((x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)),
               fill=col, width=w)


def seal(d, cx, cy, s=1.0):
    """Nerpa silhouette: curved body, head, tail."""
    d.ellipse((cx - 90 * s, cy - 34 * s, cx + 90 * s, cy + 34 * s),
              fill=TEAL_DD + (255,), outline=INK + (255,), width=4)
    d.ellipse((cx + 66 * s, cy - 52 * s, cx + 116 * s, cy - 4 * s),
              fill=TEAL_DD + (255,), outline=INK + (255,), width=4)
    d.polygon([(cx - 86 * s, cy), (cx - 130 * s, cy - 26 * s),
               (cx - 130 * s, cy + 26 * s)], fill=TEAL_DD + (255,),
              outline=INK + (255,))


# ---------------------------------------------------------------- plates ---

def b1_lake_tease():
    img = parchment(1041)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 560, 300, CYAN)
    # cold sky
    for k in range(5):
        d.line(((140, 160 + k * 60), (1396, 200 + k * 60)),
               fill=GLAC + (90 + k * 12,), width=22)
    hills(d, 620)
    # the long lake band
    d.rectangle((140, 620, 1396, 800), fill=TEAL + (255,),
                outline=INK + (255,), width=6)
    d.line(((200, 664), (1340, 664)), fill=CREAM + (200,), width=5)
    d.rectangle((140, 800, 1396, 880), fill=TEAL_D + (255,),
                outline=INK + (255,), width=5)
    label(d, "LAKE BAIKAL", (700, 710), (420, 660), col=TEAL_D)
    label(d, "SIBERIA", (1000, 300), (880, 240), col=TEAL_D)
    footer_centered(d, "WHERE'S THE WATER?")
    return finish_plate(img, 1042, 0.22)


def b2_depth_line():
    img = parchment(1051)
    img_holder[0] = img
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 480, 260, CYAN)
    water_bands(d, 420, 300, 1120, 830, n=5)
    d.line(((140, 830), (1396, 830)), fill=INK + (255,), width=8)
    hatch_polygon(img_holder[0], [(140, 830), (1396, 830), (1396, 900),
                                  (140, 900)], TAN, 110, 16, 11)
    # plumb line + weight
    d.line(((770, 260), (770, 790)), fill=CREAM + (240,), width=5)
    d.polygon([(744, 790), (796, 790), (770, 830)], fill=TEAL_D + (255,),
              outline=INK + (255,), width=4)
    for gy in range(340, 830, 120):
        d.ellipse((762, gy - 5, 778, gy + 5), fill=CYAN + (235,),
                  outline=INK + (120,), width=2)
    label(d, "DEEPEST LAKE", (620, 380), (390, 320), col=TEAL_D)
    label(d, "1,642 M", (920, 700), (900, 640), col=TEAL_D)
    footer_centered(d, "THE SOUNDING LINE")
    return finish_plate(img, 1052, 0.18)


def b3_volume_bars():
    img = parchment(1061)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 540, 460, 220, CYAN)
    d.line(((768, 200), (768, 850)), fill=INK + (160,), width=4)
    # Baikal vessel: tall, full
    d.rectangle((440, 240, 660, 800), fill=TEAL + (255,),
                outline=INK + (255,), width=6)
    d.line(((440, 262), (660, 262)), fill=CREAM + (230,), width=5)
    # Great Lakes vessel: shorter
    d.rectangle((860, 520, 1080, 800), fill=CYAN + (230,),
                outline=INK + (255,), width=6)
    d.line(((860, 542), (1080, 542)), fill=CREAM + (230,), width=5)
    label(d, "BAIKAL", (550, 420), (400, 380), col=TEAL_D)
    label(d, "GREAT LAKES COMBINED", (970, 660), (820, 720), col=TEAL_D)
    footer_centered(d, "ONE FIFTH OF EARTH")
    return finish_plate(img, 1062, 0.18)


def b4_rift_tear():
    img = parchment(1071)
    img_holder[0] = img
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 620, 220, CYAN)
    # crust blocks with a sinking graben between (teal-grey rock family)
    d.polygon([(140, 420), (560, 420), (620, 560), (620, 860), (140, 860)],
              fill=(52, 82, 86, 255), outline=INK + (255,), width=6)
    d.polygon([(1396, 420), (976, 420), (916, 560), (916, 860), (1396, 860)],
              fill=(52, 82, 86, 255), outline=INK + (255,), width=6)
    hatch_polygon(img, [(150, 560), (614, 560), (614, 854), (150, 854)],
                  GLAC, 110, 16, 13)
    hatch_polygon(img, [(922, 560), (1390, 560), (1390, 854), (922, 854)],
                  GLAC, 110, 16, 17)
    # the basin: water filling the tear
    d.polygon([(620, 540), (916, 540), (916, 860), (620, 860)],
              fill=TEAL + (255,), outline=INK + (255,), width=5)
    # outward pull arrows
    arrow(d, (600, 350), (420, 350), col=CYAN, w=10, head=26)
    arrow(d, (936, 350), (1116, 350), col=CYAN, w=10, head=26)
    label(d, "CRUST PULLED APART", (768, 300), (420, 240), col=TEAL_D)
    label(d, "BASIN SINKS", (768, 700), (880, 740), col=TEAL_D)
    footer_centered(d, "THE TEAR BENEATH")
    return finish_plate(img, 1072, 0.18)


def b5_endemics():
    img = parchment(1081)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 520, 240, CYAN)
    d.rectangle((420, 300, 1120, 800), fill=CREAM + (220,),
                outline=INK + (255,), width=5)
    # transparent fish: outline + spine, organs faint
    d.ellipse((490, 420, 850, 560), outline=CYAN + (255,), width=6)
    d.line(((510, 490), (830, 490)), fill=CYAN + (170,), width=4)
    d.polygon([(830, 440), (920, 470), (830, 540)], outline=CYAN + (255,),
              width=5)
    d.ellipse((560, 470, 600, 510), outline=INK + (180,), width=3)
    # branching sponges on the floor
    for bx in (980, 1050):
        d.line(((bx, 760), (bx, 620)), fill=CYAN + (235,), width=8)
        d.line(((bx, 680), (bx - 40, 600)), fill=CYAN + (235,), width=6)
        d.line(((bx, 700), (bx + 44, 616)), fill=CYAN + (235,), width=6)
    for gy in range(700, 790, 26):
        d.line(((440, gy), (1100, gy)), fill=TEAL + (90,), width=3)
    label(d, "ENDEMICS", (560, 470), (390, 380), col=TEAL_D)
    label(d, "25 MILLION YEARS", (770, 840), (520, 790), col=TEAL_D)
    footer_centered(d, "THE ANCIENT ARK")
    return finish_plate(img, 1082, 0.18)


def b6_nerpa_ice():
    img = parchment(1091)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 620, 560, 220, CYAN)
    # ice floe + seal
    d.rectangle((380, 640, 900, 700), fill=CREAM + (255,),
                outline=INK + (255,), width=5)
    seal(d, 620, 590)
    # dashed route arc receding to a distant ocean edge
    dashed(d, (700, 560), (1020, 380), TEAL + (235,), 5)
    dashed(d, (1020, 380), (1180, 330), TEAL + (235,), 5)
    d.rectangle((1120, 320, 1360, 372), fill=TEAL + (200,),
                outline=INK + (200,), width=4)
    label(d, "THE NERPA", (620, 590), (400, 480), col=TEAL_D)
    label(d, "NO OCEAN IN SIGHT", (1140, 300), (820, 260), col=TEAL_D)
    footer_centered(d, "THE IMPOSSIBILITY")
    return finish_plate(img, 1092, 0.18)


def b7_living_archive():
    img = parchment(1101)
    tint = Image.new("RGBA", (1536, 1024), (168, 118, 84, 30))  # dusk warmth
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 800, 400, CYAN)
    # valley walls + deep banded water, calm, no arrows
    d.polygon([(140, 320), (420, 320), (560, 860), (140, 860)],
              fill=(52, 82, 86, 255), outline=INK + (255,), width=5)
    d.polygon([(1396, 320), (1116, 320), (976, 860), (1396, 860)],
              fill=(52, 82, 86, 255), outline=INK + (255,), width=5)
    water_bands(d, 560, 380, 976, 830, n=5)
    d.line(((140, 830), (1396, 830)), fill=INK + (255,), width=7)
    label(d, "A LIVING ARCHIVE", (768, 500), (600, 280), col=TEAL_D)
    footer_centered(d, "STILL OPENING")
    return finish_plate(img, 1102, 0.24)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_lake_tease": b1_lake_tease(),
        "B2_depth_line": b2_depth_line(),
        "B3_volume_bars": b3_volume_bars(),
        "B4_rift_tear": b4_rift_tear(),
        "B5_endemics": b5_endemics(),
        "B6_nerpa_ice": b6_nerpa_ice(),
        "B7_living_archive": b7_living_archive(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in plates:
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([(n_, "diagram") for n_ in plates])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=83, base_hz=68.0,
              dur=75.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=81, kind="swell",
              dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
