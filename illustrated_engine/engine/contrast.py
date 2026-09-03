"""Local contrast — text vs the actual background beneath it.

Used by the V3 subtitle system to decide whether a caption needs backing,
a shadow, or nothing. WCAG-style relative luminance ratio on the cropped
region under the caption bbox; compared against the WCAG AA threshold
(4.5:1 for body text, 3.0:1 for large text). This is the "automatic gate"
the V3 brief asks for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


def _relative_luminance(rgb: np.ndarray) -> float:
    """rgb 0..255 float -> WCAG relative luminance 0..1."""
    a = np.clip(rgb.astype(np.float32) / 255.0, 0.0, 1.0)
    a = np.where(a <= 0.03928, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return float((0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]).mean())


def bbox_pixels(image: Image.Image, bbox) -> np.ndarray:
    """Return the RGB pixel array under a bbox (x0, y0, x1, y1). Clipped."""
    x0, y0, x1, y1 = bbox
    w, h = image.size
    x0 = max(0, min(w, int(x0))); x1 = max(0, min(w, int(x1)))
    y0 = max(0, min(h, int(y0))); y1 = max(0, min(h, int(y1)))
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return np.asarray(image.crop((x0, y0, x1, y1)).convert("RGB"))


def _p10_lum(pixels: np.ndarray) -> float:
    """10th-percentile luminance (proxy for the darkest 'under-text' region)."""
    if pixels.size == 0:
        return 0.0
    lum = (0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]) / 255.0
    return float(np.quantile(lum, 0.10))


def _p90_lum(pixels: np.ndarray) -> float:
    lum = (0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]) / 255.0
    return float(np.quantile(lum, 0.90))


def contrast_ratio(l1: float, l2: float) -> float:
    """WCAG contrast ratio between two relative luminances (0..1)."""
    L1, L2 = max(l1, l2), min(l1, l2)
    return (L1 + 0.05) / (L2 + 0.05)


def local_contrast(text_rgb: tuple, bg_pixels: np.ndarray) -> float:
    """Contrast between a solid text colour and the *worst-case* (lightest)
    patch of the actual background under the caption bbox.

    Returns a WCAG ratio (1..21). For dark text on light bg, use the lightest
    background patch; for light text on dark bg, use the darkest.
    """
    text_lum = _relative_luminance(np.array([text_rgb], dtype=np.float32))
    # decide which end of the bg to compare against
    if text_lum < 0.5:
        bg_lum = _p90_lum(bg_pixels)  # dark text -> worry about light bg
    else:
        bg_lum = _p10_lum(bg_pixels)  # light text -> worry about dark bg
    return round(contrast_ratio(text_lum, bg_lum), 2)


@dataclass
class BackingDecision:
    level: str          # "none" | "shadow" | "gradient"
    ratio: float
    threshold: float

    def ok(self) -> bool:
        return self.ratio >= self.threshold

    def as_dict(self) -> dict:
        return {"level": self.level, "ratio": self.ratio, "threshold": self.threshold}


def needs_backing(text_rgb: tuple, bg_pixels: np.ndarray,
                  body_threshold: float = 4.5) -> BackingDecision:
    """Decide the lightest intervention that meets the contrast bar.

    - ratio >= 4.5 -> "none" (AA body)
    - 3.0 <= ratio < 4.5 -> "shadow" (drop a soft 1px shadow under glyphs)
    - ratio < 3.0  -> "gradient" (draw a soft 0..alpha_max black strip)
    """
    r = local_contrast(text_rgb, bg_pixels)
    if r >= body_threshold:
        return BackingDecision("none", r, body_threshold)
    if r >= 3.0:
        return BackingDecision("shadow", r, body_threshold)
    return BackingDecision("gradient", r, body_threshold)


def gradient_strip(width: int, height: int, alpha_max: int = 140) -> Image.Image:
    """A vertical black-to-transparent strip for under-caption backing.

    Top is alpha_max (solid-ish under the caption), bottom is 0.
    Drawn in RGBA. Caller pastes it at (x, y) of the frame.
    """
    grad = np.linspace(alpha_max, 0, height, dtype=np.float32)
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    arr[..., 3] = np.repeat(grad.astype(np.uint8)[:, None], width, axis=1)
    arr[..., :3] = 0
    return Image.fromarray(arr, "RGBA")
