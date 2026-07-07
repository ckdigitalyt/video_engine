#!/usr/bin/env python3
"""Tests for cinematic beat-based editing module."""
import sys, os, json
sys.path.insert(0, '/home/ubuntu/video_engine')

from src.cinematic.beat_planner import (
    BeatPlanner, ShotPlanner, CinematicEditor, TimelineBuilder,
    Beat, Shot, Emotion, CameraStyle, Transition, Motion, ShotType
)
from src.models import BeatPlan, ShotPlan

bp = BeatPlanner()
sp = ShotPlanner()
ce = CinematicEditor()
tb = TimelineBuilder()

print("Testing BeatPlanner...")
narration = "The universe is vast and full of mysteries. But we are only beginning to understand our place in it. What if we are alone? What if we are not?"
beats = bp.plan_beats(narration, 15.0)
assert len(beats) > 1, f"Expected multiple beats, got {len(beats)}"
print(f"  Beats: {len(beats)}")
for b in beats:
    assert 2.5 <= b.duration <= 7.0, f"Beat {b.index} duration {b.duration}s out of range"
assert abs(sum(b.duration for b in beats) - 15.0) < 0.1, f"Duration sum mismatch: {sum(b.duration for b in beats)}"

print("Testing emotion assignment...")
beats = bp.assign_emotions(beats, "Space Exploration")
for b in beats:
    assert b.emotion in list(Emotion), f"Invalid emotion: {b.emotion}"

print("Testing visual style assignment...")
beats = bp.assign_visual_style(beats)
for b in beats:
    assert b.camera_primary in list(CameraStyle)
    assert b.camera_cutaway in list(CameraStyle)
    assert b.transition_in in list(Transition)

print("Testing ShotPlanner...")
beats = sp.plan_shots(beats)
for b in beats:
    assert len(b.shots) >= 1, f"Beat {b.index} has no shots"
    for s in b.shots:
        assert s.duration > 0, f"Shot has zero duration"
        assert s.shot_type in [ShotType.PRIMARY, ShotType.CUTAWAY, ShotType.BACKUP]
        assert s.camera in list(CameraStyle)
        assert s.motion is not None

print("Testing CinematicEditor...")
beats = ce.edit_sequence(beats)
beats = ce.adjust_pacing(beats, 0.6)

print("Testing TimelineBuilder full pipeline (Pydantic output)...")
bep = tb.build_timeline(narration, 15.0, "Space", 0.5)
assert len(bep) > 1
for b in bep:
    assert isinstance(b, BeatPlan), f"Expected BeatPlan, got {type(b)}"
    for s in b.shots:
        assert isinstance(s, ShotPlan), f"Expected ShotPlan, got {type(s)}"

metrics = tb.get_pacing_metrics(bep)
assert metrics["total_beats"] > 0
assert metrics["total_shots"] > 0
assert metrics["pacing_score"] > 0
print(f"  Pacing metrics: {json.dumps(metrics, indent=2)}")

timeline_str = tb.format_timeline(bep)
assert "Beat" in timeline_str
assert "Shot" in timeline_str

print("Testing long narration...")
long_narration = ("The Fermi Paradox asks a simple question. "
    "The universe is vast with billions of stars. "
    "But we have found no evidence of extraterrestrial intelligence. "
    "This contradiction is the heart of the paradox. "
    "Several solutions have been proposed over the years. "
    "Perhaps intelligent life is rare in the universe. "
    "Or perhaps they are out there and we simply cannot see them yet. "
    "The answer remains one of science's greatest mysteries.")
bep_long = tb.build_timeline(long_narration, 45.0, "Fermi Paradox", 0.5)
metrics_long = tb.get_pacing_metrics(bep_long)
assert metrics_long["total_beats"] > 3
assert metrics_long["total_shots"] > 3
print(f"  Long: {metrics_long['total_beats']} beats, {metrics_long['total_shots']} shots, pacing {metrics_long['pacing_score']}")

# Empty
empty = tb.build_timeline("", 10.0, "Test")
assert len(empty) == 0

# Single beat
single = tb.build_timeline("Just one short sentence.", 5.0, "Test")
assert len(single) >= 1

print("\nAll tests passed!")
print("BeatPlanner: OK")
print("ShotPlanner: OK")
print("CinematicEditor: OK")
print("TimelineBuilder: OK (Pydantic output)")
print("Pacing metrics: OK")
