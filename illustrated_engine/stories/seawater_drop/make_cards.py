"""seawater_drop — deterministic plates + SFX pack.

Scale-descent story: what's inside a single drop of seawater — diatoms,
bacteria, a swarm of viruses, then ions: one connected machine. Grammar
`scale_descent` on the kit depth_gradient background.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import ASSETS, arrow, big_number, label, register_diagram, \
    save_plate, write_manifest
from _v12_kitlib import finish, kit_background
from PIL import Image, ImageDraw

STORY = Path(__file__).resolve().parent

AQUA = (96, 142, 142)
LIGHT = (198, 218, 218)
NAVY = (36, 64, 92)
AMBER = (224, 163, 60)
CREAM = (240, 233, 218)


def _kit():
    return kit_background("depth_gradient", seed=6301,
                          top=(104, 120, 122), mid=(60, 78, 86),
                          bottom=(44, 56, 66))


def specks(d, cx, cy, rx, ry, n, seed=7, r=(3, 9), col=AQUA):
    import random as _r
    rnd = _r.Random(seed)
    for _ in range(n):
        x = cx + rnd.randint(-rx, rx)
        y = cy + rnd.randint(-ry, ry)
        rr = rnd.randint(*r)
        a = rnd.randint(120, 230)
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=col + (a,))


def diatom(d, cx, cy, s=1.0):
    d.ellipse((cx - 200 * s, cy - 120 * s, cx + 200 * s, cy + 120 * s),
              outline=AQUA + (255,), width=9)
    d.ellipse((cx - 170 * s, cy - 95 * s, cx + 170 * s, cy + 95 * s),
              outline=AQUA + (150,), width=4)
    for k in range(9):
        x = cx - 150 * s + k * 38 * s
        d.line((x, cy - 90 * s, x, cy + 90 * s), fill=AQUA + (120,), width=3)


def bacterium(d, cx, cy, s=1.0, burst=False):
    w, h = 150 * s, 70 * s
    d.rounded_rectangle((cx - w, cy - h, cx + w, cy + h), radius=70,
                        outline=AQUA + (255,), width=8)
    for k in range(4):
        d.arc((cx - w + 30 + k * 60 * s, cy - 40 * s,
               cx - w + 80 + k * 60 * s, cy + 40 * s),
              start=90, end=270, fill=AQUA + (140,), width=3)
    if burst:
        cloud = [(cx + w + 40, cy, 90), (cx + w + 110, cy - 40, 60),
                 (cx + w + 90, cy + 60, 70)]
        for (x, y, r) in cloud:
            d.ellipse((x - r, y - r // 2, x + r, y + r // 2),
                      fill=AMBER + (70,))
        for k in range(6):
            ang = math.radians(k * 60)
            d.line((cx + w, cy, cx + w + 70 * math.cos(ang),
                    cy + 55 * math.sin(ang)), fill=AMBER + (200,), width=4)


def virus(d, x, y, s=1.0, col=AQUA):
    r = 14 * s
    d.ellipse((x - r, y - r, x + r, y + r), outline=col + (240,), width=4)
    for k in range(6):
        ang = math.radians(k * 60)
        d.line((x + r * math.cos(ang), y + r * math.sin(ang),
                x + (r + 7 * s) * math.cos(ang), y + (r + 7 * s) * math.sin(ang)),
               fill=col + (220,), width=3)


def ion_pair(d, x, y, s=1.0):
    d.ellipse((x - 12 * s, y - 12 * s, x + 12 * s, y + 12 * s),
              fill=AQUA + (230,))
    d.ellipse((x + 26 * s - 9 * s, y - 9 * s, x + 26 * s + 9 * s, y + 9 * s),
              outline=LIGHT + (220,), width=4)


def chip(d, text, x, y):
    label(d, text, (x, y), (x + 60, y + 40), col=NAVY)


def sd_b1_hook():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    d.line((120, 330, 1440, 330), fill=LIGHT + (90,), width=6)
    for k in range(3):
        d.arc((140 + k * 400, 250, 540 + k * 400, 400), start=200, end=340,
              fill=LIGHT + (60,), width=4)
    d.ellipse((468, 330, 1068, 830), fill=(10, 26, 46, 200),
              outline=LIGHT + (200,), width=7)
    specks(d, 768, 580, 240, 190, 90, seed=11)
    big_number(d, "0.05 mL", (1120, 700), size=90, col=AMBER)
    label(d, "ONE DROP OF SURFACE SEAWATER", (700, 560), (360, 300))
    label(d, "A CITY IN SUSPENSION", (768, 850), (520, 900))
    return finish(img, 6302, 0.28)


def sd_b2_composition():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((560, 260, 700, 940), radius=24,
                        outline=CREAM + (200,), width=6)
    d.rectangle((566, 270, 694, 640), fill=NAVY + (140,))
    d.rectangle((566, 646, 694, 934), fill=AQUA + (110,))
    for k in range(9):
        ion_pair(d, 615 + (k % 3) * 26, 700 + (k // 3) * 70, 0.8)
    d.rectangle((566, 900, 694, 934), fill=AMBER + (200,))
    label(d, "WATER ~96.5%", (630, 400), (300, 380))
    label(d, "SALT ~3.5% (NA+ CL-)", (630, 770), (300, 760))
    label(d, "THE LIVING SLIVER", (630, 916), (760, 900))
    return finish(img, 6303, 0.28)


def sd_b3_diatom():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    for k in range(4):
        x = 400 + k * 120
        d.line((x, 220, x + 60, 520), fill=LIGHT + (70,), width=5)
    diatom(d, 768, 560, 1.15)
    big_number(d, "100 μm", (1120, 300), size=100, col=AMBER)
    label(d, "DIATOM: A DRIFTING GLASS SHELL", (700, 440), (360, 300))
    label(d, "~1/5 OF THE OCEAN'S FOOD", (740, 740), (560, 840))
    return finish(img, 6304, 0.28)


def sd_b4_viral():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    bacterium(d, 620, 560, 1.1, burst=True)
    specks(d, 1020, 480, 160, 130, 34, seed=23, r=(4, 8), col=LIGHT)
    for (x, y) in ((940, 400), (1060, 430), (1000, 520), (1100, 560), (950, 560)):
        virus(d, x, y, 1.1, col=LIGHT)
    big_number(d, "1 μm", (1120, 280), size=90, col=AMBER)
    label(d, "BACTERIUM — THE OCEAN'S ENGINEER", (560, 440), (330, 300))
    label(d, "VIRUSES: TEN TIMES MORE", (1020, 640), (700, 780))
    label(d, "CELLS BURST — CARBON LEAKS OUT", (790, 690), (560, 860))
    return finish(img, 6305, 0.28)


def sd_b5_foodweb():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    specks(d, 500, 880, 120, 60, 24, seed=31, r=(3, 6))
    bacterium(d, 560, 700, 0.55)
    d.ellipse((880, 560, 1080, 700), outline=AQUA + (240,), width=7)  # copepod
    d.line((930, 560, 910, 500), fill=AQUA + (200,), width=4)
    d.line((1010, 560, 1030, 500), fill=AQUA + (200,), width=4)
    d.polygon([(420, 380), (560, 330), (590, 400), (520, 430), (440, 420)],
              outline=AQUA + (250,), width=7)  # fish larva
    d.polygon([(590, 370), (650, 345), (590, 415)], outline=AQUA + (250,), width=5)
    for (y0, y1) in ((830, 740), (660, 590), (520, 430)):
        arrow(d, (700, y0), (700, y1), col=AMBER, w=7)
    label(d, "MOLECULES", (500, 900), (330, 950))
    label(d, "BACTERIA", (560, 720), (330, 760))
    label(d, "GRAZERS", (980, 640), (1010, 700))
    label(d, "FISH LARVA", (500, 350), (300, 300))
    label(d, "THE FOOD WEB STARTS HERE", (760, 260), (560, 210))
    return finish(img, 6306, 0.28)


def sd_b6_ions():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    for (x, y, s) in ((520, 420, 1.3), (900, 620, 1.1), (700, 800, 0.9),
                      (1040, 380, 0.8), (420, 700, 0.7)):
        ion_pair(d, x, y, s)
    specks(d, 768, 560, 300, 240, 40, seed=41, r=(2, 5), col=LIGHT)
    big_number(d, "0.2 nm", (1120, 280), size=90, col=AMBER)
    label(d, "SODIUM + CHLORIDE IONS", (540, 470), (330, 330))
    label(d, "DISSOLVED GASSES, ORGANIC SPECKS", (760, 640), (520, 760))
    label(d, "A MILLIONFOLD SMALLER THAN BACTERIA", (700, 340), (480, 240))
    return finish(img, 6307, 0.28)


def sd_b7_ladder():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    x = 768
    d.line((x, 240, x, 940), fill=AQUA + (200,), width=6)
    d.ellipse((x - 130, 220, x + 130, 340), outline=LIGHT + (220,), width=5)
    specks(d, x, 280, 90, 40, 18, seed=51, r=(2, 5))
    diatom(d, x, 450, 0.42)
    bacterium(d, x, 620, 0.34)
    virus(d, x, 760, 1.3, col=LIGHT)
    ion_pair(d, x, 900, 1.2)
    for (y, t) in ((280, "DROP 0.05 mL"), (450, "DIATOM 100 μm"),
                   (620, "BACTERIUM 1 μm"), (760, "VIRUS 0.1 μm"),
                   (900, "ION 0.2 nm")):
        chip(d, t, x - 120, y + 14)
    label(d, "ONE LADDER — ONE MACHINE", (740, 160), (480, 180))
    return finish(img, 6308, 0.28)


def synth_sfx_pack(audio_dir):
    import wave
    import numpy as np
    SR = 44100
    rng = np.random.default_rng(6300)

    def _write(path, stereo):
        data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes(data.tobytes())

    def _norm(sig, g):
        return sig / (np.sqrt((sig ** 2).mean()) or 1e-9) * g

    n = int(SR * 0.9); t = np.arange(n) / SR
    env = np.sin(math.pi * np.minimum(t / 0.9, 1.0)) ** 2
    k = np.exp(-np.linspace(-2, 5.4, n))
    spec = np.fft.rfft(rng.standard_normal(n) * k)
    fr = np.fft.rfftfreq(n, 1 / SR); spec[(fr < 600) | (fr > 4500)] = 0
    _write(audio_dir / "sfx_whoosh.wav",
           np.stack([_norm(np.fft.irfft(spec, n) * env, 0.045)] * 2, 1))
    n = int(SR * 0.12); t = np.arange(n) / SR
    tick = np.sin(2 * math.pi * 2400 * t) * np.exp(-t * 55)
    _write(audio_dir / "sfx_tick.wav", np.stack([_norm(tick, 0.04)] * 2, 1))
    n = int(SR * 0.5); t = np.arange(n) / SR
    thud = np.sin(2 * math.pi * (64 - 44 * t / 0.5) * t) * np.exp(-t * 9)
    _write(audio_dir / "sfx_pulse.wav", np.stack([_norm(thud, 0.05)] * 2, 1))
    print("  sfx pack: whoosh/tick/pulse")


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "SD_B1_hook": sd_b1_hook(),
        "SD_B2_composition": sd_b2_composition(),
        "SD_B3_diatom": sd_b3_diatom(),
        "SD_B4_viral": sd_b4_viral(),
        "SD_B5_foodweb": sd_b5_foodweb(),
        "SD_B6_ions": sd_b6_ions(),
        "SD_B7_ladder": sd_b7_ladder(),
    }
    from engine import bible as B
    bible = B.load_bible(STORY)
    scores = [save_plate(img, name, bible) for name, img in plates.items()]
    d_scores = []
    for name in ("SD_B2_composition", "SD_B3_diatom", "SD_B4_viral",
                 "SD_B5_foodweb", "SD_B6_ions"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([(n, "diagram") for n in
                    ("SD_B2_composition", "SD_B3_diatom", "SD_B4_viral",
                     "SD_B5_foodweb", "SD_B6_ions")])
    audio = STORY / "audio"
    audio.mkdir(exist_ok=True)
    synth_sfx_pack(audio)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
