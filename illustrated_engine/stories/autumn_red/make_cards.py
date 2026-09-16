"""autumn_red — deterministic plates + diagram cards + bed/SFX.

Botany-of-autumn story: green shutdown, hidden yellows, brewed reds, the
sunscreen idea, the open debate, the farewell. All art Pillow-drawn via
_v6_cardlib (no image-model calls, no network), botanical-atlas family per
the shared visual bible. V7 chrome policy: NO baked title bars; cards carry
only subtle footer section markers.

V10 edge-label discipline (documented V10 gap: landscape plates are
cover-cropped into the portrait card, so the visible horizontal band is the
central 62.5% => x 288..1248 at scale 1.0). Every label/bar/anchor here is
kept inside x 350..1190, and footer text is drawn CENTERED.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, CREAM, INK, W, arrow, bgrid, finish_plate,
                         label, parchment, register_diagram, save_plate,
                         synth_bed, synth_sfx, write_manifest)
from PIL import Image, ImageDraw

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

OLIVE = (74, 82, 40)
OLIVE_D = (44, 48, 30)
AMBER = (196, 150, 70)
YELLOW = (214, 158, 64)
CRIM = (170, 52, 40)
CRIM_D = (150, 44, 36)
RUSSET = (138, 106, 60)


# ------------------------------------------------------------ helpers ---

def footer_centered(d, text, y=920):
    """Solid olive footer strip; text CENTERED in the V10-visible band."""
    d.rectangle((40, y, W - 40, y + 66), fill=OLIVE_D + (255,))
    f = _inter(30)
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y + 10), text, font=f, fill=CREAM + (245,))


def _inter(sz):
    from engine.diagrams import FONT_DIR
    from PIL import ImageFont
    return ImageFont.truetype(str(Path(FONT_DIR) / "Inter-Variable.ttf"), sz)


def leaf_pts(cx, cy, R, tilt=0.0, lobes=5):
    """Stylized 5-lobed maple outline: polar rose with deep sinuses."""
    pts = []
    for k in range(0, 360, 3):
        th = math.radians(k)
        r = R * (0.62 + 0.38 * math.cos(lobes * th) ** 2
                 + 0.10 * math.cos(2 * lobes * th))
        x = cx + r * math.cos(th + tilt)
        y = cy + r * math.sin(th + tilt) * 0.92
        pts.append((x, y))
    return pts


def leaf(d, cx, cy, R, col, tilt=0.0, outline=True, lobes=5):
    pts = leaf_pts(cx, cy, R, tilt, lobes)
    d.polygon(pts, fill=col + (255,), outline=INK + (255,) if outline else None,
              width=5)
    # stem toward lower-left of the tilt frame
    sx = cx + R * 0.95 * math.sin(tilt)
    sy = cy + R * 0.95 * math.cos(tilt)
    d.line(((cx, cy), (sx, sy + R * 0.55)), fill=INK + (255,), width=7)
    # primary veins from centre to lobe tips
    for k in range(lobes):
        th = math.radians(k * 360 / lobes + 90) + tilt
        d.line(((cx, cy), (cx + R * 0.72 * math.cos(th),
                           cy + R * 0.72 * math.sin(th))),
               fill=col[0] and INK + (120,) or INK + (120,), width=3)
    return pts


def lab(d, text, anchor, bar_xy):
    """Story-local label: olive-dark ink instead of cardlib navy."""
    label(d, text, anchor, bar_xy, col=OLIVE_D)


def leaf_mask(cx, cy, R, tilt=0.0, lobes=5):
    m = Image.new("L", (1536, 1024), 0)
    dm = ImageDraw.Draw(m)
    dm.polygon(leaf_pts(cx, cy, R, tilt, lobes), fill=255)
    return m


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def dot(d, x, y, r, col):
    d.ellipse((x - r, y - r, x + r, y + r), fill=col + (235,),
              outline=INK + (150,), width=2)


def rays(d, cx, y0, y1, n=3, col=AMBER):
    for k in range(n):
        x = cx - 160 + k * 160
        d.line(((x, y0), (x, y1)), fill=col + (220,), width=6)


def panel(d, x0, x1, y0=300, y1=760):
    d.rectangle((x0, y0, x1, y1), fill=CREAM + (200,), outline=INK + (255,),
                width=4)


def atlas_tint(img, col, a=70):
    """Full-card botanical-atlas wash: lifts mean saturation toward the
    bible's olive family across the whole frame (parchment alone is too
    desaturated to carry the palette match)."""
    tint = Image.new("RGBA", img.size, col + (a,))
    return Image.alpha_composite(img.convert("RGBA"), tint)


# ---------------------------------------------------------------- plates ---

def b1_autumn_hero():
    img = parchment(901)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 520, 240, CRIM)   # warm wash behind the whole subject
    # turning leaf: olive -> amber -> crimson through the leaf mask
    m = leaf_mask(768, 470, 260, tilt=0.12)
    grad = Image.new("RGBA", (1536, 1024), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    gd.rectangle((508, 210, 700, 730), fill=OLIVE + (255,))
    gd.rectangle((700, 210, 810, 730), fill=AMBER + (255,))
    gd.rectangle((810, 210, 1030, 730), fill=CRIM + (255,))
    img.paste(grad, (0, 0), m)
    d = ImageDraw.Draw(img, "RGBA")
    d.polygon(leaf_pts(768, 470, 260, 0.12), outline=INK + (255,), width=5)
    # amber ground wash keeps the tan family in frame
    d.ellipse((420, 760, 1120, 900), fill=AMBER + (120,))
    label(d, "MAPLE LEAF", (700, 480), (400, 260), col=OLIVE_D)
    label(d, "AUTUMN", (980, 620), (900, 700), col=OLIVE_D)
    footer_centered(d, "WHY THE RED?")
    return finish_plate(img, 902, 0.22)


def b2_green_fade():
    img = parchment(911)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 470, 250, AMBER)
    # leaf with a left-to-right green->amber->yellow gradient via mask
    m = leaf_mask(768, 470, 295, tilt=0.06)
    grad = Image.new("RGBA", (1536, 1024), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    gd.rectangle((470, 175, 690, 765), fill=OLIVE + (255,))
    gd.rectangle((690, 175, 890, 765), fill=AMBER + (255,))
    gd.rectangle((890, 175, 1066, 765), fill=YELLOW + (255,))
    gd.rectangle((950, 175, 1066, 765), fill=CRIM + (255,))  # first red blush
    img.paste(grad, (0, 0), m)
    d = ImageDraw.Draw(img, "RGBA")
    d.polygon(leaf_pts(768, 470, 295, 0.06), outline=INK + (255,), width=5)
    # the draining green band + revealed yellow dots
    d.rectangle((560, 800, 980, 848), fill=OLIVE + (255,), outline=INK + (255,),
                width=4)
    for k in range(5):
        dot(d, 700 + k * 60, 880, 9, YELLOW)
    arrow(d, (620, 880), (900, 880), col=CRIM, w=6, head=20)
    glow(d, 990, 470, 190, CRIM)
    label(d, "GREEN FADES", (620, 470), (390, 300), col=OLIVE_D)
    label(d, "HIDDEN YELLOW", (950, 560), (880, 640), col=OLIVE_D)
    label(d, "CAROTENOIDS", (770, 884), (400, 700), col=OLIVE_D)
    footer_centered(d, "THE GREEN SHUTS DOWN")
    return finish_plate(img, 912, 0.18)


def b3_new_red():
    img = parchment(921)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 1090, 470, 220, CRIM)   # warm wash under the fresh red
    d.line(((768, 180), (768, 850)), fill=INK + (160,), width=4)
    # left: yellow leaf under a translucent green veil (hidden all along)
    leaf(d, 540, 500, 190, YELLOW, tilt=-0.08)
    d.ellipse((380, 700, 700, 800), fill=AMBER + (160,))
    d.polygon(leaf_pts(540, 500, 205, -0.08), fill=OLIVE + (150,))
    label(d, "HIDDEN YELLOW", (540, 500), (380, 720), col=OLIVE_D)
    # right: fresh crimson leaf, brewed this fall
    leaf(d, 1030, 480, 210, CRIM, tilt=0.10)
    d.ellipse((900, 690, 1180, 790), fill=AMBER + (120,))
    label(d, "MADE THIS FALL", (1030, 480), (900, 250), col=OLIVE_D)
    footer_centered(d, "NOT REVEALED \u2014 BREWED")
    return finish_plate(img, 922, 0.18)


def b4_sugar_brew():
    img = parchment(931)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 950, 300, 200, CRIM)   # warm wash on the light entering
    # plant cell: outline + inner vacuole filling with crimson dots
    # olive cell-wall band, then ink outline
    d.rounded_rectangle((470, 330, 1066, 780), radius=140, width=26,
                        outline=OLIVE + (180,))
    d.rounded_rectangle((470, 330, 1066, 780), radius=140, fill=CREAM + (235,),
                        outline=INK + (255,), width=6)
    d.ellipse((560, 420, 980, 700), fill=(210, 108, 96, 255),
              outline=INK + (170,), width=4)
    for k in range(9):
        dot(d, 600 + k * 45, 470 + (k % 3) * 80, 12, CRIM)
    for k in range(4):
        dot(d, 620 + k * 70, 640, 9, AMBER)
    d.ellipse((330, 780, 1210, 890), fill=AMBER + (160,))
    # sun arrow entering top-right
    arrow(d, (1180, 220), (1000, 360), col=CRIM, w=12, head=30)
    label(d, "BRIGHT LIGHT", (1120, 250), (880, 180), col=OLIVE_D)
    label(d, "SUGARS", (660, 640), (420, 700), col=OLIVE_D)
    label(d, "NEW PIGMENT", (830, 500), (900, 730), col=OLIVE_D)
    footer_centered(d, "THE AUTUMN RECIPE")
    return finish_plate(img, 932, 0.18)


def b5_sun_shield():
    img = parchment(941)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 260, 180, AMBER)
    rays(d, 768, 200, 330)
    label(d, "AUTUMN LIGHT", (600, 240), (380, 180), col=OLIVE_D)
    # the red shield band
    d.rectangle((430, 350, 1110, 415), fill=CRIM + (255,),
                outline=INK + (255,), width=5)
    for hx in range(450, 1100, 40):
        d.line(((hx, 355), (hx + 18, 410)), fill=CRIM_D + (200,), width=3)
    label(d, "RED SHIELD", (768, 382), (880, 420), col=OLIVE_D)
    # leaf below, nutrients flowing down the stem
    leaf(d, 768, 600, 150, CRIM, tilt=0.0)
    arrow(d, (768, 740), (768, 850), col=OLIVE, w=9, head=26)
    label(d, "NITROGEN OUT", (768, 800), (900, 760), col=OLIVE_D)
    footer_centered(d, "THE SUNSCREEN IDEA")
    return finish_plate(img, 942, 0.18)


def b6_hypotheses():
    img = parchment(951)
    d = ImageDraw.Draw(img, "RGBA")
    xs = [(360, 660), (620, 920), (880, 1180)]
    tags = ["SUNSCREEN", "ANTIOXIDANT", "PEST SIGNAL"]
    for k, (x0, x1) in enumerate(xs):
        panel(d, x0, x1)
        cx = (x0 + x1) // 2
        if k == 0:
            rays(d, cx, 360, 430)
            leaf(d, cx, 540, 110, CRIM)
            d.rectangle((cx - 120, 440, cx + 120, 470), fill=CRIM_D + (255,),
                        outline=INK + (255,), width=3)
        elif k == 1:
            leaf(d, cx, 540, 110, CRIM)
            d.arc((cx - 60, 480, cx + 60, 600), 20, 320, fill=AMBER + (235,),
                  width=7)
        else:
            leaf(d, cx, 540, 110, CRIM)
            for j in range(3):
                d.line(((cx - 60 + j * 60, 420), (cx - 40 + j * 60, 450)),
                       fill=CRIM_D + (235,), width=6)
        f = _inter(26)
        tw = d.textlength(tags[k], font=f)
        d.text((cx - tw / 2, 700), tags[k], font=f, fill=INK + (245,))
    # the open question mark
    f = _inter(120)
    d.text((740, 170), "?", font=f, fill=CRIM + (235,))
    footer_centered(d, "STILL DEBATED")
    return finish_plate(img, 952, 0.18)


def b7_farewell():
    img = parchment(961)
    tint = Image.new("RGBA", (1536, 1024), (196, 128, 74, 34))  # dusk warmth
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 780, 400, CRIM)   # ONE moderate dusk glow, low in frame
    leaf(d, 768, 460, 240, CRIM, tilt=0.55)
    # clean scar where the leaf let go
    d.ellipse((742, 668, 794, 716), outline=INK + (255,), width=5,
              fill=(216, 208, 190, 255))
    label(d, "BUILT AT THE END", (768, 470), (880, 280), col=OLIVE_D)
    footer_centered(d, "A FAREWELL BROADCAST")
    return finish_plate(img, 962, 0.24)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_autumn_hero": b1_autumn_hero(),
        "B2_green_fade": b2_green_fade(),
        "B3_new_red": b3_new_red(),
        "B4_sugar_brew": b4_sugar_brew(),
        "B5_sun_shield": b5_sun_shield(),
        "B6_hypotheses": b6_hypotheses(),
        "B7_farewell": b7_farewell(),
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
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=91, base_hz=82.0,
              dur=75.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=93, kind="swell",
              dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
