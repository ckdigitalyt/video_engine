"""
integrate.py — SceneEditor for full scene edits using the cinematic timeline.
"""

from typing import List, Dict
from src.cinematic.beat_planner import TimelineBuilder
from src.models import BeatPlan, ShotPlan


class SceneEditor:
    """Edits a full documentary scene using beat-based timeline."""

    def __init__(self):
        self.timeline_builder = TimelineBuilder()

    def edit_scene(
        self, narration: str, duration: float,
        topic: str = "", energy: float = 0.5
    ) -> Dict:
        """Full scene edit returning timeline + metrics."""
        beats = self.timeline_builder.build_timeline(narration, duration, topic, energy)
        metrics = self.timeline_builder.get_pacing_metrics(beats)
        timeline_str = self.timeline_builder.format_timeline(beats)
        return {"beats": beats, "metrics": metrics, "timeline": timeline_str}

    def timeline_to_dict(self, beats: List[BeatPlan]) -> List[Dict]:
        """Convert BeatPlans to serializable dict for renderer."""
        result = []
        for beat in beats:
            beat_dict = {
                "index": beat.index,
                "text": beat.text,
                "start_time": beat.start_time,
                "duration": beat.duration,
                "emotion": beat.emotion,
                "camera": beat.camera_primary.value,
                "shots": [],
            }
            for shot in beat.shots:
                beat_dict["shots"].append({
                    "timestamp": shot.timestamp,
                    "duration": shot.duration,
                    "type": shot.shot_type.value,
                    "camera": shot.camera.value,
                    "motion": shot.motion,
                    "transition": shot.transition.value,
                })
            result.append(beat_dict)
        return result
