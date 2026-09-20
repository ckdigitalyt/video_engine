"""V13 M2 — final-transform safe-area QA (docs/v13/V13_PLAN.md Contract 1).

Projects sidecar annotation/subject bboxes through the FINAL camera window
per sampled frame; any semantic element clipped by the crop window
(edge_cross), violating the safe margin, or overlapping another annotation
(overlap) fails the publish-gate component `safe_area_final` (P0 ->
CAN_PUBLISH=false).

Self-contained + deterministic: no model calls, no ffmpeg, numpy/PIL only
(PIL used only to probe plate dimensions when no explicit size is given).

Rects live in source-plate pixel space (Contract 1: plates are 2160x3840).
The camera window is the normalized crop window {w, cx, cy} emitted by the
v6 camera filter; window aspect == canvas aspect, so the window's height
fraction equals its width fraction `w`. Mapping assumption: plate -> canvas
1:1 (V10 native 9:16 portrait); supply render_size/plate_size for a uniform
cover-fit mapping. Motion interpolation is linear at sampled t (task spec:
crop_reveal linear interpolation, push/pull linear zoom).
"""
from __future__ import annotations

from typing import Any

SIDECAR_SCHEMA = "v13-plate-sidecar@1"
DEFAULT_CANVAS = (2160.0, 3840.0)   # Contract 1: source plates are 2160x3840
DEFAULT_MARGIN_PX = 40.0
DEFAULT_SAMPLES = (0.1, 0.3, 0.5, 0.7, 0.9)


# ---------------------------------------------------------------- rects ---

def _xyxy(raw: Any) -> list[float] | None:
    """Normalize a bbox to [x0, y0, x1, y1] floats; None when unusable."""
    try:
        v = [float(x) for x in list(raw)]
    except (TypeError, ValueError):
        return None
    if len(v) != 4:
        return None
    x0, y0, x1, y1 = v
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return [x0, y0, x1, y1]


def load_rects(sidecar_or_plan: dict) -> list[tuple[str, str, list[float]]]:
    """-> [(id, kind, bbox_px[x0,y0,x1,y1])].

    Sidecar schema v13-plate-sidecar@1: reads ``annotation_rects_px`` and
    ``subject_bbox_px``. Legacy fallback: planv8 ``key_number_rect``
    (normalized [x, y, w, h]) scaled onto the plate canvas.
    """
    d = sidecar_or_plan or {}
    if str(d.get("schema", "")).startswith("v13-plate-sidecar") \
            or "annotation_rects_px" in d:
        rects: list[tuple[str, str, list[float]]] = []
        for r in d.get("annotation_rects_px") or []:
            bbox = _xyxy((r or {}).get("bbox"))
            if bbox:
                rects.append((str(r.get("id") or "annotation"),
                              str(r.get("kind") or "annotation"), bbox))
        subj = _xyxy(d.get("subject_bbox_px"))
        if subj:
            rects.append(("subject", "subject", subj))
        return rects
    # Legacy planv8 path: declared key number rect is normalized [x, y, w, h].
    knr = d.get("key_number_rect")
    bbox = None
    try:
        x, y, w, h = [float(v) for v in list(knr)]
        cw, ch = _canvas_size(d)
        bbox = _xyxy([x * cw, y * ch, (x + w) * cw, (y + h) * ch])
    except (TypeError, ValueError):
        bbox = None
    return [("key_number", "number", bbox)] if bbox else []


def _canvas_size(meta: dict) -> tuple[float, float]:
    for key in ("canvas_px", "plate_size"):
        v = meta.get(key)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            try:
                return (float(v[0]), float(v[1]))
            except (TypeError, ValueError):
                pass
    p = meta.get("plate")
    if p:
        try:
            from PIL import Image  # optional probe; numpy/PIL only
            with Image.open(str(p)) as im:
                return (float(im.size[0]), float(im.size[1]))
        except Exception:
            pass
    return DEFAULT_CANVAS


# --------------------------------------------------------------- camera ---

def _clamp_win(w: float, cx: float, cy: float) -> tuple[float, float, float]:
    """Same bounds philosophy as motion_v6.clamp_window (generic form)."""
    w = min(max(float(w), 0.30), 1.0)
    cx = min(max(float(cx), w / 2.0), 1.0 - w / 2.0)
    cy = min(max(float(cy), w / 2.0), 1.0 - w / 2.0)
    return w, cx, cy


def _win_at(camera_params: dict, t: float) -> tuple[float, float, float]:
    """Window (w, cx, cy) at normalized shot time t in [0, 1].

    Accepted shapes (renderer-global, no per-story hardcoding):
      {"w":..,"cx":..,"cy":..}                         static window
      {"start":{...},"end":{...}}                      linear start->end
      {"windows":[{"t":..,"w":..,"cx":..,"cy":..}]}    keyframed, piecewise
    Missing channels default to a centered w=0.85 window.
    """
    cam = camera_params or {}
    wins = cam.get("windows")
    if isinstance(wins, list) and wins:
        pts = sorted(
            (dict(w=float(e.get("w", 0.85)), cx=float(e.get("cx", 0.5)),
                  cy=float(e.get("cy", 0.5)), t=float(e.get("t", 0.0)))
             for e in wins if isinstance(e, dict)),
            key=lambda e: e["t"])
        if t <= pts[0]["t"]:
            p = pts[0]
        elif t >= pts[-1]["t"]:
            p = pts[-1]
        else:
            a, b = pts[0], pts[-1]
            for i in range(len(pts) - 1):
                if pts[i]["t"] <= t <= pts[i + 1]["t"]:
                    a, b = pts[i], pts[i + 1]
                    break
            u = (t - a["t"]) / max(b["t"] - a["t"], 1e-9)
            p = {k: a[k] + (b[k] - a[k]) * u for k in ("w", "cx", "cy")}
        return _clamp_win(p["w"], p["cx"], p["cy"])
    start = cam.get("start") or cam.get("from")
    end = cam.get("end") or cam.get("to")
    if isinstance(start, dict) or isinstance(end, dict):
        start = start if isinstance(start, dict) else end
        end = end if isinstance(end, dict) else start
        u = min(max(float(t), 0.0), 1.0)

        def _chan(a: dict, b: dict, key: str, default: float) -> float:
            av = float(a.get(key, default))
            bv = float(b.get(key, default))
            return av + (bv - av) * u

        return _clamp_win(_chan(start, end, "w", 0.85),
                          _chan(start, end, "cx", 0.5),
                          _chan(start, end, "cy", 0.5))
    return _clamp_win(cam.get("w", 0.85), cam.get("cx", 0.5), cam.get("cy", 0.5))


def project_bbox(bbox: list[float], camera_params: dict, t: float,
                 plate_size: tuple[float, float] | None = None,
                 render_size: tuple[float, float] | None = None) -> dict:
    """Project a source-plate px bbox through the final camera window at t.

    Returns {"bbox": final-frame px [x0,y0,x1,y1], "frame": [fw, fh],
    "window": canvas-px [wx0, wy0, ww, wh]}. The final frame IS the crop
    window (1 canvas px = 1 final-frame px), so edge/margin checks compare
    the projected bbox against [0, fw] x [0, fh].
    """
    pw, ph = plate_size or (None, None)
    if not (pw and ph):
        pw = ph = None
    cw, ch = render_size or (pw, ph) or DEFAULT_CANVAS
    px, py, qx, qy = [float(v) for v in bbox]
    if pw and ph and render_size:
        s = max(cw / pw, ch / ph)          # cover fit
        ox = (pw * s - cw) / 2.0
        oy = (ph * s - ch) / 2.0
        px, py, qx, qy = px * s - ox, py * s - oy, qx * s - ox, qy * s - oy
    w, cx, cy = _win_at(camera_params, t)
    wx0, wy0 = (cx - w / 2.0) * cw, (cy - w / 2.0) * ch
    ww, wh = w * cw, w * ch                 # window aspect == canvas aspect
    return {"bbox": [px - wx0, py - wy0, qx - wx0, qy - wy0],
            "frame": [ww, wh], "window": [wx0, wy0, ww, wh]}


# ------------------------------------------------------------- evaluate ---

def evaluate(plate_meta: dict, camera_params: dict,
             samples=DEFAULT_SAMPLES) -> dict:
    """Safe-area QA over sampled final frames.

    -> {"passed": bool, "violations": [{id, kind, frame, reason, detail}], ...}
    reason: edge_cross (clipped by crop window) | margin (within
    safe_margin_px of the final-frame edge) | overlap (annotation x
    annotation collision in plate space; transform-invariant for a rigid
    window crop).
    """
    meta = plate_meta or {}
    ts = (samples,) if isinstance(samples, (int, float)) else \
        tuple(float(x) for x in (samples or DEFAULT_SAMPLES))
    ts = tuple(sorted(min(max(t, 0.0), 1.0) for t in ts))
    rects = load_rects(meta)
    margin = float(meta.get("safe_margin_px", DEFAULT_MARGIN_PX) or 0)
    canvas = _canvas_size(meta)
    render = meta.get("render_size") or None
    violations: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(rid: str, kind: str, t: float, reason: str, detail: str) -> None:
        key = (rid, reason)
        if key in seen:
            return
        seen.add(key)
        violations.append({"id": rid, "kind": kind, "frame": t,
                           "reason": reason, "detail": detail})

    for t in ts:
        for rid, kind, bbox in rects:
            proj = project_bbox(bbox, camera_params, t,
                                plate_size=canvas, render_size=render)
            x0, y0, x1, y1 = proj["bbox"]
            fw, fh = proj["frame"]
            dists = (x0, y0, fw - x1, fh - y1)
            if min(dists) < 0:
                edges = []
                for name, d in zip(("left", "top", "right", "bottom"), dists):
                    if d < 0:
                        edges.append("%s(%.1fpx out)" % (name, -d))
                _add(rid, kind, t, "edge_cross",
                     "clipped by crop window at t=%.2f: %s" % (t, ",".join(edges)))
            elif margin > 0 and min(dists) < margin:
                _add(rid, kind, t, "margin",
                     "only %.1fpx from final-frame edge at t=%.2f "
                     "(margin %.0fpx)" % (min(dists), t, margin))
    # Overlap: annotations vs annotations (subject overlap is intentional
    # layering — arrows/labels point at subjects — and is not a defect).
    anns = [(rid, bbox) for rid, kind, bbox in rects if kind != "subject"]
    for i in range(len(anns)):
        for j in range(i + 1, len(anns)):
            (ida, ba), (idb, bb) = anns[i], anns[j]
            ix = min(ba[2], bb[2]) - max(ba[0], bb[0])
            iy = min(ba[3], bb[3]) - max(ba[1], bb[1])
            if ix > 0.5 and iy > 0.5:
                _add(ida, "annotation", ts[0] if ts else 0.0, "overlap",
                     "overlaps %s by %.0fx%.0fpx" % (idb, ix, iy))
    return {"schema": "v13.safe_area/1.0", "component": "safe_area_final",
            "passed": not violations, "violations": violations[:64],
            "n_violations": len(violations), "sampled_ts": list(ts),
            "canvas_px": [canvas[0], canvas[1]], "margin_px": margin,
            "n_rects": len(rects)}


# ------------------------------------------------------------- self-test ---

if __name__ == "__main__":
    # Case 1 — FAIL: annotation near the left edge, PUSH_IN zoompan drives
    # the crop window inward so the rect is pushed off-canvas.
    fail_sidecar = {
        "schema": SIDECAR_SCHEMA,
        "plate": "build/plates/fake/beat/asset.png",  # absent -> 2160x3840
        "canvas_px": [2160, 3840],
        "subject_bbox_px": [800, 1500, 1400, 2300],
        "annotation_rects_px": [
            {"id": "label-1", "kind": "label", "bbox": [20, 1800, 500, 2100]},
        ],
        "safe_margin_px": 40,
    }
    push_in = {"primitive": "PUSH_IN",
               "start": {"w": 0.95, "cx": 0.5, "cy": 0.5},
               "end": {"w": 0.55, "cx": 0.5, "cy": 0.5}}
    r_fail = evaluate(fail_sidecar, push_in)
    print("FAIL-case: passed=%s n_violations=%d first=%s" % (
        r_fail["passed"], r_fail["n_violations"],
        (r_fail["violations"] or [{}])[0]))

    # Case 2 — PASS: static camera, all rects well inside the safe area.
    ok_sidecar = dict(fail_sidecar)
    ok_sidecar["annotation_rects_px"] = [
        {"id": "label-1", "kind": "label", "bbox": [700, 2000, 1300, 2400]},
    ]
    static = {"w": 0.85, "cx": 0.5, "cy": 0.5}
    r_ok = evaluate(ok_sidecar, static)
    print("PASS-case: passed=%s n_violations=%d" % (
        r_ok["passed"], r_ok["n_violations"]))

    # Case 3 — legacy planv8 fallback (normalized key_number_rect), in-spec.
    r_leg = evaluate({"key_number_rect": [0.25, 0.47, 0.25, 0.08],
                      "safe_margin_px": 40}, static)
    print("legacy-fallback: passed=%s n_rects=%d" % (
        r_leg["passed"], r_leg["n_rects"]))

    assert r_fail["passed"] is False, "expected FAIL on pushed-off-canvas rect"
    assert any(v["reason"] == "edge_cross" for v in r_fail["violations"])
    assert r_ok["passed"] is True, "expected PASS on in-spec plate"
    assert r_leg["passed"] is True, "expected PASS on legacy fallback"
    print("SELF-TEST OK (fail=%d viol, pass, legacy ok)" % r_fail["n_violations"])
