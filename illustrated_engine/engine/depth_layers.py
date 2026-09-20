"""V13 M3 — depth_layers: real-mask 2.5D depth derivation for plates.

Directive (docs/directives/JADE_V13_RICH_VISUAL_DIRECTIVE.md, P0
"DEPTH-AWARE 2.5D"): depth must become REAL masks/parallax. A blurred
background extension does NOT count as depth.

This module derives per-layer masks (BACKGROUND / MIDGROUND / SUBJECT)
for a rich-visual plate and updates the ``v13-plate-sidecar@1``
sidecar: ``layers[].mask`` + ``layers[].parallax_weight`` and
``generation.depth = {status: "derived", method, seconds, ...}``.

Route A — rembg (u2net): adopted only when importable AND the measured
per-plate runtime stays under ``REMBG_MAX_S`` (30s) on this CPU. The
first call benchmarks it; if the import fails or the run is too slow
(model download impractical), Route B is used from then on.

Route B (expected/default) — deterministic saliency: luminance-deviation
+ saturation subject mask against a border-estimated background,
morphological cleanup, edge-aware feathering (tight feather across
strong luminance edges, soft feather elsewhere), and a foreground band
split into BACKGROUND / MIDGROUND / SUBJECT. Pure numpy/PIL (cv2
optional, never required). No RNG — byte-identical output per plate.

Contract: ``derive_masks(plate_path, sidecar, sidecar_path=None)``
returns ``{"masks": {layer_name: png_path}, "method": str,
"seconds": float, "coverage": {layer_name: frac}}``. It never raises;
on any failure it returns ``method="none"`` and leaves the sidecar
untouched (the deferred_to_M3 fallback stands).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image, ImageFilter

REMBG_MAX_S = 30.0      # per-plate CPU budget for Route A (directive)
_WORK_MAX_SIDE = 720    # saliency computed at this scale, masks upscaled
_BORDER_FRAC = 0.06     # background estimated from the outer border band

# Route A benchmark result is cached for the process lifetime.
_REMBG_STATE = {"checked": False, "ok": False}

_LAYER_NAMES = ("BACKGROUND", "MIDGROUND", "SUBJECT")


def _border_medians(lum, sat):
    import numpy as np
    h, w = lum.shape
    b = max(2, int(_BORDER_FRAC * min(h, w)))
    m = np.ones((h, w), dtype=bool)
    m[b:h - b, b:w - b] = False
    return (float(np.median(lum[m])), float(np.median(sat[m])))


def _norm(a):
    import numpy as np
    hi = float(np.percentile(a, 98))
    if hi <= 1e-6:
        return a * 0.0
    return np.clip(a / hi, 0.0, 1.0)


def _cleanup_hard(mask_bool):
    """Morphological close-then-open via PIL Min/Max filters (deterministic)."""
    im = Image.fromarray((mask_bool * 255).astype("uint8"), "L")
    im = im.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    im = im.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return im


def _edge_weight(lum):
    """Normalized gradient-magnitude map (1.0 near strong luminance edges)."""
    import numpy as np
    gy, gx = np.gradient(lum)
    g = np.sqrt(gx * gx + gy * gy)
    return np.clip(_norm(g) * 3.0, 0.0, 1.0)


def _feather(hard_im, edge, lo_r, hi_r):
    """Edge-aware feather: tight across edges, soft elsewhere."""
    import numpy as np
    soft_lo = np.asarray(hard_im.filter(
        ImageFilter.GaussianBlur(lo_r)), dtype=np.float64) / 255.0
    soft_hi = np.asarray(hard_im.filter(
        ImageFilter.GaussianBlur(hi_r)), dtype=np.float64) / 255.0
    a = edge * soft_lo + (1.0 - edge) * soft_hi
    return (np.clip(a, 0.0, 1.0) * 255.0).astype("uint8")


def _saliency_masks(plate_path: Path, out_dir: Path, subject_bbox):
    """Route B — deterministic saliency band split. -> {layer: path}."""
    import numpy as np

    plate = Image.open(plate_path).convert("RGB")
    W, H = plate.size
    scale = _WORK_MAX_SIDE / float(max(W, H))
    if scale < 1.0:
        small = plate.resize((max(1, int(W * scale)), max(1, int(H * scale))),
                             Image.BILINEAR)
    else:
        small = plate
    arr = np.asarray(small, dtype=np.float64) / 255.0
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)

    med_lum, med_sat = _border_medians(lum, sat)
    dev = _norm(np.abs(lum - med_lum))
    sat_dev = _norm(np.abs(sat - med_sat))
    sal = 0.65 * dev + 0.35 * sat_dev

    # Subject gate: zero saliency outside the declared subject bbox
    # (expanded 4%) so masks stay consistent with the M2 safe-area rects.
    h, w = lum.shape
    if subject_bbox:
        x0, y0, x1, y1 = subject_bbox
        sx = w / float(W)
        sy = h / float(H)
        ex = 0.04 * (x1 - x0)
        ey = 0.04 * (y1 - y0)
        gx0 = max(0, int((x0 - ex) * sx))
        gy0 = max(0, int((y0 - ey) * sy))
        gx1 = min(w, int((x1 + ex) * sx))
        gy1 = min(h, int((y1 + ey) * sy))
        gate = np.zeros((h, w), dtype=bool)
        gate[gy0:gy1, gx0:gx1] = True
        sal = sal * gate

    t_sub = float(sal.mean() + 0.35 * sal.std())
    sub_hard = sal > t_sub

    rest = sal * (1.0 - sub_hard.astype(np.float64))
    t_mid = float(np.median(rest) + 0.5 * rest.std())
    mid_hard = (rest > t_mid) & (~sub_hard)

    edge = _edge_weight(lum)
    side = float(max(small.size))
    sub_im = _cleanup_hard(sub_hard)
    mid_im = _cleanup_hard(mid_hard)

    a_sub = _feather(sub_im, edge, 1.2, 0.014 * side)
    a_mid = _feather(mid_im, edge, 1.0, 0.010 * side)

    a_sub_full = Image.fromarray(a_sub, "L").resize((W, H), Image.BILINEAR)
    a_mid_full = Image.fromarray(a_mid, "L").resize((W, H), Image.BILINEAR)

    # BACKGROUND = 1 - max(SUBJECT, MIDGROUND)
    sub_a = np.asarray(a_sub_full, dtype=np.float64) / 255.0
    mid_a = np.asarray(a_mid_full, dtype=np.float64) / 255.0
    bg = ((1.0 - np.maximum(sub_a, mid_a)) * 255.0).astype("uint8")
    a_bg_full = Image.fromarray(bg, "L")

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, im in (("SUBJECT", a_sub_full), ("MIDGROUND", a_mid_full),
                     ("BACKGROUND", a_bg_full)):
        p = out_dir / f"{plate_path.stem}.mask.{name}.png"
        im.save(p, "PNG")
        paths[name] = str(p)
    return paths


def _rembg_masks(plate_path: Path, out_dir: Path):
    """Route A — rembg (u2net). Returns masks dict or None (unusable/too slow)."""
    t0 = time.time()
    try:
        from rembg import remove as _remove, new_session as _new_session
    except Exception:
        _REMBG_STATE["checked"] = True
        _REMBG_STATE["ok"] = False
        return None
    try:
        session = _new_session("u2net")
        plate = Image.open(plate_path).convert("RGB")
        cut = _remove(plate, session=session)
        alpha = cut.getchannel("A")
    except Exception:
        _REMBG_STATE["checked"] = True
        _REMBG_STATE["ok"] = False
        return None
    if time.time() - t0 > REMBG_MAX_S:
        _REMBG_STATE["checked"] = True
        _REMBG_STATE["ok"] = False
        return None
    _REMBG_STATE["checked"] = True
    _REMBG_STATE["ok"] = True

    import numpy as np
    W, H = plate.size
    a = np.asarray(alpha, dtype=np.float64) / 255.0
    sub = (a > 0.5).astype("uint8") * 255
    # MIDGROUND = dilated ring of the subject; BACKGROUND = complement.
    sub_im = Image.fromarray(sub, "L")
    ring = np.asarray(sub_im.filter(ImageFilter.MaxFilter(9))
                      .filter(ImageFilter.MinFilter(5)), dtype=np.float64)
    mid = np.clip(ring - a * 255.0, 0, 255).astype("uint8")
    bg = ((1.0 - np.maximum(a, mid / 255.0)) * 255.0).astype("uint8")

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, im in (("SUBJECT", Image.fromarray(sub, "L")),
                     ("MIDGROUND", Image.fromarray(mid, "L")),
                     ("BACKGROUND", Image.fromarray(bg, "L"))):
        p = out_dir / f"{plate_path.stem}.mask.{name}.png"
        im.save(p, "PNG")
        paths[name] = str(p)
    return paths


def derive_masks(plate_path, sidecar=None, sidecar_path=None) -> dict:
    """Derive BACKGROUND/MIDGROUND/SUBJECT masks for a plate; update sidecar.

    Returns {"masks": {name: path}, "method": str, "seconds": float,
    "coverage": {name: frac}}. Never raises. When ``sidecar`` is given the
    dict is updated in place (layers[].mask + parallax_weight and
    generation.depth = derived) and, when ``sidecar_path`` is also given,
    the updated sidecar JSON is written.
    """
    t0 = time.time()
    plate_path = Path(plate_path)
    result = {"masks": {}, "method": "none", "seconds": 0.0, "coverage": {}}
    try:
        masks, method = None, None
        if not _REMBG_STATE["checked"] or _REMBG_STATE["ok"]:
            masks = _rembg_masks(plate_path, plate_path.parent)
            method = "rembg-u2net" if masks else None
        if masks is None:
            bbox = None
            if isinstance(sidecar, dict):
                bbox = sidecar.get("subject_bbox_px")
            masks = _saliency_masks(plate_path, plate_path.parent, bbox)
            method = "saliency_v1"
        import numpy as np
        coverage = {}
        for name, p in masks.items():
            a = np.asarray(Image.open(p).convert("L"), dtype=np.float64) / 255.0
            coverage[name] = round(float((a > 0.5).mean()), 4)
        result.update({"masks": masks, "method": method,
                       "coverage": coverage})
    except Exception:
        result["method"] = "none"
        result["seconds"] = round(time.time() - t0, 2)
        return result

    result["seconds"] = round(time.time() - t0, 2)

    if isinstance(sidecar, dict):
        try:
            _apply_to_sidecar(sidecar, result)
            if sidecar_path is not None:
                Path(sidecar_path).write_text(
                    json.dumps(sidecar, indent=2) + "\n")
        except Exception:
            pass  # masks still returned; sidecar fallback stands
    return result


def _apply_to_sidecar(sidecar: dict, result: dict) -> None:
    """Stamp derived masks + weights + depth status into a sidecar dict."""
    masks = result.get("masks") or {}
    coverage = result.get("coverage") or {}
    for layer in sidecar.get("layers") or []:
        name = layer.get("name")
        if name in masks:
            layer["mask"] = masks[name]
            # Keep the authored semantic weight when the mask has real
            # support; an (near-)empty mask earns no parallax.
            if coverage.get(name, 0.0) < 0.005:
                layer["parallax_weight"] = 0.0
        else:
            layer["mask"] = None
            layer["parallax_weight"] = 0.0
    gen = sidecar.get("generation") or {}
    gen["depth"] = {
        "provider": "depth_layers",
        "model": result.get("method"),
        "seed": None,
        "status": "derived",
        "depth_map": None,
        "seconds": result.get("seconds"),
        "note": "V13 M3 real-mask 2.5D derivation (CPU, deterministic)",
    }
    sidecar["generation"] = gen
