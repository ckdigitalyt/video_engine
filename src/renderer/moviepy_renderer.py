"""
moviepy_renderer.py — Concrete MoviePy-based renderer implementation.

Applies the Pillow/MoviePy compatibility shim at module import time,
then provides the ``MoviePyRenderer`` class implementing the ``Renderer``
interface defined in ``src.renderer``.
"""

# ── Compatibility shim ──────────────────────────────────────────────────
# Pillow >= 11 removed the deprecated Image.ANTIALIAS constant.
# MoviePy 1.0.3 still references it in video/fx/resize.py.
# We alias LANCZOS so MoviePy works unchanged.  Must run before moviepy import.
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

import json

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    VideoFileClip,
)

from src.models import RenderSettings, Timeline, TimelineTrack
from src.renderer import Renderer
from src.utils.config import get_config


# ── Module-level helpers (shared across instances) ───────────────────────


def parse_timeline(raw: dict) -> Timeline:
    """Convert a raw dict (from timeline.json) into a typed Timeline model."""
    rs = raw.get("render_settings", {})
    render_settings = RenderSettings(
        resolution=rs.get("resolution", [1920, 1080]),
        fps=rs.get("fps", 30),
    )
    audio_timeline = [
        TimelineTrack(
            track=a.get("track", "voice"),
            file=a["file"],
            start_time=a.get("start_time", 0.0),
            end_time=a.get("end_time", 0.0),
        )
        for a in raw.get("audio_timeline", [])
    ]
    video_timeline = [
        TimelineTrack(
            layer=v.get("layer", 1),
            file=v["file"],
            start_time=v.get("start_time", 0.0),
            end_time=v.get("end_time", 0.0),
            transition_out=v.get("transition_out", "none"),
        )
        for v in raw.get("video_timeline", [])
    ]
    return Timeline(
        render_settings=render_settings,
        audio_timeline=audio_timeline,
        video_timeline=video_timeline,
    )


# ── Renderer implementation ──────────────────────────────────────────────


class MoviePyRenderer(Renderer):
    """MoviePy-based renderer.

    Decodes audio/video clips using MoviePy (which wraps FFmpeg), composites
    them, and encodes the final output via ``write_videofile``.
    """

    def render(self, timeline_path: str, output_path: str) -> None:
        """Render a timeline JSON file to a video file.

        Args:
            timeline_path: Absolute or relative path to ``timeline.json``.
            output_path: Destination path for the final ``.mp4``.
        """
        with open(timeline_path, "r") as f:
            raw = json.load(f)

        timeline = parse_timeline(raw)
        target_res = tuple(timeline.render_settings.resolution)

        audio_clips = []
        for track in timeline.audio_timeline:
            clip = AudioFileClip(track.file).set_start(track.start_time)
            audio_clips.append(clip)

        video_clips = []
        for track in timeline.video_timeline:
            clip = VideoFileClip(track.file).resize(newsize=target_res)
            clip = clip.set_start(track.start_time).set_end(track.end_time)
            video_clips.append(clip)

        final_audio = CompositeAudioClip(audio_clips)
        final_video = CompositeVideoClip(video_clips, size=target_res).set_audio(final_audio)

        print(f"Rendering {output_path} on CPU...")
        final_video.write_videofile(
            output_path,
            fps=timeline.render_settings.fps,
            codec=get_config("render.codec", "libx264"),
            audio_codec=get_config("render.audio_codec", "aac"),
            threads=get_config("render.threads", 4),
            preset=get_config("render.preset", "fast"),
        )
