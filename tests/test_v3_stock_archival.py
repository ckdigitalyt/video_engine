"""Wave-2 tests: archival providers (mocked HTTP), conform, STOCK/ARCHIVAL
renderers. Offline-safe — all network calls are patched."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from engine.renderers.base import RenderContext
from engine.renderers.media.conform import conform_image


def _ffprobe_video(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         str(path)],
        capture_output=True, text=True, timeout=60,
    )
    streams = json.loads(out.stdout)["streams"]
    return next(s for s in streams if s["codec_type"] == "video")


class TestConform:
    def test_image_to_clip(self, tmp_path):
        src = tmp_path / "arch.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=800x600",
             "-frames:v", "1", str(src)], capture_output=True, timeout=60,
            check=True)
        out = conform_image(src, tmp_path / "clip.mp4", duration=1.0,
                            aspect="16:9", fps=30)
        info = _ffprobe_video(out)
        assert info["codec_name"] == "h264"
        assert info["width"] == 1920 and info["height"] == 1080
        # audio stripped (§18: mastering downstream)
        assert "codec_type" not in str(info.get("codec_type"))


class TestNasaProvider:
    def test_search_parses_payload(self):
        from engine.broker.providers.archival import NasaImagesProvider

        payload = {"collection": {"items": [
            {"data": [{"nasa_id": "PIA1", "title": "Earth",
                       "media_type": "image"}],
             "links": [{"rel": "preview", "href": "http://x/thumb.jpg"}]},
        ]}}
        with mock.patch(
            "engine.broker.providers.archival._get_json",
            return_value=payload,
        ):
            p = NasaImagesProvider(cache=mock.Mock())
            results = p.search("earth", per_page=1)
        assert results[0]["asset_id"] == "PIA1"

    def test_download_requires_nasa_id(self):
        from engine.broker.providers.archival import NasaImagesProvider
        from engine.broker.providers.base import ProviderError

        p = NasaImagesProvider(cache=mock.Mock())
        with pytest.raises(ProviderError, match="license"):
            p.download({"asset_id": ""})

    def test_download_prefers_video_and_caches(self, tmp_path):
        from engine.broker.cache import BrokerCache
        from engine.broker.providers.archival import NasaImagesProvider

        payload = {"collection": {"items": [
            {"href": "http://x/orig.mp4"}, {"href": "http://x/orig.jpg"},
        ]}}
        cache = BrokerCache(root=tmp_path)
        p = NasaImagesProvider(cache=cache)
        with mock.patch(
            "engine.broker.providers.archival._get_json",
            return_value=payload,
        ), mock.patch(
            "engine.broker.providers.archival._download",
            return_value=b"V" * 30000,
        ) as dl:
            res = p.download({"asset_id": "PIA1", "title": "Earth"})
        assert dl.call_args[0][0].endswith(".mp4")
        meta = res.metadata
        assert meta["source"] == "nasa_images"
        assert "Public Domain" in meta["license"]
        assert meta["download_date"]
        # deterministic cache: second call does not re-download
        with mock.patch(
            "engine.broker.providers.archival._get_json",
            return_value=payload,
        ), mock.patch(
            "engine.broker.providers.archival._download",
            return_value=b"V" * 30000,
        ) as dl2:
            res2 = p.download({"asset_id": "PIA1", "title": "Earth"})
        dl2.assert_not_called()
        assert res2.cached


class TestWikimediaLicenseGate:
    def test_non_free_license_skipped(self):
        from engine.broker.providers.archival import WikimediaCommonsProvider
        from engine.broker.providers.base import ProviderError

        p = WikimediaCommonsProvider(cache=mock.Mock())
        with pytest.raises(ProviderError, match="§13"):
            p.download({"asset_id": "1", "license": "CC BY-SA 4.0", "url": "http://x"})

    def test_pd_license_downloads(self, tmp_path):
        from engine.broker.cache import BrokerCache
        from engine.broker.providers.archival import WikimediaCommonsProvider

        cache = BrokerCache(root=tmp_path)
        p = WikimediaCommonsProvider(cache=cache)
        with mock.patch(
            "engine.broker.providers.archival._download",
            return_value=b"W" * 30000,
        ):
            res = p.download({"asset_id": "9", "license": "Public domain",
                              "url": "http://x/a.jpg"})
        assert res.metadata["attribution_required"] is True
        assert "Public domain" in res.metadata["license"]


class TestInternetArchiveGate:
    def test_requires_publicdomain_licenseurl(self):
        from engine.broker.providers.archival import InternetArchiveProvider
        from engine.broker.providers.base import ProviderError

        p = InternetArchiveProvider(cache=mock.Mock())
        with pytest.raises(ProviderError, match="§13"):
            p.download({"asset_id": "item1", "licenseurl": ""})


class TestStockVideoRenderer:
    def _shot(self, **kw):
        return dict({"shot_id": "S1", "duration_sec": 1.0,
                     "subject": "waves", "visual_goal": "waves"}, **kw)

    def test_offline_with_local_footage(self, tmp_path):
        from engine.renderers.media.stock_video import StockVideoRenderer

        # build a tiny real clip
        src = tmp_path / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
             "-t", "2", "-pix_fmt", "yuv420p", str(src)],
            capture_output=True, timeout=60, check=True)
        r = StockVideoRenderer(broker=object())  # broker unused w/ local asset
        shot = self._shot(asset_requirements={"footage_path": str(src)})
        res = r.render(shot, None, RenderContext(
            output_dir=str(tmp_path), fps=24, aspect="16:9", seed=0))
        info = _ffprobe_video(res.path)
        assert info["codec_name"] == "h264"
        assert info["width"] == 1920

    def test_no_asset_raises_for_fallback(self, tmp_path):
        from engine.renderers.media.stock_video import StockVideoRenderer

        class DeadBroker:
            def search_stock(self, q, per_page=4):
                return []

        r = StockVideoRenderer(broker=DeadBroker())
        with pytest.raises(RuntimeError, match="falling back"):
            r.render(self._shot(), None, RenderContext(
                output_dir=str(tmp_path), fps=24, aspect="16:9", seed=0))

    def test_license_gate_skip_then_fallback(self, tmp_path):
        from engine.renderers.media.stock_video import ArchivalRenderer

        class GateBroker:
            """All candidates fail the §13 gate → renderer must raise."""
            def search_archival(self, q, per_page=4):
                return [{"asset_id": "x"}]
            def download_archival(self, asset):
                raise RuntimeError("license not established")

        r = ArchivalRenderer(broker=GateBroker())
        with pytest.raises(RuntimeError, match="falling back"):
            r.render(self._shot(), None, RenderContext(
                output_dir=str(tmp_path), fps=24, aspect="16:9", seed=0))

    def test_archival_still_conformed(self, tmp_path):
        from engine.renderers.media.stock_video import ArchivalRenderer

        still = tmp_path / "nasa.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=steelblue:s=800x600",
             "-frames:v", "1", str(still)], capture_output=True, timeout=60,
            check=True)
        r = ArchivalRenderer(broker=object())
        shot = self._shot(asset_requirements=[str(still)])
        res = r.render(shot, None, RenderContext(
            output_dir=str(tmp_path), fps=30, aspect="16:9", seed=0))
        assert _ffprobe_video(res.path)["codec_name"] == "h264"

    def test_router_conformance_stub_list(self):
        """STOCK_VIDEO and ARCHIVAL now implement render (no longer stubs)."""
        from engine.renderers.registry import get_renderer

        assert get_renderer("STOCK_VIDEO").__class__.__name__ == "StockVideoRenderer"
        assert get_renderer("ARCHIVAL").__class__.__name__ == "ArchivalRenderer"
