#!/usr/bin/env python3
"""
BeatPlanner — splits narration into semantic beats with visual intent.
Uses Pydantic models from src.models.schemas for output.
"""

from typing import List, Optional, Union, Dict
from enum import Enum
import re

from src.models.schemas import (
    BeatPlan, ShotPlan, ShotType, CameraMotion, TransitionType, AssetPlan
)
from src.director.motion_grammar import (
    apply_archetype_to_sequence,
    get_safe_motion_fallback,
    select_archetype,
)
from src.cinematic.pace_profiler import analyze_vo_narration, estimate_shot_count_from_pace


class Emotion(str, Enum):
    """Emotional tone for beats and shots."""
    NEUTRAL = "neutral"
    WONDER = "wonder"
    TENSION = "tension"
    DRAMATIC = "dramatic"
    SOLEMN = "solemn"
    ENERGETIC = "energetic"
    MYSTERIOUS = "mysterious"
    NOSTALGIC = "nostalgic"
    CONTEMPLATIVE = "contemplative"
    URGENT = "urgent"
    TRIUMPHANT = "triumphant"
    HOPEFUL = "hopeful"


class CameraStyle(str, Enum):
    """Camera framing styles — maps to beats for planning, then to CameraMotion."""
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSEUP = "closeup"
    EXTREME_CLOSEUP = "extreme_closeup"
    AERIAL = "aerial"
    POV = "pov"
    LOW_ANGLE = "low_angle"
    HIGH_ANGLE = "high_angle"
    DUTCH = "dutch"
    TRACKING = "tracking"
    STATIC = "static"


class Transition(str, Enum):
    """Transition types — maps to TransitionType for the Pydantic model."""
    CUT = "cut"
    CROSS_DISSOLVE = "cross_dissolve"
    DIP_TO_BLACK = "dip_to_black"
    DIP_TO_WHITE = "dip_to_white"
    L_CUT = "l_cut"
    J_CUT = "j_cut"
    MATCH_CUT = "match_cut"
    CAMERA_MOTION = "camera_motion"
    WIPE = "wipe"
    FADE = "fade"


class AssetType(str, Enum):
    VIDEO = "video"
    IMAGE_KEN_BURNS = "image_ken_burns"
    GENERATED = "generated"
    MOTION_GRAPHICS = "motion_graphics"
    ANIMATED = "animated"
    TEXT_OVERLAY = "text_overlay"


class Motion(str, Enum):
    NONE = "none"
    KEN_BURNS_IN = "ken_burns_in"
    KEN_BURNS_OUT = "ken_burns_out"
    PARALLAX = "parallax"
    PUSH_IN = "push_in"
    PUSH_OUT = "push_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    FOLLOW = "follow"
    DRIFT = "drift"


# Internal beat dataclass (used during planning, then converted to BeatPlan)
class Beat:
    """Internal beat data during planning — NOT serialized."""
    def __init__(self, index: int, text: str, start_time: float, duration: float,
                 emotion: Emotion = Emotion.NEUTRAL,
                 visual_purpose: str = "",
                 camera_primary: CameraStyle = CameraStyle.MEDIUM,
                 camera_cutaway: CameraStyle = CameraStyle.WIDE,
                 transition_in: Transition = Transition.CROSS_DISSOLVE,
                 transition_out: Transition = Transition.CROSS_DISSOLVE,
                 motion_graphics_note: str = ""):
        self.index = index
        self.text = text
        self.start_time = start_time
        self.duration = duration
        self.emotion = emotion
        self.visual_purpose = visual_purpose
        self.camera_primary = camera_primary
        self.camera_cutaway = camera_cutaway
        self.transition_in = transition_in
        self.transition_out = transition_out
        self.shots: List["Shot"] = []
        self.motion_graphics_note = motion_graphics_note

    def total_shot_duration(self) -> float:
        return sum(s.duration for s in self.shots)


class Shot:
    """Internal shot data during planning — NOT serialized."""
    def __init__(self, timestamp: float = 0.0, duration: float = 0.0,
                 shot_type: "ShotType" = None,
                 camera: CameraStyle = CameraStyle.MEDIUM,
                 motion: Motion = Motion.NONE,
                 asset_type: AssetType = AssetType.VIDEO,
                 transition: Transition = Transition.CUT,
                 emotion: Emotion = Emotion.NEUTRAL,
                 visual_purpose: str = "", description: str = "",
                 search_query: str = "", justify_long_shot: str = ""):
        self.timestamp = timestamp
        self.duration = duration
        self.shot_type = shot_type or ShotType.PRIMARY
        self.camera = camera
        self.motion = motion
        self.asset_type = asset_type
        self.transition = transition
        self.emotion = emotion
        self.visual_purpose = visual_purpose
        self.description = description
        self.search_query = search_query
        self.justify_long_shot = justify_long_shot


# ── Mapper functions ───────────────────────────────────────────────────

def _camera_style_to_motion(style: CameraStyle) -> CameraMotion:
    """Map internal CameraStyle to Pydantic CameraMotion.
    All default to STATIC. Motion is opt-in per shot.
    """
    return CameraMotion.STATIC


def _emotion_to_camera_motion(emotion: Emotion) -> CameraMotion:
    """All emotions default to STATIC. Motion is opt-in."""
    return CameraMotion.STATIC


def _motion_to_camera_motion(m: Motion) -> CameraMotion:
    return CameraMotion.NONE


def _transition_to_transition_type(t: Transition) -> TransitionType:
    mapping = {
        Transition.CUT: TransitionType.CUT_SYNC,
        Transition.CROSS_DISSOLVE: TransitionType.CROSSFADE,
        Transition.DIP_TO_BLACK: TransitionType.FADE,
        Transition.DIP_TO_WHITE: TransitionType.CROSSFADE,
        Transition.L_CUT: TransitionType.CROSSFADE,
        Transition.J_CUT: TransitionType.CROSSFADE,
        Transition.MATCH_CUT: TransitionType.CROSSFADE,
        Transition.CAMERA_MOTION: TransitionType.CROSSFADE,
        Transition.WIPE: TransitionType.WIPE_LEFT,
        Transition.FADE: TransitionType.FADE,
    }
    return mapping.get(t, TransitionType.CROSSFADE)


def _shot_type_to_pydantic_shot_type(st: "ShotType") -> ShotType:
    """Map internal shot type to Pydantic ShotType."""
    if st == ShotType.PRIMARY:
        return ShotType.PRIMARY
    elif st == ShotType.CUTAWAY:
        return ShotType.CUTAWAY
    elif st == ShotType.BACKUP:
        return ShotType.BACKUP
    elif st == ShotType.MOTION_GRAPHICS:
        return ShotType.MOTION_GRAPHICS
    return ShotType.PRIMARY


# Alias
def _internal_beat_to_pydantic(b: Beat) -> BeatPlan:
    """Convert internal Beat to Pydantic BeatPlan."""
    shots_p = []
    for s in b.shots:
        sp = ShotPlan(
            timestamp=round(s.timestamp, 2),
            duration=round(s.duration, 2),
            shot_type=_shot_type_to_pydantic_shot_type(s.shot_type),
            camera=_motion_to_camera_motion(s.motion),
            transition=_transition_to_transition_type(s.transition),
            emotion=s.emotion.value,
            motion=s.motion.value if hasattr(s.motion, 'value') else str(s.motion),
            asset_type=s.asset_type.value,
            description=s.description,
            search_query=s.search_query,
            semantic_score=0.0,
            justify_long_shot=s.justify_long_shot,
        )
        shots_p.append(sp)

    return BeatPlan(
        index=b.index,
        text=b.text,
        start_time=round(b.start_time, 2),
        duration=round(b.duration, 2),
        emotion=b.emotion.value,
        visual_purpose=b.visual_purpose,
        camera_primary=_emotion_to_camera_motion(b.emotion),
        camera_cutaway=_camera_style_to_motion(b.camera_cutaway),
        transition_in=_transition_to_transition_type(b.transition_in),
        transition_out=_transition_to_transition_type(b.transition_out),
        shots=shots_p,
        motion_graphics_note=b.motion_graphics_note,
    )


# ── Sentence splitting ─────────────────────────────────────────────────

def split_into_sentences(text: str) -> List[str]:
    """Split narration into individual sentences."""
    text = re.sub(r'(?<=[.!?])\s+', '\n', text)
    return [s.strip() for s in text.split('\n') if s.strip()]


def split_into_clauses(sentence: str) -> List[str]:
    """Split a long sentence into clauses at commas, conjunctions."""
    if len(sentence) < 80:
        return [sentence]
    clauses = re.split(r'(?:;\s*|,\s*(?:and|but|however|while|although|because)\s*)', sentence)
    return [c.strip() for c in clauses if c.strip()] or [sentence]


# ── Planning classes ────────────────────────────────────────────────────

class BeatPlanner:
    """Plans beats from narration text."""

    def plan_beats(self, narration: str, scene_duration: float,
                    narrative_role: str = "exploration") -> List[Beat]:
        """Split narration into beats with timing based on voiceover pace analysis.

        Uses the PaceProfiler to analyze narration for sentence boundaries
        and natural breath points, then sets shot durations to match
        breath units (3.5s-6.0s range) instead of arbitrary intervals.
        """
        sentences = split_into_sentences(narration)
        if not sentences:
            return []

        clauses = []
        for s in sentences:
            clauses.extend(split_into_clauses(s))
        if not clauses:
            return []

        # Voiceover-aware pacing: analyze narration for breath units
        pace = analyze_vo_narration(narration, narrative_role)
        beat_count = len(clauses)

        # Use recommended average from pace profiler as base duration
        ideal_duration = pace.recommended_avg

        # Use pace profiler min/max
        min_dur = pace.recommended_min
        max_dur = pace.recommended_max

        total_needed = beat_count * ideal_duration
        scale = scene_duration / total_needed if total_needed > 0 else 1.0

        beats = []
        time_cursor = 0.0
        for i, clause in enumerate(clauses):
            raw_duration = ideal_duration * scale
            # Clamp within pace-profiler bounds
            duration = max(min_dur, min(max_dur, raw_duration))
            if i == len(clauses) - 1:
                remaining = scene_duration - time_cursor
                if remaining > 0:
                    duration = min(remaining, 12.0)

            beat = Beat(index=i, text=clause, start_time=time_cursor, duration=duration)
            beats.append(beat)
            time_cursor += duration

        if beats and beats[-1].start_time + beats[-1].duration < scene_duration:
            diff = scene_duration - (beats[-1].start_time + beats[-1].duration)
            new_dur = beats[-1].duration + diff
            beats[-1].duration = min(new_dur, 12.0)

        return beats

    def assign_emotions(self, beats: List[Beat], topic: str = "") -> List[Beat]:
        """Assign emotions based on beat content heuristics."""
        emotion_map = {
            "why": Emotion.WONDER,
            "what if": Emotion.HOPEFUL,
            "imagine": Emotion.WONDER,
            "but": Emotion.TENSION,
            "however": Emotion.TENSION,
            "suddenly": Emotion.URGENT,
            "amazing": Emotion.TRIUMPHANT,
            "incredible": Emotion.TRIUMPHANT,
            "mystery": Emotion.MYSTERIOUS,
            "unknown": Emotion.MYSTERIOUS,
            "dark": Emotion.SOLEMN,
            "tragic": Emotion.SOLEMN,
            "fear": Emotion.DRAMATIC,
            "danger": Emotion.URGENT,
            "hope": Emotion.HOPEFUL,
            "future": Emotion.HOPEFUL,
            "past": Emotion.NOSTALGIC,
            "ancient": Emotion.NOSTALGIC,
            "think": Emotion.CONTEMPLATIVE,
            "consider": Emotion.CONTEMPLATIVE,
            "vast": Emotion.WONDER,
            "billions": Emotion.WONDER,
            "millions": Emotion.WONDER,
        }

        for beat in beats:
            lower = beat.text.lower()
            found = False
            for keyword, emo in emotion_map.items():
                if keyword in lower:
                    beat.emotion = emo
                    found = True
                    break
            if not found:
                if beat.index == 0:
                    beat.emotion = Emotion.WONDER if topic else Emotion.NEUTRAL
                elif beat.index == len(beats) - 1:
                    beat.emotion = Emotion.TRIUMPHANT if topic else Emotion.NEUTRAL
                else:
                    beat.emotion = Emotion.NEUTRAL
        return beats

    def assign_visual_style(self, beats: List[Beat]) -> List[Beat]:
        """Assign camera styles and visual purposes per beat."""
        for i, beat in enumerate(beats):
            e = beat.emotion
            if e == Emotion.WONDER:
                beat.camera_primary = CameraStyle.WIDE
                beat.camera_cutaway = CameraStyle.AERIAL
            elif e in (Emotion.TENSION, Emotion.DRAMATIC, Emotion.URGENT):
                beat.camera_primary = CameraStyle.CLOSEUP
                beat.camera_cutaway = CameraStyle.DUTCH
            elif e in (Emotion.CONTEMPLATIVE, Emotion.NOSTALGIC):
                beat.camera_primary = CameraStyle.MEDIUM
                beat.camera_cutaway = CameraStyle.CLOSEUP
            elif e in (Emotion.SOLEMN, Emotion.MYSTERIOUS):
                beat.camera_primary = CameraStyle.LOW_ANGLE
                beat.camera_cutaway = CameraStyle.HIGH_ANGLE
            elif e in (Emotion.TRIUMPHANT, Emotion.HOPEFUL):
                beat.camera_primary = CameraStyle.WIDE
                beat.camera_cutaway = CameraStyle.TRACKING
            elif e in (Emotion.ENERGETIC,):
                beat.camera_primary = CameraStyle.TRACKING
                beat.camera_cutaway = CameraStyle.POV
            else:
                style_idx = i % 3
                if style_idx == 0:
                    beat.camera_primary = CameraStyle.WIDE
                    beat.camera_cutaway = CameraStyle.MEDIUM
                elif style_idx == 1:
                    beat.camera_primary = CameraStyle.MEDIUM
                    beat.camera_cutaway = CameraStyle.CLOSEUP
                else:
                    beat.camera_primary = CameraStyle.CLOSEUP
                    beat.camera_cutaway = CameraStyle.WIDE

            # Transition Triggers: ~80% CUT_SYNC for fast-paced editing.
            # Crossfade/fade only for scene boundaries.
            if i == 0:
                # Scene entry: fade in from black
                beat.transition_in = Transition.FADE
                # Scene exit: cut sync into next shot
                beat.transition_out = Transition.CUT
            else:
                # Within-scene: use CUT_SYNC (voiceover-aware cut)
                beat.transition_in = Transition.CUT
                beat.transition_out = Transition.CUT
            if i == len(beats) - 1:
                # Scene end: dip to black
                beat.transition_out = Transition.DIP_TO_BLACK

            # Visual purpose
            if beat.camera_primary == CameraStyle.WIDE:
                beat.visual_purpose = f"Establish context: {beat.text[:60]}"
            elif beat.camera_primary == CameraStyle.CLOSEUP:
                beat.visual_purpose = f"Emphasize intensity: {beat.text[:60]}"
            else:
                beat.visual_purpose = f"Illustrate: {beat.text[:60]}"

        return beats


class ShotPlanner:
    """Plans individual shots within each beat."""

    def plan_shots(self, beats: List[Beat], scene_index: int = 0) -> List[Beat]:
        """Generate primary + cutaway + backup shots per beat.

        Uses Motion Grammar to apply archetypal motion sequences across shots,
        ensuring direction consistency and eliminating flicker.
        """
        for beat in beats:
            bd = beat.duration
            shots = []

            # Primary: 60-70% of beat
            primary_dur = min(bd * 0.65, 5.0)
            shots.append(Shot(
                timestamp=0.0,
                duration=primary_dur,
                shot_type=ShotType.PRIMARY,
                camera=beat.camera_primary,
                emotion=beat.emotion,
                visual_purpose=beat.visual_purpose,
                transition=beat.transition_in,
                description=f"Primary shot for beat {beat.index}",
            ))

            # Cutaway: 25-30% remaining
            remaining = bd - primary_dur
            if remaining > 1.5:
                cutaway_dur = min(remaining * 0.7, 3.0)
                shots.append(Shot(
                    timestamp=primary_dur,
                    duration=cutaway_dur,
                    shot_type=ShotType.CUTAWAY,
                    camera=beat.camera_cutaway,
                    emotion=beat.emotion,
                    transition=Transition.CUT,
                    visual_purpose=f"Cutaway detail",
                ))
                backup_remaining = remaining - cutaway_dur
                if backup_remaining > 1.0:
                    shots.append(Shot(
                        timestamp=primary_dur + cutaway_dur,
                        duration=backup_remaining,
                        shot_type=ShotType.BACKUP,
                        camera=beat.camera_primary,
                        emotion=beat.emotion,
                        transition=Transition.CUT,
                        visual_purpose=f"Backup shot",
                    ))

            # Assign motion using Motion Grammar archetypes
            beat.shots = shots

        # Apply archetypal motion patterns across all shots in the scene
        # Use the scene index to select a deterministic archetype
        all_shots = []
        for beat in beats:
            all_shots.extend(beat.shots)

        if all_shots:
            # Get the dominant emotion from the first beat for archetype selection
            dominant_emotion = beats[0].emotion.value if beats else "neutral"
            applied_shots = apply_archetype_to_sequence(
                all_shots, scene_index, dominant_emotion
            )

            # Re-distribute shots back to beats
            shot_idx = 0
            for beat in beats:
                beat_shot_count = len(beat.shots)
                beat.shots = applied_shots[shot_idx:shot_idx + beat_shot_count]
                shot_idx += beat_shot_count

        return beats


class CinematicEditor:
    """Edits shots into a cinematic sequence with L/J cuts, transitions."""

    def edit_sequence(self, beats: List[Beat]) -> List[Beat]:
        """Apply editing sequence with Transition Triggers (CUT_SYNC).

        Instead of L/J cuts (which require crossfades), use precise
        cut sync points between beats.
        """
        for i in range(len(beats) - 1):
            curr, nxt = beats[i], beats[i + 1]

            # All internal beats use CUT_SYNC transitions
            if curr.shots:
                curr.shots[-1].transition = Transition.CUT
            if nxt.shots:
                nxt.shots[0].transition = Transition.CUT

        return beats

    def adjust_pacing(self, beats: List[Beat], energy_level: float = 0.5) -> List[Beat]:
        """Adjust beat duration. 0.0=slow, 1.0=fast."""
        for beat in beats:
            if energy_level > 0.7:
                beat.duration = max(2.5, beat.duration * 0.8)
            elif energy_level < 0.3:
                beat.duration = min(7.0, beat.duration * 1.2)

            if beat.shots:
                total = sum(s.duration for s in beat.shots)
                if total > 0:
                    scale = beat.duration / total
                    for s in beat.shots:
                        s.duration *= scale
        return beats


class TimelineBuilder:
    """Builds timeline from beats with pacing optimization.
    Returns Pydantic BeatPlan objects for pipeline consumption.
    """

    def __init__(self):
        self.beat_planner = BeatPlanner()
        self.shot_planner = ShotPlanner()
        self.editor = CinematicEditor()

    def build_timeline(self, narration: str, scene_duration: float,
                       topic: str = "", energy: float = 0.5,
                       scene_index: int = 0,
                       narrative_role: str = "exploration") -> List[BeatPlan]:
        """Full pipeline: narration -> beats -> shots -> Pydantic BeatPlans.

        Args:
            scene_index: Used to select deterministic motion archetype.
            narrative_role: Role in narrative arc for pace-based duration.
        """
        beats = self.beat_planner.plan_beats(narration, scene_duration, narrative_role)
        beats = self.beat_planner.assign_emotions(beats, topic)
        beats = self.beat_planner.assign_visual_style(beats)
        beats = self.shot_planner.plan_shots(beats, scene_index)
        beats = self.editor.edit_sequence(beats)
        beats = self.editor.adjust_pacing(beats, energy)
        # Convert to Pydantic models
        return [_internal_beat_to_pydantic(b) for b in beats]

    def get_pacing_metrics(self, bep: List[BeatPlan]) -> dict:
        """Compute visual pacing metrics from BeatPlan list."""
        if not bep:
            return {}

        shot_count = sum(len(b.shots) for b in bep)
        total_duration = sum(b.duration for b in bep)
        avg_beat_dur = total_duration / len(bep) if bep else 0
        avg_shot_dur = total_duration / shot_count if shot_count else 0

        cameras = set()
        motions = set()
        emotions = set()
        transitions = set()
        l_cuts = 0
        j_cuts = 0
        match_cuts = 0

        for b in bep:
            cameras.add(b.camera_primary)
            emotions.add(b.emotion)
            for s in b.shots:
                motions.add(s.motion)
                transitions.add(s.transition)
                if s.transition == TransitionType.CROSSFADE and s.timestamp < 0:
                    l_cuts += 1

        pacing_score = round(
            (len(cameras) / 3.0 * 0.3 + 
             len(emotions) / 4.0 * 0.3 +
             len(transitions) / 3.0 * 0.2 +
             min(shot_count / len(bep) / 2.0, 1.0) * 0.2) * 100, 1
        ) if bep else 0

        return {
            "total_beats": len(bep),
            "total_shots": shot_count,
            "total_duration": round(total_duration, 2),
            "avg_beat_duration": round(avg_beat_dur, 2),
            "avg_shot_duration": round(avg_shot_dur, 2),
            "unique_cameras": len(cameras),
            "unique_motions": len(motions),
            "unique_emotions": len(emotions),
            "unique_transitions": len(transitions),
            "max_shot_duration": round(max(
                (s.duration for b in bep for s in b.shots), default=0
            ), 2),
            "pacing_score": pacing_score,
        }

    def format_timeline(self, bep: List[BeatPlan]) -> str:
        """Human-readable timeline dump."""
        lines = [f"{'Beat':>5} {'Start':>7} {'Dur':>6} {'Emotion':16s} {'Camera':16s} {'Shots':>6} {'Trans':12s}",
                 "-" * 75]
        for b in bep:
            lines.append(
                f"{b.index:>5} {b.start_time:>6.1f}s {b.duration:>5.1f}s "
                f"{b.emotion:16s} {b.camera_primary.value:16s} "
                f"{len(b.shots):>6} {b.transition_in.value:12s}"
            )
            for s in b.shots:
                lines.append(
                    f"  {s.shot_type.value:12s} {s.timestamp:>6.2f}s {s.duration:>5.2f}s "
                    f"{s.camera.value:16s} {s.motion:16s} {s.transition.value:12s}"
                )
        return "\n".join(lines)
