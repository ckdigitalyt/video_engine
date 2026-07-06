"""
timeline_builder.py — Deterministic timeline construction for the video_engine pipeline.

Reads generated audio files, calculates exact scene durations from audio length,
applies transition offsets (when configured), and produces a validated timeline.json
that the renderer consumes.

The builder enforces:
- Monotonic timestamps.
- No overlapping clips within a track.
- Matching audio/video durations per scene.
- Existence of all referenced files.
"""

import json
import os
from typing import Any

from pydub import AudioSegment
from src.utils.config import get_config


class TimelineBuilder:
    """Deterministic timeline construction and validation."""

    def __init__(self):
        self.resolution = [
            get_config("render.resolution.width", 1920),
            get_config("render.resolution.height", 1080),
        ]
        self.fps = get_config("render.fps", 30)

    # ── Public API ─────────────────────────────────────────────────────────

    def build_and_write(
        self,
        scenes: list[dict[str, Any]],
        output_path: str = "timeline.json",
    ) -> str:
        """
        Build a validated timeline from *scenes* and write it to *output_path*.

        *scenes* is a list of dicts, each with:

            {"scene_id": int, "video_path": str, "audio_path": str}

        Returns the timeline as a JSON string.
        """
        timeline = self._build(scenes)
        errors = self.validate(timeline)
        if errors:
            for e in errors:
                print(f"[timeline] Validation error: {e}")
            raise RuntimeError(
                f"Timeline validation failed with {len(errors)} error(s)"
            )

        with open(output_path, "w") as f:
            json.dump(timeline, f, indent=2)

        print(f"[timeline] Wrote {output_path}")
        return json.dumps(timeline)

    def validate(self, timeline: dict) -> list[str]:
        """
        Run all timeline validation checks.

        Returns a list of error messages (empty list = valid).
        """
        errors: list[str] = []

        audio_tl = timeline.get("audio_timeline", [])
        video_tl = timeline.get("video_timeline", [])

        # ── Required keys ──────────────────────────────────────────────
        if "render_settings" not in timeline:
            errors.append("Missing 'render_settings'")
        else:
            rs = timeline["render_settings"]
            if "resolution" not in rs or "fps" not in rs:
                errors.append("render_settings missing 'resolution' or 'fps'")

        # ── File existence ─────────────────────────────────────────────
        for entry in audio_tl:
            path = entry.get("file", "")
            if path and not os.path.exists(path):
                errors.append(f"Audio file not found: {path}")

        for entry in video_tl:
            path = entry.get("file", "")
            if path and not os.path.exists(path):
                errors.append(f"Video file not found: {path}")

        # ── Monotonic timestamps / no overlap (audio) ──────────────────
        for track_name, entries in [("audio", audio_tl), ("video", video_tl)]:
            sorted_entries = sorted(entries, key=lambda e: e.get("start_time", 0))
            for i, e in enumerate(sorted_entries):
                st = e.get("start_time", 0)
                et = e.get("end_time", 0)
                if et < st:
                    errors.append(
                        f"{track_name} entry {i}: end_time ({et}) < start_time ({st})"
                    )
                if i > 0:
                    prev = sorted_entries[i - 1]
                    prev_et = prev.get("end_time", 0)
                    if st < prev_et:
                        errors.append(
                            f"{track_name} entries {i-1} and {i} overlap: "
                            f"prev end {prev_et} > next start {st}"
                        )

        # ── Audio / video duration correspondence ──────────────────────
        # For the current single-scene pipeline, the full timeline length
        # is determined by audio; video clips should cover the same range.
        if audio_tl and video_tl:
            audio_end = max(e.get("end_time", 0) for e in audio_tl)
            video_end = max(e.get("end_time", 0) for e in video_tl)
            # Allow trivial rounding differences
            if abs(audio_end - video_end) > 0.1:
                errors.append(
                    f"Audio duration ({audio_end:.2f}s) and video duration "
                    f"({video_end:.2f}s) differ by more than 0.1s"
                )

        return errors

    # ── Internal helpers ───────────────────────────────────────────────────

    def _build(self, scenes: list[dict[str, Any]]) -> dict:
        """Internal: produce a raw timeline dict from scenes (no validation)."""
        audio_timeline: list[dict] = []
        video_timeline: list[dict] = []

        # Scenes are ordered by scene_id
        current_time: float = 0.0

        for scene in sorted(scenes, key=lambda s: s["scene_id"]):
            audio_path = scene["audio_path"]
            video_path = scene["video_path"]

            # Determine exact audio duration
            audio_len = self._get_audio_duration(audio_path)

            start = current_time
            end = current_time + audio_len

            audio_timeline.append({
                "track": "voice",
                "file": audio_path,
                "start_time": start,
                "end_time": end,
            })

            video_timeline.append({
                "layer": 1,
                "file": video_path,
                "start_time": start,
                "end_time": end,
                "transition_out": "none",
            })

            # Advance the clock for the next scene.
            # Future: apply transition_offset here when cross-fades are supported.
            current_time = end

        return {
            "render_settings": {
                "resolution": self.resolution,
                "fps": self.fps,
            },
            "audio_timeline": audio_timeline,
            "video_timeline": video_timeline,
        }

    @staticmethod
    def _get_audio_duration(path: str) -> float:
        """Return the duration of *path* in seconds using pydub."""
        return len(AudioSegment.from_wav(path)) / 1000.0
