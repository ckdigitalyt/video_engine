"""
concept_planner.py — Concept-Driven Visual Search Planner.

Replaces the literal keyword-based query generation with concept-driven
visual planning.  Given a scene narration and global VisualStyle, the
ConceptPlanner generates search queries targeting visual metaphors,
scientific concepts, and cinematic compositions rather than literal
keywords from the narration.

Example: For narration "gravitational waves ripple through spacetime":
    Old (literal): "gravitational waves spacetime ripple"
    New (concept): ["interferometer laser beams", "fabric of space distortion",
                     "particle collision simulation", "ripple on water surface",
                     "Einstein's thought experiment visualization"]
"""

from __future__ import annotations

import re
import json
from typing import Optional

from src.providers.llm_provider import LLMProvider
from src.utils.config import get_config
from src.director.visual_style import VisualStyle


_CONCEPT_PROMPT = """You are a visual concept director for a documentary. Given a scene's narration and the video's visual style, generate {num_queries} visually diverse search queries. Each query must target a *different visual concept* or *metaphor* — do NOT just rephrase the narration with synonyms.

Visual Style: {style_description}
Scene Narration: "{narration}"
Scene Title: "{title}"
Video Topic: "{topic}"
Scene Purpose: "{purpose}"

RULES:
1. Each query must depict a visually DISTINCT concept (different subject, setting, or visual metaphor).
2. If the narration is abstract (e.g. "gravity", "time", "consciousness"), search for VISUAL METAPHORS that represent the concept (e.g. "hourglass sand falling" for time, "planet orbiting star" for gravity).
3. If the narration describes a concrete subject (e.g. "Roman soldiers marching"), provide diverse visuals of that subject from different angles/contexts.
4. Each query should be 2-8 words — optimized for stock footage search engines.
5. Prefer landscape/horizontal compositions.
6. Include a mix of: wide establishing shots, close-up details, aerial perspectives, atmospheric textures, and slow-motion captures.
7. Do NOT repeat the same visual subject across queries.

Return ONLY a JSON array of strings, no explanation. Example:
["interferometer laser beams", "fabric of space distortion", "particle collision simulation", "ripple on water surface", "Einstein thought experiment"]

Generate exactly {num_queries} diverse queries."""


class ConceptPlanner:
    """Generates concept-driven visual search queries for a scene.

    Uses an LLM to create queries targeting visual metaphors, scientific
    concepts, and diverse visual perspectives.  Falls back to keyword
    extraction when no LLM is available.

    Parameters
    ----------
    provider : LLMProvider | None
        LLM for query generation.  Falls back to keyword extraction
        when *None*.
    visual_style : VisualStyle | None
        Global visual style guiding query generation.
    num_queries : int
        Number of queries to generate (default 7).
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        visual_style: Optional[VisualStyle] = None,
        num_queries: Optional[int] = None,
    ):
        self._provider = provider
        self._style = visual_style or VisualStyle()
        self._num_queries = num_queries or get_config("search_planner.num_queries", 7)

    # ── Public API ─────────────────────────────────────────────────────

    def generate_queries(
        self,
        narration: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> list[str]:
        """Generate concept-driven search queries.

        Returns a deduplicated list of 5-10 visually distinct queries.
        """
        if self._provider:
            return self._generate_via_llm(narration, title, topic, purpose)
        return self._generate_fallback(narration, title, topic, purpose)

    # ── LLM-based generation ───────────────────────────────────────────

    def _generate_via_llm(
        self,
        narration: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> list[str]:
        """Generate concept-driven queries via LLM."""
        prompt = _CONCEPT_PROMPT.format(
            style_description=self._style.describe(),
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
            print(f"-> ConceptPlanner LLM error: {e} — using fallback")
            return self._generate_fallback(narration, title, topic, purpose)

    # ── Fallback generation ────────────────────────────────────────────

    def _generate_fallback(
        self,
        narration: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> list[str]:
        """Keyword-based fallback with visual diversity patterns."""
        keywords = self._extract_keywords(narration)
        if title:
            keywords.extend(self._extract_keywords(title))
        if topic:
            keywords.extend(self._extract_keywords(topic))

        seen: set[str] = set()
        deduped: list[str] = []
        for kw in keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                deduped.append(kw)

        primary = deduped[:3] if deduped else ["stock footage"]

        # Generate diverse visual patterns around each keyword
        patterns = [
            "{kw} cinematic wide shot",
            "{kw} close up detail",
            "{kw} aerial perspective",
            "{kw} atmospheric texture",
            "{kw} establishing shot",
            "{kw} scientific visualization",
            "{kw} slow motion capture",
        ]

        queries: list[str] = []
        for kw in primary:
            for pattern in patterns:
                q = pattern.format(kw=kw)
                queries.append(q)
                if len(queries) >= self._num_queries:
                    return queries[:self._num_queries]

        return queries[:self._num_queries]

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract meaningful keywords, filtering stop words."""
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
        seen: set[str] = set()
        result: list[str] = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                result.append(w)
        return result

    @staticmethod
    def _parse_queries(raw: str) -> list[str]:
        """Parse a JSON array of strings from LLM response."""
        import re as _re
        # Strip markdown fences
        cleaned = _re.sub(r"```(?:json)?", "", raw).strip()
        array_match = _re.search(r"\[.*?\]", cleaned, _re.DOTALL)
        if not array_match:
            return [line.strip(" \t\"',-.") for line in raw.split("\n")
                    if line.strip() and not line.strip().startswith(("#", "//"))]
        try:
            parsed = json.loads(array_match.group())
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            try:
                fixed = _re.sub(r",\s*]", "]", array_match.group())
                parsed = json.loads(fixed)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except (json.JSONDecodeError, Exception):
                pass
        return []

    @property
    def num_queries(self) -> int:
        return self._num_queries

    @property
    def visual_style(self) -> VisualStyle:
        return self._style
