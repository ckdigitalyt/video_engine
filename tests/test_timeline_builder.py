"""
test_timeline_builder.py — Tests for the TimelineBuilder (src/renderer/timeline_builder.py).

Verifies monotonic timestamps, no overlaps, correct duration calculations,
multi-scene handling, and rejection of invalid inputs.
All external calls (pydub AudioSegment) are mocked to avoid real I/O.
"""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from src.renderer.timeline_builder import TimelineBuilder
from src.models import SceneAsset


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def builder() -> TimelineBuilder:
    """Return a fresh builder that uses the real config layer (already loaded)."""
    return TimelineBuilder()


@pytest.fixture
def mock_audio_duration() -> MagicMock:
    """Mock pydub AudioSegment.from_wav to return known durations.

    Usage::

        def test_foo(mock_audio_duration):
            mock_audio_duration.side_effect = [5.0, 3.0, 7.0]
    """
    with patch("src.renderer.timeline_builder.AudioSegment.from_wav") as mock:
        instance = MagicMock()
        instance.__len__.return_value = 5000  # 5 s in ms
        mock.return_value = instance
        yield mock


# ── Single-scene tests ─────────────────────────────────────────────────────


class TestSingleScene:
    def test_basic_single_scene(self, builder: TimelineBuilder, mock_audio_duration: MagicMock) -> None:
        """One scene → one audio + one video track."""
        mock_audio_duration.return_value.__len__.return_value = 5000  # 5 s
        assets = [SceneAsset(scene_id=1, video_path="/v/1.mp4", audio_path="/a/1.wav")]
        result = builder._build(assets)
        assert len(result["audio_timeline"]) == 1
        assert len(result["video_timeline"]) == 1
        assert result["audio_timeline"][0]["start_time"] == 0.0
        assert result["audio_timeline"][0]["end_time"] == 5.0

    def test_render_settings(self, builder: TimelineBuilder, mock_audio_duration: MagicMock) -> None:
        """Render settings should contain resolution and fps."""
        mock_audio_duration.return_value.__len__.return_value = 3000
        assets = [SceneAsset(scene_id=1, video_path="/v/1.mp4", audio_path="/a/1.wav")]
        result = builder._build(assets)
        rs = result["render_settings"]
        assert "resolution" in rs
        assert "fps" in rs
        assert rs["fps"] == 30


# ── Multi-scene tests ──────────────────────────────────────────────────────


class TestMultiScene:
    @pytest.mark.parametrize("durations,expected_total", [
        ([5.0, 3.0, 7.0], 15.0),
        ([2.5, 2.5], 5.0),
        ([10.0], 10.0),
    ])
    def test_clock_advances(
        self,
        builder: TimelineBuilder,
        mock_audio_duration: MagicMock,
        durations: list[float],
        expected_total: float,
    ) -> None:
        """Scene start times should be cumulative based on previous durations."""
        # Each call to AudioSegment.from_wav returns a MagicMock whose __len__
        # returns the duration in milliseconds for the corresponding scene.
        duration_objs = []
        for d in durations:
            obj = MagicMock()
            obj.__len__.return_value = int(d * 1000)
            duration_objs.append(obj)
        mock_audio_duration.side_effect = duration_objs

        assets = [
            SceneAsset(scene_id=i + 1, video_path=f"/v/{i+1}.mp4", audio_path=f"/a/{i+1}.wav")
            for i in range(len(durations))
        ]
        result = builder._build(assets)
        assert len(result["audio_timeline"]) == len(durations)
        assert result["audio_timeline"][-1]["end_time"] == pytest.approx(expected_total, rel=1e-3)

    def test_no_overlap(self, builder: TimelineBuilder, mock_audio_duration: MagicMock) -> None:
        """Consecutive scenes must not overlap."""
        class Ctx:
            __len__ = MagicMock()
        ctx = Ctx()
        mock_audio_duration.return_value = ctx

        durations = [4.0, 6.0, 5.0]
        def _len():
            idx = _len.call_count
            _len.call_count += 1
            return int(durations[min(idx, len(durations) - 1)] * 1000)
        _len.call_count = 0
        ctx.__len__ = _len

        assets = [
            SceneAsset(scene_id=i + 1, video_path=f"/v/{i+1}.mp4", audio_path=f"/a/{i+1}.wav")
            for i in range(len(durations))
        ]
        result = builder._build(assets)
        for i in range(1, len(result["audio_timeline"])):
            prev = result["audio_timeline"][i - 1]
            curr = result["audio_timeline"][i]
            assert curr["start_time"] == pytest.approx(prev["end_time"], rel=1e-3), \
                f"Overlap or gap between scene {i} and {i + 1}"

    def test_monotonic_timestamps(self, builder: TimelineBuilder, mock_audio_duration: MagicMock) -> None:
        """All timestamps should be strictly increasing."""
        mock_audio_duration.return_value.__len__.return_value = 3000
        assets = [
            SceneAsset(scene_id=i + 1, video_path=f"/v/{i+1}.mp4", audio_path=f"/a/{i+1}.wav")
            for i in range(4)
        ]
        result = builder._build(assets)
        prev_end = 0.0
        for entry in result["audio_timeline"]:
            assert entry["start_time"] >= prev_end
            assert entry["end_time"] > entry["start_time"]
            prev_end = entry["end_time"]


# ── Validation tests ───────────────────────────────────────────────────────


class TestValidation:
    def test_valid_timeline_passes(self, builder: TimelineBuilder) -> None:
        now = __file__  # use a file that exists
        tl = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [{"track": "voice", "file": __file__, "start_time": 0.0, "end_time": 5.0}],
            "video_timeline": [{"layer": 1, "file": __file__, "start_time": 0.0, "end_time": 5.0, "transition_out": "none"}],
        }
        errors = builder.validate(tl)
        assert errors == []

    def test_missing_render_settings(self, builder: TimelineBuilder) -> None:
        tl = {"audio_timeline": [], "video_timeline": []}
        errors = builder.validate(tl)
        assert any("render_settings" in e for e in errors)

    def test_negative_duration(self, builder: TimelineBuilder) -> None:
        tl = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [{"track": "voice", "file": __file__, "start_time": 10.0, "end_time": 5.0}],
            "video_timeline": [],
        }
        errors = builder.validate(tl)
        assert any("end_time" in e and "start_time" in e for e in errors)

    def test_overlap_detected(self, builder: TimelineBuilder) -> None:
        tl = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [
                {"track": "voice", "file": __file__, "start_time": 0.0, "end_time": 5.0},
                {"track": "voice", "file": __file__, "start_time": 4.0, "end_time": 9.0},
            ],
            "video_timeline": [],
        }
        errors = builder.validate(tl)
        assert any("overlap" in e.lower() for e in errors)

    def test_missing_file_audio(self, builder: TimelineBuilder) -> None:
        tl = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [
                {"track": "voice", "file": "/_nonexistent_file_xyz.wav", "start_time": 0.0, "end_time": 5.0}
            ],
            "video_timeline": [],
        }
        errors = builder.validate(tl)
        assert any("not found" in e.lower() for e in errors)

    def test_audio_video_duration_mismatch(self, builder: TimelineBuilder) -> None:
        tl = {
            "render_settings": {"resolution": [1920, 1080], "fps": 30},
            "audio_timeline": [{"track": "voice", "file": __file__, "start_time": 0.0, "end_time": 100.0}],
            "video_timeline": [{"layer": 1, "file": __file__, "start_time": 0.0, "end_time": 50.0, "transition_out": "none"}],
        }
        errors = builder.validate(tl)
        assert any("duration" in e.lower() and "differ" in e.lower() for e in errors)

    def test_empty_timeline_valid(self, builder: TimelineBuilder) -> None:
        tl = {"render_settings": {"resolution": [1920, 1080], "fps": 30}, "audio_timeline": [], "video_timeline": []}
        errors = builder.validate(tl)
        assert errors == []


# ── SceneAsset / dict normalisation ────────────────────────────────────────


class TestNormalisation:
    def test_to_asset_dict_from_scene_asset(self) -> None:
        sa = SceneAsset(scene_id=5, video_path="/v/5.mp4", audio_path="/a/5.wav")
        d = TimelineBuilder._to_asset_dict(sa)
        assert d["scene_id"] == 5
        assert d["video_path"] == "/v/5.mp4"
        assert d["audio_path"] == "/a/5.wav"

    def test_to_asset_dict_from_dict(self) -> None:
        raw = {"scene_id": 3, "video_path": "/v/3.mp4", "audio_path": "/a/3.wav"}
        d = TimelineBuilder._to_asset_dict(raw)
        assert d is raw  # returned as-is

    def test_sort_by_scene_id(self, builder: TimelineBuilder, mock_audio_duration: MagicMock) -> None:
        """Scenes should be sorted by scene_id regardless of input order."""
        mock_audio_duration.return_value.__len__.return_value = 2000
        assets = [
            SceneAsset(scene_id=3, video_path="/v/3.mp4", audio_path="/a/3.wav"),
            SceneAsset(scene_id=1, video_path="/v/1.mp4", audio_path="/a/1.wav"),
        ]
        result = builder._build(assets)
        assert result["audio_timeline"][0]["file"] == "/a/1.wav"
        assert result["audio_timeline"][1]["file"] == "/a/3.wav"


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_duration_scene(self, builder: TimelineBuilder, mock_audio_duration: MagicMock) -> None:
        """A scene with 0-length audio should produce 0-length entries."""
        mock_audio_duration.return_value.__len__.return_value = 0
        assets = [SceneAsset(scene_id=1, video_path="/v/1.mp4", audio_path="/a/1.wav")]
        result = builder._build(assets)
        assert result["audio_timeline"][0]["start_time"] == 0.0
        assert result["audio_timeline"][0]["end_time"] == 0.0
