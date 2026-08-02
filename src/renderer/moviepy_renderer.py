"""
moviepy_renderer.py — Concrete MoviePy-based renderer implementation.

Applies the Pillow/MoviePy compatibility shim at module import time,
then provides the ``MoviePyRenderer`` class implementing the ``Renderer``
interface defined in ``src.renderer``.

Supports optional cinematic motion effects (Ken Burns) and configurable
scene transitions via the ``MotionEngine`` and ``TransitionEngine``.
"""

# ── Compatibility shim ──────────────────────────────────────────────────
# Pillow >= 11 removed the deprecated Image.ANTIALIAS constant.
# MoviePy 1.0.3 still references it in video/fx/resize.py.
# We alias LANCZOS so MoviePy works unchanged.  Must run before moviepy import.
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

import os
import json
from typing import Any, Optional

from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
)
from moviepy.video.fx.resize import resize

from src.effects import MotionEngine, TransitionEngine
from src.models import RenderSettings, Timeline, TimelineTrack
from src.models.schemas import (
    Scene,
    AssetPlan,
    AudioPlan,
    RenderPlan,
    EditingPlan,
    CameraMotion,
    TransitionType,
)
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


# ── Motion helper ──────────────────────────────────────────────────────────


def _cover_crop(clip, target_res: tuple[int, int]):
    """Scale to fill the target frame (cover) then center-crop.

    Fixes v2 regression: clips were stretched to 1920x1080, distorting
    non-16:9 assets (letterboxed/ultra-wide Pexels clips).  Now every
    shot fills the full canvas with correct aspect ratio.
    """
    tw, th = target_res
    cw, ch = clip.size
    if cw <= 0 or ch <= 0:
        return clip.resize(newsize=target_res)
    scale = max(tw / cw, th / ch)
    new_size = (int(round(cw * scale)), int(round(ch * scale)))
    clip = clip.resize(newsize=new_size)
    # Center crop to exact target
    x = (new_size[0] - tw) // 2
    y = (new_size[1] - th) // 2
    return clip.crop(x1=x, y1=y, width=tw, height=th)


def _apply_motion(
    clip: VideoFileClip,
    motion: dict[str, Any],
    target_res: tuple[int, int],
) -> VideoFileClip:
    """Apply a Ken Burns motion descriptor to a clip.

    Uses time-dependent ``resize`` and ``set_position`` to create
    smooth zoom/pan effects.  Base frame is cover-cropped (never
    stretched) so non-16:9 assets fill the canvas.
    """
    mtype = motion.get("type", "none")
    if mtype == "none":
        return _cover_crop(clip, target_res)

    zoom_start = motion.get("zoom_start", 1.0)
    zoom_end = motion.get("zoom_end", 1.0)
    pan_x = motion.get("pan_x", 0)
    pan_y = motion.get("pan_y", 0)

    dur = clip.duration
    if dur <= 0:
        return _cover_crop(clip, target_res)

    # Base cover-crop to fill the frame (no distortion)
    clip = _cover_crop(clip, target_res)

    # Time-dependent zoom (linerp between zoom_start and zoom_end)
    def _zoom(t: float) -> float:
        progress = t / dur if dur > 0 else 0
        return zoom_start + (zoom_end - zoom_start) * progress

    clip = clip.resize(lambda t: _zoom(t))

    # Time-dependent pan
    def _pos(t: float) -> tuple[int, int]:
        progress = t / dur if dur > 0 else 0
        x = int(pan_x * progress)
        y = int(pan_y * progress)
        return (x, y)

    clip = clip.set_position(_pos)
    return clip


# ── Transition helper ─────────────────────────────────────────────────────


def _apply_transition(
    clip: VideoFileClip,
    transition: dict[str, Any],
    dur: float,
) -> VideoFileClip:
    """Apply a transition effect to a single clip.

    *cut* / *cut_sync* — no effect (instant transitions).
    *fade* — fade in at the start.
    *crossfade* — crossfade in (caller must overlap adjacent clips).
    *dip_to_black*, *dissolve*, *zoom* — fade in (simplified using crossfadein).
    """
    ttype = transition.get("type", "cut")
    tdur = transition.get("duration", dur)

    if ttype in ("cut", "cut_sync") or tdur <= 0:
        return clip

    if ttype == "fade":
        return clip.fadein(tdur).fadeout(tdur)

    # crossfade / dissolve / dip_to_black / zoom all use crossfade
    return clip.crossfadein(tdur)


# ── Renderer implementation ──────────────────────────────────────────────


class MoviePyRenderer(Renderer):
    """MoviePy-based renderer.

    Decodes audio/video clips using MoviePy (which wraps FFmpeg), composites
    them, optionally applies cinematic motion and transitions, and encodes
    the final output via ``write_videofile``.
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

        # ── Audio clips ────────────────────────────────────────────────
        audio_clips = []
        for track in timeline.audio_timeline:
            if not track.file or not os.path.exists(track.file):
                print(f"  -> Skipping missing audio file: {track.file!r}")
                continue
            clip = AudioFileClip(track.file).set_start(track.start_time)
            audio_clips.append(clip)

        # ── Video clips with motion + transitions ──────────────────────
        video_tracks = timeline.video_timeline
        video_clips: list = []

        motion_enabled = get_config("effects.motion.enabled", True)
        trans_enabled = get_config("effects.transitions.enabled", True)

        # Generate motion and transition descriptors
        motion_engine = MotionEngine()
        transition_engine = TransitionEngine()
        motion_descriptors = motion_engine.generate(len(video_tracks))
        transition_descriptors = transition_engine.generate(len(video_tracks))

        for i, track in enumerate(video_tracks):
            if not os.path.exists(track.file):
                print(f"  -> Skipping missing video file: {track.file}")
                continue

            clip = VideoFileClip(track.file)

            # ── Apply motion (from timeline or auto-generated) ────────
            # Check for per-shot motion from timeline metadata
            track_dict = raw.get("video_timeline", [])
            track_meta = track_dict[i] if i < len(track_dict) else {}
            shot_motion = track_meta.get("motion", "")
            shot_transition = track_meta.get("transition", "crossfade")

            if motion_enabled and shot_motion and shot_motion != "none":
                # Use motion from timeline metadata
                motion_desc = {"type": shot_motion, "intensity": 0.3}
                clip = _apply_motion(clip, motion_desc, target_res)
            elif motion_enabled:
                # Fall back to auto-generated motion
                clip = _apply_motion(clip, motion_descriptors[i], target_res)

            # ── Apply transitions ───────────────────────────────────────
            trans = transition_descriptors[i]
            tdur = trans.get("duration", 0.0)

            # Use timeline-specified transition type
            if shot_transition and shot_transition != "none":
                if "dissolve" in shot_transition or "crossfade" in shot_transition:
                    trans["type"] = "dissolve"
                elif "fade" in shot_transition or "dip_to_black" in shot_transition:
                    trans["type"] = "fade"
                elif "wipe" in shot_transition:
                    trans["type"] = "wipe"

            if trans["type"] not in ("cut", "cut_sync") and tdur > 0 and i > 0:
                # Overlap with previous clip: shift start earlier by tdur
                start = track.start_time - tdur
                end = track.end_time
                start = max(0.0, start)
                clip = clip.set_start(start).set_end(end)
                clip = _apply_transition(clip, trans, tdur)
            else:
                clip = clip.set_start(track.start_time).set_end(track.end_time)

            video_clips.append(clip)

        # ── Add transition bridge clips for fade/dip_to_black ────────
        if trans_enabled:
            for i, trans in enumerate(transition_descriptors):
                if i == 0:
                    continue
                tdur = trans.get("duration", 0.0)
                ttype = trans.get("type", "cut")
                if tdur > 0 and ttype in ("dip_to_black", "fade"):
                    black = ColorClip(size=target_res, color=[0, 0, 0]).set_duration(tdur)
                    prev_end = video_tracks[i - 1].end_time
                    black = black.set_start(prev_end)
                    video_clips.append(black)
                elif tdur > 0 and ttype == "dissolve":
                    # Dissolve is handled by crossfadein on clip above;
                    # no extra bridge needed, but we add a half-opacity overlay
                    prev_end = video_tracks[i - 1].end_time
                    overlay = ColorClip(size=target_res, color=[0, 0, 0]).set_duration(tdur)
                    overlay = overlay.set_start(prev_end).set_opacity(0.5)
                    video_clips.append(overlay)

        # ── Subtitle overlay ──────────────────────────────────────────
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
                txt_clip = txt_clip.set_position(
                    ("center", target_res[1] - sub.get("bottom_margin", 80))
                ).set_start(start_sec).set_duration(dur)

                fade_in = sub.get("fade_in_ms", 0)
                fade_out = sub.get("fade_out_ms", 0)
                if fade_in > 0:
                    txt_clip = txt_clip.crossfadein(fade_in / 1000.0)
                if fade_out > 0:
                    txt_clip = txt_clip.crossfadeout(fade_out / 1000.0)

                video_clips.append(txt_clip)

        # ── Composite ──────────────────────────────────────────────────
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
