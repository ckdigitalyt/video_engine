"""
search_planner.py — Intelligent Multi-Query Asset Search.

Generates multiple visually diverse search queries per scene instead of
relying on a single literal search phrase.  Uses an LLM to produce
semantically different queries covering different visual angles of the
same narration, then evaluates them via the AssetRouter to find the
best matching asset.

Usage::

    planner = SearchPlanner(provider=deepseek)
    queries = planner.generate_queries(
        narration="Scientists still don't know why...",
        title="The Great Silence",
        topic="The Fermi Paradox Explained",
        purpose="exploration",
    )
    # => ["radio telescope at night", "SETI observatory", ...]
"""

from typing import Optional

from src.providers.llm_provider import LLMProvider
from src.utils.config import get_config


# ── Default prompt template ───────────────────────────────────────────

_DEFAULT_PROMPT = """You are a stock footage search planner. Given a scene's narration, title, video topic, and purpose, generate {num_queries} visually diverse search queries optimized for stock video libraries (Pexels, Pixabay, etc.).

Rules:
1. Each query must be visually different from the others (different subject, perspective, setting, or mood).
2. Queries should be 2-8 words — short enough for stock API search.
3. Focus on concrete, visually searchable elements (locations, objects, actions, scenes).
4. Avoid abstract concepts or metaphors.
5. Prioritize landscape/horizontal compositions.
6. Include a mix of: wide shots, close-ups, aerial views, slow motion, and detailed textures.
7. Return ONLY a JSON array of strings, no explanation.

Scene Narration: "{narration}"
Scene Title: "{title}"
Video Topic: "{topic}"
Scene Purpose: "{purpose}"

Generate exactly {num_queries} diverse, visually distinct search queries."""


def _default_prompt(**kwargs) -> str:
    """Build the search query generation prompt."""
    return _DEFAULT_PROMPT.format(**kwargs)


# ── Fallback (no LLM) ────────────────────────────────────────────────

_FALLBACK_TEMPLATES = [
    "{kw} wide angle",
    "{kw} close up",
    "{kw} aerial view",
    "{kw} slow motion",
    "{kw} cinematic",
    "{kw} landscape",
    "{kw} time lapse",
    "{kw} detailed view",
    "{kw} establishing shot",
    "{kw} macro shot",
]


class SearchPlanner:
    """Generates and manages diverse search queries for a scene.

    Parameters
    ----------
    provider : LLMProvider | None
        LLM used for query generation.  When *None*, uses a keyword-
        extraction fallback.
    num_queries : int
        Number of queries to generate (default 7, configurable).
    min_acceptable_score : float
        Minimum quality score (0-1) for a result to be accepted without
        trying further queries (default 0.75).
    max_provider_attempts : int
        Maximum total provider API calls across all queries (default 15).
    diversity_weighting : float
        Bonus weight for visual diversity when ranking candidates across
        multiple queries (default 0.2).
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        num_queries: Optional[int] = None,
        min_acceptable_score: Optional[float] = None,
        max_provider_attempts: Optional[int] = None,
        diversity_weighting: Optional[float] = None,
    ):
        self._provider = provider
        self._num_queries = num_queries or get_config("search_planner.num_queries", 7)
        self._min_acceptable_score = min_acceptable_score or get_config(
            "search_planner.min_acceptable_score", 0.75
        )
        self._max_provider_attempts = max_provider_attempts or get_config(
            "search_planner.max_provider_attempts", 15
        )
        self._diversity_weighting = diversity_weighting or get_config(
            "search_planner.diversity_weighting", 0.2
        )

    # ── Public API ─────────────────────────────────────────────────────

    def generate_queries(
        self,
        narration: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> list[str]:
        """Generate diverse stock-footage search queries.

        Parameters
        ----------
        narration : str
            The voiceover text for this scene.
        title : str | None
            Optional scene title.
        topic : str | None
            Overall video topic.
        purpose : str | None
            Scene purpose (e.g. "hook", "context", "climax").

        Returns
        -------
        list[str]
            5-10 diverse search queries, unique and stripped.
        """
        if self._provider:
            queries = self._generate_via_llm(narration, title, topic, purpose)
        else:
            queries = self._generate_fallback(narration, title, topic, purpose)

        # Deduplicate and filter
        seen: set[str] = set()
        unique: list[str] = []
        for q in queries:
            normalised = q.strip().lower()
            if normalised and normalised not in seen:
                seen.add(normalised)
                unique.append(q.strip())

        return unique[:self._num_queries]

    # ── LLM-based generation ───────────────────────────────────────────

    def _generate_via_llm(
        self,
        narration: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> list[str]:
        """Generate queries via LLM."""
        prompt = _default_prompt(
            narration=narration or "",
            title=title or "",
            topic=topic or "",
            purpose=purpose or "general",
            num_queries=self._num_queries,
        )
        try:
            raw = self._provider.generate_json(prompt)
            return self._parse_queries(raw)
        except Exception as e:
            print(f"-> SearchPlanner LLM error: {e} -- using fallback")
            return self._generate_fallback(narration, title, topic, purpose)

    # ── Fallback generation ────────────────────────────────────────────

    def _generate_fallback(
        self,
        narration: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> list[str]:
        """Extract keywords from narration and combine with visual
        descriptors to produce diverse queries.

        This is a lightweight, deterministic fallback that does not
        require an LLM provider.
        """
        # Extract meaningful keywords from narration
        keywords = self._extract_keywords(narration)

        # Also use title words if available
        if title:
            keywords.extend(self._extract_keywords(title))
        if topic:
            keywords.extend(self._extract_keywords(topic))

        # Remove duplicates, keep top 3
        seen: set[str] = set()
        deduped: list[str] = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                deduped.append(kw)

        primary_keywords = deduped[:3] if deduped else ["stock footage"]

        # Generate queries by combining keywords with visual templates
        queries: list[str] = []
        for kw in primary_keywords:
            for template in _FALLBACK_TEMPLATES:
                query = template.format(kw=kw)
                queries.append(query)
                if len(queries) >= self._num_queries:
                    return queries[:self._num_queries]

        return queries[:self._num_queries]

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract meaningful single-word keywords from text.

        Filters out common stop words and short tokens, keeping only
        nouns and adjectives that make good search terms.
        """
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "up", "about", "into", "over", "after", "all", "also", "and",
            "but", "or", "if", "because", "so", "than", "that", "this",
            "these", "those", "it", "its", "they", "them", "we", "our",
            "you", "your", "he", "she", "his", "her", "my", "not", "no",
            "nor", "just", "very", "too", "much", "many", "some", "any",
            "each", "every", "both", "few", "more", "most", "other",
            "such", "only", "own", "same", "what", "which", "who", "whom",
            "when", "where", "why", "how",
        }
        words = text.lower().split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        # Deduplicate while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                result.append(w)
        return result

    @staticmethod
    def _parse_queries(raw: str) -> list[str]:
        """Parse a JSON array of strings from the LLM response.

        Tolerates minor formatting issues (markdown fences, trailing
        commas, extra whitespace).
        """
        import json
        import re

        # Strip markdown fences
        cleaned = re.sub(r"```(?:json)?", "", raw).strip()

        # Try to find a JSON array
        array_match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
        if not array_match:
            # Fallback: split by newline and clean
            return [line.strip(" \t\"',-.") for line in raw.split("\n")
                    if line.strip() and not line.strip().startswith(("#", "//"))]

        try:
            parsed = json.loads(array_match.group())
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            # Handle trailing commas by replacing them before re-parsing
            try:
                fixed = re.sub(r",\s*]", "]", array_match.group())
                parsed = json.loads(fixed)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except (json.JSONDecodeError, Exception):
                pass

        return []

    # ── Configuration access ───────────────────────────────────────────

    @property
    def num_queries(self) -> int:
        return self._num_queries

    @property
    def min_acceptable_score(self) -> float:
        return self._min_acceptable_score

    @property
    def max_provider_attempts(self) -> int:
        return self._max_provider_attempts

    @property
    def diversity_weighting(self) -> float:
        return self._diversity_weighting
