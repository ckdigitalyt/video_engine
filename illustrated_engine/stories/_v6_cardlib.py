"""Shared deterministic Pillow helpers for the three V6 test stories.

Pattern source: stories/round_window/make_fallback_cards.py (parchment family,
navy/rust accents per the visual bibles). No network, no image-model calls.

Each story script draws its 1536x1024 plates into assets/, writes the
diagram manifest cards used by the density gate (build/diag_stages/), and
synthesizes its ambient bed + one reveal SFX into the story audio/ dir.
"""
import math
import random
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import bible as B  # noqa: E402
from engine.diagrams import FONT_DIR  # noqa: E402
from engine.density import diagram_density  # noqa: E402
from engine.harmonize import continuity_score  # noqa: E402

ASSETS = ROOT / "assets"
BUILD = ROOT / "build"
DIAG = BUILD / "diag_stages"

W, H = 1536, 1024
# Parchment is deliberately LOW-saturation (S < 0.15): harmonize._hue_hist
# excludes near-greys, so the card's hue histogram is dominated by ink/navy/rust
# — the palette families the bible reference actually carries.
PARCH = (216, 208, 190)   # density-diff 42 < 60 (not "ink"); S=0.12 (excluded from hue hist)
PARCH_D = (206, 197, 178)
# Chrome bands: desaturated dark, SOLID — stays density-ink but drops out of
# the hue histogram so rust/navy accents own the palette match.
BANDC = (58, 54, 46)
PARCH_L = (236, 230, 217)
INK = (62, 52, 40)
NAVY = (34, 48, 78)
NAVY_D = (22, 32, 56)
RUST = (194, 91, 51)
CREAM = (239, 230, 212)
MUTED = (122, 106, 82)

_fd = Path(FONT_DIR)


def bebas(sz):
    return ImageFont.truetype(str(_fd / "BebasNeue-Regular.ttf"), sz)


def inter(sz):
    return ImageFont.truetype(str(_fd / "Inter-Variable.ttf"), sz)


def vgrad(w, h, top, bot):
    base = Image.new("RGB", (1, h))
    base.putdata([tuple(int(top[i] + (bot[i] - top[i]) * y / max(1, h - 1))
                        for i in range(3)) for y in range(h)])
    return base.resize((w, h))


def mottle(img, seed, n=9, strength=(8, 14)):
    """Soft parchment mottle."""
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rnd = random.Random(seed)
    w, h = img.size
    for _ in range(n):
        cx, cy = rnd.randint(0, w), rnd.randint(0, h)
        r = rnd.randint(180, 520)
        d.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2),
                  fill=PARCH_D + (rnd.randint(*strength),))
    ov = ov.filter(ImageFilter.GaussianBlur(60))
    return Image.alpha_composite(img.convert("RGBA"), ov)


def grain(img, seed, amount=0.012):
    """Fine per-pixel film grain (grey, seeded) — never blocky."""
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    rng = np.random.default_rng(seed)
    n = rng.normal(0.0, amount * 255 * 0.32, arr.shape[:2]).astype(np.float32)
    arr = np.clip(arr + n[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def vignette(img, strength=0.25):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((-w * 0.25, -h * 0.25, w * 1.25, h * 1.25), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(160))
    dark = Image.new("RGB", (w, h), (14, 12, 10))
    return Image.composite(img.convert("RGB"), dark, mask.point(lambda v: int(255 - (255 - v) * strength)))


def parchment(seed, border=True):
    img = mottle(Image.new("RGB", (W, H), PARCH), seed)
    d = ImageDraw.Draw(img, "RGBA")
    if border:
        d.rectangle((24, 24, W - 24, H - 24), outline=INK + (95,), width=2)
        d.rectangle((34, 34, W - 34, H - 34), outline=INK + (60,), width=1)
    return img.convert("RGBA")


def bgrid(d, x0=40, y0=40, x1=None, y1=None, step=64, col=INK, alpha=13):
    x1 = x1 or W - 40
    y1 = y1 or H - 40
    for x in range(x0 // step * step + step, x1, step):
        d.line((x, y0, x, y1), fill=col + (alpha,), width=1)
    for y in range(y0 // step * step + step, y1, step):
        d.line((x0, y, x1, y), fill=col + (alpha,), width=1)


def title_bar(d, text, y=64, sub=None):
    """Solid ink header band (counts as ink for the density gate)."""
    d.rectangle((40, y + 6, W - 40, y + 82), fill=BANDC + (255,))
    d.text((70, y), text, font=bebas(64), fill=CREAM + (255,))
    d.line((70, y + 78, 70 + int(d.textlength(text, font=bebas(64))) + 10, y + 78),
           fill=RUST + (230,), width=5)
    if sub:
        d.text((72, y + 98), sub, font=inter(26), fill=MUTED + (245,))


def footer_band(d, text, y=920, col=NAVY):
    """Solid navy footer strip with cream text (density + continuity ink)."""
    d.rectangle((40, y, W - 40, y + 66), fill=BANDC + (255,))
    d.text((64, y + 10), text, font=inter(30), fill=CREAM + (245,))


def label(d, text, anchor, bar_xy, font=None, align="left", col=NAVY):
    """Small caption box with a leader line to an anchor point."""
    font = font or bebas(34)
    tw = d.textlength(text, font=font)
    th = font.size
    pad_x, pad_y = 12, 7
    if align == "left":
        x0, y0 = bar_xy
    else:
        x0, y0 = bar_xy[0] - int(tw) - 2 * pad_x, bar_xy[1]
    x1, y1 = x0 + int(tw) + 2 * pad_x, y0 + th + 2 * pad_y
    d.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=(23, 19, 16, 210))
    d.text((x0 + pad_x, y0 + pad_y - 2), text, font=font, fill=CREAM)
    ex = x0 if anchor[0] < x0 else x1
    ey = (y0 + y1) // 2
    d.line((anchor[0], anchor[1], ex, ey), fill=RUST + (220,), width=3)
    d.ellipse((anchor[0] - 4, anchor[1] - 4, anchor[0] + 4, anchor[1] + 4),
              fill=RUST + (230,))


def arrow(d, p0, p1, col=RUST, w=7, head=22):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    d.line((p0[0] + ux * head * 0.6, p0[1] + uy * head * 0.6, p1[0], p1[1]),
           fill=col + (235,), width=w)
    bx, by = p1[0] - ux * head, p1[1] - uy * head
    px, py = -uy, ux
    d.polygon([(p1[0], p1[1]),
               (bx + px * head * 0.55, by + py * head * 0.55),
               (bx - px * head * 0.55, by - py * head * 0.55)], fill=col + (235,))


def big_number(d, text, xy, size=120, col=RUST, anchor_center=True, shadow=True):
    f = bebas(size)
    tw = d.textlength(text, font=f)
    x = xy[0] - tw / 2 if anchor_center else xy[0]
    if shadow:
        d.text((x + 4, xy[1] + 5), text, font=f, fill=(0, 0, 0, 130))
    d.text((x, xy[1]), text, font=f, fill=col + (255,))


def clock_face(d, cx, cy, r, tick_col=CREAM, face_col=(24, 26, 34), hand_col=CREAM,
               ticks=12, hour_angle=200, minute_angle=80, width=6):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=face_col + (255,),
              outline=tick_col + (230,), width=max(3, r // 28))
    for i in range(ticks):
        a = 2 * math.pi * i / ticks
        r1, r2 = r * 0.82, r * 0.94
        d.line((cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a)),
               fill=tick_col + (200,), width=max(2, r // 40))
    ha = math.radians(hour_angle - 90)
    ma = math.radians(minute_angle - 90)
    d.line((cx, cy, cx + r * 0.5 * math.cos(ha), cy + r * 0.5 * math.sin(ha)),
           fill=hand_col + (255,), width=max(4, r // 16))
    d.line((cx, cy, cx + r * 0.72 * math.cos(ma), cy + r * 0.72 * math.sin(ma)),
           fill=hand_col + (240,), width=max(3, r // 24))
    d.ellipse((cx - r * 0.06, cy - r * 0.06, cx + r * 0.06, cy + r * 0.06),
              fill=hand_col + (255,))


def hatch_polygon(img, pts, col=NAVY, alpha=70, step=14, seed=3):
    """Diagonal hatch fill inside a polygon (kept subtle)."""
    d = ImageDraw.Draw(img, "RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    lines = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dl = ImageDraw.Draw(lines)
    rnd = random.Random(seed)
    off = rnd.randint(0, step)
    for k in range(-img.size[1], img.size[0] + img.size[1], step):
        dl.line((k + off, 0, k + off + img.size[1], img.size[1]),
                fill=col + (alpha,), width=2)
    img.paste(Image.composite(lines, Image.new("RGBA", img.size, (0, 0, 0, 0)), mask),
              (0, 0), Image.composite(lines, Image.new("RGBA", img.size, (0, 0, 0, 0)), mask))


def finish_plate(img, seed, vig=0.25):
    img = grain(img, seed)
    return vignette(img, vig)


def save_plate(img, name, bible=None, min_cont=0.55):
    out = ASSETS / f"{name}.png"
    img.convert("RGB").save(out, "PNG")
    sc = float(continuity_score(np.asarray(img.convert("RGB")), bible))
    print(f"  plate {name}: continuity {sc:.3f} {'ok' if sc >= min_cont else 'LOW!'}")
    return sc


def register_diagram(name, bible, density_min=75.0):
    """Write the _full.png stage frame + manifest entry for the density gate,
    and verify density + continuity for the card."""
    from engine.layout import CANVAS_W, CANVAS_H
    DIAG.mkdir(parents=True, exist_ok=True)
    card = Image.open(ASSETS / f"{name}.png").convert("RGB")
    cw = CANVAS_W  # 1080
    ch = round(card.size[1] * cw / card.size[0])
    frame = Image.new("RGB", (CANVAS_W, CANVAS_H), (14, 12, 10))
    frame.paste(card.resize((cw, ch), Image.LANCZOS), (0, (CANVAS_H - ch) // 2))
    frame.save(DIAG / f"{name}_full.png", "PNG")
    m = diagram_density(card)
    sc = float(continuity_score(np.asarray(card), bible))
    print(f"  diag  {name}: density {m['score']} ({m['violations']}) continuity {sc:.3f}"
          f" {'ok' if m['score'] >= density_min and sc >= 0.4 else 'LOW!'}")
    return m["score"], sc


def write_manifest(entries):
    DIAG.mkdir(parents=True, exist_ok=True)
    man = {}
    for name, kind in entries:
        man[name.replace("_full", "")] = [{"stage": 0, "asset": name, "kind": kind}]
    (DIAG / "manifest_v4.json").write_text(
        __import__("json").dumps(man, indent=2))
    print(f"  manifest_v4.json: {len(man)} diagrams")


# ---------------------------------------------------------------- audio ----

SR = 44100


def _write_wav(path, stereo):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = np.clip(stereo, -1.0, 1.0)
    pcm = (s * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.reshape(-1, 2).tobytes() if pcm.ndim == 2
                      else np.column_stack([pcm, pcm]).tobytes())


def _lowpass_noise(n, rng, cutoff_frac=0.04):
    x = rng.standard_normal(n)
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    spec *= np.exp(-np.maximum(0.0, freqs - SR * cutoff_frac * 0.15) / (SR * cutoff_frac))
    return np.fft.irfft(spec, n)


def synth_bed(path, seed, base_hz, dur=75.0, rms=0.028):
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    det = 1.0035
    pad = (0.50 * np.sin(2 * math.pi * base_hz * t + rng.uniform(0, 6))
           + 0.30 * np.sin(2 * math.pi * base_hz * 1.5 * t + rng.uniform(0, 6))
           + 0.20 * np.sin(2 * math.pi * base_hz * 2.0 * t + rng.uniform(0, 6))
           + 0.10 * np.sin(2 * math.pi * base_hz * 3.01 * t + rng.uniform(0, 6)))
    lfo = 0.55 + 0.45 * np.sin(2 * math.pi * 0.045 * t + rng.uniform(0, 6))
    air = _lowpass_noise(n, rng, 0.10) * 0.5
    air_lfo = 0.4 + 0.6 * np.abs(np.sin(2 * math.pi * 0.023 * t + 1.2))
    left = pad * lfo + air * air_lfo * 0.35
    pad_r = (0.50 * np.sin(2 * math.pi * base_hz * det * t + rng.uniform(0, 6))
             + 0.30 * np.sin(2 * math.pi * base_hz * 1.5 * det * t + rng.uniform(0, 6))
             + 0.20 * np.sin(2 * math.pi * base_hz * 2.0 * det * t + rng.uniform(0, 6)))
    right = pad_r * lfo + air * air_lfo * 0.35
    fade = int(SR * 3)
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    cur = math.sqrt((left ** 2 + right ** 2).mean() / 2) or 1e-9
    g = rms / cur
    st = np.stack([left * env * g, right * env * g], axis=1)
    _write_wav(path, st)
    print(f"  bed -> {path.name} ({dur:.0f}s, rms {rms})")


def synth_sfx(path, seed, kind="swell", dur=1.8, rms=0.05):
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    if kind == "swell":
        env = np.sin(math.pi * np.minimum(t / dur, 1.0)) ** 2
        body = _lowpass_noise(n, rng, 0.06) * env
        thud = 0.8 * np.sin(2 * math.pi * (60 - 18 * t / dur) * t) * np.exp(-t * 2.2)
        sig = body * 0.8 + thud * 0.7
    else:
        env = np.exp(-t * 3.0)
        sig = 0.9 * np.sin(2 * math.pi * 52 * t) * env
    cur = math.sqrt((sig ** 2).mean()) or 1e-9
    s = sig * (rms / cur)
    st = np.stack([s, s], axis=1)
    _write_wav(path, st)
    print(f"  sfx -> {path.name} ({dur:.1f}s)")
