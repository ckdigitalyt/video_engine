"""Fade/transition hardening (wave-2, glm_review_v3 §4.5).

Rules enforced:
  (a) fade durations ≤ MAX_FADE_S (0.4s) so fades complete between 1fps
      review samples — no mid-fade ghosts on keyframes;
  (b) minimum contrast during a fade: alpha-weighted luminance of the
      fading layer against the background must stay readable (the
      t≈28.5s dark-gray-on-navy ghost);
  (c) scene-state and text fades must run on synced schedules — callers
      pass one shared fade duration per beat boundary (see fade_windows);
  (d) thumbnail candidates never land inside a transition window.
"""

from __future__ import annotations

MAX_FADE_S = 0.4
MIN_FADE_CONTRAST = 0.18   # alpha-weighted luma delta floor (0..1)


def clamp_fade(duration: float) -> float:
    """Clamp any fade run_time to the <=0.4s rule."""
    try:
        d = float(duration)
    except (TypeError, ValueError):
        return MAX_FADE_S
    return min(max(d, 0.05), MAX_FADE_S)


def fade_windows_from_spec(visualspec: dict,
                           max_fade: float = MAX_FADE_S) -> list[tuple[float, float]]:
    """Transition windows: every beat boundary ± max_fade.  Scene state,
    text layers and camera moves all change at beat boundaries, so this
    is the (synced) union schedule used for sampling and thumbnails."""
    windows: list[tuple[float, float]] = []
    for b in visualspec.get("beats", []):
        for t in (float(b.get("start", 0.0) or 0.0),
                  float(b.get("end", 0.0) or 0.0)):
            windows.append((round(max(0.0, t - max_fade), 3),
                            round(t + max_fade, 3)))
    return _merge(windows)


def _merge(windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(windows):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def in_fade_window(t: float, windows: list[tuple[float, float]]) -> bool:
    return any(a <= t <= b for a, b in windows)


def thumbnail_candidate_times(total_duration: float, n: int = 5,
                              exclude: list[tuple[float, float]] | None = None,
                              margin_s: float = 0.6) -> list[float]:
    """Evenly spaced thumbnail candidate timestamps that NEVER sit inside
    a fade window (rule d): candidates are re-drawn to the nearest safe
    spot outside every window with a small margin."""
    exclude = exclude or []
    span = max(0.1, total_duration - 2 * margin_s)
    raw = [margin_s + span * (i + 0.5) / n for i in range(n)]
    safe: list[float] = []
    for t in raw:
        cand = t
        for _ in range(40):
            if not in_fade_window(cand, exclude):
                break
            # push to the nearest window edge + margin, AWAY from the
            # window (cand inside the window: move past the edge)
            dists = [(min(abs(cand - a), abs(cand - b)), (a if abs(cand - a) < abs(cand - b) else b))
                     for a, b in exclude] or [(0.0, cand)]
            _, edge = min(dists)
            cand = edge + (margin_s if cand < edge else -margin_s)
            cand = min(max(cand, 0.0), total_duration - 0.05)
        safe.append(round(cand, 3))
    return safe


def safe_timestamp(ts: float, windows: list[tuple[float, float]],
                   total_duration: float | None = None,
                   margin_s: float = 0.6) -> float:
    """Shift a single candidate timestamp out of every fade window."""
    if not in_fade_window(ts, windows):
        return round(ts, 3)
    for cand in thumbnail_candidate_times(
            total_duration or (ts + 2 * margin_s + 1.0), n=8,
            exclude=windows, margin_s=margin_s):
        if not in_fade_window(cand, windows) and abs(cand - ts) <= 2.0:
            return cand
    return round(ts, 3)


def alpha_weighted_contrast(fg_luma: float, bg_luma: float,
                            alpha: float) -> float:
    """Readable-contrast of a layer at opacity `alpha` over `bg`.

    Perceived luma of the blended layer = alpha*fg + (1-alpha)*bg; the
    effective contrast vs the background is the ABSOLUTE luma delta
    scaled by the layer's visibility (alpha) — a fully transparent layer
    has zero contrast by definition, and a dark-gray ghost on navy
    (v3 t≈28.5s) scores far below the floor.
    """
    alpha = min(max(float(alpha), 0.0), 1.0)
    fg = min(max(float(fg_luma), 0.0), 1.0)
    bg = min(max(float(bg_luma), 0.0), 1.0)
    blended = alpha * fg + (1.0 - alpha) * bg
    return abs(blended - bg)


def passes_fade_contrast(fg_luma: float, bg_luma: float, alpha: float,
                         floor: float = MIN_FADE_CONTRAST) -> bool:
    """A fade frame is acceptable when the blended layer is readable OR
    nearly invisible (alpha low enough that no ghost would sample)."""
    c = alpha_weighted_contrast(fg_luma, bg_luma, alpha)
    return c >= floor or alpha <= 0.5 * floor
