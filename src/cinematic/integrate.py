
"""Integration: replaces old single-clip-per-scene with beat-based editing."""
from .beat_planner import TimelineBuilder, Beat
from typing import List, Dict
import json

class SceneEditor:
    """Edits a full documentary scene using beat-based timeline."""
    
    def __init__(self):
        self.timeline_builder = TimelineBuilder()
    
    def edit_scene(self, narration: str, duration: float, topic: str = "", energy: float = 0.5) -> Dict:
        """Full scene edit returning timeline + metrics."""
        beats = self.timeline_builder.build_timeline(narration, duration, topic, energy)
        metrics = self.timeline_builder.get_pacing_metrics(beats)
        timeline_str = self.timeline_builder.format_timeline(beats)
        return {
            "beats": beats,
            "metrics": metrics,
            "timeline": timeline_str,
        }
    
    def timeline_to_dict(self, beats: List[Beat]) -> List[Dict]:
        """Convert beats to serializable dict for renderer."""
        result = []
        for beat in beats:
            beat_dict = {
                "index": beat.index,
                "text": beat.text,
                "start_time": round(beat.start_time, 2),
                "duration": round(beat.duration, 2),
                "emotion": beat.emotion.value,
                "camera": beat.camera_primary.value,
                "shots": []
            }
            for shot in beat.shots:
                beat_dict["shots"].append({
                    "timestamp": round(shot.timestamp, 2),
                    "duration": round(shot.duration, 2),
                    "type": shot.shot_type.value,
                    "camera": shot.camera.value,
                    "motion": shot.motion.value,
                    "transition": shot.transition.value,
                    "asset_type": shot.asset_type.value,
                })
            result.append(beat_dict)
        return result
