"""V8 living-diagram event frames (brief §3).

Diagrams must support state transitions: draw/reveal → highlight → flow →
transform → consequence. These renderers animate the INFORMATION itself —
new elements appearing (reveal), attention isolation (isolate), energy
flowing between components (flow), regions filling (fill_state), and
consequences propagating (consequence). Camera movement is never counted as
any of these.

Frames are full-canvas RGBA PNGs with effects drawn at the card's absolute
position (card-space [0,1] rects → canvas px), matching the V7 event-PNG
convention so composev5 can overlay at 0:0. The full lifecycle (fade-in,
act, fade-out) is baked into the frame alphas, so the compositor only needs
an enable window.

Spec schemas (emitted by planv8):
  reveal      {kind: REVEAL,      rects: [[x,y,w,h], ...], style}
  isolate     {kind: ISOLATE,     rect, style}
  flow        {kind: FLOW,        from_rect, to_rect, style}
  fill_state  {kind: FILL_STATE,  rect, style}
  consequence {kind: CONSEQUENCE, rect, effect}
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from engine import flags as _flags

EVENT_FPS = 15
KINDS = ("reveal", "isolate", "flow", "fill_state", "consequence")
DEFAULT_HOLD = {"reveal": 2.6, "isolate": 2.6, "flow": 2.4,
                "fill_state": 2.8, "consequence": 2.2}

STROKE = (243, 240, 233, 255)      # warm paper-white stroke
AMBER = (255, 178, 84)             # energy / heat accent
AMBER_SOFT = (255, 178, 84, 80)
DANGER = (255, 96, 60)


def _ease(p: float) -> float:
    p = min(max(float(p), 0.0), 1.0)
    return 3 * p * p - 2 * p * p * p


def _ease_out(p: float) -> float:
    """Cubic ease-out: fast departure, decelerating arrival."""
    p = min(max(float(p), 0.0), 1.0)
    return 1.0 - (1.0 - p) ** 3


def _E(p: float) -> float:
    """V9 motion: smoothstep where linear interpolation used to run
    (fades, dims). Flag off -> exact linear baseline (rollback)."""
    p = min(max(float(p), 0.0), 1.0)
    return _ease(p) if _flags.motion9() else p


def _EO(p: float) -> float:
    """V9 motion: cubic ease-out for moving elements (particles, rings).
    Flag off -> exact linear baseline (rollback)."""
    p = min(max(float(p), 0.0), 1.0)
    return _ease_out(p) if _flags.motion9() else p


def _magnitude(spec: dict) -> float:
    """V9 compounding: visual magnitude scales with the beat's intensity
    tier instead of static parameters — 0.62 discovery -> 1.00x,
    0.78 escalation -> ~1.26x, 0.85 payoff -> ~1.37x (clamped 0.8-1.5).
    Flag off or unspecified -> 1.0 static baseline."""
    if not _flags.compound9():
        return 1.0
    try:
        it = float((spec or {}).get("intensity"))
    except (TypeError, ValueError):
        return 1.0
    return min(max(it / 0.62, 0.8), 1.5)


def _env(t_frac: float, fin: float = 0.14, fout: float = 0.16,
         persist: bool = False) -> float:
    """Baked lifecycle envelope: fade-in, plateau, fade-out.

    persist=True keeps the end-state (state transformations must HOLD, not
    revert — otherwise they are decoration, not information)."""
    if t_frac < fin:
        return _E(t_frac / fin)
    if not persist and t_frac > 1.0 - fout:
        return _E(max((1.0 - t_frac) / fout, 0.0))
    return 1.0


def _clamp_rect(r: list, pad: float = 0.015) -> list:
    x, y, w, h = [float(v) for v in r]
    x = min(max(x, pad), 1.0 - pad)
    y = min(max(y, pad), 1.0 - pad)
    w = min(max(w, 0.02), 1.0 - pad - x)
    h = min(max(h, 0.02), 1.0 - pad - y)
    return [x, y, w, h]


def _abs(rect: list, card_w: int, card_h: int, card_y0: float):
    """Card-space [0,1] rect -> absolute canvas px (composev5 convention)."""
    x, y, w, h = _clamp_rect(rect)
    return (x * card_w, card_y0 + y * card_h, w * card_w, h * card_h)


def _center(abs_rect):
    x, y, w, h = abs_rect
    return (x + w / 2.0, y + h / 2.0)


def _rounded(d: ImageDraw.ImageDraw, box, radius, fill, outline, width=3):
    try:
        d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline,
                            width=width)
    except AttributeError:  # older Pillow
        d.rectangle(box, fill=fill, outline=outline, width=width)


def _frame_reveal(img, draw, spec, p, geo):
    """Progressive draw-on of declared elements (staggered)."""
    rects = spec.get("rects") or []
    if not rects:
        return
    n = len(rects)
    slot = 0.55 / max(n, 1)
    for i, r in enumerate(rects):
        start = i * slot
        pi = _ease((p - start) / max(0.30, 0.45 - 0.1 * i))
        if pi <= 0.02:
            continue
        ax, ay, aw, ah = _abs(r, *geo)
        a = int(235 * pi)
        box = (ax, ay, ax + aw, ay + ah)
        # draw-on perimeter: partial outline along the rect edge
        per = pi * 2 * (aw + ah)
        pts, edge = [], per
        edges = [((ax, ay), (ax + aw, ay)), ((ax + aw, ay), (ax + aw, ay + ah)),
                 ((ax + aw, ay + ah), (ax, ay + ah)), ((ax, ay + ah), (ax, ay))]
        for (x0, y0), (x1, y1) in edges:
            seg = math.hypot(x1 - x0, y1 - y0)
            if edge <= 0:
                break
            take = min(seg, edge)
            f = take / seg if seg else 0
            pts += [(x0, y0), (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)]
            edge -= take
        if len(pts) >= 2:
            draw.line(pts, fill=STROKE[:3] + (a,), width=3)
        fill_a = int(46 * pi)
        _rounded(draw, box, 6, (255, 244, 214, fill_a), None)


def _frame_isolate(img, draw, spec, p, geo):
    """Dim everything outside the focus rect; bright edge on the hole."""
    r = spec.get("rect") or [0.25, 0.2, 0.5, 0.6]
    ax, ay, aw, ah = _abs(r, *geo)
    a = int(150 * _E(p))
    if a <= 3:
        return
    W, H = img.size
    for box in [(0, 0, W, ay), (0, ay + ah, W, H),
                (0, ay, ax, ay + ah), (ax + aw, ay, W, ay + ah)]:
        draw.rectangle(box, fill=(6, 8, 12, a))
    draw.rectangle((ax, ay, ax + aw, ay + ah),
                   outline=STROKE[:3] + (int(220 * _E(p)),), width=3)


def _frame_flow(img, draw, spec, p, geo):
    """Particles flowing from_rect -> to_rect with an arced path + ripple."""
    fr, to = spec.get("from_rect"), spec.get("to_rect")
    if not fr or not to:
        return
    A = _center(_abs(fr, *geo))
    B = _center(_abs(to, *geo))
    m = _magnitude(spec)          # V9: particle density compounds with tier
    k = max(5, int(round(9 * m)))
    rs = math.sqrt(m)             # radius grows with sqrt of magnitude
    for i in range(k):
        u = ((p * 1.5 + i / k) % 1.0)
        ue = _EO(u)               # V9: energy arrives, it doesn't slide
        fade = min(ue * 4, (1 - ue) * 4, 1.0)
        if fade <= 0.05:
            continue
        x = A[0] + (B[0] - A[0]) * ue
        y = A[1] + (B[1] - A[1]) * ue - math.sin(math.pi * ue) * 42.0
        rad = (4.5 + 2.0 * math.sin(math.pi * ue)) * rs
        a = int(235 * fade)
        col = AMBER + (a,)
        draw.ellipse((x - rad, y - rad, x + rad, y + rad), fill=col)
        # short motion trail
        u0 = max(ue - 0.06, 0.0)
        x0 = A[0] + (B[0] - A[0]) * u0
        y0 = A[1] + (B[1] - A[1]) * u0 - math.sin(math.pi * u0) * 42.0
        draw.line([(x0, y0), (x, y)], fill=AMBER + (int(a * 0.45),), width=3)
    # destination ripple in the back half
    rp = _ease((p - 0.45) / 0.55)
    if rp > 0.02:
        rr = (8 + 34 * rp) * rs
        draw.ellipse((B[0] - rr, B[1] - rr, B[0] + rr, B[1] + rr),
                     outline=AMBER + (int(200 * (1 - rp)),), width=3)


def _frame_fill_state(img, draw, spec, p, geo):
    """Region fills bottom-up (heat/liquid/vegetation spread metaphor)."""
    r = spec.get("rect") or [0.2, 0.25, 0.6, 0.5]
    ax, ay, aw, ah = _abs(r, *geo)
    m = _magnitude(spec)          # V9: fill glow compounds with tier
    level = _ease(min(p / 0.72, 1.0))
    fh = ah * level
    if fh > 2:
        top = ay + ah - fh
        grad_a = min(255, int(96 * (0.55 + 0.45 * level) * m))
        draw.rectangle((ax, top, ax + aw, ay + ah),
                       fill=AMBER + (grad_a,))
        draw.line([(ax, top), (ax + aw, top)],
                  fill=(255, 214, 150, min(255, int(235 * m))), width=3)
    if level >= 0.999:
        draw.rectangle((ax, ay, ax + aw, ay + ah),
                       outline=AMBER + (min(255, int(200 * m)),), width=3)


def _frame_consequence(img, draw, spec, p, geo):
    """Pulsing glow on the affected element (the effect landing)."""
    r = spec.get("rect") or [0.3, 0.3, 0.4, 0.4]
    ax, ay, aw, ah = _abs(r, *geo)
    cx, cy = ax + aw / 2, ay + ah / 2
    base = max(aw, ah)
    m = _magnitude(spec)          # V9: radius/glow compound with tier
    col = DANGER if str(spec.get("effect") or "glow") == "danger" else AMBER
    for j in range(3):
        ring_p = ((p * 1.25 + j / 3.0) % 1.0)
        rr = base * (0.18 + 0.30 * _EO(ring_p)) * m
        a = int(215 * (1 - ring_p))
        if a <= 4:
            continue
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                     outline=col + (a,),
                     width=max(2, min(8, int(5 * (1 - ring_p) * m))))
    aura_a = min(255, int(70 * m * math.sin(math.pi * min(p / 0.9, 1.0)) ** 2))
    if aura_a > 4:
        rb = base * 0.42 * (1.0 + 0.15 * (m - 1.0))
        draw.ellipse((cx - rb, cy - rb, cx + rb, cy + rb),
                     fill=col + (aura_a,))


_RENDER = {"reveal": _frame_reveal, "isolate": _frame_isolate,
           "flow": _frame_flow, "fill_state": _frame_fill_state,
           "consequence": _frame_consequence}


PERSIST_KINDS = ("reveal", "fill_state")


def render_frames(kind: str, spec: dict, out_dir: Path, n_frames: int,
                  card_w: int, card_h: int, card_y0: float,
                  canvas_w: int = 1536, canvas_h: int = 1024,
                  persist: bool = False) -> Path:
    """Render one living event as n_frames RGBA PNGs (f%05d.png)."""
    if kind not in _RENDER:
        raise ValueError(f"living: unknown event kind {kind!r}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    geo = (int(card_w), int(card_h), float(card_y0))
    fn = _RENDER[kind]
    n = max(2, int(n_frames))
    for i in range(n):
        p = i / max(n - 1, 1)
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        fn(img, draw, dict(spec or {}), p, geo)
        env = _env(p, persist=persist or kind in PERSIST_KINDS)
        if env < 0.999:
            a = img.getchannel("A").point(lambda v: int(v * env))
            img.putalpha(a)
        img.save(out_dir / f"f{i:05d}.png", "PNG")
    return out_dir
