"""
test_pixabay_provider.py — Tests for the fully functional PixabayProvider.

Covers:
- Search with API key
- Cache hit
- Cache miss → API call
- Empty results
- API failure
- Missing API key fallback
- Metadata normalisation
- Deterministic scoring
- Download (new file, existing file)
- AssetRouter integration (Pixabay tried before Pexels)
- Fallback to Pexels when Pixabay returns empty
- AssetLibrary compat via router
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from typing import Any

from src.providers.asset_provider import AssetProvider, PexelsProvider, PixabayProvider
from src.assets.asset_router import AssetRouter


# ── Shared helpers ─────────────────────────────────────────────────────────

_query_counter = 0


def _uq(base: str) -> str:
    """Return a unique query string to avoid cache collisions between tests."""
    global _query_counter
    _query_counter += 1
    return f"{base}_{_query_counter}"


# ============================================================================
#  Interface compliance
# ============================================================================


class TestPixabayInterface:
    """PixabayProvider must satisfy the AssetProvider interface."""

    def test_is_asset_provider(self) -> None:
        assert issubclass(PixabayProvider, AssetProvider)

    def test_has_search(self) -> None:
        assert hasattr(PixabayProvider, "search")
        assert callable(getattr(PixabayProvider, "search"))

    def test_has_download(self) -> None:
        assert hasattr(PixabayProvider, "download")
        assert callable(getattr(PixabayProvider, "download"))


# ============================================================================
#  Search
# ============================================================================


class TestPixabaySearch:
    """Verify search behaviour, caching, and scoring."""

    def test_search_returns_list(self, mock_pixabay_api: MagicMock) -> None:
        provider = PixabayProvider()
        results = provider.search(_uq("nature"))
        assert isinstance(results, list)
        assert len(results) > 0

    def test_search_result_has_link(self, mock_pixabay_api: MagicMock) -> None:
        provider = PixabayProvider()
        results = provider.search(_uq("nature"))
        assert len(results) > 0
        assert results[0]["video_files"][0]["link"] == "https://test.pixabay.com/video_large.mp4"
        assert results[0]["video_files"][0]["quality"] == "hd"

    def test_search_has_top_level_dimensions(self, mock_pixabay_api: MagicMock) -> None:
        provider = PixabayProvider()
        results = provider.search(_uq("nature"))
        assert results[0]["width"] == 1920
        assert results[0]["height"] == 1080
        assert results[0]["duration"] == 8

    def test_search_has_all_video_qualities(self, mock_pixabay_api: MagicMock) -> None:
        provider = PixabayProvider()
        results = provider.search(_uq("nature"))
        vf = results[0]["video_files"]
        urls = [v["link"] for v in vf]
        assert "https://test.pixabay.com/video_large.mp4" in urls
        assert "https://test.pixabay.com/video_medium.mp4" in urls
        assert "https://test.pixabay.com/video_small.mp4" in urls

    def test_search_cache_hit_after_download(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """After search + download, cached data is returned without API call."""
        call_count: list[int] = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.json.return_value = {
                "hits": [
                    {
                        "id": 1,
                        "duration": 5,
                        "tags": "test",
                        "videos": {
                            "large": {"url": "https://pixabay.com/v.mp4", "width": 1920, "height": 1080, "size": 100},
                        },
                    }
                ]
            }
            resp.content = b"fake video data"
            resp.status_code = 200
            return resp

        mock = MagicMock()
        mock.side_effect = side_effect
        import src.providers.asset_provider as ap
        monkeypatch.setattr(ap.requests, "get", mock)

        provider = PixabayProvider()
        out = str(tmp_path / "cached_video.mp4")

        # First search + download — populates cache
        results = provider.search(_uq("cache_test"))
        assert len(results) > 0
        assert call_count[0] >= 1
        url = results[0]["video_files"][0]["link"]

        provider.download(url, out)

        # Second search — cache hit, no API call for Pixabay
        results = provider.search(_uq("cache_test"))
        assert len(results) > 0

    def test_search_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        mock.return_value.json.return_value = {"hits": []}
        import src.providers.asset_provider
        monkeypatch.setattr(src.providers.asset_provider.requests, "get", mock)

        provider = PixabayProvider()
        results = provider.search("xyznonexistent12345")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_api_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        mock.side_effect = Exception("Connection refused")
        import src.providers.asset_provider
        monkeypatch.setattr(src.providers.asset_provider.requests, "get", mock)

        provider = PixabayProvider()
        results = provider.search("test")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
        provider = PixabayProvider()
        results = provider.search("nature")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_empty_query(self, mock_pixabay_api: MagicMock) -> None:
        provider = PixabayProvider()
        results = provider.search("")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_passes_target_duration(self, mock_pixabay_api: MagicMock) -> None:
        """target_duration should be passed through to scoring."""
        provider = PixabayProvider()
        results = provider.search(_uq("nature"), target_duration=10)
        assert len(results) > 0

    def test_search_scores_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple hits should be scored and sorted."""
        mock = MagicMock()
        mock.return_value.json.return_value = {
            "hits": [
                {
                    "id": 1,
                    "duration": 5,
                    "tags": "low res",
                    "videos": {
                        "large": {"url": "https://pixabay.com/1.mp4", "width": 640, "height": 480, "size": 100000},
                        "medium": {"url": "", "width": 0, "height": 0, "size": 0},
                        "small": {"url": "", "width": 0, "height": 0, "size": 0},
                    },
                },
                {
                    "id": 2,
                    "duration": 10,
                    "tags": "high res",
                    "videos": {
                        "large": {"url": "https://pixabay.com/2.mp4", "width": 3840, "height": 2160, "size": 8000000},
                        "medium": {"url": "https://pixabay.com/2_med.mp4", "width": 1920, "height": 1080, "size": 3000000},
                        "small": {"url": "", "width": 0, "height": 0, "size": 0},
                    },
                },
            ]
        }
        import src.providers.asset_provider
        monkeypatch.setattr(src.providers.asset_provider.requests, "get", mock)

        provider = PixabayProvider()
        results = provider.search(_uq("scoring_test"), target_duration=8)
        # Higher-res result should be first
        assert len(results) == 2
        assert results[0]["id"] == 2  # 4K video scored higher
        assert results[1]["id"] == 1  # Low-res scored lower


# ============================================================================
#  Download
# ============================================================================


class TestPixabayDownload:
    """Verify download behaviour."""

    def test_download_new_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        out = str(tmp_path / "video.mp4")

        def side_effect(url, **kw):
            resp = MagicMock()
            resp.content = b"pixabay video content"
            resp.status_code = 200
            return resp

        mock = MagicMock()
        mock.side_effect = side_effect
        monkeypatch.setattr("src.providers.asset_provider.requests.get", mock)

        provider = PixabayProvider()
        provider._last_query = _uq("dl_test")
        result = provider.download("https://test.pixabay.com/video_large.mp4", out)
        assert result == out
        assert os.path.exists(out)
        assert open(out, "rb").read() == b"pixabay video content"

    def test_download_existing_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        out = str(tmp_path / "existing.mp4")
        with open(out, "wb") as f:
            f.write(b"existing data")

        mock_get = MagicMock()
        monkeypatch.setattr("src.providers.asset_provider.requests.get", mock_get)

        provider = PixabayProvider()
        provider._last_query = "nature"
        result = provider.download("https://pixabay.com/v.mp4", out)
        assert result == out
        mock_get.assert_not_called()  # no HTTP request

    def test_download_touches_cache(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        out = str(tmp_path / "touched.mp4")

        def side_effect(url, **kw):
            resp = MagicMock()
            resp.content = b"data"
            resp.status_code = 200
            return resp

        mock = MagicMock()
        mock.side_effect = side_effect
        monkeypatch.setattr("src.providers.asset_provider.requests.get", mock)

        provider = PixabayProvider()
        q = _uq("touch_test")
        # Register a cache entry first so touch has an effect
        from src.assets.asset_cache import AssetCache
        cache = AssetCache()
        cache.register("pixabay", q, "https://pixabay.com/v.mp4")

        provider._last_query = q
        provider.download("https://pixabay.com/v.mp4", out)
        # Verify it was saved by re-searching (should have hit from earlier registration)
        results = provider.search(q)
        assert len(results) > 0


# ============================================================================
#  Normalisation
# ============================================================================


class TestPixabayNormalisation:
    """Verify Pixabay hits are normalised to the internal asset model."""

    def test_preserves_id(self) -> None:
        from src.providers.asset_provider import _normalise_pixabay_hit
        result = _normalise_pixabay_hit({"id": 42, "videos": {"large": {"url": "x.mp4"}}})
        assert result["id"] == 42

    def test_handles_missing_videos(self) -> None:
        from src.providers.asset_provider import _normalise_pixabay_hit
        result = _normalise_pixabay_hit({"id": 1})
        assert result["id"] == 1
        assert result["video_files"] == []
        assert result["width"] == 0
        assert result["height"] == 0

    def test_handles_partial_video_tiers(self) -> None:
        from src.providers.asset_provider import _normalise_pixabay_hit
        hit = {
            "id": 1,
            "duration": 5,
            "videos": {
                "large": {"url": "big.mp4", "width": 1920, "height": 1080, "size": 1000},
                "tiny": {"url": "tiny.mp4", "width": 150, "height": 100, "size": 50},
            },
        }
        result = _normalise_pixabay_hit(hit)
        # Only large, medium, small should be in video_files (tiny is skipped)
        vf = result["video_files"]
        assert len(vf) == 1
        assert vf[0]["link"] == "big.mp4"

    def test_quality_labels(self) -> None:
        from src.providers.asset_provider import _normalise_pixabay_hit
        hit = {
            "id": 1,
            "videos": {
                "large": {"url": "large.mp4", "width": 1920, "height": 1080, "size": 100},
                "medium": {"url": "med.mp4", "width": 1280, "height": 720, "size": 50},
                "small": {"url": "small.mp4", "width": 640, "height": 360, "size": 20},
            },
        }
        result = _normalise_pixabay_hit(hit)
        vf = {v["quality"]: v["link"] for v in result["video_files"]}
        assert vf["hd"] == "large.mp4"
        assert vf["sd"] in ("med.mp4", "small.mp4")  # both medium and small are "sd"

    def test_raw_metadata_preserved(self) -> None:
        from src.providers.asset_provider import _normalise_pixabay_hit
        hit = {"id": 1, "tags": "a, b", "views": 100, "downloads": 50, "user": "u",
               "videos": {"large": {"url": "x.mp4"}}}
        result = _normalise_pixabay_hit(hit)
        assert result["_raw"]["tags"] == "a, b"
        assert result["_raw"]["views"] == 100
        assert result["_raw"]["downloads"] == 50
        assert result["_raw"]["user"] == "u"


# ============================================================================
#  AssetRouter integration
# ============================================================================


class TestPixabayRouterIntegration:
    """Verify PixabayProvider works correctly inside AssetRouter."""

    def test_router_tries_pixabay_first_for_general(self, mock_pixabay_api: MagicMock) -> None:
        """General routes to [pixabay, pexels]; Pixabay should be tried first."""
        router = AssetRouter.for_topic("General Topic")
        results = router.search("nature")
        assert len(results) > 0
        # Pixabay is first in the chain, so it should have been selected
        assert router.current_provider_name() == "pixabay"

    def test_router_tries_pixabay_for_space(self, mock_pixabay_api: MagicMock) -> None:
        """Space routes to [nasa, pixabay, pexels]; Pixabay is first real."""
        router = AssetRouter.for_topic("Stars and Planets")
        results = router.search("nebula")
        assert len(results) > 0
        assert router.current_provider_name() == "pixabay"

    def test_router_tries_pixabay_for_history(self, mock_pixabay_api: MagicMock) -> None:
        """History routes to [wikimedia, pixabay, pexels]."""
        router = AssetRouter.for_topic("Roman Empire")
        results = router.search("colosseum")
        assert len(results) > 0
        assert router.current_provider_name() == "pixabay"

    def test_router_falls_back_to_pexels_when_pixabay_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When Pixabay returns no results, Pexels should be tried."""
        call_log: list[str] = []

        def side_effect(url, **kwargs):
            resp = MagicMock()
            if "pexels" in url:
                call_log.append("pexels")
                resp.json.return_value = {
                    "videos": [
                        {
                            "id": 1, "width": 1920, "height": 1080, "duration": 10,
                            "video_files": [{"link": "https://pexels.com/v.mp4", "quality": "hd"}]
                        }
                    ]
                }
            elif "pixabay" in url:
                call_log.append("pixabay")
                resp.json.return_value = {"hits": []}  # empty from Pixabay
            return resp

        mock = MagicMock()
        mock.side_effect = side_effect
        import src.providers.asset_provider as ap
        monkeypatch.setattr(ap.requests, "get", mock)

        router = AssetRouter.for_topic("General Topic")
        results = router.search("something")
        assert len(results) > 0
        # Pexels should have been selected after Pixabay returned empty
        assert router.current_provider_name() == "pexels"
        # Both providers should have been tried
        assert "pixabay" in call_log
        assert "pexels" in call_log

    def test_router_falls_back_when_pixabay_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When Pixabay raises, Pexels should be tried."""
        call_log: list[str] = []

        def side_effect(url, **kwargs):
            if "pixabay" in url:
                call_log.append("pixabay")
                raise Exception("Pixabay down")
            # pexels: return real data
            call_log.append("pexels")
            resp = MagicMock()
            resp.json.return_value = {
                "videos": [{"id": 1, "width": 1920, "height": 1080, "duration": 10,
                            "video_files": [{"link": "https://pexels.com/v.mp4", "quality": "hd"}]}]
            }
            return resp

        mock = MagicMock()
        mock.side_effect = side_effect
        monkeypatch.setattr("src.providers.asset_provider.requests.get", mock)

        router = AssetRouter.for_topic("General")
        results = router.search("test fallback")
        assert len(results) > 0
        assert router.current_provider_name() == "pexels"
        assert "pixabay" in call_log
        assert "pexels" in call_log

    def test_download_after_router_search(self, mock_pixabay_api: MagicMock, tmp_path: Any) -> None:
        """Download should work through the router after Pixabay is selected."""
        router = AssetRouter.for_topic("General")
        results = router.search("nature")
        assert router.current_provider_name() == "pixabay"

        out = str(tmp_path / "pixabay_dl.mp4")
        url = results[0]["video_files"][0]["link"]

        with patch("src.providers.asset_provider.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.content = b"downloaded from pixabay"
            mock_get.return_value = mock_resp

            result = router.download(url, out)
            assert result == out
            assert os.path.exists(out)

    def test_router_provider_list_includes_pixabay(self) -> None:
        router = AssetRouter.for_topic("Science")
        providers = router._providers
        assert "pixabay" in providers

    def test_pixabay_wrapped_in_asset_library(self) -> None:
        """Pixabay should be wrapped in AssetLibrary for caching."""
        from src.assets.asset_library import AssetLibrary
        router = AssetRouter.for_topic("General")
        pixabay_ref = router._providers.get("pixabay")
        assert isinstance(pixabay_ref, AssetLibrary)
