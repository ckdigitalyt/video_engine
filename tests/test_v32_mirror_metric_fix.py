"""Tests for the v32 corrected mirrored_edges detector.

The v13 metric (p90 of per-row flip deltas) false-positived on smooth/
structured content: for the innermost border rows the "flipped counterpart"
pairing collapsed to the adjacent interior row, turning the delta into an
adjacency correlation.  Wow! Signal v31 re-run: 12/24 clean AI stills were
flagged and the publish gate blocked a clean video (p90 +0.20 >= 0.15).

The v32 detector (`mirror_band_scan`) requires a CONTIGUOUS RUN of rows
that are a pixel-faithful vertical flip of the adjacent interior band, at
any seam depth 4..32px, per edge independently.  Verified cases:
  * true mirrored band (depth 10)          -> DETECTED
  * smooth vertical gradient               -> clean
  * blurred noise                          -> clean (old metric FP'd: 0.212)
  * smooth sky                             -> clean
  * vertically symmetric blob              -> clean
  * all 24 real Wow! Signal stills         -> clean (old metric FP'd 12)
"""

import glob
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.qa.visual_artifact_check import (
    MIRROR_MIN_CORR, MIRROR_MIN_MARGIN, MIRROR_MAX_REL_MAD, MIRROR_ABS_MAD,
    mirror_band_scan, _row_mirror_score,
)

STILL_DIR = os.path.join("cache", "stills", "the_wow__signal")


def _blur(a, k=2):
    pad = np.pad(a, ((k, k), (k, k)), mode="edge")
    out = np.zeros_like(a)
    for i in range(-k, k + 1):
        for j in range(-k, k + 1):
            out += pad[k + i:k + i + a.shape[0], k + j:k + j + a.shape[1]]
    return out / ((2 * k + 1) ** 2)


def _true_mirror_band(depth=10, h=60, w=200, seed=0):
    """Textured base + top `depth` rows = pixel-exact reversed copy of the
    rows just below them (the classic outpainting/inpaint mirror seam)."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (h, w)).astype(np.float32)
    return np.vstack([base[:depth][::-1], base])


def _smooth_gradient(h=80, w=200, seed=1):
    rng = np.random.default_rng(seed)
    g = np.linspace(0, 255, h).reshape(-1, 1) * np.ones((1, w))
    return (g + rng.normal(0, 2, (h, w))).astype(np.float32)


def _blurred_noise(h=80, w=200, seed=2):
    rng = np.random.default_rng(seed)
    return _blur(rng.integers(0, 255, (h, w)).astype(np.float32), 2)


def _smooth_sky(h=80, w=200, seed=3):
    rng = np.random.default_rng(seed)
    return _blur(rng.integers(40, 150, (h, w)).astype(np.float32), 3)


def _symmetric_blob(h=80, w=200, seed=4):
    rng = np.random.default_rng(seed)
    x = np.linspace(-1, 1, w)
    y = np.linspace(-1, 1, h)
    gx, gy = np.meshgrid(x, y)
    return (128 + 100 * np.exp(-(gx ** 2 + gy ** 2) * 3)
            + rng.normal(0, 4, (h, w))).astype(np.float32)


# ── true mirror bands at multiple depths MUST be detected ────────────── #

@pytest.mark.parametrize("depth", [4, 8, 10, 16, 32])
def test_true_mirror_band_detected(depth):
    img = _true_mirror_band(depth=depth)
    hits = mirror_band_scan(img)
    assert hits, f"true mirror band at depth {depth} not detected"
    assert any(h["edge"] == "top" for h in hits)
    # the hit must be at (or very near) the true seam depth
    assert any(abs(h["depth"] - depth) <= 2 for h in hits)


def test_true_mirror_band_edge_specific():
    """A band on the TOP must not fire bottom/left/right."""
    img = _true_mirror_band(depth=10)
    hits = mirror_band_scan(img)
    assert all(h["edge"] == "top" for h in hits)


# ── benign content MUST stay clean (old metric false-positived) ──────── #

@pytest.mark.parametrize("name,fn", [
    ("smooth_gradient", _smooth_gradient),
    ("blurred_noise", _blurred_noise),
    ("smooth_sky", _smooth_sky),
    ("symmetric_blob", _symmetric_blob),
])
def test_benign_content_clean(name, fn):
    hits = mirror_band_scan(fn())
    assert hits == [], f"{name} flagged: {hits}"


def test_blurred_noise_was_old_fp():
    """The v13 metric scored blurred noise p90=+0.212 (>= 0.15 threshold,
    false positive).  The v32 detector must not flag it."""
    assert mirror_band_scan(_blurred_noise()) == []


def test_real_stills_clean():
    """All 24 Wow! Signal stills must pass (the old metric flagged 12)."""
    if not os.path.isdir(STILL_DIR):
        pytest.skip("Wow! Signal still cache not present")
    from PIL import Image
    flagged = []
    for f in sorted(glob.glob(os.path.join(STILL_DIR, "*.jpg"))):
        a = np.asarray(Image.open(f).convert("L"), dtype=np.float32)
        hits = mirror_band_scan(a)
        if hits:
            flagged.append((os.path.basename(f), hits))
    assert flagged == [], f"clean stills flagged: {flagged}"


# ── row-level criteria sanity ────────────────────────────────────────── #

def test_row_mirror_score_rejects_flat_rows():
    t = np.zeros(64, dtype=np.float32)
    mir = np.zeros(64, dtype=np.float32)
    same = np.zeros(64, dtype=np.float32)
    assert _row_mirror_score(t, mir, same) is False  # std < 2.0


def test_row_mirror_score_accepts_pixel_copy():
    rng = np.random.default_rng(5)
    t = rng.integers(0, 255, 128).astype(np.float32)
    mir = t.copy()
    same = rng.integers(0, 255, 128).astype(np.float32)
    assert _row_mirror_score(t, mir, same) is True


def test_row_mirror_score_rejects_margin_failure():
    """Smooth content: flip corr high but same-side corr equally high, so
    the margin check fails (the old metric's adjacency false positive)."""
    rng = np.random.default_rng(6)
    base = np.linspace(0, 255, 128)
    t = (base + rng.normal(0, 1, 128)).astype(np.float32)
    mir = (base[::-1] + rng.normal(0, 1, 128)).astype(np.float32)
    same = (base + rng.normal(0, 1, 128)).astype(np.float32)
    assert _row_mirror_score(t, mir, same) is False


# ── gate-level: mirrored_edges passes the REAL video ─────────────────── #

def test_real_video_passes_mirror_gate():
    vid = os.path.join("results", "the_wow__signal",
                       "the_wow__signal_mixed.mp4")
    if not os.path.exists(vid):
        pytest.skip("Wow! Signal video not present")
    from src.qa.visual_artifact_check import run_visual_artifact_check
    res = run_visual_artifact_check(vid)
    by_name = {c["name"]: c for c in res["checks"]}
    assert by_name["mirrored_edges"]["passed"] is True, \
        by_name["mirrored_edges"]["detail"]
