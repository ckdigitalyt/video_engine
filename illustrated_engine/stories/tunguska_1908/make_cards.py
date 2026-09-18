"""tunguska_1908 — deterministic plates + SFX pack.

History story: the 1908 Tunguska airburst — eyewitness record, global
signals, Kulik's 1927 no-crater reveal, the hedged airburst model, the
2013 Chelyabinsk confirmation, the resolved signature.

V12 Stage 3 — KIT ART DIRECTION: the plan declares grammar `timeline_band`
(background era_field, panel_usage none, chrome_density none, top_band
captions), so plates are painted on the kit's darkened archival paper via
_v12_kitlib — NO parchment, NO grid paper, NO baked header/footer chrome.
Date anchors live in the art as content. Labels stay inside x 350..1190.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import ASSETS, W, H, arrow, label, register_diagram, \
    save_plate, write_manifest
from _v12_kitlib import era_field, finish, kit_background
from PIL import Image, ImageDraw

STORY = Path(__file__).resolve().parent

SEPIA = (138, 102, 66)    # primary ink wash
INK = (62, 54, 42)        # dark linework / silhouettes
RUST = (176, 74, 40)      # event accent
CREAM = (237, 228, 206)   # light (fireball, text highlights)
MUT = (122, 106, 82)


# ------------------------------------------------------------ helpers -----

def treeline(d, y, x0=120, x1=1416, col=INK, h=90):
    """Taiga silhouette: jagged conifer line along y."""
    import random as _r
    rnd = _r.Random(1908)
    x = x0
    while x < x1:
        th = rnd.randint(int(h * 0.55), h)
        hw = th * 0.3
        d.polygon([(x, y), (x + hw, y - th), (x + 2 * hw, y)], fill=col + (255,))
        x += int(hw * 1.4)


def cabin(d, x, y, w=120, h=80):
    d.rectangle((x, y - h, x + w, y), fill=INK + (255,))
    d.polygon([(x - 10, y - h), (x + w / 2, y - h - 34), (x + w + 10, y - h)],
              fill=SEPIA + (255,))
    d.rectangle((x + w * 0.32, y - h * 0.5, x + w * 0.46, y),
                fill=SEPIA + (220,))


def figure(d, x, y, s=26, lying=False):
    """Tiny abstract silhouette (no faces, no detail)."""
    if lying:
        d.line((x - s, y, x + s, y - 6), fill=INK + (255,), width=9)
        d.ellipse((x + s, y - 14, x + s + 12, y - 2), fill=INK + (255,))
    else:
        d.ellipse((x - 6, y - s - 8, x + 6, y - s + 4), fill=INK + (255,))
        d.line((x, y - s + 4, x, y - 4), fill=INK + (255,), width=7)
        d.line((x - 10, y - 8, x + 10, y - 8), fill=INK + (255,), width=5)


def streak(d, x0, y0, x1, y1, w=18, col=CREAM):
    """Fireball trail: bright core + sepia wash + rust rim."""
    import math as _m
    dx, dy = x1 - x0, y1 - y0
    L = _m.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    for k in range(5):
        t0, t1 = k * 0.16, k * 0.16 + 0.2
        a = 255 - k * 48
        d.line((x0 + dx * t0, y0 + dy * t0, x0 + dx * t1, y0 + dy * t1),
               fill=col + (a,), width=w - k * 3)
    d.line((x1 - ux * 40, y1 - uy * 40, x1, y1), fill=RUST + (255,), width=w + 4)
    d.ellipse((x1 - 26, y1 - 26, x1 + 26, y1 + 26), fill=CREAM + (255,))
    d.ellipse((x1 - 44, y1 - 44, x1 + 44, y1 + 44), fill=CREAM + (60,))


def anchor_chip(d, text, x, y):
    """Date anchor: small sepia chip — content, not chrome."""
    import math as _m
    from _v6_cardlib import bebas
    f = bebas(40)
    tw = _m.ceil(d.textlength(text, font=f))
    d.rounded_rectangle((x - 14, y - 8, x + tw + 14, y + 52), radius=8,
                        fill=INK + (235,), outline=RUST + (220,), width=3)
    d.text((x, y - 2), text, font=f, fill=CREAM + (250,))


def flash(d, cx, cy, r, col=CREAM):
    import math as _m
    for k in range(10):
        a0 = k * _m.pi / 5
        x1 = cx + r * _m.cos(a0)
        y1 = cy + r * _m.sin(a0)
        d.line((cx, cy, x1, y1), fill=col + (200 - k * 12,), width=8)


def radial_fan(d, cx, cy, r_in=90, r_out=460, n=26):
    """The blowdown: trunks laid radially outward from the centre."""
    import math as _m
    for k in range(n):
        a = 2 * _m.pi * k / n + 0.11
        x0, y0 = cx + r_in * _m.cos(a), cy + r_in * _m.sin(a)
        x1, y1 = cx + r_out * _m.cos(a), cy + r_out * _m.sin(a)
        d.line((x0, y0, x1, y1), fill=SEPIA + (255,), width=10)
        d.line((x0, y0, x0 + (x1 - x0) * 0.3, y0 + (y1 - y0) * 0.3),
               fill=INK + (200,), width=4)
        d.ellipse((x1 - 9, y1 - 9, x1 + 9, y1 + 9), fill=INK + (255,))


def standing_poles(d, cx, cy, n=7, spread=64):
    """Ground zero: upright stripped trees, still standing."""
    for k in range(n):
        x = cx - spread + k * (2 * spread / max(n - 1, 1))
        hh = 66 + (k % 3) * 22
        d.line((x, cy - 8, x, cy - 8 - hh), fill=INK + (255,), width=9)
        d.line((x - 7, cy - 16 - hh * 0.4, x + 7, cy - 16 - hh * 0.4),
               fill=INK + (190,), width=4)


def ground_line(d, y, x0=140, x1=1396):
    d.line((x0, y, x1, y), fill=INK + (255,), width=6)


def skyline(d, y, x0=180, x1=1356):
    import random as _r
    rnd = _r.Random(2013)
    x = x0
    while x < x1:
        bw = rnd.randint(70, 150)
        bh = rnd.randint(120, 300)
        d.rectangle((x, y - bh, x + bw, y), fill=INK + (255,))
        for wx in range(x + 14, x + bw - 14, 30):
            d.line((wx, y - bh + 16, wx, y - 16), fill=SEPIA + (140,), width=3)
        x += bw + 26


# ---------------------------------------------------------------- plates ---

def tu_b1_hook():
    img = kit_background("era_field", seed=4101)
    d = ImageDraw.Draw(img, "RGBA")
    # morning glow band above the horizon
    d.rectangle((120, 560, 1416, 780), fill=SEPIA + (70,))
    d.line((120, 780, 1416, 780), fill=INK + (255,), width=6)
    treeline(d, 780)
    treeline(d, 830, h=70)
    streak(d, 980, 190, 640, 560)
    anchor_chip(d, "30 JUNE 1908", 420, 130)
    label(d, "PODKAMENNAYA TUNGUSKA", (700, 900), (420, 940))
    return finish(img, 4102, 0.3)


def tu_b2_eyewitness():
    img = kit_background("era_field", seed=4111)
    d = ImageDraw.Draw(img, "RGBA")
    ground_line(d, 700)
    cabin(d, 380, 700)
    cabin(d, 900, 700, w=150, h=96)
    figure(d, 700, 700, lying=True)
    figure(d, 560, 700, lying=False)
    figure(d, 1120, 700, lying=True)
    # heat rays from the upper left
    for k in range(3):
        d.line((200 + k * 40, 220 + k * 60, 760 + k * 160, 620),
               fill=RUST + (210 - k * 40,), width=10 - k * 2)
    anchor_chip(d, "1908 — VANAVARA, 65 KM", 400, 120)
    label(d, "HEAT ON SKIN", (760, 600), (1020, 420))
    label(d, "THROWN FROM CHAIRS", (700, 700), (480, 830))
    return finish(img, 4112, 0.3)


def tu_b3_signals():
    img = kit_background("era_field", seed=4121)
    d = ImageDraw.Draw(img, "RGBA")
    # sky that will not darken: pale band up top
    d.rectangle((120, 120, 1416, 300), fill=CREAM + (90,))
    # concentric pressure rings
    for k in range(4):
        r = 130 + k * 110
        d.arc((768 - r, 620 - r, 768 + r, 620 + r), start=200, end=340,
              fill=SEPIA + (235 - k * 40,), width=7)
    # barograph drum
    d.rectangle((300, 600, 560, 700), fill=INK + (255,))
    d.arc((300, 560, 560, 700), start=180, end=360, fill=INK + (255,), width=6)
    d.line((560, 630, 560, 700), fill=INK + (255,), width=6)
    # trace with the anomalous spike
    pts = [(300, 660), (380, 650), (440, 662), (480, 560), (520, 668), (560, 655)]
    d.line(pts, fill=RUST + (255,), width=7)
    anchor_chip(d, "BAROGRAPH — ENGLAND", 330, 760)
    label(d, "PRESSURE WAVE", (900, 380), (1000, 240))
    label(d, "THE SKY STAYS BRIGHT", (768, 210), (860, 320))
    return finish(img, 4122, 0.3)


def tu_b4_kulik():
    img = kit_background("era_field", seed=4131)
    d = ImageDraw.Draw(img, "RGBA")
    ground_line(d, 560)
    radial_fan(d, 768, 560)
    standing_poles(d, 768, 560)
    anchor_chip(d, "1927 — KULIK REACHES THE SITE", 380, 120)
    label(d, "NO CRATER", (1030, 640), (1120, 480))
    label(d, "POLES STILL STANDING", (768, 470), (430, 320))
    return finish(img, 4132, 0.3)


def tu_b5_airburst():
    img = kit_background("era_field", seed=4141)
    d = ImageDraw.Draw(img, "RGBA")
    ground_line(d, 860)
    treeline(d, 860, h=60)
    # altitude scale (content, not chrome)
    for k, km in ((860, "0"), (640, "5"), (420, "10")):
        d.line((190, k, 250, k), fill=INK + (220,), width=4)
        d.text((200, k - 34), km, font=__import__("_v6_cardlib", fromlist=["bebas"]).bebas(34),
               fill=INK + (240,))
    # entry lane + burst at altitude
    streak(d, 1160, 140, 700, 520, w=16)
    flash(d, 700, 520, 120)
    # shock cones driving down
    for k in range(3):
        r = 150 + k * 120
        d.arc((700 - r, 520 - r // 2, 700 + r, 520 + r), start=40, end=140,
              fill=RUST + (215 - k * 45,), width=9)
    anchor_chip(d, "LEADING MODEL", 1050, 620)
    label(d, "BURST 5-10 KM UP", (700, 520), (940, 700))
    label(d, "BLAST WAVE, NOT A FRAGMENT", (820, 760), (400, 900))
    return finish(img, 4142, 0.3)


def tu_b6_chelyabinsk():
    img = kit_background("era_field", seed=4151)
    d = ImageDraw.Draw(img, "RGBA")
    skyline(d, 760)
    streak(d, 300, 200, 1050, 520, w=20)
    # shocked windows
    for wx in (420, 700, 980, 1230):
        d.line((wx, 640, wx + 26, 690), fill=RUST + (230,), width=6)
        d.line((wx + 26, 640, wx, 690), fill=RUST + (230,), width=6)
    anchor_chip(d, "2013 — CHELYABINSK", 420, 110)
    label(d, "MECHANISM CONFIRMED", (1050, 520), (1080, 620))
    return finish(img, 4152, 0.3)


def tu_b7_payoff():
    img = kit_background("era_field", seed=4161)
    d = ImageDraw.Draw(img, "RGBA")
    ground_line(d, 700)
    radial_fan(d, 768, 700, r_out=430, n=22)
    standing_poles(d, 768, 700)
    # calm sky: no streak, no flash
    d.rectangle((120, 120, 1416, 300), fill=CREAM + (60,))
    label(d, "THE AIRBURST SIGNATURE", (768, 470), (440, 300))
    label(d, "NO CRATER — BY DESIGN", (1030, 760), (1080, 840))
    return finish(img, 4162, 0.3)


def synth_sfx_pack(audio_dir):
    import wave
    import numpy as np
    SR = 44100
    rng = np.random.default_rng(1908)

    def _write(path, stereo):
        data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
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
    _write(audio_dir / "sfx_whoosh.wav", np.stack([sig, sig], 1))

    n = int(SR * 0.12)
    t = np.arange(n) / SR
    tick = np.sin(2 * math.pi * 2100 * t) * np.exp(-t * 55)
    tick += 0.4 * np.sin(2 * math.pi * 3150 * t) * np.exp(-t * 70)
    tick = tick / (np.sqrt((tick ** 2).mean()) or 1e-9) * 0.04
    _write(audio_dir / "sfx_tick.wav", np.stack([tick, tick], 1))

    n = int(SR * 0.5)
    t = np.arange(n) / SR
    thud = np.sin(2 * math.pi * (58 - 40 * t / 0.5) * t) * np.exp(-t * 9)
    thud = thud / (np.sqrt((thud ** 2).mean()) or 1e-9) * 0.05
    _write(audio_dir / "sfx_pulse.wav", np.stack([thud, thud], 1))
    print("  sfx pack: whoosh/tick/pulse")


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "TU_B1_hook": tu_b1_hook(),
        "TU_B2_eyewitness": tu_b2_eyewitness(),
        "TU_B3_signals": tu_b3_signals(),
        "TU_B4_kulik": tu_b4_kulik(),
        "TU_B5_airburst": tu_b5_airburst(),
        "TU_B6_chelyabinsk": tu_b6_chelyabinsk(),
        "TU_B7_payoff": tu_b7_payoff(),
    }
    from engine import bible as B
    bible = B.load_bible(STORY)
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("TU_B3_signals", "TU_B4_kulik", "TU_B5_airburst"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("TU_B3_signals", "diagram"),
                    ("TU_B4_kulik", "diagram"),
                    ("TU_B5_airburst", "diagram")])
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
