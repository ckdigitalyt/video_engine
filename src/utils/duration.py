"""
duration.py — Video duration verification and adjustment.

Ensures that video clips are at least as long as their corresponding
audio tracks.  Uses ffprobe to check real durations and applies looping
or speed adjustment as needed.
"""

import os
import subprocess
import tempfile
from typing import Optional

from src.utils.config import get_config


def get_media_duration(path: str) -> float:
    """Get the duration of a media file in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return 0.0


def ensure_video_duration(
    video_path: str,
    required_duration: float,
    output_path: Optional[str] = None,
) -> str:
    """Ensure a video clip is at least *required_duration* seconds long.

    If the video is shorter, loops it or slows it (configurable).

    Returns the path to the adjusted video (may be the same as input).
    """
    if not os.path.exists(video_path):
        return video_path

    vid_dur = get_media_duration(video_path)
    if vid_dur <= 0:
        return video_path

    if vid_dur >= required_duration:
        # Video is already long enough
        return video_path

    # Video is shorter than required — adjust
    out = output_path or video_path
    prefer_loop = get_config("duration_verification.prefer_loop", True)
    max_speed = get_config("duration_verification.max_speed_change", 1.5)

    if prefer_loop:
        # Loop the video to cover the required duration
        return _loop_video(video_path, required_duration, out)

    # Slow the video (within limits)
    speed_factor = vid_dur / required_duration
    if speed_factor < 1.0 / max_speed:
        speed_factor = 1.0 / max_speed

    return _slow_video(video_path, speed_factor, out)


def _loop_video(video_path: str, required_duration: float, output_path: str) -> str:
    """Loop a video to cover the required duration using concat."""
    vid_dur = get_media_duration(video_path)
    if vid_dur <= 0:
        return video_path

    loops_needed = int(required_duration / vid_dur) + 1

    # Build concat file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        concat_path = f.name
        for _ in range(loops_needed):
            f.write(f"file '{video_path}'\n")

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", concat_path, "-c", "copy",
             "-t", str(required_duration), output_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            print(f"-> Duration: looped video {vid_dur:.1f}s -> {required_duration:.1f}s")
        else:
            print(f"-> Duration: loop failed ({result.stderr[:100]}), using original")
            output_path = video_path
    except Exception as e:
        print(f"-> Duration: loop error {e}, using original")
        output_path = video_path
    finally:
        try:
            os.unlink(concat_path)
        except OSError:
            pass

    return output_path


def _slow_video(video_path: str, speed_factor: float, output_path: str) -> str:
    """Slow a video using the setpts filter."""
    pts_factor = 1.0 / speed_factor
    atempo = min(speed_factor, 2.0)

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path,
             "-filter:v", f"setpts={pts_factor}*PTS",
             "-filter:a", f"atempo={atempo}",
             output_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            print(f"-> Duration: slowed video by {speed_factor:.2f}x")
        else:
            print(f"-> Duration: slow failed, using original")
            output_path = video_path
    except Exception as e:
        print(f"-> Duration: slow error {e}, using original")
        output_path = video_path

    return output_path
