"""
motion.py — Deterministic Ken Burns camera motion engine.

Generates per-clip motion effect descriptors that any renderer can apply.
Motion types:
- zoom_in      : slow zoom into the centre (1.0 → 1.0 + strength)
- zoom_out     : slow zoom out (1.0 + strength → 1.0)
- pan_left     : static zoom + horizontal pan right-to-left
- pan_right    : static zoom + horizontal pan left-to-right
- pan_up       : static zoom + vertical pan bottom-to-top
- pan_down     : static zoom + vertical pan top-to-bottom
- none         : no motion (static clip)
"""

from __future__ import annotations

import random
from typing import Any, Optional

from src.utils.config import get_config


MOTION_TYPES = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "none")


class MotionEngine:
    """Generates deterministic Ken Burns motion descriptors for video clips.

    Parameters
    ----------
    enabled : bool, optional
        Override for ``effects.motion.enabled``.  Default True.
    strength : float, optional
        How much zoom/pan to apply (0–1).  Default 0.08.
    probability : float, optional
        Chance that any given clip gets motion (0–1).  Default 0.85.
    seed : int, optional
        Random seed for deterministic output.  Default 42.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        strength: Optional[float] = None,
        probability: Optional[float] = None,
        seed: Optional[int] = None,
    ):
        self._enabled = enabled if enabled is not None else get_config(
            "effects.motion.enabled", True
        )
        self._strength = strength if strength is not None else get_config(
            "effects.motion.strength", 0.08
        )
        self._probability = probability if probability is not None else get_config(
            "effects.motion.probability", 0.85
        )
        self._seed = seed if seed is not None else get_config(
            "effects.random_seed", 42
        )

    def generate(self, clip_count: int) -> list[dict[str, Any]]:
        """Produce one motion descriptor per clip.

        Returns a list of dicts with keys:

        - ``type`` : str — one of MOTION_TYPES
        - ``zoom_start`` : float — scale at the beginning of the clip
        - ``zoom_end`` : float — scale at the end of the clip
        - ``pan_x`` : float — horizontal pan offset in pixels (0 = none)
        - ``pan_y`` : float — vertical pan offset in pixels (0 = none)
        """
        if not self._enabled or clip_count == 0:
            return [{"type": "none", "zoom_start": 1.0, "zoom_end": 1.0,
                     "pan_x": 0, "pan_y": 0} for _ in range(clip_count)]

        rng = random.Random(self._seed)
        descriptors: list[dict[str, Any]] = []

        for i in range(clip_count):
            # Deterministic: vary seed per clip
            clip_rng = random.Random(self._seed + i * 137)

            if clip_rng.random() >= self._probability:
                descriptors.append({
                    "type": "none",
                    "zoom_start": 1.0,
                    "zoom_end": 1.0,
                    "pan_x": 0,
                    "pan_y": 0,
                })
                continue

            # Exclude "none" from random motion selection
            active_types = [t for t in MOTION_TYPES if t != "none"]
            motion_type = clip_rng.choice(active_types)

            if motion_type == "zoom_in":
                zoom_end = 1.0 + self._strength
                descriptors.append({
                    "type": "zoom_in",
                    "zoom_start": 1.0,
                    "zoom_end": round(zoom_end, 4),
                    "pan_x": 0,
                    "pan_y": 0,
                })
            elif motion_type == "zoom_out":
                zoom_start = 1.0 + self._strength
                descriptors.append({
                    "type": "zoom_out",
                    "zoom_start": round(zoom_start, 4),
                    "zoom_end": 1.0,
                    "pan_x": 0,
                    "pan_y": 0,
                })
            elif motion_type == "pan_left":
                pan = int(100 * self._strength)
                descriptors.append({
                    "type": "pan_left",
                    "zoom_start": round(1.0 + self._strength * 0.3, 4),
                    "zoom_end": round(1.0 + self._strength * 0.3, 4),
                    "pan_x": pan,
                    "pan_y": 0,
                })
            elif motion_type == "pan_right":
                pan = int(100 * self._strength)
                descriptors.append({
                    "type": "pan_right",
                    "zoom_start": round(1.0 + self._strength * 0.3, 4),
                    "zoom_end": round(1.0 + self._strength * 0.3, 4),
                    "pan_x": -pan,
                    "pan_y": 0,
                })
            elif motion_type == "pan_up":
                pan = int(100 * self._strength)
                descriptors.append({
                    "type": "pan_up",
                    "zoom_start": round(1.0 + self._strength * 0.3, 4),
                    "zoom_end": round(1.0 + self._strength * 0.3, 4),
                    "pan_x": 0,
                    "pan_y": pan,
                })
            elif motion_type == "pan_down":
                pan = int(100 * self._strength)
                descriptors.append({
                    "type": "pan_down",
                    "zoom_start": round(1.0 + self._strength * 0.3, 4),
                    "zoom_end": round(1.0 + self._strength * 0.3, 4),
                    "pan_x": 0,
                    "pan_y": -pan,
                })
            else:
                descriptors.append({
                    "type": "none",
                    "zoom_start": 1.0,
                    "zoom_end": 1.0,
                    "pan_x": 0,
                    "pan_y": 0,
                })

        return descriptors
