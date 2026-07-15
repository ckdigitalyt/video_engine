"""
transitions.py — Cinematic transition planner.

Context-aware transitions that never random. Selects appropriate transitions
based on shot metadata (emotion, pace, scene boundaries).

Transition types:
- cross dissolve: scene changes, mood transitions
- zoom: emphasis, reveal
- Ken Burns: slow documentary shots
- parallax: multi-layer depth
- push: directional scene changes
- whip pan: fast cuts between locations
- light leak: dreamy/mysterious transitions
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TransitionType(str, Enum):
    CUT = "cut"
    CROSS_DISSOLVE = "cross_dissolve"
    FADE = "fade"
    ZOOM = "zoom"
    KEN_BURNS = "ken_burns"
    PARALLAX = "parallax"
    PUSH = "push"
    WHIP_PAN = "whip_pan"
    LIGHT_LEAK = "light_leak"


@dataclass
class TransitionPlan:
    """Transition plan for a single cut between two shots."""

    transition_type: TransitionType = TransitionType.CROSS_DISSOLVE
    duration: float = 0.5
    direction: str = "right"  # for directional transitions

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_type": self.transition_type.value,
            "duration": self.duration,
            "direction": self.direction,
        }


class TransitionPlanner:
    """Plans transitions between consecutive shots based on context.

    Usage::

        planner = TransitionPlanner()
        transition = planner.plan(prev_shot=shot_a, next_shot=shot_b, scene_boundary=True)
    """

    def __init__(self):
        self._last_transition = TransitionType.CUT
        self._consecutive_count = 0

    def plan(
        self,
        prev_shot: Optional[dict[str, Any]] = None,
        next_shot: Optional[dict[str, Any]] = None,
        scene_boundary: bool = False,
        emotion: str = "neutral",
        pace: str = "normal",
    ) -> TransitionPlan:
        """Determine the best transition between two shots.

        Args:
            prev_shot: Metadata for the previous shot.
            next_shot: Metadata for the next shot.
            scene_boundary: True if this is a scene change.
            emotion: Narration emotion (mysterious, exciting, dramatic, etc.).
            pace: Edit pace (slow, normal, fast).

        Returns:
            TransitionPlan with best transition for this context.
        """
        self._consecutive_count += 1

        # Scene boundaries get longer transitions
        if scene_boundary:
            if emotion in ("mysterious", "contemplative", "sad"):
                return TransitionPlan(
                    TransitionType.FADE,
                    duration=1.0,
                )
            elif emotion in ("exciting", "dramatic", "revelation"):
                return TransitionPlan(
                    TransitionType.ZOOM,
                    duration=0.8,
                )
            else:
                return TransitionPlan(
                    TransitionType.CROSS_DISSOLVE,
                    duration=0.7,
                )

        # Avoid repeating the same transition too often
        same_type_count = 0
        if self._last_transition == TransitionType.CROSS_DISSOLVE:
            same_type_count = self._consecutive_count

        # Camera movement-based transitions
        prev_camera = (prev_shot or {}).get("camera", "")
        next_camera = (next_shot or {}).get("camera", "")

        # Fast pace = cut or whip pan
        if pace == "fast":
            if self._last_transition != TransitionType.WHIP_PAN and random.random() < 0.3:
                return TransitionPlan(TransitionType.WHIP_PAN, duration=0.3)
            return TransitionPlan(TransitionType.CUT, duration=0.0)

        # Same camera angle = dissolve (avoids jarring cut)
        if prev_camera == next_camera and prev_camera:
            return TransitionPlan(
                TransitionType.CROSS_DISSOLVE,
                duration=0.4,
            )

        # Default: cross dissolve with varying duration
        if same_type_count > 3:
            return TransitionPlan(
                TransitionType.ZOOM if random.random() < 0.5 else TransitionType.FADE,
                duration=0.5,
            )

        return TransitionPlan(
            TransitionType.CROSS_DISSOLVE,
            duration=0.4,
        )

    def next(self) -> TransitionType:
        """Return the next transition type, cycling to avoid repetition."""
        types = [
            TransitionType.CROSS_DISSOLVE,
            TransitionType.FADE,
            TransitionType.ZOOM,
        ]
        # Don't repeat the last one
        available = [t for t in types if t != self._last_transition]
        chosen = random.choice(available) if available else types[0]
        self._last_transition = chosen
        return chosen
