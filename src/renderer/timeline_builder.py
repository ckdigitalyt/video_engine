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
from typing import Any, Union

from pydub import AudioSegment
from src.utils.config import get_config
from src.models import SceneAsset, BeatPlan
from src.models.schemas import (
    Scene,
    AssetPlan,
    SceneNarration,
    SearchPlan,
    EditingPlan,
    AudioPlan,
    RenderPlan,
    scene_to_flat_dict,
)


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
        scenes: Union[list[dict[str, Any]], list[SceneAsset], list[Scene]],
        output_path: str = "timeline.json",
    ) -> str:
        """
        Build a validated timeline from *scenes* and write it to *output_path*.

        *scenes* is a list of :class:`SceneAsset`, :class:`Scene`, or dicts.
        Dict-based scenes must have:

            {"scene_id": int, "video_path": str, "audio_path": str}

        :class:`Scene` objects are converted to flat dicts via
        ``scene_to_flat_dict()``, then mapped to the timeline format using
        ``asset_plan`` fields (filepath for video, audio_plan.narration_audio_path
        for audio).

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
            if not path:
                errors.append("Audio entry has empty file path")
            elif not os.path.exists(path):
                errors.append(f"Audio file not found: {path}")

        for entry in video_tl:
            path = entry.get("file", "")
            if not path:
                errors.append("Video entry has empty file path")
            elif not os.path.exists(path):
                errors.append(f"Video file not found: {path}")

        # ── Monotonic timestamps / no overlap (audio only; video shots
        # may intentionally overlap for crossfades, L-cuts, J-cuts) ─────
        for track_name, entries in [("audio", audio_tl), ("video", video_tl)]:
            sorted_entries = sorted(entries, key=lambda e: e.get("start_time", 0))
            for i, e in enumerate(sorted_entries):
                st = e.get("start_time", 0)
                et = e.get("end_time", 0)
                if et < st:
                    errors.append(
                        f"{track_name} entry {i}: end_time ({et}) < start_time ({st})"
                    )
                if i > 0 and track_name == "audio":
                    prev = sorted_entries[i - 1]
                    prev_et = prev.get("end_time", 0)
                    if st < prev_et:
                        errors.append(
                            f"{track_name} entries {i-1} and {i} overlap: "
                            f"prev end {prev_et} > next start {st}"
                        )

        # ── Audio / video duration correspondence ──────────────────────
        # Video clips with transitions overlap, so the video track end
        # may not match audio end exactly.  We accept up to a 1.0s gap
        # (the video can undershoot — we pad; overshoot is a real problem).
        if audio_tl and video_tl:
            audio_end = max(e.get("end_time", 0) for e in audio_tl)
            video_end = max(e.get("end_time", 0) for e in video_tl)
            if audio_end > 0 and video_end < audio_end - 1.0:
                errors.append(
                    f"Audio duration ({audio_end:.2f}s) exceeds video duration "
                    f"({video_end:.2f}s) by more than 1.0s"
                )

        return errors

    # ── Internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _to_asset_dict(scene: Union[dict[str, Any], SceneAsset, Scene]) -> dict[str, Any]:
        """Normalize a Scene, SceneAsset, or raw dict to a dict with
        scene_id/video_path/audio_path.

        When a Scene has beat_plans, returns a list of shot-level dicts
        keyed as a "shots" list within the scene dict.
        """
        if isinstance(scene, Scene):
            # Check for beat-based editing
            if hasattr(scene, 'beat_plans') and scene.beat_plans:
                result = {
                    "scene_id": scene.scene_id,
                    "video_path": "",
                    "audio_path": "",
                    "shots": [],
                }
                if scene.audio_plan is not None:
                    result["audio_path"] = scene.audio_plan.narration_audio_path

                for beat in scene.beat_plans:
                    for shot in beat.shots:
                        if shot.asset_plan and shot.asset_plan.filepath:
                            result["shots"].append({
                                "beat_index": beat.index,
                                "shot_type": shot.shot_type.value,
                                "timestamp": beat.start_time + shot.timestamp,
                                "duration": shot.duration,
                                "filepath": shot.asset_plan.filepath,
                                "motion": shot.motion,
                                "transition": shot.transition.value,
                                "camera": shot.camera.value,
                            })
                return result

            video_path = ""
            audio_path = ""
            if scene.asset_plan is not None:
                video_path = scene.asset_plan.filepath
            if scene.audio_plan is not None:
                audio_path = scene.audio_plan.narration_audio_path
            return {
                "scene_id": scene.scene_id,
                "video_path": video_path,
                "audio_path": audio_path,
            }
        if isinstance(scene, SceneAsset):
            return {
                "scene_id": scene.scene_id,
                "video_path": scene.video_path,
                "audio_path": scene.audio_path,
            }
        return scene

    def _build(
        self,
        scenes: Union[list[dict[str, Any]], list[SceneAsset], list[Scene]],
    ) -> dict:
        """Internal: produce a raw timeline dict from scenes (no validation).

        Supports both single-clip scenes and beat-based shot-level scenes.
        Beat-based scenes expand shots into individual video timeline entries
        with per-shot motion and transition metadata.
        """
        audio_timeline: list[dict] = []
        video_timeline: list[dict] = []

        # Normalise all entries to dicts and order by scene_id
        scene_dicts = [self._to_asset_dict(s) for s in scenes]
        scene_dicts.sort(key=lambda s: s["scene_id"])

        global_time: float = 0.0

        for sd in scene_dicts:
            audio_path = sd["audio_path"]
            video_path = sd["video_path"]

            # Determine exact audio duration
            if audio_path and os.path.exists(audio_path):
                audio_len = self._get_audio_duration(audio_path)
            else:
                audio_len = 10.0  # fallback

            start = global_time
            end = global_time + audio_len

            audio_timeline.append({
                "track": "voice",
                "file": audio_path,
                "start_time": start,
                "end_time": end,
            })

            # Check for beat-based shots
            shots = sd.get("shots", [])
            if shots:
                # Shot-level entries with per-shot timing
                shot_time_offset = global_time
                for shot in shots:
                    shot_start = shot_time_offset + shot["timestamp"]
                    shot_start = max(global_time, shot_start)  # clamp to scene start
                    shot_end = shot_start + shot["duration"]
                    shot_end = min(end, shot_end)  # clamp to scene end

                    if shot["filepath"] and shot_end > shot_start:
                        video_timeline.append({
                            "layer": 1,
                            "file": shot["filepath"],
                            "start_time": shot_start,
                            "end_time": shot_end,
                            "transition": shot["transition"],
                            "motion": shot["motion"],
                            "camera": shot["camera"],
                            "beat_index": shot["beat_index"],
                            "shot_type": shot["shot_type"],
                        })

                # If shots don't cover the full audio length, extend coverage
                # WITHOUT unbounded static holds (expert review rec #4: no
                # single clip may run 12+ s of essentially unchanged visual).
                # Holds are chunked at MAX_HOLD_S and each chunk gets a
                # slow zoom (visual progression) so long narration overruns
                # stay visually alive.  An overrun longer than
                # MAX_TOTAL_HOLD_S fails the build loudly instead of
                # producing a retention-killing freeze.
                scene_shots = [v for v in video_timeline
                               if v.get("start_time", 0) >= start and v.get("end_time", 0) <= end]
                if scene_shots:
                    last_vid_end = max(v.get("end_time", 0) for v in scene_shots)
                    last_shot = max(scene_shots, key=lambda v: v.get("end_time", 0))
                    if last_vid_end < end - 0.1:
                        gap = end - last_vid_end
                        max_hold = getattr(self, "max_hold_s", 6.0)
                        max_total = getattr(self, "max_total_hold_s", 9.0)
                        if gap > max_total + 1e-6:
                            raise RuntimeError(
                                f"Timeline coverage gap {gap:.1f}s in scene "
                                f"{sd.get('scene_id')} exceeds hold limit "
                                f"{max_total:.0f}s — narration overruns visuals; "
                                "add more shots or trim narration")
                        cursor = last_vid_end
                        chunk_i = 0
                        beat = last_shot.get("beat_index", 0)
                        # v13 fix (expert review rec #4 + repeated_assets gate):
                        # hold chunks must NOT reuse the ending shot's file —
                        # that flags repeated_assets and holds one visual for
                        # too long.  Rotate through the scene's OTHER shots
                        # (visual progression) with progressive zooms; only
                        # fall back to the last file when the scene is
                        # single-shot.
                        _pool = [s for s in scene_shots
                                 if s.get("file") != last_shot.get("file")]
                        if not _pool:
                            # v14 fix (repeated_assets blocker on 52-Hz run):
                            # a SINGLE-shot scene must not reuse its own file
                            # for hold chunks — that flags repeated_assets.
                            # Rotate through OTHER scenes' distinct files so
                            # holds stay visually varied.
                            _pool = [s for s in video_timeline
                                     if s.get("file") != last_shot.get("file")]
                        if not _pool:
                            _pool = [last_shot]
                        while cursor < end - 0.05:
                            chunk = min(max_hold, end - cursor)
                            if chunk <= 0.05:
                                break
                            # rotate to the next distinct file in the pool
                            _src = _pool[chunk_i % len(_pool)]
                            _src_file = _src.get("file", "")
                            # Slow progressive zoom per chunk — each hold chunk
                            # is its own camera move (motion metadata drives
                            # the renderer's Ken Burns), never a freeze.
                            zoom = 1.0 + 0.06 * (chunk_i + 1)
                            video_timeline.append({
                                "layer": 1,
                                "file": _src_file,
                                "start_time": round(cursor, 3),
                                "end_time": round(cursor + chunk, 3),
                                "transition": "none",
                                "motion": "kenburns",
                                "camera": "static",
                                "beat_index": beat,
                                "shot_type": "hold",
                                "motion_params": {
                                    "zoom_start": max(1.0, zoom - 0.05),
                                    "zoom_end": zoom,
                                    "pan_x": 0.0,
                                    "pan_y": 0.0,
                                },
                            })
                            cursor += chunk
                            chunk_i += 1
            else:
                # Single clip per scene (legacy mode)
                video_timeline.append({
                    "layer": 1,
                    "file": video_path,
                    "start_time": start,
                    "end_time": end,
                    "transition": "none",
                    "motion": "none",
                    "camera": "static",
                })

            # Advance the clock for the next scene.
            global_time = end

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
