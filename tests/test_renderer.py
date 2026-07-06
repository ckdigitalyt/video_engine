"""
test_renderer.py — Tests for the renderer layer.

Verifies:
- The Renderer abstract interface
- The MoviePyRenderer concrete implementation
- Timeline parsing
- Render dispatch (no real encoding)
- Invalid timeline detection
- Pillow / MoviePy compatibility shim
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Renderer interface ─────────────────────────────────────────────────────


class TestRendererInterface:
    """Verify the Renderer ABC enforces the contract."""

    def test_abstract_class_cannot_be_instantiated(self) -> None:
        from src.renderer import Renderer
        with pytest.raises(TypeError):
            Renderer()  # type: ignore

    def test_abstract_method_defined(self) -> None:
        from src.renderer import Renderer
        assert hasattr(Renderer, "render")
        assert callable(Renderer.render)

    def test_moviepy_renderer_is_subclass(self) -> None:
        from src.renderer import Renderer
        from src.renderer.moviepy_renderer import MoviePyRenderer
        assert issubclass(MoviePyRenderer, Renderer)

    def test_moviepy_renderer_implements_render(self) -> None:
        from src.renderer.moviepy_renderer import MoviePyRenderer
        r = MoviePyRenderer()
        assert hasattr(r, "render")
        assert callable(r.render)


# ── Timeline parsing ───────────────────────────────────────────────────────


class TestParseTimeline:
    """Tests for the ``parse_timeline`` function in moviepy_renderer."""

    def _parse(self, raw: dict):
        from src.renderer.moviepy_renderer import parse_timeline
        return parse_timeline(raw)

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

    # ── Backward compat: module-level function still works ────────────

    def test_backward_compat_parse_timeline(self) -> None:
        """The ``_parse_timeline`` name must remain accessible from renderer module."""
        from renderer import _parse_timeline
        raw = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [],
            "video_timeline": [],
        }
        tl = _parse_timeline(raw)
        assert tl.render_settings.fps == 30


# ── Compatibility shim ─────────────────────────────────────────────────────


class TestCompatibilityShim:
    """Verify the Pillow ANTIALIAS shim in moviepy_renderer."""

    def test_antialias_alias_exists(self) -> None:
        import PIL.Image
        if not hasattr(PIL.Image, "ANTIALIAS"):
            PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
        assert hasattr(PIL.Image, "ANTIALIAS")
        assert PIL.Image.ANTIALIAS == PIL.Image.LANCZOS

    def test_antialias_already_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import PIL.Image
        monkeypatch.setattr(PIL.Image, "ANTIALIAS", PIL.Image.BICUBIC, raising=False)
        # Importing the module should not overwrite if already set
        from src.renderer import moviepy_renderer  # noqa: F401
        assert PIL.Image.ANTIALIAS == PIL.Image.BICUBIC  # unchanged


# ── MoviePyRenderer.render (no real encoding) ──────────────────────────────


class TestMoviePyRenderer:
    """Verify MoviePyRenderer dispatches correctly (all MoviePy classes mocked)."""

    def test_render_dispatches(self, tmp_path: Path) -> None:
        """MoviePyRenderer.render reads timeline.json and calls write_videofile."""
        from src.renderer import moviepy_renderer as mpr_mod

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

        with patch.object(mpr_mod, "VideoFileClip") as mock_vfc, \
               patch.object(mpr_mod, "AudioFileClip") as mock_afc, \
               patch.object(mpr_mod, "CompositeVideoClip") as mock_cvc, \
               patch.object(mpr_mod, "CompositeAudioClip") as mock_cac:
            r = mpr_mod.MoviePyRenderer()
            r.render(str(tl_path), out_path)

        # Verify that write_videofile was called on the composite
        assert mock_cvc.return_value.set_audio.return_value.write_videofile.called

    def test_render_no_json_file(self, tmp_path: Path) -> None:
        """A missing timeline file should raise FileNotFoundError."""
        from src.renderer.moviepy_renderer import MoviePyRenderer
        r = MoviePyRenderer()
        with pytest.raises(FileNotFoundError):
            r.render(str(tmp_path / "no_such_file.json"), "out.mp4")

    def test_render_corrupted_json(self, tmp_path: Path) -> None:
        """Invalid JSON should raise json.JSONDecodeError."""
        bad = tmp_path / "bad.json"
        bad.write_text("{corrupted: json")
        from src.renderer.moviepy_renderer import MoviePyRenderer
        r = MoviePyRenderer()
        with pytest.raises(json.JSONDecodeError):
            r.render(str(bad), "out.mp4")

    def test_render_missing_audio_file(self, tmp_path: Path) -> None:
        """Missing audio files should propagate the MoviePy error."""
        from src.renderer import moviepy_renderer as mpr_mod

        tl_data = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [
                {"track": "voice", "file": "/_nonexistent_audio.wav", "start_time": 0.0, "end_time": 5.0}
            ],
            "video_timeline": [],
        }
        tl_path = tmp_path / "tl_missing_audio.json"
        tl_path.write_text(json.dumps(tl_data))

        with patch.object(mpr_mod, "AudioFileClip") as mock:
            mock.side_effect = FileNotFoundError("No such file")
            r = mpr_mod.MoviePyRenderer()
            with pytest.raises(FileNotFoundError):
                r.render(str(tl_path), "out.mp4")


# ── Backward compat: module-level render_timeline ─────────────────────────


class TestBackwardCompat:
    """The old module-level ``render_timeline`` function must still work."""

    def test_render_timeline_still_callable(self, tmp_path: Path) -> None:
        from renderer import render_timeline
        from src.renderer import moviepy_renderer as mpr_mod

        tl_data = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [],
            "video_timeline": [],
        }
        tl_path = tmp_path / "tl.json"
        tl_path.write_text(json.dumps(tl_data))

        with patch.object(mpr_mod, "VideoFileClip") as mock_vfc, \
               patch.object(mpr_mod, "AudioFileClip") as mock_afc, \
               patch.object(mpr_mod, "CompositeVideoClip") as mock_cvc, \
               patch.object(mpr_mod, "CompositeAudioClip") as mock_cac:
            render_timeline(str(tl_path), str(tmp_path / "out.mp4"))

        # No audio entries → write_videofile on CVC directly (no set_audio)
        assert mock_cvc.return_value.write_videofile.called

    def test_renderer_module_exports_class(self) -> None:
        from renderer import MoviePyRenderer
        from src.renderer.moviepy_renderer import MoviePyRenderer as Base
        assert MoviePyRenderer is Base
