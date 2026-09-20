"""visual_sophistication.py — V13 M6a diagnostics (NON-GATING).

Two qa8 report diagnostics per JADE_V13_RICH_VISUAL_DIRECTIVE:

- VISUAL_SOPHISTICATION: 9 sub-scores (depth, material, lighting, texture,
  context, scale, semantic_layers, subject_specificity, hierarchy).
  Each sub-score = declared component (plan representation /
  mode_justification + sidecar texture_tags / lighting / layers) blended with
  a frame-verified component ONLY when a plate PNG is resolvable. Frame
  verification uses deterministic PIL/numpy region stats INSIDE DECLARED
  LAYER REGIONS (local contrast, color richness, edge structure) — explicitly
  NOT global entropy: a cluttered diagram is not sophisticated. A CLUTTER
  PENALTY (edge density beyond what the declared tags/regions justify)
  lowers the composite, so adding objects can never raise the score.

- RICH_ASSET_COVERAGE: plate duration / total duration. No universal target;
  the point is visibility, so flat diagram-only coverage cannot hide.

Fully offline and deterministic: zero AI judge calls, zero network.
Diagnostics only: nothing here feeds publish_gate or CAN_PUBLISH
(calibration on the pilot story happens later).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:  # PIL is required for frame verification only; module imports without it
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

SCHEMA = "v13.visual_sophistication/1.0"
SUB_SCORES = ("depth", "material", "lighting", "texture", "context", "scale",
              "semantic_layers", "subject_specificity", "hierarchy")

_GENERIC_TAGS = {"illustration", "diagram", "flat", "vector"}
_PLATE_REPS = {"PLATE", "SCENE", "SCENE_PLATE", "ENVIRONMENT", "PHOTOREAL"}


# ── plan / sidecar plumbing ──────────────────────────────────────────────────

def _beats(plan):
    """Yield (beat_id, beat_dict) from dict/list beats, or a shots view.

    V13 — render-path edit plans carry `shots` (no `beats`); derive the beat
    view from shots so the diagnostics see plate-bearing beats. Representation
    preference: shot stamp -> beat_model row -> plate presence -> None.
    """
    beats = plan.get("beats") or {}
    if isinstance(beats, dict) and beats:
        for bid, b in beats.items():
            yield str(bid), (b if isinstance(b, dict) else {})
        return
    if isinstance(beats, list) and beats:
        for i, b in enumerate(beats):
            if isinstance(b, dict):
                yield str(b.get("beat_id", f"beat{i}")), b
        return
    bm = ((plan.get("beat_model") or {}).get("beats")) or {}
    for i, s in enumerate(plan.get("shots") or []):
        if not isinstance(s, dict):
            continue
        bid = str(s.get("beat_id") or s.get("shot_id") or f"shot{i}")
        row = bm.get(bid) or {}
        yield bid, {
            "beat_id": bid,
            "mode": s.get("visual_mode") or row.get("mode"),
            "representation": (s.get("representation") or row.get("representation")
                               or ("PLATE" if (s.get("plate") or s.get("plate_sidecar")) else None)),
            "mode_justification": (s.get("mode_justification")
                                   or row.get("mode_justification")),
            "duration_s": float(s.get("duration_s") or 0.0),
            "plate": s.get("plate"),
            "asset": s.get("asset"),
        }


def load_sidecars(base, limit=400):
    """Discover *.sidecar.json under a build tree (dicts, path kept in _path)."""
    out = []
    for p in sorted(Path(base).rglob("*.sidecar.json"))[:limit]:
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(d, dict):
            d["_path"] = str(p)
            out.append(d)
    return out


def _match_sidecar(beat_id, beat, sidecars):
    """Beat→sidecar by declared plate path, then beat-id substring in path."""
    want = str(beat.get("plate") or beat.get("asset") or "")
    for sc in sidecars:
        plate = str(sc.get("plate") or "")
        if want and (plate == want or plate.endswith(want)):
            return sc
    for sc in sidecars:
        if beat_id and beat_id.lower() in str(sc.get("plate", "")).lower():
            return sc
    return None


def _resolve_png(beat_id, sc, sample_frames):
    """Resolve a beat's plate PNG: explicit sample_frames first, then paths."""
    if sample_frames:
        for key in (str(sc.get("plate") or ""), beat_id):
            v = sample_frames.get(key)
            if v is None:
                continue
            if isinstance(v, np.ndarray):
                return v
            p = Path(v)
            if p.exists():
                return _imread(p)
    if sc is None:
        return None
    plate = str(sc.get("plate") or "")
    if not plate:
        return None
    bases = [Path(plate), Path("build") / plate,
             Path(sc.get("_path", "x")).parent / Path(plate).name,
             Path("illustrated_engine") / plate, Path("..") / plate]
    for p in bases:
        if p.exists():
            return _imread(p)
    return None


def _imread(path):
    if Image is None:
        return None
    try:
        return np.asarray(Image.open(path).convert("RGB"),
                          dtype=np.float64) / 255.0
    except Exception:
        return None


# ── deterministic region stats (NOT global entropy) ──────────────────────────

def _lum(arr):
    return arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114


def _grad_mag(lum):
    gx = np.zeros_like(lum)
    gy = np.zeros_like(lum)
    gx[:, :-1] = np.abs(np.diff(lum, axis=1))
    gy[:-1, :] = np.abs(np.diff(lum, axis=0))
    return gx + gy


def _hf(arr):
    """Mean gradient magnitude (local high-frequency detail) in a region."""
    if arr.size == 0:
        return 0.0
    return float(_grad_mag(_lum(arr)).mean())


def _edge_frac(arr, thr=0.08):
    if arr.size == 0:
        return 0.0
    return float((_grad_mag(_lum(arr)) > thr).mean())


def _lf_std(arr, grid=6):
    """Large-scale luminance variation (block means) — smooth lighting/gradients."""
    if arr.size == 0:
        return 0.0
    lum = _lum(arr)
    h, w = lum.shape
    cells = [float(lum[i * h // grid:(i + 1) * h // grid,
                         j * w // grid:(j + 1) * w // grid].mean())
             for i in range(grid) for j in range(grid)]
    return float(np.std(cells))


def _color_richness(arr):
    """Within-region color variety: mean saturation + channel-mean spread."""
    if arr.size == 0:
        return 0.0
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    sat = np.divide(mx - mn, np.maximum(mx, 1e-3)).mean()
    spread = float(np.std(arr.reshape(-1, 3).mean(axis=0)))
    return float(min(1.0, 0.6 * sat + 1.5 * spread))


def _clip01(x):
    return float(max(0.0, min(1.0, x)))


def _crop(arr, bbox):
    if arr is None or not bbox:
        return None
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in bbox]
    x0, y0 = max(0, min(w - 1, x0)), max(0, min(h - 1, y0))
    x1, y1 = max(x0 + 1, min(w, x1)), max(y0 + 1, min(h, y1))
    return arr[y0:y1, x0:x1]


# ── declared components (plan + sidecar text) ────────────────────────────────

def _just(beat):
    return str(beat.get("mode_justification") or "").lower()


def _has(text, words):
    return any(w in text for w in words)


def _declared_depth(beat, sc):
    layers = (sc or {}).get("layers") or []
    pw = [float(l.get("parallax_weight") or 0) for l in layers
          if isinstance(l, dict)]
    spread = (max(pw) - min(pw)) if len(pw) >= 2 else 0.0
    score = _clip01(0.2 * (len(layers) - 1) + 0.6 * spread
                    + (0.2 if (sc or {}).get("depth_map") else 0.0))
    ev = f"{len(layers)} layers, parallax spread {spread:.2f}"
    if _has(_just(beat), ("depth", "foreground", "background", "parallax")):
        score = _clip01(score + 0.15)
        ev += "; justification cites depth"
    return score, ev


def _declared_material(beat, sc):
    tags = [t for t in ((sc or {}).get("texture_tags") or [])
            if str(t).lower() not in _GENERIC_TAGS]
    score = _clip01(0.34 * len(tags))
    ev = f"texture_tags {tags or ['(none/generic)']}"
    if _has(_just(beat), ("material", "surface", "metal", "wood", "fabric",
                          "stone", "brass", "grain")):
        score = _clip01(score + 0.25)
        ev += "; justification cites material"
    return score, ev


def _declared_lighting(beat, sc):
    light = str((sc or {}).get("lighting") or "").lower()
    if not light:
        return 0.1, "no lighting declared"
    dir_words = ("upper", "lower", "left", "right", "key", "rim", "backlit",
                 "side", "warm", "cool", "vignette", "gradient", "falloff")
    n = sum(1 for w in dir_words if w in light)
    return _clip01(0.35 + 0.16 * n), f"lighting '{light}' ({n} directional cues)"


def _declared_texture(beat, sc):
    tags = list((sc or {}).get("texture_tags") or [])
    real = [t for t in tags if str(t).lower() not in _GENERIC_TAGS]
    score = _clip01(0.25 * len(real) + 0.08 * (len(tags) - len(real)))
    return score, f"texture_tags {tags or ['(none)']}"


def _declared_context(beat, sc):
    rep = str(beat.get("representation") or "DIAGRAM").upper()
    score, ev = 0.15, f"representation {rep}"
    if rep in _PLATE_REPS:
        score, ev = 0.6, ev + " (environmental representation)"
    if (sc or {}).get("asset_class", "").upper() == "PLATE":
        score = _clip01(score + 0.25)
        ev += "; sidecar asset_class PLATE"
    if _has(_just(beat), ("environment", "setting", "scene", "world",
                          "surroundings", "location")):
        score = _clip01(score + 0.15)
        ev += "; justification cites setting"
    return score, ev


def _declared_scale(beat, sc):
    zoom = float(((sc or {}).get("zoom_safe") or {}).get("max_scale") or 0)
    score = 0.2 + (0.3 if zoom >= 1.3 else 0.0)
    ev = f"zoom_safe.max_scale {zoom or '(none)'}"
    if _has(_just(beat), ("scale", "size", "huge", "tiny", "massive", "dwarf",
                          "towering", "microscopic")):
        score = _clip01(score + 0.5)
        ev += "; justification cites scale"
    return _clip01(score), ev


def _declared_semantic_layers(beat, sc):
    layers = (sc or {}).get("layers") or []
    names = [str(l.get("name") or "") for l in layers if isinstance(l, dict)]
    rects = (sc or {}).get("annotation_rects_px") or []
    score = _clip01(0.25 * len(set(n for n in names if n)) + 0.15 * bool(rects))
    return score, f"layers {names or ['(none)']}, {len(rects)} annotation rects"


def _declared_subject(beat, sc):
    bbox = (sc or {}).get("subject_bbox_px")
    if not bbox:
        return 0.15, "no subject_bbox_px declared"
    w = max(0.0, float(bbox[2]) - float(bbox[0]))
    h = max(0.0, float(bbox[3]) - float(bbox[1]))
    frac = w * h
    score = 0.5 + (0.3 if 0.03 <= frac <= 0.75 else 0.0)
    ev = f"subject bbox frac {frac:.2f}"
    if _just(beat):
        score = _clip01(score + 0.2)
        ev += "; mode_justification present"
    return _clip01(score), ev


def _declared_hierarchy(beat, sc):
    layers = [l for l in ((sc or {}).get("layers") or []) if isinstance(l, dict)]
    pw = [float(l.get("parallax_weight") or 0) for l in layers]
    if len(pw) >= 2 and max(pw) - min(pw) >= 0.3:
        order = sorted(layers, key=lambda l: -float(l.get("parallax_weight") or 0))
        return 0.9, f"parallax ordering {[l.get('name') for l in order]}"
    if len(pw) >= 2:
        return 0.4, "layers present, flat parallax weights"
    return 0.2, "no layered hierarchy declared"


# ── frame-verified components (declared regions only) ────────────────────────

def _frame_components(img, sc):
    """Deterministic per-sub-score frame evidence inside DECLARED regions."""
    lum = _lum(img)
    grad = _grad_mag(lum)
    bbox = (sc or {}).get("subject_bbox_px")
    inside = _crop(img, bbox)
    if bbox:
        mask = np.ones(lum.shape, dtype=bool)
        x0, y0, x1, y1 = [int(round(v)) for v in bbox]
        mask[max(0, y0):y1, max(0, x0):x1] = False
        outside_g = grad[mask]
        outside_img = img[mask]
    else:
        outside_g = grad.ravel()
        outside_img = img.reshape(-1, img.shape[-1])

    hf_in, hf_out = _hf(inside) if inside is not None else 0.0, float(outside_g.mean())
    eps = 1e-4

    plane = (_clip01(abs(hf_in - hf_out) / (hf_in + hf_out + eps))
             if inside is not None else 0.0)
    vert = _clip01(abs(lum[:lum.shape[0] // 3].mean()
                       - lum[2 * lum.shape[0] // 3:].mean()) / 0.5)
    depth = _clip01(0.6 * plane + 0.4 * vert)

    material = _clip01(
        0.5 * _color_richness(inside if inside is not None else img)
        + 0.5 * (min(1.0, hf_in / 0.06) if inside is not None else 0.0))
    lf = _lf_std(img)
    lighting = _clip01(lf / (lf + hf_out + 0.01)) if lf > 0.02 else 0.0
    texture = min(1.0, hf_in / 0.08)  # hard cap: more objects cannot raise it

    ctx = 0.0
    if outside_img.size:
        n = min(4096, outside_img.shape[0])
        side = max(2, int(np.sqrt(n)))
        samp = outside_img[:side * side].reshape(side, side, 3)
        ctx = _clip01(0.5 * min(1.0, float((outside_g > 0.08).mean()) / 0.25)
                      + 0.5 * min(1.0, _lf_std(samp) / 0.04))

    h, w = lum.shape
    frac = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / (h * w)) if bbox else 0.0
    if frac <= 0.0:
        scale = 0.0
    elif frac < 0.12:
        scale = _clip01((frac - 0.02) / 0.10)
    elif frac <= 0.55:
        scale = 1.0
    else:
        scale = _clip01(1.0 - (frac - 0.55) / 0.25)

    layers = [l for l in ((sc or {}).get("layers") or []) if isinstance(l, dict)]
    distinct = [l for l in layers
                if (int(l.get("bbox_px", [0, 0, 0, 0])[2])
                    - int(l.get("bbox_px", [0, 0, 0, 0])[0]))
                * (int(l.get("bbox_px", [0, 0, 0, 0])[3])
                   - int(l.get("bbox_px", [0, 0, 0, 0])[1])) < 0.98 * h * w]
    if distinct:
        ok = 0
        for l in distinct:
            r = _crop(img, l.get("bbox_px"))
            if r is not None and abs(float(_lum(r).mean()) - float(lum.mean())) >= 0.12:
                ok += 1
        semantic = _clip01(ok / len(distinct))
    else:
        semantic = 0.0

    if inside is not None and outside_g.size:
        spec = _clip01(2.0 * (hf_in - hf_out) / (hf_in + hf_out + eps))
        e_in = float(grad[~mask].mean()) if (~mask).any() else 0.0
        share = e_in / (e_in + float(outside_g.mean()) + eps)
        hier = _clip01((share - 0.3) / 0.4)
    else:
        spec = hier = 0.0

    return {"depth": depth, "material": material, "lighting": lighting,
            "texture": texture, "context": ctx, "scale": scale,
            "semantic_layers": semantic, "subject_specificity": spec,
            "hierarchy": hier}


def _clutter(img, sc):
    """Edge density beyond what declared regions/tags justify (0..1).

    Declared content regions = non-background layer bboxes + subject bbox +
    annotation rects; they own the texture budget. High-frequency edges
    appearing OUTSIDE them are unexplained objects -> clutter. Adding
    objects can therefore never raise the score, only lower it.
    """
    grad = _grad_mag(_lum(img))
    h, w = grad.shape
    declared = np.zeros(grad.shape, dtype=bool)
    for l in (sc or {}).get("layers") or []:
        if not isinstance(l, dict):
            continue
        b = l.get("bbox_px")
        if not b or str(l.get("name") or "").upper() == "BACKGROUND":
            continue
        if (b[2] - b[0]) * (b[3] - b[1]) >= 0.98 * h * w:
            continue  # full-frame layer declares nothing
        x0, y0, x1, y1 = [int(round(v)) for v in b]
        declared[max(0, y0):y1, max(0, x0):x1] = True
    rects = [(sc or {}).get("subject_bbox_px")]
    rects += list((sc or {}).get("annotation_rects_px") or [])
    for b in rects:
        if b:
            x0, y0, x1, y1 = [int(round(v)) for v in b]
            declared[max(0, y0):y1, max(0, x0):x1] = True
    if declared.any():
        out = grad[~declared] > 0.08
        out_frac = float(out.mean()) if out.size else 0.0
    else:
        out_frac = float((grad > 0.08).mean())
    hf_frame = float(grad.mean())
    tags = len((sc or {}).get("texture_tags") or [])
    cap = min(0.55, 0.30 + 0.04 * tags)
    excess = max(0.0, hf_frame - cap) / 0.25
    busy_bg = max(0.0, out_frac - 0.03) / 0.10
    return _clip01(0.6 * excess + 0.4 * busy_bg), hf_frame, cap


# ── public API ────────────────────────────────────────────────────────────────

def assess(plan, sidecars, sample_frames=None):
    """VISUAL_SOPHISTICATION diagnostic. Non-gating; deterministic; offline."""
    sidecars = [sc for sc in (sidecars or []) if isinstance(sc, dict)]
    sample_frames = sample_frames or {}
    per_beat = []
    acc = {k: [] for k in SUB_SCORES}
    evid = {k: [] for k in SUB_SCORES}
    clutter_vals, hf_vals, cap_vals = [], [], []
    n_frames = 0

    for bid, beat in _beats(plan):
        sc = _match_sidecar(bid, beat, sidecars)
        decl = {
            "depth": _declared_depth(beat, sc),
            "material": _declared_material(beat, sc),
            "lighting": _declared_lighting(beat, sc),
            "texture": _declared_texture(beat, sc),
            "context": _declared_context(beat, sc),
            "scale": _declared_scale(beat, sc),
            "semantic_layers": _declared_semantic_layers(beat, sc),
            "subject_specificity": _declared_subject(beat, sc),
            "hierarchy": _declared_hierarchy(beat, sc),
        }
        img = _resolve_png(bid, sc, sample_frames)
        frame = _frame_components(img, sc) if img is not None else None
        if img is not None:
            n_frames += 1
            c, hf, cap = _clutter(img, sc)
            clutter_vals.append(c)
            hf_vals.append(hf)
            cap_vals.append(cap)
        row = {"beat": bid, "composite": 0.0, "clutter": None}
        for k in SUB_SCORES:
            d, d_ev = decl[k]
            if frame is None:
                v = d
                ev = f"{bid}: declared {d_ev}"
            else:
                v = 0.5 * d + 0.5 * frame[k]
                ev = (f"{bid}: declared {d_ev}; frame {frame[k]:.2f}")
            acc[k].append(v)
            evid[k].append(ev)
            row[k] = round(v, 3)
        row["composite"] = round(float(np.mean([acc[k][-1] for k in SUB_SCORES])), 3)
        per_beat.append(row)

    if not acc["depth"]:  # no beats -> neutral-zero diagnostic
        return {"schema": SCHEMA, "composite": 0.0, "sub_scores": {},
                "clutter_penalty": 0.0, "beats_assessed": 0,
                "frames_verified": 0, "notes": "no beats in plan"}

    penalty = float(np.mean(clutter_vals)) * 0.5 if clutter_vals else 0.0
    base = float(np.mean([np.mean(acc[k]) for k in SUB_SCORES]))
    composite = _clip01(base * (1.0 - penalty))

    return {
        "schema": SCHEMA,
        "composite": round(composite, 3),
        "clutter_penalty": round(penalty, 3),
        "clutter": ({"mean_edge_density": round(float(np.mean(hf_vals)), 4),
                     "cap": round(float(np.mean(cap_vals)), 3)}
                    if hf_vals else None),
        "sub_scores": {k: {
            "score": round(float(np.mean(acc[k])), 3),
            "evidence": " | ".join(evid[k][:4])} for k in SUB_SCORES},
        "beats_assessed": len(per_beat),
        "frames_verified": n_frames,
        "per_beat": per_beat,
        "notes": ("non-gating diagnostic; declared+frame hybrid on declared "
                  "regions, never raw entropy; clutter-penalized; zero AI calls"),
    }


def rich_asset_coverage(plan, sidecars):
    """RICH_ASSET_COVERAGE: plate duration / total duration (+ per-beat map)."""
    sidecars = [sc for sc in (sidecars or []) if isinstance(sc, dict)]
    plate_s = total_s = 0.0
    per_beat = []
    for bid, beat in _beats(plan):
        rep = str(beat.get("representation") or "DIAGRAM")
        dur = float(beat.get("duration_s") or 0)
        sc = _match_sidecar(bid, beat, sidecars)
        is_plate = (((sc or {}).get("asset_class") or "").upper() == "PLATE"
                    or rep.upper() in _PLATE_REPS)
        total_s += dur
        if is_plate:
            plate_s += dur
        per_beat.append({"beat": bid, "representation": rep,
                         "duration_s": round(dur, 3)})
    return {
        "plate_duration_s": round(plate_s, 3),
        "total_duration_s": round(total_s, 3),
        "ratio": round(plate_s / total_s, 3) if total_s > 0 else 0.0,
        "per_beat": per_beat,
        "notes": ("visibility diagnostic, no universal target; flat "
                  "diagram-only coverage must not dominate"),
    }
