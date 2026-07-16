"""
motion_grammar.py — Motion Grammar Engine for predictable, cinematic
shot sequences across scenes.

Enforces motion direction consistency so adjacent shots don't cause
visual flicker.  Each scene gets an archetypal motion pattern (3-4 shots
with a predictable direction: zoom-in → pan → static → push-in).

The grammar prevents incompatible adjacent motions (e.g. zoom_in followed
immediately by zoom_out) and downgrades violating shots to static.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class MotionDirection(Enum):
    """Describes the direction of motion on screen."""
    INWARD = "inward"        # zoom_in, ken_burns_in, push_in, truck_in
    OUTWARD = "outward"      # zoom_out, ken_burns_out, push_out, truck_out
    LATERAL = "lateral"      # pan_left, pan_right, follow, drift
    VERTICAL = "vertical"    # tilt_up, tilt_down
    STATIC = "static"        # none, stabilized
    COMPLEX = "complex"      # parallax (multi-directional)


# ── Motion direction mapping ───────────────────────────────────────────

_MOTION_DIRECTION: dict[str, MotionDirection] = {
    "none": MotionDirection.STATIC,
    "ken_burns_in": MotionDirection.INWARD,
    "ken_burns_out": MotionDirection.OUTWARD,
    "parallax": MotionDirection.COMPLEX,
    "push_in": MotionDirection.INWARD,
    "push_out": MotionDirection.OUTWARD,
    "pan_left": MotionDirection.LATERAL,
    "pan_right": MotionDirection.LATERAL,
    "tilt_up": MotionDirection.VERTICAL,
    "tilt_down": MotionDirection.VERTICAL,
    "zoom_in": MotionDirection.INWARD,
    "zoom_out": MotionDirection.OUTWARD,
    "follow": MotionDirection.LATERAL,
    "drift": MotionDirection.LATERAL,
    "stabilized": MotionDirection.STATIC,
    "static": MotionDirection.STATIC,
}


def get_motion_direction(motion_name: str) -> MotionDirection:
    """Map a motion type name to its directional category."""
    return _MOTION_DIRECTION.get(motion_name, MotionDirection.STATIC)


# ── Archetypal sequences ───────────────────────────────────────────────

ARCHETYPAL_SEQUENCES: list[dict[str, Any]] = [
    {
        "name": "classic_reveal",
        "description": "Begin wide, pan to reveal context, land on static, push in for emphasis",
        "shots": [
            {"motion": "ken_burns_in",   "camera": "wide",    "purpose": "Subject entry"},
            {"motion": "pan_left",       "camera": "medium",  "purpose": "Context expansion"},
            {"motion": "none",           "camera": "static",  "purpose": "Anchor / landing"},
            {"motion": "push_in",        "camera": "closeup", "purpose": "Detail emphasis"},
        ],
    },
    {
        "name": "sweep_and_land",
        "description": "Sweeping lateral motion, then tilt up and stabilise",
        "shots": [
            {"motion": "pan_right",      "camera": "wide",    "purpose": "Establish scope"},
            {"motion": "follow",         "camera": "tracking","purpose": "Guide attention"},
            {"motion": "tilt_up",        "camera": "low_angle","purpose": "Reveal scale"},
            {"motion": "none",           "camera": "static",  "purpose": "Let idea land"},
        ],
    },
    {
        "name": "contemplative_study",
        "description": "Slow inward study ending on reflective static",
        "shots": [
            {"motion": "zoom_in",        "camera": "medium",  "purpose": "Initial focus"},
            {"motion": "drift",          "camera": "medium",  "purpose": "Contemplative roam"},
            {"motion": "push_in",        "camera": "closeup", "purpose": "Narrow focus"},
            {"motion": "none",           "camera": "static",  "purpose": "Reflection"},
        ],
    },
    {
        "name": "dynamic_action",
        "description": "Fast energetic sequence for action-oriented content",
        "shots": [
            {"motion": "parallax",       "camera": "wide",    "purpose": "Dynamic entry"},
            {"motion": "pan_left",       "camera": "tracking","purpose": "Motion follow"},
            {"motion": "zoom_in",        "camera": "closeup", "purpose": "Impact moment"},
            {"motion": "none",           "camera": "static",  "purpose": "Pause / reset"},
        ],
    },
    {
        "name": "slow_reveal",
        "description": "Gentle inward journey culminating in wide static",
        "shots": [
            {"motion": "ken_burns_in",   "camera": "closeup", "purpose": "Detail entry"},
            {"motion": "tilt_up",        "camera": "medium",  "purpose": "Reveal upward"},
            {"motion": "pan_right",      "camera": "wide",    "purpose": "Widen context"},
            {"motion": "none",           "camera": "wide",    "purpose": "Full reveal"},
        ],
    },
]


def select_archetype(scene_index: int, emotion: str = "neutral") -> dict[str, Any]:
    """Select an archetypal motion sequence based on scene index and emotion.

    Cycles through archetypes deterministically, but allows emotional
    overrides for specific tones.
    """
    # Emotion-based override
    emotion_override = {
        "wonder": "classic_reveal",
        "tension": "dynamic_action",
        "dramatic": "dynamic_action",
        "contemplative": "contemplative_study",
        "solemn": "contemplative_study",
        "mysterious": "slow_reveal",
        "urgent": "dynamic_action",
        "hopeful": "sweep_and_land",
        "triumphant": "sweep_and_land",
        "nostalgic": "slow_reveal",
    }

    preferred = emotion_override.get(emotion.lower())
    if preferred:
        for seq in ARCHETYPAL_SEQUENCES:
            if seq["name"] == preferred:
                return seq

    # Deterministic round-robin by scene index
    idx = scene_index % len(ARCHETYPAL_SEQUENCES)
    return ARCHETYPAL_SEQUENCES[idx]


def validate_motion_sequence(prev_motion: str, proposed_motion: str) -> bool:
    """Check if *proposed_motion* is compatible after *prev_motion*.

    Rules:
      1. INWARD → INWARD is OK (sustained zoom/push)
      2. INWARD → OUTWARD is FORBIDDEN (zoom_in → zoom_out flickers)
      3. OUTWARD → INWARD is FORBIDDEN (zoom_out → zoom_in flickers)
      4. LATERAL → LATERAL is OK (pan the same direction)
      5. LATERAL → INWARD is OK
      6. INWARD → LATERAL is OK
      7. Any → STATIC is OK (always safe to land on static)
      8. STATIC → Any is OK
      9. COMPLEX → Any is OK (parallax is multi-directional, resets)

    Returns True if valid, False if incompatible.
    """
    prev_dir = get_motion_direction(prev_motion)
    prop_dir = get_motion_direction(proposed_motion)

    # STATIC is always safe
    if prev_dir == MotionDirection.STATIC or prop_dir == MotionDirection.STATIC:
        return True

    # COMPLEX (parallax) resets the direction chain
    if prev_dir == MotionDirection.COMPLEX:
        return True

    # Prevent directional reversal
    if (prev_dir == MotionDirection.INWARD and prop_dir == MotionDirection.OUTWARD):
        return False
    if (prev_dir == MotionDirection.OUTWARD and prop_dir == MotionDirection.INWARD):
        return False

    # LATERAL → LATERAL is fine, LATERAL → INWARD/OUTWARD needs check
    if prev_dir == MotionDirection.LATERAL and prop_dir in (
        MotionDirection.LATERAL,
        MotionDirection.INWARD,
        MotionDirection.VERTICAL,
    ):
        return True

    # INWARD → VERTICAL is OK
    if prev_dir == MotionDirection.INWARD and prop_dir == MotionDirection.VERTICAL:
        return True

    return True


def get_safe_motion_fallback(prev_motion: str, proposed_motion: str) -> str:
    """Return the motion to use: *proposed_motion* if valid, else 'none' (static).

    This is the primary entry-point for beat planners to check motion
    consistency before assigning a motion to a shot.
    """
    if validate_motion_sequence(prev_motion, proposed_motion):
        return proposed_motion
    return "none"


def apply_archetype_to_sequence(
    shots: list[Any],
    scene_index: int,
    emotion: str = "neutral",
) -> list[Any]:
    """Apply an archetypal motion pattern to a list of shot objects.

    Each shot must have a ``motion`` attribute (string) that will be
    set/overridden.  Additional shots beyond the archetype length use
    the last archetype motion repeated.

    Args:
        shots: List of shot objects with a ``motion`` attribute.
        scene_index: Scene index for deterministic archetype selection.
        emotion: Emotional tone for archetype selection.

    Returns:
        The modified shots list (in-place).
    """
    archetype = select_archetype(scene_index, emotion)
    pattern = archetype["shots"]

    prev_motion = "none"
    # Resolve Motion enum type from the shot objects
    from src.cinematic.beat_planner import Motion as MotionEnum
    str_to_enum = {m.value: m for m in MotionEnum}

    for i, shot in enumerate(shots):
        if i < len(pattern):
            raw_motion = pattern[i]["motion"]
        else:
            # Repeat last motion for extra shots
            raw_motion = pattern[-1]["motion"]

        # Enforce motion grammar compatibility
        assigned_motion_str = get_safe_motion_fallback(prev_motion, raw_motion)
        # Convert to Motion Enum (shots expect Motion, not string)
        shot.motion = str_to_enum.get(assigned_motion_str, MotionEnum.NONE)
        prev_motion = assigned_motion_str

    return shots
