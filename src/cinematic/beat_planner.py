#!/usr/bin/env python3
"""
BeatPlanner — splits narration into semantic beats with visual intent.

Each beat: 3-6 seconds, with visual purpose, emotion, camera style,
transition, asset type, and motion.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import re


class Emotion(str, Enum):
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


class ShotType(str, Enum):
    PRIMARY = "primary"
    CUTAWAY = "cutaway"
    BACKUP = "backup"
    MOTION_GRAPHICS = "motion_graphics"


@dataclass
class Shot:
    """A single shot within a beat. Contains visual + timing data."""
    timestamp: float  # seconds from start of scene
    duration: float  # seconds (never > 6 unless explicitly justified)
    shot_type: ShotType = ShotType.PRIMARY
    camera: CameraStyle = CameraStyle.MEDIUM
    motion: Motion = Motion.KEN_BURNS_IN
    asset_type: AssetType = AssetType.VIDEO
    transition: Transition = Transition.CROSS_DISSOLVE
    emotion: Emotion = Emotion.NEUTRAL
    visual_purpose: str = ""
    description: str = ""
    search_query: str = ""
    justify_long_shot: str = ""  # required if duration > 6


@dataclass
class Beat:
    """A semantic beat — one complete thought unit with visual treatment."""
    index: int
    text: str  # the narration text for this beat
    start_time: float  # seconds from start of scene
    duration: float  # seconds (3-6 typical)
    emotion: Emotion = Emotion.NEUTRAL
    visual_purpose: str = ""
    camera_primary: CameraStyle = CameraStyle.MEDIUM
    camera_cutaway: CameraStyle = CameraStyle.WIDE
    transition_in: Transition = Transition.CROSS_DISSOLVE
    transition_out: Transition = Transition.CROSS_DISSOLVE
    shots: List[Shot] = field(default_factory=list)
    motion_graphics_note: str = ""

    def total_shot_duration(self) -> float:
        return sum(s.duration for s in self.shots)


def split_into_sentences(text: str) -> List[str]:
    """Split narration into individual sentences."""
    # Handle common abbreviations
    text = re.sub(r'(?<=[.!?])\s+', '\n', text)
    sentences = [s.strip() for s in text.split('\n') if s.strip()]
    return sentences


def split_into_clauses(sentence: str) -> List[str]:
    """Split a long sentence into clauses at commas, conjunctions."""
    # If sentence is short enough, keep as one beat
    if len(sentence) < 80:
        return [sentence]
    
    # Split at major punctuation
    clauses = re.split(r'(?:;\s*|,\s*(?:and|but|however|while|although|because)\s*)', sentence)
    result = []
    for c in clauses:
        c = c.strip()
        if c:
            result.append(c)
    return result if result else [sentence]


class BeatPlanner:
    """Plans beats from narration text."""

    def plan_beats(self, narration: str, scene_duration: float) -> List[Beat]:
        """Split narration into beats with timing. Each beat gets 3-6 seconds."""
        sentences = split_into_sentences(narration)
        if not sentences:
            return []

        # Flatten: split long sentences into clauses
        clauses = []
        for s in sentences:
            clauses.extend(split_into_clauses(s))

        if not clauses:
            return []

        # Allocate duration per beat
        beat_count = len(clauses)
        ideal_duration = 4.5  # seconds per beat
        total_needed = beat_count * ideal_duration

        # Scale to fit scene duration, clamp each beat to 3-6s
        scale = scene_duration / total_needed if total_needed > 0 else 1.0
        beats = []
        time_cursor = 0.0

        for i, clause in enumerate(clauses):
            raw_duration = ideal_duration * scale
            duration = max(3.0, min(6.0, raw_duration))
            
            # Last beat gets remaining time
            if i == len(clauses) - 1:
                remaining = scene_duration - time_cursor
                if remaining > 0:
                    duration = remaining

            beat = Beat(
                index=i,
                text=clause,
                start_time=time_cursor,
                duration=duration,
            )
            beats.append(beat)
            time_cursor += duration

        # Normalize to scene duration
        if beats and beats[-1].start_time + beats[-1].duration < scene_duration:
            diff = scene_duration - (beats[-1].start_time + beats[-1].duration)
            beats[-1].duration += diff

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
            for keyword, emotion in emotion_map.items():
                if keyword in lower:
                    beat.emotion = emotion
                    found = True
                    break
            if not found:
                # Default based on position
                if beat.index == 0:
                    beat.emotion = Emotion.WONDER if topic else Emotion.NEUTRAL
                elif beat.index == len(beats) - 1:
                    beat.emotion = Emotion.TRIUMPHANT if topic else Emotion.NEUTRAL
                else:
                    beat.emotion = Emotion.NEUTRAL

        return beats

    def assign_visual_style(self, beats: List[Beat]) -> List[Beat]:
        """Assign camera styles and visual purposes per beat."""
        used_cameras = []
        last_wide_idx = -3
        last_closeup_idx = -3

        for i, beat in enumerate(beats):
            # Rotate camera styles
            emotion = beat.emotion
            if emotion in (Emotion.WONDER, Emotion.VAST, Emotion.AERIAL):
                beat.camera_primary = CameraStyle.WIDE
                beat.camera_cutaway = CameraStyle.AERIAL
            elif emotion in (Emotion.TENSION, Emotion.DRAMATIC, Emotion.URGENT):
                beat.camera_primary = CameraStyle.CLOSEUP
                beat.camera_cutaway = CameraStyle.DUTCH
            elif emotion in (Emotion.CONTEMPLATIVE, Emotion.NOSTALGIC):
                beat.camera_primary = CameraStyle.MEDIUM
                beat.camera_cutaway = CameraStyle.CLOSEUP
            elif emotion in (Emotion.SOLEMN, Emotion.MYSTERIOUS):
                beat.camera_primary = CameraStyle.LOW_ANGLE
                beat.camera_cutaway = CameraStyle.HIGH_ANGLE
            elif emotion in (Emotion.TRIUMPHANT, Emotion.HOPEFUL):
                beat.camera_primary = CameraStyle.WIDE
                beat.camera_cutaway = CameraStyle.TRACKING
            else:
                # Default rotation: wide, medium, closeup, repeat
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

            # Assign transitions
            if i == 0:
                beat.transition_in = Transition.FADE
            else:
                prev_emotion = beats[i-1].emotion
                if prev_emotion != beat.emotion:
                    beat.transition_in = Transition.CROSS_DISSOLVE
                else:
                    beat.transition_in = Transition.CUT

            if i == len(beats) - 1:
                beat.transition_out = Transition.DIP_TO_BLACK
            else:
                beat.transition_out = Transition.CROSS_DISSOLVE

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

    def plan_shots(self, beats: List[Beat]) -> List[Beat]:
        """For each beat, generate primary + cutaway + backup shots."""
        for beat in beats:
            bd = beat.duration
            shots = []

            # Primary shot: 60-70% of beat duration
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

            # Cutaway: 25-30% of beat duration
            remaining = bd - primary_dur
            if remaining > 1.5:
                cutaway_dur = min(remaining * 0.7, 3.0)
                shots.append(Shot(
                    timestamp=primary_dur,
                    duration=cutaway_dur,
                    shot_type=ShotType.CUTAWAY,
                    camera=beat.camera_cutaway,
                    emotion=beat.emotion,
                    transition=Transition.CROSS_DISSOLVE,
                    visual_purpose=f"Cutaway detail for context",
                ))

                # Backup: fill remaining
                backup_remaining = remaining - cutaway_dur
                if backup_remaining > 1.0:
                    shots.append(Shot(
                        timestamp=primary_dur + cutaway_dur,
                        duration=backup_remaining,
                        shot_type=ShotType.BACKUP,
                        camera=beat.camera_primary,
                        emotion=beat.emotion,
                        transition=Transition.CROSS_DISSOLVE,
                        visual_purpose=f"Backup shot",
                    ))

            # Assign motion based on camera
            for shot in shots:
                shot.motion = self._select_motion(shot.camera, shot.shot_type)

            beat.shots = shots

        return beats

    def _select_motion(self, camera: CameraStyle, shot_type: ShotType) -> Motion:
        if camera == CameraStyle.WIDE and shot_type == ShotType.PRIMARY:
            return Motion.KEN_BURNS_IN
        elif camera == CameraStyle.CLOSEUP:
            return Motion.ZOOM_IN
        elif camera == CameraStyle.AERIAL:
            return Motion.PARALLAX
        elif camera == CameraStyle.TRACKING:
            return Motion.FOLLOW
        elif camera in (CameraStyle.LOW_ANGLE, CameraStyle.HIGH_ANGLE):
            return Motion.TILT_UP
        elif shot_type == ShotType.CUTAWAY:
            return Motion.PUSH_IN
        elif shot_type == ShotType.BACKUP:
            return Motion.DRIFT
        else:
            return Motion.KEN_BURNS_IN


class CinematicEditor:
    """Edits shots into a cinematic sequence with L/J cuts, transitions."""

    def edit_sequence(self, beats: List[Beat]) -> List[Beat]:
        """Apply cinematic editing: L cuts, J cuts, match cuts, pacing."""
        # Spread audio across beat boundaries for L/J cuts
        for i in range(len(beats) - 1):
            curr = beats[i]
            next_beat = beats[i + 1]

            # L-cut: audio from next beat starts before visual transition
            if i % 2 == 0:
                # Apply L-cut: next beat's audio leads by 0.5s
                if next_beat.shots:
                    next_beat.shots[0].timestamp = -0.5
                    next_beat.shots[0].transition = Transition.L_CUT

            # J-cut: current beat's audio continues into next
            if i % 3 == 1:
                if curr.shots:
                    last_shot = curr.shots[-1]
                    last_shot.transition = Transition.J_CUT

        # Add match cuts between similar camera styles
        for i in range(len(beats) - 1):
            curr = beats[i]
            next_beat = beats[i + 1]
            if curr.camera_primary == next_beat.camera_primary:
                if curr.shots and next_beat.shots:
                    curr.shots[-1].transition = Transition.MATCH_CUT

        return beats

    def adjust_pacing(self, beats: List[Beat], energy_level: float = 0.5) -> List[Beat]:
        """Adjust beat duration based on energy/emotion.
        
        energy_level: 0.0 (slow) to 1.0 (fast)
        Higher energy = shorter beats, faster cuts.
        """
        for beat in beats:
            if energy_level > 0.7:
                beat.duration = max(2.5, beat.duration * 0.8)
            elif energy_level < 0.3:
                beat.duration = min(7.0, beat.duration * 1.2)

            # Rescale shots within new duration
            if beat.shots:
                total_shot_dur = sum(s.duration for s in beat.shots)
                if total_shot_dur > 0:
                    scale = beat.duration / total_shot_dur
                    for shot in beat.shots:
                        shot.duration *= scale

        return beats


class TimelineBuilder:
    """Builds complete video timeline from beats with pacing optimization."""

    def __init__(self):
        self.beat_planner = BeatPlanner()
        self.shot_planner = ShotPlanner()
        self.editor = CinematicEditor()

    def build_timeline(self, narration: str, scene_duration: float,
                       topic: str = "", energy: float = 0.5) -> List[Beat]:
        """Full pipeline: narration -> beats -> shots -> edited timeline."""
        beats = self.beat_planner.plan_beats(narration, scene_duration)
        beats = self.beat_planner.assign_emotions(beats, topic)
        beats = self.beat_planner.assign_visual_style(beats)
        beats = self.shot_planner.plan_shots(beats)
        beats = self.editor.edit_sequence(beats)
        beats = self.editor.adjust_pacing(beats, energy)
        return beats

    def get_pacing_metrics(self, beats: List[Beat]) -> dict:
        """Compute visual pacing metrics."""
        if not beats:
            return {}

        shot_count = sum(len(b.shots) for b in beats)
        total_duration = sum(b.duration for b in beats)
        avg_beat_dur = total_duration / len(beats) if beats else 0
        avg_shot_dur = total_duration / shot_count if shot_count else 0

        # Shot variety
        cameras = set()
        motions = set()
        emotions = set()
        transitions = set()
        for b in beats:
            cameras.add(b.camera_primary)
            emotions.add(b.emotion)
            if b.shots:
                for s in b.shots:
                    motions.add(s.motion)
                    transitions.add(s.transition)

        return {
            "total_beats": len(beats),
            "total_shots": shot_count,
            "total_duration": round(total_duration, 2),
            "avg_beat_duration": round(avg_beat_dur, 2),
            "avg_shot_duration": round(avg_shot_dur, 2),
            "unique_cameras": len(cameras),
            "unique_motions": len(motions),
            "unique_emotions": len(emotions),
            "unique_transitions": len(transitions),
            "max_shot_duration": round(max(
                (s.duration for b in beats for s in b.shots),
                default=0
            ), 2),
            "l_cuts": sum(1 for b in beats if b.shots and b.shots[0].transition == Transition.L_CUT),
            "j_cuts": sum(1 for b in beats 
                         if b.shots and b.shots[-1].transition == Transition.J_CUT),
            "match_cuts": sum(1 for b in beats[1:] 
                            if b.shots and b.shots[0].transition == Transition.MATCH_CUT),
            "pacing_score": round(
                (len(cameras) / 3.0 * 0.3 + 
                 len(emotions) / 4.0 * 0.3 +
                 len(transitions) / 3.0 * 0.2 +
                 min(shot_count / len(beats) / 2.0, 1.0) * 0.2) * 100, 1
            ) if beats else 0,
        }

    def format_timeline(self, beats: List[Beat]) -> str:
        """Human-readable timeline dump."""
        lines = []
        lines.append(f"{'Beat':>5} {'Start':>7} {'Dur':>6} {'Emotion':16s} {'Camera':16s} {'Shots':>6} {'Trans':12s}")
        lines.append("-" * 75)

        for beat in beats:
            trans_name = beat.transition_in.value if beat.transition_in else "cut"
            lines.append(
                f"{beat.index:>5} {beat.start_time:>6.1f}s {beat.duration:>5.1f}s "
                f"{beat.emotion.value:16s} {beat.camera_primary.value:16s} "
                f"{len(beat.shots):>6} {trans_name:12s}"
            )

            for s in beat.shots:
                lines.append(
                    f"  {s.shot_type.value:12s} {s.timestamp:>6.2f}s {s.duration:>5.2f}s "
                    f"{s.camera.value:16s} {s.motion.value:16s} {s.transition.value:12s}"
                )

        return "\n".join(lines)
