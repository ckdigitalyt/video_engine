"""Deterministic fallback cards for the three round_window plates that failed
their subject contracts across three flux rounds (21 candidates, all rejected
by eye/vision): B2 kept drawing propellers on the "first jet airliner", B3
produced whole WWII fighters instead of riveted-skin macro, no B4 combined a
round window with a wing at dawn.

Editorial call (V5 creative-director layer, disclosed in the post-render
package): the Comet inquiry itself ran on reconstruction drawings, so
  B2 -> period technical reconstruction drawing of the DH-106 Comet
  B3 -> forensic riveted-skin diagram with the crack origin labelled
  B4 -> real-photography porthole composite (wing-at-dusk crop inside a
        drawn round window frame) + a fully drawn variant as alternate
Style follows the series diagram family (aged parchment, sepia ink,
navy/rust accents) per the visual bible. Deterministic, no network.
"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from engine import bible as B, finish
from engine.style_continuity import style_continuity_score

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/home/ubuntu/.openclaw/workspace/media/plates/rw_cards')
OUT.mkdir(parents=True, exist_ok=True)
bible = B.load_bible(str(ROOT / 'stories/round_window'))

W, H = 1024, 1280
PARCH = (228, 216, 186)
PARCH_D = (210, 196, 164)
INK = (62, 52, 40)
NAVY = (34, 48, 78)
RUST = (194, 91, 51)
CREAM = (239, 230, 212)
MUTED = (122, 106, 82)
SEAM = (46, 41, 32)

try:
    from engine.diagrams import FONT_DIR as _fd
    _fd = Path(_fd)
except Exception:
    _fd = next(p.parent for p in ROOT.rglob('BebasNeue-Regular.ttf'))


def bebas(sz):
    return ImageFont.truetype(str(_fd / 'BebasNeue-Regular.ttf'), sz)


def inter(sz):
    return ImageFont.truetype(str(_fd / 'Inter-Variable.ttf'), sz)


def closed_catmull(pts, n=26):
    out = []
    m = len(pts)
    for i in range(m):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % m], pts[(i + 2) % m]
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    return out


def parchment_base():
    img = Image.new('RGB', (W, H), PARCH)
    ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rnd = random.Random(11)
    for _ in range(9):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        r = rnd.randint(180, 520)
        d.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2),
                  fill=PARCH_D + (rnd.randint(8, 14),))
    ov = ov.filter(ImageFilter.GaussianBlur(60))
    return Image.alpha_composite(img.convert('RGBA'), ov)


def frame_border(d, col=INK):
    d.rectangle((24, 24, W - 24, H - 24), outline=col + (95,), width=2)
    d.rectangle((34, 34, W - 34, H - 34), outline=col + (60,), width=1)


def grid(d, step=64, col=INK, alpha=13):
    for x in range(step, W, step):
        d.line((x, 40, x, H - 40), fill=col + (alpha,), width=1)
    for y in range(step, H, step):
        d.line((40, y, W - 40, y), fill=col + (alpha,), width=1)


def vgrad(w, h, top, bot):
    base = Image.new('RGB', (1, h))
    base.putdata([tuple(int(top[i] + (bot[i] - top[i]) * y / max(1, h - 1))
                        for i in range(3)) for y in range(h)])
    return base.resize((w, h))


def label(d, text, anchor, bar_xy, font=None, align='left'):
    font = font or bebas(36)
    tw = d.textlength(text, font=font)
    th = font.size
    pad_x, pad_y = 14, 8
    if align == 'left':
        x0, y0 = bar_xy
    else:
        x0, y0 = bar_xy[0] - int(tw) - 2 * pad_x, bar_xy[1]
    x1, y1 = x0 + int(tw) + 2 * pad_x, y0 + th + 2 * pad_y
    d.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=(23, 19, 16, 215))
    d.text((x0 + pad_x, y0 + pad_y - 2), text, font=font, fill=CREAM)
    ex = x0 if anchor[0] < x0 else x1
    ey = (y0 + y1) // 2
    d.line((anchor[0], anchor[1], ex, ey), fill=RUST + (220,), width=3)
    d.ellipse((anchor[0] - 4, anchor[1] - 4, anchor[0] + 4, anchor[1] + 4),
              fill=RUST + (230,))


# ---------------------------------------------------------------- B2 Comet --
def b2_comet():
    img = parchment_base()
    d = ImageDraw.Draw(img, 'RGBA')
    grid(d)

    def shape(pts, fill=PARCH):
        d.polygon(pts, fill=fill + (255,))

    def stroke(pts, width=4, col=INK, alpha=255):
        d.line(pts + [pts[0]], fill=col + (alpha,), width=width,
               joint='curve')

    prof = [(178, 641), (230, 600), (300, 583), (420, 576), (560, 572),
            (700, 568), (800, 560), (868, 548), (884, 570), (862, 588),
            (800, 640), (720, 678), (600, 692), (460, 696), (340, 694),
            (250, 678), (196, 656)]
    body = closed_catmull(prof)
    FIN = [(800, 566), (856, 436), (900, 440), (898, 476), (876, 556)]
    TAIL = [(804, 524), (930, 504), (936, 518), (812, 540)]
    WING = [(480, 656), (300, 776), (262, 768), (430, 648)]
    shape(FIN)                                                # fin
    shape(TAIL)                                               # tailplane
    shape(WING)                                               # near wing
    shape(body)                                               # fuselage last
    d.line(FIN, fill=INK + (255,), width=4, joint='curve')
    stroke(TAIL, 3)
    stroke(WING, 4)
    stroke(body, 4)
    # double-stroke pass for hand-inked feel
    stroke([(x + 2, y + 1) for x, y in body], 1, alpha=80)

    # wing-root engine intakes (the Comet signature: no propellers)
    for box in ((404, 640, 440, 682), (450, 632, 486, 674)):
        d.ellipse(box, fill=NAVY + (235,), outline=INK + (255,), width=2)
    # exhaust hint at root trailing edge
    d.line((490, 668, 548, 676), fill=INK + (150,), width=3)

    # passenger windows (the story's motif) + cockpit
    for x in range(300, 690, 24):
        d.rounded_rectangle((x, 598, x + 6, 610), radius=2,
                            fill=INK + (150,))
    d.line((230, 600, 252, 586), fill=INK + (200,), width=2)
    d.line((244, 602, 268, 588), fill=INK + (200,), width=2)
    d.text((742, 596), 'G-ALYP', font=inter(20), fill=INK + (190,))

    # clouds (sparse ink strokes)
    for (x0, y0, n) in ((140, 866, 5), (660, 890, 4), (380, 930, 3),
                        (560, 430, 3)):
        for i in range(n):
            d.line((x0 + i * 26, y0 + (i % 2) * 8, x0 + i * 26 + 40,
                    y0 + (i % 2) * 8), fill=INK + (22,), width=2)

    # annotation: engines buried in wing root
    d.line((468, 653, 380, 500, 150, 500), fill=RUST + (220,), width=2,
           joint='curve')
    d.ellipse((464, 649, 472, 657), fill=RUST + (230,))
    d.text((140, 468), 'ENGINES BURIED IN WING ROOT', font=inter(22),
           fill=RUST)

    d.text((W // 2, 1108), 'DE HAVILLAND DH-106 COMET', font=bebas(44),
           fill=INK, anchor='mm')
    d.text((W // 2, 1166), 'TECHNICAL RECONSTRUCTION - 1952', font=inter(24),
           fill=MUTED, anchor='mm')
    frame_border(d)
    return img.convert('RGB')


# ------------------------------------------------------- B3 forensic skin --
def b3_crack():
    img = vgrad(W, H, (168, 154, 130), (87, 80, 63)).convert('RGBA')
    d = ImageDraw.Draw(img, 'RGBA')
    # raking light from top-left, darker toward bottom-right
    d.polygon([(0, 0), (640, 0), (0, 640)], fill=(255, 250, 235, 22))
    dark = Image.new('RGBA', (W, 1))
    dark.putdata([(0, 0, 0, int(36 * x / W)) for x in range(W)])
    img = Image.alpha_composite(img, dark.resize((W, H)))
    d = ImageDraw.Draw(img, 'RGBA')

    def rivet(x, y, r=4):
        d.ellipse((x - r, y - r, x + r, y + r), fill=(110, 99, 83),
                  outline=SEAM + (200,), width=1)
        d.ellipse((x - r + 1, y - r + 1, x - r + 3, y - r + 3),
                  fill=(216, 204, 176, 90))

    for x0 in (330, 690):
        d.line((x0, 0, x0, H), fill=SEAM + (120,), width=2)
        for y in range(24, H, 26):
            rivet(x0 - 13, y)
            rivet(x0 + 13, y)
    d.line((0, 430, W, 430), fill=SEAM + (120,), width=2)
    for x in range(24, W, 26):
        rivet(x, 417)
        rivet(x, 443)

    # ADF antenna cutout (sharp corners) with rim rivets
    d.rounded_rectangle((380, 300, 520, 390), radius=7, fill=(59, 53, 42),
                        outline=(36, 32, 25), width=3)
    d.line((386, 307, 514, 307), fill=(0, 0, 0, 80), width=3)
    d.line((386, 383, 514, 383), fill=(201, 188, 162, 70), width=2)
    for x in range(384, 522, 20):
        rivet(x, 282)
        rivet(x, 408)
    for y in range(306, 392, 18):
        rivet(362, y)
        rivet(538, y)
    # stress ticks at the sharp corners
    d.polygon([(512, 296), (524, 306), (510, 310)], fill=RUST + (200,))
    d.polygon([(512, 394), (524, 384), (510, 380)], fill=RUST + (170,))

    crack = [(520, 306), (548, 272), (572, 258), (600, 240), (622, 244),
             (646, 218), (676, 210)]
    d.line([(x + 1, y - 1) for x, y in crack], fill=(216, 204, 176, 110),
           width=1, joint='curve')
    d.line(crack, fill=(30, 27, 22), width=4, joint='curve')
    d.line([(572, 258), (592, 236), (612, 228)], fill=(30, 27, 22, 230),
           width=3, joint='curve')
    d.ellipse((512, 298, 528, 314), outline=RUST + (200,), width=2)

    label(d, 'ADF ANTENNA CUTOUT', (522, 345), (600, 316))
    label(d, 'FATIGUE CRACK ORIGIN', (528, 302), (660, 150))
    d.text((60, 1190), 'FUSELAGE ROOF PANEL - RIVETED ALUMINIUM',
           font=inter(22), fill=(222, 210, 182, 235))
    frame_border(d, col=(36, 32, 25))
    return img.convert('RGB')


# ------------------------------------------------------- B4 payoff window --
def b4_composite():
    src = Image.open(Path('/home/ubuntu/.openclaw/workspace/media/plates/'
                          'rw_candidates/B4_payoff_window_s11.png')).convert(
        'RGB')
    w, h = src.size
    side = int(min(w, h) * 0.8)
    cx, cy = int(w * 0.55), int(h * 0.38)
    box = (max(0, cx - side // 2), max(0, cy - side // 2),
           min(w, cx + side // 2), min(h, cy + side // 2))
    print(f'B4 src {w}x{h} crop {box}', flush=True)
    crop = src.crop(box).resize((840, 840), Image.LANCZOS)
    img = vgrad(W, H, (38, 32, 26), (23, 19, 16)).convert('RGBA')
    d = ImageDraw.Draw(img, 'RGBA')
    d.ellipse((512 - 470, 630 - 470, 512 + 470, 630 + 470),
              fill=(233, 223, 200, 8))
    mask = Image.new('L', (840, 840), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 840, 840), fill=255)
    img.paste(crop, (92, 210), mask)
    cx, cy = 512, 630
    d.ellipse((cx - 450, cy - 450, cx + 450, cy + 450),
              outline=(0, 0, 0, 90), width=18)
    d.ellipse((cx - 435, cy - 435, cx + 435, cy + 435),
              outline=(74, 68, 58), width=30)
    d.ellipse((cx - 422, cy - 422, cx + 422, cy + 422),
              outline=(181, 172, 152, 230), width=4)
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dg = ImageDraw.Draw(glow)
    dg.arc((cx - 370, cy - 370, cx + 370, cy + 370), 190, 265,
           fill=(255, 255, 255, 30), width=34)
    glow = glow.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img, 'RGBA')
    d.arc((cx - 402, cy - 402, cx + 402, cy + 402), 160, 350,
          fill=(0, 0, 0, 50), width=24)
    rnd = random.Random(7)
    for _ in range(3200):
        x, y = rnd.randint(0, W - 1), rnd.randint(0, H - 1)
        a = rnd.randint(0, 12)
        d.rectangle((x, y, x + 1, y + 1),
                    fill=(233, 223, 200, a) if rnd.random() < 0.5
                    else (0, 0, 0, a))
    scr = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(scr)
    for i in range(920, H):
        a = int(min(1.0, (i - 920) / 150.0) * 245)
        ds.line((0, i, W, i), fill=(23, 19, 16, a))
    # lower-corner shadows, BOTH sides: absorb the ring's left AND right
    # arcs so no camera state (S07 zoompan 1.16 -> 1.0) can carry bright
    # rim into the caption band edge (vignette-style, intentional look)
    px = scr.load()
    for xr in list(range(0, 300)) + list(range(W - 300, W)):
        ex = xr if xr < 300 else W - 1 - xr
        for y in range(700, 1250):
            dd = 1.0 - min(1.0, ((ex / 300.0) ** 2 +
                                 ((y - 700) / 550.0) ** 2)) ** 0.5
            if dd > 0:
                a = int(dd * 235)
                if a > px[xr, y][3]:
                    px[xr, y] = (23, 19, 16, a)
    img = Image.alpha_composite(img, scr)
    return img.convert('RGB')


def b4_drawn():
    """Fully drawn alternate: dawn gradient + wing silhouette in porthole."""
    img = vgrad(W, H, (38, 32, 26), (23, 19, 16)).convert('RGBA')
    d = ImageDraw.Draw(img, 'RGBA')
    cx, cy, R = 512, 630, 420
    # dawn sky: navy -> rust band -> dark haze
    sky = vgrad(2 * R, 2 * R, (30, 42, 68), (196, 128, 88)).convert('RGBA')
    band = Image.new('RGBA', (2 * R, 2 * R), (0, 0, 0, 0))
    db = ImageDraw.Draw(band)
    db.rectangle((0, int(R * 1.16), 2 * R, int(R * 1.30)),
                 fill=(226, 150, 96, 120))
    db.rectangle((0, int(R * 1.30), 2 * R, 2 * R), fill=(70, 52, 42, 150))
    sky = Image.alpha_composite(sky, band)
    mask = Image.new('L', (2 * R, 2 * R), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * R, 2 * R), fill=255)
    img.paste(sky, (cx - R, cy - R), mask)
    d = ImageDraw.Draw(img, 'RGBA')
    # wing silhouette sweeping across the lower view
    d.polygon([(cx - R + 10, cy + 150), (cx + 60, cy + 96),
               (cx + R - 6, cy + 66), (cx + R - 2, cy + 104),
               (cx - R + 16, cy + 208)], fill=(20, 18, 15, 255))
    d.polygon([(cx - 40, cy + 108), (cx + 30, cy + 86), (cx + 46, cy + 100),
               (cx - 24, cy + 122)], fill=(20, 18, 15, 220))
    d.ellipse((cx - 435, cy - 435, cx + 435, cy + 435),
              outline=(74, 68, 58), width=30)
    d.ellipse((cx - 422, cy - 422, cx + 422, cy + 422),
              outline=(181, 172, 152, 230), width=4)
    d.arc((cx - 370, cy - 370, cx + 370, cy + 370), 190, 265,
          fill=(255, 255, 255, 26), width=30)
    d.arc((cx - 402, cy - 402, cx + 402, cy + 402), 160, 350,
          fill=(0, 0, 0, 50), width=24)
    return img.convert('RGB')


def accept(name, img):
    p = OUT / f'{name}.png'
    img.save(p)
    fin = finish.finish_if_better(
        p, p.with_name(f'{name}_fin.png'),
        lambda q: style_continuity_score(Image.open(q), bible))
    keep = Path(fin['out'])
    (ROOT / 'assets' / f'{name}.png').write_bytes(keep.read_bytes())
    (ROOT / 'assets' / f'{name}.orig.png').write_bytes(p.read_bytes())
    sc = round(float(style_continuity_score(Image.open(keep), bible)), 3)
    print(f'{name}: finish={fin["kept"]} continuity={sc}', flush=True)


if __name__ == '__main__':
    accept('B2_comet_jet', b2_comet())
    accept('B3_crack_skin', b3_crack())
    accept('B4_payoff_window', b4_composite())
    b4_drawn().save(OUT / 'B4_payoff_window_drawn.png')
    print('done', flush=True)
