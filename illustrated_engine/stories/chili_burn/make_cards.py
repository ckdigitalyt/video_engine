"""chili_burn — deterministic plates + diagram cards + SFX.

Why-chilies-burn story: capsaicin faking heat at TRPV1, the false-alarm
signal, water failing, the milk wash, the bird payoff. All art Pillow-drawn
via _v6_cardlib (no image-model calls, no network), parchment family per the
shared visual bible. V7 chrome policy: NO baked title bars; cards carry only
subtle footer section markers.

V10 edge-label discipline: landscape plates are cover-cropped into the
portrait card, so the visible horizontal band is the central 62.5% =>
x 288..1248 at scale 1.0. Every label/bar/anchor here is kept inside
x 350..1190, and footer text is drawn CENTERED.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, CREAM, INK, NAVY, NAVY_D, PARCH, PARCH_D,
                         PARCH_L, RUST, W, bebas, bgrid, finish_plate,
                         inter, label, parchment, register_diagram,
                         save_plate, synth_bed, write_manifest)
from PIL import Image, ImageDraw

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)

# RED HEAT palette: chili-red accent owns the histogram; plum-ink chrome is
# desaturated; slate is water/chrome only. Green reserved for the stem.
RED = (194, 59, 34)
RED_D = (150, 42, 22)
PLUM = (62, 42, 46)
PLUM_D = (44, 28, 30)
SLATE = (74, 78, 88)      # desaturated water/chrome (drops out of hue hist)
CREAMY = (239, 227, 200)
LEAF = (94, 107, 67)


# ------------------------------------------------------------ helpers ---

def footer_centered(d, text, y=920):
    d.rectangle((40, y, W - 40, y + 66), fill=PLUM_D + (255,))
    f = inter(30)
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y + 10), text, font=f, fill=CREAM + (245,))


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        a = int(26 * (layers - i + 1) / layers)
        d.ellipse((cx - r * i / 3, cy - r * i / 3.6,
                   cx + r * i / 3, cy + r * i / 3.6), fill=col + (a,))


def droplet(d, x, y, r=11, col=RED, a=235):
    d.ellipse((x - r, y - r * 1.25, x + r, y + r * 0.95), fill=col + (a,))
    d.ellipse((x - r * 0.4, y - r * 0.9, x + r * 0.1, y - r * 0.35),
              fill=(255, 245, 225, 90))


def chili_outline(d, cx, cy, L=460, Hh=150, rot=0.0):
    """Chili body: tapered pod as a smooth polygon; returns anchor points."""
    import numpy as np
    t = np.linspace(0, 2 * math.pi, 120, endpoint=False)
    pts = []
    for th in t:
        xx = math.cos(th)
        yy = math.sin(th)
        taper = 1.0 - 0.72 * max(0.0, xx) ** 1.2      # pointy tip at +x
        pts.append((cx + xx * L / 2 * taper * math.cos(rot)
                    - yy * Hh * taper * math.sin(rot),
                    cy + xx * L / 2 * taper * math.sin(rot)
                    + yy * Hh * taper * math.cos(rot)))
    d.polygon(pts, fill=RED + (255,))
    d.line(pts + [pts[0]], fill=RED_D + (255,), width=4)
    return pts


def seed(d, x, y, rot=0.3):
    d.ellipse((x - 14, y - 9, x + 14, y + 9), fill=CREAMY + (250,))
    d.arc((x - 14, y - 9, x + 14, y + 9), 200, 340, fill=INK + (120,), width=2)


def membrane(d, y, x0=340, x1=1200):
    for dy, a in ((0, 235), (10, 170)):
        d.line((x0, y + dy, x1, y + dy), fill=PLUM + (a,), width=5)
    for x in range(x0, x1, 56):
        d.line((x, y, x + 18, y + 10), fill=PLUM + (120,), width=2)


def gate(d, x, y, half=34, open_px=0):
    """Two channel leaves; open_px lifts the right leaf."""
    d.line((x - half, y, x - 4, y - 16), fill=RED + (255,), width=9)
    d.line((x + 4 + open_px * 0.4, y - 16 - open_px * 0.5,
            x + half + open_px, y), fill=RED + (255,), width=9)


def nerve_path(d, pts):
    d.line(pts, fill=PLUM + (240,), width=7)
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=PLUM + (200,))


def bell(d, cx, cy, s=46):
    d.pieslice((cx - s, cy - s, cx + s, cy + s), 180, 360, fill=RED + (255,))
    d.rectangle((cx - s, cy, cx + s, cy + 12), fill=RED + (255,))
    d.ellipse((cx - 9, cy + 12, cx + 9, cy + 26), fill=RED + (255,))


# ------------------------------------------------------------- plates ---

def b1_chili_hero():
    img = parchment(901)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 520, 330, RED)
    pts = chili_outline(d, 768, 540, L=520, Hh=170, rot=0.0)
    # cut face: inner cavity + placenta band along the lower wall with glands
    d.polygon([(560, 540), (976, 540), (930, 610), (606, 610)],
              fill=PARCH_D + (255,))
    d.line((580, 620, 956, 620), fill=CREAMY + (255,), width=16)
    for gx in range(600, 940, 56):
        glow(d, gx, 620, 34, RED)
        droplet(d, gx, 620, r=10)
    for sx in range(640, 900, 82):
        seed(d, sx, 556, rot=0.2)
    d.line((768, 540 - 170 - 6, 768 + 60, 540 - 150), fill=LEAF + (255,),
           width=10)
    label(d, "PLACENTA", (700, 620), (380, 760))
    label(d, "CAPSAICIN GLANDS", (840, 620), (900, 780))
    label(d, "SEEDS", (720, 556), (420, 430))
    footer_centered(d, "NO FLAME. NO HEAT.")
    return finish_plate(img, 902, 0.22)


def b2_nerve_alarm():
    img = parchment(911)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 470, 240, RED)
    # two inputs, one alarm
    chili_outline(d, 470, 430, L=150, Hh=48)
    label(d, "CHILI", (470, 430), (370, 330))
    # heat input: scald symbol
    d.ellipse((438, 560, 502, 624), outline=RED + (255,), width=5)
    for i in range(3):
        d.arc((450 + i * 12, 540, 470 + i * 12, 560), 200, 340,
              fill=RED + (220,), width=4)
    label(d, "HEAT", (470, 592), (370, 700))
    nerve_path(d, [(510, 440), (640, 470), (768, 470), (768, 330)])
    nerve_path(d, [(512, 596), (660, 540), (768, 470)])
    bell(d, 768, 260)
    label(d, "ONE ALARM", (768, 250), (960, 200))
    footer_centered(d, "THE SAME ALARM")
    return finish_plate(img, 912, 0.18)


def b3_trpv1_gate():
    img = parchment(921)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 520, 300, RED)
    d.line((768, 120, 768, 860), fill=PLUM + (90,), width=3)
    for y0, lab in ((430, None),):
        membrane(d, y0, x0=360, x1=720)
        membrane(d, y0, x0=816, x1=1176)
    # left: heat opens
    from _v6_cardlib import arrow
    arrow(d, (540, 250), (540, 396), col=RED, w=11, head=28)
    gate(d, 540, 430, open_px=22)
    d.text((505, 470), "43\u00b0C", font=bebas(56), fill=RED + (255,))
    label(d, "HEAT OPENS", (540, 300), (370, 220))
    # right: capsaicin wedges it open, cool
    gate(d, 996, 430, open_px=22)
    d.ellipse((952, 388, 1040, 436), fill=RED + (255,))
    d.line((1040, 412, 1108, 404), fill=RED + (255,), width=7)
    label(d, "CAPSAICIN WEDGES IT OPEN", (996, 412), (850, 260))
    d.text((930, 470), "37\u00b0C", font=bebas(56), fill=SLATE + (255,))
    footer_centered(d, "THE GATE OPENS")
    return finish_plate(img, 922, 0.18)


def b4_ion_flood():
    img = parchment(931)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 768, 480, 280, RED)
    membrane(d, 360, x0=360, x1=1176)
    gate(d, 768, 360, half=52, open_px=34)
    for i in range(9):
        y = 386 + i * 34
        droplet(d, 748 - (i % 3) * 26, y, r=11, col=RED)
        droplet(d, 796 + (i % 2) * 24, y + 16, r=11, col=RED)
    nerve_path(d, [(768, 640), (768, 560), (860, 520), (960, 470)])
    d.text((980, 420), "BURNING", font=bebas(72), fill=RED + (255,))
    label(d, "IONS", (720, 480), (400, 520))
    label(d, "OPEN CHANNEL", (768, 360), (420, 260))
    label(d, "ONE MESSAGE UP", (900, 500), (1080, 640))
    footer_centered(d, "A FALSE ALARM")
    return finish_plate(img, 932, 0.18)


def b5_water_fails():
    img = parchment(941)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 520, 300, RED)
    d.line((360, 640, 1176, 640), fill=PLUM + (170,), width=4)
    for i in range(7):
        droplet(d, 560 + i * 70, 628, r=16, col=RED)
    # incoming water drop + outward spread fan
    d.ellipse((726, 200, 810, 284), fill=SLATE + (255,))
    from _v6_cardlib import arrow
    for dx in (-210, -120, 120, 210):
        arrow(d, (768, 500), (768 + dx, 616), col=SLATE, w=8, head=24)
    label(d, "WATER", (768, 240), (1020, 180))
    label(d, "FAT-LOVING DROPLETS", (700, 628), (360, 740))
    label(d, "SMEARED WIDER", (990, 600), (1040, 500))
    footer_centered(d, "WATER MAKES IT WORSE")
    return finish_plate(img, 942, 0.2)


def b6_milk_wash():
    img = parchment(951)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 520, 300, RED)
    d.line((768, 120, 768, 860), fill=PLUM + (90,), width=3)
    # left: free droplets spreading
    for i in range(5):
        droplet(d, 470 + i * 68, 430 + (i % 2) * 40, r=13, col=RED)
    from _v6_cardlib import arrow
    arrow(d, (500, 500), (430, 560), col=SLATE, w=8, head=22)
    arrow(d, (740, 500), (810, 560), col=SLATE, w=8, head=22)
    label(d, "WATER: STILL LOOSE", (580, 450), (360, 300))
    # right: casein clusters capturing
    for cx, cy in ((940, 400), (1060, 470), (960, 560)):
        d.ellipse((cx - 44, cy - 34, cx + 44, cy + 34), fill=CREAMY + (255,))
        d.arc((cx - 44, cy - 34, cx + 44, cy + 34), 200, 340,
              fill=INK + (110,), width=2)
        droplet(d, cx + 30, cy - 10, r=9, col=RED)
    arrow(d, (1010, 620), (1010, 730), col=LEAF, w=9, head=24)
    label(d, "CASEIN GRIPS", (1010, 440), (1080, 320))
    label(d, "CARRIED OFF", (1010, 660), (1120, 760))
    footer_centered(d, "THE MILK WASH")
    return finish_plate(img, 952, 0.18)


def b7_bird_payoff():
    img = parchment(961)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 470, 300, RED)
    # engraved bird: body, head, beak, tail, legs
    d.ellipse((560, 380, 900, 580), fill=CREAMY + (255,))
    d.arc((560, 380, 900, 580), 200, 340, fill=PLUM + (255,), width=4)
    d.ellipse((840, 330, 950, 420), fill=CREAMY + (255,))
    d.arc((840, 330, 950, 420), 200, 340, fill=PLUM + (255,), width=4)
    d.polygon([(950, 370), (1010, 385), (950, 400)], fill=RED + (255,))
    d.ellipse((896, 348, 916, 366), fill=PLUM + (255,))
    d.line((640, 420, 700, 520), fill=PLUM + (230,), width=5)
    d.line((700, 520, 760, 470), fill=PLUM + (230,), width=5)
    d.polygon([(560, 470), (470, 520), (560, 500)], fill=PLUM + (255,))
    d.line((700, 580, 700, 660), fill=PLUM + (255,), width=6)
    d.line((800, 580, 800, 660), fill=PLUM + (255,), width=6)
    d.line((660, 662, 740, 662), fill=PLUM + (255,), width=5)
    d.line((760, 662, 840, 662), fill=PLUM + (255,), width=5)
    # whole chili swallowed from the beak
    chili_outline(d, 1030, 385, L=110, Hh=34, rot=0.0)
    d.line((360, 664, 1176, 664), fill=PLUM + (170,), width=4)
    for sx in (470, 590, 760, 900, 1060):
        seed(d, sx, 700, rot=0.1)
    label(d, "UNBOTHERED", (900, 350), (1080, 250))
    label(d, "SEEDS TRAVEL", (760, 700), (520, 800))
    footer_centered(d, "THE IMMUNE EATER")
    return finish_plate(img, 962, 0.24)


# ---------------------------------------------------------------- sfx ---

def _write_wav(path, stereo):
    import numpy as np
    import wave
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(data.tobytes())
    print(f"  sfx -> {path.name}")


def synth_sfx_pack(audio_dir):
    """whoosh (draw-on stroke), tick (number pop), pulse (stakes landing)."""
    import numpy as np
    SR = 44100
    rng = np.random.default_rng(4242)
    n = int(SR * 0.9)
    t = np.arange(n) / SR
    env = np.sin(math.pi * np.minimum(t / 0.9, 1.0)) ** 2
    noise = rng.standard_normal(n)
    k = np.exp(-np.linspace(-2, 5.4, n))
    spec = np.fft.rfft(noise * k)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    spec[(freqs < 600) | (freqs > 4200)] = 0
    body = np.fft.irfft(spec, n)
    sig = body * env
    sig = sig / (np.sqrt((sig ** 2).mean()) or 1e-9) * 0.045
    _write_wav(audio_dir / "sfx_whoosh.wav", np.stack([sig, sig], 1))

    n = int(SR * 0.12)
    t = np.arange(n) / SR
    tick = np.sin(2 * math.pi * 2100 * t) * np.exp(-t * 55)
    tick += 0.4 * np.sin(2 * math.pi * 3150 * t) * np.exp(-t * 70)
    tick = tick / (np.sqrt((tick ** 2).mean()) or 1e-9) * 0.04
    _write_wav(audio_dir / "sfx_tick.wav", np.stack([tick, tick], 1))

    n = int(SR * 0.5)
    t = np.arange(n) / SR
    thud = np.sin(2 * math.pi * (58 - 40 * t / 0.5) * t) * np.exp(-t * 9)
    thud = thud / (np.sqrt((thud ** 2).mean()) or 1e-9) * 0.05
    _write_wav(audio_dir / "sfx_pulse.wav", np.stack([thud, thud], 1))


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_chili_hero": b1_chili_hero(),
        "B2_nerve_alarm": b2_nerve_alarm(),
        "B3_trpv1_gate": b3_trpv1_gate(),
        "B4_ion_flood": b4_ion_flood(),
        "B5_water_fails": b5_water_fails(),
        "B6_milk_wash": b6_milk_wash(),
        "B7_bird_payoff": b7_bird_payoff(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_nerve_alarm", "B3_trpv1_gate", "B4_ion_flood",
                 "B5_water_fails", "B6_milk_wash"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_nerve_alarm", "diagram"),
                    ("B3_trpv1_gate", "diagram"),
                    ("B4_ion_flood", "diagram"),
                    ("B5_water_fails", "diagram"),
                    ("B6_milk_wash", "diagram")])
    audio_dir = STORY / "audio"
    audio_dir.mkdir(exist_ok=True)
    synth_sfx_pack(audio_dir)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
