"""Information density (V4 §4).

For diagram/graphic assets: detect excessive empty space, tiny labels
surrounded by empty canvas, overcrowding, too many equal-weight elements.
Solve low density by making important information bigger and more purposeful
— never by adding decoration.

Measured on the actual rendered card pixels:
  ink_ratio    — fraction of pixels that differ from the parchment base
  empty_ratio  — content-zone emptiness (inside margins)
  edge_pixels  — glyph/line detail proxy (Laplacian magnitude)
  hierarchy    — ratio of largest connected ink block to total ink (proxy)
"""

from __future__ import annotations

import numpy as np
from PIL import Image

INK_MIN = 0.02    # below this = nearly empty poster
INK_MAX = 0.42    # above this = overcrowded
EMPTY_MAX = 0.68  # content-zone emptiness ceiling
EDGE_MIN = 0.004  # tiny-label detector: too little glyph detail


def _ink_mask(arr: np.ndarray, base=(233, 223, 200)) -> np.ndarray:
    diff = np.abs(arr[..., :3].astype(int) - np.array(base)).sum(axis=-1)
    return diff > 60


def density_metrics(img) -> dict:
    img = img.convert("RGB") if not isinstance(img, Image.Image) or img.mode != "RGB" else img
    arr = np.asarray(img)
    mask = _ink_mask(arr)
    h, w = mask.shape
    ink_ratio = float(mask.mean())
    # content zone (drop 8% margins)
    y0, y1 = int(h * 0.08), int(h * 0.92)
    x0, x1 = int(w * 0.08), int(w * 0.92)
    zone = mask[y0:y1, x0:x1]
    zone_ink = float(zone.mean())
    # glyph/line detail via simple gradient magnitude
    gray = arr.mean(axis=-1)
    gx = np.abs(np.diff(gray, axis=1)).mean()
    gy = np.abs(np.diff(gray, axis=0)).mean()
    edge = float((gx + gy) / 510.0)
    # hierarchy proxy: row-wise ink concentration (top-heavy titles etc.)
    row_ink = mask.mean(axis=1)
    hierarchy = float(row_ink.max() / max(1e-6, row_ink.mean() + 1e-6) / h * 60.0)
    hierarchy = float(np.clip(hierarchy, 0, 1))
    return {"ink_ratio": round(ink_ratio, 4), "zone_ink_ratio": round(zone_ink, 4),
            "edge_ratio": round(edge, 4), "hierarchy": round(hierarchy, 4),
            "empty_ratio": round(1.0 - zone_ink, 4)}


def density_score(metrics: dict) -> tuple:
    """(score 0..100, violations[])."""
    v = []
    if metrics["ink_ratio"] < INK_MIN:
        v.append("nearly_empty")
    if metrics["ink_ratio"] > INK_MAX:
        v.append("overcrowded")
    if metrics["empty_ratio"] > EMPTY_MAX:
        v.append("excessive_empty_space")
    if metrics["edge_ratio"] < EDGE_MIN:
        v.append("tiny_or_missing_labels")
    score = round(100.0 - 22.0 * len(v), 1)
    return max(0.0, score), v


def diagram_density(img) -> dict:
    m = density_metrics(img)
    s, v = density_score(m)
    m["score"] = s
    m["violations"] = v
    m["ok"] = s >= 75.0
    return m
