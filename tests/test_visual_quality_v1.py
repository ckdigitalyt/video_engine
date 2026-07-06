"""
test_visual_quality_v1.py — Tests for Visual Quality V1 components.

Tests cover:
- SemanticValidator (LLM + fallback)
- Duration verification (looping, slowing)
- Clip diversity (AssetLibrary penalty tracking)
- Smart transitions (context-aware selection)
- NASA provider (mocked API)
- Wikimedia Commons provider (mocked API)
- Extended evaluator metrics
"""

import json
import os
import pytest
import tempfile
from unittest.mock import MagicMock, patch


# ── SemanticValidator Tests ─────────────────────────────────────────────

class TestSemanticValidator:
    """Semantic relevance validation."""

    def test_default_config(self):
        from src.validation.semantic_validator import SemanticValidator
        v = SemanticValidator()
        assert v._enabled is True
        assert 0.0 <= v._threshold <= 1.0
        assert v._max_attempts > 0

    def test_disabled_returns_perfect_score(self):
        from src.validation.semantic_validator import SemanticValidator
        v = SemanticValidator(enabled=False)
        score = v.score("test", "test", {})
        assert score == 1.0

    def test_fallback_scoring_same_tokens(self):
        from src.validation.semantic_validator import SemanticValidator
        v = SemanticValidator(enabled=True, provider=None)
        score = v.score(
            "Scientists study the galaxy",
            "milky way galaxy",
            {"_raw": {"tags": "galaxy space stars"}},
        )
        assert 0.0 < score <= 1.0

    def test_fallback_scoring_no_overlap(self):
        from src.validation.semantic_validator import SemanticValidator
        v = SemanticValidator(enabled=True, provider=None)
        score = v.score(
            "The stock market crashed",
            "cute puppy playing",
            {"tags": "dog park grass"},
        )
        assert 0.0 <= score < 0.5

    def test_is_acceptable(self):
        from src.validation.semantic_validator import SemanticValidator
        v = SemanticValidator(enabled=True, threshold=0.5)
        assert v.is_acceptable(0.75)
        assert not v.is_acceptable(0.25)

    def test_extract_tags_pexels_format(self):
        from src.validation.semantic_validator import SemanticValidator
        asset = {"tags": ["space", "galaxy", "stars"]}
        tags = SemanticValidator._extract_tags(asset)
        assert "space" in tags

    def test_extract_tags_pixabay_format(self):
        from src.validation.semantic_validator import SemanticValidator
        asset = {"_raw": {"tags": "nebula,cosmic,dust"}}
        tags = SemanticValidator._extract_tags(asset)
        assert "nebula" in tags

    def test_llm_scoring(self):
        from src.validation.semantic_validator import SemanticValidator
        mock = MagicMock()
        mock.generate_text.return_value = "0.85"
        v = SemanticValidator(provider=mock, enabled=True)
        score = v.score("test narration", "test query", {"_raw": {"tags": "test"}})
        assert score == 0.85
        mock.generate_text.assert_called_once()

    def test_llm_error_fallback(self):
        from src.validation.semantic_validator import SemanticValidator
        mock = MagicMock()
        mock.generate_text.side_effect = RuntimeError("API error")
        v = SemanticValidator(provider=mock, enabled=True)
        score = v.score("scientists study galaxy", "milky way", {"tags": "galaxy"})
        assert 0.0 <= score <= 1.0


# ── Duration Tests ─────────────────────────────────────────────────────

class TestDurationVerification:
    """Duration verification utilities."""

    def test_get_media_duration_missing_file(self):
        from src.utils.duration import get_media_duration
        assert get_media_duration("/nonexistent/file.mp4") == 0.0

    def test_ensure_video_duration_missing_file(self):
        from src.utils.duration import ensure_video_duration
        result = ensure_video_duration("/nonexistent/file.mp4", 10.0)
        assert result == "/nonexistent/file.mp4"

    @pytest.fixture
    def short_video(self):
        """Create a short test video using ffmpeg."""
        path = tempfile.mktemp(suffix=".mp4")
        # Generate a 2-second test video
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "color=c=blue:s=320x240:d=2",
             "-c:v", "libx264", "-preset", "ultrafast",
             path],
            capture_output=True, timeout=30,
        )
        yield path
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_get_media_duration_real_file(self, short_video):
        from src.utils.duration import get_media_duration
        dur = get_media_duration(short_video)
        assert 1.5 <= dur <= 3.0

    @pytest.mark.timeout(30)
    def test_loop_video(self, short_video):
        from src.utils.duration import _loop_video
        out_path = short_video.replace(".mp4", "_loop.mp4")
        result = _loop_video(short_video, 10.0, out_path)
        assert os.path.exists(result)
        # Check duration
        from src.utils.duration import get_media_duration
        dur = get_media_duration(result)
        assert 8.0 <= dur <= 12.0
        # Cleanup
        try:
            os.unlink(out_path)
        except OSError:
            pass

    def test_ensure_video_already_long_enough(self, short_video):
        """When video is already >= required, return unchanged."""
        from src.utils.duration import ensure_video_duration
        result = ensure_video_duration(short_video, 1.0)
        assert result == short_video


# ── Clip Diversity Tests ───────────────────────────────────────────────

class TestClipDiversity:
    """AssetLibrary diversity penalty tracking."""

    @pytest.fixture
    def mock_cache(self):
        cache = MagicMock()
        # Create a mock connection that returns empty results for _get_all_indexed
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn.execute.return_value = cursor
        cache._conn = conn
        return cache

    @pytest.fixture
    def library(self, mock_cache):
        from src.assets.asset_library import AssetLibrary
        from src.providers.asset_provider import PexelsProvider
        prov = MagicMock(spec=PexelsProvider)
        prov.search.return_value = [{"id": 1, "video_files": [{"link": "http://example.com/v1.mp4"}]}]
        prov.download.return_value = "/tmp/v1.mp4"
        lib = AssetLibrary(
            provider=prov, cache=mock_cache,
            diversity_enabled=True, recent_window=3,
            repeat_penalty=0.3,
        )
        lib._query_repeat_penalty = 0.15
        return lib

    def test_penalty_for_same_url(self, library):
        library._recent_asset_urls = ["http://example.com/v1.mp4"]
        penalty = library._compute_diversity_penalty("query", "http://example.com/v1.mp4")
        assert penalty == 0.3

    def test_penalty_for_same_query(self, library):
        library._recent_queries = ["milky way"]
        penalty = library._compute_diversity_penalty("milky way", "http://example.com/v2.mp4")
        assert penalty == 0.15

    def test_no_penalty_for_new_asset(self, library):
        library._recent_asset_urls = ["http://example.com/v1.mp4"]
        library._recent_queries = ["milky way"]
        penalty = library._compute_diversity_penalty("galaxy", "http://example.com/v3.mp4")
        assert penalty == 0.0

    def test_trim_window(self, library):
        library._recent_asset_urls = ["u1", "u2", "u3", "u4", "u5"]
        library._recent_queries = ["q1", "q2", "q3", "q4", "q5"]
        library._trim_window()
        assert len(library._recent_asset_urls) == 3
        assert library._recent_asset_urls == ["u3", "u4", "u5"]


# ── Smart Transitions Tests ─────────────────────────────────────────────

class TestSmartTransitions:
    """Context-aware transition selection."""

    @pytest.fixture
    def engine(self):
        from src.effects.transitions import TransitionEngine
        return TransitionEngine(
            enabled=True, default_transition="crossfade",
            duration=0.5, seed=42, smart_enabled=True,
        )

    def test_same_category_uses_cut(self, engine):
        t = engine._pick_smart(
            {"category": "Space", "provider": "pixabay"},
            {"category": "Space", "provider": "pexels"},
            index=1,
        )
        assert t == "cut"

    def test_same_provider_different_query(self, engine):
        t = engine._pick_smart(
            {"category": "Space", "provider": "pixabay", "query": "galaxy"},
            {"category": "History", "provider": "pixabay", "query": "colosseum"},
            index=1,
        )
        assert t == "dissolve"

    def test_different_category(self, engine):
        t = engine._pick_smart(
            {"category": "Space", "provider": "pixabay"},
            {"category": "History", "provider": "pexels"},
            index=1,
        )
        assert t == "fade"

    def test_same_asset_id(self, engine):
        t = engine._pick_smart(
            {"category": "Space", "provider": "pixabay", "asset_id": "123"},
            {"category": "Space", "provider": "pixabay", "asset_id": "123"},
            index=1,
        )
        assert t == "dissolve"

    def test_no_context_falls_to_default(self, engine):
        t = engine._pick_smart(None, None, index=1)
        assert t == "crossfade"

    def test_generate_smart(self, engine):
        contexts = [
            {"category": "Space", "provider": "nasa", "query": "nebula"},
            {"category": "Space", "provider": "pixabay", "query": "galaxy"},
            {"category": "History", "provider": "wikimedia", "query": "colosseum"},
        ]
        result = engine.generate_smart(clip_count=3, scene_contexts=contexts)
        assert len(result) == 3
        assert result[0]["type"] == "cut"  # First is always cut
        assert result[1]["type"] in ("cut", "dissolve", "fade")
        assert result[2]["type"] in ("cut", "dissolve", "fade")

    def test_generate_legacy_fallback(self):
        """With smart disabled, uses legacy random selection."""
        from src.effects.transitions import TransitionEngine
        engine = TransitionEngine(enabled=True, seed=42, smart_enabled=False)
        result = engine.generate(clip_count=3)
        assert len(result) == 3

    def test_single_clip_all_cut(self, engine):
        result = engine.generate_smart(clip_count=1)
        assert len(result) == 1
        assert result[0]["type"] == "cut"


# ── NASA Provider Tests ─────────────────────────────────────────────────

class TestNasaProvider:
    """Real NASA provider with mocked API."""

    @pytest.fixture
    def mock_nasa_response(self):
        return {
            "collection": {
                "items": [
                    {
                        "data": [{
                            "nasa_id": "GSFC_20171208_Archive_e001603",
                            "title": "Hubble Deep Field",
                            "description": "The Hubble Space Telescope",
                            "date_created": "2017-01-01",
                        }],
                        "links": [{"href": "https://images.nasa.gov/details-hubble.mp4"}],
                    },
                    {
                        "data": [{
                            "nasa_id": "PIA12345",
                            "title": "Milky Way Panorama",
                            "description": "Milky Way galaxy",
                            "date_created": "2018-01-01",
                        }],
                        "links": [{"href": "https://images.nasa.gov/details-milkyway.mp4"}],
                    },
                ]
            }
        }

    def test_search_normalises_items(self, mock_nasa_response):
        from src.providers.asset_provider import _normalise_nasa_items
        items = mock_nasa_response["collection"]["items"]
        results = _normalise_nasa_items(items)
        assert len(results) == 2
        assert results[0]["id"] == "GSFC_20171208_Archive_e001603"
        assert len(results[0]["video_files"]) == 1
        assert results[0]["video_files"][0]["link"] == "https://images.nasa.gov/details-hubble.mp4"

    @patch("requests.get")
    def test_search_no_apikey(self, mock_get):
        from src.providers.asset_provider import NasaMediaProvider
        mock_get.return_value.json.return_value = {"collection": {"items": []}}
        prov = NasaMediaProvider()
        # Just check it returns empty without errors
        results = prov.search("deep field")
        assert isinstance(results, list)

    @patch("requests.get")
    def test_download_cached(self, mock_get, tmp_path):
        from src.providers.asset_provider import NasaMediaProvider
        prov = NasaMediaProvider()
        out = tmp_path / "nasa_test.mp4"
        out.write_text("cached content")
        result = prov.download("https://test.url/video.mp4", str(out))
        assert result == str(out)
        mock_get.assert_not_called()


# ── Wikimedia Provider Tests ────────────────────────────────────────────

class TestWikimediaProvider:
    """Wikimedia Commons provider with mocked API."""

    @patch("requests.get")
    def test_search_returns_empty_for_empty_query(self, mock_get):
        from src.providers.asset_provider import WikimediaCommonsProvider
        prov = WikimediaCommonsProvider()
        results = prov.search("")
        assert results == []

    @patch("requests.get")
    def test_download_cached(self, mock_get, tmp_path):
        from src.providers.asset_provider import WikimediaCommonsProvider
        prov = WikimediaCommonsProvider()
        out = tmp_path / "wiki_test.jpg"
        out.write_text("cached content")
        result = prov.download("https://test.url/image.jpg", str(out))
        assert result == str(out)
        mock_get.assert_not_called()

    def test_provider_defaults_to_image_mode(self):
        from src.providers.asset_provider import WikimediaCommonsProvider
        prov = WikimediaCommonsProvider()
        assert prov._image_mode is True


# ── Evaluator Extended Metrics Tests ───────────────────────────────────

class TestExtendedMetrics:
    """Extended EvalSnapshot with V1 metrics."""

    def test_eval_snapshot_has_v1_fields(self):
        from src.evaluator.metrics import EvalSnapshot
        s = EvalSnapshot()
        assert hasattr(s, "semantic_score_avg")
        assert hasattr(s, "asset_diversity_penalties_applied")
        assert hasattr(s, "provider_usage")
        assert hasattr(s, "asset_reuse_percentage")
        assert hasattr(s, "avg_clip_length_s")
        assert hasattr(s, "avg_transition_duration_s")
        assert hasattr(s, "duration_adjustments")

    def test_semantic_scores_in_snapshot(self):
        from src.evaluator.metrics import MetricsCollector
        coll = MetricsCollector()
        snap = coll.snapshot(semantic_scores=[0.8, 0.6, 0.9])
        assert snap.semantic_score_avg == pytest.approx(0.767, rel=0.01)
        assert snap.semantic_scores == [0.8, 0.6, 0.9]

    def test_provider_usage_in_snapshot(self):
        from src.evaluator.metrics import MetricsCollector
        coll = MetricsCollector()
        snap = coll.snapshot(provider_usage={"pixabay": 7, "pexels": 3})
        assert snap.provider_usage["pixabay"] == 7

    def test_clip_lengths_in_snapshot(self):
        from src.evaluator.metrics import MetricsCollector
        coll = MetricsCollector()
        snap = coll.snapshot(clip_lengths=[10.0, 15.0, 12.0])
        assert snap.avg_clip_length_s == pytest.approx(12.3, rel=0.1)

    def test_transition_durations_in_snapshot(self):
        from src.evaluator.metrics import MetricsCollector
        coll = MetricsCollector()
        snap = coll.snapshot(transition_durations=[0.5, 0.3, 0.5])
        assert snap.avg_transition_duration_s == pytest.approx(0.43, rel=0.1)

    def test_duration_adjustments_in_snapshot(self):
        from src.evaluator.metrics import MetricsCollector
        coll = MetricsCollector()
        snap = coll.snapshot(duration_adjustments=3)
        assert snap.duration_adjustments == 3
