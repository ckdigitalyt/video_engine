"""panama_locks — deterministic plates + diagram cards + bed/SFX.

Panama locks story: isthmus map silhouette hero, rock-and-tide rejection of
the sea-level ditch, gravity-fed lock cross-section, fresh-water toll,
drought gauge, water-saving basins payoff. All art Pillow-drawn via
_v6_cardlib (no image-model calls, no network), parchment family per the
shared visual bible. V7 chrome policy: NO baked title bars.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, CREAM, INK, NAVY, NAVY_D, PARCH, PARCH_L,
                         RUST, W, arrow, bgrid, footer_band, finish_plate,
                         inter, label, parchment, register_diagram,
                         save_plate, synth_bed, synth_sfx, write_manifest,
                         hatch_polygon)
from PIL import Image, ImageDraw

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

# Isthmus silhouette (Caribbean top-left, Pacific bottom-right), reused
# across the map plates so the hero stays recognizable in every shot.
LAND = [(150, 250), (440, 295), (715, 350), (975, 430), (1215, 565),
        (1395, 705), (1325, 790), (1105, 655), (855, 565), (605, 485),
        (355, 425), (135, 335)]
CANAL = [(820, 372), (800, 430), (788, 470), (775, 545), (758, 615), (742, 660)]
GREY_NAVY = (70, 74, 84)   # desaturated chrome: drops out of the hue
# histogram (cardlib convention) so rust/navy accents own the palette match.


# ------------------------------------------------------------ helpers ---

def rounded(d, box, r, **kw):
    d.rounded_rectangle(box, radius=r, **kw)


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def draw_map(d, land=True):
    """Parchment sea + isthmus silhouette + canal line + Gatun + labels."""
    # wave marks in both seas
    for (x0, y0) in ((200, 880), (520, 930), (1250, 260), (1420, 420)):
        for k in range(3):
            d.arc((x0 - 40 - k * 12, y0 - 14, x0 + 40 + k * 12, y0 + 14),
                  start=200, end=340, fill=NAVY + (110 - k * 25,), width=4)
    if land:
        d.polygon(LAND, fill=PARCH_L + (250,), outline=INK + (255,), width=6)
        # spine hatching
        hatch_polygon(img=None, pts=[], col=NAVY) if False else None
    # canal line + lock steps
    d.line(CANAL, fill=RUST + (255,), width=7, joint="curve")
    for k, (sx, sy) in enumerate(CANAL[3:6]):
        d.rectangle((sx - 13, sy - 13, sx + 13, sy + 13),
                    fill=RUST + (120,), outline=INK + (255,), width=3)
    # Gatun lake
    d.ellipse((742, 408, 872, 486), fill=NAVY + (170,),
              outline=INK + (200,), width=4)
    label(d, "GATUN LAKE", (806, 447), (1080, 330))
    label(d, "THE CANAL", (CANAL[4][0], CANAL[4][1]), (520, 640))
    label(d, "ATLANTIC", (300, 190), (170, 110))
    label(d, "PACIFIC", (1330, 905), (1330, 960))


def drops(d, pts, col=NAVY):
    for (x, y) in pts:
        d.ellipse((x - 7, y - 9, x + 7, y + 9), fill=col + (200,))


def hull(d, cx, water_y, s=1.0, col=RUST):
    """Simple ship hull sitting on a waterline at (cx, water_y)."""
    hw, hh = int(120 * s), int(46 * s)
    pts = [(cx - hw, water_y), (cx + hw, water_y), (cx + int(0.7 * hw),
           water_y + hh), (cx - int(0.7 * hw), water_y + hh)]
    d.polygon(pts, fill=col + (225,), outline=INK + (255,), width=4)
    d.rectangle((cx - 26, water_y - int(58 * s), cx + 34, water_y),
                fill=CREAM + (235,), outline=INK + (220,), width=3)


def water_fill(d, box, level_y, col=NAVY, alpha=55):
    x0, y0, x1, y1 = box
    d.rectangle((x0 + 6, level_y, x1 - 6, y1 - 6), fill=col + (alpha,))
    d.line(((x0 + 6, level_y), (x1 - 6, level_y)), fill=CREAM + (255,),
           width=5)


# ---------------------------------------------------------------- plates ---

def b1_panama_map_hero():
    img = parchment(701)
    d = ImageDraw.Draw(img, "RGBA")
    draw_map(d)
    # emphasis: glow along the staircase
    glow(d, 782, 470, 330, RUST)
    label(d, "26 M CLIMB", (775, 545), (330, 700))
    footer_band(d, "THE WATER STAIRCASE")
    return finish_plate(img, 702, 0.22)


def b2_rock_tide():
    img = parchment(711)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 1250, 700, 230, RUST)   # warm wash at the tidal coast
    draw_map(d)
    # hatched rock band along the spine
    hatch_polygon(img, [(560, 330), (900, 420), (1160, 560), (1050, 620),
                        (760, 480), (520, 390)], RUST, 60, 14, seed=5)
    label(d, "HARD ROCK", (830, 470), (940, 250))
    # dashed impossible flat channel + cross mark
    for k in range(12):
        x = 300 + k * 88
        y = 330 + (560 - 330) * k / 11.0
        d.line(((x - 14, y + 4), (x + 14, y - 4)), fill=INK + (190,), width=4)
    d.line(((600, 400), (660, 480)), fill=RUST + (255,), width=8)
    d.line(((660, 400), (600, 480)), fill=RUST + (255,), width=8)
    label(d, "NO FLAT PATH", (630, 440), (250, 540))
    # tidal arrows at the Pacific coast
    for k in range(2):
        d.arc((1180 + k * 36, 620 + k * 20, 1340 + k * 36, 760 + k * 20),
              start=110, end=215, fill=NAVY + (230 - k * 60,), width=6)
    arrow(d, (1240, 760), (1210, 690), col=NAVY, w=6, head=20)
    label(d, "TIDAL SWING", (1265, 700), (1150, 830))
    footer_band(d, "WHY NOT FLAT")
    return finish_plate(img, 712, 0.18)


def b3_lock_section():
    img = parchment(721)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 470, 460, 270, RUST)   # warm wash behind the gravity feed
    # chamber
    box = (560, 380, 1120, 780)
    rounded(d, box, 8, fill=PARCH_L + (60,), outline=INK + (255,), width=7)
    d.rectangle((536, 370, 572, 790), fill=GREY_NAVY + (255,))   # left gate wall
    d.rectangle((1108, 370, 1144, 790), fill=GREY_NAVY + (255,))  # right gate wall
    # water at mid level + ship
    water_fill(d, box, 560)
    hull(d, 840, 560)
    label(d, "SHIP RISES", (840, 500), (1150, 430))
    # culvert from the lake side with valve
    d.rectangle((330, 690, 560, 738), fill=NAVY + (220,),
                outline=INK + (255,), width=4)
    d.rectangle((510, 676, 546, 752), fill=RUST + (235,),
                outline=INK + (255,), width=3)
    arrow(d, (250, 714), (340, 714), col=NAVY, w=8, head=22)
    label(d, "VALVE", (528, 714), (380, 850))
    # gravity feed from Gatun (down the supply line)
    d.line(((470, 250), (470, 680)), fill=RUST + (235,), width=6)
    for k in range(7):
        yy = 300 + k * 52
        d.ellipse((462, yy - 6, 478, yy + 6), fill=CREAM + (230,))
    arrow(d, (470, 560), (470, 680), col=RUST, w=6, head=20)
    label(d, "GATUN LAKE", (470, 260), (120, 190))
    label(d, "CHAMBER", (840, 740), (700, 880))
    label(d, "GRAVITY FEED", (470, 480), (140, 460))
    footer_band(d, "GRAVITY DOES THE WORK")
    return finish_plate(img, 722, 0.18)


def b4_water_toll():
    img = parchment(731)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 775, 500, 300, RUST)   # warm wash over the canal corridor
    draw_map(d)
    # drain arrows from the lock steps to both oceans
    arrow(d, (758, 615), (980, 850), col=NAVY, w=8, head=24)
    arrow(d, (775, 545), (430, 250), col=NAVY, w=8, head=24)
    drops(d, [(850, 720), (920, 790), (650, 430), (560, 360), (700, 660),
              (800, 740)])
    label(d, "FRESH WATER", (700, 660), (560, 760))
    label(d, "TO THE SEA", (950, 820), (1000, 890))
    # rain-only refill into Gatun
    for k in range(4):
        d.arc((640 + k * 46, 210, 700 + k * 46, 260), start=180, end=360,
              fill=NAVY + (200,), width=5)
        drops(d, [(660 + k * 46, 280), (682 + k * 46, 320)], col=NAVY)
    label(d, "RAIN REFILL", (770, 260), (900, 150))
    footer_band(d, "THE WATER TOLL")
    return finish_plate(img, 732, 0.18)


def b5_drought_level():
    img = parchment(741)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 790, 560, 270, RUST)   # warm wash around the drought line
    # lake banks
    d.polygon([(180, 300), (420, 300), (420, 860), (180, 860)],
              fill=PARCH_L + (240,), outline=INK + (255,), width=5)
    d.polygon([(1160, 300), (1400, 300), (1400, 860), (1160, 860)],
              fill=PARCH_L + (240,), outline=INK + (255,), width=5)
    # normal level band (desaturated so water reads but stays out of the
    # hue histogram)
    d.rectangle((420, 380, 1160, 420), fill=NAVY + (55,))
    d.line(((420, 380), (1160, 380)), fill=CREAM + (255,), width=6)
    label(d, "GATUN LEVEL", (790, 400), (470, 250))
    # drought line (dashed, far below)
    for k in range(16):
        x = 420 + k * 47
        d.line(((x, 560), (x + 26, 560)), fill=RUST + (235,), width=6)
    label(d, "DROUGHT LINE", (790, 560), (1160, 500))
    # ship riding deep at the drought line, draft marks
    hull(d, 790, 560, s=0.92)
    for k in range(4):
        yy = 606 + k * 16
        d.line(((700 - k * 6, yy), (740 - k * 6, yy)), fill=INK + (200,),
               width=3)
    arrow(d, (790, 640), (790, 720), col=RUST, w=7, head=22)
    label(d, "DRAFT LIMIT", (790, 700), (600, 760))
    footer_band(d, "WHEN RAIN STOPS")
    return finish_plate(img, 742, 0.18)


def b6_recycle_payoff():
    img = parchment(751)
    tint = Image.new("RGBA", (W, 1024), (212, 148, 84, 34))  # dusk warmth
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 760, 940, 620, RUST)   # phone-b6 style dusk glows
    glow(d, 700, 920, 430, RUST)
    # main chamber at left with ship
    box = (330, 380, 760, 780)
    rounded(d, box, 8, fill=PARCH_L + (60,), outline=INK + (255,), width=7)
    water_fill(d, box, 540)
    hull(d, 545, 540, s=0.8)
    label(d, "SHIP", (545, 490), (330, 300))
    # stepped side basins to the right
    basins = [(830, 430, 1010, 560), (1040, 505, 1220, 640),
              (1250, 580, 1430, 720)]
    for (x0, y0, x1, y1) in basins:
        rounded(d, (x0, y0, x1, y1), 8, fill=PARCH_L + (50,),
                outline=INK + (255,), width=5)
        d.rectangle((x0 + 6, y0 + 34, x1 - 6, y1 - 6), fill=NAVY + (55,))
        d.line(((x0 + 6, y0 + 34), (x1 - 6, y0 + 34)), fill=CREAM + (255,),
               width=4)
    # spill arrows chamber -> basins, return arrows basins -> chamber
    for k, (bx0, by0, bx1, by1) in enumerate(basins):
        arrow(d, (760, 560 + k * 40), (bx0 - 8, (y0 := by0 + 30)),
              col=NAVY, w=6, head=18) if False else None
    arrow(d, (765, 560), (822, 500), col=NAVY, w=7, head=20)
    arrow(d, (765, 620), (1032, 580), col=NAVY, w=7, head=20)
    arrow(d, (765, 680), (1242, 660), col=NAVY, w=7, head=20)
    arrow(d, (1220, 700), (780, 740), col=CREAM, w=7, head=20)
    label(d, "SAVING BASINS", (1130, 560), (1090, 400))
    label(d, "WATER RETURNS", (990, 740), (760, 870))
    footer_band(d, "SIXTY PERCENT BACK")
    return finish_plate(img, 752, 0.24)


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_panama_map_hero": b1_panama_map_hero(),
        "B2_rock_tide": b2_rock_tide(),
        "B3_lock_section": b3_lock_section(),
        "B4_water_toll": b4_water_toll(),
        "B5_drought_level": b5_drought_level(),
        "B6_recycle_payoff": b6_recycle_payoff(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_rock_tide", "B3_lock_section", "B4_water_toll",
                 "B5_drought_level"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_rock_tide", "diagram"),
                    ("B3_lock_section", "diagram"),
                    ("B4_water_toll", "diagram"),
                    ("B5_drought_level", "diagram")])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=47, base_hz=87.0,
              dur=60.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=53, kind="swell",
              dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
