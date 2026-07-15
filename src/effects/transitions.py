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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.utils.config import get_config


TRANSITION_TYPES = ("cut", "fade", "crossfade", "dip_to_black", "dissolve", "zoom")


class TransitionEngine:
    """Selects transitions between adjacent video clips.

    Supports both random and context-aware (smart) transition selection.
    Smart transitions use topic category, provider, and visual context to
    choose appropriate transition types.

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
    smart_enabled : bool, optional
        Whether to use context-aware smart transitions.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        default_transition: Optional[str] = None,
        duration: Optional[float] = None,
        seed: Optional[int] = None,
        smart_enabled: Optional[bool] = None,
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
        self._smart_enabled = smart_enabled if smart_enabled is not None else get_config(
            "smart_transitions.enabled", True
        )
        self._same_topic_default = get_config("smart_transitions.same_topic_default", "cut")
        self._same_provider_default = get_config("smart_transitions.same_provider_default", "dissolve")
        self._new_idea_default = get_config("smart_transitions.new_idea_default", "fade")

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
            if self._smart_enabled:
                t_type = self._pick_smart(None, None, i)
            else:
                # Legacy random selection
                gap_rng = random.Random(self._seed + i * 73)
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

    def generate_smart(
        self,
        clip_count: int,
        scene_contexts: Optional[list[dict]] = None,
    ) -> list[dict[str, Any]]:
        """Generate transitions with context-aware selection.

        *scene_contexts* is a list of dicts, one per scene, with keys:
        - ``category`` (str): topic category
        - ``provider`` (str): provider that supplied the asset
        - ``query`` (str): search query used
        - ``asset_id`` (str|int): unique asset identifier

        Returns same format as ``generate()``.
        """
        if not self._enabled or clip_count <= 1:
            return self._all_cut(clip_count)

        descriptors: list[dict[str, Any]] = [{
            "type": "cut", "duration": 0.0, "index": 0,
        }]

        for i in range(1, clip_count):
            prev_ctx = scene_contexts[i - 1] if scene_contexts and i - 1 < len(scene_contexts) else {}
            curr_ctx = scene_contexts[i] if scene_contexts and i < len(scene_contexts) else {}

            t_type = self._pick_smart(prev_ctx, curr_ctx, i)
            descriptors.append({
                "type": t_type,
                "duration": 0.0 if t_type == "cut" else self._duration,
                "index": i,
            })

        return descriptors

    def _pick_smart(
        self,
        prev_context: Optional[dict],
        curr_context: Optional[dict],
        index: int,
    ) -> str:
        """Pick a transition based on scene context.

        Rules:
        - Same topic + same category -> "cut"
        - Same provider, different query -> "dissolve"
        - Different category / new idea -> "fade"
        - Same asset id reused -> "dissolve"
        """
        if not self._smart_enabled:
            rng = random.Random(self._seed + index * 73)
            if rng.random() < 0.7 and self._duration > 0:
                return rng.choice([t for t in TRANSITION_TYPES if t != "cut"])
            return "cut"

        if not prev_context or not curr_context:
            return self._default

        prev_cat = prev_context.get("category", "")
        curr_cat = curr_context.get("category", "")
        prev_prov = prev_context.get("provider", "")
        curr_prov = curr_context.get("provider", "")
        prev_query = prev_context.get("query", "")
        curr_query = curr_context.get("query", "")
        prev_asset = prev_context.get("asset_id", "")
        curr_asset = curr_context.get("asset_id", "")

        # Same asset reused -> dissolve
        if prev_asset and curr_asset and str(prev_asset) == str(curr_asset):
            return "dissolve"

        # Same category, different idea -> cut (fast pacing)
        if prev_cat and curr_cat and prev_cat == curr_cat:
            return self._same_topic_default

        # Same provider, different query -> dissolve
        if prev_prov and curr_prov and prev_prov == curr_prov:
            return self._same_provider_default

        # Different category -> new idea
        if prev_cat and curr_cat and prev_cat != curr_cat:
            return self._new_idea_default

        return self._default

    def _all_cut(self, clip_count: int) -> list[dict[str, Any]]:
        return [
            {"type": "cut", "duration": 0.0, "index": i}
            for i in range(clip_count)
        ]


# ══════════════════════════════════════════════════════════════════════
# TransitionPlanner — context-aware transition selection
# ══════════════════════════════════════════════════════════════════════

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
    transition_type: TransitionType = TransitionType.CROSS_DISSOLVE
    duration: float = 0.5
    direction: str = "right"

    def to_dict(self) -> dict:
        return {
            "transition_type": self.transition_type.value,
            "duration": self.duration,
            "direction": self.direction,
        }


class TransitionPlanner:
    def __init__(self):
        self._last_transition = TransitionType.CUT
        self._consecutive_count = 0

    def plan(
        self,
        prev_shot: Optional[dict] = None,
        next_shot: Optional[dict] = None,
        scene_boundary: bool = False,
        emotion: str = "neutral",
        pace: str = "normal",
    ) -> TransitionPlan:
        self._consecutive_count += 1
        if scene_boundary:
            if emotion in ("mysterious", "contemplative", "sad"):
                return TransitionPlan(TransitionType.FADE, duration=1.0)
            elif emotion in ("exciting", "dramatic", "revelation"):
                return TransitionPlan(TransitionType.ZOOM, duration=0.8)
            else:
                return TransitionPlan(TransitionType.CROSS_DISSOLVE, duration=0.7)
        if pace == "fast":
            if self._last_transition != TransitionType.WHIP_PAN and self._consecutive_count % 3 == 0:
                return TransitionPlan(TransitionType.WHIP_PAN, duration=0.3)
            return TransitionPlan(TransitionType.CUT, duration=0.0)
        if self._consecutive_count > 3 and self._last_transition == TransitionType.CROSS_DISSOLVE:
            return TransitionPlan(TransitionType.ZOOM, duration=0.5)
        return TransitionPlan(TransitionType.CROSS_DISSOLVE, duration=0.4)

    def next(self) -> TransitionType:
        types = [TransitionType.CROSS_DISSOLVE, TransitionType.FADE, TransitionType.ZOOM]
        available = [t for t in types if t != self._last_transition]
        chosen = random.choice(available) if available else types[0]
        self._last_transition = chosen
        return chosen
