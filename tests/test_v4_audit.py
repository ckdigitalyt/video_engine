"""Unit tests for v4_audit metric functions using synthetic frames.

Expected-score table (the contract for the STATIC_HOLD / VISUAL_EVENT_DENSITY
gates):

  flat clip  -> mean_delta == 0, longest_hold == full duration,
                events == 0, density == 0, class == static_hold
  zoom clip  -> deltas small but > 0 throughout, zoom_corr high,
                events == 0, class == pseudo_motion (Ken Burns)
  cut clip   -> exactly 1 event cluster at the cut, class == true_motion
  live clip  -> events from subject motion, low zoom_corr, class == true_motion
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import v4_audit as va  # noqa: E402

FPS = 10.0
H, W = 36, 64


def _texture(seed: int, smooth: bool = True) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 220, size=(H, W), dtype=np.uint8)
    if not smooth:
        return base
    # smooth it so gradients exist but noise is not everywhere
    k = np.ones((3, 3)) / 9.0
    out = base.astype(np.float32)
    for _ in range(2):
        out = np.pad(out, 1, mode="edge")
        out = (out[:-2, :-2] * k[0, 0] + out[1:-1, :-2] * k[1, 0] + out[2:, :-2] * k[2, 0]
               + out[:-2, 1:-1] * k[0, 1] + out[1:-1, 1:-1] * k[1, 1] + out[2:, 1:-1] * k[2, 1]
               + out[:-2, 2:] * k[0, 2] + out[1:-1, 2:] * k[1, 2] + out[2:, 2:] * k[2, 2])
    return out.astype(np.uint8)


def _landscape(seed: int = 2, height: int = 288, width: int = 512) -> np.ndarray:
    """Smooth photographic-style source image (sum of Gaussian blobs)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width]
    img = np.zeros((height, width), dtype=np.float32)
    for _ in range(25):
        cy, cx = rng.integers(0, height), rng.integers(0, width)
        s = rng.integers(20, 90)
        amp = rng.uniform(30, 180) * rng.choice([-1, 1])
        img += amp * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * s * s))
    return np.clip(img + 128, 0, 255).astype(np.uint8)


def _bilinear_resize(img: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    from scipy.ndimage import map_coordinates
    Y, X = np.meshgrid(ys, xs, indexing="ij")
    return map_coordinates(img, [Y, X], order=1, mode="nearest").astype(np.uint8)


def _flat_clip(n: int = 30) -> np.ndarray:
    """A frozen slideshow slide: every frame identical."""
    f = _texture(1)
    return np.repeat(f[None, :, :], n, axis=0)


def _zoom_clip(n: int = 30) -> np.ndarray:
    """Ken Burns: slow bilinear zoom into a static smooth scene (pseudo-motion)."""
    big = _landscape(2)
    frames = []
    for i in range(n):
        s = 1.0 + 0.012 * i  # slow zoom
        ch, cw = int(big.shape[0] / s), int(big.shape[1] / s)
        y0 = (big.shape[0] - ch) // 2
        x0 = (big.shape[1] - cw) // 2
        ys = np.linspace(y0, y0 + ch - 1, H)
        xs = np.linspace(x0, x0 + cw - 1, W)
        frames.append(_bilinear_resize(big, ys, xs))
    return np.stack(frames)


def _cut_clip(n: int = 30) -> np.ndarray:
    """Two frozen scenes hard-cut in the middle -> exactly one event.

    Note the expected motion class is still static_hold: a single cut between
    two frozen slides does not constitute scene motion (that is exactly the
    slideshow pattern the V4 gates must catch).
    """
    a = _texture(3, smooth=False)
    b = _texture(4, smooth=False)
    half = n // 2
    return np.concatenate([np.repeat(a[None], half, 0), np.repeat(b[None], n - half, 0)])


def _live_clip(n: int = 30) -> np.ndarray:
    """True motion: static background with a moving bright subject."""
    bg = np.zeros((H, W), dtype=np.float32) + 60
    blob = 25
    frames = []
    for i in range(n):
        f = bg.copy()
        cx = int(W * 0.15 + (W * 0.7) * i / n)
        f[H // 2 - blob:H // 2 + blob, cx - blob:cx + blob] = 230
        frames.append(f.astype(np.uint8))
    return np.stack(frames)


# ---------------------------------------------------------------- flat

def test_flat_clip_is_full_static_hold():
    frames = _flat_clip()
    deltas = va.frame_deltas(frames)
    assert deltas.max() == 0.0
    holds = va.static_holds(deltas, FPS)
    assert va.longest_hold_sec(holds) == pytest.approx((len(frames) - 1) / FPS)
    assert va.count_events(deltas) == 0
    d = va.visual_event_density(deltas, FPS)
    assert d["events"] == 0 and d["events_per_10s"] == 0.0
    assert d["moving_pair_fraction"] == 0.0


def test_flat_clip_classifies_static_hold():
    frames = _flat_clip()
    deltas = va.frame_deltas(frames)
    holds = va.static_holds(deltas, FPS)
    motion = va.global_motion(frames)
    assert va.classify_motion(deltas, FPS, (len(frames) - 1) / FPS, holds, motion) == "static_hold"


# ---------------------------------------------------------------- zoom

def test_zoom_clip_is_pseudo_motion_not_true_motion():
    frames = _zoom_clip()
    deltas = va.frame_deltas(frames)
    assert deltas.mean() > 0.05          # pixels *do* change...
    assert deltas.max() < va.DEFAULT_SPIKE_THRESHOLD  # ...but never an "event"
    holds = va.static_holds(deltas, FPS, threshold=0.05)
    motion = va.global_motion(frames)
    # Ken Burns signature: diff concentrated on image gradients
    assert motion["zoom_corr_median"] >= va.DEFAULT_ZOOM_CORR
    assert va.count_events(deltas) == 0
    assert va.classify_motion(deltas, FPS, (len(frames) - 1) / FPS, holds, motion) \
        == "pseudo_motion"

# ---------------------------------------------------------------- cut

def test_cut_clip_has_exactly_one_event():
    frames = _cut_clip()
    deltas = va.frame_deltas(frames)
    assert deltas.max() > 50.0           # hard cut between high-contrast scenes
    assert va.count_events(deltas) == 1
    d = va.visual_event_density(deltas, FPS)
    assert d["events"] == 1
    # density uses full clip duration (frames / fps = 3.0 s here); tool rounds to 3 dp
    assert d["events_per_10s"] == pytest.approx(1.0 * 10.0 / (len(frames) / FPS), abs=1e-3)


def test_cut_clip_single_cut_does_not_rescue_motion():
    frames = _cut_clip()
    deltas = va.frame_deltas(frames)
    holds = va.static_holds(deltas, FPS)
    motion = va.global_motion(frames)
    # two frozen slides + one cut = still a slideshow
    assert va.classify_motion(deltas, FPS, (len(frames) - 1) / FPS, holds, motion) \
        == "static_hold"

# ---------------------------------------------------------------- live

def test_live_clip_is_true_motion_with_low_zoom_corr():
    frames = _live_clip()
    deltas = va.frame_deltas(frames)
    assert va.count_events(deltas, threshold=va.DEFAULT_SPIKE_THRESHOLD) >= 1
    motion = va.global_motion(frames)
    # moving blob ≠ edge-aligned global zoom: corr stays well below Ken Burns
    assert motion["zoom_corr_median"] < va.DEFAULT_ZOOM_CORR
    holds = va.static_holds(deltas, FPS)
    assert va.longest_hold_sec(holds) < 2.5


# ---------------------------------------------------------------- helpers

def test_black_flat_seconds():
    black = np.zeros((5, H, W), dtype=np.uint8)
    card = np.full((5, H, W), 20, dtype=np.uint8)   # flat, not black
    normal = _texture(5, smooth=False)[None].repeat(5, 0)
    res = va.black_flat_seconds(np.concatenate([black, card, normal]), FPS)
    assert res["black_sec"] == pytest.approx(5 / FPS)
    assert res["flat_sec"] == pytest.approx(5 / FPS)


def test_dhash_distance_and_duplicates():
    a = _texture(1)
    b = _texture(2)
    ha, hb = va.dhash(a), va.dhash(b)
    assert va.hamming(ha, ha) == 0
    assert va.hamming(ha, hb) > 0
    samples = [
        {"label": "S01", "t": 0.0, "hash": ha},
        {"label": "S09", "t": 1.0, "hash": ha},   # same imagery, other shot
        {"label": "S02", "t": 0.0, "hash": hb},
    ]
    clusters = va.find_duplicates(samples)
    assert len(clusters) == 1
    assert set(clusters[0]["labels"]) == {"S01", "S09"}


def test_probe_real_fixture(tmp_path):
    """End-to-end probe/decode on a synthetic 1s video (ffmpeg required)."""
    frames = _flat_clip(10)
    import subprocess
    raw = frames.tobytes()
    p = tmp_path / "flat.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
                    "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)],
                   input=raw, check=True)
    meta = va.probe(p)
    assert meta["width"] == W and meta["height"] == H
    assert meta["fps"] == pytest.approx(FPS)
    a = va.audit_video(p, label="flat")
    assert a["motion_class"] == "static_hold"
    assert a["visual_event_density"]["events"] == 0
