"""
transition_cache.py — Pre-rendered Transition Cache.

At planning time, detects all unique transition pairs between adjacent
video clips. Pre-renders transitions as separate short clips before the
main render. During final assembly, the video is built by concatenating:

    clip1 → transition_cache_entry → clip2

This saves ~15-20s per crossfade during the main render because MoviePy
no longer needs to composite overlapping frames for transitions.

The cache is keyed by (prev_filepath, next_filepath, transition_type, duration).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple


class TransitionCache:
    """Manages pre-rendered transition clips.

    Usage::

        cache = TransitionCache(cache_dir="cache/transitions")
        cache.detect_unique_pairs(video_timeline)
        cache.prerender_all(target_resolution=(1920, 1080), fps=30)
        assembly = cache.assemble(video_timeline)
    """

    def __init__(self, cache_dir: str = "cache/transitions"):
        self._cache_dir = cache_dir
        os.makedirs(self._cache_dir, exist_ok=True)

        # Detected unique pairs: set of (prev_file, next_file, ttype, dur)
        self._pairs: set[Tuple[str, str, str, float]] = set()

        # Rendered cache key -> filepath mapping
        self._rendered: Dict[str, str] = {}

    # ── Public API ─────────────────────────────────────────────────────

    def detect_unique_pairs(self, video_timeline: List[dict]) -> int:
        """Scan video_timeline and detect all unique transition pairs.

        Args:
            video_timeline: List of video timeline entries with:
                - file: str (filepath)
                - transition: str (transition type)

        Returns:
            Number of unique pairs found.
        """
        self._pairs.clear()

        for i in range(1, len(video_timeline)):
            prev_file = video_timeline[i - 1].get("file", "")
            next_file = video_timeline[i].get("file", "")
            ttype = video_timeline[i].get("transition", video_timeline[i].get("transition_out", "cut_sync"))
            duration = 0.5  # Default transition duration

            if not prev_file or not next_file:
                continue
            if ttype in ("cut", "cut_sync", "none"):
                continue  # No need to pre-render instant cuts

            self._pairs.add((prev_file, next_file, ttype, duration))

        return len(self._pairs)

    def prerender_all(
        self,
        target_resolution: Tuple[int, int] = (1920, 1080),
        fps: int = 30,
    ) -> Dict[str, str]:
        """Pre-render all unique transition pairs as separate short clips.

        Uses ffmpeg for fast crossfade rendering.

        Args:
            target_resolution: Output resolution (width, height).
            fps: Output frame rate.

        Returns:
            Dict mapping cache_key -> filepath of pre-rendered transition.
        """
        self._rendered.clear()

        for prev_file, next_file, ttype, duration in self._pairs:
            cache_key = self._make_cache_key(prev_file, next_file, ttype, duration)
            output_path = os.path.join(self._cache_dir, f"{cache_key}.mp4")

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                # Already cached
                self._rendered[cache_key] = output_path
                continue

            if ttype in ("crossfade", "dissolve"):
                self._render_crossfade(prev_file, next_file, output_path, duration, target_resolution, fps)
            elif ttype == "fade":
                self._render_fade(prev_file, next_file, output_path, duration, target_resolution, fps)
            elif ttype == "dip_to_black":
                self._render_dip_to_black(prev_file, output_path, duration, target_resolution, fps)
            else:
                # Fallback: simple cut
                self._render_crossfade(prev_file, next_file, output_path, duration, target_resolution, fps)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                self._rendered[cache_key] = output_path
            else:
                print(f"  [TransitionCache] Failed to render transition: {cache_key}")

        return dict(self._rendered)

    def assemble(self, video_timeline: List[dict]) -> List[dict]:
        """Assemble a new video timeline using pre-rendered transition clips.

        Replaces the transition logic with explicit clip → transition → clip
        concatenation. Each transition entry has:
            - file: str (pre-rendered transition filepath)
            - start_time: float
            - end_time: float
            - is_transition: True

        Args:
            video_timeline: Original video timeline entries.

        Returns:
            Flattened timeline with transition clips inserted.
        """
        assembled: List[dict] = []

        for i, entry in enumerate(video_timeline):
            assembled.append(entry)

            if i < len(video_timeline) - 1:
                next_entry = video_timeline[i + 1]
                prev_file = entry.get("file", "")
                next_file = next_entry.get("file", "")
                ttype = next_entry.get("transition", next_entry.get("transition_out", "cut_sync"))
                duration = 0.5

                if ttype in ("cut", "cut_sync", "none") or not prev_file or not next_file:
                    continue

                cache_key = self._make_cache_key(prev_file, next_file, ttype, duration)
                cached_path = self._rendered.get(cache_key)

                if cached_path and os.path.exists(cached_path):
                    # Insert transition clip between entry and next_entry
                    # Position it at the end of the current entry
                    trans_start = entry.get("end_time", entry.get("start_time", 0) + 3)
                    trans_end = trans_start + duration
                    assembled.append({
                        "layer": 1,
                        "file": cached_path,
                        "start_time": trans_start,
                        "end_time": trans_end,
                        "transition": ttype,
                        "is_transition": True,
                        "motion": "none",
                        "camera": "static",
                    })

        return assembled

    def get_cache_stats(self) -> Dict[str, Any]:
        """Report cache statistics."""
        total_pairs = len(self._pairs)
        cached = len([p for p in self._rendered.values() if os.path.exists(p)])
        size_bytes = sum(
            os.path.getsize(p) for p in self._rendered.values() if os.path.exists(p)
        )
        return {
            "unique_pairs": total_pairs,
            "cached": cached,
            "cache_size_mb": round(size_bytes / (1024 * 1024), 2),
            "cache_dir": self._cache_dir,
        }

    # ── Internal ──────────────────────────────────────────────────────

    @staticmethod
    def _make_cache_key(prev_file: str, next_file: str, ttype: str, duration: float) -> str:
        """Create deterministic cache key from transition pair."""
        raw = f"{prev_file}:{next_file}:{ttype}:{duration}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _render_crossfade(
        prev_file: str,
        next_file: str,
        output_path: str,
        duration: float,
        resolution: Tuple[int, int],
        fps: int,
    ) -> None:
        """Pre-render a crossfade between two clips using ffmpeg."""
        width, height = resolution
        # ffmpeg crossfade filter: overlay first clip's tail with second clip's head
        cmd = [
            "ffmpeg", "-y",
            "-i", prev_file,
            "-i", next_file,
            "-filter_complex",
            f"[0:v]format=pix_fmts=yuva420p,fade=t=out:st={max(0, 3-duration)}:d={duration}:alpha=1[v0];"
            f"[1:v]format=pix_fmts=yuva420p,fade=t=in:st=0:d={duration}:alpha=1[v1];"
            f"[v0][v1]overlay=format=auto,scale={width}:{height},fps={fps}[v]",
            "-map", "[v]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-an",
            "-shortest",
            output_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception as e:
            print(f"  [TransitionCache] ffmpeg crossfade error: {e}")

    @staticmethod
    def _render_fade(
        prev_file: str,
        next_file: str,
        output_path: str,
        duration: float,
        resolution: Tuple[int, int],
        fps: int,
    ) -> None:
        """Pre-render a fade-to-black + fade-in transition."""
        width, height = resolution
        cmd = [
            "ffmpeg", "-y",
            "-i", prev_file,
            "-i", next_file,
            "-filter_complex",
            f"[0:v]fade=t=out:st={max(0, 3-duration)}:d={duration}:color=black[v0];"
            f"[1:v]fade=t=in:st=0:d={duration}:color=black[v1];"
            f"[v0][v1]concat=n=2:v=1:a=0,scale={width}:{height},fps={fps}[v]",
            "-map", "[v]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception as e:
            print(f"  [TransitionCache] ffmpeg fade error: {e}")

    @staticmethod
    def _render_dip_to_black(
        prev_file: str,
        output_path: str,
        duration: float,
        resolution: Tuple[int, int],
        fps: int,
    ) -> None:
        """Pre-render a dip-to-black transition (fade out previous clip only)."""
        width, height = resolution
        cmd = [
            "ffmpeg", "-y",
            "-i", prev_file,
            "-filter_complex",
            f"[0:v]fade=t=out:st={max(0, 3-duration)}:d={duration}:color=black,"
            f"scale={width}:{height},fps={fps}[v]",
            "-map", "[v]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-an",
            "-t", str(duration + 0.5),
            output_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception as e:
            print(f"  [TransitionCache] ffmpeg dip_to_black error: {e}")
