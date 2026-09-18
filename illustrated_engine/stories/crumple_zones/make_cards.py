"""crumple_zones — deterministic plates + SFX pack.

Engineering story: why the car that crumples protects you — the survival
cage plus a front end engineered to fold, buying stop time and spending
energy in designed hinges. Grammar `before_after` on the kit split_field.
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

STEEL = (110, 140, 160)    # cool side / intact
RUST = (194, 84, 62)       # warm side / collapsed
AMBER = (224, 163, 60)     # energy / cage glow
CREAM = (240, 233, 218)


def _kit():
    return kit_background("split_field", seed=5201)


def _car(d, cx, cy, scale=1.0, crumple=0.0, cage=False, hatch=False,
         folds=(), occupant=False):
    """Side-profile car centred on (cx, cy); crumple 0..1 deforms the nose."""
    s = scale
    x0, x1 = cx - 300 * s, cx + 300 * s
    y0, y1 = cy - 40 * s, cy + 80 * s
    body = STEEL if crumple < 0.5 else RUST
    d.rounded_rectangle((x0, y0, x1, y1), radius=40 * s,
                        outline=body + (255,), width=8)
    d.polygon([(cx - 170 * s, y0), (cx - 130 * s, y0 - 95 * s),
               (cx + 110 * s, y0 - 95 * s), (cx + 170 * s, y0)],
              outline=body + (255,), width=8)  # roof
    for wx in (x0 + 90 * s, x1 - 90 * s):
        d.ellipse((wx - 42 * s, y1 - 14 * s, wx + 42 * s, y1 + 70 * s),
                  fill=(20, 24, 28, 255), outline=body + (255,), width=6)
    nose_x0 = x1 - 150 * s
    if crumple > 0:
        n = int(crumple * 4) + 1
        for k in range(n):
            xx = nose_x0 + k * 26 * s
            amp = 14 * s * (1 + k * 0.5) * crumple
            d.line((xx, y0 + 6, xx + 13 * s, y0 + 6 + amp), fill=body + (255,), width=5)
            d.line((xx + 13 * s, y1 - 6 - amp, xx + 26 * s, y1 - 6), fill=body + (255,), width=5)
        d.line((x1 - 10 * s * crumple, y0, x1 - 46 * s * crumple, y0 - 95 * s),
               fill=body + (255,), width=8)
    if cage:
        for gx in range(6):
            xx = cx - 150 * s + gx * 55 * s
            d.line((xx, y0 - 80 * s, xx - 24 * s, y1 - 10 * s),
                   fill=AMBER + (210,), width=4)
        d.line((cx - 150 * s, y0 - 12 * s, cx + 150 * s, y0 - 12 * s),
               fill=AMBER + (210,), width=4)
    if hatch:
        for k in range(6):
            xx = nose_x0 + k * 24 * s
            d.line((xx, y0 + 10, xx + 20 * s, y1 - 10), fill=STEEL + (150,), width=3)
    if folds:
        for (frac, stage) in folds:
            xx = nose_x0 + frac * 120 * s
            col = AMBER + (230,) if stage else RUST + (120,)
            d.rounded_rectangle((xx - 16 * s, y0 - 6, xx + 16 * s, y1 - 4),
                                radius=8, outline=col, width=5)
    if occupant:
        d.ellipse((cx - 40 * s, y0 - 78 * s, cx - 4 * s, y0 - 42 * s),
                  fill=CREAM + (220,))
        d.line((cx - 24 * s, y0 - 42 * s, cx - 30 * s, y0 + 10 * s),
               fill=CREAM + (220,), width=8)


def _axis(d, x0, y0, x1, y1):
    d.line((x0, y0, x1, y0), fill=CREAM + (200,), width=5)
    d.line((x0, y0, x0, y1), fill=CREAM + (200,), width=5)


def cr_b1_hook():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    d.line((768, 200, 768, 950), fill=CREAM + (110,), width=4)
    _car(d, 768, 560, crumple=0.0)
    d.rounded_rectangle((768 + 40, 470, 1068, 640), radius=30,
                        outline=RUST + (230,), width=8)
    for k in range(4):
        d.line((810 + k * 60, 480, 850 + k * 60, 630), fill=RUST + (200,), width=5)
    label(d, "RIGID NOSE: PEAK FORCE INTO THE CABIN", (930, 440), (500, 300))
    label(d, "SAME BARRIER — TWO OUTCOMES", (700, 760), (430, 840))
    return finish(img, 5202, 0.28)


def cr_b2_cage():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    _car(d, 768, 560, crumple=0.0, cage=True, hatch=True)
    label(d, "HIGH-STRENGTH SURVIVAL CELL", (700, 470), (400, 300))
    label(d, "ENGINEERED CRUSH ZONE", (990, 600), (830, 760))
    return finish(img, 5203, 0.28)


def cr_b3_patent():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    d.line((768, 220, 768, 900), fill=CREAM + (110,), width=4)
    for k in range(6):  # straight rail, cool side
        d.line((430 + k * 50, 540, 470 + k * 50, 540), fill=STEEL + (230,), width=8)
    d.line((400, 540, 740, 540), fill=STEEL + (230,), width=6)
    for k in range(7):  # bellows rail, warm side
        xx = 800 + k * 46
        d.line((xx, 540, xx + 23, 500 + (k % 2) * 80), fill=RUST + (240,), width=8)
    big_number(d, "1952", (1120, 300), size=110, col=AMBER)
    label(d, "STRAIGHT RAIL", (540, 600), (400, 680))
    label(d, "BARÉNYI PATENT: BELLOWS RAIL", (980, 640), (700, 760))
    return finish(img, 5204, 0.28)


def cr_b4_pulse():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    _axis(d, 280, 320, 1160, 800)
    pts = [(280 + k * 24, 320 + int(430 * math.exp(-((k - 2) ** 2) / 6.0)))
           for k in range(14)]
    d.line(pts, fill=STEEL + (240,), width=9)
    pts2 = [(280 + k * 64, 320 + int(120 * math.sin(math.pi * k / 13.0) + 30))
            for k in range(14)]
    d.line(pts2, fill=AMBER + (240,), width=9)
    label(d, "RIGID STOP: TALL SPIKE", (610, 350), (430, 240))
    label(d, "CRUMPLED STOP: LONG, LOW", (900, 500), (760, 560))
    label(d, "SAME AREA — SAME MOMENTUM CHANGE", (700, 830), (430, 890))
    return finish(img, 5205, 0.28)


def cr_b5_folds():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    _car(d, 768, 560, crumple=0.7, cage=True, folds=[(0.1, 1), (0.45, 1), (0.8, 0)])
    label(d, "STAGE 3 WAITING", (1000, 500), (860, 330))
    label(d, "FOLD 1 — FOLD 2 ABSORBING", (880, 620), (700, 760))
    label(d, "CAGE UNDEFORMED", (560, 470), (380, 300))
    return finish(img, 5206, 0.28)


def cr_b6_staging():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    _axis(d, 240, 560, 1180, 820)
    for k, (x, col) in enumerate([(380, RUST), (560, RUST), (740, AMBER), (1010, STEEL)]):
        d.ellipse((x - 16, 540 - 16, x + 16, 540 + 16), fill=col + (240,))
        d.line((x, 556, x, 760), fill=col + (150,), width=4)
    d.ellipse((940, 330, 1120, 470), outline=STEEL + (240,), width=8)
    d.ellipse((990, 370, 1070, 430), fill=STEEL + (120,))
    label(d, "FOLD STAGES", (380, 800), (300, 880))
    label(d, "BELT PRETENSION", (740, 800), (560, 880))
    label(d, "AIRBAG BLOOM ~30-50 MS", (1030, 500), (760, 400))
    label(d, "ONE CRASH PULSE — EVERYTHING IN SLOT", (700, 300), (430, 240))
    return finish(img, 5207, 0.28)


def cr_b7_payoff():
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    d.line((768, 200, 768, 950), fill=CREAM + (110,), width=4)
    _car(d, 660, 560, crumple=0.9)
    _car(d, 940, 560, scale=0.62, crumple=0.0, cage=True, occupant=True)
    label(d, "THE DENT: ENERGY SPENT ON METAL", (640, 780), (380, 860))
    label(d, "THE CAGE: ENERGY NEVER REACHED YOU", (960, 460), (820, 300))
    return finish(img, 5208, 0.28)


def synth_sfx_pack(audio_dir):
    import wave
    import numpy as np
    SR = 44100
    rng = np.random.default_rng(5200)

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
    fr = np.fft.rfftfreq(n, 1 / SR); spec[(fr < 400) | (fr > 3200)] = 0
    _write(audio_dir / "sfx_whoosh.wav",
           np.stack([_norm(np.fft.irfft(spec, n) * env, 0.045)] * 2, 1))
    n = int(SR * 0.12); t = np.arange(n) / SR
    tick = np.sin(2 * math.pi * 2100 * t) * np.exp(-t * 55)
    _write(audio_dir / "sfx_tick.wav", np.stack([_norm(tick, 0.04)] * 2, 1))
    n = int(SR * 0.5); t = np.arange(n) / SR
    thud = np.sin(2 * math.pi * (54 - 36 * t / 0.5) * t) * np.exp(-t * 9)
    _write(audio_dir / "sfx_pulse.wav", np.stack([_norm(thud, 0.05)] * 2, 1))
    print("  sfx pack: whoosh/tick/pulse")


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "CR_B1_hook": cr_b1_hook(),
        "CR_B2_cage": cr_b2_cage(),
        "CR_B3_patent": cr_b3_patent(),
        "CR_B4_pulse": cr_b4_pulse(),
        "CR_B5_folds": cr_b5_folds(),
        "CR_B6_staging": cr_b6_staging(),
        "CR_B7_payoff": cr_b7_payoff(),
    }
    from engine import bible as B
    bible = B.load_bible(STORY)
    scores = [save_plate(img, name, bible) for name, img in plates.items()]
    d_scores = []
    for name in ("CR_B2_cage", "CR_B3_patent", "CR_B4_pulse",
                 "CR_B5_folds", "CR_B6_staging"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([(n, "diagram") for n in
                    ("CR_B2_cage", "CR_B3_patent", "CR_B4_pulse",
                     "CR_B5_folds", "CR_B6_staging")])
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
