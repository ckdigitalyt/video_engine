"""
test_models.py — Tests for domain models (src/models/__init__.py).

Verifies dataclass construction, field defaults, type hints,
serialisation, and rejection of obviously invalid inputs.
"""

import json
from pathlib import Path

import pytest
from src.models import (
    Scene,
    SceneAsset,
    Narration,
    Timeline,
    TimelineTrack,
    RenderSettings,
    VideoProject,
    VideoMetadata,
    AssetMetadata,
    ProviderResult,
    RenderResult,
    CriticResult,
    ExecutionResult,
    UploadJob,
    ChannelProfile,
)


# ── Scene ──────────────────────────────────────────────────────────────────


class TestScene:
    def test_minimal(self) -> None:
        s = Scene(scene_id=1, search_query="milky way", narration="Hello")
        assert s.scene_id == 1
        assert s.search_query == "milky way"
        assert s.narration == "Hello"

    def test_types(self) -> None:
        s = Scene(scene_id=42, search_query="q", narration="n")
        assert isinstance(s.scene_id, int)
        assert isinstance(s.search_query, str)


class TestSceneAsset:
    def test_minimal(self) -> None:
        a = SceneAsset(scene_id=1, video_path="/v/1.mp4", audio_path="/a/1.wav")
        assert a.scene_id == 1
        assert a.video_path == "/v/1.mp4"
        assert a.audio_path == "/a/1.wav"

    def test_scene_id_type(self) -> None:
        """Python dataclasses do not enforce types at construction."""
        # This is expected: dataclass __init__ accepts any type.
        # Type-checking is provided by mypy / pyright at development time.
        sa = SceneAsset(scene_id="a", video_path="x", audio_path="y")
        assert sa.scene_id == "a"  # no TypeError raised by dataclass


# ── Narration ──────────────────────────────────────────────────────────────


class TestNarration:
    def test_defaults(self) -> None:
        n = Narration(text="hello")
        assert n.text == "hello"
        assert n.voice == "bm_george"
        assert n.speed == 1.0
        assert n.language == "en-gb"
        assert n.output_path == ""

    def test_custom_values(self) -> None:
        n = Narration(text="hi", voice="af_heart", speed=1.2, language="en-us")
        assert n.voice == "af_heart"
        assert n.speed == 1.2


# ── RenderSettings ─────────────────────────────────────────────────────────


class TestRenderSettings:
    def test_defaults(self) -> None:
        rs = RenderSettings()
        assert rs.resolution == [1920, 1080]
        assert rs.fps == 30

    def test_to_tuple(self) -> None:
        rs = RenderSettings(resolution=[1280, 720], fps=24)
        assert rs.to_tuple() == (1280, 720)

    def test_invalid_resolution_length(self) -> None:
        """Dataclasses accept any list; wrong-length resolution is not validated."""
        rs = RenderSettings(resolution=[1920])
        assert rs.resolution == [1920]


# ── TimelineTrack ──────────────────────────────────────────────────────────


class TestTimelineTrack:
    def test_defaults(self) -> None:
        t = TimelineTrack(file="/path/clip.mp4")
        assert t.start_time == 0.0
        assert t.end_time == 0.0
        assert t.track == "voice"
        assert t.layer == 1
        assert t.transition_out == "none"

    def test_audio_track(self) -> None:
        t = TimelineTrack(
            file="/a.wav", start_time=5.0, end_time=10.0, track="music"
        )
        assert t.start_time == 5.0
        assert t.end_time == 10.0
        assert t.track == "music"


# ── Timeline ───────────────────────────────────────────────────────────────


class TestTimeline:
    def test_empty(self) -> None:
        rs = RenderSettings()
        tl = Timeline(render_settings=rs)
        assert tl.audio_timeline == []
        assert tl.video_timeline == []
        assert tl.render_settings.fps == 30

    def test_with_tracks(self) -> None:
        rs = RenderSettings()
        a_track = TimelineTrack(file="/a.wav", start_time=0.0, end_time=5.0)
        v_track = TimelineTrack(file="/v.mp4", start_time=0.0, end_time=5.0)
        tl = Timeline(
            render_settings=rs,
            audio_timeline=[a_track],
            video_timeline=[v_track],
        )
        assert len(tl.audio_timeline) == 1
        assert len(tl.video_timeline) == 1

    def test_to_dict(self) -> None:
        rs = RenderSettings(resolution=[1920, 1080], fps=30)
        tl = Timeline(
            render_settings=rs,
            audio_timeline=[TimelineTrack(file="/a.wav", start_time=0.0, end_time=5.0)],
            video_timeline=[TimelineTrack(file="/v.mp4", start_time=0.0, end_time=5.0)],
        )
        d = tl.to_dict()
        assert d["render_settings"]["resolution"] == [1920, 1080]
        assert d["audio_timeline"][0]["file"] == "/a.wav"
        assert d["video_timeline"][0]["file"] == "/v.mp4"

    def test_to_json(self) -> None:
        rs = RenderSettings()
        tl = Timeline(render_settings=rs)
        raw = tl.to_json()
        parsed = json.loads(raw)
        assert parsed["render_settings"]["fps"] == 30

    def test_to_dict_audio_no_track_field_in_output(self) -> None:
        """Audio entries omit 'layer' and 'transition_out' per the schema."""
        rs = RenderSettings()
        tl = Timeline(
            render_settings=rs,
            audio_timeline=[TimelineTrack(file="/a.wav", start_time=0.0, end_time=5.0)],
        )
        d = tl.to_dict()
        entry = d["audio_timeline"][0]
        assert "layer" not in entry
        assert "transition_out" not in entry


# ── VideoProject + VideoMetadata ──────────────────────────────────────────


class TestVideoProject:
    def test_minimal(self) -> None:
        vp = VideoProject(topic="Fermi Paradox")
        assert vp.topic == "Fermi Paradox"
        assert vp.scenes == []
        assert vp.metadata is None
        assert vp.timeline is None
        assert vp.iteration == 0

    def test_with_scenes(self) -> None:
        scenes = [
            Scene(scene_id=1, search_query="q1", narration="n1"),
            Scene(scene_id=2, search_query="q2", narration="n2"),
        ]
        meta = VideoMetadata(topic="t", duration_seconds=60.0)
        vp = VideoProject(topic="test", scenes=scenes, metadata=meta, iteration=1)
        assert len(vp.scenes) == 2
        assert vp.metadata.duration_seconds == 60.0
        assert vp.iteration == 1


class TestVideoMetadata:
    def test_defaults(self) -> None:
        vm = VideoMetadata(topic="t")
        assert vm.duration_seconds is None
        assert vm.file_size_bytes is None
        assert vm.approved is None
        assert vm.iterations == 0
        assert vm.status == "pending"

    def test_status_enum(self) -> None:
        for s in ["pending", "running", "approved", "rejected", "error"]:
            vm = VideoMetadata(topic="t", status=s)
            assert vm.status == s


# ── Provider result models ────────────────────────────────────────────────


class TestAssetMetadata:
    def test_defaults(self) -> None:
        am = AssetMetadata()
        assert am.provider == ""
        assert am.search_query == ""
        assert am.asset_url == ""

    def test_full(self) -> None:
        am = AssetMetadata(
            provider="pexels",
            search_query="space",
            asset_url="https://test.com/v.mp4",
            local_path="/cache/v.mp4",
            file_size_bytes=1024,
        )
        assert am.file_size_bytes == 1024


class TestProviderResult:
    def test_defaults(self) -> None:
        pr = ProviderResult()
        assert pr.items == []
        assert pr.error is None

    def test_with_items(self) -> None:
        items = [AssetMetadata(provider="p", search_query="q", asset_url="u")]
        pr = ProviderResult(items=items)
        assert len(pr.items) == 1
        assert pr.error is None

    def test_with_error(self) -> None:
        pr = ProviderResult(error="API limit")
        assert pr.error == "API limit"


# ── Pipeline result models ────────────────────────────────────────────────


class TestRenderResult:
    def test_ok(self) -> None:
        rr = RenderResult(
            output_path="/out.mp4", duration_seconds=30.0, file_size_bytes=1_000_000
        )
        assert rr.success is True
        assert rr.error is None

    def test_failure(self) -> None:
        rr = RenderResult(
            output_path="/out.mp4",
            duration_seconds=0.0,
            file_size_bytes=0,
            success=False,
            error="OOM",
        )
        assert rr.success is False
        assert rr.error == "OOM"


class TestCriticResult:
    def test_defaults(self) -> None:
        cr = CriticResult()
        assert cr.approved is False
        assert cr.decision == ""
        assert cr.error is None

    def test_approved(self) -> None:
        cr = CriticResult(approved=True, decision="Looks good")
        assert cr.approved is True
        assert cr.decision == "Looks good"

    def test_rejected_with_error(self) -> None:
        cr = CriticResult(approved=False, error="Service unavailable")
        assert cr.approved is False
        assert cr.error == "Service unavailable"


class TestExecutionResult:
    def test_defaults(self) -> None:
        er = ExecutionResult(topic="test")
        assert er.status == "running"
        assert er.iteration_count == 0
        assert er.critic_approved is None

    def test_complete(self) -> None:
        er = ExecutionResult(
            topic="test",
            status="completed",
            plan_json='{"scenes": []}',
            timeline_json='{"render_settings": {}}',
            output_path="/out.mp4",
            duration_seconds=60.0,
            iteration_count=2,
            critic_approved=True,
        )
        assert er.status == "completed"
        assert er.iteration_count == 2
        assert er.critic_approved is True


# ── Channel / Upload models ───────────────────────────────────────────────


class TestChannelProfile:
    def test_defaults(self) -> None:
        cp = ChannelProfile()
        assert cp.channel_id == ""
        assert cp.name == ""
        assert cp.niche == ""

    def test_full(self) -> None:
        cp = ChannelProfile(
            channel_id="UC123", name="Science", niche="physics", target_audience="students"
        )
        assert cp.name == "Science"


class TestUploadJob:
    def test_minimal(self) -> None:
        uj = UploadJob(video_path="/v.mp4", title="My Video")
        assert uj.video_path == "/v.mp4"
        assert uj.title == "My Video"
        assert uj.tags == []
        assert uj.privacy_status == "public"
        assert uj.status == "pending"

    def test_with_tags(self) -> None:
        uj = UploadJob(
            video_path="/v.mp4",
            title="T",
            tags=["space", "science"],
            privacy_status="unlisted",
        )
        assert "space" in uj.tags
        assert uj.privacy_status == "unlisted"
