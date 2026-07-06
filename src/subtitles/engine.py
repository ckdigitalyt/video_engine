"""
engine.py — Word-level subtitle engine for the video_engine pipeline.

Uses silence detection on the narration audio (via pydub) to estimate
word-level timing, then produces SRT, WebVTT, or internal JSON subtitle
timelines.

Design is renderer-agnostic: the output is a plain list of word-timing
dicts that any renderer can consume.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

from pydub import AudioSegment
from pydub.silence import detect_silence, split_on_silence

from src.utils.config import get_config
from .animation import get_animation_clips


# ── Public API ────────────────────────────────────────────────────────────


class SubtitleEngine:
    """Generates word-level subtitle timing from a narration audio file.

    Parameters
    ----------
    enabled : bool, optional
        Override for ``subtitles.enabled`` config.  Default True.
    max_words_per_line : int, optional
        Maximum words per subtitle line.  Default 4.
    min_silence_ms : int, optional
        Minimum silence (ms) to treat as a phrase boundary.  Default 200.
    silence_thresh : int, optional
        Silence threshold in dBFS.  Default -40.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        max_words_per_line: Optional[int] = None,
        min_silence_ms: Optional[int] = None,
        silence_thresh: Optional[int] = None,
    ):
        self._enabled = enabled if enabled is not None else get_config(
            "subtitles.enabled", True
        )
        self._max_words_per_line = max_words_per_line if max_words_per_line is not None else get_config(
            "subtitles.max_words_per_line", 4
        )
        self._min_silence_ms = min_silence_ms if min_silence_ms is not None else get_config(
            "subtitles.min_silence_ms", 200
        )
        self._silence_thresh = silence_thresh if silence_thresh is not None else get_config(
            "subtitles.silence_thresh", -40
        )
        self._font_size = get_config("subtitles.font_size", 28)
        self._bottom_margin = get_config("subtitles.bottom_margin", 80)
        self._color = get_config("subtitles.color", "#FFFFFF")
        self._outline = get_config("subtitles.outline", "#000000")
        self._shadow = get_config("subtitles.shadow", "#000000")
        self._animation_style = get_config("subtitles.animation", "fade")
        self._resolution: tuple[int, int] = (1920, 1080)

    # ── Main generation ────────────────────────────────────────────────

    def generate(
        self,
        audio_path: str,
        text: str,
        resolution: Optional[tuple[int, int]] = None,
    ) -> list[dict[str, Any]]:
        """Generate word-level subtitle timing from narration audio.

        Returns a list of word-timing entries::

            [
                {
                    "word": str,
                    "start_ms": float,
                    "end_ms": float,
                    "line": int,
                    "is_first_in_line": bool,
                    "is_last_in_line": bool,
                },
                ...
            ]

        If subtitles are disabled, returns an empty list.
        """
        if not self._enabled:
            return []

        if not os.path.exists(audio_path) or not text.strip():
            return []

        if resolution is not None:
            self._resolution = resolution

        words = text.strip().split()
        if not words:
            return []

        # ── Generate raw word timing from audio ────────────────────────
        raw_timing = self._generate_word_timing(audio_path, words)

        # ── Group into lines ───────────────────────────────────────────
        lined_timing = self._assign_lines(raw_timing)

        return lined_timing

    # ── Format helpers ─────────────────────────────────────────────────

    def to_srt(self, timing: list[dict[str, Any]]) -> str:
        """Convert word-level timing to SRT format string."""
        if not timing:
            return ""
        lines = self._merge_into_lines(timing)
        return self._format_srt(lines)

    def to_vtt(self, timing: list[dict[str, Any]]) -> str:
        """Convert word-level timing to WebVTT format string."""
        if not timing:
            return ""
        lines = self._merge_into_lines(timing)
        return self._format_vtt(lines)

    def to_json(self, timing: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return the internal timing as plain JSON-serializable data."""
        return timing

    def to_renderer_clips(self, timing: list[dict[str, Any]]) -> list[dict]:
        """Produce renderer-compatible clip descriptions with animation."""
        return get_animation_clips(
            words=timing,
            style=self._animation_style,
            font_size=self._font_size,
            bottom_margin=self._bottom_margin,
            max_words_per_line=self._max_words_per_line,
            resolution=self._resolution,
        )

    # ── Timing: silence-based word estimation ──────────────────────────

    def _generate_word_timing(
        self,
        audio_path: str,
        words: list[str],
    ) -> list[dict[str, Any]]:
        """Generate per-word timing using silence detection on the audio."""
        audio = AudioSegment.from_wav(audio_path)
        duration_ms = len(audio)
        total_words = len(words)

        if total_words == 0:
            return []

        # Detect silent segments to find phrase boundaries
        silent_ranges = detect_silence(
            audio,
            min_silence_len=self._min_silence_ms,
            silence_thresh=self._silence_thresh,
        )

        # Build non-silent (voice) segments
        voice_segments: list[tuple[float, float]] = []
        prev_end = 0.0
        for start_s, end_s in silent_ranges:
            if start_s > prev_end:
                voice_segments.append((prev_end, float(start_s)))
            prev_end = float(end_s)
        if prev_end < duration_ms:
            voice_segments.append((prev_end, float(duration_ms)))

        # If no voice segments detected (very short/quiet audio),
        # distribute words evenly across the full duration
        if not voice_segments:
            return self._distribute_evenly(words, duration_ms)

        # Distribute words proportionally across voice segments
        total_voice_ms = sum(e - s for s, e in voice_segments)
        word_idx = 0
        timings: list[dict[str, Any]] = []

        for start_ms, end_ms in voice_segments:
            seg_dur = end_ms - start_ms
            # How many words fall in this segment
            seg_word_count = max(
                1,
                round(seg_dur / total_voice_ms * total_words),
            )
            seg_words = words[word_idx : word_idx + seg_word_count]
            if not seg_words:
                continue

            if len(seg_words) == 1:
                timings.append({
                    "word": seg_words[0],
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                })
            else:
                word_dur = seg_dur / len(seg_words)
                for i, w in enumerate(seg_words):
                    timings.append({
                        "word": w,
                        "start_ms": start_ms + i * word_dur,
                        "end_ms": start_ms + (i + 1) * word_dur,
                    })

            word_idx += len(seg_words)

        # Handle any remaining words (off-by-one rounding)
        if word_idx < total_words:
            remaining = words[word_idx:]
            last_end = timings[-1]["end_ms"] if timings else 0.0
            remaining_dur = max(duration_ms - last_end, 50)
            avg = remaining_dur / len(remaining)
            for i, w in enumerate(remaining):
                start = last_end + i * avg
                timings.append({
                    "word": w,
                    "start_ms": start,
                    "end_ms": start + avg,
                })

        return timings

    def _distribute_evenly(
        self,
        words: list[str],
        duration_ms: float,
    ) -> list[dict[str, Any]]:
        """Fallback: distribute words evenly across the full duration."""
        avg = duration_ms / len(words)
        timings: list[dict[str, Any]] = []
        for i, w in enumerate(words):
            timings.append({
                "word": w,
                "start_ms": i * avg,
                "end_ms": (i + 1) * avg,
            })
        return timings

    # ── Line grouping ──────────────────────────────────────────────────

    def _assign_lines(
        self,
        timings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Group consecutive words into lines."""
        result: list[dict[str, Any]] = []
        line_idx = 0
        for i, entry in enumerate(timings):
            pos_in_line = i % self._max_words_per_line
            if pos_in_line == 0 and i > 0:
                line_idx += 1
            entry["line"] = line_idx
            entry["is_first_in_line"] = pos_in_line == 0
            entry["is_last_in_line"] = (
                pos_in_line == self._max_words_per_line - 1
                or i == len(timings) - 1
            )
            result.append(entry)
        return result

    # ── Line merging for SRT/VTT ───────────────────────────────────────

    def _merge_into_lines(
        self,
        timing: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge word entries into subtitle lines (phrase-level)."""
        if not timing:
            return []

        lines: list[dict[str, Any]] = []
        current_line: list[str] = []
        line_start = timing[0]["start_ms"]
        line_end = timing[0]["end_ms"]

        for entry in timing:
            current_line.append(entry["word"])
            line_end = entry["end_ms"]
            if entry.get("is_last_in_line", False):
                lines.append({
                    "text": " ".join(current_line),
                    "start_ms": line_start,
                    "end_ms": line_end,
                    "line": entry.get("line", 0),
                })
                current_line = []
                line_start = timing[-1]["end_ms"] if lines else entry["end_ms"]

        # Flush remaining words
        if current_line:
            lines.append({
                "text": " ".join(current_line),
                "start_ms": line_start,
                "end_ms": timing[-1]["end_ms"],
                "line": timing[-1].get("line", 0),
            })

        # Assign sequential line numbers
        for i, line in enumerate(lines):
            line["index"] = i + 1

        return lines

    # ── SRT / VTT formatting ───────────────────────────────────────────

    @staticmethod
    def _format_srt(lines: list[dict[str, Any]]) -> str:
        """Produce SRT format string from merged lines."""
        chunks: list[str] = []
        for line in lines:
            idx = line.get("index", 1)
            start = SubtitleEngine._ms_to_srt(line["start_ms"])
            end = SubtitleEngine._ms_to_srt(line["end_ms"])
            chunks.append(f"{idx}\n{start} --> {end}\n{line['text']}\n")
        return "\n".join(chunks)

    @staticmethod
    def _format_vtt(lines: list[dict[str, Any]]) -> str:
        """Produce WebVTT format string from merged lines."""
        chunks: list[str] = ["WEBVTT\n"]
        for line in lines:
            start = SubtitleEngine._ms_to_vtt(line["start_ms"])
            end = SubtitleEngine._ms_to_vtt(line["end_ms"])
            chunks.append(f"{start} --> {end}\n{line['text']}\n")
        return "\n".join(chunks)

    @staticmethod
    def _ms_to_srt(ms: float) -> str:
        """Convert milliseconds to SRT time format HH:MM:SS,mmm."""
        total_sec = ms / 1000.0
        h = int(total_sec // 3600)
        m = int((total_sec % 3600) // 60)
        s = int(total_sec % 60)
        mill = int(ms % 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{mill:03d}"

    @staticmethod
    def _ms_to_vtt(ms: float) -> str:
        """Convert milliseconds to WebVTT time format HH:MM:SS.mmm."""
        total_sec = ms / 1000.0
        h = int(total_sec // 3600)
        m = int((total_sec % 3600) // 60)
        s = int(total_sec % 60)
        mill = int(ms % 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{mill:03d}"
