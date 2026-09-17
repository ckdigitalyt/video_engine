"""microwave_dielectric — deterministic plates + SFX pack.

Mechanism story: how a microwave oven really heats — dielectric heating at
the outer shell, limited penetration, conduction inward, hot spots averaged
by the turntable. All art Pillow-drawn (no image-model calls, no network).

V12 Stage 3 — KIT ART DIRECTION: the plan declares grammar `mechanism_flow`
(background edge_to_edge_dark, panel_usage none, chrome_density minimal), so
plates are painted on the kit's dark field via _v12_kitlib — NO parchment,
NO grid paper, NO baked header/footer chrome. Labels stay inside the
V10-visible band (x 350..1190).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import ASSETS, W, H, arrow, big_number, finish_plate, \
    inter, label, register_diagram, save_plate, write_manifest
from _v12_kitlib import dark_field, finish, kit_background
from PIL import Image, ImageDraw

STORY = Path(__file__).resolve().parent

# kit palette (mirrors visual_bible.json)
AMBER = (224, 163, 60)     # field glow / heating
TEAL = (46, 140, 140)      # structure lines / water
RUST = (196, 80, 46)       # heat accents / leaders
CREAM = (240, 233, 218)
SLATE = (60, 62, 64)       # food block body (channel-neutral)
SLATE_D = (42, 43, 44)


# ------------------------------------------------------------ helpers ---

def food_block(d, x0, y0, x1, y1, core_glow=None):
    """The reheated food block: rounded slab, low-sat body, subtle top light."""
    d.rounded_rectangle((x0, y0, x1, y1), radius=26, fill=SLATE + (255,),
                        outline=(32, 33, 34, 255), width=5)
    d.rounded_rectangle((x0 + 10, y0 + 8, x1 - 10, y0 + 26), radius=12,
                        fill=(74, 84, 98, 120))
    if core_glow is not None:
        cx, cy, r, col, a = core_glow
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (a,))


def wave_arcs(d, cx, y0, y1, x_span, n=5, col=AMBER, a=200, w=7, right=True):
    """Field wave arcs wrapping the block edge (fade with distance)."""
    sgn = 1 if right else -1
    for k in range(n):
        rr = 70 + k * 46
        box = (cx - rr, y0, cx + rr, y0 + (y1 - y0))
        alpha = max(28, a - k * 34)
        d.arc(box, start=270 - sgn * 55, end=270 + sgn * 55,
              fill=col + (alpha,), width=w)


def molecule(d, x, y, r=17, flip=False, locked=False):
    """Water dipole: teal sphere with a dark O and two light H lobes."""
    d.ellipse((x - r, y - r, x + r, y + r), fill=TEAL + (235,),
              outline=(20, 40, 40, 255), width=3)
    hy = -r * 0.62 if not flip else r * 0.62
    for hx in (-r * 0.5, r * 0.5):
        d.ellipse((x + hx - 7, y + hy - 7, x + hx + 7, y + hy + 7),
                  fill=CREAM + (240,))
    if locked:
        d.rectangle((x - r - 6, y - 3, x + r + 6, y + 3),
                    fill=(94, 96, 98, 200))


def spark(d, x, y, r=8, col=RUST):
    d.line((x - r, y, x + r, y), fill=col + (230,), width=4)
    d.line((x, y - r, x, y + r), fill=col + (230,), width=4)


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(60 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def oven_outline(d, inset=64):
    d.rounded_rectangle((inset, inset, W - inset, H - inset), radius=40,
                        outline=TEAL + (90,), width=3)


# ---------------------------------------------------------------- plates ---

def mw_b1_hook():
    """HOOK / mechanism_mid_action — the shell glows, the core sits dark."""
    img = kit_background("edge_to_edge_dark", seed=3201)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 520, 380, AMBER)
    oven_outline(d)
    food_block(d, 560, 360, 976, 700)
    wave_arcs(d, 768, 340, 720, 420, n=5, right=True)
    wave_arcs(d, 768, 340, 720, 420, n=5, right=False)
    d.ellipse((738, 490, 798, 550), fill=(24, 25, 26, 255),
              outline=TEAL + (120,), width=3)
    label(d, "OUTER SHELL HEATING", (560, 380), (390, 260))
    label(d, "CORE STILL COLD", (768, 520), (1020, 760))
    label(d, "OVEN CAVITY", (110, 96), (420, 130))
    return finish(img, 3202, 0.28)


def mw_b2_myth():
    """CURIOSITY / flow_path_full_bleed — the popular picture: straight rays
    beaming through the food, bright core marked."""
    img = kit_background("edge_to_edge_dark", seed=3211)
    d = ImageDraw.Draw(img, "RGBA")
    food_block(d, 520, 360, 1016, 700)
    # dashed rays crossing the whole block
    for yy in (430, 530, 630):
        dash = 26
        x = 150
        while x < 1390:
            d.line((x, yy, x + dash, yy), fill=AMBER + (150,), width=6)
            x += dash * 2
    glow(d, 768, 530, 120, AMBER, layers=5)
    d.ellipse((738, 500, 798, 560), fill=AMBER + (235,),
              outline=(255, 240, 210, 160), width=3)
    label(d, "THE POPULAR PICTURE", (768, 380), (420, 250))
    label(d, "COOKED FROM THE INSIDE OUT?", (768, 530), (980, 780))
    return finish(img, 3212, 0.26)

def mw_b3_penetration():
    """REVEAL / cutaway_open — the cutaway: field glow dies over the first
    centimetres; conduction gradient reaches the cold core."""
    img = kit_background("edge_to_edge_dark", seed=3221)
    d = ImageDraw.Draw(img, "RGBA")
    food_block(d, 480, 340, 1100, 720)
    # cutaway window: the left face of the block opened
    d.rounded_rectangle((480, 340, 720, 720), radius=26,
                        fill=SLATE_D + (255,), outline=TEAL + (200,), width=4)
    # exponential field decay: bright band near the face fading inward
    for k in range(9):
        xx = 498 + k * 24
        a = max(12, 225 - k * 26)
        d.line((xx, 356, xx, 704), fill=AMBER + (a,), width=14)
    # conduction gradient toward the core
    for k in range(4):
        x0 = 720 + k * 70
        arrow(d, (x0, 530), (x0 + 62, 530), col=TEAL, w=6, head=18)
    d.ellipse((1000, 490, 1064, 554), fill=(24, 25, 26, 255),
              outline=TEAL + (130,), width=3)
    big_number(d, "a few cm", (768, 200), 84, col=AMBER)
    label(d, "FIELD FADES", (552, 430), (360, 260))
    label(d, "CONDUCTION CARRIES", (880, 530), (900, 620))
    label(d, "COLD CORE", (1032, 522), (1100, 340))
    return finish(img, 3222, 0.26)


def mw_b4_dielectric():
    """EXPLANATION / flow_path_full_bleed — dipoles torque with the swinging
    field; neighbours scrape the swing into heat."""
    img = kit_background("edge_to_edge_dark", seed=3231)
    d = ImageDraw.Draw(img, "RGBA")
    # swinging field axis across the frame
    arrow(d, (220, 300), (1320, 300), col=AMBER, w=9, head=30)
    arrow(d, (1320, 700), (220, 700), col=AMBER, w=9, head=30)
    for k in range(6):
        x = 330 + k * 190
        y = 500 + (26 if k % 2 else -26)
        molecule(d, x, y, flip=(k % 2 == 1))
        spark(d, x + 66, y + 40)
        spark(d, x + 100, y - 44)
    label(d, "FIELD SWINGS 2.45 GHz", (770, 300), (400, 210))
    label(d, "DIPOLES TORQUE", (520, 500), (350, 610))
    label(d, "HEAT", (1090, 460), (1140, 330))
    return finish(img, 3232, 0.26)


def mw_b5_frozen():
    """ESCALATION / consequence_spread — liquid flips freely; ice lattice is
    locked and dim."""
    img = kit_background("edge_to_edge_dark", seed=3241)
    d = ImageDraw.Draw(img, "RGBA")
    d.line((768, 150, 768, 900), fill=(76, 77, 78, 220), width=4)
    for k in range(3):
        molecule(d, 480 + (k % 2) * 120, 380 + k * 160, flip=(k % 2 == 0))
        spark(d, 560, 420 + k * 160)
    for row in range(3):
        for col in range(3):
            molecule(d, 1000 + col * 110, 380 + row * 160, locked=True)
    label(d, "LIQUID: FLIPS FREELY", (480, 500), (380, 200))
    label(d, "ICE: LOCKED LATTICE", (1110, 500), (1000, 200))
    label(d, "FROZEN FOOD SULKS", (768, 760), (600, 830))
    return finish(img, 3242, 0.26)


def mw_b6_hotspots():
    """ESCALATION / consequence_spread — hot-spot patchwork at the rim; the
    turntable swings the load through it."""
    img = kit_background("edge_to_edge_dark", seed=3251)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 380, 360, AMBER)
    food_block(d, 520, 240, 1016, 520)
    wave_arcs(d, 768, 220, 540, 420, n=4, right=True)
    wave_arcs(d, 768, 220, 540, 420, n=4, right=False)
    for (hx, hy, hr) in ((560, 280, 60), (980, 290, 56), (560, 480, 52),
                         (980, 470, 60), (768, 250, 48)):
        glow(d, hx, hy, hr, RUST, layers=4)
        d.ellipse((hx - 30, hy - 30, hx + 30, hy + 30), fill=RUST + (200,))
    d.ellipse((488, 600, 1048, 900), outline=TEAL + (200,), width=5)
    d.ellipse((758, 740, 778, 760), fill=TEAL + (230,))
    d.line((768, 750, 990, 700), fill=TEAL + (200,), width=4)
    d.rounded_rectangle((660, 640, 876, 730), radius=16, fill=SLATE + (255,),
                        outline=(32, 33, 34, 255), width=4)
    label(d, "HOT SPOTS", (980, 290), (1120, 170))
    label(d, "PATTERN SHIFTS WITH THE LOAD", (768, 750), (250, 930))
    label(d, "TURNTABLE AVERAGES", (768, 685), (960, 880))
    return finish(img, 3252, 0.26)


def mw_b7_payoff():
    """PAYOFF / mechanism_resolved — one even warm gradient, calm field."""
    img = kit_background("edge_to_edge_dark", seed=3261)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 768, 540, 340, AMBER)
    food_block(d, 520, 340, 1016, 720)
    for k in range(7):
        xx = 560 + k * 60
        a = max(36, 210 - k * 30)
        d.line((xx, 360, xx, 700), fill=AMBER + (a,), width=16)
    arrow(d, (860, 530), (700, 530), col=TEAL, w=7, head=20)
    label(d, "SHELL FIRST, THEN INWARD", (768, 340), (420, 230))
    label(d, "STIR, REST, EVEN", (768, 530), (950, 800))
    return finish(img, 3262, 0.24)


def synth_sfx_pack(audio_dir):
    """whoosh (draw-on stroke), tick (number pop), pulse (stakes landing)."""
    import numpy as np
    import wave
    SR = 44100
    rng = __import__("numpy").random.default_rng(4242)

    def _write(path, stereo):
        data = (__import__("numpy").clip(stereo, -1, 1) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(data.tobytes())

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
    _write(audio_dir / "sfx_whoosh.wav", __import__("numpy").stack([sig, sig], 1))

    n = int(SR * 0.12)
    t = np.arange(n) / SR
    tick = np.sin(2 * math.pi * 2100 * t) * np.exp(-t * 55)
    tick += 0.4 * np.sin(2 * math.pi * 3150 * t) * np.exp(-t * 70)
    tick = tick / (np.sqrt((tick ** 2).mean()) or 1e-9) * 0.04
    _write(audio_dir / "sfx_tick.wav", __import__("numpy").stack([tick, tick], 1))

    n = int(SR * 0.5)
    t = np.arange(n) / SR
    thud = np.sin(2 * math.pi * (58 - 40 * t / 0.5) * t) * np.exp(-t * 9)
    thud = thud / (np.sqrt((thud ** 2).mean()) or 1e-9) * 0.05
    _write(audio_dir / "sfx_pulse.wav", __import__("numpy").stack([thud, thud], 1))
    print("  sfx pack: whoosh/tick/pulse")


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "MW_B1_hook": mw_b1_hook(),
        "MW_B2_myth": mw_b2_myth(),
        "MW_B3_penetration": mw_b3_penetration(),
        "MW_B4_dielectric": mw_b4_dielectric(),
        "MW_B5_frozen": mw_b5_frozen(),
        "MW_B6_hotspots": mw_b6_hotspots(),
        "MW_B7_payoff": mw_b7_payoff(),
    }
    from engine import bible as B
    bible = B.load_bible(STORY)
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("MW_B2_myth", "MW_B3_penetration", "MW_B4_dielectric",
                 "MW_B5_frozen", "MW_B6_hotspots"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("MW_B2_myth", "diagram"),
                    ("MW_B3_penetration", "diagram"),
                    ("MW_B4_dielectric", "diagram"),
                    ("MW_B5_frozen", "diagram"),
                    ("MW_B6_hotspots", "diagram")])
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
