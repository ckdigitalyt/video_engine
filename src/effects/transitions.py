"""
transitions.py — Configurable scene transition engine.

Generates transition descriptors between adjacent video clips.
Transitions are renderer-agnostic plain dicts.

Transition types:
- cut           : instant switch (no effect)
- fade          : fade to black, then fade in
- crossfade     : cross dissolve from one clip to the next
- dip_to_black  : dip through black
- dissolve      : dissolve through overlapping opacity
- zoom          : zoom-in transition
"""

from __future__ import annotations

import random
from typing import Any, Optional

from src.utils.config import get_config


TRANSITION_TYPES = ("cut", "fade", "crossfade", "dip_to_black", "dissolve", "zoom")


class TransitionEngine:
    """Selects transitions between adjacent video clips.

    Parameters
    ----------
    enabled : bool, optional
        Override for ``effects.transitions.enabled``.  Default True.
    default_transition : str, optional
        Fallback transition type.  Default ``"crossfade"``.
    duration : float, optional
        Transition duration in seconds.  Default 0.5.
    seed : int, optional
        Random seed for deterministic selection.  Default 42.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        default_transition: Optional[str] = None,
        duration: Optional[float] = None,
        seed: Optional[int] = None,
    ):
        self._enabled = enabled if enabled is not None else get_config(
            "effects.transitions.enabled", True
        )
        self._default = default_transition if default_transition is not None else get_config(
            "effects.transitions.default_transition", "crossfade"
        )
        self._duration = duration if duration is not None else get_config(
            "effects.transitions.transition_duration", 0.5
        )
        self._seed = seed if seed is not None else get_config(
            "effects.random_seed", 42
        )

    def generate(self, clip_count: int) -> list[dict[str, Any]]:
        """Produce one transition descriptor per gap between clips.

        Returns ``clip_count`` entries.  The first entry is always a
        ``cut`` (nothing before clip 0).  Each subsequent entry describes
        how to transition from clip i-1 to clip i.

        Each dict:

        - ``type`` : str — transition type
        - ``duration`` : float — transition duration in seconds
        - ``index`` : int — applies between clip (index-1) and clip (index)
        """
        if not self._enabled or clip_count <= 1:
            return self._all_cut(clip_count)

        rng = random.Random(self._seed)
        descriptors: list[dict[str, Any]] = []

        # First entry (nothing before clip 0)
        descriptors.append({
            "type": "cut",
            "duration": 0.0,
            "index": 0,
        })

        for i in range(1, clip_count):
            # Deterministic: vary seed per gap
            gap_rng = random.Random(self._seed + i * 73)

            # 70% chance of non-cut transition (if duration > 0)
            if gap_rng.random() < 0.7 and self._duration > 0:
                t_type = gap_rng.choice(
                    [t for t in TRANSITION_TYPES if t != "cut"]
                )
            else:
                t_type = "cut"

            descriptors.append({
                "type": t_type,
                "duration": 0.0 if t_type == "cut" else self._duration,
                "index": i,
            })

        return descriptors

    def _all_cut(self, clip_count: int) -> list[dict[str, Any]]:
        return [
            {"type": "cut", "duration": 0.0, "index": i}
            for i in range(clip_count)
        ]
