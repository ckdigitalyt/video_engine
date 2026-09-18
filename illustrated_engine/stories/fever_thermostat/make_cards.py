"""fever_thermostat — deterministic plates + SFX pack.

Biology story: how a fever actually works — the hypothalamic set point is
raised by prostaglandin E2, the body heats itself toward the new target,
then sheds the heat when the set point falls. All art Pillow-drawn.

V12 Stage 3 — KIT ART DIRECTION: grammar `cutaway_reveal` (background
edge_to_edge_dark with a blood-warm tint, panel_usage none, chrome_density
minimal). Plates painted via _v12_kitlib — NO parchment, NO grid paper, NO
baked header/footer chrome.
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

RUST = (196, 84, 66)       # tissue planes / heat
ROSE = (150, 96, 92)       # body fill
TEAL = (70, 150, 150)      # vessels / cool structure
AMBER = (224, 163, 60)     # heat glow
CREAM = (240, 233, 218)
DIAL_BG = (52, 34, 32)


def _kit():
    return kit_background("edge_to_edge_dark", seed=4101,
                          top=(38, 25, 25), bottom=(16, 11, 11),
                          mott=(28, 18, 18))


def dial(d, cx, cy, r, val, lo=36, hi=41):
    """Set-point gauge: arc from lo..hi, needle at val."""
    a0, a1 = 220, 500  # degrees in PIL arc space (left-down sweep)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=DIAL_BG + (255,),
              outline=CREAM + (200,), width=5)
    for i in range(5):
        ang = math.radians(a0 + (a1 - a0) * i / 4)
        x0, y0 = cx + (r - 12) * math.cos(ang), cy + (r - 12) * math.sin(ang)
        x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
        d.line((x0, y0, x1, y1), fill=CREAM + (170,), width=3)
    frac = (val - lo) / (hi - lo)
    ang = math.radians(a0 + (a1 - a0) * frac)
    d.line((cx, cy, cx + (r - 22) * math.cos(ang),
            cy + (r - 22) * math.sin(ang)), fill=AMBER + (255,), width=8)
    d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=AMBER + (255,))
    return val


def body_fig(d, x0, y0, x1, y1, core_glow=True, shiver=False, vessels=1.0,
             sweat=False):
    """Cutaway torso: outer skin plane, inner tissue, glowing core."""
    d.rounded_rectangle((x0, y0, x1, y1), radius=110, fill=ROSE + (150,),
                        outline=RUST + (255,), width=9)
    d.rounded_rectangle((x0 + 34, y0 + 34, x1 - 34, y1 - 34), radius=90,
                        outline=RUST + (160,), width=4)
    cx = (x0 + x1) // 2
    if core_glow:
        d.ellipse((cx - 95, y0 + 240, cx + 95, y0 + 430),
                  fill=AMBER + (120,))
        d.ellipse((cx - 60, y0 + 275, cx + 60, y0 + 395),
                  fill=(238, 180, 80, 160))
    if vessels < 1.0:
        w = max(2, int(8 * vessels))
        col = TEAL + (200,)
    else:
        w = 10
        col = TEAL + (230,)
    for yy in (y0 + 90, y0 + 180, y1 - 120, y1 - 220):
        d.line((x0 + 20, yy, x1 - 20, yy), fill=col, width=w)
    if shiver:
        for k in range(6):
            xx = x0 + 60 + k * ((x1 - x0 - 120) // 5)
            d.arc((xx - 22, y1 - 60, xx + 22, y1 + 10), start=200, end=340,
                  fill=CREAM + (190,), width=4)
    if sweat:
        for k in range(7):
            xx = x0 + 45 + k * ((x1 - x0 - 90) // 6)
            d.ellipse((xx - 7, y0 - 4, xx + 7, y0 + 10), fill=(170, 210, 220, 220))
            d.ellipse((xx - 5, y0 + 16, xx + 5, y0 + 28), fill=(170, 210, 220, 160))


def brain_head(d, cx, cy, hyp_col=AMBER, vessel=None):
    """Cutaway head profile with brain mass and lit hypothalamus dot."""
    d.ellipse((cx - 250, cy - 260, cx + 250, cy + 260), outline=RUST + (220,),
              width=7)
    d.polygon([(cx - 120, cy + 240), (cx - 120, cy + 400), (cx - 60, cy + 240)],
              outline=RUST + (140,), width=4)  # jaw hint
    d.ellipse((cx - 185, cy - 195, cx + 175, cy + 130), fill=ROSE + (130,),
              outline=RUST + (230,), width=5)
    for k in range(5):
        d.arc((cx - 150 + k * 14, cy - 160, cx + 130 - k * 10, cy + 95 - k * 8),
              start=110, end=330, fill=RUST + (200,), width=4)
    hx, hy = cx - 10, cy + 92
    d.ellipse((hx - 26, hy - 26, hx + 26, hy + 26), fill=hyp_col + (235,))
    if vessel is not None:
        d.line((cx + 320, cy + 40, hx + 24, hy), fill=TEAL + (200,), width=9)
        for (ox, oy) in vessel:
            d.ellipse((cx + ox - 8, cy + oy - 8, cx + ox + 8, cy + oy + 8),
                      fill=RUST + (235,))


def fv_b1_hook():
    """HOOK — burning hot inside, shivering at the skin."""
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    d.ellipse((250, 240, 1290, 900), fill=AMBER + (26,))
    body_fig(d, 560, 250, 980, 900, core_glow=True, shiver=True)
    big_number(d, "39°C", (330, 430), size=150, col=AMBER)
    label(d, "CORE BURNING HOT", (810, 480), (350, 300))
    label(d, "SKIN: SHIVERING, VESSELS CLAMPED", (620, 870), (900, 700))
    return finish(img, 4102, 0.28)


def fv_b2_thermostat():
    """CURIOSITY — the hypothalamus is the thermostat."""
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    brain_head(d, 700, 470)
    dial(d, 1130, 430, 120, 37)
    label(d, "HYPOTHALAMUS — THE BODY'S THERMOSTAT", (690, 560), (360, 300))
    label(d, "BASELINE SET POINT 36.5-37.5°C", (1130, 570), (860, 640))
    return finish(img, 4103, 0.28)


def fv_b3_reveal():
    """REVEAL — cytokines arrive; PGE2 turns the dial up."""
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    brain_head(d, 700, 470, vessel=[(300, 90), (262, 66), (228, 48)])
    dial(d, 1130, 430, 120, 39)
    label(d, "IMMUNE MESSENGERS (IL-1, IL-6, TNF)", (980, 520), (760, 780))
    label(d, "PGE2 RAISES THE SET POINT", (690, 560), (360, 300))
    big_number(d, "+1-2°C", (1120, 250), size=110, col=RUST)
    return finish(img, 4104, 0.28)


def fv_b4_climb():
    """EXPLANATION — vasoconstriction + shivering climb to the target."""
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    body_fig(d, 480, 260, 900, 900, core_glow=True, shiver=True, vessels=0.3)
    for k in range(3):
        arrow(d, (300, 430 + k * 120), (500, 480 + k * 120),
              col=AMBER, w=8)
    dial(d, 1130, 430, 120, 39)
    label(d, "SKIN VESSELS CLAMPED", (500, 690), (350, 860))
    label(d, "SHIVERING: MUSCLES MAKE HEAT", (620, 880), (880, 950))
    label(d, "HEAT RUSHES TO THE CORE", (390, 500), (350, 380))
    return finish(img, 4105, 0.28)


def fv_b5_defense():
    """ESCALATION — what the heat buys: slow pathogens, brisk immune cells."""
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    d.line((768, 220, 768, 920), fill=CREAM + (90,), width=4)
    for k in range(3):  # sluggish pathogen chain (left)
        d.ellipse((360 + k * 90, 520, 428 + k * 90, 588),
                  outline=RUST + (230,), width=6)
    d.line((330, 554, 610, 554), fill=RUST + (200,), width=5)
    d.ellipse((860, 470, 1000, 610), fill=RUST + (90,),
              outline=RUST + (230,), width=6)  # immune cell
    d.ellipse((900, 510, 960, 570), fill=AMBER + (190,))
    for k in range(8):
        ang = math.radians(k * 45)
        d.line((930 + 70 * math.cos(ang), 540 + 70 * math.sin(ang),
                930 + 105 * math.cos(ang), 540 + 105 * math.sin(ang)),
               fill=RUST + (240,), width=6)
    label(d, "PATHOGENS REPLICATE SLOWER", (470, 620), (360, 700))
    label(d, "IMMUNE CELLS WORK FASTER", (930, 560), (820, 700))
    label(d, "VERY HIGH FEVERS HARM — BALANCE DEBATED", (540, 320), (520, 250))
    return finish(img, 4106, 0.28)


def fv_b6_break():
    """ESCALATION — set point falls: flush and sweat."""
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    body_fig(d, 480, 300, 900, 900, core_glow=False, vessels=1.6, sweat=True)
    dial(d, 1130, 430, 120, 37)
    label(d, "SET POINT BACK DOWN", (1130, 570), (830, 640))
    label(d, "VESSELS OPEN — FLUSHED SKIN", (500, 690), (350, 830))
    label(d, "SWEAT EVAPORATES: HEAT OUT", (620, 320), (520, 250))
    return finish(img, 4107, 0.28)


def fv_b7_payoff():
    """PAYOFF — the loop resolved: chills were the ramp, sweat the descent."""
    img = _kit(); d = ImageDraw.Draw(img, "RGBA")
    body_fig(d, 540, 300, 940, 880, core_glow=True, vessels=1.0)
    dial(d, 1120, 430, 110, 37)
    arrow(d, (350, 700), (350, 540), col=AMBER, w=7)
    arrow(d, (1190, 540), (1190, 700), col=TEAL, w=7)
    label(d, "CHILLS = THE CLIMB", (350, 760), (350, 800))
    label(d, "SWEAT = THE DESCENT", (1190, 780), (860, 820))
    label(d, "ONE REGULATED SYSTEM, AIMED ON PURPOSE", (740, 460), (400, 300))
    return finish(img, 4108, 0.28)


def synth_sfx_pack(audio_dir):
    import wave
    import numpy as np
    SR = 44100
    rng = np.random.default_rng(3700)

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
    fr = np.fft.rfftfreq(n, 1 / SR); spec[(fr < 500) | (fr > 3800)] = 0
    _write(audio_dir / "sfx_whoosh.wav",
           np.stack([_norm(np.fft.irfft(spec, n) * env, 0.045)] * 2, 1))
    n = int(SR * 0.12); t = np.arange(n) / SR
    tick = np.sin(2 * math.pi * 1900 * t) * np.exp(-t * 55)
    _write(audio_dir / "sfx_tick.wav",
           np.stack([_norm(tick, 0.04)] * 2, 1))
    n = int(SR * 0.5); t = np.arange(n) / SR
    thud = np.sin(2 * math.pi * (60 - 40 * t / 0.5) * t) * np.exp(-t * 9)
    _write(audio_dir / "sfx_pulse.wav",
           np.stack([_norm(thud, 0.05)] * 2, 1))
    print("  sfx pack: whoosh/tick/pulse")


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "FV_B1_hook": fv_b1_hook(),
        "FV_B2_thermostat": fv_b2_thermostat(),
        "FV_B3_reveal": fv_b3_reveal(),
        "FV_B4_climb": fv_b4_climb(),
        "FV_B5_defense": fv_b5_defense(),
        "FV_B6_break": fv_b6_break(),
        "FV_B7_payoff": fv_b7_payoff(),
    }
    from engine import bible as B
    bible = B.load_bible(STORY)
    scores = [save_plate(img, name, bible) for name, img in plates.items()]
    d_scores = []
    for name in ("FV_B2_thermostat", "FV_B3_reveal", "FV_B4_climb",
                 "FV_B5_defense", "FV_B6_break"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([(n, "diagram") for n in
                    ("FV_B2_thermostat", "FV_B3_reveal", "FV_B4_climb",
                     "FV_B5_defense", "FV_B6_break")])
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
