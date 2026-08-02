"""
camera_language.py — Intent-driven camera direction + diversity metrics.

Reusable camera language: every move is a named, intent-mapped movement
(reveal, follow, orbit, push, pull, crane, tracking, parallax) instead of
random variation.  Tracks camera/transition/motion/asset diversity across
the timeline and flags repetitive patterns automatically.

Moves map to concrete ffmpeg/motion parameters via ``motion_params``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════ #
# Camera language
# ═══════════════════════════════════════════════════════════════════════ #

CAMERA_MOVES = {
    "reveal":    {"zoom_start": 1.25, "zoom_end": 1.0,  "pan_x": 0,    "pan_y": 0,
                  "desc": "start tight, pull out to reveal context"},
    "push_in":   {"zoom_start": 1.0,  "zoom_end": 1.22, "pan_x": 0,    "pan_y": 0,
                  "desc": "steady push toward subject"},
    "pull_out":  {"zoom_start": 1.22, "zoom_end": 1.0,  "pan_x": 0,    "pan_y": 0,
                  "desc": "pull away to show scale"},
    "pan_left":  {"zoom_start": 1.12, "zoom_end": 1.12, "pan_x": -60,  "pan_y": 0,
                  "desc": "lateral pan left"},
    "pan_right": {"zoom_start": 1.12, "zoom_end": 1.12, "pan_x": 60,   "pan_y": 0,
                  "desc": "lateral pan right"},
    "tilt_up":   {"zoom_start": 1.12, "zoom_end": 1.12, "pan_x": 0,    "pan_y": -40,
                  "desc": "vertical tilt up"},
    "tilt_down": {"zoom_start": 1.12, "zoom_end": 1.12, "pan_x": 0,    "pan_y": 40,
                  "desc": "vertical tilt down"},
    "orbit":     {"zoom_start": 1.15, "zoom_end": 1.15, "pan_x": 80,   "pan_y": 20,
                  "desc": "arc around subject (simulated diagonal drift)"},
    "crane_up":  {"zoom_start": 1.05, "zoom_end": 1.18, "pan_x": 0,    "pan_y": -60,
                  "desc": "rise while pushing in"},
    "tracking":  {"zoom_start": 1.1,  "zoom_end": 1.1,  "pan_x": -80,  "pan_y": 0,
                  "desc": "track alongside subject"},
    "parallax":  {"zoom_start": 1.2,  "zoom_end": 1.05, "pan_x": 50,   "pan_y": -30,
                  "desc": "depth shift (zoom out + drift)"},
    "static":    {"zoom_start": 1.0,  "zoom_end": 1.0,  "pan_x": 0,    "pan_y": 0,
                  "desc": "locked-off shot"},
}

# Narrative intent -> preferred camera vocabulary
INTENT_CAMERA = {
    "hook":        ["push_in", "reveal", "parallax"],
    "reveal":      ["reveal", "pull_out", "crane_up"],
    "scale":       ["pull_out", "parallax", "crane_up"],
    "journey":     ["tracking", "pan_right", "orbit"],
    "exploration": ["orbit", "pan_left", "pan_right", "tilt_up"],
    "emotion":     ["push_in", "reveal", "static"],
    "conclusion":  ["pull_out", "reveal", "static"],
    "default":     ["push_in", "reveal", "pan_right", "pull_out"],
}


@dataclass
class CameraDecision:
    move: str = "static"
    intent: str = "default"
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"move": self.move, "intent": self.intent, "params": self.params}


class CameraDirector:
    """Assigns intent-driven camera moves with diversity tracking."""

    def __init__(self, seed: Optional[int] = None):
        import random
        self._rng = random.Random(seed)
        self._history: list[str] = []
        self._used: dict[str, int] = {}

    def decide(self, intent: str = "default") -> CameraDecision:
        vocab = INTENT_CAMERA.get(intent, INTENT_CAMERA["default"])
        # avoid repeating the last move; prefer least-used in vocab
        candidates = [m for m in vocab if not self._history or m != self._history[-1]]
        if not candidates:
            candidates = vocab
        candidates.sort(key=lambda m: self._used.get(m, 0))
        pick = candidates[0] if self._rng.random() < 0.8 else self._rng.choice(candidates)
        self._history.append(pick)
        self._used[pick] = self._used.get(pick, 0) + 1
        params = dict(CAMERA_MOVES[pick])
        params.pop("desc", None)
        return CameraDecision(move=pick, intent=intent, params=params)

    # ── Diversity metrics ──────────────────────────────────────────────

    def diversity(self) -> dict:
        """Shannon entropy of the move distribution + repetition flags."""
        import math
        n = len(self._history)
        if n == 0:
            return {"moves": 0, "entropy": 0.0, "repetitive": False, "distribution": {}}
        dist = {m: self._used.get(m, 0) for m in set(self._history)}
        entropy = -sum((c / n) * math.log2(c / n) for c in dist.values())
        max_entropy = math.log2(max(1, len(dist)))
        norm = entropy / max_entropy if max_entropy > 0 else 1.0
        # repetitive: same move 3+ times in a row
        repetitive = any(
            all(self._history[i] == self._history[i + j] for j in range(3))
            for i in range(len(self._history) - 2)
        )
        return {
            "moves": n,
            "entropy": round(entropy, 3),
            "normalized_entropy": round(norm, 3),
            "repetitive": repetitive,
            "distribution": dist,
        }


class DiversityTracker:
    """Tracks asset/transition/motion/duration diversity across a timeline."""

    def __init__(self):
        self.assets: list[str] = []
        self.transitions: list[str] = []
        self.motions: list[str] = []
        self.durations: list[float] = []

    def record(self, asset: str, transition: str, motion: str, duration: float):
        self.assets.append(asset)
        self.transitions.append(transition)
        self.motions.append(motion)
        self.durations.append(duration)

    def metrics(self) -> dict:
        import math
        from collections import Counter

        def entropy(items: list[str]) -> float:
            n = len(items)
            if n == 0:
                return 0.0
            c = Counter(items)
            return -sum((v / n) * math.log2(v / n) for v in c.values())

        def max_entropy(items: list[str]) -> float:
            return math.log2(max(1, len(set(items))))

        def norm(items: list[str]) -> float:
            m = max_entropy(items)
            return round(entropy(items) / m, 3) if m > 0 else 1.0

        dur = self.durations
        dur_std = (sum((d - sum(dur) / len(dur)) ** 2 for d in dur) / len(dur)) ** 0.5 if dur else 0
        # consecutive near-identical assets (duplicate detection via caller)
        return {
            "asset_diversity": norm(self.assets),
            "transition_diversity": norm(self.transitions),
            "motion_diversity": norm(self.motions),
            "shot_duration_mean_s": round(sum(dur) / len(dur), 2) if dur else 0,
            "shot_duration_std_s": round(dur_std, 2),
            "shot_count": len(dur),
        }
