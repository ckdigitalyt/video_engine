"""
test_visual_director.py — Tests for the Visual Director system.

Covers:
- VisualStyle creation and factory
- ConceptPlanner generation (LLM + fallback)
- AestheticAgent style classification and consistency
- QualityGates gating logic (semantic, reuse, aesthetic, duplicate)
- VisualDirector integration
- Critic fail-closed behaviour
"""

import json
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.models.schemas import AssetPlan, ProviderType


# ── VisualStyle Tests ──────────────────────────────────────────────────

class TestVisualStyle:
    """Global Visual Style creation and behaviour."""

    def test_default_style(self):
        from src.director.visual_style import VisualStyle
        s = VisualStyle()
        assert s.aesthetic == "photorealistic"
        assert s.mood == "neutral"
        assert s.pace == "medium"
        assert len(s.color_palette) > 0

    def test_for_topic_space(self):
        from src.director.visual_style import VisualStyle
        s = VisualStyle.for_topic("The Fermi Paradox", "Space")
        assert s.aesthetic == "space"
        assert s.sub_aesthetic == "space"
        assert "nasa" in s.provider_prefs
        assert s.mood == "mysterious"

    def test_for_topic_history(self):
        from src.director.visual_style import VisualStyle
        s = VisualStyle.for_topic("Roman Empire", "History")
        assert s.aesthetic == "archival"
        assert "wikimedia" in s.provider_prefs

    def test_for_topic_without_category(self):
        from src.director.visual_style import VisualStyle
        s = VisualStyle.for_topic("Anything", None)
        assert s.aesthetic == "photorealistic"

    def test_describe(self):
        from src.director.visual_style import VisualStyle
        s = VisualStyle(aesthetic="cinematic", mood="dramatic")
        desc = s.describe()
        assert "Aesthetic: cinematic" in desc
        assert "Mood: dramatic" in desc

    def test_to_prompt(self):
        from src.director.visual_style import VisualStyle
        s = VisualStyle(aesthetic="cinematic", mood="dramatic")
        prompt = s.to_prompt()
        assert "cinematic" in prompt
        assert "dramatic" in prompt

    def test_for_topic_finance(self):
        from src.director.visual_style import VisualStyle
        s = VisualStyle.for_topic("Stock Market", "Finance")
        assert s.aesthetic == "educational"
        assert s.pace == "fast"


# ── ConceptPlanner Tests ───────────────────────────────────────────────

class TestConceptPlanner:
    """Concept-driven query generation."""

    def test_default_config(self):
        from src.director.concept_planner import ConceptPlanner
        p = ConceptPlanner()
        assert p.num_queries >= 5

    def test_fallback_generation(self):
        from src.director.concept_planner import ConceptPlanner
        p = ConceptPlanner(provider=None)
        queries = p.generate_queries(
            narration="Scientists study the galaxy",
            title="Deep Space",
            topic="The Fermi Paradox",
            purpose="exploration",
        )
        assert len(queries) >= 1
        assert all(isinstance(q, str) for q in queries)

    def test_llm_generation(self):
        from src.director.concept_planner import ConceptPlanner
        mock = MagicMock()
        mock.generate_json.return_value = json.dumps([
            "radio telescope at night",
            "Milky Way galaxy wide",
            "deep space nebula",
            "observatory dome silhouette",
            "satellite dish communication",
        ])
        p = ConceptPlanner(provider=mock, num_queries=5)
        queries = p.generate_queries("narration", "title", "topic")
        assert len(queries) == 5
        assert "radio telescope at night" in queries
        mock.generate_json.assert_called_once()

    def test_llm_error_fallback(self):
        from src.director.concept_planner import ConceptPlanner
        mock = MagicMock()
        mock.generate_json.side_effect = RuntimeError("API error")
        p = ConceptPlanner(provider=mock, num_queries=3)
        queries = p.generate_queries("test narration", "title", "topic")
        assert len(queries) >= 1  # falls back to keyword extraction

    def test_parse_queries(self):
        from src.director.concept_planner import ConceptPlanner
        raw = '["query one", "query two", "query three"]'
        result = ConceptPlanner._parse_queries(raw)
        assert len(result) == 3

    def test_parse_queries_with_fences(self):
        from src.director.concept_planner import ConceptPlanner
        raw = '```json\n["q1", "q2"]\n```'
        result = ConceptPlanner._parse_queries(raw)
        assert len(result) == 2

    def test_extract_keywords(self):
        from src.director.concept_planner import ConceptPlanner
        keywords = ConceptPlanner._extract_keywords(
            "Scientists discovered a new planet"
        )
        assert "scientists" in keywords
        assert "discovered" in keywords
        assert "planet" in keywords
        assert "the" not in keywords  # stop word
        assert "a" not in keywords


# ── AestheticAgent Tests ───────────────────────────────────────────────

class TestAestheticAgent:
    """Style classification and consistency checking."""

    @pytest.fixture
    def agent(self):
        from src.director.aesthetic_agent import AestheticAgent
        from src.director.visual_style import VisualStyle
        style = VisualStyle(aesthetic="photorealistic")
        return AestheticAgent(visual_style=style, enabled=True)

    def _make_asset(self, asset_id: str, provider: str = "pixabay", query: str = "test", score: float = 0.85) -> AssetPlan:
        return AssetPlan(
            provider=ProviderType(provider),
            filepath="",
            video_url="http://example.com/v.mp4",
            query_used=query,
            score=score,
            semantic_score=score,
            technical_score=score,
        )

    def test_first_asset_accepted(self, agent):
        ok, reason = agent.check_asset(
            self._make_asset("1"), "pixabay", "mountain nature", "Nature"
        )
        assert ok is True
        assert "first asset" in reason

    def test_same_provider_consistent(self, agent):
        agent.check_asset(self._make_asset("1"), "pixabay", "mountain", "Nature")
        ok, reason = agent.check_asset(self._make_asset("2"), "pixabay", "forest", "Nature")
        assert ok is True

    def test_wikimedia_historic_image(self, agent):
        """Wikimedia assets should be classified as historic_image."""
        ok, reason = agent.check_asset(
            self._make_asset("1", provider="wikimedia"), "wikimedia", "roman colosseum", "History"
        )
        assert ok is True
        # The agent tracking should say it was historic
        assert agent.history[-1] == "historic_image"

    def test_nasa_space_photo(self, agent):
        ok, reason = agent.check_asset(
            self._make_asset("1", provider="nasa"), "nasa", "mars surface", "Space"
        )
        assert ok is True
        assert agent.history[-1] == "space_photo"

    def test_disabled_returns_accepted(self):
        from src.director.aesthetic_agent import AestheticAgent
        agent = AestheticAgent(enabled=False)
        ok, reason = agent.check_asset(self._make_asset("1"), "pixabay", "test", "General")
        assert ok is True
        assert "disabled" in reason

    def test_reset(self, agent):
        agent.check_asset(self._make_asset("1"), "pixabay", "test", "General")
        assert len(agent.history) == 1
        agent.reset()
        assert len(agent.history) == 0

    def test_batch_check(self, agent):
        assets = [self._make_asset("1"), self._make_asset("2")]
        all_ok, reasons = agent.check_scene_assets(
            assets, ["pixabay", "pixabay"],
            ["mountain", "forest"],
            ["Nature", "Nature"],
        )
        assert all_ok is True
        assert len(reasons) == 2


# ── QualityGates Tests ────────────────────────────────────────────────

class TestQualityGates:
    """Hard quality gates."""

    @pytest.fixture
    def gates(self):
        from src.director.quality_gate import QualityGates
        return QualityGates(
            semantic_threshold=0.75,
            reuse_window=3,
        )

    def _make_asset(self, provider: str = "pixabay", query: str = "galaxy", score: float = 0.85, semantic_score: float = 0.85) -> AssetPlan:
        return AssetPlan(
            provider=ProviderType(provider),
            filepath="",
            video_url="http://example.com/v1.mp4",
            query_used=query,
            score=score,
            semantic_score=semantic_score,
            technical_score=score,
        )

    def test_all_gates_pass(self, gates):
        asset = self._make_asset(score=0.85)
        passed, reason, details = gates.check_all(asset=asset, category="Space")
        assert passed is True
        assert "semantic" in details
        assert details["semantic"]["passed"] is True

    def test_semantic_gate_fails(self, gates):
        asset = self._make_asset(score=0.5, semantic_score=0.5)
        passed, reason, details = gates.check_all(asset=asset, category="Space")
        assert passed is False
        assert "semantic" in reason
        assert details["semantic"]["passed"] is False

    def test_reuse_gate_fails(self, gates):
        asset = self._make_asset(score=0.85)
        # First pass: should succeed
        gates.check_all(asset=asset, category="Space")

        # Second pass with same asset: reuse gate should trigger
        passed, reason, details = gates.check_all(asset=asset, category="Space")
        assert passed is False
        assert "reuse" in reason or "duplicate" in reason

    def test_duplicate_gate_by_id(self, gates):
        asset1 = AssetPlan(
            provider=ProviderType.PIXABAY,
            filepath="",
            video_url="http://example.com/v1.mp4",
            query_used="q1",
            score=0.85,
            semantic_score=0.85,
            technical_score=0.85,
        )
        asset2 = AssetPlan(
            provider=ProviderType.PIXABAY,
            filepath="",
            video_url="http://example.com/v2.mp4",
            query_used="q1",
            score=0.85,
            semantic_score=0.85,
            technical_score=0.85,
        )
        gates.check_all(asset1, category="Space")
        passed, reason, details = gates.check_all(asset2, category="Space")
        assert passed is False
        assert "reuse" in reason

    def test_check_all_details_structure(self, gates):
        """Details dict should have per-gate entries."""
        asset = self._make_asset(score=0.85)
        passed, reason, details = gates.check_all(asset=asset, category="Space")
        assert "semantic" in details
        assert "aesthetic" in details
        assert "reuse" in details
        assert "duplicate" in details

    def test_reset(self, gates):
        asset = self._make_asset(score=0.85)
        gates.check_all(asset=asset, category="Space")
        gates.reset()
        passed, reason, details = gates.check_all(asset=asset, category="Space")
        assert passed is True  # After reset, asset is not tracked


# ── Critic Fail-Closed Tests ──────────────────────────────────────────

class TestCriticFailClosed:
    """Critic must fail closed on errors."""

    @patch("orchestrator.gemini")
    def test_api_error_sets_approved_false(self, mock_gemini):
        """Simulate an API error — critic must NOT auto-approve."""
        from orchestrator import critic_node, AgentState
        mock_gemini.generate_text.side_effect = RuntimeError("API unavailable")

        state = AgentState(
            topic="test",
            output_path="final_output.mp4",
            plan_json="{}",
            timeline_json="{}",
            iteration=1,
            approved=False,
            critic_result="",
            subtitle_timeline=[],
        )
        result = critic_node(state)
        assert result["approved"] is False

    @patch("orchestrator.gemini")
    def test_auth_error_sets_approved_false(self, mock_gemini):
        """Authentication errors must NOT auto-approve."""
        from google.api_core.exceptions import PermissionDenied
        from orchestrator import critic_node, AgentState

        mock_gemini.generate_text.side_effect = PermissionDenied("invalid key")

        state = AgentState(
            topic="test",
            output_path="final_output.mp4",
            plan_json="{}",
            timeline_json="{}",
            iteration=1,
            approved=False,
            critic_result="",
            subtitle_timeline=[],
        )
        result = critic_node(state)
        assert result["approved"] is False

    @patch("orchestrator.gemini")
    def test_config_error_sets_approved_false(self, mock_gemini):
        """Config errors (model not found) must NOT auto-approve."""
        from google.api_core.exceptions import NotFound
        from orchestrator import critic_node, AgentState

        mock_gemini.generate_text.side_effect = NotFound("model not found")

        state = AgentState(
            topic="test",
            output_path="final_output.mp4",
            plan_json="{}",
            timeline_json="{}",
            iteration=1,
            approved=False,
            critic_result="",
            subtitle_timeline=[],
        )
        result = critic_node(state)
        assert result["approved"] is False


# ── VisualDirector Integration Tests ──────────────────────────────────

class TestVisualDirector:
    """VisualDirector integration with mocked components."""

    def test_director_initialization(self):
        """Verify the director can be created with mock dependencies."""
        from src.director.director import VisualDirector
        from src.director.visual_style import VisualStyle

        director = VisualDirector(
            topic="The Fermi Paradox",
            llm_provider=None,
            scene_data=[{
                "scene_id": 1,
                "narration": "Test narration",
                "search_query": "test query",
                "scene_title": "Test Scene",
                "purpose": "general",
            }],
        )
        assert isinstance(director.style, VisualStyle)
        assert director.style.aesthetic == "space"
        assert "nasa" in director.style.provider_prefs

    def test_director_processes_scene(self):
        """Verify the director can process a scene (mocked search)."""
        from src.director.director import VisualDirector
        from src.assets.asset_router import AssetRouter

        mock_llm = MagicMock()
        mock_llm.generate_text.return_value = "This is a regenerated narration."

        # We need to mock the router's methods, not patch the class attribute
        director = VisualDirector(
            topic="test",
            llm_provider=mock_llm,
            scene_data=[{
                "scene_id": 1,
                "narration": "Test narration",
                "search_query": "test query",
                "scene_title": "Test",
                "purpose": "general",
            }],
        )

        # Replace router with a mock
        director._router = MagicMock()
        director._router.multi_query_search.return_value = {
            "assets": [{
                "id": "1",
                "video_files": [{"link": "http://example.com/v1.mp4"}],
                "_raw": {"tags": "test footage"},
            }],
            "selected_query": "test query",
            "provider_name": "pixabay",
            "selected_score": 0.85,
            "query_log": [],
        }
        director._router.category = "General"
        director._router.download.return_value = "/tmp/test.mp4"

        # We expect fallback since download paths won't exist
        results = director.run()
        assert len(results) == 1
        assert results[0].scene_id == 1

    def test_narration_regeneration(self):
        """Verify the director can regenerate narration."""
        from src.director.director import VisualDirector

        mock_llm = MagicMock()
        mock_llm.generate_text.return_value = (
            "A completely rewritten narration with visual details."
        )

        director = VisualDirector(
            topic="test",
            llm_provider=mock_llm,
            scene_data=[],
        )
        new_text = director._regenerate_narration(1, "Old narration")
        assert "rewritten narration" in new_text.lower()
