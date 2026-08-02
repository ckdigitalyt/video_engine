"""
shot_instrumenter.py — Per-shot instrumentation and render diagnostics.

Makes every rendered decision observable.  After a render, produces a
diagnostics report answering: WHY did this frame appear?

Per shot records:
  - selected asset + source + query + verification result
  - shot duration / narration duration
  - camera motion + transition + motion parameters
  - render duration + timeline placement
  - entity spec (required/prohibited) it was chosen for

Output: JSON file (render_diagnostics.json) + optional CSV for analysis.
"""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ShotRecord:
    scene_id: int = 0
    beat_index: int = 0
    shot_index: int = 0
    asset_path: str = ""
    asset_source: str = ""          # nasa / wikimedia / pexels / manim / ai / pinned
    asset_title: str = ""
    query_used: str = ""
    verification: Optional[dict] = None   # Entity–Asset verification result
    entity_spec: Optional[dict] = None
    shot_duration_s: float = 0.0
    narration_duration_s: float = 0.0
    camera_motion: str = ""
    motion_params: dict = field(default_factory=dict)
    transition: str = ""
    timeline_start_s: float = 0.0
    timeline_end_s: float = 0.0
    render_duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "beat_index": self.beat_index,
            "shot_index": self.shot_index,
            "asset_path": self.asset_path,
            "asset_source": self.asset_source,
            "asset_title": self.asset_title,
            "query_used": self.query_used,
            "verification": self.verification,
            "entity_spec": self.entity_spec,
            "shot_duration_s": round(self.shot_duration_s, 2),
            "narration_duration_s": round(self.narration_duration_s, 2),
            "camera_motion": self.camera_motion,
            "motion_params": self.motion_params,
            "transition": self.transition,
            "timeline_start_s": round(self.timeline_start_s, 2),
            "timeline_end_s": round(self.timeline_end_s, 2),
            "render_duration_s": round(self.render_duration_s, 2),
        }


class ShotInstrumenter:
    """Collects per-shot records and writes diagnostics."""

    def __init__(self):
        self._shots: list[ShotRecord] = []
        self._render_start = 0.0

    def start_render(self):
        self._render_start = time.time()

    def add_shot(self, rec: ShotRecord):
        self._shots.append(rec)

    def finish_render(self) -> float:
        return time.time() - self._render_start

    # ── Lookup helpers ─────────────────────────────────────────────────

    def shot_at(self, timestamp_s: float) -> Optional[ShotRecord]:
        """Explain which shot (and why) occupies a given timestamp."""
        for s in self._shots:
            if s.timeline_start_s <= timestamp_s < s.timeline_end_s:
                return s
        return None

    def explain(self, timestamp_s: float) -> str:
        s = self.shot_at(timestamp_s)
        if not s:
            return f"no shot at {timestamp_s:.1f}s"
        return (
            f"t={timestamp_s:.1f}s → scene {s.scene_id} beat {s.beat_index} "
            f"shot {s.shot_index}: '{os.path.basename(s.asset_path)}' "
            f"({s.asset_source}: {s.asset_title or s.query_used or 'n/a'}) "
            f"motion={s.camera_motion} trans={s.transition} "
            f"verified={'yes' if (s.verification or {}).get('passed') else 'no'}"
        )

    # ── Output ─────────────────────────────────────────────────────────

    def write(self, out_dir: str, render_seconds: float = 0.0,
              extra: Optional[dict] = None) -> str:
        os.makedirs(out_dir, exist_ok=True)
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_render_s": round(render_seconds, 2),
            "shot_count": len(self._shots),
            "shots": [s.to_dict() for s in self._shots],
        }
        if extra:
            report["extra"] = extra
        path = os.path.join(out_dir, "render_diagnostics.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2)
        return path

    def write_csv(self, out_dir: str) -> str:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "shot_diagnostics.csv")
        fields = ["scene_id", "beat_index", "shot_index", "asset_path", "asset_source",
                  "asset_title", "query_used", "shot_duration_s", "narration_duration_s",
                  "camera_motion", "transition", "timeline_start_s", "timeline_end_s",
                  "verified"]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for s in self._shots:
                w.writerow({
                    "scene_id": s.scene_id, "beat_index": s.beat_index,
                    "shot_index": s.shot_index, "asset_path": s.asset_path,
                    "asset_source": s.asset_source, "asset_title": s.asset_title,
                    "query_used": s.query_used,
                    "shot_duration_s": round(s.shot_duration_s, 2),
                    "narration_duration_s": round(s.narration_duration_s, 2),
                    "camera_motion": s.camera_motion, "transition": s.transition,
                    "timeline_start_s": round(s.timeline_start_s, 2),
                    "timeline_end_s": round(s.timeline_end_s, 2),
                    "verified": bool((s.verification or {}).get("passed")),
                })
        return path
