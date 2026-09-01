"""Motion grammar: camera + overlay primitives -> deterministic ffmpeg fragments.

Coordinate systems
------------------
PLATE (asset): 1536x1024. Camera windows are normalized to the plate:
  w     = visible-window width as a fraction of plate width,
  cx/cy = window center in [0, 1] plate coordinates.
The window always keeps PANEL aspect (1080x780 = 18:13), so its height
fraction on the plate is w * 1.0833. Windows with w <= 0.9231 fit fully
inside the plate; w up to 1.0 letterboxes against the pre-padded working
canvas (thin black bars top/bottom). Anything out of range is clamped
(plan.validate reports the clamps).

PANEL: the 1080x780 artwork window at frame y=460. Overlay targets and
arrow/callout points are normalized to the PANEL: x, y, w, h in [0, 1]
of 1080x780.

Everything here is pure and deterministic: no randomness, no clocks.
Camera motion is a closed-form linear interpolation written as zoompan
expressions over the output frame number `on`; overlay art is Pillow RGBA
PNGs cached under build/overlays/ with content-addressed names, composited
with enable/fade/scale expressions. All renders use -threads 1.

Primitives
----------
Camera (input camera={primitive, from:{w,cx,cy}, to:{...}}, duration, fps):
  ZOOM_IN ZOOM_OUT PAN_LEFT PAN_RIGHT PAN_UP PAN_DOWN DIAGONAL_PAN
  PUSH_IN PULL_OUT CROP_REVEAL FOCUS_REVEAL
  -> camera_filter(): one zoompan filter fragment (d = duration*30 frames).

Overlays (Pillow PNG -> timed overlay):
  HIGHLIGHT   rust rounded-rect/circle/ring; fade-in + gentle throb 1.0->1.03
  ARROW_DRAW  ink arrow drawn on along its length in 12 deterministic stages
  CALLOUT     small ink label + thin leader line; fade + 8px slide
  LIGHT_SWEEP diagonal white gradient strip (alpha 0.12) sliding across panel
  TITLE_BAND  static hook-title band PNG (built once, cached)
  NUMBER_POP  documented only: rendered by text_ass (ASS), not a PNG overlay
  IMAGE_WIPE / CROSSFADE / FADE: concat-level transitions (compose.py);
  FADE also exposes a shot-level fade_filter fragment.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FPS = 30
PANEL_W, PANEL_H = 1080, 780
PANEL_Y = 460                      # panel top inside the 1080x1920 frame
FRAME_W, FRAME_H = 1080, 1920
PLATE_W, PLATE_H = 1536, 1024
CONTENT_W, CONTENT_H = 3060, 2040  # plate placed on the working canvas
CANVAS_W, CANVAS_H = 3060, 2210    # working canvas = panel aspect (13/18)
CANVAS_PAD_Y = 85                  # (2210 - 2040) / 2 letterbox rows

CAMERA_PRIMITIVES = (
    "ZOOM_IN", "ZOOM_OUT", "PAN_LEFT", "PAN_RIGHT", "PAN_UP", "PAN_DOWN",
    "DIAGONAL_PAN", "PUSH_IN", "PULL_OUT", "CROP_REVEAL", "FOCUS_REVEAL",
)
OVERLAY_KINDS = ("HIGHLIGHT", "ARROW_DRAW", "CALLOUT", "LIGHT_SWEEP", "TITLE_BAND")
ASS_ONLY_KINDS = ("NUMBER_POP",)   # documented: NUMBER_POP is rendered by text_ass
TRANSITIONS = ("CUT", "CROSSFADE", "FADE", "IMAGE_WIPE_UP")
XFADE_MAP = {"CROSSFADE": "fade", "IMAGE_WIPE_UP": "wipeup"}
XFADE_DUR = 0.4
FADE_DUR = 0.5

RGB = {
    "parchment": (233, 223, 200), "ink": (42, 33, 24), "navy": (27, 42, 74),
    "rust": (180, 85, 45), "slate": (110, 127, 145), "offwhite": (245, 241, 232),
    "white": (255, 255, 255), "black": (0, 0, 0),
}

# Endpoint defaults per primitive; explicit from/to keys override.
# "to" inherits any key not given from the resolved "from".
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
}

# Overlay display semantics: HIGHLIGHT/CALLOUT/LIGHT_SWEEP "dur" = time on
# screen; ARROW_DRAW "dur" = reveal (draw-on) time, "hold" = extra time the
# finished arrow stays. Defaults when a cue gives neither.
DEFAULT_DUR = {"HIGHLIGHT": 2.6, "ARROW_DRAW": 0.9, "CALLOUT": 3.0, "LIGHT_SWEEP": 1.6}
DEFAULT_HOLD = {"ARROW_DRAW": 1.4}


# --------------------------------------------------------------------------
# camera grammar
# --------------------------------------------------------------------------

def clamp_window(w, cx, cy):
    """Clamp a camera window to plate+letterbox bounds. Returns (w, cx, cy)."""
    w = min(max(float(w), 0.30), 1.0)
    cx = min(max(float(cx), w / 2.0), 1.0 - w / 2.0)
    cy_lo = (CANVAS_H * w / 2.0 - CANVAS_PAD_Y) / CONTENT_H
    cy_hi = (CONTENT_H + CANVAS_PAD_Y - CANVAS_H * w / 2.0) / CONTENT_H
    cy = min(max(float(cy), cy_lo), cy_hi)
    return w, cx, cy


def resolve_camera(camera):
    """-> (primitive, from{w,cx,cy}, to{...}, notes[]). Raises on unknown
    primitive; notes list every value changed by clamping."""
    cam = camera or {}
    prim = cam.get("primitive", "ZOOM_IN")
    if prim not in CAMERA_PRIMITIVES:
        raise ValueError(f"unknown camera primitive: {prim!r}")
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
    return prim, f, t, notes


def frame_count(duration_s, fps=FPS):
    return max(1, int(round(float(duration_s) * fps)))


def camera_filter(camera, duration_s, fps=FPS):
    """-> (filter_fragment, n_frames, primitive, notes).

    Linear from->to interpolation of (w, cx, cy) expressed as closed-form
    zoompan expressions over `on`. Plate is pre-scaled to 3060x2040 and
    letterboxed onto the 3060x2210 panel-aspect canvas, so a uniform zoom
    crop maps 1:1 onto the 1080x780 panel without distortion. zoom = 1/w,
    so zoompan's integer jitter is at the 0.5-source-pixel level.
    """
    prim, f, t, notes = resolve_camera(camera)
    n = frame_count(duration_s, fps)
    p = f"clip(on/{n - 1},0,1)" if n > 1 else "0"

    def lin(a, b):
        if abs(b - a) < 1e-9:
            return f"({a:.6f})"
        return f"(({a:.6f})+(({b - a:.6f})*({p})))"

    w_e = lin(f["w"], t["w"])
    cx_e = lin(f["cx"], t["cx"])
    cy_e = lin(f["cy"], t["cy"])
    z_e = f"(1/({w_e}))"
    x_e = (f"clip({CANVAS_W}*({cx_e})-({CANVAS_W})*({w_e})/2,"
           f"0,{CANVAS_W}-{CANVAS_W}*({w_e}))")
    y_e = (f"clip({CONTENT_H}*({cy_e})+{CANVAS_PAD_Y}-({CANVAS_H})*({w_e})/2,"
           f"0,{CANVAS_H}-{CANVAS_H}*({w_e}))")
    frag = (f"scale={CONTENT_W}:{CONTENT_H}:flags=lanczos,"
            f"pad={CANVAS_W}:{CANVAS_H}:0:{CANVAS_PAD_Y}:color=black,"
            f"zoompan=z='{z_e}':x='{x_e}':y='{y_e}':d={n}:s={PANEL_W}x{PANEL_H}:fps={fps},"
            f"setsar=1")
    return frag, n, prim, notes


def fade_filter(direction="in", start=0.0, dur=FADE_DUR):
    """FADE primitive (shot-level fragment): fade from/to black."""
    d = "in" if str(direction).lower() in ("in", "from", "from_black") else "out"
    return f"fade=t={d}:st={float(start):.3f}:d={float(dur):.3f}"


# --------------------------------------------------------------------------
# overlay PNG builders (deterministic, cached under build/overlays/)
# --------------------------------------------------------------------------

def _cache_path(out_dir, prefix, payload):
    key = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return Path(out_dir) / f"{prefix}_{hashlib.sha1(key.encode()).hexdigest()[:10]}.png"


def target_px(target):
    """Panel-normalized rect -> clamped pixel rect inside the panel."""
    t = target or {}
    x = float(t.get("x", 0.30)) * PANEL_W
    y = float(t.get("y", 0.32)) * PANEL_H
    w = min(float(t.get("w", 0.40)) * PANEL_W, PANEL_W - 8)
    h = min(float(t.get("h", 0.28)) * PANEL_H, PANEL_H - 8)
    x = min(max(x, 4), PANEL_W - w - 4)
    y = min(max(y, 4), PANEL_H - h - 4)
    return x, y, w, h


def point_px(p):
    """Panel-normalized point -> panel pixel point (dict form only; named
    points are resolved by plan.py before reaching motion)."""
    if isinstance(p, dict):
        return float(p.get("x", 0.5)) * PANEL_W, float(p.get("y", 0.5)) * PANEL_H
    return 0.5 * PANEL_W, 0.5 * PANEL_H


def band_y(style):
    return int((style.get("title_band") or {}).get("y", 120))


def build_title_band(out_dir, style):
    """Static hook-title band (1080 x h, navy, 3-line Archivo Black).
    Cached; rebuilt only when ass_style.json is newer than the PNG."""
    band = style.get("title_band") or {}
    W = PANEL_W
    H = max(80, int(band.get("h", 320)))
    path = Path(out_dir) / "title_band.png"
    src = style.get("_style_path")
    if path.exists() and src and Path(src).exists() and \
            path.stat().st_mtime >= Path(src).stat().st_mtime:
        return path
    bg = RGB.get(band.get("color", "navy"), RGB["navy"])
    fg = RGB.get(band.get("text_color", "offwhite"), RGB["offwhite"])
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(style.get("_endcard_font_path")), int(band.get("font_size", 80)))
    lines = band.get("lines", ["SPACE IS", "CLOSER THAN", "YOU THINK"])
    step = int(band.get("line_step", 92))
    cy = (H - step * (len(lines) - 1)) / 2.0
    for line in lines:
        d.text((W / 2, cy), line, font=font, fill=fg, anchor="mm")
        cy += step
    img.save(path)
    return path


def build_highlight(out_dir, target, style_name="rect", color="rust"):
    """Rust rounded-rect / circle / ring at a panel-normalized target."""
    x, y, w, h = target_px(target)
    W, H = max(6, int(round(w))), max(6, int(round(h)))
    path = _cache_path(out_dir, "hl", {"t": target, "s": style_name, "c": color, "wh": [W, H]})
    if path.exists():
        return path
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = RGB.get(color, RGB["rust"])
    box = (2, 2, W - 3, H - 3)
    if style_name == "circle":
        d.ellipse(box, fill=c + (64,), outline=c + (235,), width=6)
    elif style_name == "ring":
        d.rounded_rectangle(box, radius=max(6, min(26, H // 4)), outline=c + (235,), width=8)
    else:
        d.rounded_rectangle(box, radius=max(6, min(28, H // 4)),
                            fill=c + (60,), outline=c + (235,), width=6)
    img.save(path)
    return path


def build_arrow_stages(out_dir, p0, p1, color="ink", stages=12, width=12, head=38):
    """Ink arrow revealed along its length in `stages` deterministic steps.
    -> (paths, x_px, y_px) where x/y is the overlay position in frame coords."""
    ax, ay = point_px(p0)
    bx, by = point_px(p1)
    pad = head + 16
    x0f, y0f = min(ax, bx) - pad, min(ay, by) - pad
    W = max(8, int(round(max(ax, bx) + pad - x0f)))
    H = max(8, int(round(max(ay, by) + pad - y0f)))
    c = RGB.get(color, RGB["ink"])
    base = _cache_path(out_dir, "ar", {"p": [[ax, ay], [bx, by]], "c": color,
                                        "s": stages, "wh": [W, H]})
    paths = []
    if all((Path(out_dir) / f"{base.stem}_{i:02d}.png").exists() for i in range(1, stages + 1)):
        paths = [Path(out_dir) / f"{base.stem}_{i:02d}.png" for i in range(1, stages + 1)]
        return paths, x0f, y0f
    ang = math.atan2(by - ay, bx - ax)
    for i in range(1, stages + 1):
        frac = i / stages
        ex, ey = ax + (bx - ax) * frac, ay + (by - ay) * frac
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        sx, sy = ax - x0f, ay - y0f
        dx, dy = ex - x0f, ey - y0f
        d.line([(sx, sy), (dx, dy)], fill=c + (255,), width=width)
        if frac >= 0.2:
            a1 = ang + math.radians(152)
            a2 = ang + math.radians(208)
            d.polygon([(dx, dy),
                       (dx + head * math.cos(a1), dy + head * math.sin(a1)),
                       (dx + head * math.cos(a2), dy + head * math.sin(a2))],
                      fill=c + (255,))
        p = Path(out_dir) / f"{base.stem}_{i:02d}.png"
        img.save(p)
        paths.append(p)
    return paths, x0f, y0f


def build_callout(out_dir, text, anchor=None, label=None, color="ink",
                  font_path=None, size=34):
    """Small ink label + thin leader line toward an anchor (panel px).
    -> (path, x_px, y_px) overlay position in frame coords."""
    text = str(text or "").strip() or " "
    font = ImageFont.truetype(str(font_path), size)
    pad = 14
    LW = int(font.getlength(text)) + pad * 2
    LH = size + pad + 4
    lx = float((label or {}).get("x", 0.16)) * PANEL_W
    ly = float((label or {}).get("y", 0.16)) * PANEL_H
    pts = [(lx, ly), (lx + LW, ly + LH)]
    if anchor:
        apx, apy = point_px(anchor)
        pts.append((apx, apy))
    x0 = max(0, min(p[0] for p in pts) - 10)
    y0 = max(0, min(p[1] for p in pts) - 10)
    x1 = min(PANEL_W, max(p[0] for p in pts) + 10)
    y1 = min(PANEL_H, max(p[1] for p in pts) + 10)
    W, H = max(8, int(x1 - x0)), max(8, int(y1 - y0))
    path = _cache_path(out_dir, "co", {"t": text, "a": anchor, "l": label,
                                       "c": color, "s": size, "wh": [W, H]})
    if not path.exists():
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = RGB.get(color, RGB["ink"])
        box = (lx - x0, ly - y0, lx - x0 + LW, ly - y0 + LH)
        if anchor:
            apx, apy = point_px(anchor)
            sx = min(max(apx, box[0] + 8), box[2] - 8)
            sy = box[3] if apy >= (box[1] + box[3]) / 2 else box[1]
            d.line([(sx - x0, sy - y0), (apx - x0, apy - y0)], fill=c + (220,), width=3)
            d.ellipse([apx - x0 - 5, apy - y0 - 5, apx - x0 + 5, apy - y0 + 5],
                      fill=c + (255,))
        d.rounded_rectangle(box, radius=12, fill=c + (215,))
        d.text((box[0] + pad, (box[1] + box[3]) / 2), text, font=font,
               fill=RGB["offwhite"] + (255,), anchor="lm")
        img.save(path)
    return path, x0, y0


def build_light_sweep(out_dir):
    """Full-panel diagonal white gradient strip (peak alpha 0.12). One PNG,
    reused by every LIGHT_SWEEP cue; it slides via the overlay x expression."""
    path = Path(out_dir) / "light_sweep.png"
    if path.exists():
        return path
    import numpy as np
    xs = np.arange(PANEL_W, dtype=np.float32)[None, :]
    ys = np.arange(PANEL_H, dtype=np.float32)[:, None]
    u = (xs + ys * 0.55) / float(PANEL_W + PANEL_H * 0.55)
    band = np.clip(1.0 - np.abs(u - 0.42) / 0.16, 0.0, 1.0) ** 2
    arr = np.zeros((PANEL_H, PANEL_W, 4), np.uint8)
    arr[..., 0:3] = 255
    arr[..., 3] = (band * (0.12 * 255)).astype(np.uint8)
    Image.fromarray(arr).save(path)
    return path


# --------------------------------------------------------------------------
# overlay compile: cue dict -> sublayers consumed by compose.render_shot
# --------------------------------------------------------------------------

def compile_overlay(ov, shot_dur, out_dir, style, throb_ok=True):
    """Compile one overlay cue -> list of sublayers:
    {png, pre, x, y, enable}
      png     input PNG path (becomes one -loop 1 -t dur input)
      pre     filter chain applied after format=rgba (fade / throb scale)
      x, y    overlay position EXPRESSIONS (frame coords; may use t/w/h)
      enable  t-expression or None (always on)
    """
    kind = ov.get("kind")
    if kind not in OVERLAY_KINDS:
        raise ValueError(f"unknown overlay kind: {kind!r}")
    if kind == "TITLE_BAND":
        png = build_title_band(out_dir, style)
        return [{"png": png, "pre": "", "x": "0", "y": str(band_y(style)), "enable": None}]

    shot_dur = float(shot_dur)
    t0 = min(max(float(ov.get("at", 0.0)), 0.0), max(0.0, shot_dur - 0.2))
    dur = float(ov.get("dur", DEFAULT_DUR.get(kind, 2.0)))
    t1 = min(t0 + max(0.2, dur), shot_dur)

    def fades(pre):
        pre += f",fade=t=in:st={t0:.3f}:d=0.35:alpha=1"
        if t1 < shot_dur - 0.05:
            pre += f",fade=t=out:st={max(t0, t1 - 0.25):.3f}:d=0.25:alpha=1"
        return pre

    if kind == "HIGHLIGHT":
        x, y, w, h = target_px(ov.get("target"))
        png = build_highlight(out_dir, ov.get("target"),
                              str(ov.get("style", "rect")), ov.get("color", "rust"))
        pre = ""
        x_e, y_e = f"{x:.1f}", f"{PANEL_Y + y:.1f}"
        if throb_ok:
            th = f"(1+0.015*(1-cos(2*PI*(t-{t0:.3f})/1.4)))"
            pre += f",scale=w='iw*({th})':h='ih*({th})':eval=frame"
            x_e = f"{x:.1f}-(w-{w:.0f})/2"
            y_e = f"{PANEL_Y + y:.1f}-(h-{h:.0f})/2"
        pre = fades(pre)
        return [{"png": png, "pre": pre, "x": x_e, "y": y_e,
                 "enable": f"between(t,{t0:.3f},{t1:.3f})"}]

    if kind == "ARROW_DRAW":
        p0 = ov.get("from") or {"x": 0.22, "y": 0.72}
        p1 = ov.get("to") or {"x": 0.72, "y": 0.35}
        paths, ox, oy = build_arrow_stages(out_dir, p0, p1, ov.get("color", "ink"))
        reveal = min(max(0.3, dur), max(0.3, t1 - t0))
        hold_end = min(t0 + reveal + float(ov.get("hold", DEFAULT_HOLD["ARROW_DRAW"])), shot_dur)
        step = reveal / len(paths)
        out = []
        for i, png in enumerate(paths):
            a = t0 + i * step
            b = t0 + (i + 1) * step if i < len(paths) - 1 else hold_end
            out.append({"png": png, "pre": "", "x": f"{ox:.1f}",
                        "y": f"{PANEL_Y + oy:.1f}",
                        "enable": f"between(t,{a:.3f},{b:.3f})"})
        return out

    if kind == "CALLOUT":
        png, ox, oy = build_callout(out_dir, ov.get("text", ""), anchor=ov.get("anchor"),
                                    label=ov.get("label"), color=ov.get("color", "ink"),
                                    font_path=style.get("_caption_font_path"))
        pre = fades("")
        x_e = f"{ox:.1f}+8*clip(1-(t-{t0:.3f})/0.4,0,1)"
        return [{"png": png, "pre": pre, "x": x_e, "y": f"{PANEL_Y + oy:.1f}",
                 "enable": f"between(t,{t0:.3f},{t1:.3f})"}]

    if kind == "LIGHT_SWEEP":
        png = build_light_sweep(out_dir)
        dur_s = max(0.4, t1 - t0)
        x_e = f"-{PANEL_W}+{2 * PANEL_W}*clip((t-{t0:.3f})/{dur_s:.3f},0,1)"
        return [{"png": png, "pre": "", "x": x_e, "y": str(PANEL_Y),
                 "enable": f"between(t,{t0:.3f},{t1:.3f})"}]

    raise ValueError(kind)  # unreachable
