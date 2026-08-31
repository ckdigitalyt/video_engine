#!/usr/bin/env python3
"""V4 forensic audit tool — deterministic, offline, per-video visual audit.

Motivation (docs/directives/v4_cinematography_2026-08-30.md §1-§3): the V3
publish gate scored shots 100/100 on technical metadata alone while the output
behaved like an animated slideshow. This tool measures what the gate did not:

  * declared vs actual container/stream metadata (ffprobe, never trusted input)
  * frame-to-frame visual change (mean absolute gray delta per frame pair)
  * STATIC-HOLD detection (longest run of near-identical frames; the §3 rule:
    a static hold > 2.5 s is a warning)
  * VISUAL EVENT DENSITY (§2): significant frame-change spikes per 10 s
  * black / luminance-flat (text-card) seconds
  * pseudo-motion discrimination: is the observed change just a global
    zoom/pan (Ken Burns) over an otherwise frozen scene?
  * perceptual-hash (dhash) sampling for repeated-imagery detection

Everything is computed from decoded pixels on CPU (numpy only); no GPU, no
network, no API keys. Usage:

    python tools/v4_audit.py results/dino_v1/master.mp4 --label dino_v1_master \
        --outdir results/dino_v1/audit
    python tools/v4_audit.py results/dino_v1/assemble/clips/ --batch

Writes <outdir>/<label>.audit.json plus a markdown summary next to it.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# Tunables (defaults; CLI flags override). Calibrated on 192x108 grayscale
# decodes at native fps: JPEG/h264 noise keeps a truly frozen shot below
# ~0.7 mean-abs-delta, Ken Burns drift sits around 1-3, cuts/spikes > 8.
# --------------------------------------------------------------------------
DEFAULT_STATIC_THRESHOLD = 0.7   # mean-abs gray delta below this = "unchanged"
DEFAULT_SPIKE_THRESHOLD = 8.0    # mean-abs gray delta above this = "event"
DEFAULT_ZOOM_CORR = 0.6          # median |diff|-vs-gradient corr for Ken Burns
STATIC_HOLD_WARN_SEC = 2.5       # directive §3
BLACK_LUMA = 16.0                # mean luma below this = black frame
FLAT_STD = 22.0                  # spatial std below this = flat/card-like frame
ANALYSIS_SIZE = (192, 108)       # decode size (w, h), keeps 16:9 geometry


# --------------------------------------------------------------------------
# ffprobe / ffmpeg helpers
# --------------------------------------------------------------------------

def probe(path: str | Path) -> dict:
    """Actual container/stream metadata via ffprobe (the §1 ground truth)."""
    path = str(path)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_frames",
         "-show_entries", "format=duration,size",
         "-of", "json", path],
        check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    st = (d.get("streams") or [{}])[0]
    fmt = d.get("format") or {}
    num, _, den = (st.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(num or 0) else 0.0
    return {
        "codec": st.get("codec_name"),
        "width": st.get("width"),
        "height": st.get("height"),
        "fps": round(fps, 3),
        "nb_frames": int(st["nb_frames"]) if st.get("nb_frames") else None,
        "duration_sec": round(float(fmt["duration"]), 3) if fmt.get("duration") else None,
        "size_bytes": int(fmt["size"]) if fmt.get("size") else None,
    }


def decode_frames(path: str | Path, width: int = ANALYSIS_SIZE[0],
                  height: int = ANALYSIS_SIZE[1]) -> np.ndarray:
    """Decode all video frames to a (N, H, W) uint8 grayscale array."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path),
           "-vf", f"scale={width}:{height}", "-pix_fmt", "gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    n = len(raw) // (width * height)
    if n == 0:
        raise RuntimeError(f"no frames decoded from {path}")
    return np.frombuffer(raw[: n * width * height], dtype=np.uint8).reshape(n, height, width)


# --------------------------------------------------------------------------
# Metric functions (unit-tested in tests/test_v4_audit.py)
# --------------------------------------------------------------------------

def frame_deltas(frames: np.ndarray) -> np.ndarray:
    """Mean absolute pixel difference (0-255 scale) per consecutive frame pair.

    len(deltas) == len(frames) - 1; deltas[i] compares frames[i] and frames[i+1].
    """
    if len(frames) < 2:
        return np.zeros(0, dtype=np.float32)
    a = frames[:-1].astype(np.float32)
    b = frames[1:].astype(np.float32)
    return np.abs(a - b).mean(axis=(1, 2))


def static_holds(deltas: np.ndarray, fps: float,
                 threshold: float = DEFAULT_STATIC_THRESHOLD) -> list[dict]:
    """Runs of consecutive frame pairs whose delta is below `threshold`.

    Returns list of {start_sec, end_sec, duration_sec, frames} sorted by time.
    """
    holds = []
    run_start = None
    for i, d in enumerate(deltas):
        if d < threshold:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                holds.append((run_start, i))  # pairs [run_start, i)
                run_start = None
    if run_start is not None:
        holds.append((run_start, len(deltas)))
    out = []
    for a, b in holds:
        out.append({
            "start_sec": round(a / fps, 3),
            "end_sec": round(b / fps, 3),
            "duration_sec": round((b - a) / fps, 3),
            "frames": b - a,
        })
    return out


def longest_hold_sec(holds: list[dict]) -> float:
    return max((h["duration_sec"] for h in holds), default=0.0)


def count_events(deltas: np.ndarray, threshold: float = DEFAULT_SPIKE_THRESHOLD) -> int:
    """Significant visual events: frame pairs with delta >= threshold.

    Counts *clusters* of consecutive spiking pairs as one event (a cut or flash
    usually spans 2-3 pairs at scene level).
    """
    spikes = deltas >= threshold
    if not spikes.any():
        return 0
    # count rising edges (cluster starts)
    return int(np.count_nonzero(spikes & ~np.concatenate(([False], spikes[:-1]))))


def visual_event_density(deltas: np.ndarray, fps: float,
                         spike_threshold: float = DEFAULT_SPIKE_THRESHOLD,
                         static_threshold: float = DEFAULT_STATIC_THRESHOLD) -> dict:
    """VISUAL EVENT DENSITY (directive §2): events per 10 s, plus motion stats.

    A frozen slideshow scores ~0; a shot with real internal events scores > 0.
    """
    dur = (len(deltas) + 1) / fps if fps else 0.0
    events = count_events(deltas, spike_threshold)
    moving = deltas >= static_threshold
    return {
        "duration_sec": round(dur, 3),
        "events": events,
        "events_per_10s": round(events * 10.0 / dur, 3) if dur else 0.0,
        "mean_delta": round(float(deltas.mean()), 3) if len(deltas) else 0.0,
        "p95_delta": round(float(np.percentile(deltas, 95)), 3) if len(deltas) else 0.0,
        "moving_pair_fraction": round(float(moving.mean()), 3) if len(deltas) else 0.0,
    }


CHANGED_PIXEL_DELTA = 10.0  # per-pixel gray delta counting a pixel as "changed"


def changed_pixel_fraction(frames: np.ndarray) -> float:
    """Mean fraction of pixels changing > CHANGED_PIXEL_DELTA between pairs.

    Complements mean-abs-delta: a small moving subject over a frozen background
    yields a tiny mean delta; this tells you *how much* of the frame is alive.
    dino_v1 forensics: even the "best" shots changed < 0.4% of pixels.
    """
    if len(frames) < 2:
        return 0.0
    a = frames[:-1].astype(np.float32)
    b = frames[1:].astype(np.float32)
    changed = (np.abs(a - b) > CHANGED_PIXEL_DELTA).mean(axis=(1, 2))
    return round(float(changed.mean()), 4)


def black_flat_seconds(frames: np.ndarray, fps: float,
                       black_luma: float = BLACK_LUMA,
                       flat_std: float = FLAT_STD) -> dict:
    """Seconds of black frames and of luminance-flat (text-card-like) frames."""
    if len(frames) == 0:
        return {"black_sec": 0.0, "flat_sec": 0.0, "flat_fraction": 0.0}
    means = frames.astype(np.float32).mean(axis=(1, 2))
    stds = frames.astype(np.float32).std(axis=(1, 2))
    black = means < black_luma
    flat = (stds < flat_std) & ~black  # flat but not pure black = card/title
    return {
        "black_sec": round(float(black.sum()) / fps, 3),
        "flat_sec": round(float(flat.sum()) / fps, 3),
        "flat_fraction": round(float(flat.mean()), 3),
    }


def _phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Global (dx, dy) translation between two frames via FFT phase correlation."""
    fa = np.fft.rfft2(a.astype(np.float32) - a.mean())
    fb = np.fft.rfft2(b.astype(np.float32) - b.mean())
    cross = fa * np.conj(fb)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=a.shape)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    h, w = a.shape
    dy = peak[0] if peak[0] <= h // 2 else peak[0] - h
    dx = peak[1] if peak[1] <= w // 2 else peak[1] - w
    return float(dx), float(dy), float(corr[peak])


def global_motion(frames: np.ndarray, max_pairs: int = 400) -> dict:
    """Detect global zoom/pan (Ken Burns) vs local/subject motion.

    Strategy: on a subsampled pair set, correlate |frame diff| with the frame's
    gradient magnitude. A pure zoom/pan changes pixels exactly where the image
    has edges (corr ~ 1); independent subject/particle motion decorrelates.
    Also estimates translation via phase correlation.
    """
    n = len(frames)
    if n < 2:
        return {"zoom_corr_median": 0.0, "dominant_pan": None, "consistent_pan_fraction": 0.0}
    idx = np.unique(np.linspace(0, n - 2, num=min(max_pairs, n - 1), dtype=int))
    corrs, dxs, dys = [], [], []
    for i in idx:
        f1 = frames[i].astype(np.float32)
        f2 = frames[i + 1].astype(np.float32)
        diff = np.abs(f2 - f1)
        gy, gx = np.gradient(f1)
        grad = np.hypot(gx, gy)
        if diff.mean() < 0.5:
            # frozen pair: pan estimate from phase correlation would be noise
            dxs.append(0.0)
            dys.append(0.0)
            continue
        if grad.std() < 1e-6 or diff.std() < 1e-6:
            continue
        c = np.corrcoef(diff.ravel(), grad.ravel())[0, 1]
        if not math.isnan(c):
            corrs.append(c)
        dx, dy, _pk = _phase_shift(frames[i], frames[i + 1])
        dxs.append(dx)
        dys.append(dy)
    if not corrs:
        return {"zoom_corr_median": 0.0, "dominant_pan": None, "consistent_pan_fraction": 0.0}
    dxs_a, dys_a = np.array(dxs), np.array(dys)
    # a "pan" only counts if there is consistent sub-pixel drift in one axis
    def consistent(v):
        pos = (v > 0).mean()
        return max(pos, 1 - pos)
    pan_x, pan_y = consistent(dxs_a), consistent(dys_a)
    dominant = None
    if pan_x > 0.9 and np.abs(dxs_a).mean() > 0.2:
        dominant = "pan_x"
    elif pan_y > 0.9 and np.abs(dys_a).mean() > 0.2:
        dominant = "pan_y"
    return {
        "zoom_corr_median": round(float(np.median(corrs)), 3),
        "dominant_pan": dominant,
        "consistent_pan_fraction": round(float(max(pan_x, pan_y)), 3),
    }


def classify_motion(deltas: np.ndarray, fps: float, duration_sec: float,
                    holds: list[dict], motion: dict,
                    static_threshold: float = DEFAULT_STATIC_THRESHOLD,
                    zoom_corr_threshold: float = DEFAULT_ZOOM_CORR) -> str:
    """Directive §3 classes: true_motion | pseudo_motion | static_hold.

    static_hold  — content effectively frozen for a long stretch (>= 2.5 s and
                   covering most of the shot)
    pseudo_motion — pixels keep changing but the change is a global Ken Burns
                   zoom/pan over an otherwise frozen scene (no internal events)
    true_motion  — internal scene events (subject motion, particles, light…)
    """
    longest = longest_hold_sec(holds)
    events = count_events(deltas)
    moving_fraction = float((deltas >= static_threshold).mean()) if len(deltas) else 0.0
    frozen_fraction = 1.0 - moving_fraction
    if duration_sec > 0 and longest >= max(STATIC_HOLD_WARN_SEC, 0.5 * duration_sec) \
            and frozen_fraction >= 0.5:
        return "static_hold"
    if frozen_fraction >= 0.8:
        # frozen nearly the whole time (e.g. a single cut between frozen slides)
        return "static_hold"
    ken_burns = (motion.get("zoom_corr_median", 0.0) >= zoom_corr_threshold
                 or motion.get("dominant_pan") is not None)
    if events == 0 and ken_burns and moving_fraction >= 0.3:
        return "pseudo_motion"
    if deltas.mean() < static_threshold:
        return "static_hold"
    return "true_motion"


# --------------------------------------------------------------------------
# dhash (perceptual hashing for repeated-imagery detection)
# --------------------------------------------------------------------------

def dhash(img: np.ndarray, hash_size: int = 8) -> int:
    """64-bit dhash of a grayscale image (row-wise gradient bits)."""
    # downscale to (hash_size+1) x hash_size with simple area sampling
    h, w = img.shape
    small = img[:: max(1, h // (hash_size + 1)), :: max(1, w // hash_size)]
    small = np.asarray(small[: hash_size + 1, : hash_size], dtype=np.float32)
    diff = small[1:, :] > small[:-1, :]
    bits = diff.ravel()
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def sample_hashes(frames: np.ndarray, n: int = 5) -> list[dict]:
    """Sampled perceptual hashes + coarse luminance structure per frame.

    The hash alone phantom-clusters flat fields: two unrelated near-uniform
    plates (a dark template stage vs a bright split-screen panel) both hash
    to near-zero gradient signs, so dino_v2 r3.1's dark impact map and its
    bright BEFORE panel matched at hamming 4. find_duplicates therefore
    also requires agreement on mean luma and spatial std — two flat fields
    of different brightness are not repeated imagery."""
    idx = np.unique(np.linspace(0, len(frames) - 1, num=min(n, len(frames)), dtype=int))
    out: list[dict] = []
    for i in idx:
        fr = frames[i].astype(np.float32)
        out.append({"hash": dhash(frames[i]),
                    "mean": round(float(fr.mean()), 1),
                    "std": round(float(fr.std()), 1)})
    return out


def find_duplicates(hash_samples: list[dict], max_hamming: int = 6) -> list[dict]:
    """Cross-shot near-duplicate clusters.

    hash_samples: [{"label": str, "t": float, "hash": int
                    [, "mean": float, "std": float]}, ...]
    Returns clusters of visually identical frames that come from >= 2 labels.
    A pair joins a cluster only when the hashes agree AND the coarse
    luminance structure agrees (mean within 12, std within 10, when the
    fields are present) — see sample_hashes for why.
    """
    parent = list(range(len(hash_samples)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def same_structure(a: dict, b: dict) -> bool:
        if "mean" not in a or "mean" not in b:
            return True
        if abs(float(a["mean"]) - float(b["mean"])) > 12.0:
            return False
        if "std" in a and "std" in b \
                and abs(float(a["std"]) - float(b["std"])) > 10.0:
            return False
        return True

    for i in range(len(hash_samples)):
        for j in range(i + 1, len(hash_samples)):
            if hamming(hash_samples[i]["hash"], hash_samples[j]["hash"]) <= max_hamming \
                    and same_structure(hash_samples[i], hash_samples[j]):
                parent[find(i)] = find(j)
    clusters: dict[int, list[int]] = {}
    for i in range(len(hash_samples)):
        clusters.setdefault(find(i), []).append(i)
    out = []
    for members in clusters.values():
        labels = {hash_samples[m]["label"] for m in members}
        if len(labels) >= 2:
            out.append({
                "labels": sorted(labels),
                "members": [{k: hash_samples[m][k] for k in ("label", "t")} for m in members],
            })
    return out


# --------------------------------------------------------------------------
# Per-video audit
# --------------------------------------------------------------------------

def audit_video(path: str | Path, label: str | None = None,
                static_threshold: float = DEFAULT_STATIC_THRESHOLD,
                spike_threshold: float = DEFAULT_SPIKE_THRESHOLD) -> dict:
    path = Path(path)
    label = label or path.stem
    meta = probe(path)
    fps = meta["fps"] or 30.0
    frames = decode_frames(path)
    deltas = frame_deltas(frames)
    holds = static_holds(deltas, fps, static_threshold)
    density = visual_event_density(deltas, fps, spike_threshold, static_threshold)
    density["changed_pixel_fraction"] = changed_pixel_fraction(frames)
    bf = black_flat_seconds(frames, fps)
    motion = global_motion(frames)
    dur = density["duration_sec"]
    result = {
        "label": label,
        "path": str(path),
        "metadata": meta,
        "visual_event_density": density,
        "static_holds": {
            "threshold": static_threshold,
            "longest_hold_sec": longest_hold_sec(holds),
            "holds_over_2_5s": [h for h in holds if h["duration_sec"] > STATIC_HOLD_WARN_SEC],
            "total_hold_sec": round(sum(h["duration_sec"] for h in holds), 3),
            "runs": holds,
        },
        "black_flat": bf,
        "global_motion": motion,
        "motion_class": classify_motion(deltas, fps, dur, holds, motion,
                                        static_threshold),
        "hash_samples": [
            {"label": label, "t": round(i / fps, 3), **h}
            for i, h in zip(
                np.unique(np.linspace(0, max(len(frames) - 1, 0),
                                      num=min(5, len(frames)), dtype=int)),
                sample_hashes(frames, 5))
        ],
    }
    return result


def to_markdown(a: dict) -> str:
    m = a["metadata"]
    d = a["visual_event_density"]
    s = a["static_holds"]
    lines = [
        f"## {a['label']} — `{a['path']}`",
        "",
        f"- container: {m['codec']} {m['width']}x{m['height']} @ {m['fps']} fps, "
        f"{m['duration_sec']} s, {m['nb_frames']} frames",
        f"- events: {d['events']} ({d['events_per_10s']}/10 s), mean delta {d['mean_delta']}, "
        f"p95 {d['p95_delta']}, moving pairs {d['moving_pair_fraction']*100:.0f}%",
        f"- motion class: **{a['motion_class']}** "
        f"(zoom-corr {a['global_motion']['zoom_corr_median']}, "
        f"pan {a['global_motion']['dominant_pan']})",
        f"- static hold: longest **{s['longest_hold_sec']} s**, "
        f"holds > 2.5 s: {len(s['holds_over_2_5s'])}, "
        f"total frozen {s['total_hold_sec']} s",
        f"- black {a['black_flat']['black_sec']} s, flat/card {a['black_flat']['flat_sec']} s "
        f"({a['black_flat']['flat_fraction']*100:.0f}%)",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="video file or directory (with --batch)")
    ap.add_argument("--label", default=None)
    ap.add_argument("--outdir", default="audit_out")
    ap.add_argument("--batch", action="store_true", help="audit every *.mp4 in dir")
    ap.add_argument("--static-threshold", type=float, default=DEFAULT_STATIC_THRESHOLD)
    ap.add_argument("--spike-threshold", type=float, default=DEFAULT_SPIKE_THRESHOLD)
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    targets = (sorted(Path(args.target).glob("*.mp4")) if args.batch
               else [Path(args.target)])
    md_parts = ["# V4 Audit\n"]
    for t in targets:
        a = audit_video(t, static_threshold=args.static_threshold,
                        spike_threshold=args.spike_threshold)
        name = a["label"].replace("/", "_")
        (outdir / f"{name}.audit.json").write_text(json.dumps(a, indent=1))
        md_parts.append(to_markdown(a))
    (outdir / "audit_summary.md").write_text("\n".join(md_parts))
    print(f"wrote {len(targets)} audit(s) to {outdir}/audit_summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
