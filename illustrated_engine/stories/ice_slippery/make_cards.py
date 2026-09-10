"""ice_slippery — deterministic plates + diagram cards + bed/SFX.

Physics-of-ice story: skate blade on ice, the pressure-melting myth, the
quasi-liquid surface layer, friction feeding, cold-thinning film, wet payoff.
All art Pillow-drawn via _v6_cardlib (no image-model calls, no network),
parchment family per the shared visual bible. V7 chrome policy: NO baked
title bars; cards carry only subtle footer section markers.

V10 edge-label discipline (documented V10 gap: landscape plates are
cover-cropped into the portrait card, so the visible horizontal band is the
central 62.5% => x 288..1248 at scale 1.0). Every label/bar/anchor here is
kept inside x 350..1190, and footer text is drawn CENTERED (cardlib's
footer_band starts text at x=64, which the crop clips).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, CREAM, INK, NAVY, NAVY_D, PARCH, PARCH_D,
                         PARCH_L, RUST, W, inter, arrow, bgrid, finish_plate,
                         label, parchment, register_diagram, save_plate,
                         synth_bed, synth_sfx, write_manifest)
from PIL import Image, ImageDraw

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

from _v6_cardlib import H as H_, W as W_  # canvas size for tint layers

GREY_NAVY = (70, 74, 84)   # desaturated chrome: reads as ink wash, drops out
# of the hue histogram (cardlib convention) so saturated rust/navy accents
# own the palette match.
ICE_TOP = 560              # default ice-surface y


# ------------------------------------------------------------ helpers ---

def footer_centered(d, text, y=920):
    """Solid navy footer strip; text CENTERED in the V10-visible band."""
    d.rectangle((40, y, W - 40, y + 66), fill=NAVY_D + (255,))
    f = inter(30)
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y + 10), text, font=f, fill=CREAM + (245,))


def rounded(d, box, r, **kw):
    d.rounded_rectangle(box, radius=r, **kw)


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def ice_band(d, y0=560, y1=830, x0=140, x1=1396):
    """Ice cross-section: filled band + surface line + lattice hatch."""
    d.rectangle((x0, y0, x1, y1), fill=PARCH_D + (255,),
                outline=INK + (255,), width=6)
    d.line(((x0, y0), (x1, y0)), fill=INK + (255,), width=7)
    step = 56
    for gy in range(y0 + 40, y1 - 20, step):
        for gx in range(x0 + 40, x1 - 20, step):
            d.line(((gx, gy), (gx + 14, gy + 14)), fill=NAVY + (70,), width=3)
            d.ellipse((gx - 3, gy - 3, gx + 3, gy + 3),
                      fill=NAVY + (110,))


def water_sheen(d, cx, cy, rx, ry=14, col=CREAM, a=235):
    d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=col + (a,),
              outline=INK + (90,), width=2)


def skate_blade(d, cx, y_top, half=170, mount=True):
    """Side-view skate blade with mount above. Returns (blade_y, x0, x1)."""
    x0, x1 = cx - half, cx + half
    if mount:
        rounded(d, (cx - 74, y_top, cx + 74, y_top + 44), 10,
                fill=NAVY + (255,), outline=INK + (255,), width=5)
        d.line(((cx - 40, y_top + 44), (cx - 40, y_top + 72)),
               fill=INK + (255,), width=8)
        d.line(((cx + 40, y_top + 44), (cx + 40, y_top + 72)),
               fill=INK + (255,), width=8)
    by = y_top + 72
    rounded(d, (x0, by, x1, by + 12), 6, fill=GREY_NAVY + (255,),
            outline=INK + (255,), width=4)
    # front curl of the runner
    d.arc((x1 - 26, by - 8, x1 + 14, by + 26), start=-90, end=40,
          fill=INK + (255,), width=5)
    return by + 12, x0, x1


def molecule(d, x, y, r=7, col=NAVY):
    d.ellipse((x - r, y - r, x + r, y + r), fill=col + (170,),
              outline=INK + (120,), width=2)


def droplet(d, x, y, r=13):
    d.ellipse((x - r, y - r, x + r, y + r), fill=CREAM + (245,),
              outline=INK + (200,), width=3)


def bite_marks(d, x0, x1, y, n=6):
    """Short rust notches cut into the ice surface (blade grip)."""
    step = (x1 - x0) / max(n - 1, 1)
    for k in range(n):
        bx = x0 + k * step
        d.line(((bx, y), (bx - 10, y + 18)), fill=RUST + (235,), width=6)


# ---------------------------------------------------------------- plates ---

def b1_ice_blade_hero():
    img = parchment(801)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 540, 340, RUST)   # warm wash behind the whole subject
    ice_band(d)
    by, bx0, bx1 = skate_blade(d, 768, 400)
    # faint water sheen at the running edge: the unexplained slipperiness
    water_sheen(d, 768, 498, 210, 16)
    label(d, "SKATE BLADE", (770, 470), (430, 330))
    label(d, "WATER SKIN", (768, 498), (880, 640))
    label(d, "ICE", (1150, 700), (1060, 610))
    footer_centered(d, "WHY SO SLIPPERY?")
    return finish_plate(img, 802, 0.22)


def b2_pressure_idea():
    img = parchment(811)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 520, 260, RUST)
    ice_band(d, y0=640, y1=830)
    skate_blade(d, 768, 420, half=150)
    # the classic claim: one heavy press squeezing out meltwater
    arrow(d, (768, 240), (768, 408), col=RUST, w=13, head=32)
    droplet(d, 700, 624)
    droplet(d, 768, 636)
    droplet(d, 836, 624)
    label(d, "PRESSURE", (768, 320), (410, 250))
    label(d, "ICE", (1120, 730), (1040, 620))
    label(d, "MELTWATER", (768, 632), (400, 700))
    footer_centered(d, "THE CLASSIC ANSWER")
    return finish_plate(img, 812, 0.18)


def b3_pressure_fail():
    img = parchment(821)
    d = ImageDraw.Draw(img, "RGBA")
    # no bgrid here: grid + divider + melt line read as graph axes to the
    # subject-QA judge (evidence 2026-09-10 run 1). Plain parchment keeps
    # the split/comparison clean.
    glow(d, 520, 470, 200, RUST)   # warm wash under the big arrow
    # divider
    d.line(((768, 180), (768, 850)), fill=INK + (160,), width=4)
    # left: a whole skater's weight as one huge arrow. NAVY shaft: a rust
    # arrow inside the rust glow is invisible (run-1 evidence: judge saw
    # only "a large orange circle" where the weight should be).
    arrow(d, (520, 230), (520, 690), col=NAVY, w=20, head=44)
    label(d, "SKATER'S WEIGHT", (520, 460), (360, 180))
    # right: what it buys — a droplet beside the melt line
    d.line(((820, 620), (1380, 620)), fill=NAVY + (200,), width=6)
    droplet(d, 1000, 596, 16)
    label(d, "TOO LITTLE", (1000, 596), (900, 690))
    label(d, "MELT POINT", (1290, 620), (1000, 540))
    footer_centered(d, "PRESSURE FAILS")
    return finish_plate(img, 822, 0.18)


def b4_quasi_liquid():
    img = parchment(831)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 400, 240, RUST)   # warm wash on the loose layer
    # solid lattice below
    ice_band(d, y0=470, y1=830)
    # quasi-liquid band above: loose, disordered molecules
    d.rectangle((140, 360, 1396, 470), fill=PARCH_L + (235,),
                outline=INK + (255,), width=5)
    rng = [(210, 405), (300, 438), (395, 392), (480, 425), (575, 402),
           (665, 440), (760, 395), (855, 428), (950, 400), (1045, 435),
           (1140, 398), (1240, 430), (1330, 405)]
    for mx, my in rng:
        molecule(d, mx, my)
    # dashed boundary between the layers
    for bx in range(160, 1380, 34):
        d.line(((bx, 470), (bx + 16, 470)), fill=RUST + (230,), width=5)
    label(d, "QUASI-LIQUID LAYER", (760, 400), (370, 290))
    label(d, "ICE LATTICE", (700, 650), (380, 700))
    label(d, "BELOW FREEZING", (1160, 415), (960, 500))
    footer_centered(d, "THE SKIN OF WATER")
    return finish_plate(img, 832, 0.18)


def b5_friction_heat():
    img = parchment(841)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    ice_band(d, y0=640, y1=830)
    # blade gliding right: heat glow at the contact, film trailing left
    glow(d, 940, 640, 130, RUST)
    glow(d, 940, 640, 70, RUST)
    skate_blade(d, 940, 420, half=150)
    for k in range(5):
        rx = 900 - k * 120
        water_sheen(d, rx, 646 + k * 2, 120 + k * 26, 12 + k * 3,
                    a=225 - k * 28)
    # motion direction
    arrow(d, (1090, 340), (1250, 340), col=NAVY, w=8, head=26)
    label(d, "FRICTION HEAT", (940, 640), (960, 420))
    label(d, "WATER FILM", (560, 660), (380, 720))
    footer_centered(d, "GLIDE ADDS HEAT")
    return finish_plate(img, 842, 0.18)


def b6_cold_film():
    img = parchment(851)
    d = ImageDraw.Draw(img, "RGBA")
    d.line(((768, 180), (768, 850)), fill=INK + (160,), width=4)
    # left panel: mild cold, generous film, glide. Glow rides ABOVE the ice
    # line (centered on the blade) — a glow centered on the contact is clipped
    # by the ice band into an odd orange mound (run-1 evidence).
    glow(d, 570, 470, 130, RUST)
    ice_band(d, y0=620, y1=830, x0=140, x1=748)
    skate_blade(d, 570, 400, half=130)
    water_sheen(d, 570, 622, 190, 16)
    label(d, "MINUS FIVE", (570, 622), (360, 450))
    # right panel: deep cold, starved film, bite
    glow(d, 1090, 470, 150, RUST)
    ice_band(d, y0=620, y1=830, x0=788, x1=1396)
    skate_blade(d, 1090, 400, half=130)
    water_sheen(d, 1090, 620, 120, 7, a=180)
    bite_marks(d, 950, 1230, 622)
    label(d, "MINUS THIRTY", (1090, 620), (880, 450))
    footer_centered(d, "THE FILM THINS")
    return finish_plate(img, 852, 0.18)


def b7_wet_payoff():
    img = parchment(861)
    tint = Image.new("RGBA", (W_, H_), (212, 148, 84, 34))  # dusk warmth
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    # ONE moderate dusk glow behind the subject. Run-1 evidence: two big
    # glows washed the whole card orange and the cream glow at the contact
    # buried the blade (judge saw "a white circle with a red line").
    # r=430 low on the ice band: enough rust mass for the continuity gate
    # without washing out blade + line (0.535 at r=300).
    glow(d, 768, 800, 430, RUST)
    ice_band(d)
    by, bx0, bx1 = skate_blade(d, 768, 400)
    # one calm glossy water line through the whole frame, ON TOP so the
    # blade + sheen read at phone size
    d.line(((300, 498), (1230, 498)), fill=CREAM + (255,), width=12)
    label(d, "ALREADY WET", (768, 498), (600, 300))
    footer_centered(d, "BORN AT THE SURFACE")
    return finish_plate(img, 862, 0.24)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_ice_blade_hero": b1_ice_blade_hero(),
        "B2_pressure_idea": b2_pressure_idea(),
        "B3_pressure_fail": b3_pressure_fail(),
        "B4_quasi_liquid": b4_quasi_liquid(),
        "B5_friction_heat": b5_friction_heat(),
        "B6_cold_film": b6_cold_film(),
        "B7_wet_payoff": b7_wet_payoff(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_pressure_idea", "B3_pressure_fail", "B4_quasi_liquid",
                 "B5_friction_heat", "B6_cold_film"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_pressure_idea", "diagram"),
                    ("B3_pressure_fail", "diagram"),
                    ("B4_quasi_liquid", "diagram"),
                    ("B5_friction_heat", "diagram"),
                    ("B6_cold_film", "diagram")])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=97, base_hz=100.0,
              dur=60.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=95, kind="swell",
              dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
