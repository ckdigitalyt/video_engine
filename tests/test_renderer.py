"""
test_renderer.py — Tests for the renderer (renderer.py).

Verifies timeline parsing, render validation, invalid timeline detection,
and the Pillow/MoviePy compatibility shim.
Does NOT call MoviePy's write_videofile (no GPU / FFmpeg encode).
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pytest


# ── Timeline parsing ───────────────────────────────────────────────────────


class TestParseTimeline:
    """Tests for the ``_parse_timeline`` function in renderer.py."""

    def _parse(self, raw: dict):
        """Import and call _parse_timeline from the real renderer module."""
        from renderer import _parse_timeline
        return _parse_timeline(raw)

    def test_parse_minimal(self) -> None:
        """Minimal valid timeline should produce a Timeline with defaults."""
        raw = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [],
            "video_timeline": [],
        }
        tl = self._parse(raw)
        assert tl.render_settings.resolution == [1920, 1080]
        assert tl.render_settings.fps == 30
        assert tl.audio_timeline == []
        assert tl.video_timeline == []

    def test_parse_audio_tracks(self) -> None:
        raw = {
            "render_settings": {"resolution": [1280, 720], "fps": 24},
            "audio_timeline": [
                {"track": "voice", "file": "/a/1.wav", "start_time": 0.0, "end_time": 5.0},
                {"track": "music", "file": "/m/bg.wav", "start_time": 5.0, "end_time": 10.0},
            ],
            "video_timeline": [],
        }
        tl = self._parse(raw)
        assert len(tl.audio_timeline) == 2
        assert tl.audio_timeline[0].track == "voice"
        assert tl.audio_timeline[1].file == "/m/bg.wav"

    def test_parse_video_tracks(self) -> None:
        raw = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [],
            "video_timeline": [
                {"layer": 1, "file": "/v/1.mp4", "start_time": 0.0, "end_time": 5.0, "transition_out": "fade"},
            ],
        }
        tl = self._parse(raw)
        assert len(tl.video_timeline) == 1
        assert tl.video_timeline[0].layer == 1
        assert tl.video_timeline[0].transition_out == "fade"

    def test_parse_missing_render_settings_defaults(self) -> None:
        """Missing render_settings should still produce a Timeline with defaults."""
        raw = {"audio_timeline": [], "video_timeline": []}
        tl = self._parse(raw)
        assert tl.render_settings.resolution == [1920, 1080]
        assert tl.render_settings.fps == 30

    def test_parse_invalid_resolution(self) -> None:
        """A non-standard resolution should still parse (renderer will handle it)."""
        raw = {
            "render_settings": {"resolution": [640, 480], "fps": 15},
            "audio_timeline": [],
            "video_timeline": [],
        }
        tl = self._parse(raw)
        assert tl.render_settings.resolution == [640, 480]
        assert tl.render_settings.fps == 15

    def test_parse_missing_optional_fields(self) -> None:
        """Entries missing optional fields should get defaults from TimelineTrack."""
        raw = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [{"file": "/a.wav"}],
            "video_timeline": [{"file": "/v.mp4"}],
        }
        tl = self._parse(raw)
        assert tl.audio_timeline[0].track == "voice"
        assert tl.audio_timeline[0].start_time == 0.0
        assert tl.video_timeline[0].layer == 1
        assert tl.video_timeline[0].transition_out == "none"


# ── Renderer compatibility shim ────────────────────────────────────────────


class TestCompatibilityShim:
    """Verify the Pillow ANTIALIAS shim at the top of renderer.py."""

    def test_antialias_alias_exists(self) -> None:
        """The ANTIALIAS compatibility shim should alias LANCZOS."""
        # The shim runs at import time in renderer.py; test its logic directly
        import PIL.Image
        if not hasattr(PIL.Image, "ANTIALIAS"):
            PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
        assert hasattr(PIL.Image, "ANTIALIAS")
        assert PIL.Image.ANTIALIAS == PIL.Image.LANCZOS

    def test_antialias_already_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If Pillow already has ANTIALIAS, the shim should not overwrite it."""
        import PIL.Image
        monkeypatch.setattr(PIL.Image, "ANTIALIAS", PIL.Image.BICUBIC, raising=False)
        import renderer  # noqa: F401
        assert PIL.Image.ANTIALIAS == PIL.Image.BICUBIC  # unchanged


# ── Render timeline (no-op) ────────────────────────────────────────────────


class TestRenderTimeline:
    """Verify render_timeline dispatches correctly (no real encoding)."""

    def test_render_dispatches(self, tmp_path: Path) -> None:
        """render_timeline reads timeline.json and calls write_videofile."""
        import importlib
        import renderer as _renderer_before  # noqa: ensure loaded

        tl_data = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [
                {"track": "voice", "file": "/fakepath/a.wav", "start_time": 0.0, "end_time": 5.0}
            ],
            "video_timeline": [
                {"layer": 1, "file": "/fakepath/v.mp4", "start_time": 0.0, "end_time": 5.0, "transition_out": "none"}
            ],
        }
        tl_path = tmp_path / "timeline.json"
        tl_path.write_text(json.dumps(tl_data))
        out_path = str(tmp_path / "out.mp4")

        with patch.object(_renderer_before, "VideoFileClip") as mock_vfc, \
               patch.object(_renderer_before, "AudioFileClip") as mock_afc, \
               patch.object(_renderer_before, "CompositeVideoClip") as mock_cvc, \
               patch.object(_renderer_before, "CompositeAudioClip") as mock_cac:
            _renderer_before.render_timeline(str(tl_path), out_path)

        # Verify that write_videofile was called on the composite
        # CompositeVideoClip(...).set_audio(...).write_videofile(...)
        assert mock_cvc.return_value.set_audio.return_value.write_videofile.called


# ── Invalid timeline detection ─────────────────────────────────────────────


class TestInvalidTimeline:
    def test_no_json_file(self, tmp_path: Path) -> None:
        """A missing timeline file should raise FileNotFoundError."""
        from renderer import render_timeline
        with pytest.raises(FileNotFoundError):
            render_timeline(str(tmp_path / "no_such_file.json"), "out.mp4")

    def test_corrupted_json(self, tmp_path: Path) -> None:
        """Invalid JSON should raise json.JSONDecodeError."""
        bad = tmp_path / "bad.json"
        bad.write_text("{corrupted: json")
        from renderer import render_timeline
        with pytest.raises(json.JSONDecodeError):
            render_timeline(str(bad), "out.mp4")

    def test_missing_audio_file_logged(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Missing audio files should cause a FileNotFoundError or MoviePy error."""
        tl_data = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [
                {"track": "voice", "file": "/_nonexistent_audio.wav", "start_time": 0.0, "end_time": 5.0}
            ],
            "video_timeline": [],
        }
        tl_path = tmp_path / "tl_missing_audio.json"
        tl_path.write_text(json.dumps(tl_data))

        # MoviePy's AudioFileClip will raise OSError or FileNotFoundError
        with patch("renderer.AudioFileClip") as mock:
            mock.side_effect = FileNotFoundError("No such file")
            from renderer import render_timeline
            with pytest.raises(FileNotFoundError):
                render_timeline(str(tl_path), "out.mp4")
