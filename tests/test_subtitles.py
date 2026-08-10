"""
test_subtitles.py — Tests for the subtitle engine, formats, animation, and renderer integration.

Verifies:
- SubtitleEngine.generate() produces word-level timing from audio
- Even distribution fallback when silence detection yields no segments
- SRT formatting
- WebVTT formatting
- JSON output
- Line wrapping (max_words_per_line)
- Long narration handling
- Disabled mode returns empty list
- Animation styles resolve correctly
- Renderer integration (subtitle clips passed to MoviePyRenderer)
- Configuration parsing
"""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.subtitles import SubtitleEngine, get_animation_clips
from src.subtitles.engine import SubtitleEngine as SE
from src.subtitles.animation import (
    ANIMATION_STYLES,
    DEFAULT_STYLE,
    get_animation_style,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> SubtitleEngine:
    """Engine with default settings, enabled."""
    return SubtitleEngine(enabled=True, max_words_per_line=4, min_silence_ms=50, silence_thresh=-60)


@pytest.fixture
def engine_disabled() -> SubtitleEngine:
    """Engine with subtitles disabled."""
    return SubtitleEngine(enabled=False)


@pytest.fixture
def short_wav(tmp_path: Path) -> Path:
    """Generate a short non-silent WAV for timing tests."""
    import wave, struct
    path = tmp_path / "short.wav"
    sample_rate = 44100
    num_samples = int(sample_rate * 0.3)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(num_samples):
            wf.writeframes(struct.pack("<h", 5000))
    return path


@pytest.fixture
def long_silent_wav(tmp_path: Path) -> Path:
    """Generate a mostly-silent WAV (triggers even-distribution fallback)."""
    import wave, struct
    path = tmp_path / "silent.wav"
    sample_rate = 44100
    num_samples = int(sample_rate * 1.0)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(num_samples):
            wf.writeframes(struct.pack("<h", 0))  # silence
    return path


# ── Basic generation ──────────────────────────────────────────────────────


class TestGenerate:
    def test_disabled_returns_empty(self, engine_disabled: SubtitleEngine, short_wav: Path) -> None:
        result = engine_disabled.generate(str(short_wav), "Hello world")
        assert result == []

    def test_missing_audio_file(self, engine: SubtitleEngine) -> None:
        result = engine.generate("/no/such/file.wav", "test")
        assert result == []

    def test_empty_text(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "")
        assert result == []

    def test_generates_word_entries(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "Hello world from subtitles")
        assert len(result) == 4
        words = [e["word"] for e in result]
        assert words == ["Hello", "world", "from", "subtitles"]

    def test_every_word_has_timing(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "one two three")
        for entry in result:
            assert "start_ms" in entry
            assert "end_ms" in entry
            assert entry["end_ms"] > entry["start_ms"]

    def test_monotonic_timestamps(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "a b c d e f")
        for i in range(1, len(result)):
            assert result[i]["start_ms"] >= result[i - 1]["end_ms"]

    def test_line_assignment(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "w1 w2 w3 w4 w5 w6")
        lines = {e["line"] for e in result}
        assert len(lines) >= 1
        # First line should have max_words_per_line words
        first_line_words = [e for e in result if e["line"] == 0]
        assert len(first_line_words) <= 4  # max_words_per_line

    def test_is_first_last_in_line(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "alpha beta gamma delta epsilon")
        assert result[0]["is_first_in_line"] is True
        # word at position 4 should be first in next line
        assert result[4]["is_first_in_line"] is True
        # word at position 3 should be last in line 0
        assert result[3]["is_last_in_line"] is True

    def test_even_distribution_fallback(self, engine: SubtitleEngine, long_silent_wav: Path) -> None:
        """When silence detection finds no voice segments, words are distributed evenly."""
        result = engine.generate(str(long_silent_wav), "a b c d e")
        assert len(result) == 5
        assert result[-1]["end_ms"] <= 1050  # within ~1 sec total


# ── SRT format ────────────────────────────────────────────────────────────


class TestSrtFormat:
    def test_empty_timing_produces_empty_string(self, engine: SubtitleEngine) -> None:
        assert engine.to_srt([]) == ""

    def test_produces_srt_format(self, engine: SubtitleEngine, short_wav: Path) -> None:
        timing = engine.generate(str(short_wav), "Hello world")
        srt = engine.to_srt(timing)
        assert "WEBVTT" not in srt
        assert "-->" in srt
        assert srt.strip().startswith("1")
        assert "Hello" in srt
        assert "world" in srt

    def test_time_format_correct(self) -> None:
        """Verify HH:MM:SS,mmm format."""
        srt_time = SE._ms_to_srt(3661000)  # 1h 1m 1s
        assert srt_time == "01:01:01,000"
        srt_time = SE._ms_to_srt(1250)
        assert srt_time == "00:00:01,250"
        srt_time = SE._ms_to_srt(0)
        assert srt_time == "00:00:00,000"


# ── WebVTT format ─────────────────────────────────────────────────────────


class TestVttFormat:
    def test_empty_timing_produces_empty_string(self, engine: SubtitleEngine) -> None:
        assert engine.to_vtt([]) == ""

    def test_produces_vtt_format(self, engine: SubtitleEngine, short_wav: Path) -> None:
        timing = engine.generate(str(short_wav), "Hello world")
        vtt = engine.to_vtt(timing)
        assert vtt.startswith("WEBVTT")
        assert "-->" in vtt
        assert "Hello" in vtt

    def test_time_format_correct(self) -> None:
        vtt_time = SE._ms_to_vtt(3661000)
        assert vtt_time == "01:01:01.000"
        vtt_time = SE._ms_to_vtt(1250)
        assert vtt_time == "00:00:01.250"


# ── JSON format ───────────────────────────────────────────────────────────


class TestJsonFormat:
    def test_json_roundtrip(self, engine: SubtitleEngine, short_wav: Path) -> None:
        timing = engine.generate(str(short_wav), "three word test")
        serialized = json.dumps(timing)
        deserialized = json.loads(serialized)
        assert len(deserialized) == 3
        assert deserialized[0]["word"] == "three"


# ── Renderer clips ────────────────────────────────────────────────────────


class TestRendererClips:
    def test_clips_have_all_keys(self, engine: SubtitleEngine, short_wav: Path) -> None:
        timing = engine.generate(str(short_wav), "test clips here")
        clips = engine.to_renderer_clips(timing)
        for clip in clips:
            assert "text" in clip
            assert "start_ms" in clip
            assert "end_ms" in clip
            assert "font_size" in clip
            assert "animation" in clip
            assert "opacity" in clip

    def test_clip_count_matches_words(self, engine: SubtitleEngine, short_wav: Path) -> None:
        timing = engine.generate(str(short_wav), "a b c")
        clips = engine.to_renderer_clips(timing)
        # v19n: words are grouped into PHRASE clips (max_words_per_line=4),
        # so 3 words → 1 phrase clip containing all three.
        assert len(clips) == 1
        assert clips[0]["text"] == "a b c"

    def test_long_line_splits_into_phrase_clips(self, engine: SubtitleEngine, short_wav: Path) -> None:
        # 6 words with max_words_per_line=4 → 2 phrase clips.
        timing = engine.generate(str(short_wav), "one two three four five six")
        clips = engine.to_renderer_clips(timing)
        assert len(clips) == 2
        assert clips[0]["text"] == "one two three four"
        assert clips[1]["text"] == "five six"


# ── Animation ─────────────────────────────────────────────────────────────


class TestAnimation:
    def test_default_style_exists(self) -> None:
        assert DEFAULT_STYLE in ANIMATION_STYLES

    def test_all_styles_registered(self) -> None:
        for name in ("static", "fade", "karaoke", "pop"):
            assert name in ANIMATION_STYLES

    def test_get_animation_style_valid(self) -> None:
        fn = get_animation_style("fade")
        assert callable(fn)

    def test_get_animation_style_invalid_falls_back(self) -> None:
        fn = get_animation_style("no_such_style")
        assert callable(fn)
        assert fn == ANIMATION_STYLES[DEFAULT_STYLE]

    def test_static_animation(self) -> None:
        from src.subtitles.animation import _static
        words = [
            {"word": "hi", "start_ms": 0.0, "end_ms": 100.0},
        ]
        result = _static(words)
        assert result[0]["anim_opacity"] == 1.0

    def test_fade_animation_adds_fade_fields(self) -> None:
        from src.subtitles.animation import _fade
        words = [
            {"word": "hi", "start_ms": 0.0, "end_ms": 500.0},
        ]
        result = _fade(words)
        assert "fade_in_ms" in result[0]
        assert "fade_out_ms" in result[0]
        assert result[0]["fade_in_ms"] > 0

    def test_karaoke_animation(self) -> None:
        from src.subtitles.animation import _karaoke
        words = [
            {"word": "a", "start_ms": 0.0, "end_ms": 200.0},
            {"word": "b", "start_ms": 200.0, "end_ms": 400.0},
        ]
        result = _karaoke(words)
        assert "prev_dim" in result[0]
        assert result[0]["prev_dim"] == 0.35

    def test_pop_animation(self) -> None:
        from src.subtitles.animation import _pop
        words = [
            {"word": "boom", "start_ms": 0.0, "end_ms": 300.0},
        ]
        result = _pop(words)
        assert "pop_scale" in result[0]
        assert result[0]["pop_scale"] > 1.0

    def test_get_animation_clips_produces_valid_clips(self) -> None:
        from src.subtitles.animation import get_animation_clips
        words = [
            {"word": "hello", "start_ms": 0.0, "end_ms": 200.0, "line": 0,
             "is_first_in_line": True, "is_last_in_line": True},
        ]
        clips = get_animation_clips(words, "fade", 28, 80, 4, (1920, 1080))
        assert len(clips) == 1
        assert clips[0]["text"] == "hello"
        assert clips[0]["animation"] == "fade"


# ── Renderer integration ─────────────────────────────────────────────────


class TestRendererIntegration:
    def test_renderer_accepts_subtitles(self, tmp_path: Path, short_video: Path) -> None:
        """MoviePyRenderer.render() accepts an optional subtitles param."""
        from src.renderer.moviepy_renderer import MoviePyRenderer

        # Create a timeline with one short video clip
        timeline = tmp_path / "mini.json"
        timeline.write_text(json.dumps({
            "render_settings": {"resolution": [160, 120], "fps": 10},
            "audio_timeline": [],
            "video_timeline": [
                {"layer": 1, "file": str(short_video),
                 "start_time": 0.0, "end_time": 1.0, "transition_out": "none"}
            ],
        }))

        output = tmp_path / "mini.mp4"
        r = MoviePyRenderer()
        r.render(str(timeline), str(output), subtitles=[])
        assert output.exists()

    def test_renderer_without_subtitles(self, tmp_path: Path, short_video: Path) -> None:
        """Renderer works when subtitles=None (backward compat)."""
        from src.renderer.moviepy_renderer import MoviePyRenderer

        timeline = tmp_path / "mini2.json"
        timeline.write_text(json.dumps({
            "render_settings": {"resolution": [160, 120], "fps": 10},
            "audio_timeline": [],
            "video_timeline": [
                {"layer": 1, "file": str(short_video),
                 "start_time": 0.0, "end_time": 1.0, "transition_out": "none"}
            ],
        }))

        output = tmp_path / "mini2.mp4"
        r = MoviePyRenderer()
        r.render(str(timeline), str(output))  # no subtitles param
        assert output.exists()

    def test_renderer_abc_signature(self) -> None:
        """Renderer ABC accepts optional subtitles param."""
        from src.renderer import Renderer
        import inspect
        sig = inspect.signature(Renderer.render)
        assert "subtitles" in sig.parameters
        param = sig.parameters["subtitles"]
        assert param.default is None


# ── Edge cases ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_very_long_narration(self, engine: SubtitleEngine, tmp_path: Path) -> None:
        """Long text should still produce correctly grouped subtitles."""
        import wave, struct
        path = tmp_path / "long.wav"
        sample_rate = 44100
        num_samples = int(sample_rate * 2.0)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for _ in range(num_samples):
                wf.writeframes(struct.pack("<h", 3000))

        words = " ".join([f"word{i}" for i in range(50)])
        result = engine.generate(str(path), words)
        assert len(result) == 50
        # Should have multiple lines
        lines = {e["line"] for e in result}
        assert len(lines) > 1

    def test_single_word(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "single")
        assert len(result) == 1
        assert result[0]["word"] == "single"

    def test_two_words_same_line(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "two words")
        assert len(result) == 2
        assert result[0]["line"] == result[1]["line"]

    def test_disabled_even_with_audio(self, engine_disabled: SubtitleEngine, short_wav: Path) -> None:
        result = engine_disabled.generate(str(short_wav), "Should be empty")
        assert result == []

    def test_resolution_parameter(self, engine: SubtitleEngine, short_wav: Path) -> None:
        result = engine.generate(str(short_wav), "test res", resolution=(640, 480))
        assert len(result) == 2


# ── Config mapping ────────────────────────────────────────────────────────


class TestConfig:
    def test_default_config_keys_exist(self, tmp_project: Path) -> None:
        """Verify config file has all required subtitle keys."""
        from src.utils.config import get_config
        assert get_config("subtitles.enabled") is True
        assert get_config("subtitles.font_size") == 28
        assert get_config("subtitles.max_words_per_line") == 4
        assert get_config("subtitles.animation") == "fade"
        assert get_config("subtitles.min_silence_ms") == 200
        assert get_config("subtitles.silence_thresh") == -40
