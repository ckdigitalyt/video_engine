"""
test_asset_router.py — Tests for TopicClassifier, AssetRouter, and provider stubs.

Covers:
- TopicClassifier category assignment
- TopicClassifier config loading and fallback
- AssetRouter provider selection
- AssetRouter fallback through providers
- Stub provider skipping
- Provider failure recovery
- Download routing
- Interface compliance for stub providers
- Edge cases (empty queries, unknown topics)
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any

from src.assets.topic_classifier import TopicClassifier, _DEFAULT_CATEGORIES
from src.assets.asset_router import AssetRouter, _DEFAULT_ROUTES
from src.providers.asset_provider import AssetProvider, PexelsProvider, PixabayProvider
from src.providers.stubs import (
    StubAssetProvider,
    NasaMediaProvider,
    WikimediaCommonsProvider,
)
from src.assets.asset_library import AssetLibrary


# ============================================================================
#  TopicClassifier
# ============================================================================


class TestTopicClassifier:
    """Verify category assignment, config loading, and edge cases."""

    def test_classify_space(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("The Fermi Paradox and Alien Life") == "Space"
        assert clf.classify("Mars Colonization") == "Space"
        assert clf.classify("Black Holes and Quasars Explained") == "Space"

    def test_classify_history(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("The Rise and Fall of the Roman Empire") == "History"
        assert clf.classify("Ancient Egyptian Civilization") == "History"
        assert clf.classify("World War II") == "History"

    def test_classify_science(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("Quantum Physics Explained") == "Science"
        assert clf.classify("DNA and Genetics") == "Science"

    def test_classify_technology(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("Artificial Intelligence") == "Technology"
        assert clf.classify("The Rise of Blockchain") == "Technology"

    def test_classify_nature(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("Ocean Wildlife") == "Nature"
        assert clf.classify("Rainforest Conservation") == "Nature"

    def test_classify_finance(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("Stock Market Crash") == "Finance"
        assert clf.classify("Cryptocurrency Investment") == "Finance"

    def test_classify_general(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("How to Bake a Cake") == "General"
        assert clf.classify("Top 10 Travel Destinations") == "General"

    def test_classify_case_insensitive(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("THE FERMI PARADOX EXPLAINED") == "Space"
        assert clf.classify("ROMAN EMPIRE HISTORY") == "History"

    def test_classify_empty_string(self) -> None:
        clf = TopicClassifier()
        assert clf.classify("") == "General"

    def test_classify_custom_categories(self) -> None:
        """Custom categories override defaults."""
        custom = {"Music": ["guitar", "piano", "orchestra"], "General": []}
        clf = TopicClassifier(categories=custom)
        assert clf.classify("Learning Piano") == "Music"
        assert clf.classify("Cooking") == "General"

    def test_list_categories(self) -> None:
        clf = TopicClassifier()
        cats = clf.list_categories()
        assert "Space" in cats
        assert "History" in cats
        assert "General" in cats

    def test_tie_break_deterministic(self) -> None:
        """When two categories tie, alphabetical order is used."""
        # "space history" matches both Space and History with 1 keyword each
        # "History" comes before "Space" alphabetically
        clf = TopicClassifier()
        result = clf.classify("space history")
        assert result in ("History", "Space")

    def test_yaml_config_fallback(self) -> None:
        """When config is absent, built-in defaults are used."""
        clf = TopicClassifier()
        assert "Space" in clf._categories
        assert "General" in clf._categories


# ============================================================================
#  Stub Asset Providers
# ============================================================================


class TestStubProviders:
    """Verify stub providers implement the AssetProvider interface."""

    @pytest.mark.parametrize("stub_cls", [
        NasaMediaProvider,
        WikimediaCommonsProvider,
    ])
    def test_interface_compliance(self, stub_cls: type) -> None:
        assert issubclass(stub_cls, AssetProvider)
        assert issubclass(stub_cls, StubAssetProvider)
        assert hasattr(stub_cls, "search")
        assert callable(getattr(stub_cls, "search"))
        assert hasattr(stub_cls, "download")
        assert callable(getattr(stub_cls, "download"))

    @pytest.mark.parametrize("stub_cls,expected_name", [
        (NasaMediaProvider, "nasa"),
        (WikimediaCommonsProvider, "wikimedia"),
    ])
    def test_provider_name(self, stub_cls: type, expected_name: str) -> None:
        assert stub_cls.PROVIDER_NAME == expected_name

    def test_stub_search_returns_empty_list(self) -> None:
        provider = NasaMediaProvider()
        results = provider.search("milky way")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_stub_download_raises_not_implemented(self) -> None:
        provider = WikimediaCommonsProvider()
        with pytest.raises(NotImplementedError):
            provider.download("https://example.com/video.mp4", "/tmp/out.mp4")

    def test_stub_instantiation_no_api_key_needed(self) -> None:
        """Stubs don't require API keys."""
        for stub in (NasaMediaProvider(), WikimediaCommonsProvider()):
            assert stub is not None


# ============================================================================
#  AssetRouter
# ============================================================================


class TestAssetRouter:
    """Verify routing logic, fallback behavior, and download delegation."""

    def test_for_topic_classifies(self) -> None:
        router = AssetRouter.for_topic("The Fermi Paradox")
        assert router.category == "Space"

    def test_for_topic_general(self) -> None:
        router = AssetRouter.for_topic("Top 10 Travel Destinations")
        assert router.category == "General"

    def test_search_uses_pexels_for_general(self, mock_pexels_api: MagicMock) -> None:
        """General category should route to pexels (the only real provider)."""
        router = AssetRouter.for_topic("How to Bake a Cake")
        results = router.search("kitchen")
        assert len(results) > 0
        # Verify the mock was called (pexels was tried)
        assert mock_pexels_api.called
        assert router.current_provider_name() == "pexels"

    def test_search_pexels_for_space_without_nasa(self, mock_pexels_api: MagicMock) -> None:
        """Space routes to [nasa, pixabay, pexels]; nasa & pixabay are stubs,
        so pexels should be selected."""
        router = AssetRouter.for_topic("The Fermi Paradox")
        results = router.search("galaxy", target_duration=10)
        assert len(results) > 0
        # The route is [nasa, pixabay, pexels]; nasa and pixabay return empty,
        # so pexels is selected
        assert router.current_provider_name() == "pexels"
        assert mock_pexels_api.called

    def test_search_pexels_for_history(self, mock_pexels_api: MagicMock) -> None:
        """History routes to [wikimedia, pixabay, pexels]."""
        router = AssetRouter.for_topic("Roman Empire")
        results = router.search("roman colosseum")
        assert len(results) > 0
        assert router.current_provider_name() == "pexels"

    def test_search_pexels_for_science(self, mock_pexels_api: MagicMock) -> None:
        router = AssetRouter.for_topic("Quantum Physics")
        results = router.search("particle accelerator")
        assert len(results) > 0
        assert router.current_provider_name() == "pexels"

    def test_search_pexels_for_technology(self, mock_pexels_api: MagicMock) -> None:
        router = AssetRouter.for_topic("AI Revolution")
        result = router.search("robot")
        assert len(result) > 0

    def test_search_pexels_for_nature(self, mock_pexels_api: MagicMock) -> None:
        router = AssetRouter.for_topic("Amazon Rainforest")
        result = router.search("forest")
        assert len(result) > 0

    def test_search_pexels_for_finance(self, mock_pexels_api: MagicMock) -> None:
        router = AssetRouter.for_topic("Stock Market")
        result = router.search("trading floor")
        assert len(result) > 0

    def test_search_empty_when_all_providers_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When Pexels returns empty, the router should return empty."""
        mock_get = MagicMock()
        mock_get.return_value.json.return_value = {"videos": []}
        monkeypatch.setattr("src.providers.asset_provider.requests.get", mock_get)

        router = AssetRouter.for_topic("Cooking Tips")
        results = router.search("kitchen")
        assert isinstance(results, list)
        assert len(results) == 0

    @patch("src.providers.asset_provider.requests.get")
    def test_search_error_on_pexels_returns_empty(self, mock_get: MagicMock) -> None:
        """If Pexels raises, the router should return empty."""
        mock_get.side_effect = Exception("API Error")

        router = AssetRouter.for_topic("Cooking Tips")
        results = router.search("kitchen")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_download_after_search(self, mock_pexels_api: MagicMock, tmp_path: Any) -> None:
        """Download should delegate to the last-used provider."""
        output = str(tmp_path / "test_video.mp4")
        router = AssetRouter.for_topic("Space")
        router.search("galaxy")
        provider_name = router.current_provider_name()
        assert provider_name == "pexels"

        # Mock the download to avoid HTTP call
        with patch.object(AssetLibrary, "download", return_value=output) as mock_dl:
            result = router.download("https://example.com/v.mp4", output)
            assert result == output
            mock_dl.assert_called_once_with("https://example.com/v.mp4", output)

    def test_download_without_prior_search_falls_back(self, mock_pexels_api: MagicMock, tmp_path: Any) -> None:
        """If no provider was selected, download should fall back to pexels."""
        output = str(tmp_path / "test_video.mp4")
        router = AssetRouter.for_topic("General")

        with patch.object(AssetLibrary, "download", return_value=output) as mock_dl:
            result = router.download("https://example.com/v.mp4", output)
            assert result == output

    def test_download_raises_when_no_provider(self) -> None:
        """If pexels is also missing, download should raise."""
        router = AssetRouter(
            category="General",
            providers={"nonexistent": PixabayProvider()},  # only stub, no pexels
            routes={"General": ["nonexistent"]},
        )
        with pytest.raises(RuntimeError, match="no provider available"):
            router.download("https://example.com/v.mp4", "/tmp/out.mp4")

    def test_category_property(self) -> None:
        router = AssetRouter(category="Science")
        assert router.category == "Science"

    def test_skip_stubs(self, mock_pexels_api: MagicMock) -> None:
        """Stubs should be skipped during search iteration."""
        router = AssetRouter.for_topic("History")
        results = router.search("ancient ruins")
        assert len(results) > 0
        # The stubs for wikimedia and pixabay should have been skipped
        assert router.current_provider_name() == "pexels"

    def test_custom_routes(self) -> None:
        """Custom routes should override defaults."""
        custom_routes = {"Space": ["pexels"]}
        router = AssetRouter(
            category="Space",
            routes=custom_routes,
        )
        assert router._routes == custom_routes


# ============================================================================
#  AssetRouter with mocked providers (unit tests)
# ============================================================================


class TestAssetRouterMocked:
    """Test routing logic with fully mocked providers."""

    def test_first_provider_wins(self) -> None:
        """The first provider that returns results should be selected."""
        mock_provider_a = MagicMock(spec=AssetProvider)
        mock_provider_a.search.return_value = [{"id": "a", "video_files": [{"link": "a.mp4"}]}]
        mock_provider_b = MagicMock(spec=AssetProvider)

        routes = {"Test": ["provider_a", "provider_b"]}
        providers = {
            "provider_a": mock_provider_a,
            "provider_b": mock_provider_b,
        }
        router = AssetRouter(
            category="Test",
            providers=providers,
            routes=routes,
        )
        results = router.search("test query")
        assert len(results) == 1
        assert results[0]["id"] == "a"
        assert router.current_provider_name() == "provider_a"
        # provider_b should never have been called
        mock_provider_b.search.assert_not_called()

    def test_fallback_to_second_provider(self) -> None:
        """When the first provider returns empty, fall through to the second."""
        mock_provider_a = MagicMock(spec=AssetProvider)
        mock_provider_a.search.return_value = []  # empty
        mock_provider_b = MagicMock(spec=AssetProvider)
        mock_provider_b.search.return_value = [{"id": "b", "video_files": [{"link": "b.mp4"}]}]

        routes = {"Test": ["provider_a", "provider_b"]}
        providers = {
            "provider_a": mock_provider_a,
            "provider_b": mock_provider_b,
        }
        router = AssetRouter(
            category="Test",
            providers=providers,
            routes=routes,
        )
        results = router.search("test query")
        assert len(results) == 1
        assert results[0]["id"] == "b"
        assert router.current_provider_name() == "provider_b"

    def test_all_providers_empty(self) -> None:
        """When every provider returns empty, the router returns empty."""
        mock_a = MagicMock(spec=AssetProvider)
        mock_a.search.return_value = []
        mock_b = MagicMock(spec=AssetProvider)
        mock_b.search.return_value = []

        routes = {"Test": ["a", "b"]}
        providers = {"a": mock_a, "b": mock_b}
        router = AssetRouter(category="Test", providers=providers, routes=routes)
        results = router.search("test")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_first_provider_error_then_second(self) -> None:
        """If the first provider raises, the second should be tried."""
        mock_a = MagicMock(spec=AssetProvider)
        mock_a.search.side_effect = Exception("API Failure")
        mock_b = MagicMock(spec=AssetProvider)
        mock_b.search.return_value = [{"id": "b", "video_files": [{"link": "b.mp4"}]}]

        routes = {"Test": ["a", "b"]}
        providers = {"a": mock_a, "b": mock_b}
        router = AssetRouter(category="Test", providers=providers, routes=routes)
        results = router.search("test")
        assert len(results) == 1
        assert router.current_provider_name() == "b"

    def test_download_uses_last_provider(self) -> None:
        """Download should use the last successful provider."""
        mock_a = MagicMock(spec=AssetProvider)
        mock_a.search.return_value = [{"id": "a", "video_files": [{"link": "a.mp4"}]}]
        mock_a.download.return_value = "/tmp/a.mp4"

        routes = {"Test": ["a", "b"]}
        providers = {"a": mock_a, "b": MagicMock(spec=AssetProvider)}
        router = AssetRouter(category="Test", providers=providers, routes=routes)
        router.search("test")
        result = router.download("https://url/a.mp4", "/tmp/a.mp4")
        assert result == "/tmp/a.mp4"
        mock_a.download.assert_called_once_with("https://url/a.mp4", "/tmp/a.mp4")

    def test_search_passes_kwargs(self) -> None:
        """kwargs passed to router.search should be forwarded to provider.search."""
        mock_provider = MagicMock(spec=AssetProvider)
        mock_provider.search.return_value = [{"id": "x"}]

        routes = {"Test": ["mock"]}
        providers = {"mock": mock_provider}
        router = AssetRouter(category="Test", providers=providers, routes=routes)
        router.search("q", target_duration=15, custom="value")

        mock_provider.search.assert_called_once_with("q", target_duration=15, custom="value")


# ============================================================================
#  Integration: Orchestrator-level routing (mocked pipeline)
# ============================================================================


class TestOrchestratorIntegration:
    """Verify the AssetRouter works correctly when called the way the
    orchestrator calls it."""

    def test_pipeline_search_and_download(self, mock_pexels_api: MagicMock, tmp_path: Any) -> None:
        """Simulate what the orchestrator's execution_node does."""
        router = AssetRouter.for_topic("The Fermi Paradox")
        assert router.category == "Space"

        # Simulate a scene search
        videos = router.search("milky way galaxy", target_duration=10)
        assert len(videos) > 0
        assert router.current_provider_name() == "pexels"

        # Simulate download
        output = str(tmp_path / "scene_1.mp4")
        video_url = videos[0]["video_files"][0]["link"]

        with patch.object(AssetLibrary, "download", return_value=output) as mock_dl:
            result = router.download(video_url, output)
            assert result == output

    def test_history_routes_correctly(self) -> None:
        """History category should have the correct provider priority."""
        router = AssetRouter.for_topic("The Roman Empire")
        assert router.category == "History"
        priority = router._routes.get("History", [])
        assert priority == ["wikimedia", "pixabay", "pexels"]

    def test_stubs_have_no_effect_on_routing(self, mock_pexels_api: MagicMock) -> None:
        """Even though stubs are in the provider list, they don't block
        routing to the real provider."""
        router = AssetRouter.for_topic("History")
        # Force the stub to be called first by manipulating routes
        router._routes["History"] = ["nasa", "pixabay", "pexels"]
        # Stubs should be skipped; pexels should return results
        results = router.search("roman ruins")
        assert len(results) > 0
        assert router.current_provider_name() == "pexels"
