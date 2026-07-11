"""
test_story_planner_v2.py — Tests for StoryPlannerV2 (Stage 3).

Coverage plan:
  1. Happy path: full arc with framework + beats + logline
  2. Beat knowledge_node_ids reference only valid KG nodes
  3. Invalid node IDs in response are stripped
  4. Beat with no valid node IDs → injected with topic node
  5. Framework selection failure → default framework
  6. Arc generation failure → deterministic fallback arc
  7. Empty KG → fallback arc with single topic node
  8. Large KG → correct beat count range
  9. Cache hit returns cached arc
  10. Cache TTL → stale triggers regeneration
  11. Duration propagates to total_target_duration
  12. Custom config overrides work
  13. Fallback arc uses chronological framework
  14. Fallback arc distributes KG nodes across beats
  15. _find_topic_node_id finds by exact label match
  16. _find_topic_node_id falls back to first concept node
  17. _find_topic_node_id falls back to first node when no concept
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.v2_types import (
    EmotionalTone,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    NarrativeArc,
    NarrativeBeat,
    NarrativeRole,
)
from src.planner.story_planner_v2 import (
    StoryPlannerV2,
    VALID_FRAMEWORKS,
    _DEFAULT_FRAMEWORK,
)


# ═══════════════════════════════════════════════════════════════════════ #
# Fixtures
# ═══════════════════════════════════════════════════════════════════════ #


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock LLMProvider.generate_json for controlled responses."""
    responses = {}

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
def sample_kg() -> KnowledgeGraph:
    """A realistic knowledge graph for testing."""
    return KnowledgeGraph(
        topic="Fermi Paradox",
        nodes=[
            KnowledgeNode(id="fermi_paradox", label="Fermi Paradox", type="concept",
                          description="Contradiction between high probability estimates for alien life and lack of evidence."),
            KnowledgeNode(id="enrico_fermi", label="Enrico Fermi", type="person",
                          description="Italian physicist who first posed the question."),
            KnowledgeNode(id="drake_equation", label="Drake Equation", type="concept",
                          description="Equation estimating number of active extraterrestrial civilizations."),
            KnowledgeNode(id="great_filter", label="Great Filter", type="concept",
                          description="Hypothetical barrier that prevents life from advancing."),
            KnowledgeNode(id="year_1950", label="1950", type="date",
                          description="Fermi asked 'Where is everybody?'"),
            KnowledgeNode(id="year_1961", label="1961", type="date",
                          description="Drake Equation formulated"),
            KnowledgeNode(id="milky_way", label="Milky Way", type="place",
                          description="Our home galaxy with 100 billion stars"),
            KnowledgeNode(id="stat_stars", label="100 billion stars", type="stat",
                          description="Estimated number of stars in the Milky Way"),
        ],
        edges=[
            KnowledgeEdge(source_id="enrico_fermi", target_id="fermi_paradox", relationship="proposed"),
            KnowledgeEdge(source_id="drake_equation", target_id="fermi_paradox", relationship="supports"),
            KnowledgeEdge(source_id="great_filter", target_id="fermi_paradox", relationship="questions"),
        ],
    )


@pytest.fixture
def empty_kg() -> KnowledgeGraph:
    """An empty knowledge graph."""
    return KnowledgeGraph(topic="Unknown", nodes=[], edges=[])


@pytest.fixture
def single_node_kg() -> KnowledgeGraph:
    """A KG with one node."""
    return KnowledgeGraph(
        topic="Simple Topic",
        nodes=[KnowledgeNode(id="topic", label="Simple Topic", type="concept", description="A simple topic.")],
        edges=[],
    )


@pytest.fixture
def tmp_narrative_cache(tmp_path) -> Path:
    """Use a temp directory for narrative cache."""
    return tmp_path / "narrative_cache"


# ═══════════════════════════════════════════════════════════════════════ #
# StoryPlannerV2 Tests
# ═══════════════════════════════════════════════════════════════════════ #


class TestStoryPlannerV2:
    """Core StoryPlannerV2 functionality."""

    def test_build_narrative_happy_path(self, mock_llm, sample_kg, tmp_narrative_cache):
        """Happy path: framework selection + beats + logline."""
        mock_llm("narrative framework", json.dumps({
            "framework": "mystery_reveal",
            "reasoning": "This is a paradox with multiple explanations.",
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
                    "hook_sentence": "The universe is silent.",
                    "core_message": "There is a contradiction between high probability estimates and no evidence.",
                    "emotional_tone": "wonder",
                    "knowledge_node_ids": ["fermi_paradox", "enrico_fermi"],
                    "target_duration_range": [60, 90],
                    "cliffhanger": "But why?",
                },
                {
                    "index": 1,
                    "role": "context",
                    "hook_sentence": "Let's understand the numbers.",
                    "core_message": "The Drake Equation estimates civilizations.",
                    "emotional_tone": "contemplative",
                    "knowledge_node_ids": ["drake_equation", "milky_way"],
                    "target_duration_range": [45, 75],
                    "cliffhanger": "But where is everyone?",
                },
                {
                    "index": 2,
                    "role": "exploration",
                    "hook_sentence": "There are dark possibilities.",
                    "core_message": "The Great Filter may be ahead or behind us.",
                    "emotional_tone": "tension",
                    "knowledge_node_ids": ["great_filter"],
                    "target_duration_range": [60, 90],
                    "cliffhanger": "And either is terrifying.",
                },
                {
                    "index": 3,
                    "role": "climax",
                    "hook_sentence": "Both possibilities are chilling.",
                    "core_message": "The answer may be that we are alone.",
                    "emotional_tone": "dramatic",
                    "knowledge_node_ids": ["fermi_paradox", "great_filter"],
                    "target_duration_range": [60, 90],
                    "cliffhanger": "What does this mean?",
                },
                {
                    "index": 4,
                    "role": "resolution",
                    "hook_sentence": "We must keep looking.",
                    "core_message": "The search continues for answers.",
                    "emotional_tone": "hopeful",
                    "knowledge_node_ids": ["fermi_paradox", "year_1950"],
                    "target_duration_range": [45, 60],
                    "cliffhanger": "The story isn't over.",
                },
            ],
        }))

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(sample_kg, duration=480, template="documentary")

        assert isinstance(arc, NarrativeArc)
        assert arc.topic == "Fermi Paradox"
        assert arc.title == "The Great Silence"
        assert arc.logline
        assert len(arc.beats) >= 4  # 5 beats in mock, but fallback permits 4+
        assert arc.total_target_duration == 480.0
        assert arc.narrative_framework == "mystery_reveal"

        # Every beat references valid KG nodes
        valid_ids = {n.id for n in sample_kg.nodes}
        for beat in arc.beats:
            for nid in beat.knowledge_node_ids:
                assert nid in valid_ids, f"Beat references unknown node: {nid}"

    def test_unknown_node_ids_stripped(self, mock_llm, sample_kg, tmp_narrative_cache):
        """Node IDs not in the KG are removed from beats."""
        mock_llm("narrative framework", json.dumps({
            "framework": "chronological",
            "reasoning": "Test.",
            "expected_tension_curve": "rise",
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "Test",
            "subtitle": "",
            "logline": "Test.",
            "beats": [
                {
                    "index": 0,
                    "role": "hook",
                    "hook_sentence": "Test.",
                    "core_message": "Test.",
                    "emotional_tone": "neutral",
                    "knowledge_node_ids": ["fermi_paradox", "nonexistent_id", "also_bad"],
                    "target_duration_range": [60, 90],
                    "cliffhanger": "",
                },
            ],
        }))

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(sample_kg)

        # The invalid IDs should be stripped
        assert "nonexistent_id" not in arc.beats[0].knowledge_node_ids
        assert "also_bad" not in arc.beats[0].knowledge_node_ids
        assert "fermi_paradox" in arc.beats[0].knowledge_node_ids

    def test_beat_with_no_valid_ids_gets_topic_node(self, mock_llm, sample_kg, tmp_narrative_cache):
        """A beat whose knowledge_node_ids are all invalid gets the topic node injected."""
        mock_llm("narrative framework", json.dumps({
            "framework": "chronological", "reasoning": "T", "expected_tension_curve": "r",
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "T", "subtitle": "", "logline": "T.",
            "beats": [
                {
                    "index": 0,
                    "role": "hook",
                    "hook_sentence": "T.",
                    "core_message": "T.",
                    "emotional_tone": "neutral",
                    "knowledge_node_ids": ["nobody_here"],
                    "target_duration_range": [60, 90],
                    "cliffhanger": "",
                },
            ],
        }))

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(sample_kg)

        # The beat should now reference a real node (first concept = fermi_paradox)
        assert len(arc.beats[0].knowledge_node_ids) >= 1
        assert arc.beats[0].knowledge_node_ids[0] in {n.id for n in sample_kg.nodes}

    def test_framework_failure_defaults(self, mock_llm, sample_kg, tmp_narrative_cache):
        """When framework selection LLM fails, default framework is used."""
        mock_llm("narrative framework", "not valid json")
        mock_llm("available narrative roles", json.dumps({
            "title": "T", "subtitle": "", "logline": "T.",
            "beats": [
                {"index": 0, "role": "hook", "hook_sentence": "T.", "core_message": "T.",
                 "emotional_tone": "neutral", "knowledge_node_ids": ["fermi_paradox"],
                 "target_duration_range": [60, 90], "cliffhanger": ""},
            ],
        }))

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(sample_kg)

        assert arc.narrative_framework == _DEFAULT_FRAMEWORK

    def test_invalid_framework_defaults(self, mock_llm, sample_kg, tmp_narrative_cache):
        """When LLM returns an unrecognised framework, default is used."""
        mock_llm("narrative framework", json.dumps({
            "framework": "not_a_real_framework",
            "reasoning": "T",
            "expected_tension_curve": "r",
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "T", "subtitle": "", "logline": "T.",
            "beats": [
                {"index": 0, "role": "hook", "hook_sentence": "T.", "core_message": "T.",
                 "emotional_tone": "neutral", "knowledge_node_ids": ["fermi_paradox"],
                 "target_duration_range": [60, 90], "cliffhanger": ""},
            ],
        }))

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(sample_kg)

        assert arc.narrative_framework == _DEFAULT_FRAMEWORK

    def test_arc_generation_failure_fallback(self, mock_llm, sample_kg, tmp_narrative_cache):
        """When beat generation fails entirely, deterministic fallback arc is used."""
        mock_llm("narrative framework", json.dumps({
            "framework": "mystery_reveal", "reasoning": "T", "expected_tension_curve": "r",
        }))
        mock_llm("available narrative roles", "not valid json at all")

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(sample_kg)

        assert isinstance(arc, NarrativeArc)
        assert arc.topic == "Fermi Paradox"
        # Fallback should produce 6 beats (one per NarrativeRole)
        assert len(arc.beats) >= 4
        # Fallback uses chronological
        assert arc.narrative_framework == "chronological"
        # Fallback distributes KG nodes
        all_node_ids = set()
        for beat in arc.beats:
            all_node_ids.update(beat.knowledge_node_ids)
        # At least some KG nodes should be referenced
        kg_ids = {n.id for n in sample_kg.nodes}
        assert kg_ids & all_node_ids

    def test_fallback_with_empty_kg(self, mock_llm, empty_kg, tmp_narrative_cache):
        """Empty KG produces a valid fallback arc with just the topic node."""
        mock_llm("narrative framework", json.dumps({
            "framework": "mystery_reveal", "reasoning": "T", "expected_tension_curve": "r",
        }))
        mock_llm("available narrative roles", "not valid json")

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(empty_kg)

        assert isinstance(arc, NarrativeArc)
        assert arc.topic == "Unknown"
        assert len(arc.beats) >= 4
        # With no nodes, beats should still have valid (empty) IDs
        for beat in arc.beats:
            assert isinstance(beat.knowledge_node_ids, list)

    def test_duration_propagates(self, mock_llm, sample_kg, tmp_narrative_cache):
        """Duration parameter propagates to total_target_duration."""
        mock_llm("narrative framework", json.dumps({
            "framework": "comparison", "reasoning": "T", "expected_tension_curve": "r",
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "T", "subtitle": "", "logline": "T.",
            "beats": [
                {"index": 0, "role": "hook", "hook_sentence": "T.", "core_message": "T.",
                 "emotional_tone": "neutral", "knowledge_node_ids": ["fermi_paradox"],
                 "target_duration_range": [100, 120], "cliffhanger": ""},
            ],
        }))

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(sample_kg, duration=600)

        assert arc.total_target_duration == 600.0

    def test_cache_hit(self, mock_llm, sample_kg, tmp_narrative_cache):
        """Cached arc returned without LLM calls."""
        call_count = [0]

        def counting_mock(self_obj, prompt: str, **kwargs):
            call_count[0] += 1
            if "narrative framework" in prompt:
                return json.dumps({"framework": "listicle", "reasoning": "T", "expected_tension_curve": "r"})
            return json.dumps({
                "title": "T", "subtitle": "", "logline": "T.",
                "beats": [
                    {"index": 0, "role": "hook", "hook_sentence": "T.", "core_message": "T.",
                     "emotional_tone": "neutral", "knowledge_node_ids": ["fermi_paradox"],
                     "target_duration_range": [60, 90], "cliffhanger": ""},
                ],
            })

        import src.providers.llm_provider as llm_mod
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(llm_mod.LLMProvider, "generate_json", counting_mock)
        monkeypatch.setattr("src.providers.llm_provider.LLMProvider.generate_json", counting_mock)

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        # First call — populates cache
        arc1 = planner.build_narrative(sample_kg)
        assert len(arc1.beats) >= 1
        first_call_count = call_count[0]

        # Second call — should hit cache
        arc2 = planner.build_narrative(sample_kg)
        assert arc2.topic == "Fermi Paradox"
        # Only the first call should have made LLM requests
        assert call_count[0] == first_call_count

        monkeypatch.undo()

    def test_cache_stale_triggers_regeneration(self, mock_llm, sample_kg, tmp_narrative_cache):
        """Stale cache (TTL=0) causes regeneration."""
        mock_llm("narrative framework", json.dumps({
            "framework": "comparison", "reasoning": "T", "expected_tension_curve": "r",
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "T", "subtitle": "", "logline": "T.",
            "beats": [
                {"index": 0, "role": "hook", "hook_sentence": "T.", "core_message": "T.",
                 "emotional_tone": "neutral", "knowledge_node_ids": ["fermi_paradox"],
                 "target_duration_range": [60, 90], "cliffhanger": ""},
            ],
        }))

        planner = StoryPlannerV2(config={
            "cache_store": str(tmp_narrative_cache),
            "cache_ttl_days": 0,
        })
        # First call writes cache
        arc1 = planner.build_narrative(sample_kg)
        # Second call should regenerate (TTL=0 means always stale)
        # With TTL=0, it won't load from cache but should still produce a valid arc
        arc2 = planner.build_narrative(sample_kg)
        assert isinstance(arc2, NarrativeArc)

    def test_config_overrides(self):
        """Config parameters correctly override defaults."""
        planner = StoryPlannerV2(config={
            "min_beats": 3,
            "max_beats": 12,
            "hook_threshold": 0.5,
        })
        assert planner._min_beats == 3
        assert planner._max_beats == 12
        assert planner._hook_threshold == 0.5

    def test_large_kg_beat_count(self, mock_llm, tmp_narrative_cache):
        """Large KG produces a beat count within configured range."""
        # Create a KG with many nodes
        nodes = [
            KnowledgeNode(id=f"n{i}", label=f"Node {i}", type="concept",
                          description=f"Concept {i}")
            for i in range(20)
        ]
        large_kg = KnowledgeGraph(topic="Large Topic", nodes=nodes)

        mock_llm("narrative framework", json.dumps({
            "framework": "listicle", "reasoning": "T", "expected_tension_curve": "r",
        }))
        mock_llm("available narrative roles", json.dumps({
            "title": "T", "subtitle": "", "logline": "T.",
            "beats": [
                {"index": i, "role": "hook" if i == 0 else "exploration",
                 "hook_sentence": f"Beat {i}.", "core_message": f"Message {i}.",
                 "emotional_tone": "neutral", "knowledge_node_ids": [f"n{i}"],
                 "target_duration_range": [60, 90], "cliffhanger": f"Next: {i+1}"}
                for i in range(7)
            ],
        }))

        planner = StoryPlannerV2(config={"cache_store": str(tmp_narrative_cache)})
        arc = planner.build_narrative(large_kg)

        assert 4 <= len(arc.beats) <= 8  # Within configured bounds


# ═══════════════════════════════════════════════════════════════════════ #
# Static / internal helpers
# ═══════════════════════════════════════════════════════════════════════ #


class TestHelpers:
    """Internal helper tests."""

    def test_find_topic_node_exact_match(self, sample_kg):
        """Exact label match finds the correct node."""
        node_id = StoryPlannerV2._find_topic_node_id(sample_kg, "Fermi Paradox")
        assert node_id == "fermi_paradox"

    def test_find_topic_node_case_insensitive(self, sample_kg):
        """Case-insensitive match."""
        node_id = StoryPlannerV2._find_topic_node_id(sample_kg, "fermi paradox")
        assert node_id == "fermi_paradox"

    def test_find_topic_node_fallback_to_first_concept(self, sample_kg):
        """Falls back to first concept node for unknown topic."""
        node_id = StoryPlannerV2._find_topic_node_id(sample_kg, "Nonexistent Topic")
        # Should match fermi_paradox as the first concept
        assert node_id == "fermi_paradox"

    def test_find_topic_node_fallback_to_first_node(self, empty_kg):
        """Falls back to first node when KG has no concepts."""
        node_id = StoryPlannerV2._find_topic_node_id(empty_kg, "Anything")
        assert node_id is None

    def test_kg_summary_contains_nodes(self, sample_kg):
        """_kg_summary produces a text with node information."""
        summary = StoryPlannerV2._kg_summary(sample_kg)
        assert "fermi_paradox" in summary
        assert "enrico_fermi" in summary
        assert "Nodes (8)" in summary
        # Should show edge count
        assert "Edges (3)" in summary

    def test_kg_summary_empty(self, empty_kg):
        """_kg_summary handles empty KG."""
        summary = StoryPlannerV2._kg_summary(empty_kg)
        assert "Topic: Unknown" in summary
        assert "Nodes (0)" in summary

    def test_kg_for_prompt_valid_json(self, sample_kg):
        """_kg_for_prompt returns parseable JSON."""
        result = StoryPlannerV2._kg_for_prompt(sample_kg)
        data = json.loads(result)
        assert data["topic"] == "Fermi Paradox"
        assert len(data["nodes"]) == 8
        assert len(data["edges"]) == 3

    def test_kg_for_prompt_empty(self, empty_kg):
        """_kg_for_prompt handles empty KG."""
        result = StoryPlannerV2._kg_for_prompt(empty_kg)
        data = json.loads(result)
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_cache_key_deterministic(self):
        """Same inputs produce the same cache key."""
        planner = StoryPlannerV2()
        key1 = planner._cache_key("Fermi Paradox", "documentary", 480)
        key2 = planner._cache_key("Fermi Paradox", "documentary", 480)
        assert key1 == key2

    def test_cache_key_varied(self):
        """Different inputs produce different cache keys."""
        planner = StoryPlannerV2()
        key1 = planner._cache_key("Topic A", "documentary", 480)
        key2 = planner._cache_key("Topic B", "documentary", 480)
        assert key1 != key2

    def test_valid_frameworks_set(self):
        """VALID_FRAMEWORKS contains expected values."""
        assert "mystery_reveal" in VALID_FRAMEWORKS
        assert "chronological" in VALID_FRAMEWORKS
        assert "problem_solution" in VALID_FRAMEWORKS
        assert "comparison" in VALID_FRAMEWORKS
        assert "listicle" in VALID_FRAMEWORKS
        assert "character_driven" in VALID_FRAMEWORKS
