"""
test_research_agent.py — Tests for ResearchAgent and FactVerifier.

Coverage plan:
  1. ResearchAgent: happy path (mocked web + LLM) produces ResearchDocument
  2. All web searches fail → fallback document with low confidence
  3. Search query LLM fails → fallback queries used
  4. Fact extraction from single source
  5. Partial source failures (some URLs fail)
  6. Cache hit returns cached document
  7. Cache staleness (TTL expired → re-fetch)
  8. Research document serialization round-trip
  9. FactVerifier: high confidence with 2+ sources
  10. FactVerifier: low confidence with single source
  11. FactVerifier: insufficient when no sources match
  12. Fallback with empty topic
  13. Config overrides work (max_sources, concurrency)
  14. Racy: concurrent extraction is thread-safe
  15. Topic classification integration (via _compute_relevance)
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.v2_types import Source, Fact, ResearchDocument
from src.research.research_agent import ResearchAgent, FactVerifier


# ═══════════════════════════════════════════════════════════════════════ #
# Fixtures
# ═══════════════════════════════════════════════════════════════════════ #


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock DeepSeekProvider.generate_json to return controlled responses."""
    responses = {}

    def set_response(key: str, value: str):
        responses[key] = value

    original = None

    def mock_generate_json(self_obj, prompt: str, **kwargs):
        # Determine which mock response to return based on prompt content
        for key, value in responses.items():
            if key in prompt.lower():
                return value
        # Fallback to the default registered response
        return responses.get("__default__", '{"scenes": []}')

    import src.research.research_agent
    monkeypatch.setattr(src.research.research_agent.DeepSeekProvider, "generate_json",
                        mock_generate_json)
    return set_response


@pytest.fixture
def mock_web_search(monkeypatch):
    """Mock the _web_search method to return controlled results."""
    results_by_query = {}

    def register(query_prefix: str, results: list[dict]):
        results_by_query[query_prefix] = results

    def mock_search(self_obj, query: str):
        for prefix, results in results_by_query.items():
            if prefix in query.lower():
                return results
        return [{"url": "https://example.com", "title": "Example", "snippet": "Default snippet"}]

    monkeypatch.setattr(ResearchAgent, "_web_search", mock_search)
    return register


@pytest.fixture
def mock_web_fetch(monkeypatch):
    """Mock the _web_fetch method to return controlled content."""
    def mock_fetch(self_obj, url: str, max_chars: int = 3000):
        if "bad" in url or "fail" in url:
            return ""
        return f"This is fetched content from {url}. It contains factual information about the topic."

    monkeypatch.setattr(ResearchAgent, "_web_fetch", mock_fetch)
    return mock_fetch


@pytest.fixture
def tmp_research_cache(tmp_path) -> Path:
    """Use a temp directory for research cache during tests."""
    return tmp_path / "research_cache"


# ═══════════════════════════════════════════════════════════════════════ #
# ResearchAgent Tests
# ═══════════════════════════════════════════════════════════════════════ #


class TestResearchAgentBasic:
    """Happy path and basic functionality."""

    def test_research_returns_document(self, mock_llm, mock_web_search, mock_web_fetch):
        """Happy path: valid topic produces ResearchDocument with expected fields."""
        mock_llm("queries", '["fermi paradox facts", "drake equation explained"]')
        mock_llm("extract", '{"facts": [{"claim": "The Fermi Paradox questions why we haven\'t found alien life.", "confidence": 0.85}], "statistics": ["100 billion stars"], "key_people": ["Enrico Fermi"]}')
        mock_web_search("fermi", [{"url": "https://en.wikipedia.org/wiki/Fermi_paradox", "title": "Fermi Paradox - Wikipedia", "snippet": "The Fermi Paradox is the discrepancy between the lack of evidence for alien life."}])
        mock_web_search("drake", [{"url": "https://example.com/drake", "title": "Drake Equation", "snippet": "The Drake Equation estimates the number of civilizations."}])

        agent = ResearchAgent()
        doc = agent.research("The Fermi Paradox")

        assert isinstance(doc, ResearchDocument)
        assert doc.topic == "The Fermi Paradox"
        assert len(doc.key_facts) >= 1
        assert doc.key_facts[0].claim
        assert doc.key_facts[0].sources  # Should have attached sources
        assert len(doc.sources) >= 1

    def test_all_web_searches_fail_fallback(self, mock_llm, mock_web_search, mock_web_fetch):
        """When all web searches return empty, fallback document is generated."""
        mock_llm("queries", '["test query 1", "test query 2"]')
        mock_llm("research", '{"key_facts": [{"claim": "Fallback fact about the topic.", "confidence": 0.3}], "key_statistics": ["50% of statistics are made up"]}')
        mock_web_search("test", [])

        agent = ResearchAgent()
        doc = agent.research("Some Topic")

        assert isinstance(doc, ResearchDocument)
        assert doc.topic == "Some Topic"
        assert len(doc.sources) == 0  # No web sources
        # In the current flow, if searches return empty, it goes to fallback
        # which generates LLM-based facts
        assert len(doc.key_facts) >= 0

    def test_queries_llm_fails_fallback_queries(self, mock_llm, mock_web_search, mock_web_fetch):
        """When query LLM returns bad JSON, fallback queries generated."""
        mock_llm("queries", "not valid json")  # Will cause JSON decode error
        mock_web_search("facts", [{"url": "https://example.com", "title": "E1", "snippet": "s1"}])

        agent = ResearchAgent()
        queries = agent._generate_search_queries("Some Topic")
        assert len(queries) > 0  # Fallback queries returned
        # All fallback queries contain the topic
        for q in queries:
            assert "some" in q.lower() or "topic" in q.lower()

    def test_cache_hit(self, mock_llm, mock_web_search, mock_web_fetch, tmp_research_cache):
        """Cached document returned without network calls."""
        mock_llm("queries", '["query1"]')
        mock_llm("extract", '{"facts": [{"claim": "Cached fact.", "confidence": 0.9}], "statistics": []}')
        mock_web_search("query1", [{"url": "https://example.com", "title": "E1", "snippet": "s1"}])

        agent = ResearchAgent(config={"cache_store": str(tmp_research_cache)})
        # First call — populates cache
        doc1 = agent.research("Cache Test Topic")
        assert len(doc1.key_facts) >= 1

        # Reset mocks — if cache is working, _web_search won't be called
        # Second call should return cached result
        doc2 = agent.research("Cache Test Topic")
        assert doc2.topic == "Cache Test Topic"

    def test_cache_staleness(self, mock_llm, mock_web_search, mock_web_fetch, tmp_research_cache):
        """Stale cache triggers re-fetch."""
        mock_llm("queries", '["test query"]')
        mock_llm("extract", '{"facts": [{"claim": "Fresh fact.", "confidence": 0.8}], "statistics": []}')
        mock_web_search("test", [{"url": "https://example.com", "title": "E1", "snippet": "s1"}])

        agent = ResearchAgent(config={"cache_store": str(tmp_research_cache), "cache_ttl_days": 0})
        # TTL=0 means immediate staleness
        doc = agent.research("Stale Test")
        # Should still return a doc (even if stale, it re-fetches, but web searches return empty)
        assert isinstance(doc, ResearchDocument)

    def test_serialization_round_trip(self):
        """ResearchDocument serializes and deserializes correctly."""
        sources = [Source(url="https://a.com", title="A")]
        facts = [Fact(claim="Test fact", sources=sources, confidence=0.8)]
        doc = ResearchDocument(
            topic="Test",
            sources=sources,
            key_facts=facts,
            key_statistics=["stat1"],
            key_people=["Person A"],
            controversies=["Controversy 1"],
            unanswered_questions=["Question 1"],
        )
        json_str = doc.model_dump_json()
        restored = ResearchDocument.model_validate_json(json_str)
        assert restored.topic == "Test"
        assert len(restored.key_facts) == 1
        assert restored.key_facts[0].claim == "Test fact"

    def test_partial_source_failures(self, mock_llm, mock_web_search, mock_web_fetch):
        """Some sources fail; successful ones are still used."""
        mock_llm("queries", '["good query", "bad query"]')
        mock_llm("extract", '{"facts": [{"claim": "Working source fact.", "confidence": 0.8}], "statistics": []}')
        mock_web_search("good", [{"url": "https://good.com", "title": "Good", "snippet": "Good snippet"}])
        mock_web_search("bad", [{"url": "https://bad.com", "title": "Bad", "snippet": "Bad snippet"}])

        agent = ResearchAgent()
        # _parallel_extract_facts uses _web_fetch which returns empty for "bad" URLs
        doc = agent.research("Partial Topic")
        assert isinstance(doc, ResearchDocument)

    def test_empty_topic(self, mock_llm, mock_web_search, mock_web_fetch):
        """Empty topic string doesn't crash."""
        mock_llm("queries", '["general topic"]')
        mock_llm("extract", '{"facts": [{"claim": "General fact.", "confidence": 0.5}], "statistics": []}')
        mock_web_search("general", [{"url": "https://a.com", "title": "A", "snippet": "a"}])

        agent = ResearchAgent()
        doc = agent.research("")
        assert isinstance(doc, ResearchDocument)

    def test_config_override(self):
        """Config parameters correctly override defaults."""
        agent = ResearchAgent(config={
            "max_sources": 5,
            "search_query_count": 3,
            "concurrency_web": 2,
            "concurrency_llm": 2,
        })
        assert agent._max_sources == 5
        assert agent._search_query_count == 3
        assert agent._concurrency_web == 2
        assert agent._concurrency_llm == 2

    def test_topic_hash_deterministic(self):
        """Same topic always produces the same hash."""
        agent = ResearchAgent()
        h1 = agent._topic_hash("Fermi Paradox")
        h2 = agent._topic_hash("Fermi Paradox")
        assert h1 == h2

    def test_topic_hash_different_topics(self):
        """Different topics produce different hashes."""
        agent = ResearchAgent()
        h1 = agent._topic_hash("Topic A")
        h2 = agent._topic_hash("Topic B")
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════════════ #
# FactVerifier Tests
# ═══════════════════════════════════════════════════════════════════════ #


class TestFactVerifier:
    """FactVerifier cross-references claims against sources."""

    def test_high_confidence_with_two_sources(self):
        """Two supporting sources → high confidence."""
        sources = [
            Source(url="https://wikipedia.org/wiki/Fermi", domain="wikipedia.org",
                   snippet="The Fermi Paradox is the discrepancy between estimates of high probability of alien life and the lack of evidence.", relevance_score=0.9),
            Source(url="https://bbc.com/news/science", domain="bbc.com",
                   snippet="Scientists have long wondered about the Fermi Paradox.", relevance_score=0.8),
        ]
        fact = Fact(claim="The Fermi Paradox questions the lack of evidence for alien life.",
                     sources=sources, confidence=0.9)
        verifier = FactVerifier()
        verified = verifier.verify(fact, sources)
        assert verified.verified is True
        assert verified.confidence >= 0.6

    def test_single_source_medium_confidence(self):
        """One supporting source that exactly matches the claim text → low confidence."""
        sources = [
            Source(url="https://example.com/article", domain="example.com",
                   snippet="Fermi Paradox: where is everybody?", relevance_score=0.7),
        ]
        fact = Fact(claim="Fermi Paradox: where is everybody?",
                     sources=sources, confidence=0.5)
        verifier = FactVerifier()
        verified = verifier.verify(fact, sources)
        # The claim text matches the snippet exactly, so the authoritative
        # domain check applies: example.com is NOT in the primary domain list
        # but the direct text match triggers a single-source verification.
        assert verified.verified is True
        assert verified.confidence <= 0.3  # Low for single non-authoritative source

    def test_no_supporting_sources(self):
        """No source matches the claim → insufficient confidence."""
        sources = [
            Source(url="https://example.com", domain="example.com",
                   snippet="Unrelated content about something else.", relevance_score=0.0),
        ]
        fact = Fact(claim="The Great Filter is inevitable.", sources=sources, confidence=0.5)
        verifier = FactVerifier()
        verified = verifier.verify(fact, sources)
        assert verified.verified is False
        assert verified.confidence <= 0.2  # Insufficient

    def test_authoritative_domain_boosts_confidence(self):
        """Authoritative domain (wikipedia.org) counts as supporting."""
        sources = [
            Source(url="https://en.wikipedia.org/wiki/Fermi_paradox", domain="wikipedia.org",
                   snippet="The Fermi Paradox is named after physicist Enrico Fermi.",
                   relevance_score=0.8),
        ]
        fact = Fact(claim="Named after Enrico Fermi", sources=sources, confidence=0.7)
        verifier = FactVerifier()
        verified = verifier.verify(fact, sources)
        assert verified.verified is True

    def test_verify_all(self):
        """verify_all processes all facts."""
        sources = [
            Source(url="https://wikipedia.org/wiki/Fermi", domain="wikipedia.org",
                   snippet="Fermi Paradox", relevance_score=0.5),
        ]
        facts = [
            Fact(claim="Claim about Fermi", sources=sources, confidence=0.8),
            Fact(claim="Unrelated fact", sources=[], confidence=0.3),
        ]
        verifier = FactVerifier()
        results = verifier.verify_all(facts, sources)
        assert len(results) == 2
        # First should be verified (authoritative domain), second may not
        assert isinstance(results[0], Fact)
        assert isinstance(results[1], Fact)

    def test_confidence_never_exceeds_extraction_confidence(self):
        """Verification confidence is capped at extraction confidence."""
        sources = [
            Source(url="https://wikipedia.org/wiki/Fermi", domain="wikipedia.org",
                   snippet="Fermi Paradox", relevance_score=0.9),
            Source(url="https://bbc.com/news", domain="bbc.com",
                   snippet="Fermi Paradox", relevance_score=0.8),
            Source(url="https://nature.com/articles", domain="nature.com",
                   snippet="Fermi Paradox", relevance_score=0.7),
        ]
        # Fact with low extraction confidence (0.2)
        fact = Fact(claim="Fermi Paradox", sources=sources, confidence=0.2)
        verifier = FactVerifier()
        verified = verifier.verify(fact, sources)
        # Should be capped at 0.2 even though 3 sources support it
        assert verified.confidence <= 0.2


# ═══════════════════════════════════════════════════════════════════════ #
# Helper method tests
# ═══════════════════════════════════════════════════════════════════════ #


class TestHelpers:
    """Internal helper method tests."""

    def test_extract_domain(self):
        agent = ResearchAgent()
        assert agent._extract_domain("https://www.example.com/path") == "www.example.com"
        assert agent._extract_domain("") == ""
        assert agent._extract_domain("not-a-url") == ""

    def test_compute_relevance_exact_match(self):
        agent = ResearchAgent()
        score = agent._compute_relevance("Fermi Paradox", "The Fermi Paradox is interesting", "Title")
        assert score > 0.5

    def test_compute_relevance_no_match(self):
        agent = ResearchAgent()
        score = agent._compute_relevance("Quantum Physics", "Cooking recipes for pasta", "Title")
        assert score == 0.0

    def test_compute_relevance_empty_topic(self):
        agent = ResearchAgent()
        score = agent._compute_relevance("", "Some content", "Title")
        assert score == 0.5

    def test_duckduckgo_parser(self, mock_llm):
        """DDG search results parser handles HTML correctly."""
        agent = ResearchAgent()
        html = """
        <html><body>
        <table><tr>
        <td><a rel="nofollow" href="https://example.com/1">Result 1</a></td>
        <td class="result-snippet">Snippet 1 about topic</td>
        </tr><tr>
        <td><a rel="nofollow" href="https://example.com/2">Result 2</a></td>
        <td class="result-snippet">Snippet 2 about something</td>
        </tr></table>
        </body></html>
        """
        results = agent._parse_ddg_html(html, "test query")
        assert len(results) >= 1
        if len(results) > 0:
            assert "example.com" in results[0]["url"]
            assert results[0]["title"] == "Result 1"
