"""
visual_artifact_check.py — Automated visual-artifact detection (rec #5).

The expert review found mirrored/smeared borders from aspect-ratio padding
and outpainting failures.  This module runs deterministic pixel-level checks
on the FINAL rendered video (or any video/image):

  * mirrored_edges  — top/bottom (and left/right) border rows that are a
                      mirror of the interior (the classic "inpaint seam"
                      artifact).  Detected by measuring cross-correlation
                      between the border strip and its vertical flip.
  * smeared_borders — blurry/low-detail borders vs sharp interior (the
                      "smeared padding" artifact).  Detected via local
                      gradient-energy ratio.
  * seam_lines      — a single bright/dark vertical or horizontal line
                      (duplicated/warped object boundary).
  * stretch         — aspect-ratio distortion of the whole frame (detected
                      via geometric consistency: if the frame is not 16:9,
                      or edges carry gradient identical to a stretched
                      version — we flag non-16:9 sources).

All checks are cheap: N sample frames, each downscaled to ~480px wide,
border strips of ~4% height.  Runs in seconds, no LLM.

Output: {passed, checks: [{name, passed, detail}], frames_checked}
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional

import numpy as np

BORDER_FRAC = 0.04          # border strip = 4% of frame height
MIRROR_P90 = 0.15            # 90th percentile of border-row flip deltas must stay below this
SMEAR_RATIO = 0.12          # border gradient energy / interior below this = smear
SEAM_PCT = 99.5             # row/col diff must exceed this percentile by SEAM_FACTOR
SEAM_FACTOR = 6.0
# A true seam (duplicated/stretched content) is a SHARP discontinuity:
# the anomalous line must also correlate poorly with its neighbor (a
# natural high-contrast edge — light ray, object boundary — continues
# smoothly into adjacent columns/rows, so corr stays high).
SEAM_MAX_NEIGHBOR_CORR = 0.90
SAMPLE_FRAMES = 6           # how many frames to probe (evenly spaced)


def _probe_size(video_path: str) -> Optional[tuple[int, int]]:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=15,
        )
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return None


def extract_frames(video_path: str, n: int = SAMPLE_FRAMES) -> list[np.ndarray]:
    """Extract n evenly spaced grayscale frames, 480px wide, as float arrays.

    Uses ffmpeg frame extraction to rawvideo + numpy reshape.  Robust to
    short videos (fewer frames than n is fine).
    """
    size = _probe_size(video_path)
    if size is None:
        return []
    vw, vh = size
    scale = 480 / vw
    th = max(2, int(round(vh * scale / 2) * 2))  # keep even
    dur = _probe_duration(video_path)
    if dur <= 0:
        dur = 10.0
    step = max(0.1, dur / n)
    frames: list[np.ndarray] = []
    for i in range(n):
        ts = min(dur - 0.05, i * step)
        try:
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{ts:.2f}", "-i", video_path,
                 "-frames:v", "1", "-vf", f"scale=480:{th},format=gray",
                 "-f", "rawvideo", "-"],
                capture_output=True, timeout=30,
            )
            if len(r.stdout) >= 480 * th:
                arr = np.frombuffer(r.stdout, dtype=np.uint8).reshape(th, 480)
                frames.append(arr.astype(np.float32))
        except Exception:
            continue
    return frames


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _gradient_energy(img: np.ndarray) -> float:
    gy, gx = np.gradient(img)
    return float(np.mean(np.abs(gx) + np.abs(gy)))


def border_row_deltas(img: np.ndarray, frac: float = BORDER_FRAC) -> list[float]:
    """Per-row mirror deltas for top + bottom border strips of one frame.

    Positive delta = the row correlates better with the FLIPPED interior
    row than with the same-side interior row (a mirror artifact).  Returns
    raw per-row values so the caller can aggregate across frames robustly.
    """
    h, w = img.shape
    bh = max(2, int(h * frac))

    def corr(a: np.ndarray, b: np.ndarray) -> float:
        a = a - a.mean(); b = b - b.mean()
        denom = (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9)
        return float((a * b).sum() / denom)

    def deltas(top_rows, inner_rows):
        return [corr(top_rows[i], inner_rows[::-1][i]) -
                corr(top_rows[i], inner_rows[i])
                for i in range(len(top_rows))]

    out = deltas(img[:bh, :], img[bh:2 * bh, :])
    out += deltas(img[-bh:, :], img[-2 * bh:-bh, :])
    # left/right columns, transposed so rows become columns
    bw = max(2, int(w * frac))
    out += deltas(img[:, :bw].T, img[:, bw:2 * bw].T)
    return out


def check_frame_mirror(img: np.ndarray, frac: float = BORDER_FRAC) -> dict:
    """Per-frame mirror detection (aggregated deltas).  Kept for tests;
    the video-level gate uses :func:`border_row_deltas` across frames."""
    deltas = border_row_deltas(img, frac)
    worst = max(deltas) if deltas else 0.0
    return {"passed": worst < MIRROR_P90, "deltas": deltas, "worst": worst}


def check_frame_smear(img: np.ndarray, frac: float = BORDER_FRAC) -> dict:
    """Border blur detection: border gradient energy vs interior."""
    h, w = img.shape
    bh = max(2, int(h * frac))
    border = np.vstack([img[:bh, :], img[-bh:, :]])
    interior = img[bh:-bh, :]
    e_border = _gradient_energy(border)
    e_interior = _gradient_energy(interior) + 1e-9
    ratio = e_border / e_interior
    return {"passed": ratio >= SMEAR_RATIO, "ratio": float(ratio)}


def check_frame_seam(img: np.ndarray) -> dict:
    """Vertical/horizontal seam lines: a row/col whose diff from neighbors
    spikes far above the frame's own 99.5th percentile AND whose content
    does not continue smoothly into its neighbor (a duplicated or stretched
    strip shows a hard boundary; a natural high-contrast edge continues
    into the adjacent line, so neighbor correlation stays high)."""
    h, w = img.shape
    row_diff = np.abs(np.diff(img, axis=0)).mean(axis=1)   # h-1 values
    col_diff = np.abs(np.diff(img, axis=1)).mean(axis=0)   # w-1 values
    r_p = np.percentile(row_diff, SEAM_PCT) + 1e-9
    c_p = np.percentile(col_diff, SEAM_PCT) + 1e-9
    r_max = row_diff.max()
    c_max = col_diff.max()

    def _neighbor_corr_col(idx):
        if idx <= 0 or idx >= w - 2:
            return 1.0
        a, b = img[:, idx], img[:, idx + 1]
        if a.std() < 1e-6 or b.std() < 1e-6:
            return 1.0
        return float(np.corrcoef(a, b)[0, 1])

    def _neighbor_corr_row(idx):
        if idx <= 0 or idx >= h - 2:
            return 1.0
        a, b = img[idx, :], img[idx + 1, :]
        if a.std() < 1e-6 or b.std() < 1e-6:
            return 1.0
        return float(np.corrcoef(a, b)[0, 1])

    col_seam = False
    col_idx = None
    if c_max > SEAM_FACTOR * c_p:
        idx = int(col_diff.argmax())
        col_idx = idx
        col_seam = _neighbor_corr_col(idx) < SEAM_MAX_NEIGHBOR_CORR
    row_seam = False
    if r_max > SEAM_FACTOR * r_p:
        idx = int(row_diff.argmax())
        row_seam = _neighbor_corr_row(idx) < SEAM_MAX_NEIGHBOR_CORR
    seam = col_seam or row_seam
    return {"passed": not seam, "row_anomaly": float(r_max / r_p),
            "col_anomaly": float(c_max / c_p),
            "col_index": col_idx if col_seam else None}


def check_aspect_stretch(video_path: str) -> dict:
    """Aspect-ratio sanity: final video must be 16:9 (rendered output)."""
    size = _probe_size(video_path)
    if size is None:
        return {"passed": True, "detail": "size unprobeable"}
    w, h = size
    ar = w / h
    ok = abs(ar - 16 / 9) < 0.02
    return {"passed": ok,
            "detail": f"{w}x{h} aspect {ar:.3f} (16:9)" if ok
                      else f"WRONG ASPECT {w}x{h} ({ar:.3f}) — stretched/non-16:9"}


def run_visual_artifact_check(video_path: str,
                              n_frames: int = SAMPLE_FRAMES) -> dict:
    """Full rec #5 gate on a rendered video.  Deterministic, no LLM."""
    checks: list[dict] = []

    stretch = check_aspect_stretch(video_path)
    checks.append({"name": "aspect_ratio", **stretch})

    frames = extract_frames(video_path, n_frames)
    if not frames:
        checks.append({"name": "frames_available", "passed": False,
                       "detail": "could not extract frames for artifact scan"})
        return {"passed": False, "checks": checks, "frames_checked": 0}

    mirror_hits, smear_hits, seam_hits = [], [], []
    mirror_deltas: list[float] = []
    seam_positions: list[int] = []  # column indices of seam candidates
    for i, f in enumerate(frames):
        # Skip essentially-black frames (luma < 5): every artifact metric is
        # meaningless on a blank frame and black is a separate QA concern
        # (frozen/opening checks already own it).
        if f.mean() < 5.0:
            continue
        mirror_deltas += border_row_deltas(f)
        s = check_frame_smear(f)
        if not s["passed"]:
            smear_hits.append(f"frame{i}:ratio={s['ratio']:.2f}")
        se = check_frame_seam(f)
        if not se["passed"]:
            seam_hits.append(f"frame{i}:row={se['row_anomaly']:.0f}x,col={se['col_anomaly']:.0f}x")
            if se.get("col_index") is not None:
                seam_positions.append(se["col_index"])

    # Mirror verdict from the robust aggregate: the 90th percentile of ALL
    # border-row deltas across frames (single-row chance correlations and
    # flat-frame noise wash out; sustained border mirroring does not).
    if mirror_deltas:
        import numpy as _np
        p90 = float(_np.percentile(mirror_deltas, 90))
        if p90 >= MIRROR_P90:
            mirror_hits.append(f"p90 delta {p90:+.2f} >= {MIRROR_P90:.2f}")

    # Seam verdict with PERSISTENCE: a real duplicated/stretched strip is a
    # static artifact — its seam column reappears at the same position in
    # multiple frames (camera motion moves natural edges, so they scatter).
    if seam_hits:
        from collections import Counter as _Counter
        pos_counts = _Counter(seam_positions)
        persistent = [p for p, n in pos_counts.items() if n >= 2]
        if not persistent:
            seam_hits = []  # all seams were transient (natural edges)

    checks.append({"name": "mirrored_edges", "passed": not mirror_hits,
                   "detail": "no mirrored border artifacts"
                   if not mirror_hits else "mirror artifacts: " + "; ".join(mirror_hits[:5])})
    checks.append({"name": "smeared_borders", "passed": not smear_hits,
                   "detail": "no smeared border padding"
                   if not smear_hits else "smear artifacts: " + "; ".join(smear_hits[:5])})
    checks.append({"name": "seam_lines", "passed": not seam_hits,
                   "detail": "no seam/duplicate-object lines"
                   if not seam_hits else "seam artifacts: " + "; ".join(seam_hits[:5])})

    failed = [c for c in checks if not c["passed"]]
    return {"passed": not failed, "checks": checks,
            "frames_checked": len(frames),
            "detail": "no visual artifacts detected"
                      if not failed else
                      "visual artifacts: " + "; ".join(c["name"] for c in failed)}


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "final_output.mp4"
    result = run_visual_artifact_check(path)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 2)
