"""V15 — shot grammars: (BVP shot + plates + word timing) -> Scene IR.

One Scene IR scene per SHOT (2-3 per beat), so every picture change has its
own purposeful camera move and its own §24/§25 cache entry. Grammar names map
onto the existing §9 library so the validator, cache and renderers are
unchanged:

  plate         -> RICH_ILLUSTRATED_SCENE   AI plate world (overscanned) +
                   feathered subject cutout band (subtle parallax) + camera
                   move aimed at the subject centroid + headline / giant
                   number / leader label revealed ON THEIR WORDS
  zoom_through  -> SCALE_DIVE               2-4 plates: the current level
                   zooms past the camera and fades while the next level grows
                   from the centre (continuous zoom-through, §17 scale
                   transformation); level label pops on its word
  process       -> PROCESS_FLOW             dimmed plate + 2-4 causal step
                   chips with drawn connectors, each revealed on its word

Every shot gets the bible finish layer (grain + vignette). All on-screen text
is fitted with the real font metrics (engine.textfit) and its rendered box is
recorded in spec.meta.text_boxes for the gate's bounds/caption-band check.
Ink colour per text is chosen from the measured plate luminance of its zone
(dark ink on light plates, light ink on dark) — deterministic.

When a shot has no plate (every image provider failed) it degrades to the
V14 procedural subject with the bible gradient (asset_tier="procedural"),
recorded in meta — never silent.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from engine.brand import rail_safe_x1
from engine.grammars.base import (WORLD_H, WORLD_W, animation, base_spec,
                                  camera_track, layer)
from engine.textfit import (DISPLAY, TextFitError, fit_text, text_bbox,
                            text_width)
from engine.v15_style import _lum, renderer_palette

ROOT = Path(__file__).resolve().parent.parent
GRAIN = ROOT / "build" / "cache" / "v15_grain.png"
OVERSCAN = 1.12          # plate layer scale: camera moves never show edges
BG_DEPTH, SUBJ_DEPTH = 0.35, 0.6   # small parallax differential (rough masks)
CAPTION_TOP = 1440.0     # caption carrier band starts at 1464 (captions.py)
SAFE_X0, SAFE_X1 = 70.0, WORLD_W - 70.0
TOP_ZONE_Y = 230.0       # first baseline of top-zone copy
LOW_ZONE_BOTTOM = 1390.0  # last baseline of bottom-zone copy
GRAMMAR = {"plate": "RICH_ILLUSTRATED_SCENE", "zoom_through": "SCALE_DIVE",
           "process": "PROCESS_FLOW"}


class ShotError(ValueError):
    pass


PORTAL = ROOT / "build" / "cache" / "v15_portal_mask.png"


def portal_mask() -> str:
    """Feathered elliptical luminance mask: a zoom-through level arrives as
    a soft portal instead of a hard-edged picture-in-picture rectangle."""
    if not PORTAL.exists():
        PORTAL.parent.mkdir(parents=True, exist_ok=True)
        yy, xx = np.mgrid[0:480, 0:270].astype(np.float32)
        d = np.hypot((xx - 134.5) / 135.0, (yy - 239.5) / 240.0)
        a = np.clip((1.12 - d) / 0.34, 0.0, 1.0) ** 1.5
        Image.fromarray((a * 255).astype("uint8"), "L").resize(
            (int(WORLD_W), int(WORLD_H)), Image.BICUBIC).save(PORTAL)
    return str(PORTAL)


def grain_path() -> str:
    if not GRAIN.exists():
        GRAIN.parent.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(1507)
        g = (128 + rng.normal(0, 42, (1020, 570))).clip(0, 255).astype("uint8")
        Image.fromarray(g, "L").resize((1140, 1980), Image.NEAREST).save(GRAIN)
    return str(GRAIN)


# ------------------------------------------------------------ typography --

def lighten(hex_: str, min_lum: float = 150.0) -> str:
    """Raise HLS lightness (saturation kept >= 0.6) until luminance >=
    min_lum: a readable accent on dark zones/scrims that is still the bible
    hue and still distinct from light body text. Deterministic."""
    import colorsys
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    ss = max(ss, 0.6)
    for _ in range(40):
        r, g, b = colorsys.hls_to_rgb(hh, ll, ss)
        if 255 * (0.299 * r + 0.587 * g + 0.114 * b) >= min_lum or ll >= 0.9:
            break
        ll += 0.02
    return "#" + "".join(f"{round(c * 255):02X}" for c in (r, g, b))


def _inks(bible: dict, zone_lum: float) -> dict:
    p = bible["palette"]
    light_text = p["text"] if _lum(p["text"]) > _lum(p["primary"]) else p["primary"]
    dark_text = p["primary"] if _lum(p["primary"]) < _lum(p["text"]) else p["text"]
    if zone_lum >= 135:
        return {"fill": dark_text, "halo": light_text, "accent": p["accent"]}
    return {"fill": light_text, "halo": dark_text,
            "accent": lighten(p["accent"])}


def _fit_centered(text: str, y: float, size: int, min_size: int,
                  max_lines: int, spacing: float, anchor_bottom: bool,
                  max_w: float) -> tuple:
    fit = fit_text(text, max_w=max_w, size=size, min_size=min_size,
                   max_lines=max_lines, font=DISPLAY, spacing=spacing)
    lines, s = fit["lines"], fit["size"]
    yy = y - s * 1.05 * (len(lines) - 1) if anchor_bottom else y
    box = text_bbox(lines, s, WORLD_W / 2, yy, "middle", DISPLAY, spacing)
    return lines, s, yy, box


def _text_layer(lid: str, text: str, *, y: float, size: int, ink: dict,
                boxes: list, vis=None, pop: bool = False, accent: bool = False,
                max_lines: int = 3, min_size: int = 44, spacing: float = 1.5,
                anchor_bottom: bool = False) -> dict:
    max_w = SAFE_X1 - SAFE_X0 - 20
    y0 = y  # baseline reference (last baseline when anchor_bottom)
    lines, s, y, box = _fit_centered(text, y0, size, min_size, max_lines,
                                     spacing, anchor_bottom, max_w)
    # A box whose y-range dips into the right UI rail (DESIGN §7.1
    # safe_zones.right_rail) must not cross it: re-fit narrower, centred,
    # rather than clip — a clipped headline is worse than a smaller one.
    cap_x1 = rail_safe_x1(box[1], box[3], SAFE_X1)
    if box[2] > cap_x1:
        narrower = max(200.0, 2 * (cap_x1 - WORLD_W / 2) - 20)
        try:
            lines, s, y, box = _fit_centered(text, y0, size, min_size,
                                             max_lines, spacing,
                                             anchor_bottom, narrower)
        except TextFitError:
            pass  # keep the wider fit; the gate still catches a real breach
    boxes.append({"id": lid, "box": [round(v, 1) for v in box],
                  "text": " ".join(lines)})
    payload = {"lines": lines, "position": [WORLD_W / 2, y], "size": s,
               "font": "display", "anchor": "middle", "spacing": spacing,
               "fill": ink["accent"] if accent else ink["fill"],
               "stroke": ink["halo"], "stroke_w": max(3.0, s * 0.045),
               "shadow": ink["halo"] if not accent else True}
    if pop:
        payload["pop"] = True
    return layer(lid, "text", "world_typography", "vector", z=60,
                 visibility=vis, payload=payload)


def _zone(shot: dict, info: dict) -> str:
    comp = shot.get("composition", "centered")
    if comp == "subject_low":
        return "top"
    if comp == "subject_high":
        return "bottom"
    calm = (info or {}).get("calm") or {}
    if calm:
        return "top" if calm.get("top", 0) <= calm.get("bottom", 0) else "bottom"
    return "top"


def _zone_lum(info: dict, zone: str) -> float:
    return float(((info or {}).get("mean_lum") or {}).get(zone, 120.0))


def _scrim(lid: str, zone: str, ink: dict, strength: float = 0.45) -> dict:
    """Soft full-width wash behind zone copy (no hard container edges):
    halo-coloured gradient fading to transparent — legibility on busy
    plates without a template panel (§19/§20)."""
    if zone == "top":
        y0, y1, a0, a1 = 0.0, 620.0, strength, 0.0
    else:
        y0, y1, a0, a1 = 900.0, WORLD_H, 0.0, strength  # no hard edge
    steps = 12
    rects = []
    for i in range(steps):
        u = i / (steps - 1)
        rects.append({"x": 0, "y": y0 + (y1 - y0) * i / steps,
                      "w": WORLD_W, "h": (y1 - y0) / steps + 1,
                      "fill": ink["halo"], "fill_opacity": a0 + (a1 - a0) * u,
                      "stroke_w": 0})
    return layer(lid, "effect", "legibility_wash", "vector", z=55,
                 payload={"primitives": {"rects": rects},
                          "screen_space": True})


# ---------------------------------------------------------------- camera --

def _camera(kind: str, dur: float, info: dict | None) -> dict:
    tx = ty = 0.0
    if info and info.get("centroid"):
        tx = max(-160.0, min(160.0, (info["centroid"][0] - WORLD_W / 2) * 0.35))
        ty = max(-200.0, min(200.0, (info["centroid"][1] - WORLD_H / 2) * 0.25))
    E = "ease_in_out_cubic"
    if kind == "pull_out":
        kf = [{"t": 0, "scale": 1.16, "x": tx, "y": ty, "easing": E},
              {"t": dur, "scale": 1.0, "easing": E}]
        purpose = "pull back from the detail to reveal its context"
    elif kind in ("pan_left", "pan_right"):
        sgn = 1.0 if kind == "pan_right" else -1.0
        kf = [{"t": 0, "scale": 1.06, "x": -90.0 * sgn, "y": ty * 0.5, "easing": E},
              {"t": dur, "scale": 1.06, "x": 90.0 * sgn, "y": ty * 0.5,
               "easing": E}]
        purpose = "travel across the subject along the process"
    elif kind in ("rise", "descend"):
        sgn = 1.0 if kind == "descend" else -1.0
        kf = [{"t": 0, "scale": 1.06, "x": tx * 0.5, "y": -140.0 * sgn,
               "easing": E},
              {"t": dur, "scale": 1.06, "x": tx * 0.5, "y": 140.0 * sgn,
               "easing": E}]
        purpose = ("move down through the structure" if kind == "descend"
                   else "rise up the structure")
    elif kind == "punch_in":  # cut to a tighter framing of the subject
        kf = [{"t": 0, "scale": 1.26, "x": tx * 1.3, "y": ty * 1.3,
               "easing": E},
              {"t": dur, "scale": 1.36, "x": tx * 1.5, "y": ty * 1.5,
               "easing": E}]
        purpose = "cut in close on the detail the narration is naming"
    else:  # push_in
        kf = [{"t": 0, "scale": 1.0, "easing": E},
              {"t": dur, "scale": 1.15, "x": tx, "y": ty, "easing": E}]
        purpose = "push toward the subject the narration names"
    return camera_track("push_in" if kind in ("push_in", "punch_in") else
                        {"pull_out": "pull_out", "pan_left": "pan",
                         "pan_right": "pan", "rise": "travel",
                         "descend": "travel"}.get(kind, "push_in"),
                        kf, purpose)


# ----------------------------------------------------------------- layers --

def _plate_layers(plate: dict, *, prefix: str = "plate", vis=None,
                  z: int = 10, cutout: bool = True) -> list:
    out = [layer(f"{prefix}_world", "background", "world_plate", "ai_image",
                 depth=BG_DEPTH, z=z, scale=OVERSCAN, visibility=vis,
                 payload={"path": plate["path"], "fit": "cover"})]
    info = plate.get("info") or {}
    if cutout and info.get("cutout") and 0.06 <= info.get("coverage", 0) <= 0.6:
        out.append(layer(f"{prefix}_subject", "subject", "subject_band",
                         "ai_image", depth=SUBJ_DEPTH, z=z + 1, scale=OVERSCAN,
                         visibility=vis,
                         payload={"path": plate["path"], "fit": "cover",
                                  "mask": info["cutout"]}))
    return out


def _finish(bible: dict) -> dict:
    tex = bible.get("texture") or {}
    return layer("finish", "effect", "film_finish", "procedural_svg", z=95,
                 payload={"finish": {"grain": float(tex.get("grain", 0.012)),
                                     "vignette": float(tex.get("vignette", 0.25))},
                          "path": grain_path()})


def _procedural_world(bible: dict, text: str) -> list:
    """Floor tier when no plate exists: V14 procedural subject on the bible
    gradient (recorded as asset_tier=procedural)."""
    from engine.grammars.rich_illustrated import subject_layer
    from engine.v14_pipeline import _subject_kind
    p = bible["palette"]
    return [layer("bg", "background", "world_ground", "generated_gradient",
                  depth=0.0, z=0, payload={"kind": "radial",
                                           "stops": [p["secondary"], p["primary"]],
                                           "focus": [0.5, 0.42]}),
            subject_layer("subject", {"kind": _subject_kind(text),
                                      "stroke": p["text"]}, depth=0.6, z=20)]


def _label(lid: str, text: str, info: dict, t: float, dur: float,
           ink: dict, boxes: list, zone: str) -> dict | None:
    """Leader label anchored on the subject bbox edge, text on the roomier
    side, kept out of the headline zone and the caption band."""
    bb = (info or {}).get("bbox")
    if not bb:
        return None
    cx = (bb[0] + bb[2]) / 2
    ay = min(max((bb[1] + bb[3]) / 2, 640.0), 1260.0)
    side = "left" if cx > WORLD_W / 2 else "right"
    ax = bb[0] + (bb[2] - bb[0]) * (0.3 if side == "left" else 0.7)
    size = 74
    tw = text_width(text, DISPLAY, size, 3)
    tx = ax - 170 if side == "left" else ax + 170
    y0b, y1b = ay - 90 - size, ay - 90 + 10
    # cap the box's right edge to the UI rail (DESIGN §7.1 safe_zones.
    # right_rail) whenever it dips into the rail's y-range, on EITHER side —
    # a left-anchored label's right edge can breach the rail just as easily.
    rail_x1 = rail_safe_x1(y0b, y1b, SAFE_X1)
    if side == "left":
        tx = max(SAFE_X0 + tw, min(tx, rail_x1))
        box = (tx - tw, y0b, tx, y1b)
    else:
        tx = min(rail_x1 - tw, tx)
        box = (tx, y0b, tx + tw, y1b)
    if box[0] < SAFE_X0 - 1 or box[2] > rail_x1 + 1:
        return None
    boxes.append({"id": lid, "box": [round(v, 1) for v in box], "text": text})
    return layer(lid, "semantic_annotation", "key_callout", "vector", z=58,
                 visibility=[round(t, 3), dur],
                 payload={"leader_from": [ax, ay],
                          "elbow": [ax + (-80 if side == "left" else 80), ay - 90],
                          "text_at": [tx, ay - 90], "title": text,
                          "text_anchor": "end" if side == "left" else "start",
                          "fill": ink["fill"], "halo": ink["halo"],
                          "accent": ink["accent"], "font": "display",
                          "size": size, "line_w": 6, "dot_r": 14})


# ------------------------------------------------------------- compilers --

def compile_plate_shot(sc: dict, bible: dict, boxes: list, events: list) -> tuple:
    dur, plate = sc["duration"], sc["plates"][0] if sc["plates"] else None
    shot = sc["shot"]
    info = (plate or {}).get("info") or {}
    layers = _plate_layers(plate) if plate else _procedural_world(
        bible, shot.get("subject", ""))
    zone = _zone(shot, info)
    ink = _inks(bible, _zone_lum(info, zone) if plate else 60.0)
    has_copy = shot.get("headline") or shot.get("number")
    if has_copy and plate:
        layers.append(_scrim("wash", zone, ink))
    y_top = TOP_ZONE_Y + 60
    if shot.get("headline"):
        hl = _text_layer("headline", shot["headline"],
                         y=y_top if zone == "top" else LOW_ZONE_BOTTOM,
                         size=150, ink=ink, boxes=boxes, max_lines=3,
                         anchor_bottom=(zone == "bottom"),
                         vis=[0.0, dur] if sc.get("first") else [0.12, dur])
        layers.append(hl)
        if not sc.get("first"):
            events.append({"t": 0.12, "kind": "pulse", "gain": 0.6})
    if shot.get("number"):
        t = sc["t_of"](shot["number"]["word"])
        if shot.get("headline"):  # number sits in the other zone
            ny, nb = (LOW_ZONE_BOTTOM, True) if zone == "top" else (y_top + 60, False)
        else:
            ny, nb = (y_top + 60, False) if zone == "top" else (LOW_ZONE_BOTTOM, True)
        nzone = "top" if not nb else "bottom"
        nink = _inks(bible, _zone_lum(info, nzone) if plate else 60.0)
        if plate and nzone != zone or (plate and not shot.get("headline")):
            layers.append(_scrim("wash_n", nzone, nink))
        layers.append(_text_layer("number", shot["number"]["text"], y=ny,
                                  size=230, ink=nink, boxes=boxes, max_lines=2,
                                  anchor_bottom=nb, pop=True, accent=True,
                                  min_size=70, vis=[t, dur]))
        events.append({"t": t, "kind": "tick", "gain": 0.7})
    if shot.get("label") and plate:
        t = sc["t_of"](shot["label"]["word"])
        lab = _label("label", shot["label"]["text"], info, t, dur,
                     _inks(bible, float(info.get("mean_lum", {}).get("all", 120))),
                     boxes, zone)
        if lab:
            layers.append(lab)
            events.append({"t": t, "kind": "tick", "gain": 0.45})
    layers.append(_finish(bible))
    return layers, _camera(shot.get("camera", "push_in"), dur,
                           info if plate else None), []


def compile_zoom_shot(sc: dict, bible: dict, boxes: list, events: list) -> tuple:
    dur, shot = sc["duration"], sc["shot"]
    levels = shot["levels"]
    plates = sc["plates"]
    n = len(levels)
    tw = 0.45  # half transition window
    # level start times: level 0 at 0, others at their words (min spacing)
    ts = [0.0]
    for lev in levels[1:]:
        t = max(sc["t_of"](lev["word"]), ts[-1] + 1.2)
        ts.append(min(t, dur - 0.8))
    layers, anims = [], []
    p = bible["palette"]
    layers.append(layer("void", "background", "world_ground",
                        "generated_gradient", depth=0.0, z=0,
                        payload={"kind": "radial",
                                 "stops": [p["secondary"], p["primary"]],
                                 "focus": [0.5, 0.5]}))
    for i in range(n):
        t0 = ts[i]
        t1 = ts[i + 1] if i + 1 < n else dur
        vis = [max(0.0, t0 - tw), min(dur, t1 + tw) if i + 1 < n else dur]
        if vis[1] - vis[0] < 0.2:
            continue
        pl = plates[i] if i < len(plates) else None
        lid = f"L{i}"
        if pl:
            pls = _plate_layers(pl, prefix=lid, vis=vis, z=10 + 2 * i,
                                cutout=False)
            if i > 0:
                pls[0]["payload"]["mask"] = portal_mask()
            layers += pls
        else:
            layers.append(layer(f"{lid}_world", "subject", "procedural_level",
                                "generated_shape", depth=BG_DEPTH, z=10 + 2 * i,
                                visibility=vis,
                                payload={"shape": "circle", "r": 260 - 40 * i,
                                         "fill": p["secondary"],
                                         "stroke": p["text"]}))
        # grow-in from the centre, drift, then zoom past the camera + fade
        skf, okf = [], []
        if i > 0:
            skf += [{"t": vis[0], "value": 0.38, "easing": "ease_out_cubic"},
                    {"t": t0 + tw, "value": 1.0, "easing": "linear"}]
            okf += [{"t": vis[0], "value": 0.0, "easing": "ease_out_cubic"},
                    {"t": t0 + tw * 0.6, "value": 1.0, "easing": "linear"}]
        else:
            skf += [{"t": 0.0, "value": 1.0, "easing": "linear"}]
            okf += [{"t": 0.0, "value": 1.0, "easing": "linear"}]
        if i + 1 < n:
            skf += [{"t": t1 - tw, "value": 1.07, "easing": "ease_in_cubic"},
                    {"t": vis[1], "value": 3.4, "easing": "linear"}]
            okf += [{"t": t1 - tw * 0.2, "value": 1.0, "easing": "linear"},
                    {"t": vis[1], "value": 0.0, "easing": "linear"}]
        else:
            skf += [{"t": dur, "value": 1.08, "easing": "linear"}]
            okf += [{"t": dur, "value": 1.0, "easing": "linear"}]
        tgt = f"{lid}_world"
        anims.append(animation(tgt, "scale", skf,
                               "dive: this scale grows in, then zooms past "
                               "the camera into the next, smaller world"))
        anims.append(animation(tgt, "opacity", okf,
                               "hand the frame to the next scale level"))
        # level label (lower zone), pops on its word
        info = (pl or {}).get("info") or {}
        ink = _inks(bible, _zone_lum(info, "bottom") if pl else 60.0)
        lt = sc["t_of"](levels[i]["word"]) if i == 0 else t0
        layers.append(_text_layer(f"lvl{i}", levels[i]["label"],
                                  y=LOW_ZONE_BOTTOM, size=120, ink=ink,
                                  boxes=boxes, max_lines=2, anchor_bottom=True,
                                  pop=True, accent=(i == n - 1),
                                  vis=[max(0.05, lt), ts[i + 1] if i + 1 < n
                                       else dur]))
        events.append({"t": max(0.05, lt), "kind": "tick" if i < n - 1
                       else "pulse", "gain": 0.55})
        if i > 0:
            events.append({"t": max(0.0, t0 - tw), "kind": "whoosh", "gain": 0.45})
    layers.insert(1, _scrim("wash", "bottom", _inks(bible, 200.0), 0.35))
    layers.append(_finish(bible))
    cam = camera_track("scale_dive", [
        {"t": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
        {"t": dur, "scale": 1.05, "easing": "ease_in_out_cubic"}],
        "steady frame while the worlds dive through each other")
    return layers, cam, anims


def compile_process_shot(sc: dict, bible: dict, boxes: list, events: list) -> tuple:
    dur, shot = sc["duration"], sc["shot"]
    plate = sc["plates"][0] if sc["plates"] else None
    info = (plate or {}).get("info") or {}
    layers = _plate_layers(plate, cutout=False) if plate else _procedural_world(
        bible, shot.get("subject", ""))
    p = bible["palette"]
    dark_chip = _lum(p["primary"]) < _lum(p["text"])
    chip_fill = p["primary"] if dark_chip else p["text"]
    chip_ink = p["text"] if dark_chip else p["primary"]
    # dim the world so the chain reads (full-frame wash, not a panel)
    layers.append(layer("dim", "effect", "focus_dim", "vector", z=40,
                        payload={"primitives": {"rects": [
                            {"x": 0, "y": 0, "w": WORLD_W, "h": WORLD_H,
                             "fill": chip_fill, "fill_opacity": 0.28,
                             "stroke_w": 0}]}, "screen_space": True}))
    steps = shot["steps"]
    n = len(steps)
    y0, y1 = 420.0, 1250.0
    gap = (y1 - y0) / max(1, n - 1) if n > 1 else 0
    prev_t = 0.0
    span = max(0.5, dur - 0.9)
    for i, st in enumerate(steps):
        # on the step's word, but never clustered: reveals are spread so no
        # stretch of the shot holds > ~span/n without a change
        t = max(prev_t + (0.0 if i == 0 else 0.7), sc["t_of"](st["word"]),
                i * span / n)
        t = min(t, dur - 0.6)
        prev_t = t
        y = y0 + gap * i if n > 1 else (y0 + y1) / 2
        # cap the chip width so it clears the right UI rail (DESIGN §7.1)
        # whenever this row's estimated y-range dips into it; 120 px is a
        # conservative half-height bound for a 2-line, size-88 chip.
        rail_x1 = rail_safe_x1(y - 120.0, y + 120.0, WORLD_W / 2 + 425.0)
        max_w = min(760.0, 2 * (rail_x1 - WORLD_W / 2) - 90.0)
        try:
            fit = fit_text(st["text"], max_w=max_w, size=88, min_size=48,
                           max_lines=2, font=DISPLAY, spacing=2)
        except TextFitError as e:
            raise ShotError(str(e))
        lines, s = fit["lines"], fit["size"]
        bh = s * 1.05 * len(lines) + 44
        bw = fit["width"] + 90
        top = y - bh / 2
        base = top + 22 + s * 0.82
        texts = [{"x": WORLD_W / 2, "y": base + k * s * 1.05, "text": ln,
                  "size": s, "fill": chip_ink, "weight": 400,
                  "spacing": 2} for k, ln in enumerate(lines)]
        prims = {"rects": [{"x": WORLD_W / 2 - bw / 2, "y": top, "w": bw,
                            "h": bh, "rx": 18, "fill": chip_fill,
                            "fill_opacity": 0.9, "stroke": p["accent"],
                            "stroke_w": 5}],
                 "texts": texts}
        boxes.append({"id": f"step{i}", "box": [WORLD_W / 2 - bw / 2, top,
                                                 WORLD_W / 2 + bw / 2, top + bh],
                      "text": " ".join(lines)})
        lay = layer(f"step_{i}", "text", "process_stage", "vector", z=60 + i,
                    visibility=[round(t, 3), dur],
                    payload={"primitives": prims, "screen_space": True})
        # chips render with DISPLAY font through the primitives text path
        for tx in prims["texts"]:
            tx["font"] = "display"
        layers.append(lay)
        events.append({"t": t, "kind": "tick", "gain": 0.55})
        if i > 0:
            yp = y0 + gap * (i - 1)
            a0, a1 = yp + 70, y - bh / 2 - 12
            if a1 - a0 > 20:
                layers.append(layer(f"link_{i}", "effect", "causal_link",
                                    "vector", z=59, visibility=[round(t, 3), dur],
                                    payload={"screen_space": True, "primitives": {
                                        "paths": [
                                            {"d": f"M {WORLD_W/2} {a0:.0f} L {WORLD_W/2} {a1:.0f}",
                                             "stroke": p["accent"], "width": 7},
                                            {"d": f"M {WORLD_W/2-22} {a1-26:.0f} L {WORLD_W/2} {a1:.0f} L {WORLD_W/2+22} {a1-26:.0f}",
                                             "stroke": p["accent"], "width": 7}]}}))
    layers.append(_finish(bible))
    cam = _camera(shot.get("camera", "push_in") if shot.get("camera") in
                  ("pan_left", "pan_right", "rise", "descend") else "push_in",
                  dur, info if plate else None)
    return layers, cam, []


def compile_shot(sc: dict, bible: dict) -> dict:
    """sc: {scene_id, duration, shot, plates:[{path, info}], t_of(word)->s,
    first}. -> {spec, events, asset_tier}."""
    kind = sc["shot"]["kind"]
    boxes, events = [], []
    fn = {"plate": compile_plate_shot, "zoom_through": compile_zoom_shot,
          "process": compile_process_shot}[kind]
    layers, cam, anims = fn(sc, bible, boxes, events)
    spec = base_spec(GRAMMAR[kind], {"scene_id": sc["scene_id"],
                                     "duration_s": round(sc["duration"], 3)},
                     layers=layers, camera=cam, animations=anims)
    need = 1 if kind != "zoom_through" else len(sc["shot"]["levels"])
    tier = "plate" if len([p for p in sc["plates"] if p]) >= need else (
        "partial" if any(sc["plates"]) else "procedural")
    spec["meta"].update({"palette": renderer_palette(bible),
                         "fonts": bible.get("typography") or {},
                         "text_boxes": boxes, "asset_tier": tier,
                         "shot_kind": kind, "generated_by": "engine.v15_shots"})
    return {"spec": spec, "events": events, "asset_tier": tier}
