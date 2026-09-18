"""atacama_fog_oases — deterministic plates + SFX pack.

Geography story: the Atacama fog oases — driest nonpolar desert, the two
blocked moisture sources, the lomas ridgeline reveal, the camanchaca fog
deck under its warm lid, mesh harvest yields, village arrays and the
Mars-analog core, the resolved sideways-water map.

V12 Stage 3 — KIT ART DIRECTION: the plan declares grammar `map_first`
(background terrain_field, panel_usage none, chrome_density minimal),
so plates are painted on the kit's desaturated map paper via
_v12_kitlib — NO parchment border, NO grid paper, NO baked chrome.
Anchor chips live in the art as content. Labels stay inside x 350..1190.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from _v6_cardlib import ASSETS, W, H, label, register_diagram, \
    save_plate, write_manifest
from _v12_kitlib import finish, kit_background

STORY = Path(__file__).resolve().parent
SLUG = "atacama_fog_oases"

INK = (40, 36, 28)
CREAM = (237, 228, 206)
RUST = (176, 74, 40)
OLIVE = (140, 110, 60)
OCEAN = (26, 26, 26)
FOG = (205, 198, 182)
TAN = (122, 96, 64)
GROUND = (190, 140, 96)
CURRENT = (150, 130, 105)
DROP = (170, 160, 140)


def anchor_chip(d, text, x, y):
    """Anchor chip: small map-legend chip — content, not chrome."""
    from _v6_cardlib import bebas
    f = bebas(40)
    tw = math.ceil(d.textlength(text, font=f))
    d.rounded_rectangle((x - 14, y - 8, x + tw + 14, y + 52), radius=8,
                        fill=INK + (235,), outline=RUST + (220,), width=3)
    d.text((x, y - 2), text, font=f, fill=CREAM + (250,))


def coastline(d, x=430, y0=120, y1=930, wig=26, seg=34):
    pts = [(x + (wig if (i // 2) % 2 else -wig) // 2, y0 + i * seg)
           for i in range((y1 - y0) // seg + 1)]
    d.line(pts, fill=INK + (210,), width=7)
    d.polygon([(0, y0)] + [(p[0], p[1]) for p in pts] +
              [(0, y1)], fill=OCEAN + (255,))


def ridgelines(d, x0, x1, y, n=3, amp=34):
    for k in range(n):
        pts = []
        for i in range(0, x1 - x0, 26):
            yy = y + k * 26 - amp * abs(math.sin((i / 210) + k * 1.3))
            pts.append((x0 + i, yy))
        d.line(pts, fill=TAN + (180 - k * 30,), width=4)


def fog_banks(d, x_edge, n=6, seed=7):
    from PIL import ImageFilter
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(ov)
    for i in range(n):
        cx = x_edge - 60 - i * 70
        cy = 260 + ((i * 173) % 420)
        r = 150 + ((i * 97) % 130)
        dd.ellipse((cx - r, cy - r // 3, cx + r, cy + r // 3),
                   fill=FOG + (26 + (i % 3) * 7,))
    ov = ov.filter(ImageFilter.GaussianBlur(46))
    return Image.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 0)), ov)


def ribbon(d, x0, y, n=9, step=26):
    for i in range(n):
        x = x0 + i * step
        yy = y + int(10 * math.sin(i * 0.9))
        d.line((x, yy, x + 14, yy), fill=OLIVE + (230,), width=7)
        d.line((x + 2, yy + 9, x + 10, yy + 9), fill=OLIVE + (150,), width=4)


def mesh_panel(d, x0, y0, w, h):
    d.rectangle((x0, y0, x0 + w, y0 + h), outline=INK + (230,), width=6)
    for gx in range(1, 7):
        d.line((x0 + gx * w // 7, y0, x0 + gx * w // 7, y0 + h),
               fill=INK + (120,), width=3)
    for gy in range(1, 7):
        d.line((x0, y0 + gy * h // 7, x0 + w, y0 + gy * h // 7),
               fill=INK + (120,), width=3)


def tank(d, x, y, w=120, h=90):
    d.rounded_rectangle((x, y, x + w, y + h), radius=10,
                        outline=INK + (230,), width=6, fill=(96, 88, 70, 160))


def droplet_run(d, x, y0, y1, n=5, col=DROP):
    for i in range(n):
        yy = y0 + (y1 - y0) * i // max(n - 1, 1)
        r = 8
        d.ellipse((x - r, yy - r, x + r, yy + r), fill=col + (220,))


def arrow_sideways(d, x0, y, x1, col=RUST, w=9):
    d.line((x0, y, x1 - 26, y), fill=col + (220,), width=w)
    d.polygon([(x1, y), (x1 - 30, y - 16), (x1 - 30, y + 16)], fill=col + (230,))


def glow(d, cx, cy, r, col=RUST, layers=5):
    for i in range(layers):
        rr = r * (1 - i / layers)
        d.ellipse((cx - rr, cy - rr * 0.62, cx + rr, cy + rr * 0.62),
                  fill=col + (26,))


def af_b1_hook():
    img = kit_background("terrain_field", seed=5201, base_col=GROUND)
    d = ImageDraw.Draw(img, "RGBA")
    coastline(d, x=470)
    ridgelines(d, 560, 1330, 520)
    d.ellipse((640, 430, 700, 470), fill=OLIVE + (0,))
    ribbon(d, 620, 470)
    ribbon(d, 980, 520, n=7)
    img = Image.alpha_composite(img, fog_banks(d, 520, n=6, seed=11))
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 700, 480, 150, RUST)
    anchor_chip(d, "THE ATACAMA", 380, 130)
    label(d, "SECRET GARDENS — NO RAIN", (640, 700), (560, 760), col=INK)
    label(d, "FOG CREEPS IN FROM THE PACIFIC", (700, 850), (620, 910), col=INK)
    return finish(img, 5202, 0.3)


def af_b2_dry():
    img = kit_background("terrain_field", seed=5211, base_col=GROUND)
    d = ImageDraw.Draw(img, "RGBA")
    coastline(d, x=500)
    ridgelines(d, 600, 1380, 500)
    # east: Andes wall blocks Amazon moisture
    d.polygon([(1300, 180), (1440, 560), (1300, 940)], fill=TAN + (170,))
    arrow_sideways(d, 1360, 360, 1180, col=RUST)
    d.line((1160, 320, 1160, 400), fill=RUST + (230,), width=10)
    # west: cold current kills rain
    d.line((300, 700, 470, 700), fill=CURRENT + (150,), width=8)
    anchor_chip(d, "< 1 MM / YEAR", 620, 130)
    label(d, "ANDES BLOCKS THE EAST", (700, 380), (620, 440), col=INK)
    label(d, "COLD CURRENT KILLS RAIN", (700, 780), (620, 840), col=INK)
    return finish(img, 5212, 0.3)


def af_b3_lomas():
    img = kit_background("terrain_field", seed=5221, base_col=GROUND)
    d = ImageDraw.Draw(img, "RGBA")
    coastline(d, x=430)
    ridgelines(d, 540, 1360, 500)
    ribbon(d, 560, 440)
    ribbon(d, 830, 500, n=11)
    ribbon(d, 1120, 420, n=8)
    img = Image.alpha_composite(img, fog_banks(d, 470, n=5, seed=23))
    d = ImageDraw.Draw(img, "RGBA")
    anchor_chip(d, "300–1000 M", 380, 130)
    label(d, "BONE DRY —", (760, 250), (680, 310), col=INK)
    label(d, "— EXCEPT HERE", (700, 620), (620, 680), col=INK)
    return finish(img, 5222, 0.3)


def af_b4_fogdeck():
    img = kit_background("terrain_field", seed=5231, base_col=GROUND)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((90, 690, 1446, 700), fill=INK + (210,), width=0)
    d.rectangle((90, 700, 1446, 930), fill=OCEAN + (255,))
    d.line((90, 700, 1446, 700), fill=CURRENT + (170,), width=8)
    # warm lid
    d.line((90, 330, 1446, 330), fill=RUST + (220,), width=9)
    # fog deck between lid and ocean
    img = Image.alpha_composite(img, fog_banks(d, 90, n=9, seed=31))
    d = ImageDraw.Draw(img, "RGBA")
    # ridge spears through the deck
    d.polygon([(980, 930), (1060, 240), (1140, 930)], fill=TAN + (220,))
    d.line((980, 930, 1060, 240, 1140, 930), fill=INK + (220,), width=6)
    ribbon(d, 1000, 420, n=4, step=20)
    for i in range(5):
        droplet_run(d, 1005 + i * 22, 300, 400, n=3)
    anchor_chip(d, "CAMANCHACA", 380, 130)
    label(d, "WARM LID", (420, 250), (360, 300), col=INK)
    label(d, "FOG DECK", (430, 560), (360, 620), col=INK)
    label(d, "RIDGE PIERCES THE DECK", (760, 180), (680, 240), col=INK)
    return finish(img, 5232, 0.3)


def af_b5_mesh():
    img = kit_background("terrain_field", seed=5241, base_col=GROUND)
    d = ImageDraw.Draw(img, "RGBA")
    mesh_panel(d, 380, 260, 420, 460)
    for i in range(6):
        droplet_run(d, 430 + i * 60, 730, 800, n=4)
    tank(d, 560, 810, w=180, h=110)
    # the leaf that invented it
    d.ellipse((980, 340, 1220, 560), outline=OLIVE + (230,), width=8)
    d.line((1100, 560, 1100, 700), fill=OLIVE + (200,), width=8)
    droplet_run(d, 1100, 700, 820, n=4)
    anchor_chip(d, "2–5 L / M² / DAY", 560, 130)
    label(d, "MESH NET", (430, 210), (370, 260), col=INK)
    label(d, "THE LEAF INVENTED IT FIRST", (860, 620), (760, 680), col=INK)
    return finish(img, 5242, 0.3)


def af_b6_arrays():
    img = kit_background("terrain_field", seed=5251, base_col=GROUND)
    d = ImageDraw.Draw(img, "RGBA")
    for k in range(3):
        mesh_panel(d, 300 + k * 130, 300, 100, 330)
        droplet_run(d, 350 + k * 130, 640, 760, n=3)
    tank(d, 760, 700, w=200, h=120)
    d.line((960, 760, 1180, 760), fill=INK + (200,), width=7)
    # Mars-analog pin on the core
    glow(d, 1180, 420, 90, RUST)
    d.ellipse((1162, 402, 1198, 438), fill=RUST + (240,))
    anchor_chip(d, "HUNDREDS OF LITRES / DAY", 420, 130)
    label(d, "MESH WALLS", (330, 250), (280, 300), col=INK)
    label(d, "YUNGAY: MARS ANALOG", (760, 480), (680, 540), col=INK)
    return finish(img, 5252, 0.3)


def af_b7_payoff():
    img = kit_background("terrain_field", seed=5261, base_col=GROUND)
    d = ImageDraw.Draw(img, "RGBA")
    coastline(d, x=400)
    ridgelines(d, 520, 1340, 500)
    ribbon(d, 540, 450)
    ribbon(d, 820, 520, n=10)
    ribbon(d, 1100, 430, n=8)
    for k in range(3):
        arrow_sideways(d, 240, 360 + k * 130, 560 + k * 60, col=RUST)
    img = Image.alpha_composite(img, fog_banks(d, 460, n=5, seed=41))
    d = ImageDraw.Draw(img, "RGBA")
    anchor_chip(d, "RESOLVED", 380, 130)
    label(d, "RAIN NEVER COMES", (640, 250), (560, 310), col=INK)
    label(d, "FOG IS THE WATER", (700, 700), (620, 760), col=INK)
    return finish(img, 5262, 0.3)


def synth_sfx_pack(audio_dir):
    import wave
    import numpy as np
    SR = 44100
    rng = np.random.default_rng(5201)

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


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "AF_B1_hook": af_b1_hook(),
        "AF_B2_dry": af_b2_dry(),
        "AF_B3_lomas": af_b3_lomas(),
        "AF_B4_fogdeck": af_b4_fogdeck(),
        "AF_B5_mesh": af_b5_mesh(),
        "AF_B6_arrays": af_b6_arrays(),
        "AF_B7_payoff": af_b7_payoff(),
    }
    from engine import bible as B
    bible = B.load_bible(STORY)
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("AF_B4_fogdeck", "AF_B5_mesh"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("AF_B4_fogdeck", "diagram"),
                    ("AF_B5_mesh", "diagram")])
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
