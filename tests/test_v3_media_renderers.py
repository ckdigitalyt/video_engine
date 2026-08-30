"""Wave-2 tests: Ken Burns engine, AI_IMAGE_MOTION + MEDIA renderers.

Offline-safe: the broker is stubbed dead so no network is touched; the
offline solid-still fallback exercises the full motion pipeline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engine.renderers.base import RenderContext
from engine.renderers.media.ai_image_motion import (
    AIImageMotionRenderer,
    make_solid_still,
)
from engine.renderers.media.kenburns import motion_plan, render_kenburns


class _DeadBroker:
    def generate_image(self, *a, **k):
        raise RuntimeError("offline test broker")


def _ffprobe_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return float(out.stdout.strip())


def _ffprobe_video(path: str | Path) -> dict:
    import json

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         str(path)],
        capture_output=True, text=True, timeout=60,
    )
    streams = json.loads(out.stdout)["streams"]
    return next(s for s in streams if s["codec_type"] == "video")


class TestMotionPlan:
    def test_deterministic(self):
        a = motion_plan("dunes", 42, 3.0, "16:9")
        b = motion_plan("dunes", 42, 3.0, "16:9")
        assert a == b

    def test_changes_with_inputs(self):
        a = motion_plan("dunes", 1, 3.0, "16:9")
        b = motion_plan("dunes", 2, 3.0, "16:9")
        assert a != b

    def test_zoom_bounds(self):
        plan = motion_plan("dunes", 7, 3.0, "16:9")
        assert 1.0 <= plan.zoom_start <= 1.5
        assert 1.0 <= plan.zoom_end <= 1.5


class TestKenBurns:
    def test_render_produces_valid_clip(self, tmp_path):
        still = make_solid_still(tmp_path / "still.png")
        out = render_kenburns(
            still, tmp_path / "out.mp4", duration=1.5, aspect="16:9", fps=24,
            prompt="t", seed=1,
        )
        assert out.exists() and out.stat().st_size > 1000
        info = _ffprobe_video(out)
        assert info["codec_name"] == "h264"
        assert info["width"] == 1920 and info["height"] == 1080
        assert abs(_ffprobe_duration(out) - 1.5) < 0.2

    def test_deterministic_output(self, tmp_path):
        still = make_solid_still(tmp_path / "still.png")
        a = render_kenburns(still, tmp_path / "a.mp4", duration=1.0,
                            aspect="16:9", fps=24, prompt="t", seed=5)
        b = render_kenburns(still, tmp_path / "b.mp4", duration=1.0,
                            aspect="16:9", fps=24, prompt="t", seed=5)
        import hashlib

        h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        assert h(a) == h(b)

    def test_missing_still_raises(self, tmp_path):
        with pytest.raises(Exception):
            render_kenburns(tmp_path / "nope.png", tmp_path / "o.mp4",
                            duration=1.0)


class TestAIImageMotionRenderer:
    def test_offline_render_end_to_end(self, tmp_path):
        r = AIImageMotionRenderer(broker=_DeadBroker())
        shot = {
            "shot_id": "T1", "duration_sec": 1.5,
            "subject": "test cliffs", "motion": {"atmosphere": True},
        }
        res = r.render(shot, None, RenderContext(
            output_dir=str(tmp_path), fps=24, aspect="16:9", seed=3))
        assert Path(res.path).exists()
        info = _ffprobe_video(res.path)
        assert info["codec_name"] == "h264"
        assert res.metadata["image_provider"] == "offline_solid"
        assert len(res.qa_frames) >= 1

    def test_validate_rejects_bad_shot(self):
        r = AIImageMotionRenderer(broker=_DeadBroker())
        assert r.validate({"shot_id": "X", "renderer": "MANIM"})
        assert r.validate({"shot_id": "X", "duration_sec": 2.0})


class TestMediaRenderer:
    def test_single_still_render(self, tmp_path):
        from engine.renderers.adapters import MediaRenderer

        still = make_solid_still(tmp_path / "s.png")
        r = MediaRenderer()
        shot = {
            "shot_id": "M1", "duration_sec": 1.5, "visual_goal": "v",
            "asset_requirements": {"still_path": str(still)},
        }
        res = r.render(shot, None, RenderContext(
            output_dir=str(tmp_path), fps=24, aspect="16:9", seed=1))
        info = _ffprobe_video(res.path)
        assert info["codec_name"] == "h264"
        assert abs(_ffprobe_duration(res.path) - 1.5) < 0.2

    def test_multi_still_concat(self, tmp_path):
        from engine.renderers.adapters import MediaRenderer

        s1 = make_solid_still(tmp_path / "a.png", color="0x112233")
        s2 = make_solid_still(tmp_path / "b.png", color="0x445566")
        r = MediaRenderer()
        shot = {
            "shot_id": "M2", "duration_sec": 2.0, "visual_goal": "v",
            "asset_requirements": [str(s1), str(s2)],
        }
        res = r.render(shot, None, RenderContext(
            output_dir=str(tmp_path), fps=24, aspect="16:9", seed=1))
        assert abs(_ffprobe_duration(res.path) - 2.0) < 0.4

    def test_no_stills_raises(self, tmp_path):
        from engine.renderers.adapters import MediaRenderer

        r = MediaRenderer()
        shot = {"shot_id": "M3", "duration_sec": 1.0, "visual_goal": "v"}
        with pytest.raises(ValueError):
            r.render(shot, None, RenderContext(
                output_dir=str(tmp_path), fps=24, aspect="16:9", seed=1))
