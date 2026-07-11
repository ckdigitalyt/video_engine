"""
test_v2_pipeline.py — Integration tests for the V2 pipeline.

Tests the LangGraph-wired pipeline with deterministic mocked providers.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.v2_types import (
    Fact,
    KnowledgeGraph,
    NarrativeArc,
    PipelineStateV2,
    ResearchDocument,
)
from src.orchestration.v2_pipeline import build_v2_pipeline
from src.research.research_agent import ResearchAgent
from src.research.knowledge_graph import KnowledgeGraphBuilder
from src.planner.story_planner_v2 import StoryPlannerV2


# ═══════════════════════════════════════════════════════════════════════ #
# Fixtures
# ═══════════════════════════════════════════════════════════════════════ #


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock LLMProvider.generate_json so all V2 modules get controlled responses."""
    responses: dict[str, str] = {}

    def set_response(key: str, value: str):
        responses[key] = value

    def mock_generate_json(self_obj, prompt: str, **kwargs):
        prompt_lower = prompt.lower()
        for key, value in responses.items():
            if key.lower() in prompt_lower:
                return value
        return responses.get("__default__", '{"edges": []}')

    monkeypatch.setattr(
        "src.providers.llm_provider.LLMProvider.generate_json",
        mock_generate_json,
    )
    return set_response


@pytest.fixture
def mock_web_search(monkeypatch):
    """Mock ResearchAgent._web_search."""
    def mock_search(self_obj, query: str):
        return [{"url": "https://example.com", "title": "Example", "snippet": "Factual snippet about the topic."}]
    monkeypatch.setattr("src.research.research_agent.ResearchAgent._web_search", mock_search)
    return mock_search


@pytest.fixture
def mock_web_fetch(monkeypatch):
    """Mock ResearchAgent._web_fetch."""
    def mock_fetch(self_obj, url: str, max_chars: int = 3000):
        return "Mocked fetched content about the topic with factual information."
    monkeypatch.setattr("src.research.research_agent.ResearchAgent._web_fetch", mock_fetch)
    return mock_fetch


@pytest.fixture
def mock_research_cache(tmp_path):
    """Isolate research cache to tmp."""
    cache_dir = tmp_path / "research_cache"
    cache_dir.mkdir()
    return cache_dir


# ═══════════════════════════════════════════════════════════════════════ #
# Pipeline integration tests
# ═══════════════════════════════════════════════════════════════════════ #


class TestV2PipelineIntegration:
    """End-to-end V2 pipeline integration tests."""

    def test_full_pipeline_happy_path(
        self, mock_llm, mock_web_search, mock_web_fetch, mock_research_cache, tmp_path,
    ):
        """End-to-end: Topic → Research → KG → Narrative via LangGraph."""
        # Stage the LLM responses for each V2 module
        # ResearchAgent: search queries + fact extraction
        mock_llm("queries", '["fermi paradox facts", "drake equation explained"]')
        mock_llm("extract", json.dumps({
            "facts": [{"claim": "The Fermi Paradox is named after physicist Enrico Fermi.", "confidence": 0.9}],
            "statistics": ["100 billion stars in the Milky Way"],
            "key_people": ["Enrico Fermi", "Frank Drake"],
            "key_dates": [{"date": "1950", "event": "Fermi asked the question"}],
        }))

        # KnowledgeGraphBuilder: entity extraction + relationship extraction
        mock_llm("extract all named entities", json.dumps({
            "concepts": [
                {"id": "c1", "label": "Fermi Paradox", "description": "Core concept"},
                {"id": "c2", "label": "Drake Equation", "description": "Mathematical estimate"},
            ],
            "people": [
                {"id": "p1", "label": "Enrico Fermi", "description": "Physicist"},
                {"id": "p2", "label": "Frank Drake", "description": "Astronomer"},
            ],
            "events": [],
            "dates": [{"id": "d1", "label": "1950", "description": "Fermi asked the question"}],
            "statistics": [{"id": "s1", "label": "100 billion stars", "description": "Stars in Milky Way"}],
            "places": [],
        }))
        mock_llm("identify relationships", json.dumps({
            "edges": [
                {"source_id": "p1", "target_id": "c1", "relationship": "proposed"},
                {"source_id": "p2", "target_id": "c2", "relationship": "proposed"},
            ],
        }))

        # StoryPlannerV2: framework selection + beat generation
        mock_llm("narrative framework", json.dumps({
            "framework": "mystery_reveal",
            "reasoning": "A paradox with multiple explanations.",
            "expected_tension_curve": "gradual_rise_plateau",
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "The Great Silence",
            "subtitle": "Why the Universe Isn't Talking Back",
            "logline": "A journey through the most profound question in science.",
            "beats": [
                {
                    "index": 0,
                    "role": "hook",
                    "hook_sentence": "The universe is completely silent.",
                    "core_message": "There is a contradiction between high probability estimates and no evidence.",
                    "emotional_tone": "wonder",
                    "knowledge_node_ids": ["c1", "p1"],
                    "target_duration_range": [60, 90],
                    "cliffhanger": "But why?",
                },
                {
                    "index": 1,
                    "role": "context",
                    "hook_sentence": "Let's understand the numbers.",
                    "core_message": "The Drake Equation estimates civilizations.",
                    "emotional_tone": "contemplative",
                    "knowledge_node_ids": ["c2", "p2"],
                    "target_duration_range": [45, 75],
                    "cliffhanger": "But where is everyone?",
                },
            ],
        }))

        # Build pipeline with injected components using isolated cache dirs
        kg_cache_dir = tmp_path / "kg_cache"
        narrative_cache_dir = tmp_path / "narrative_cache"
        kg_cache_dir.mkdir()
        narrative_cache_dir.mkdir()

        app = build_v2_pipeline(
            research_agent=ResearchAgent(config={"cache_store": str(mock_research_cache)}),
            kg_builder=KnowledgeGraphBuilder(config={"cache_store": str(kg_cache_dir), "sqlite_store": str(kg_cache_dir / "graphs.db")}),
            story_planner=StoryPlannerV2(config={"cache_store": str(narrative_cache_dir)}),
        )

        initial = PipelineStateV2(topic="Fermi Paradox", status="initialized")
        final = app.invoke(initial)

        # Assertions: research stage
        assert final["status"] == "narratived"
        assert final["research_document"] is not None
        assert isinstance(final["research_document"], ResearchDocument)
        assert final["research_document"].topic == "Fermi Paradox"
        assert len(final["research_document"].key_facts) >= 1

        # Assertions: knowledge stage
        assert final["knowledge_graph"] is not None
        assert isinstance(final["knowledge_graph"], KnowledgeGraph)
        assert len(final["knowledge_graph"].nodes) >= 4
        assert len(final["knowledge_graph"].edges) >= 1

        # Assertions: narrative stage
        assert final["narrative_arc"] is not None
        assert isinstance(final["narrative_arc"], NarrativeArc)
        assert len(final["narrative_arc"].beats) >= 2
        assert final["narrative_arc"].title == "The Great Silence"

        # Every beat references valid KG node IDs
        kg_ids = {n.id for n in final["knowledge_graph"].nodes}
        for beat in final["narrative_arc"].beats:
            for nid in beat.knowledge_node_ids:
                assert nid in kg_ids, f"Beat references node {nid} not in KG"

        # Stages elapsed should be populated
        assert "stages_elapsed" in final
        assert "research" in final["stages_elapsed"]
        assert "knowledge" in final["stages_elapsed"]
        assert "narrative" in final["stages_elapsed"]

    def test_pipeline_with_empty_topic(self, mock_llm, mock_web_search, mock_web_fetch, tmp_path):
        """Pipeline handles empty topic gracefully."""
        mock_llm("queries", '["general info"]')
        mock_llm("extract", json.dumps({
            "facts": [{"claim": "Fallback fact.", "confidence": 0.3}],
            "statistics": [],
            "key_people": [],
            "key_dates": [],
        }))
        mock_llm("extract all named entities", json.dumps({
            "concepts": [], "people": [], "events": [], "dates": [], "statistics": [], "places": [],
        }))
        mock_llm("identify relationships", json.dumps({"edges": []}))
        mock_llm("available narrative roles", "not valid json")

        app = build_v2_pipeline()

        initial = PipelineStateV2(topic="", status="initialized")
        final = app.invoke(initial)

        # Even with empty input, the pipeline should complete via fallback paths
        assert final["research_document"] is not None
        # KG and narrative have fallbacks so should exist
        assert final["knowledge_graph"] is not None
        assert final["narrative_arc"] is not None
        assert final["narrative_arc"].topic is not None

    def test_pipeline_returns_all_stages_elapsed(self, mock_llm, mock_web_search, mock_web_fetch, mock_research_cache, tmp_path):
        """stages_elapsed dict contains timing for all three stages."""
        mock_llm("queries", '["test query"]')
        mock_llm("extract", json.dumps({
            "facts": [{"claim": "Test fact.", "confidence": 0.7}],
            "statistics": [], "key_people": [], "key_dates": [],
        }))
        mock_llm("extract all named entities", json.dumps({
            "concepts": [{"id": "c1", "label": "Test", "description": "Test"}],
            "people": [], "events": [], "dates": [], "statistics": [], "places": [],
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "T", "subtitle": "", "logline": "T.",
            "beats": [
                {"index": 0, "role": "hook", "hook_sentence": "T.", "core_message": "T.",
                 "emotional_tone": "neutral", "knowledge_node_ids": ["c1"],
                 "target_duration_range": [60, 90], "cliffhanger": ""},
            ],
        }))

        kg_dir = tmp_path / "kg"
        nar_dir = tmp_path / "nar"
        kg_dir.mkdir(); nar_dir.mkdir()

        app = build_v2_pipeline(
            research_agent=ResearchAgent(config={"cache_store": str(mock_research_cache)}),
            kg_builder=KnowledgeGraphBuilder(config={"cache_store": str(kg_dir), "sqlite_store": str(kg_dir / "graphs.db")}),
            story_planner=StoryPlannerV2(config={"cache_store": str(nar_dir)}),
        )

        final = app.invoke(PipelineStateV2(topic="Test", status="initialized"))
        elapsed = final.get("stages_elapsed", {})
        assert "research" in elapsed
        assert "knowledge" in elapsed
        assert "narrative" in elapsed
        assert elapsed["research"] > 0
        assert elapsed["knowledge"] > 0
        assert elapsed["narrative"] > 0


# ═══════════════════════════════════════════════════════════════════════ #
# Graph structure tests
# ═══════════════════════════════════════════════════════════════════════ #


class TestV2PipelineGraph:
    """Tests that verify the graph structure without running nodes."""

    def test_build_returns_compiled_graph(self):
        """build_v2_pipeline returns a compiled LangGraph."""
        app = build_v2_pipeline()
        # Verify it's a CompiledStateGraph with invoke
        assert hasattr(app, 'invoke')

    def test_graph_nodes_present(self):
        """All three nodes exist in the graph."""
        app = build_v2_pipeline()
        # LangGraph compiled graphs have a .nodes attribute
        node_names = [n for n in app.nodes.keys() if n != "__start__"]
        assert "research" in node_names
        assert "knowledge" in node_names
        assert "narrative" in node_names

    def test_graph_edge_sequence(self):
        """Nodes are connected in the correct order."""
        app = build_v2_pipeline()
        node_names = list(app.nodes.keys())
        # Verify ordering: research → knowledge → narrative
        research_idx = node_names.index("research") if "research" in node_names else -1
        knowledge_idx = node_names.index("knowledge") if "knowledge" in node_names else -1
        narrative_idx = node_names.index("narrative") if "narrative" in node_names else -1
        assert research_idx < knowledge_idx < narrative_idx


# ═══════════════════════════════════════════════════════════════════════ #
# V1 Orchestrator unchanged
# ═══════════════════════════════════════════════════════════════════════ #


class TestV1OrchestratorUnchanged:
    """Verify that the V1 orchestrator file was not modified."""

    def test_v1_orchestrator_exists(self):
        """The original V1 orchestrator file is still at project root."""
        from pathlib import Path
        assert Path("orchestrator.py").exists()

    def test_v1_orchestrator_has_no_v2_imports(self):
        """V1 orchestrator does not import any V2 module."""
        import ast
        tree = ast.parse(Path("orchestrator.py").read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names if isinstance(node, ast.Import) else [node]:
                    if isinstance(node, ast.ImportFrom):
                        imports.add(node.module or "")
                    else:
                        imports.add(alias.name or "")
        v2_imports = {imp for imp in imports if "v2" in imp or "story_planner_v2" in imp or "knowledge_graph" in imp}
        assert len(v2_imports) == 0, f"V1 orchestrator should not have V2 imports: {v2_imports}"
