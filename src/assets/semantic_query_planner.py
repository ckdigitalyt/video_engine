"""
semantic_query_planner.py — LLM-driven semantic search query generation.

Transforms raw narration text into semantically meaningful asset search queries
that describe visible objects, locations, and phenomena — not names, metaphors,
or emotion words.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider


# ═══════════════════════════════════════════════════════════════════════════
# Filters
# ═══════════════════════════════════════════════════════════════════════════

NEVER_SEARCH = {
    "person names",
    "metaphors",
    "verbs",
    "emotion words",
}

ALWAYS_SEARCH = {
    "visible objects",
    "locations",
    "phenomena",
    "scientific equipment",
    "natural events",
    "animations",
}


# ═══════════════════════════════════════════════════════════════════════════
# Prompt template
# ═══════════════════════════════════════════════════════════════════════════

SEARCH_QUERY_SYSTEM_PROMPT = """You generate video stock footage search queries from narration text.

Rules:
- Search for VISIBLE OBJECTS, LOCATIONS, PHENOMENA, SCIENTIFIC EQUIPMENT, NATURAL EVENTS
- NEVER search for: person names, metaphors, verbs, emotion words
- Each query must describe something a camera can actually record
- Generate 3-5 alternative queries at different specificity levels

EXAMPLES:

Narration: "Fermi asked over lunch whether anyone is out there"
Queries: ["scientists discussing around conference table", "researchers having intellectual discussion"]

Narration: "Frank Drake pointed the radio telescope toward Tau Ceti"
Queries: ["radio telescope control room", "SETI observatory astronomer working"]

Narration: "At the singularity, spacetime curvature becomes infinite"
Queries: ["black hole visualization", "gravitational distortion simulation", "accretion disk animation"]

Return ONLY a JSON list of strings.
"""


class SemanticQueryPlanner:
    """Generate semantic search queries from narration text.

    Usage::

        planner = SemanticQueryPlanner()
        queries = planner.plan("Fermi asked over lunch...")
        # -> ["scientists discussing around conference table", ...]
    """

    def __init__(self, provider: Optional[LLMProvider] = None):
        self._provider = provider or self._default_provider()

    # ── Public API ─────────────────────────────────────────────────────

    def plan(self, narration: str, n_queries: int = 5) -> list[str]:
        """Generate *n_queries* semantic search queries from *narration*.

        Returns a list of query strings, specific to general.
        Falls back to simple keyword extraction if the LLM call fails.
        """
        try:
            prompt = f"Narration: {narration}\n\nQueries:"
            raw = self._provider.llm_complete(
                system=SEARCH_QUERY_SYSTEM_PROMPT,
                prompt=prompt,
                temperature=0.7,
                max_tokens=300,
            )
            queries = self._parse_response(raw, n_queries)
            if queries:
                return queries
        except Exception as e:
            print(f"[SemanticQueryPlanner] LLM query generation failed: {e}")

        return self._fallback_keywords(narration, n_queries)

    # ── Internal ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(raw: str, n: int) -> list[str]:
        """Parse LLM JSON response into query list."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("\n", 1)[0]
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list) and data:
            return [str(q).strip().strip('"').strip("'") for q in data[:n]]
        return []

    @staticmethod
    def _fallback_keywords(narration: str, n: int) -> list[str]:
        """Fallback: simple keyword extraction when LLM fails."""
        import re
        # Remove common stopwords plus names that might appear
        stopwords = {
            "the", "a", "an", "is", "was", "are", "were", "in", "on", "at",
            "of", "to", "for", "with", "by", "from", "and", "or", "but",
            "that", "this", "it", "its", "he", "she", "they", "we", "you",
            "i", "my", "me", "his", "her", "our", "their", "as", "at",
            "be", "been", "being", "have", "has", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "shall",
            "about", "into", "over", "after", "before", "between", "under",
            "very", "just", "so", "too", "also", "not", "no", "nor",
            "scientists", "researchers", "astronomers", "physicists",
            "said", "says", "asked", "answered", "explained", "noted",
        }
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9]+", narration.lower())
        filtered = [w for w in words if w not in stopwords and len(w) > 3]
        # De-duplicate preserving order
        seen: set[str] = set()
        unique = []
        for w in filtered:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        if not unique:
            return ["science documentary footage"]
        # Build queries of increasing generality
        queries = []
        for i in range(min(n, len(unique))):
            chunk = unique[i : i + 3]
            queries.append(" ".join(chunk))
        if not queries:
            queries = ["science documentary footage"]
        return queries[:n]
