"""
concept_planner.py — Visual concept planning for asset search.

Generates structured search queries from a scene's VisualIntent metadata
instead of using raw narration text.  This is the bridge between the
StoryPlanner's visual intent model and the AssetRouter's search interface.

Two modes:
1. **Intent-driven** (primary): Uses VisualIntent.concepts and
   VisualIntent.search_terms to generate targeted queries.
2. **Narration-driven** (fallback): Uses the LLM to extract visual
   concepts from narration text (original behavior).
"""

from __future__ import annotations

import json
import logging
import random
from typing import Optional

from src.models.schemas import VisualIntent
from src.providers.llm_provider import LLMProvider
from src.director.visual_style import VisualStyle
from src.utils.config import get_config
from src.assets.query_expander import expand_queries, expand_for_shot

logger = logging.getLogger(__name__)


class ConceptPlanner:
    """Generates visual search queries from scene metadata.

    When a scene has **VisualIntent** populated (with concepts and
    search_terms), the planner uses those directly via ``expand_queries()``.
    Otherwise it falls back to LLM-based concept extraction from the
    narration text, then expands those.

    Parameters
    ----------
    provider : LLMProvider, optional
        LLM provider for narration-based fallback.
    visual_style : VisualStyle, optional
        Current visual style context.
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        visual_style: Optional[VisualStyle] = None,
    ):
        self._provider = provider
        self._style = visual_style or VisualStyle()

    # ── Public API ─────────────────────────────────────────────────────

    def generate_queries(
        self,
        narration: str = "",
        title: str = "",
        topic: str = "",
        purpose: str = "general",
        visual_intent: Optional[VisualIntent] = None,
    ) -> list[str]:
        """Generate search queries for a scene.

        When *visual_intent* is provided with concepts or search_terms,
        uses those directly.  Otherwise falls back to LLM extraction
        from *narration*.

        Parameters
        ----------
        narration : str
            Scene narration text (fallback path only).
        title : str
            Scene title (used for context).
        topic : str
            Video topic.
        purpose : str
            Scene purpose description.
        visual_intent : VisualIntent | None
            Structured visual metadata (primary path).

        Returns
        -------
        list[str]
            Ranked search queries (best-first), up to 20.
        """
        # ── Primary path: use VisualIntent ────────────────────────────
        if visual_intent is not None:
            if visual_intent.search_terms or visual_intent.concepts:
                return expand_queries(
                    visual_intent,
                    topic=topic,
                    category=self._categorize_topic(topic),
                )

        # ── Fallback path: LLM extraction from narration ──────────────
        return self._llm_fallback(narration, title, topic, purpose)

    def generate_shot_queries(
        self,
        scene_visual_intent: Optional[VisualIntent],
        base_query: str,
        shot_type: str,
        topic: str,
    ) -> list[str]:
        """Generate per-shot queries for beat mode.

        Uses the scene's visual intent for context, then adds
        shot-type-specific diversification.

        Returns up to 5 queries.
        """
        category = self._categorize_topic(topic)

        # If we have a visual intent, use its search terms as base
        if scene_visual_intent and scene_visual_intent.search_terms:
            base = scene_visual_intent.search_terms[0]
        else:
            base = base_query

        return expand_for_shot(base, shot_type, topic, category)

    # ── Internal helpers ───────────────────────────────────────────────

    def _llm_fallback(
        self,
        narration: str,
        title: str,
        topic: str,
        purpose: str,
    ) -> list[str]:
        """Extract visual concepts from narration using the LLM.

        This is the original behavior, preserved for backward compatibility
        when VisualIntent is not available.
        """
        if not self._provider:
            return [topic, "stock footage", "documentary", "general"]

        prompt = (
            f"You are a visual search strategist for a documentary video.\n\n"
            f"Topic: {topic}\n"
            f"Scene: {title}\n"
            f"Purpose: {purpose}\n"
            f"Narration:\n{narration}\n\n"
            f"Generate up to 10 diverse search queries for stock footage "
            f"libraries.  Each query should be 2-5 words, optimised for "
            f"finding real-world video clips that visually match the "
            f"narrative concepts.\n\n"
            f"Rules:\n"
            f"1. Queries must be VISUAL (things you can film), not abstract.\n"
            f"2. Vary the style: wide shots, time-lapses, close-ups, "
            f"establishing shots, macro.\n"
            f"3. Include topic-specific keywords.\n"
            f"4. Avoid words like 'video', 'footage', 'stock'.\n\n"
            f"Return ONLY a JSON list of strings.  No markdown.  No explanation."
        )

        try:
            result = self._provider.generate_json(prompt)
            queries = json.loads(result)
            if isinstance(queries, list) and len(queries) > 0:
                return [str(q) for q in queries[:15]]
        except Exception as exc:
            logger.debug("LLM query generation failed: %s", exc)

        # Ultimate fallback
        return [topic, "stock footage", "documentary", "general"]

    @staticmethod
    def _categorize_topic(topic: str) -> str:
        """Simple topic classification."""
        tl = topic.lower()
        if any(w in tl for w in ["space", "star", "galaxy", "universe", "planet", "cosmic"]):
            return "Space"
        if any(w in tl for w in ["history", "war", "empire", "ancient", "medieval"]):
            return "History"
        if any(w in tl for w in ["science", "physics", "biology", "chemistry", "nature"]):
            return "Science"
        if any(w in tl for w in ["tech", "computer", "ai", "robot"]):
            return "Technology"
        return "General"
