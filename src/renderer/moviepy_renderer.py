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
from typing import Optional

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    TextClip,
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

    def render(
        self,
        timeline_path: str,
        output_path: str,
        subtitles: Optional[list[dict]] = None,
    ) -> None:
        """Render a timeline JSON file to a video file.

        Args:
            timeline_path: Absolute or relative path to ``timeline.json``.
            output_path: Destination path for the final ``.mp4``.
            subtitles: Optional list of word-timing dicts from the
                SubtitleEngine.  When provided, animated subtitle
                clips are composited onto the final video.
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

        # ── Subtitle overlay ──────────────────────────────────────────────
        subtitle_enabled = get_config("subtitles.enabled", True)
        if subtitles and subtitle_enabled:
            print(f"-> Adding {len(subtitles)} animated subtitle clips...")
            for sub in subtitles:
                start_sec = sub["start_ms"] / 1000.0
                end_sec = sub["end_ms"] / 1000.0
                dur = end_sec - start_sec
                if dur <= 0:
                    continue

                txt_clip = TextClip(
                    txt=sub.get("text", ""),
                    fontsize=sub.get("font_size", 28),
                    color=sub.get("color", "#FFFFFF"),
                    stroke_color=sub.get("outline", "#000000"),
                    stroke_width=1,
                    method="label",
                )
                # Align at bottom centre
                txt_clip = txt_clip.set_position(
                    ("center", target_res[1] - sub.get("bottom_margin", 80))
                ).set_start(start_sec).set_duration(dur)

                # Apply fade animation
                fade_in = sub.get("fade_in_ms", 0)
                fade_out = sub.get("fade_out_ms", 0)
                if fade_in > 0:
                    txt_clip = txt_clip.crossfadein(fade_in / 1000.0)
                if fade_out > 0:
                    txt_clip = txt_clip.crossfadeout(fade_out / 1000.0)

                video_clips.append(txt_clip)

        if audio_clips:
            final_audio = CompositeAudioClip(audio_clips)
            final_video = CompositeVideoClip(video_clips, size=target_res).set_audio(final_audio)
        else:
            final_video = CompositeVideoClip(video_clips, size=target_res)

        print(f"Rendering {output_path} on CPU...")
        final_video.write_videofile(
            output_path,
            fps=timeline.render_settings.fps,
            codec=get_config("render.codec", "libx264"),
            audio_codec=get_config("render.audio_codec", "aac"),
            threads=get_config("render.threads", 4),
            preset=get_config("render.preset", "fast"),
        )
