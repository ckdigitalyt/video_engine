"""Style continuity — separate from palette.

The V2 palette_continuity_score catches colour drift; this module catches
*style* drift: illustration medium, line quality, lighting language, texture,
rendering character. Same on-palette / wrong-family discipline, classical
image statistics only (no model download, deterministic, free).

Score is built from a 7-feature fingerprint compared against a reference
fingerprint assembled from the bible's `illustration_medium`, `lighting` and
`texture` fields via a small descriptor->expected-statistics lookup.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image


# ----- descriptor -> expected fingerprint -----------------------------
# Each row: a coarse style descriptor + a tuple of 7 anchor values:
#   (edge_density, texture_var, mean_lum, lum_std, color_entropy, warm_cool, line_dark)
# Values normalised 0..1. They are HEURISTIC, hand-tuned from observed ranges.
_STYLE_TABLE = {
    "ink_wash":       (0.55, 0.45, 0.55, 0.32, 0.55, 0.65, 0.78),
    "vintage":        (0.50, 0.40, 0.60, 0.30, 0.50, 0.62, 0.65),
    "engraving":      (0.78, 0.62, 0.45, 0.38, 0.35, 0.20, 0.88),
    "linocut":        (0.80, 0.55, 0.50, 0.40, 0.30, 0.25, 0.92),
    "watercolor":     (0.30, 0.28, 0.68, 0.25, 0.62, 0.55, 0.35),
    "charcoal":       (0.62, 0.55, 0.42, 0.40, 0.42, 0.30, 0.82),
    "vector_line":    (0.72, 0.18, 0.65, 0.30, 0.45, 0.40, 0.70),
    "photoreal":      (0.45, 0.55, 0.50, 0.30, 0.72, 0.50, 0.20),
    "cinematic":      (0.42, 0.50, 0.45, 0.34, 0.68, 0.45, 0.25),
    "diagram_parch":  (0.65, 0.15, 0.82, 0.18, 0.32, 0.55, 0.65),
    "default":        (0.50, 0.40, 0.55, 0.30, 0.55, 0.50, 0.55),
}

_LIGHTING_TABLE = {
    "low-key":      (0.00, 0.05, 0.05),  # mean_lum delta, lum_std delta, warm_cool delta
    "chiaroscuro":  (0.00, 0.05, 0.05),
    "rim-lit":      (0.02, 0.05, 0.04),
    "diffuse":      (0.05, -0.05, 0.00),
    "high-key":     (0.10, -0.08, 0.00),
    "flat":         (0.00, -0.15, 0.00),
    "moody":        (-0.05, 0.05, 0.05),
    "default":      (0.00, 0.00, 0.00),
}


def _img_fingerprint(arr: np.ndarray) -> np.ndarray:
    """7-feature style fingerprint from an RGB image array (HxWx3 uint8)."""
    a = arr.astype(np.float32) / 255.0
    gray = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    h, w = gray.shape
    # edge density via Sobel
    gx = np.diff(gray, axis=1, prepend=0)
    gy = np.diff(gray, axis=0, prepend=0)
    mag = np.hypot(gx, gy)
    edge_density = float(np.clip(mag.mean() * 4.0, 0, 1))
    # texture variance via Laplacian magnitude
    lap = np.zeros_like(gray)
    lap[1:-1, 1:-1] = (
        4 * gray[1:-1, 1:-1]
        - gray[:-2, 1:-1] - gray[2:, 1:-1]
        - gray[1:-1, :-2] - gray[1:-1, 2:]
    )
    texture_var = float(np.clip(np.abs(lap).std() * 6.0, 0, 1))
    # luminance distribution
    mean_lum = float(gray.mean())
    lum_std = float(gray.std())
    # color entropy (rough): histogram of hue, normalised
    hsv = a.max(axis=-1)
    mn = a.min(axis=-1)
    s = np.where(hsv > 1e-6, (hsv - mn) / np.maximum(hsv, 1e-6), 0.0)
    bins = np.linspace(0, 1, 17)
    h, _ = np.histogram(s[s > 0.15], bins=bins)
    p = h / max(1, h.sum())
    p = p[p > 0]
    color_entropy = float(-np.sum(p * np.log(p + 1e-9)) / np.log(16))
    # warm-cool balance: average of (R - B) on chroma pixels
    chroma = s > 0.15
    if chroma.any():
        warm_cool = float((a[..., 0][chroma] - a[..., 2][chroma]).mean())
        warm_cool = 0.5 + 0.5 * np.clip(warm_cool * 4.0, -0.5, 0.5)
    else:
        warm_cool = 0.5
    # line darkness: how dark the darkest 10% of pixels are (ink lines read here)
    line_dark = float(np.clip(1.0 - np.partition(gray.ravel(), int(gray.size * 0.10))[: int(gray.size * 0.10)].mean(), 0, 1))
    return np.array([edge_density, texture_var, mean_lum, lum_std,
                     color_entropy, warm_cool, line_dark], dtype=np.float32)


def style_fingerprint(img) -> np.ndarray:
    """Return 7-feature style fingerprint. Accepts path, PIL Image, or RGB array."""
    if isinstance(img, (str, Path)):
        img = Image.open(img).convert("RGB")
    if isinstance(img, Image.Image):
        arr = np.asarray(img)
    else:
        arr = np.asarray(img)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    return _img_fingerprint(arr)


def _ref_from_bible(bible: dict) -> np.ndarray:
    """Assemble reference fingerprint from bible fields."""
    style = (bible.get("illustration_medium")
             or bible.get("illustration_style")
             or "default").lower().replace(" ", "_")
    base = _STYLE_TABLE.get(style, _STYLE_TABLE["default"])
    # lighting modifiers
    light = (bible.get("lighting") or "default").lower()
    for key, (dlum, dstd, dwarm) in _LIGHTING_TABLE.items():
        if key in light:
            base = (base[0],
                    base[1],
                    float(np.clip(base[2] + dlum, 0, 1)),
                    float(np.clip(base[3] + dstd, 0.05, 0.6)),
                    base[4],
                    float(np.clip(base[5] + dwarm, 0, 1)),
                    base[6])
            break
    # grain: more grain -> more texture variance
    grain = float(bible.get("texture", {}).get("grain", 0.012))
    base = (base[0], float(np.clip(base[1] + grain * 4.0, 0, 1)),
            base[2], base[3], base[4], base[5], base[6])
    return np.array(base, dtype=np.float32)


def style_distance(fp_img: np.ndarray, fp_ref: np.ndarray) -> float:
    """Weighted L2 distance between two 7-feature style fingerprints."""
    w = np.array([1.4, 1.2, 0.6, 0.7, 0.9, 0.8, 1.1], dtype=np.float32)
    diff = (fp_img - fp_ref) * w
    return float(np.sqrt((diff * diff).sum()))


def style_continuity_score(img, bible: dict) -> float:
    """0..1 — 1 means the image's style signature matches the bible."""
    if isinstance(img, (str, Path)):
        img = Image.open(img).convert("RGB")
    fp_img = style_fingerprint(img)
    fp_ref = _ref_from_bible(bible)
    d = style_distance(fp_img, fp_ref)
    # sigmoid: distance ~0 -> 1.0, distance ~2 -> ~0.1
    return float(round(1.0 / (1.0 + math.exp(2.5 * d - 2.0)), 4))


def video_style_score(video_path: Path, bible: dict, samples: int = 8) -> dict:
    """Average style score across N extracted frames (evenly spaced)."""
    from engine.video_extract import sample_frames
    frames = sample_frames(Path(video_path), n=samples)
    scores = [style_continuity_score(f, bible) for f in frames]
    return {
        "scores": scores,
        "mean": round(sum(scores) / max(1, len(scores)), 4),
        "min": round(min(scores), 4),
        "max": round(max(scores), 4),
    }


# ----- self-test -----------------------------------------------------
if __name__ == "__main__":
    import sys
    from engine.bible import load_bible
    bible = load_bible("stories/tallest_mountain")
    if len(sys.argv) > 1:
        s = style_continuity_score(sys.argv[1], bible)
        print(f"style_continuity_score({sys.argv[1]}) = {s}")
    else:
        for fn in ("assets/B1_everest_plate.png", "assets/D1_scale_compare.png"):
            print(fn, style_continuity_score(fn, bible))
