"""Continuous scene-parameter tweening (wave-2 motion, review v3 §4.1).

Replaces the state-flip slideshow: numeric scene parameters (fill level,
camera x/zoom, particle drift, counter values) interpolate CONTINUOUSLY
between beat timestamps instead of hard flips at beat boundaries.

Contract (visualspec_v2, VisualBeat.scene_params):
    [{"param": "fill_level", "from": 0.0, "to": 1.0, "ease": "smooth"}, ...]

Each beat declares the value its parameters reach BY THE END of the beat;
the timeline builder chains beats into one keyframe track per parameter and
`sample_param` evaluates it at any time — so a fill level rises while
"as b grows" is spoken, a counter ticks toward ∞, and the camera crawls
down the thinning tail, all with zero static 1.5s windows.

Pure functions only: deterministic, unit-testable, no manim import.
"""

from __future__ import annotations

from typing import Any

# Canonical numeric scene parameters (extensible; unknown params tween the
# same way — the renderer decides which have visual hooks).
CANONICAL_PARAMS: tuple[str, ...] = (
    "fill_level",     # 0..1 paint fill inside the hero shape
    "camera_x",       # horizontal camera offset (screen units)
    "camera_zoom",    # 1.0 = default frame, <1 zoomed in
    "particle_drift", # particle field drift speed multiplier
    "counter_value",  # numeric counter (e.g. b → ∞ tick)
)

_EASINGS = {"linear", "smooth"}


def ease_smoothstep(t: float) -> float:
    """Hermite smoothstep on [0,1] — C1-continuous, no velocity jumps."""
    t = min(max(float(t), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _apply_ease(t: float, mode: str) -> float:
    if mode == "smooth":
        return ease_smoothstep(t)
    return min(max(float(t), 0.0), 1.0)


def beat_scene_params(beat: dict) -> list[dict]:
    """Validated scene_params entries of one beat (empty when absent)."""
    out: list[dict] = []
    for p in beat.get("scene_params", []) or []:
        if not isinstance(p, dict):
            continue
        param = str(p.get("param", "")).strip()
        if not param:
            continue
        ease = str(p.get("ease", "smooth"))
        if ease not in _EASINGS:
            ease = "smooth"
        out.append({"param": param,
                    "from": float(p.get("from", 0.0)),
                    "to": float(p.get("to", 0.0)),
                    "ease": ease})
    return out


def build_param_timelines(vs: dict) -> dict[str, list[tuple[float, float]]]:
    """Chain per-beat scene_params into one keyframe track per parameter.

    Returns {param: [(t, value), ...]} with strictly increasing timestamps.
    A beat that declares a param continues from the previous beat's value
    when no explicit `from` is given (continuity by construction).
    """
    tracks: dict[str, list[tuple[float, float]]] = {}
    current: dict[str, float] = {}
    for beat in vs.get("beats", []):
        start = float(beat.get("start", 0.0) or 0.0)
        end = float(beat.get("end", start) or start)
        for p in beat_scene_params(beat):
            param = p["param"]
            t0 = max(start, 0.0)
            t1 = max(end, t0)
            frm = p["from"] if "from" in p and p["from"] != p["to"] \
                else current.get(param, p["from"])
            # explicit `from` always wins; otherwise continue smoothly
            if track_has_value_at(tracks.get(param), t0):
                frm = sample_track(tracks[param], t0)
            track = tracks.setdefault(param, [])
            if not track or track[-1][0] < t0 - 1e-9:
                track.append((t0, frm))
            track.append((t1, p["to"]))
            current[param] = p["to"]
    return tracks


def track_has_value_at(track: list[tuple[float, float]] | None,
                       t: float) -> bool:
    return bool(track) and track[0][0] <= t <= track[-1][0]


def sample_track(track: list[tuple[float, float]], t: float,
                 ease: str = "smooth") -> float:
    """Interpolate one track at time t (clamped to the end values)."""
    if not track:
        return 0.0
    if t <= track[0][0]:
        return track[0][1]
    if t >= track[-1][0]:
        return track[-1][1]
    for (t0, v0), (t1, v1) in zip(track, track[1:]):
        if t0 <= t <= t1:
            span = (t1 - t0) or 1e-9
            u = _apply_ease((t - t0) / span, ease)
            return v0 + (v1 - v0) * u
    return track[-1][1]


def sample_param(tracks: dict[str, list[tuple[float, float]]],
                 param: str, t: float) -> float:
    return sample_track(tracks.get(param, []), t)


def tween_statements_for_beat(beat: dict) -> list[dict]:
    """Emission plan for the compiler: which params tween in this beat.

    Returned dicts are compiler-facing: {param, to, ease}.  The compiler
    animates a ValueTracker from the previous beat's end value to `to`
    across the WHOLE beat duration (continuous motion, no hold windows).
    """
    return beat_scene_params(beat)


# ── QA support: frame-diff motion gate ─────────────────────────────────
def frame_diff_ratios(raw_frames: list[bytes], w: int, h: int,
                      threshold: int = 12) -> list[float]:
    """Fraction of pixels changed between consecutive raw gray frames.

    `raw_frames` are w*h gray bytes.  A pixel counts as changed when the
    absolute luma delta exceeds `threshold` (8-bit).  Pure and fast —
    the QA gate feeds it with ffmpeg-extracted frames.
    """
    import numpy as np
    out: list[float] = []
    prev: np.ndarray | None = None
    for raw in raw_frames:
        if len(raw) < w * h:
            continue
        cur = np.frombuffer(raw[:w * h], dtype=np.uint8).reshape(h, w)
        if prev is not None:
            changed = int((np.abs(cur.astype(np.int16)
                                  - prev.astype(np.int16)) > threshold).sum())
            out.append(changed / float(w * h))
        prev = cur
    return out


def static_windows(diff_ratios: list[float], sample_fps: float,
                   window_s: float = 1.5,
                   motion_floor: float = 0.005) -> list[tuple[float, float]]:
    """Time windows (>=window_s long) where pixel change is near zero.

    Fails the wave-2 motion bar: any 1.5s window with <motion_floor of
    pixels changing is a static hold (v3 review: ~12s slideshow middle).
    """
    if not diff_ratios or sample_fps <= 0:
        return []
    n_win = max(1, int(round(window_s * sample_fps)))
    bad: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, r in enumerate(diff_ratios):
        if r < motion_floor:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and (i - run_start) >= n_win:
                a = run_start / sample_fps
                b = i / sample_fps
                bad.append((round(a, 2), round(b, 2)))
            run_start = None
    if run_start is not None and (len(diff_ratios) - run_start) >= n_win:
        bad.append((round(run_start / sample_fps, 2),
                    round(len(diff_ratios) / sample_fps, 2)))
    return bad
