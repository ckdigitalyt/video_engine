"""
pace_profiler.py — Adaptive shot duration based on voiceover narration analysis.

Analyzes narration text for sentence boundaries, clause structure, and
natural pause points.  Sets shot durations to match breath units (3.5s-6.0s
range) so cuts land on narrative rhythm rather than arbitrary intervals.

Overrides min/max shot durations in the BeatPlanner based on narrative
structure (e.g. expository gets longer shots, action gets shorter ones).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


class PaceProfile:
    """Pacing analysis result for one narration block."""

    def __init__(
        self,
        sentence_count: int,
        avg_sentence_duration: float,
        breath_points: List[float],
        recommended_min: float,
        recommended_max: float,
        recommended_avg: float,
        energy_level: float,  # 0.0 (slow/meditative) to 1.0 (fast/urgent)
        narrative_arc_position: str,  # "start", "middle", "climax", "end"
    ):
        self.sentence_count = sentence_count
        self.avg_sentence_duration = avg_sentence_duration
        self.breath_points = breath_points
        self.recommended_min = recommended_min
        self.recommended_max = recommended_max
        self.recommended_avg = recommended_avg
        self.energy_level = energy_level
        self.narrative_arc_position = narrative_arc_position

    def __repr__(self) -> str:
        return (
            f"PaceProfile(avg_dur={self.avg_sentence_duration:.2f}s, "
            f"energy={self.energy_level:.1f}, "
            f"min={self.recommended_min:.1f}s, max={self.recommended_max:.1f}s, "
            f"avg={self.recommended_avg:.1f}s, "
            f"breath_pts={len(self.breath_points)})"
        )


# ── Configurable durations ─────────────────────────────────────────────

# Default ranges per narrative role
_ROLE_RANGES = {
    "hook":        {"min": 4.0, "max": 5.5, "avg": 4.5, "energy": 0.4},
    "context":     {"min": 4.5, "max": 6.0, "avg": 5.0, "energy": 0.3},
    "exploration": {"min": 3.5, "max": 5.5, "avg": 4.5, "energy": 0.5},
    "climax":      {"min": 2.5, "max": 4.0, "avg": 3.5, "energy": 0.8},
    "conclusion":  {"min": 4.0, "max": 6.0, "avg": 5.0, "energy": 0.3},
}

# Default fallback
_DEFAULT_RANGE = {"min": 3.5, "max": 5.5, "avg": 4.5, "energy": 0.5}

# Words-per-second for spoken English narration (typical documentary pacing)
_WORDS_PER_SECOND = 2.5  # ~150 WPM = comfortable documentary pace


def analyze_vo_narration(
    text: str,
    narrative_role: str = "exploration",
) -> PaceProfile:
    """Analyze narration text and produce a pace profile.

    Args:
        text: Spoken narration text.
        narrative_role: Role in the narrative arc (hook/context/exploration/
            climax/conclusion).

    Returns:
        PaceProfile with recommended shot duration ranges.
    """
    if not text or not text.strip():
        return PaceProfile(
            sentence_count=0,
            avg_sentence_duration=4.5,
            breath_points=[],
            recommended_min=3.5,
            recommended_max=5.5,
            recommended_avg=4.5,
            energy_level=0.5,
            narrative_arc_position=narrative_role,
        )

    # Step 1: Split into sentences
    sentence_delimiters = r'(?<=[.!?])\s+'
    sentences = [s.strip() for s in re.split(sentence_delimiters, text) if s.strip()]

    # Step 2: Calculate per-sentence spoken durations
    sentence_durations = []
    for sent in sentences:
        word_count = len(sent.split())
        dur = word_count / _WORDS_PER_SECOND
        sentence_durations.append(max(1.0, dur))

    # Step 3: Find breath points — boundaries between sentences where
    # a natural pause occurs (period, question mark, exclamation)
    breath_points = []
    cumulative = 0.0
    for i, dur in enumerate(sentence_durations):
        cumulative += dur
        if i < len(sentence_durations) - 1:
            breath_points.append(cumulative)
            # Add ~0.3s for the breath/pause between sentences
            cumulative += 0.3

    # Step 4: Analyse text for energy/urgency indicators
    energy = _estimate_energy_level(text)

    # Step 5: Get role-based range
    role_range = _ROLE_RANGES.get(narrative_role.lower(), _DEFAULT_RANGE)

    # Blend energy with role-based default
    energy = (energy + role_range["energy"]) / 2.0

    # Step 6: Calculate recommended durations
    # For voiceover-heavy content: match sentence lengths
    if sentence_durations:
        avg_sentence_dur = sum(sentence_durations) / len(sentence_durations)
    else:
        avg_sentence_dur = 4.5

    # Clamp avg_sentence_dur to reasonable range
    avg_sentence_dur = max(3.0, min(6.0, avg_sentence_dur))

    # More energetic -> shorter shots
    recommended_min = max(2.5, role_range["min"] - energy * 1.0)
    recommended_max = min(7.0, role_range["max"] + (1.0 - energy) * 1.0)
    recommended_avg = max(recommended_min, min(recommended_max, avg_sentence_dur))

    return PaceProfile(
        sentence_count=len(sentences),
        avg_sentence_duration=round(avg_sentence_dur, 2),
        breath_points=[round(bp, 2) for bp in breath_points],
        recommended_min=round(recommended_min, 1),
        recommended_max=round(recommended_max, 1),
        recommended_avg=round(recommended_avg, 1),
        energy_level=round(energy, 2),
        narrative_arc_position=narrative_role,
    )


def get_shot_duration_from_pace(
    profile: PaceProfile,
    shot_index: int,
    total_shots: int,
) -> float:
    """Return a shot duration in seconds that matches the narrative breath units.

    Distributes breath points across shots proportionally.  Shots at breath
    points get a brief pause (slightly longer).  Uses the profile's recommended
    range to clamp.

    Args:
        profile: PaceProfile from analyze_vo_narration().
        shot_index: 0-based shot index in the scene.
        total_shots: Total number of shots in the scene.

    Returns:
        Duration in seconds for this shot.
    """
    if profile.sentence_count <= 1 or profile.avg_sentence_duration <= 0:
        return profile.recommended_avg

    # Try to align shots with breath points
    if profile.breath_points and total_shots > 1:
        # Find the nearest breath point for this shot index
        progress = shot_index / max(total_shots - 1, 1)
        target_breath_idx = int(progress * len(profile.breath_points))
        target_breath_idx = min(target_breath_idx, len(profile.breath_points) - 1)

        # Duration until this breath point from the previous one (or start)
        if target_breath_idx == 0:
            dur = profile.breath_points[0]
        else:
            # Account for previous breath point
            prev_bp = profile.breath_points[target_breath_idx - 1]
            dur = profile.breath_points[target_breath_idx] - prev_bp

        # Clamp within recommended range
        return max(profile.recommended_min, min(profile.recommended_max, dur))

    # Fallback: evenly distribute using the average
    return profile.recommended_avg


def estimate_shot_count_from_pace(profile: PaceProfile, scene_duration: float) -> int:
    """Estimate the ideal number of shots for a scene given its pace profile.

    Aligns shots with breath points when possible.
    """
    if profile.breath_points:
        # One shot per breath unit
        count = len(profile.breath_points) + 1  # +1 for last segment after final breath
        # Ensure reasonable range
        return max(2, min(count, int(scene_duration / profile.recommended_min)))
    return max(1, int(scene_duration / profile.recommended_avg))


def _estimate_energy_level(text: str) -> float:
    """Estimate narrative energy from text content.

    0.0 = slow/meditative, 1.0 = fast/urgent.
    """
    lower = text.lower()

    # Urgent indicators
    urgent_count = sum(lower.count(w) for w in [
        "suddenly", "immediately", "urgent", "critical", "danger",
        "explosion", "crisis", "emergency", "rapid", "fast", "quick",
    ])

    # Slow/contemplative indicators
    slow_count = sum(lower.count(w) for w in [
        "imagine", "consider", "think", "slowly", "gradual",
        "ancient", "billions", "millions", "vast", "deep",
        "peaceful", "calm", "gentle", "contemplative",
    ])

    # Exclamation/question density
    excl_count = text.count("!") + text.count("?")
    total_words = len(lower.split()) or 1

    # Exclamation density factor
    excl_factor = min(excl_count / max(total_words * 0.1, 1), 1.0)

    # Word-level urgency
    urgency = min(urgent_count * 0.2, 1.0)
    slowness = min(slow_count * 0.15, 1.0)

    # Sentence length: short sentences = more energy
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    avg_words_per_sentence = total_words / max(len(sentences), 1)
    # Short sentences (~5 words) = high energy, long sentences (~20+ words) = low energy
    sentence_energy = 1.0 - min(avg_words_per_sentence / 20.0, 1.0)

    energy = max(0.0, urgency * 0.3 + excl_factor * 0.3 + sentence_energy * 0.4 - slowness * 0.3)
    return min(1.0, energy)
