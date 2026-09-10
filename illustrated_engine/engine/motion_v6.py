"""V6 camera motion — subpixel Bézier/cubic trajectories, 2x/4x render, static support.

V6 P0 fixes vs. motion.py:
  - Continuous subpixel position/scale/rotation across the whole shot
  - Bézier / cubic / ease curves (not raw linear)
  - Per-frame coords stay floating point until rasterization
  - Camera stage rendered at 2x or 4x, downsampled once to 1080x780
  - Static shots: camera can remain fully still (no forced motion)
  - Always renders from the original plate (never a transformed frame)

Coordinate systems (unchanged from motion.py):
  PLATE (asset): 1536x1024, camera window normalized to plate
  PANEL: 1080x780 at frame y=460
  The 2x/4x "camera stage" is the *output* panel at 2x or 4x; the plate is
  pre-scaled to the stage-canvas size (CONTENT_W x CONTENT_H) on disk only
  if we pre-bake it, but in the V6 path we keep the plate native and let
  ffmpeg scale+pad+zoompan in one filter graph.

The single primitive the renderer emits is a "camera graph" string with
Bézier-evaluated expressions for zoom/x/y over the output frame number.
Because the Bézier basis is a polynomial in `on`, ffmpeg's expression
evaluator can compute it per frame at subpixel precision without any
discretization in our code.

Curves available:
  LINEAR    legacy fallback
  EASE_IN   cubic ease-in (slow start, fast end)
  EASE_OUT  cubic ease-out (fast start, slow end)
  EASE_IO   smoothstep S-curve
  BEZIER    cubic Bézier with two control handles (P1, P2 in [0,1] each)
  HOLD      static (no motion — by design)

The brief also forbids `chained` transforms (resize -> crop -> resize ...).
We never transform an already-transformed frame: the source plate PNG is
the only input. Everything downstream (scale, pad, zoompan, downsample to
PANEL_W x PANEL_H) happens inside a single filter graph on raw pixels.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from engine import flags as _flags

# panel / canvas constants (must match motion.py)
FPS = 30
# V10 §1 — native 9:16: portrait panel fills the Shorts focal band
# (canvas Y 0.15-0.75 of 1080x1920). Rollback: V10_VERTICAL=0 restores the
# 1080x780 horizontal-monitor panel. Every downstream stage/canvas constant
# derives from these two, so the camera window aspect follows automatically.
PANEL_W, PANEL_H = (1080, 1152) if _flags.vertical10() else (1080, 780)
PANEL_Y = 460
FRAME_W, FRAME_H = 1080, 1920
PLATE_W, PLATE_H = 1536, 1024

# RENDER UPSCALE — 2x = 2160x1560, 4x = 4320x3120. We support both via
# the same filter graph; the upscale factor scales CONTENT_W/H and the
# downsample target. ffmpeg's scale filter with lanczos + the final
# setsar=1 makes the downsample artifact-free.
UPSCALE = 2  # 2x is the default; brief allows 2x or 4x

# Stage canvas (2x or 4x of panel) with the same panel aspect so the
# zoompan crop still maps 1:1 onto the panel.
STAGE_W = PANEL_W * UPSCALE     # 2160
STAGE_H = PANEL_H * UPSCALE     # 1560
# Plate scaled to fit the stage canvas (cover, then letterbox vertically
# onto the stage so the window center stays stable).
CONTENT_W = STAGE_W
CONTENT_H = round(STAGE_W * PLATE_H / PLATE_W)  # 1440 (2x of 720-ish)
# Stage canvas: CONTENT_W x (CONTENT_H + 2*CANVAS_PAD_Y) at panel aspect
CANVAS_W = CONTENT_W
CANVAS_H = round(STAGE_W * PANEL_H / PANEL_W)   # panel aspect 13:18
CANVAS_PAD_Y = max(0, (CANVAS_H - CONTENT_H) // 2)

# Camera primitives — the 11 motion.py primitives plus HOLD and BEZIER/DIAGONAL
CAMERA_PRIMITIVES = (
    "ZOOM_IN", "ZOOM_OUT", "PAN_LEFT", "PAN_RIGHT", "PAN_UP", "PAN_DOWN",
    "DIAGONAL_PAN", "PUSH_IN", "PULL_OUT", "CROP_REVEAL", "FOCUS_REVEAL",
    "HOLD",            # V6 P0: static-by-design
    "CUSTOM_BEZIER",   # V6 P0: arbitrary Bézier trajectory
)

# Endpoint defaults per primitive (same as motion.py for compat).
CAMERA_DEFAULTS = {
    "ZOOM_IN":      ({"w": 0.92, "cx": 0.50, "cy": 0.50}, {"w": 0.62}),
    "ZOOM_OUT":     ({"w": 0.62, "cx": 0.50, "cy": 0.50}, {"w": 0.92}),
    "PAN_LEFT":     ({"w": 0.80, "cx": 0.68, "cy": 0.50}, {"cx": 0.32}),
    "PAN_RIGHT":    ({"w": 0.80, "cx": 0.32, "cy": 0.50}, {"cx": 0.68}),
    "PAN_UP":       ({"w": 0.80, "cx": 0.50, "cy": 0.68}, {"cy": 0.32}),
    "PAN_DOWN":     ({"w": 0.80, "cx": 0.50, "cy": 0.32}, {"cy": 0.68}),
    "DIAGONAL_PAN": ({"w": 0.85, "cx": 0.65, "cy": 0.65}, {"w": 0.78, "cx": 0.35, "cy": 0.35}),
    "PUSH_IN":      ({"w": 0.95, "cx": 0.50, "cy": 0.50}, {"w": 0.55}),
    "PULL_OUT":     ({"w": 0.55, "cx": 0.50, "cy": 0.50}, {"w": 0.95}),
    "CROP_REVEAL":  ({"w": 0.92, "cx": 0.50, "cy": 0.72}, {"w": 0.84, "cy": 0.50}),
    "FOCUS_REVEAL": ({"w": 0.90, "cx": 0.50, "cy": 0.50}, {"w": 0.86}),
    "HOLD":         ({"w": 0.85, "cx": 0.50, "cy": 0.50}, {}),
    "CUSTOM_BEZIER": ({"w": 0.85, "cx": 0.50, "cy": 0.50}, {}),
}

# Per-primitive default easing curve (V6 P0: deterministic, smooth).
DEFAULT_CURVE = {
    "ZOOM_IN": "EASE_IO", "ZOOM_OUT": "EASE_IO",
    "PAN_LEFT": "EASE_IO", "PAN_RIGHT": "EASE_IO",
    "PAN_UP": "EASE_IO", "PAN_DOWN": "EASE_IO",
    "DIAGONAL_PAN": "EASE_IO",
    "PUSH_IN": "EASE_OUT",      # push-in feels dramatic: fast start, settle
    "PULL_OUT": "EASE_IN",      # pull-out: slow reveal, accelerate out
    "CROP_REVEAL": "EASE_IN",   # hold-and-reveal: slow start
    "FOCUS_REVEAL": "EASE_OUT",
    "HOLD": "LINEAR",
    "CUSTOM_BEZIER": "BEZIER",
}


def clamp_window(w, cx, cy):
    """Clamp a camera window to plate+letterbox bounds. Returns (w, cx, cy)."""
    w = min(max(float(w), 0.30), 1.0)
    if _flags.vertical10():
        # V10 §1 — re-scale the authored window so the same zoom keeps the
        # same fraction of plate HEIGHT on the portrait panel; width
        # coverage becomes the tall-panel ratio (~60-75% of the asset) and
        # horizontal pans traverse the remainder (tracking-pan on wide
        # assets). Window aspect always equals the panel aspect, so the
        # cover crop never letterboxes.
        _r = CONTENT_H / CANVAS_H
        w = min(max(w * _r, 0.30 * _r), 1.0)
    cx = min(max(float(cx), w / 2.0), 1.0 - w / 2.0)
    cy_lo = (CANVAS_H * w / 2.0 - CANVAS_PAD_Y) / CONTENT_H
    cy_hi = (CONTENT_H + CANVAS_PAD_Y - CANVAS_H * w / 2.0) / CONTENT_H
    cy = min(max(float(cy), cy_lo), cy_hi)
    return w, cx, cy


def resolve_camera(camera):
    """-> (primitive, from{w,cx,cy}, to{...}, curve, notes[]).

    V6 changes: returns the resolved curve in the notes for inspection.
    Accepts both V6 nested {from, to} and V4 flat {from_scale, to_scale}
    camera schemas; V4 is normalized here.
    """
    cam = camera or {}
    # Normalize V4 -> V6
    if "from" not in cam and "from_scale" in cam:
        fs = float(cam.get("from_scale") or 1.0)
        ts = float(cam.get("to_scale") or 1.0)
        def _num(v, default):
            return float(v) if v is not None else float(default)
        fcx = _num(cam.get("from_cx"), _num(cam.get("cx"), 0.5))
        fcy = _num(cam.get("from_cy"), _num(cam.get("cy"), 0.5))
        tcx = _num(cam.get("cx"), fcx)
        tcy = _num(cam.get("cy"), fcy)
        cam = {
            "primitive": str(cam.get("primitive", "zoompan")).upper(),
            "from": {"w": round(1.0 / max(0.01, fs), 4), "cx": fcx, "cy": fcy},
            "to":   {"w": round(1.0 / max(0.01, ts), 4), "cx": tcx, "cy": tcy},
        }
    prim_raw = str(cam.get("primitive", "HOLD")).upper()
    prim_map = {
        "ZOOMPAN": "ZOOM_IN", "ZOOM_IN": "ZOOM_IN", "ZOOM_OUT": "ZOOM_OUT",
        "PAN_LEFT": "PAN_LEFT", "PAN_RIGHT": "PAN_RIGHT",
        "PAN_UP": "PAN_UP", "PAN_DOWN": "PAN_DOWN",
        "PUSH_IN": "PUSH_IN", "PULL_OUT": "PULL_OUT",
        "DIAGONAL_PAN": "DIAGONAL_PAN",
        "CROP_REVEAL": "CROP_REVEAL", "FOCUS_REVEAL": "FOCUS_REVEAL",
        "HOLD": "HOLD", "STATIC": "HOLD",
    }
    prim = prim_map.get(prim_raw, "HOLD")
    if prim not in CAMERA_PRIMITIVES:
        prim = "HOLD"
    d0, d1 = CAMERA_DEFAULTS[prim]
    raw_f = {**d0, **(cam.get("from") or {})}
    raw_t = {**raw_f, **d1, **(cam.get("to") or {})}
    notes = []

    def _clamp(d, which):
        w, cx, cy = clamp_window(d["w"], d["cx"], d["cy"])
        for key, v, c in (("w", d["w"], w), ("cx", d["cx"], cx), ("cy", d["cy"], cy)):
            if abs(float(v) - c) > 1e-6:
                notes.append(f"{which}.{key} {float(v):.3f}->{c:.3f}")
        return {"w": w, "cx": cx, "cy": cy}

    f = _clamp(raw_f, "from")
    t = _clamp(raw_t, "to")
    # If the resolved window doesn't actually move, force HOLD (V6 P0:
    # static shots may remain static; don't synthesize motion).
    if (abs(f["w"] - t["w"]) < 1e-4
            and abs(f["cx"] - t["cx"]) < 1e-4
            and abs(f["cy"] - t["cy"]) < 1e-4):
        prim = "HOLD"
        notes.append("auto-HOLD (no movement in camera dict)")
    if prim == "HOLD":
        notes.append("primitive=HOLD (static by design)")
    curve = cam.get("curve") or DEFAULT_CURVE.get(prim, "EASE_IO")
    notes.append(f"curve={curve} upscale={UPSCALE}x")
    return prim, f, t, curve, notes


def _ease_expr(curve: str, p_expr: str, p1: float = 0.33, p2: float = 0.66) -> str:
    """Return an ffmpeg expression that evaluates the easing curve at p=p_expr.

    p_expr is the linear progress in [0,1]. Output is also in [0,1].
    Linear and HOLD are passed through (HOLD clamps to 0).
    EASE_IN/OUT/IO use cubic polynomials on p; BEZIER uses the standard
    cubic Bézier basis (handles p1, p2 in [0,1]).
    """
    c = curve.upper()
    if c in ("LINEAR", "HOLD"):
        # HOLD -> 0; LINEAR -> identity. p_expr is the linear param.
        if c == "HOLD":
            return "(0)"
        return f"({p_expr})"
    if c == "EASE_IN":
        # cubic-in: t^3
        return f"(({p_expr})*({p_expr})*({p_expr}))"
    if c == "EASE_OUT":
        # cubic-out: 1 - (1-t)^3
        one_minus = f"(1-({p_expr}))"
        return f"(1-({one_minus})*({one_minus})*({one_minus}))"
    if c == "EASE_IO":
        # smoothstep: 3t^2 - 2t^3
        t2 = f"({p_expr})*({p_expr})"
        return f"({t2}*(3-2*({p_expr})))"
    if c == "BEZIER":
        # Cubic Bézier basis: B(t) = (1-t)^3 P0 + 3(1-t)^2 t P1 + 3(1-t) t^2 P2 + t^3 P3
        # with P0=0, P3=1. Expanding symbolically is heavy; use a fixed-iteration
        # De Casteljau is too much. ffmpeg's expr engine can do it via nested
        # ternaries on powers — but easier: use the closed-form polynomial
        # (numerator)/denom where:
        #   B(t) = (3P1 t (1-t)^2 + 3P2 t^2 (1-t) + t^3)
        # since P0=0, P3=1 and (1-t)^3 + 3(1-t)^2 t + 3(1-t) t^2 + t^3 = 1.
        t = p_expr
        one_minus = f"(1-({t}))"
        t2 = f"({t})*({t})"
        om2 = f"({one_minus})*({one_minus})"
        return (f"(3*{p1:.4f}*({t})*({om2})"
                f"+3*{p2:.4f}*({t2})*({one_minus})"
                f"+({t2})*({t}))")
    raise ValueError(f"unknown curve: {curve!r}")


def _profile_p_e(curve: str, p_expr: str) -> str:
    """Progress expression honoring CAMERA_PROFILE (bench brief §4).

    CAMERA_PROFILE=eased overrides authored curves with a C2 quintic
    smoothstep, 6t^5 - 15t^4 + 10t^3 — zero velocity AND zero acceleration
    at both endpoints, removing the residual start/stop snap of the cubic
    curves. baseline keeps authored per-shot curves untouched.
    """
    from engine import flags as _fl
    if _fl.camera_profile() == "eased":
        t = p_expr
        return f"(({t})*({t})*({t}))*(6*({t})*({t})-15*({t})+10)"
    return _ease_expr(curve, p_expr)


def _pe_numeric(curve: str, p: float) -> float:
    """Python-side mirror of _profile_p_e for QA trajectory sampling."""
    from engine import flags as _fl
    if _fl.camera_profile() == "eased":
        return p * p * p * (6 * p * p - 15 * p + 10)
    c = curve.upper()
    if c in ("LINEAR",):
        return p
    if c == "HOLD":
        return 0.0
    if c == "EASE_IN":
        return p * p * p
    if c == "EASE_OUT":
        om = 1 - p
        return 1 - om * om * om
    if c == "EASE_IO":
        return p * p * (3 - 2 * p)
    if c == "BEZIER":
        om = 1 - p
        return 3 * 0.33 * p * om * om + 3 * 0.66 * p * p * om + p * p * p
    return p


def frame_count(duration_s, fps=FPS):
    return max(1, int(round(float(duration_s) * fps)))


def camera_filter(camera, duration_s, fps=FPS):
    """-> (filter_fragment, n_frames, primitive, notes).

    V6 P0: subpixel Bézier/cubic trajectories, camera stage at 2x, single
    downsample to PANEL_W x PANEL_H via lanczos. The plate PNG is the only
    input — no chained transforms.

    The filter graph:
        [0:v] -> scale to CONTENT_W x CONTENT_H (lanczos)
              -> pad to CANVAS_W x CANVAS_H (panel aspect, top/bottom)
              -> zoompan with Bézier-evaluated (z, x, y) expressions
              -> scale PANEL_W x PANEL_H (lanczos, the single downsample)
              -> setsar=1
    """
    prim, f, t, curve, notes = resolve_camera(camera)
    n = frame_count(duration_s, fps)
    # Linear progress in [0,1] across the shot.
    p = f"clip(on/{n - 1},0,1)" if n > 1 else "0"
    p_e = _profile_p_e(curve, p)

    def blend(a, b):
        if abs(b - a) < 1e-9:
            return f"({a:.6f})"
        return f"(({a:.6f})+({p_e})*({b - a:.6f}))"

    if prim == "HOLD":
        # Camera frozen at the from position for the entire shot.
        w_e = f"({f['w']:.6f})"
        cx_e = f"({f['cx']:.6f})"
        cy_e = f"({f['cy']:.6f})"
    else:
        w_e = blend(f["w"], t["w"])
        cx_e = blend(f["cx"], t["cx"])
        cy_e = blend(f["cy"], t["cy"])

    z_e = f"(1/({w_e}))"
    x_e = (f"clip({CANVAS_W}*({cx_e})-({CANVAS_W})*({w_e})/2,"
           f"0,{CANVAS_W}-{CANVAS_W}*({w_e}))")
    y_e = (f"clip({CONTENT_H}*({cy_e})+{CANVAS_PAD_Y}-({CANVAS_H})*({w_e})/2,"
           f"0,{CANVAS_H}-{CANVAS_H}*({w_e}))")
    # V6 P0: render the camera stage at 2x (STAGE_W x STAGE_H), then ONE
    # downsample to PANEL_W x PANEL_H with lanczos. This is the single
    # rasterization of the (z, x, y) trajectory. fps stays 30 so the
    # expression sample density matches the output frame rate.
    frag = (f"scale={CONTENT_W}:{CONTENT_H}:flags=lanczos,"
            f"pad={CANVAS_W}:{CANVAS_H}:0:{CANVAS_PAD_Y}:color=black,"
            f"zoompan=z='{z_e}':x='{x_e}':y='{y_e}':d={n}:s={STAGE_W}x{STAGE_H}:fps={fps},"
            f"scale={PANEL_W}:{PANEL_H}:flags=lanczos,"
            f"setsar=1")
    return frag, n, prim, notes


def ambient_parallax_filter(camera, duration_s, fps=FPS, damp=None):
    """2.5D parallax (bench brief §3) — damped-rate ambient background.

    The ambient layer's camera window moves at `damp`x the rate of the card
    camera around its own trajectory midpoint, so the blurred background
    field lags the foreground card uniformly (depth for zoom AND pan).
    Subtle by construction (0.5 <= damp <= 0.95, default 0.85); the ambient
    is a Gaussian-blurred, darkened color field — no factual content can
    distort, and no text lives on this layer.
    -> (filter_fragment, n_frames, primitive)
    """
    if damp is None:
        from engine import flags as _fl
        damp = _fl.parallax_damp()
    prim, f, t, curve, _notes = resolve_camera(camera)
    n = frame_count(duration_s, fps)
    p = f"clip(on/{n - 1},0,1)" if n > 1 else "0"
    p_e = _profile_p_e(curve, p)

    def damped(a, b):
        a, b = float(a), float(b)
        if abs(b - a) < 1e-9:
            return a, a
        m = (a + b) / 2.0
        return m + (a - m) * damp, m + (b - m) * damp

    fw, tw = damped(f["w"], t["w"])
    fx, tx = damped(f["cx"], t["cx"])
    fy, ty = damped(f["cy"], t["cy"])

    def blend(a, b):
        if abs(b - a) < 1e-9:
            return f"({a:.6f})"
        return f"(({a:.6f})+({p_e})*({b - a:.6f}))"

    w_e = blend(fw, tw)
    cx_e = blend(fx, tx)
    cy_e = blend(fy, ty)
    # Full-frame ambient (FRAME_W x FRAME_H), 1x zoompan stage: the field is
    # Gaussian-blurred, which masks integer-sample quantization — extra
    # supersampling would cost real CPU for no visible gain.
    aw, ah = FRAME_W, FRAME_H
    z_e = f"(1/({w_e}))"
    x_e = f"clip({aw}*({cx_e})-({aw})*({w_e})/2,0,{aw}-{aw}*({w_e}))"
    y_e = f"clip({ah}*({cy_e})-({ah})*({w_e})/2,0,{ah}-{ah}*({w_e}))"
    frag = (f"zoompan=z='{z_e}':x='{x_e}':y='{y_e}':d={n}:s={aw}x{ah}:fps={fps},"
            f"setsar=1")
    return frag, n, prim


def fade_filter(direction="in", start=0.0, dur=0.5):
    d = "in" if str(direction).lower() in ("in", "from", "from_black") else "out"
    return f"fade=t={d}:st={float(start):.3f}:d={float(dur):.3f}"


# ----------------------------- QA-side helpers --------------------------------

def sample_trajectory(camera, duration_s, fps=FPS, samples=240):
    """Return lists (w, cx, cy) sampled at `samples` evenly-spaced progress
    values in [0,1]. Used by motion_qa to measure frame-to-frame
    displacement, velocity, acceleration, direction reversals."""
    prim, f, t, curve, _ = resolve_camera(camera)
    if samples < 4:
        samples = 4
    out_w, out_cx, out_cy = [], [], []
    for i in range(samples):
        p = i / (samples - 1)
        if prim == "HOLD":
            pe = 0.0
        else:
            pe = _pe_numeric(curve, p)
        out_w.append(f["w"] + (t["w"] - f["w"]) * pe)
        out_cx.append(f["cx"] + (t["cx"] - f["cx"]) * pe)
        out_cy.append(f["cy"] + (t["cy"] - f["cy"]) * pe)
    return out_w, out_cx, out_cy
