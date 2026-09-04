"""V5 §10 editorial finishing — make heterogeneous plates feel art-directed.

Chain: tonal normalization -> gentle saturation control -> consistent grain
-> consistent contrast curve. NO palette mapping (V4 evidence: full palette
mapping added purple fringing and lowered continuity — raw frequently won).
Deterministic: fixed seed, no randomness across runs.

Per-plate acceptance stays with the caller: score the finished plate against
the original (style continuity + subject check) and keep whichever wins.
The purpose is one visual team, not a higher style score (§10).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

SEED = 505  # fixed grain seed — identical finish for every plate
TARGET_LUMA = 0.46   # editorial print feel: slightly darker than mid-gray
SATURATION = 0.95    # gentle pull toward print-like saturation
CONTRAST = 1.045     # soft S-contrast around 0.5
GRAIN_SIGMA = 5.5    # /255 grain amplitude


def _luma(arr: np.ndarray) -> np.ndarray:
    return (0.2126 * arr[..., 0] + 0.7152 * arr[..., 1]
            + 0.0722 * arr[..., 2])


def finish(img: Image.Image, grain: float = GRAIN_SIGMA,
           saturation: float = SATURATION, contrast: float = CONTRAST,
           target_luma: float = TARGET_LUMA) -> Image.Image:
    """Apply the finishing chain to one RGB image. Deterministic."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0

    # 1) tonal normalization: nudge mean luma toward the editorial target
    l = _luma(arr)
    shift = np.clip((target_luma - float(l.mean())) * 0.35, -0.05, 0.05)
    arr = np.clip(arr + shift, 0.0, 1.0)

    # 2) saturation control: lerp channels toward their luma
    l = _luma(arr)[..., None]
    arr = np.clip(l + (arr - l) * saturation, 0.0, 1.0)

    # 3) consistent grain (fixed seed; identical pattern per size class)
    rng = np.random.default_rng(SEED)
    noise = rng.normal(0.0, grain / 255.0, arr.shape[:2])[..., None]
    arr = np.clip(arr + noise, 0.0, 1.0)

    # 4) consistent contrast curve around 0.5
    arr = np.clip((arr - 0.5) * contrast + 0.5, 0.0, 1.0)

    return Image.fromarray((arr * 255.0).round().astype(np.uint8), "RGB")


def finish_if_better(src_path, dst_path, score_fn) -> dict:
    """Finish `src_path`, keep the winner by `score_fn(path) -> float`.

    Returns which variant was kept and both scores. Guardrail for the V4
    lesson: never destroy image quality just to raise a style score.
    """
    src = dst = None
    from pathlib import Path as _P
    src, dst = _P(src_path), _P(dst_path)
    s0 = float(score_fn(src))
    finish(Image.open(src)).save(dst)
    s1 = float(score_fn(dst))
    if s1 >= s0:
        return {"kept": "finished", "score_raw": s0, "score_finished": s1,
                "out": str(dst)}
    dst.unlink(missing_ok=True)
    return {"kept": "raw", "score_raw": s0, "score_finished": s1,
            "out": str(src)}
