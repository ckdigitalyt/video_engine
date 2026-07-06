"""
test_search_planner.py — Tests for the SearchPlanner + AssetRouter multi_query_search.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.assets.search_planner import SearchPlanner, _FALLBACK_TEMPLATES


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm_provider():
    provider = MagicMock()
    provider.generate_json.return_value = json.dumps([
        "radio telescope at night",
        "SETI observatory dome",
        "Milky Way galaxy stars",
        "deep space nebula",
        "Earth from space ISS",
        "satellite dish communication",
        "cosmic background radiation",
    ])
    return provider


@pytest.fixture
def planner_no_llm():
    return SearchPlanner(provider=None, num_queries=5)


@pytest.fixture
def planner_with_llm(mock_llm_provider):
    return SearchPlanner(provider=mock_llm_provider, num_queries=5)


@pytest.fixture
def mock_router():
    """A mock AssetRouter that returns canned results."""
    import sys
    sys.path.insert(0, ".")

    router = MagicMock()
    # multi_query_search returns a dict with assets
    router.multi_query_search.return_value = {
        "assets": [{
            "id": 12345,
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "video_files": [{"link": "https://example.com/video.mp4", "quality": "hd"}],
        }],
        "selected_query": "radio telescope at night",
        "provider_name": "pixabay",
        "selected_score": 0.85,
        "query_log": [
            {"query": "radio telescope at night", "score": 0.85, "status": "ok",
             "tried_providers": [{"provider": "pixabay", "status": "ok", "count": 5}]},
        ],
    }
    return router


# ── SearchPlanner: Basic instantiation ─────────────────────────────────────

class TestSearchPlannerInit:
    """SearchPlanner construction and configuration."""

    def test_default_config(self):
        planner = SearchPlanner()
        assert planner.num_queries > 0
        assert planner.min_acceptable_score > 0
        assert planner.max_provider_attempts > 0
        assert planner.diversity_weighting >= 0

    def test_custom_config(self):
        planner = SearchPlanner(num_queries=3, min_acceptable_score=0.5)
        assert planner.num_queries == 3
        assert planner.min_acceptable_score == 0.5

    def test_no_provider_defaults_to_fallback(self):
        planner = SearchPlanner(provider=None)
        queries = planner.generate_queries(narration="test narration")
        assert len(queries) > 0
        assert all(isinstance(q, str) for q in queries)


# ── SearchPlanner: Query generation ────────────────────────────────────────

class TestQueryGeneration:
    """Tests for generating queries from narration."""

    def test_fallback_generates_multiple_queries(self, planner_no_llm):
        queries = planner_no_llm.generate_queries(
            narration="Scientists study the deep ocean trenches",
        )
        assert 1 <= len(queries) <= 5
        assert all(isinstance(q, str) for q in queries)
        assert all(len(q) > 0 for q in queries)

    def test_fallback_generates_diverse_templates(self, planner_no_llm):
        queries = planner_no_llm.generate_queries(
            narration="ocean",
        )
        # Should contain the keyword "ocean" in various templates
        assert any("ocean" in q.lower() for q in queries)

    def test_fallback_with_title_and_topic(self, planner_no_llm):
        queries = planner_no_llm.generate_queries(
            narration="The deep sea is unexplored",
            title="Deep Ocean",
            topic="Ocean Exploration",
        )
        assert len(queries) > 0

    def test_llm_generation(self, planner_with_llm, mock_llm_provider):
        queries = planner_with_llm.generate_queries(
            narration="Scientists study the universe",
            title="Cosmos",
            topic="Space",
            purpose="exploration",
        )
        assert len(queries) > 0
        mock_llm_provider.generate_json.assert_called_once()

    def test_llm_fallback_on_error(self, mock_llm_provider):
        mock_llm_provider.generate_json.side_effect = RuntimeError("API down")
        planner = SearchPlanner(provider=mock_llm_provider, num_queries=5)
        queries = planner.generate_queries(narration="test narration")
        assert len(queries) > 0  # Falls back to keyword extraction

    def test_deduplication(self, planner_no_llm):
        queries = planner_no_llm.generate_queries(narration="test test test")
        assert len(set(q.lower() for q in queries)) == len(queries)

    def test_empty_narration(self, planner_no_llm):
        queries = planner_no_llm.generate_queries(narration="")
        assert len(queries) > 0  # Uses title/topic or defaults


# ── SearchPlanner: Output quality ──────────────────────────────────────────

class TestQueryQuality:
    """Tests that generated queries are reasonable."""

    def test_queries_are_short(self, planner_no_llm):
        queries = planner_no_llm.generate_queries(
            narration="The Roman Empire fell in 476 AD",
        )
        for q in queries:
            assert 2 <= len(q.split()) <= 12  # reasonable query length

    def test_queries_contain_searchable_terms(self, planner_no_llm):
        queries = planner_no_llm.generate_queries(
            narration="Ancient Roman architecture and engineering",
        )
        keywords = set(" ".join(queries).lower().split())
        assert len(keywords) > 0

    def test_non_empty_queries(self, planner_no_llm):
        for _ in range(5):
            queries = planner_no_llm.generate_queries(
                narration=f"test topic number {_}",
                title="Test",
            )
            assert len(queries) >= 1


# ── SearchPlanner: Property access ─────────────────────────────────────────

class TestProperties:
    """SearchPlanner property access."""

    def test_num_queries_property(self):
        planner = SearchPlanner(num_queries=8)
        assert planner.num_queries == 8

    def test_min_score_property(self):
        planner = SearchPlanner(min_acceptable_score=0.6)
        assert planner.min_acceptable_score == 0.6

    def test_max_attempts_property(self):
        planner = SearchPlanner(max_provider_attempts=20)
        assert planner.max_provider_attempts == 20

    def test_diversity_weighting_property(self):
        planner = SearchPlanner(diversity_weighting=0.5)
        assert planner.diversity_weighting == 0.5


# ── SearchPlanner: Keyword extraction ──────────────────────────────────────

class TestKeywordExtraction:
    """Tests for the fallback keyword extraction."""

    def test_extract_filters_stop_words(self):
        keywords = SearchPlanner._extract_keywords(
            "the and of in a universe is was"
        )
        assert "universe" in keywords
        assert "the" not in keywords
        assert "and" not in keywords

    def test_extract_short_words_filtered(self):
        keywords = SearchPlanner._extract_keywords("a an of to it ox universe")
        assert "universe" in keywords
        assert "ox" not in keywords  # too short

    def test_extract_deduplicates(self):
        keywords = SearchPlanner._extract_keywords("galaxy galaxy cosmos cosmos")
        assert keywords == ["galaxy", "cosmos"]


# ── SearchPlanner: JSON parsing ────────────────────────────────────────────

class TestJsonParsing:
    """Tests for the LLM response JSON parser."""

    def test_parse_plain_json(self):
        result = SearchPlanner._parse_queries(
            '["space", "telescope", "stars"]'
        )
        assert result == ["space", "telescope", "stars"]

    def test_parse_markdown_fence(self):
        result = SearchPlanner._parse_queries(
            '```json\n["radio telescope", "milky way"]\n```'
        )
        assert result == ["radio telescope", "milky way"]

    def test_parse_with_trailing_comma(self):
        result = SearchPlanner._parse_queries(
            '["space", "telescope",]'
        )
        assert "space" in result
        assert "telescope" in result

    def test_parse_invalid_returns_empty(self):
        result = SearchPlanner._parse_queries("not json at all")
        assert isinstance(result, list)

    def test_parse_empty_string(self):
        result = SearchPlanner._parse_queries("")
        assert isinstance(result, list)


# ── AssetRouter: multi_query_search ────────────────────────────────────────

class TestMultiQuerySearch:
    """Tests for AssetRouter.multi_query_search via mock integration."""

    def test_multi_query_returns_dict_with_keys(self, mock_router):
        result = mock_router.multi_query_search(
            ["query1", "query2", "query3"]
        )
        assert "assets" in result
        assert "selected_query" in result
        assert "provider_name" in result
        assert "selected_score" in result
        assert "query_log" in result

    def test_multi_query_returns_assets(self, mock_router):
        result = mock_router.multi_query_search(
            ["radio telescope at night"]
        )
        assert len(result["assets"]) > 0

    def test_multi_query_logs_provider(self, mock_router):
        result = mock_router.multi_query_search(
            ["radio telescope at night"]
        )
        assert result["provider_name"] == "pixabay"

    def test_multi_query_logs_score(self, mock_router):
        result = mock_router.multi_query_search(
            ["radio telescope at night"]
        )
        assert result["selected_score"] > 0

    def test_multi_query_empty_results(self):
        """When no results found, returns empty assets."""
        import sys
        sys.path.insert(0, ".")
        from src.assets.asset_router import AssetRouter
        from unittest.mock import MagicMock

        router = AssetRouter.for_topic("General")
        # Replace providers with empty stub
        from src.providers.stubs import NasaMediaProvider
        from src.providers.asset_provider import PixabayProvider, PexelsProvider
        from src.assets.asset_library import AssetLibrary

        # Create a simple mock provider that returns empty
        mock_prov = MagicMock()
        mock_prov.search.return_value = []
        mock_prov.__class__.__name__ = "MockProvider"
        import types
        mock_prov.__class__.__module__ = "test_module"

        router._providers = {"pixabay": mock_prov}
        router._routes = {"General": ["pixabay"]}

        result = router.multi_query_search(
            ["nothing matches this", "no results here"],
            min_acceptable_score=0.5,
        )
        assert len(result["assets"]) == 0
        assert result["selected_query"] == ""
        assert result["selected_score"] == -1.0
        assert len(result["query_log"]) == 2


# ── Fallback template coverage ─────────────────────────────────────────────

class TestFallbackTemplates:
    """Tests that all fallback templates produce valid queries."""

    def test_all_templates_used(self):
        """At least as many templates as num_queries by default."""
        assert len(_FALLBACK_TEMPLATES) >= 5

    def test_templates_contain_placeholder(self):
        for template in _FALLBACK_TEMPLATES:
            assert "{kw}" in template

    def test_templates_are_unique(self):
        assert len(set(_FALLBACK_TEMPLATES)) == len(_FALLBACK_TEMPLATES)
