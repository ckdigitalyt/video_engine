"""Wave-2 tests: AI_VIDEO renderer + Wan/LTX/MiniMax providers (mocked).

Live generation tests are marked @pytest.mark.live (RUN_LIVE_TESTS=1).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from engine.broker.providers.base import ProviderError
from engine.renderers.ai_video import AIVideoRenderer
from engine.renderers.base import RenderContext


class TestProviderRegistration:
    def test_minimax_disabled_with_reason(self):
        from engine.broker.providers.minimax import MiniMaxH3Provider

        cap = MiniMaxH3Provider().capabilities()
        assert cap.enabled is False
        assert "paid" in cap.notes.lower()

    def test_minimax_generate_video_blocked(self):
        from engine.broker.providers.minimax import MiniMaxH3Provider

        with pytest.raises(ProviderError, match="not enabled"):
            MiniMaxH3Provider().generate_video("x")

    def test_wan_and_ltx_construct(self):
        from engine.broker.providers.ltx import LTXVideoProvider
        from engine.broker.providers.wan import Wan22I2VProvider

        wan = Wan22I2VProvider(cache=mock.Mock())
        ltx = LTXVideoProvider(cache=mock.Mock())
        assert "wan2.2" in wan.capabilities().models[0].lower()
        assert "ltx" in ltx.capabilities().models[0].lower()

    def test_wan_space_from_config(self):
        from engine.broker.providers.wan import Wan22I2VProvider

        wan = Wan22I2VProvider(cache=mock.Mock())
        assert wan.space_id  # config or default present
        assert wan.endpoint_name == "generate_video"

    def test_broker_image_to_video_chain(self):
        from engine.broker.broker import MediaBroker

        broker = MediaBroker()
        i2v = [p for p in broker._providers.values()
               if p.kind == "image_to_video"]
        ids = {p.id for p in i2v}
        # HF_TOKEN absent in CI → providers disabled → empty chain is valid
        if ids:
            assert ids == {"wan22_i2v", "ltx_video"}


class TestAIVideoRenderer:
    def test_validate(self):
        r = AIVideoRenderer(broker=object())
        assert r.validate({"shot_id": "S", "duration_sec": 999.0,
                           "visual_goal": "x"})
        assert not r.validate({"shot_id": "S", "duration_sec": 5.0,
                               "visual_goal": "x"})

    def test_render_with_explicit_keyframe_and_mock_broker(self, tmp_path):
        # Build a tiny keyframe + fake provider video, verify conform + copy.
        keyframe = tmp_path / "kf.png"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=teal:s=640x360",
             "-frames:v", "1", str(keyframe)],
            capture_output=True, timeout=60, check=True)

        class FakeBroker:
            def image_to_video(self, image, prompt, *, duration=4.0,
                               seed=0, aspect="16:9"):
                out = tmp_path / "raw_i2v.mp4"
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi",
                     "-i", "testsrc=size=1280x720:rate=24",
                     "-t", str(duration), "-pix_fmt", "yuv420p", str(out)],
                    capture_output=True, timeout=120, check=True)
                return mock.Mock(path=str(out), provider="wan22_i2v")

        r = AIVideoRenderer(broker=FakeBroker())
        shot = {"shot_id": "AV1", "duration_sec": 2.0, "subject": "volcano",
                "asset_requirements": {"image_path": str(keyframe)}}
        res = r.render(shot, None, RenderContext(
            output_dir=str(tmp_path), fps=24, aspect="16:9", seed=1))
        assert res.metadata["provider"] == "wan22_i2v"
        assert Path(res.path).exists()
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", res.path],
            capture_output=True, text=True, timeout=60).stdout.strip()
        assert abs(float(dur) - 2.0) < 0.3


@pytest.mark.live
class TestLiveGeneration:
    """Real ZeroGPU generation — only with RUN_LIVE_TESTS=1."""

    def test_ltx_image_to_video_live(self, tmp_path):
        if not Path("/home/ubuntu/video_engine/.env").exists():
            pytest.skip("no .env")
        from engine.broker.providers.ltx import LTXVideoProvider

        keyframe = tmp_path / "kf.png"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=512x896:rate=1",
             "-frames:v", "1", str(keyframe)],
            capture_output=True, timeout=60, check=True)
        provider = LTXVideoProvider()
        if not provider.capabilities().enabled:
            pytest.skip("HF_TOKEN not set")
        result = provider.image_to_video(
            keyframe, "gentle camera drift, cinematic",
            duration=2.0, seed=7)
        assert Path(result.path).exists()
        assert Path(result.path).stat().st_size > 50_000
