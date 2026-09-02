"""Post-generation colour harmonisation + visual-continuity scoring.

Bible-first rule: generated plates that drift from the Visual Bible palette
are graded toward it; if they still score below threshold they are flagged
for regeneration. Deterministic (seeded RNG, no network).

Continuity score (0..1):
  0.6 * hue-histogram intersection vs bible palette reference
  + 0.2 * saturation similarity vs bible saturation target
  + 0.2 * contrast similarity vs bible contrast target
"""

from __future__ import annotations

import colorsys
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

HUE_BINS = 36
_REF_CACHE = {}


# ---------------------------------------------------------------- scoring ---

def _hue_hist(arr: np.ndarray) -> np.ndarray:
    """36-bin hue histogram, weighted by saturation, over pixels with S>0.15."""
    a = arr.astype(np.float32) / 255.0
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    d = mx - mn
    s = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0.0)
    mask = s > 0.15   # exclude near-greys: their hue is numerically unstable (paper-mottle noise creates pseudo-hues below this)
    if not mask.any():
        return np.zeros(HUE_BINS, np.float32)
    r, g, b = a[..., 0][mask], a[..., 1][mask], a[..., 2][mask]
    sat = s[mask]
    h = np.zeros(mask.sum(), np.float32)
    dmask = d[mask] > 1e-6
    idx = np.where(dmask)[0]
    rmax = r[idx] >= np.maximum(g[idx], b[idx])
    gmax = (~rmax) & (g[idx] >= b[idx])
    bmax = ~(rmax | gmax)
    dd = d[mask][idx]
    h[idx[rmax]] = ((g[idx[rmax]] - b[idx[rmax]]) / np.maximum(dd[rmax], 1e-6)) % 6.0
    h[idx[gmax]] = (b[idx[gmax]] - r[idx[gmax]]) / np.maximum(dd[gmax], 1e-6) + 2.0
    h[idx[bmax]] = (r[idx[bmax]] - g[idx[bmax]]) / np.maximum(dd[bmax], 1e-6) + 4.0
    hue = (h / 6.0).astype(np.float32)
    hist = np.zeros(HUE_BINS, np.float32)
    bins = np.clip((hue * HUE_BINS).astype(np.int32), 0, HUE_BINS - 1)
    np.add.at(hist, bins, sat.astype(np.float32))
    tot = hist.sum()
    return hist / tot if tot > 0 else hist


def _smooth_circular(hist: np.ndarray) -> np.ndarray:
    """Circular +-1-bin triangular smoothing (hue is circular)."""
    h = np.asarray(hist, np.float32)
    n = len(h)
    out = 0.5 * h + 0.25 * np.roll(h, 1) + 0.25 * np.roll(h, -1)
    tot = out.sum()
    return out / tot if tot > 0 else out


def _calibration_image(n: int = 720, h: int = 60) -> Image.Image:
    """Hue-wheel strip: every hue at moderate saturation/value."""
    import colorsys
    arr = np.zeros((h, n, 3), np.uint8)
    for i in range(n):
        r, g, b = colorsys.hsv_to_rgb(i / n, 0.55, 0.55)
        arr[:, i] = (int(r * 255), int(g * 255), int(b * 255))
    return Image.fromarray(arr, "RGB")


def _reference_hist(bible: dict) -> np.ndarray:
    """Concentrated reference: sharpened palette hues (dominant families),
    mildly corrected by the hue signature of a graded calibration wheel
    (accounts for how the grade compresses chroma). Cached per palette."""
    key = "|".join(str(bible["palette"].get(k, ""))
                   for k in ("primary", "secondary", "accent", "muted", "background")) \
        + f"|s{bible['saturation']}|c{bible['contrast']}"
    if key in _REF_CACHE:
        return _REF_CACHE[key]
    stats = __import__("engine.bible", fromlist=["reference_stats"]).reference_stats(bible)
    pal = np.asarray(stats["hue"], np.float32)
    pal = pal ** 1.5                      # sharpen: emphasize dominant hue families
    pal = _smooth_circular(pal / pal.sum() if pal.sum() > 0 else pal)
    wheel = grade_to_bible(_calibration_image(), bible, 0.55)
    ghist = _smooth_circular(_hue_hist(np.asarray(wheel.convert("RGB"))))
    ref = 0.8 * pal + 0.2 * ghist
    tot = ref.sum()
    ref = ref / tot if tot > 0 else ref
    _REF_CACHE[key] = ref
    return ref


def _mean_sat(arr: np.ndarray) -> float:
    a = arr.astype(np.float32) / 255.0
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return float(s.mean())


def _contrast(arr: np.ndarray) -> float:
    """RMS contrast of luminance, normalised 0..1."""
    a = arr.astype(np.float32) / 255.0
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return float(np.sqrt((lum ** 2).mean()) * 2.0)


def continuity_score(img, bible: dict) -> float:
    """0..1 score of how well an image sits inside the Bible's palette world."""
    if isinstance(img, (str, Path)):
        img = Image.open(img).convert("RGB")
    if isinstance(img, Image.Image):
        arr = np.asarray(img.convert("RGB"))
    else:
        arr = np.asarray(img)

    hist = _smooth_circular(_hue_hist(arr))
    ref = _reference_hist(bible)
    # cosine similarity: rewards hue mass ALIGNED with palette families,
    # penalizes uniform/noise hists and off-palette hue families
    nh, nr = np.linalg.norm(hist), np.linalg.norm(ref)
    cos = float(hist @ ref / (nh * nr)) if nh > 1e-9 and nr > 1e-9 else 0.0
    hue_sim = max(0.0, min(1.0, cos)) ** 1.2
    stats = __import__("engine.bible", fromlist=["reference_stats"]).reference_stats(bible)

    sat_sim = 1.0 - min(1.0, abs(_mean_sat(arr) - stats["saturation"]) / max(stats["saturation"], 0.08))
    con_sim = 1.0 - min(1.0, abs(_contrast(arr) - stats["contrast"]) / max(stats["contrast"], 0.08))
    return round(max(0.0, min(1.0, 0.6 * hue_sim + 0.2 * sat_sim + 0.2 * con_sim)), 4)


# ------------------------------------------------------------- hsv utils ---

def _rgb_to_hsv(arr: np.ndarray):
    """Vectorized RGB(0..1) -> (h, s, v) arrays in 0..1."""
    a = arr.astype(np.float32)
    mx = a.max(axis=-1)
    mn = a.min(axis=-1)
    d = mx - mn
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    h = np.zeros_like(mx)
    dm = d > 1e-6
    idx_r = dm & (mx == r)
    idx_g = dm & ~idx_r & (mx == g)
    idx_b = dm & ~idx_r & ~idx_g & (mx == b)
    h[idx_r] = ((g - b)[idx_r] / np.maximum(d[idx_r], 1e-6)) % 6.0
    h[idx_g] = ((b - r)[idx_g] / np.maximum(d[idx_g], 1e-6)) + 2.0
    h[idx_b] = ((r - g)[idx_b] / np.maximum(d[idx_b], 1e-6)) + 4.0
    return (h / 6.0) % 1.0, s.astype(np.float32), mx.astype(np.float32)


def _hsv_to_rgb(h, s, v):
    """Vectorized (h, s, v) 0..1 arrays -> RGB array (..., 3)."""
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i = i.astype(np.int32) % 6
    out = np.zeros(list(h.shape) + [3], np.float32)
    for k, (rr, gg, bb) in enumerate(((v, t, p), (q, v, p), (p, v, t),
                                      (p, q, v), (t, p, v), (v, p, q))):
        m = i == k
        out[..., 0][m] = rr[m]
        out[..., 1][m] = gg[m]
        out[..., 2][m] = bb[m]
    return out


# ----------------------------------------------------------------- grading ---

def grade_to_bible(img, bible: dict, strength: float = 0.55) -> Image.Image:
    """Deterministic colour harmonisation toward the Bible palette.

    Hue is FULLY remapped to the palette hue for each pixel's luminance band
    (deep shadows -> navy, mids/highs -> warm sepia/cream; the shadow->mid
    transition travels the warm red side, never green). `strength` controls
    how much of the original saturation survives vs the bible's per-band
    target, plus vignette/grain. Luminance is preserved. This is the honest
    meaning of "grade toward the palette": an off-family asset comes back
    ON family, not 70% toward it.
    """
    from engine import bible as B
    import colorsys
    if isinstance(img, Image.Image):
        img = img.convert("RGB")
    arr = np.asarray(img).astype(np.float32) / 255.0
    H, W = arr.shape[:2]

    h, s, v = _rgb_to_hsv(arr)
    lum = arr @ np.array([0.2126, 0.7152, 0.0722], np.float32)

    h_navy = colorsys.rgb_to_hsv(*B.rgb(bible, "primary"))[0]
    h_sepia = colorsys.rgb_to_hsv(*B.rgb(bible, "secondary"))[0]
    # travel from navy to sepia the warm way (up through red, never green)
    warm_span = (1.0 - h_navy) + h_sepia

    # luminance -> hue band: deep shadow navy, above ~0.4 sepia/cream
    w = np.clip((lum - 0.38) / 0.22, 0.0, 1.0).astype(np.float32)
    h_new = ((h_navy + warm_span * w) % 1.0) * np.ones_like(h)

    # saturation: blend original toward per-band bible target (scaled by bible)
    s_tgt = np.interp(lum, [0.0, 0.35, 0.75, 1.0],
                      [0.50, 0.40, 0.30, 0.22]).astype(np.float32)
    s_tgt = np.clip(s_tgt * (float(bible["saturation"]) / 0.72), 0.0, 1.0)
    s_new = (s * (1.0 - strength) + s_tgt * strength).astype(np.float32)

    rgb = _hsv_to_rgb(h_new, s_new, np.clip(v, 0, 1))
    out = rgb

    # vignette
    tex = bible.get("texture", {})
    vig = float(tex.get("vignette", 0.25))
    if vig > 0:
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        out = out * (1.0 - vig * np.clip(r - 0.55, 0, 1))[..., None]

    # grain (seeded -> deterministic)
    grain = float(tex.get("grain", 0.012))
    if grain > 0:
        rng = np.random.default_rng(7)
        out = out + rng.normal(0.0, grain, out.shape).astype(np.float32)

    out8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(out8, "RGB")


def ensure_continuity(path, bible: dict, threshold: float = 0.55,
                      max_passes: int = 2) -> dict:
    """Grade-if-needed pipeline for one asset (operates on the original).

    Returns report: score_before, passes[], score_after, ok, needs_regenerate.
    The ungraded original is preserved once as <name>.orig.png.
    """
    p = Path(path)
    orig = p.with_suffix(".orig" + p.suffix)
    if not orig.exists():
        shutil.copy(p, orig)
    base = np.asarray(Image.open(orig).convert("RGB"))

    s0 = continuity_score(base, bible)
    best_img, best_score = None, s0
    passes = []
    strength = 0.45
    if s0 < threshold:
        for i in range(max_passes):
            graded = grade_to_bible(Image.fromarray(base), bible, strength)
            s = continuity_score(graded, bible)
            passes.append({"strength": round(strength, 2), "score": s})
            if s > best_score:
                best_img, best_score = graded, s
            if best_score >= threshold:
                break
            strength += 0.25

    if best_img is not None and best_score > s0:
        best_img.save(p, "PNG")

    return {
        "file": Path(p).name,
        "score_before": s0,
        "score_after": best_score,
        "passes": passes,
        "ok": best_score >= threshold,
        "needs_regenerate": best_score < threshold,
    }
