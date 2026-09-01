"""motion_toolkit.py — Subject-motion toolkit (directive §16).

Deterministic, parameterized motion primitives that turn continuous drift
(zoom/pan/particles — the r2 "animated slideshow" failure) into DISCRETE
perceptual events the renderers actually render:

  animals      run / fly / walk / head_turn / bite / roar / flock
               → silhouette/cutout layers sweeping the frame
  natural      smoke / fire / dust / water / rain / lightning / clouds
               → procedural particle/shape overlay layers
  camera       push / pull / orbit / pan / tilt / tracking / shake / whip
               → zoompan + crop-jitter parameter curves
  environment  wind / vegetation_sway / particles / haze
               → gentle overlay drift layers

Design contract (§16): every primitive is a pure function of
(seed, duration, fps, intensity) — identical inputs produce byte-identical
output — and composable/layerable over AI stills and backgrounds.

Renderer adapters (§4/§24 micro-event implementation):
  * AI_IMAGE_MOTION (ffmpeg)  → kenburns_ops(): fast brightness/zoom steps,
    crop-shake terms and pre-rendered overlay layers blended over the
    Ken Burns base (see engine/renderers/media/kenburns.py).
  * MOTION_CANVAS / PIXIJS    → cue dicts consumed by motion/render.mjs and
    pixi/render.mjs event layers (canvas/scene overlays, flashes, shakes).

Why FAST events matter (the phase-3 diagnosis): a brightness pulse of amp
A spread over w frames moves the mean frame delta by only ~A/w per frame —
an r2 pulse (amp 0.05, width 20) produced ~0.6 luma levels/frame, far below
the audit spike threshold (8.0) and even below the static threshold (0.7).
Real perceptual events must land within 1-4 frames: an exposure/grade step
of 0.05 = ~13 luma levels in one frame pair → a measurable spike, and an
honest "lighting change" event (directive §2 lists lighting change, object
enter/exit, impact, transformation as the events that SHOULD score).
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ── Kind vocabulary (§16) ────────────────────────────────────────────────────

ANIMAL_KINDS = ("run", "fly", "walk", "head_turn", "bite", "roar", "flock")
NATURAL_KINDS = ("smoke", "fire", "dust", "water", "rain", "lightning",
                 "clouds")
CAMERA_KINDS = ("push", "pull", "orbit", "pan", "tilt", "tracking", "shake",
                "whip")
ENVIRONMENT_KINDS = ("wind", "vegetation_sway", "particles", "haze")

ALL_KINDS = ANIMAL_KINDS + NATURAL_KINDS + CAMERA_KINDS + ENVIRONMENT_KINDS

# Overlay blend modes per primitive (how the layer composites over a base):
#   screen   — light-emitting (particles, rain glints, lightning, fire glow)
#   multiply — occluding dark shapes (animal silhouettes, smoke cores)
_BLEND = {
    "smoke": "screen", "fire": "screen", "dust": "screen", "water": "screen",
    "rain": "screen", "lightning": "screen", "clouds": "screen",
    "haze": "screen", "particles": "screen", "wind": "screen",
    "vegetation_sway": "multiply",
    "run": "multiply", "fly": "multiply", "walk": "multiply",
    "flock": "multiply", "head_turn": "multiply", "bite": "multiply",
    "roar": "multiply",
}

_OVERLAY_KINDS = frozenset(_BLEND)


def is_overlay_kind(kind: str) -> bool:
    return str(kind) in _OVERLAY_KINDS


# Overlay render resolution (small by design — numpy drawing; ffmpeg upscales
# at composite time; audit decodes at 192x108 anyway).
OVERLAY_W, OVERLAY_H = 480, 270


# ── Deterministic helpers ────────────────────────────────────────────────────

def _seed_of(*parts: object) -> np.random.Generator:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def _tri(n: np.ndarray, center: float, width: float) -> np.ndarray:
    """Triangular window 0..1 centered at *center* with half-width *width*."""
    return np.clip(1.0 - np.abs(n - center) / max(width, 1e-6), 0.0, 1.0)


# ── Primitive plans ──────────────────────────────────────────────────────────

@dataclass
class PrimitivePlan:
    """Resolved deterministic plan for one primitive."""
    kind: str
    category: str                 # animals | natural | camera | environment
    seed: int
    duration: float
    fps: int
    intensity: float
    blend: str | None = None      # overlay kinds: screen | multiply
    frames: int = 0
    # camera kinds: per-frame parameter curves (length == frames)
    curve: dict = field(default_factory=dict)
    # overlay kinds: renderer spec
    spec: dict = field(default_factory=dict)


def plan_primitive(kind: str, *, seed: int, duration: float, fps: int = 30,
                   intensity: float = 0.6) -> PrimitivePlan:
    """Deterministic plan for one §16 primitive.

    Same (kind, seed, duration, fps, intensity) → identical plan, always.
    """
    kind = str(kind)
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown motion primitive: {kind!r} "
                         f"(known: {ALL_KINDS})")
    frames = max(1, int(round(duration * fps)))
    rng = _seed_of(kind, seed, duration, intensity)
    inten = float(np.clip(intensity, 0.0, 1.0))

    if kind in CAMERA_KINDS:
        return _plan_camera(kind, frames, fps, inten, rng)
    return PrimitivePlan(
        kind=kind,
        category=("animals" if kind in ANIMAL_KINDS else
                  "natural" if kind in NATURAL_KINDS else "environment"),
        seed=seed, duration=duration, fps=fps, intensity=inten,
        blend=_BLEND[kind], frames=frames,
        spec=_overlay_spec(kind, frames, fps, inten, rng),
    )


def _plan_camera(kind: str, frames: int, fps: int, inten: float,
                 rng: np.random.Generator) -> PrimitivePlan:
    """Camera primitives as per-frame zoom / dx / dy curves (normalized:
    zoom 1.0 = no zoom, dx/dy in fraction of frame width/height)."""
    n = np.arange(frames, dtype=np.float64)
    zoom = np.ones(frames)
    dx = np.zeros(frames)
    dy = np.zeros(frames)
    amp = 0.02 + 0.06 * inten
    if kind in ("push", "tracking"):
        zoom = 1.0 + amp * (n / frames)
    elif kind == "pull":
        zoom = 1.0 + amp * (1.0 - n / frames)
    elif kind == "pan":
        dx = 0.05 * inten * (n / frames - 0.5)
    elif kind == "tilt":
        dy = 0.04 * inten * (n / frames - 0.5)
    elif kind == "orbit":
        phase = rng.uniform(0, 2 * np.pi)
        dx = 0.03 * inten * np.sin(2 * np.pi * n / frames + phase)
        dy = 0.02 * inten * np.cos(2 * np.pi * n / frames + phase)
        zoom = 1.0 + 0.03 * inten * (n / frames)
    elif kind == "shake":
        # decaying jitter — a jolt, not a seizure
        decay = np.exp(-n / max(4.0, frames * 0.12))
        dx = rng.uniform(-1, 1, frames) * 0.022 * inten * decay
        dy = rng.uniform(-1, 1, frames) * 0.018 * inten * decay
    elif kind == "whip":
        # very fast pan with ease-out (a whip-pan transition beat)
        w = max(2.0, frames * 0.2)
        dx = 0.09 * inten * _tri(n, w, w)
    return PrimitivePlan(kind=kind, category="camera", seed=0,
                         duration=frames / fps, fps=fps, intensity=inten,
                         frames=frames,
                         curve={"zoom": zoom, "dx": dx, "dy": dy})


def _overlay_spec(kind: str, frames: int, fps: int, inten: float,
                  rng: np.random.Generator) -> dict:
    """Overlay drawing spec per natural/animal/environment primitive."""
    n = np.arange(frames, dtype=np.float64)
    spec: dict = {"frames": frames, "fps": fps, "w": OVERLAY_W,
                  "h": OVERLAY_H, "intensity": inten}
    if kind == "rain":
        spec.update({"drops": int(90 + 160 * inten),
                     "speed": 0.55 + 0.5 * inten, "slant": -0.12})
    elif kind == "dust":
        spec.update({"motes": int(50 + 90 * inten),
                     "drift": 0.10 + 0.15 * inten, "size": 2})
    elif kind == "particles" or kind == "embers":
        spec.update({"motes": int(40 + 80 * inten),
                     "drift": 0.08 + 0.12 * inten, "size": 2,
                     "rise": True})
    elif kind == "smoke":
        spec.update({"puffs": int(5 + 7 * inten), "drift": 0.05,
                     "size": 40 + 50 * inten})
    elif kind == "clouds":
        spec.update({"puffs": 8, "drift": 0.02 + 0.03 * inten,
                     "size": 90})
    elif kind == "haze" or kind == "wind":
        spec.update({"puffs": 12, "drift": 0.03 + 0.04 * inten,
                     "size": 70, "haze": True})
    elif kind == "fire":
        spec.update({"flames": int(14 + 18 * inten), "base": 0.82,
                     "flicker": 0.5 + 0.5 * inten})
    elif kind == "water":
        spec.update({"lines": int(10 + 14 * inten), "speed": 0.25})
    elif kind == "lightning":
        spec.update({"strikes": [round(frames * 0.35), round(frames * 0.62)]})
    elif kind == "flock":
        spec.update({"birds": int(5 + 7 * inten), "speed": 0.16 + 0.10 * inten,
                     "t0": 0.25})
    elif kind in ("run", "walk"):
        spec.update({"figures": 1, "speed": (0.22 if kind == "run" else 0.10)
                     * (0.7 + 0.6 * inten), "t0": 0.2,
                     "bob": 0.4 if kind == "run" else 0.2})
    elif kind in ("head_turn", "bite", "roar"):
        # close-scale silhouette beat: head wedge turns / jaws snap at t0
        spec.update({"t0": 0.45, "snap": 0.12 + 0.1 * inten,
                     "kind2": kind})
    elif kind == "vegetation_sway":
        spec.update({"stems": 6, "sway": 0.04 + 0.05 * inten})
    return spec


# ── Overlay rendering (numpy → ffmpeg grayscale mp4) ────────────────────────

def render_overlay(plan: PrimitivePlan, out_path: str | Path) -> Path:
    """Render an overlay primitive to a grayscale mp4.

    The pixel value encodes the layer: 255 = full effect (added on screen
    blend, or full occlusion on multiply), 0 = transparent. Deterministic.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = dict(plan.spec)
    frames = int(spec.get("frames", plan.frames))
    w = int(spec.get("w", OVERLAY_W))
    h = int(spec.get("h", OVERLAY_H))
    rng = _seed_of("render", plan.kind, plan.seed, plan.duration,
                   plan.intensity)
    movie = np.zeros((frames, h, w), dtype=np.float32)

    kind = plan.kind
    if kind == "rain":
        _draw_rain(movie, spec, rng)
    elif kind in ("dust", "particles", "embers"):
        _draw_motes(movie, spec, rng, rise=(kind == "embers"))
    elif kind in ("smoke", "clouds", "haze", "wind"):
        _draw_puffs(movie, spec, rng, soft=kind in ("haze", "wind"))
    elif kind == "fire":
        _draw_fire(movie, spec, rng)
    elif kind == "water":
        _draw_water(movie, spec, rng)
    elif kind == "lightning":
        _draw_lightning(movie, spec, rng)
    elif kind == "flock":
        _draw_flock(movie, spec, rng)
    elif kind in ("run", "walk"):
        _draw_ground_figure(movie, spec, rng)
    elif kind in ("head_turn", "bite", "roar"):
        _draw_head_beat(movie, spec, rng)
    elif kind == "vegetation_sway":
        _draw_sway(movie, spec, rng)

    # encode: rawvideo grayscale → ffmpeg h264. Multiply layers are stored
    # inverted: 255 = untouched background, dark pixels = occluding shape.
    if plan.blend == "multiply":
        movie = 255.0 - movie
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
         "-s", f"{w}x{h}", "-r", str(plan.fps), "-i", "-",
         "-an", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", str(out)],
        input=movie.astype(np.uint8).tobytes(), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"overlay render failed ({kind}): {proc.stderr[-300:]!r}")
    return out


def _draw_rain(movie, spec, rng):
    frames, h, w = movie.shape
    drops = int(spec["drops"])
    speed = float(spec["speed"]) * h  # px per frame
    x = rng.uniform(0, w, drops)
    y = rng.uniform(-h, h, drops)
    length = max(4, int(0.06 * h))
    slant = float(spec.get("slant", -0.1)) * length
    for f in range(frames):
        yy = (y + speed * f) % (h + 2 * length) - length
        for i in range(drops):
            x0 = int(x[i]) % w
            y0 = int(yy[i])
            y1 = min(h - 1, y0 + length)
            # r6.1: bright 190/140 dashes read as white artifact streaks on
            # 1080p upscale — rain must be dimmer than any subject highlight.
            movie[f, max(0, y0):y1 + 1, x0] = 128
            xs = int(x0 + slant)
            if 0 <= xs < w and y0 >= 0:
                movie[f, max(0, y0):y1 + 1, xs] = 92


def _draw_motes(movie, spec, rng, rise=False):
    frames, h, w = movie.shape
    n = int(spec["motes"])
    drift = float(spec["drift"]) * w
    size = max(1, int(spec.get("size", 2)) - 1)
    x = rng.uniform(0, w, n)
    y = rng.uniform(0, h, n)
    vx = rng.uniform(0.2, 1.0, n) * drift / frames
    vy = (rng.uniform(0.2, 1.0, n) * drift / frames) * (-1 if rise else 0.4)
    ph = rng.uniform(0, 2 * np.pi, n)
    # Fixed per-mote brightness — the old per-frame rng.uniform(90, 200) made
    # every mote flicker, and the hard size-2 squares read as corrupted white
    # cells once the overlay is upscaled 4x to 1080p (r6.1 timeline audit:
    # "dozens of small white square/cell artifacts"). Soft dim radial disks.
    bright = rng.uniform(45, 115, n)
    r = size
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = np.clip(1.0 - np.sqrt(xx ** 2 + yy ** 2) / (r + 0.5), 0.0, 1.0)
    offs = [(dy, dx, float(disk[dy + r, dx + r]))
            for dy in range(-r, r + 1) for dx in range(-r, r + 1)
            if disk[dy + r, dx + r] > 0.0]
    for f in range(frames):
        xs = (x + vx * f + 0.004 * w * np.sin(ph + f / 9.0)) % w
        ys = (y + vy * f) % h
        for i in range(n):
            xi, yi = int(xs[i]), int(ys[i])
            v = bright[i]
            for dy, dx, a in offs:
                y0, x0 = yi + dy, xi + dx
                if 0 <= y0 < h and 0 <= x0 < w:
                    val = v * (0.4 + 0.6 * a)
                    if val > movie[f, y0, x0]:
                        movie[f, y0, x0] = val


def _draw_puffs(movie, spec, rng, soft=False):
    frames, h, w = movie.shape
    n = int(spec["puffs"])
    size = float(spec.get("size", 40))
    drift = float(spec["drift"]) * w
    cx = rng.uniform(-0.2, 1.2, n) * w
    cy = rng.uniform(0.1, 0.9, n) * h
    amp = rng.uniform(0.5, 1.0, n)
    for f in range(frames):
        xs = (cx + drift * f) % (w + 2 * size) - size
        grow = 1.0 + 0.35 * f / frames
        for i in range(n):
            s = size * amp[i] * grow
            yi, xi = int(cy[i]), int(xs[i])
            y0, y1 = max(0, int(yi - s)), min(h, int(yi + s))
            x0, x1 = max(0, int(xi - s)), min(w, int(xi + s))
            if y1 <= y0 or x1 <= x0:
                continue
            yy, xx = np.ogrid[y0:y1, x0:x1]
            d2 = ((yy - yi) / s) ** 2 + ((xx - xi) / s) ** 2
            blob = np.clip(1.0 - d2, 0, 1)
            if soft:
                blob *= 0.35
            else:
                blob *= 0.5
            movie[f, y0:y1, x0:x1] = np.maximum(
                movie[f, y0:y1, x0:x1], blob * 255)


def _draw_fire(movie, spec, rng):
    frames, h, w = movie.shape
    flames = int(spec["flames"])
    base_y = float(spec["base"]) * h
    flicker = float(spec.get("flicker", 0.8))
    x = rng.uniform(0, w, flames)
    ph = rng.uniform(0, 2 * np.pi, flames)
    for f in range(frames):
        for i in range(flames):
            xi = int((x[i] + 0.01 * w * np.sin(ph[i] + f / 5.0)) % w)
            top = base_y - (0.12 + 0.10 * flicker
                            * abs(np.sin(ph[i] + f / 3.0))) * h
            col = movie[f, int(top):int(base_y), xi]
            grad = np.linspace(255, 60, len(col))
            movie[f, int(top):int(base_y), xi] = np.maximum(col, grad)


def _draw_water(movie, spec, rng):
    frames, h, w = movie.shape
    lines = int(spec["lines"])
    speed = float(spec["speed"])
    y = rng.uniform(0, h, lines)
    ph = rng.uniform(0, 2 * np.pi, lines)
    for f in range(frames):
        for i in range(lines):
            yi = int((y[i] + speed * h * f / frames) % h)
            x0 = int(w * (0.5 + 0.4 * np.sin(ph[i] + f / 7.0)))
            movie[f, yi, max(0, x0 - 30):min(w, x0 + 30)] = 120


def _draw_lightning(movie, spec, rng):
    """1-2 frame branching flashes — the strongest honest spike there is."""
    frames, h, w = movie.shape
    strikes = spec.get("strikes") or [frames // 2]
    for c in strikes:
        c = int(np.clip(c, 1, frames - 2))
        x = rng.uniform(0.3, 0.7) * w
        pts = [(int(x), 0)]
        y = 0
        while y < h - 6:
            y += int(rng.integers(8, 22))
            x += rng.uniform(-0.06, 0.06) * w
            pts.append((int(np.clip(x, 0, w - 1)), min(y, h - 1)))
        for f in (c, c + 1):  # two-frame flash
            movie[f] = np.maximum(movie[f], 235)  # sky flash (whole frame)
            for (px, py) in pts:
                movie[f, py, max(0, px - 1):px + 2] = 255


def _bird(canvas, x, y, s, flap):
    """Small dark bird glyph ('∨' with flapping wings) as a multiply shape."""
    w = int(s * 1.6)
    hh = max(1, int(s * (0.45 + 0.35 * abs(flap))))
    for k in range(-w // 2, w // 2):
        yy = y + int((abs(k) / (w / 2)) * hh * flap if flap >= 0
                     else -abs(k) / (w / 2) * hh * flap)
        if 0 <= yy < canvas.shape[0] and 0 <= x + k < canvas.shape[1]:
            canvas[yy, x + k] = 255
            if 0 <= yy + 1 < canvas.shape[0]:
                canvas[yy + 1, x + k] = 180


def _draw_flock(movie, spec, rng):
    """A flock sweeps across the frame during the event window."""
    frames, h, w = movie.shape
    birds = int(spec["birds"])
    speed = float(spec["speed"]) * w
    t0 = float(spec.get("t0", 0.25))
    start = int(t0 * frames)
    span = max(4, frames - start - 2)
    base_y = rng.uniform(0.25, 0.55, birds) * h
    spread = rng.uniform(0.0, 0.16, birds) * h
    lag = rng.uniform(0.0, 0.25, birds) * span
    s = rng.uniform(5, 9, birds)
    for f in range(start, frames):
        for i in range(birds):
            prog = (f - start - lag[i]) / span
            if prog < 0 or prog > 1.15:
                continue
            xi = int(prog * speed - 0.1 * w)
            yi = int(base_y[i] + spread[i] * np.sin(prog * 6))
            flap = np.sin(prog * 18 + i)
            _bird(movie[f], max(0, min(w - 1, xi)), max(0, min(h - 2, yi)),
                  s[i], flap)


def _figure(canvas, x, y, s):
    """Quadruped silhouette: body ellipse + legs + head wedge (multiply)."""
    h, w = canvas.shape
    bw, bh = int(s * 2.2), int(s * 0.9)
    yy, xx = np.ogrid[-bh:bh + 1, -bw:bw + 1]
    body = ((xx / bw) ** 2 + (yy / bh) ** 2) <= 1.0
    y0, y1 = max(0, y - bh), min(h, y + bh + 1)
    x0, x1 = max(0, x - bw), min(w, x + bw + 1)
    if y1 > y0 and x1 > x0:
        canvas[y0:y1, x0:x1] = np.where(
            body[y0 - (y - bh):y1 - (y - bh), x0 - (x - bw):x1 - (x - bw)],
            255, canvas[y0:y1, x0:x1])
    for leg in range(4):
        lx = x - bw + int((2 * bw / 3) * leg)
        canvas[min(h - 1, y + bh):min(h, y + bh + int(s * 0.8)),
               max(0, lx):max(0, lx) + max(2, int(s * 0.18))] = 255


def _draw_ground_figure(movie, spec, rng):
    frames, h, w = movie.shape
    speed = float(spec["speed"]) * w
    t0 = float(spec.get("t0", 0.2))
    start = int(t0 * frames)
    span = max(4, frames - start - 2)
    s = int(0.09 * h)
    y = int(0.78 * h)
    bob_amp = float(spec.get("bob", 0.3))
    for f in range(start, frames):
        prog = (f - start) / span
        if prog > 1.1:
            continue
        xi = int(-2 * s + prog * (speed + 4 * s))
        bob = int(bob_amp * s * abs(np.sin(prog * 14)))
        _figure(movie[f], max(0, min(w - 1, xi)), y - bob, s)


def _draw_head_beat(movie, spec, rng):
    """Close-scale silhouette beat: a dark head wedge turns / jaws snap once
    mid-shot (head_turn / bite / roar)."""
    frames, h, w = movie.shape
    t0 = float(spec.get("t0", 0.45))
    snap = float(spec.get("snap", 0.15))
    c = int(t0 * frames)
    wframes = max(2, int(snap * frames))
    for f in range(max(0, c - wframes), min(frames, c + wframes + 1)):
        a = _tri(np.array([f], float), c, wframes)[0]
        s = int(0.30 * h)
        cy, cx = int(0.62 * h), int(0.68 * w)
        turn = int(a * 0.10 * w)
        yy, xx = np.ogrid[:h, :w]
        wedge = ((xx > cx) & (xx < cx + turn + s // 2)
                 & (np.abs(yy - cy) < (xx - cx) * 0.55 + 4))
        movie[f][wedge] = np.maximum(movie[f][wedge], 200 * a)


def _draw_sway(movie, spec, rng):
    frames, h, w = movie.shape
    stems = int(spec["stems"])
    sway = float(spec["sway"]) * w
    xs = np.linspace(0.08, 0.92, stems) * w
    ph = rng.uniform(0, 2 * np.pi, stems)
    for f in range(frames):
        for i in range(stems):
            top_x = int(xs[i] + sway * np.sin(ph[i] + f / 10.0))
            for t in range(int(0.45 * h), h):
                prog = (t - 0.45 * h) / (0.55 * h)
                xi = int(xs[i] * prog + top_x * (1 - prog))
                movie[f, t, max(0, xi - 1):xi + 2] = 160


# ── §4 micro-event implementation contract ───────────────────────────────────

def micro_event_ops(micro_events: list[dict], *, duration: float, fps: int,
                    seed: int, subject: str = "",
                    fill_spacing: float | None = None) -> list[dict]:
    """Convert a shot's micro_events into CONCRETE renderer ops (§4).

    Each op is a discrete perceptual event designed to produce a measurable
    frame-delta spike:
      lighting_step — exposure/grade shift landing in <= 2-3 frames
      flash         — 1-2 frame luminance flash (lightning / impact)
      shake         — decaying crop jitter (impact / roar)
      zoom_kick     — fast camera-accel bump (<= 8 frames)
      grade_swap    — hard internal cut-to: fast grade flip
      overlay       — toolkit layer (flock/rain/dust/silhouette...) sweeping
    Deterministic given (micro_events, duration, fps, seed).

    *fill_spacing*: when set (canvas/scene renderers whose base animation is
    near-frozen), insert subtle lighting beats so event gaps never exceed
    it — a static hold (> 2.5 s, §3) becomes impossible by construction.
    """
    frames = max(1, int(round(duration * fps)))
    ops: list[dict] = []
    low_subj = str(subject).lower()
    for e in (micro_events or []):
        kind = str(e.get("kind") or "")
        inten = float(np.clip(float(e.get("intensity", 0.6)), 0.0, 1.0))
        t = float(np.clip(float(e.get("t", 0.0)), 0.0, max(duration - 0.1, 0)))
        c = t * fps
        text = str(e.get("event", "")).lower()
        if kind == "lighting_change":
            dark = any(w in text for w in ("dark", "fade", "dim", "blocked",
                                           "out", "grey", "gray", "shadow"))
            ops.append({"op": "lighting_step", "center": c,
                        "ramp": 2,
                        "amp": round((0.07 + 0.06 * inten)
                                     * (-1 if dark else 1), 4)})
        elif kind == "impact":
            ops.append({"op": "flash", "center": c,
                        "amp": round(0.10 + 0.12 * inten, 4)})
            ops.append({"op": "shake", "center": c, "frames": 6,
                        "amp": round(0.02 + 0.02 * inten, 4)})
        elif kind == "cut_to":
            ops.append({"op": "grade_swap", "center": c,
                        "amp": round(0.09 + 0.07 * inten, 4)})
        elif kind == "camera_accel":
            ops.append({"op": "zoom_kick", "center": c,
                        "width": max(3.0, 0.25 * fps),
                        "amp": round(0.05 + 0.07 * inten, 4)})
        elif kind in ("object_enter", "object_exit"):
            ov = _event_overlay_kind(text, low_subj, seed)
            ops.append({"op": "overlay", "kind": ov, "t": t,
                        "duration": float(e.get("duration", 1.5)),
                        "intensity": max(inten, 0.6),
                        "seed": seed + 17 * len(ops)})
        elif kind == "subject_action":
            ov = _subject_overlay_kind(text, low_subj)
            if ov:
                ops.append({"op": "overlay", "kind": ov, "t": t,
                            "duration": float(e.get("duration", 1.5)),
                            "intensity": max(inten, 0.6),
                            "seed": seed + 17 * len(ops)})
            else:
                ops.append({"op": "zoom_kick", "center": c,
                            "width": max(3.0, 0.3 * fps),
                            "amp": round(0.04 + 0.05 * inten, 4)})
        elif kind == "environment_change":
            ov = "rain" if "rain" in text or "snow" in text else (
                "embers" if any(w in text for w in ("ember", "fire", "ash"))
                else "dust")
            ops.append({"op": "overlay", "kind": ov, "t": max(0.0, t - 0.5),
                        "duration": max(1.6, float(e.get("duration", 1.5))),
                        "intensity": max(inten, 0.5),
                        "seed": seed + 17 * len(ops)})
        elif kind == "reveal":
            ops.append({"op": "zoom_kick", "center": c,
                        "width": max(3.0, 0.3 * fps),
                        "amp": round(0.05 + 0.06 * inten, 4)})
            ops.append({"op": "lighting_step", "center": c, "ramp": 2,
                        "amp": round(0.07 + 0.05 * inten, 4)})
        elif kind == "transformation":
            ops.append({"op": "lighting_step", "center": c, "ramp": 2,
                        "amp": round(0.08 + 0.05 * inten, 4)})
    # guarantee at least one discrete event per shot (§2 floor insurance):
    # a mid-shot grade shift if nothing else landed
    if not any(o["op"] in ("lighting_step", "flash", "grade_swap",
                           "zoom_kick", "shake") for o in ops):
        c = frames * 0.5
        ops.append({"op": "lighting_step", "center": c, "ramp": 2,
                    "amp": 0.075,
                    "why": "event floor: shot had only overlay cues"})
    # §3 anti-hold: cap event gaps (canvas/scene renderers only — the
    # ffmpeg base motion already keeps frame deltas above the static
    # threshold between events).
    if fill_spacing and fill_spacing > 0:
        strong = sorted(
            float(o["center"]) for o in ops
            if o["op"] in ("lighting_step", "flash", "grade_swap",
                           "zoom_kick", "shake"))
        marks = [0.0] + strong + [frames]
        i = 0
        while i < len(marks) - 1:
            gap = marks[i + 1] - marks[i]
            if gap > fill_spacing * fps:
                c = marks[i] + gap / 2
                ops.append({"op": "lighting_step", "center": c, "ramp": 2,
                            "amp": 0.075 * (1 if i % 2 == 0 else -1),
                            "why": f"anti-hold fill (gap {gap / fps:.1f}s)"})
                marks.insert(i + 1, c)  # re-check the left half
            else:
                i += 1
    return ops


def _event_overlay_kind(text: str, subject: str, seed: int) -> str:
    if any(w in text for w in ("bird", "pterosaur", "flock", "wing")):
        return "flock"
    if any(w in text for w in ("dino", "herd", "hadrosaur", "t-rex",
                               "rex", "animal", "survivor")):
        return "run"
    if any(w in text for w in ("rain", "snow", "ash")):
        return "rain"
    if any(w in text for w in ("ember", "fire", "spark")):
        return "embers"
    if any(w in text for w in ("asteroid", "bolide", "rock", "debris")):
        return "dust"
    return ("rain", "dust", "flock")[seed % 3]


def _subject_overlay_kind(text: str, subject: str) -> str | None:
    if any(w in text for w in ("run", "rush", "flee", "herd", "move")):
        return "run"
    if any(w in text for w in ("flock", "bird", "fly", "wing")):
        return "flock"
    if any(w in text for w in ("roar", "bite", "head")):
        return "roar"
    if "walk" in text:
        return "walk"
    return None


# ── AI_IMAGE_MOTION (ffmpeg) adapter ─────────────────────────────────────────

def kenburns_ops(ops: list[dict], *, duration: float, fps: int,
                 work_dir: str | Path) -> dict:
    """Compile micro_event_ops into the kenburns render contract:
      {"zoom": [...], "brightness": [...], "shake": [...],
       "overlays": [{"path", "blend", "opacity"}]}
    Overlay layers are rendered to *work_dir* (deterministic names).
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    zoom: list[dict] = []
    brightness: list[dict] = []
    shake: list[dict] = []
    overlays: list[dict] = []
    for o in ops:
        op = o["op"]
        if op in ("lighting_step", "flash", "grade_swap"):
            amp = float(o["amp"])
            # FAST by design: ramp <= 3 frames so the frame delta spikes
            ramp = float(o.get("ramp", 2))
            brightness.append({"center": round(float(o["center"]), 1),
                               "amp": amp,
                               "width": max(1.0, ramp)})
            if op == "grade_swap":
                # hard flip back so the swap reads as a cut, not a fade
                brightness.append({"center": round(float(o["center"]) + 1.5,
                                                   1),
                                   "amp": -amp, "width": 1.0})
        elif op == "zoom_kick":
            zoom.append({"center": round(float(o["center"]), 1),
                         "amp": float(o["amp"]),
                         "width": float(o.get("width", 6))})
        elif op == "shake":
            shake.append({"center": round(float(o["center"]), 1),
                          "amp": float(o["amp"]),
                          "frames": float(o.get("frames", 6))})
        elif op == "overlay":
            try:
                plan = plan_primitive(
                    o["kind"], seed=int(o.get("seed", 0)),
                    duration=float(o.get("duration", 1.5)), fps=fps,
                    intensity=float(o.get("intensity", 0.6)))
            except ValueError:
                continue
            path = render_overlay(
                plan, work / f"ovl_{o['kind']}_{int(o.get('seed', 0))}.mp4")
            overlays.append({"path": str(path), "blend": plan.blend,
                             "opacity": round(0.55 + 0.4 * plan.intensity, 2),
                             "kind": o["kind"]})
    return {"zoom": zoom, "brightness": brightness, "shake": shake,
            "overlays": overlays}


# ── MOTION_CANVAS / PIXIJS cue adapters (event layers in render.mjs) ────────

def canvas_event_cues(ops: list[dict], fps: int) -> list[dict]:
    """Compile ops into frame-timed cues for the node canvas event layers
    (motion/render.mjs and pixi/render.mjs share the contract):
      {start, end, type, amp} — frame indices, type ∈ flash|darken|
      shake|zoom_kick|cut|overlay{kind,blend,seed}."""
    cues: list[dict] = []
    for o in ops:
        c = float(o.get("center", float(o.get("t", 0.0)) * fps))
        if o["op"] == "lighting_step":
            dark = float(o["amp"]) < 0
            cues.append({"start": int(c), "end": int(c + max(2, fps * 0.2)),
                         "type": "darken" if dark else "flash",
                         "amp": min(1.0, abs(float(o["amp"])) * 3.5)})
        elif o["op"] == "flash":
            cues.append({"start": int(c), "end": int(c + 2),
                         "type": "flash", "amp": 0.55})
        elif o["op"] == "grade_swap":
            cues.append({"start": int(c), "end": int(c + 3),
                         "type": "cut", "amp": 0.45})
        elif o["op"] == "shake":
            cues.append({"start": int(c),
                         "end": int(c + float(o.get("frames", 6))),
                         "type": "shake", "amp": float(o["amp"])})
        elif o["op"] == "zoom_kick":
            cues.append({"start": int(c - float(o.get("width", 6)) / 2),
                         "end": int(c + float(o.get("width", 6)) / 2),
                         "type": "zoom_kick", "amp": float(o["amp"])})
        elif o["op"] == "overlay":
            try:
                plan = plan_primitive(
                    o["kind"], seed=int(o.get("seed", 0)),
                    duration=float(o.get("duration", 1.5)), fps=fps,
                    intensity=float(o.get("intensity", 0.6)))
            except ValueError:
                continue
            cues.append({"start": int(c),
                         "end": int(c + plan.frames),
                         "type": "overlay", "kind": o["kind"],
                         "blend": plan.blend,
                         "spec": plan.spec,
                         "seed": int(o.get("seed", 0))})
    return cues
