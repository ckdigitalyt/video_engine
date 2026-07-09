"""
planner.py — Two-phase story planner for the video_engine pipeline.

Phase 1 (Outline):  Generates a narrative outline from the topic and the
                    selected story template.

Phase 2 (Scenes):   Uses the outline as context to produce a complete set
                    of scene dicts matching the schema expected by the
                    execution node in ``orchestrator.py``.

The planner is provider-independent — it works with any ``LLMProvider``
implementation (DeepSeek, Gemini, etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.models.schemas import Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan
from src.providers.llm_provider import LLMProvider
from src.providers.factory import ProviderFactory
from src.utils.config import get_config
from .templates import get_template, StoryTemplate

logger = logging.getLogger(__name__)


class StoryPlanner:
    """Two-phase story planner that produces a ``plan_json`` scene list.

    Parameters
    ----------
    provider : LLMProvider, optional
        LLM provider for text generation.  If ``None``, uses the configured
        provider from ``pipeline.roles.planner`` in YAML, then falls back to
        ``pipeline.roles.default``, and finally ``pipeline.roles.fallback``.
    template_name : str, optional
        Story template name.  If ``None``, uses ``planner.story_template``
        from config (default ``"documentary"``).
    target_scene_count : int, optional
        Minimum number of scenes to generate.  If ``None``, uses
        ``planner.target_scene_count`` from config.
    target_duration : int, optional
        Target video length in seconds.  If ``None``, uses
        ``planner.target_duration`` from config.
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        template_name: Optional[str] = None,
        target_scene_count: Optional[int] = None,
        target_duration: Optional[int] = None,
    ):
        # Provider selection: explicit argument > factory default > factory fallback
        if provider is not None:
            self._provider = provider
        else:
            _factory = ProviderFactory()
            try:
                # Try the role-specific planner provider first
                self._provider = _factory.get_llm_provider_for_role("planner")
            except (ValueError, ImportError):
                try:
                    # Fall back to default provider
                    self._provider = _factory.get_default_llm_provider()
                except (ValueError, ImportError):
                    # Ultimate fallback
                    self._provider = _factory.get_fallback_llm_provider()
        self._template = get_template(template_name)
        self._target_scene_count = (
            target_scene_count
            if target_scene_count is not None
            else get_config("planner.target_scene_count", 10)
        )
        self._target_duration = (
            target_duration
            if target_duration is not None
            else get_config("planner.target_duration", 120)
        )

    # ── Public API ───────────────────────────────────────────────────────

    def generate_plan(self, topic: str) -> list[Scene]:
        """Generate a complete plan for a topic.

        Internally runs two phases:

        1. Outline generation (narrative arc).
        2. Scene generation (expanded scenes).

        Returns a list of Scene objects wrapping the generated content.

        Parameters
        ----------
        topic : str
            The video topic.
        """
        logger.info("Phase 1: Generating outline for '%s' using template '%s'",
                     topic, self._template.name)
        outline = self._generate_outline(topic)

        logger.info("Phase 2: Generating scenes from outline")
        scenes_json = self._generate_scenes(topic, outline)

        # Parse scene dicts and wrap in Scene objects
        scene_dicts = json.loads(scenes_json).get("scenes", [])
        scenes: list[Scene] = []
        for i, scene_data in enumerate(scene_dicts):
            scene = Scene(
                scene_id=i,
                title=scene_data.get("title", f"Scene {i}"),
                expected_duration=scene_data.get("estimated_duration", 12.0),
                topic=topic,
                narration=SceneNarration(
                    spoken_narration=scene_data.get("narration", "narration pending"),
                ),
                search_plan=SearchPlan(
                    asset_search_queries=["general"],
                    primary_topic=topic,
                ),
                visual_plan=VisualPlan(),
                editing_plan=EditingPlan(),
            )
            scenes.append(scene)

        return scenes

    # ── Phase 1: Outline ─────────────────────────────────────────────────

    def _generate_outline(self, topic: str) -> str:
        """Produce a structured narrative outline."""

        roles_text = "\n".join(
            f"  Scene {i+1}: {role}"
            for i, role in enumerate(self._template.roles)
        )

        prompt = f"""You are the Director Agent for a YouTube documentary channel.

Topic: "{topic}"
Story Template: "{self._template.name}" — {self._template.description}
Target Scenes: {self._target_scene_count}
Target Duration: {self._target_duration} seconds

Phase 1: Generate a narrative outline BEFORE writing any scene details.

The outline should define:
1. A compelling overall narrative arc (1-2 sentences).
2. A sequence of {max(len(self._template.roles), self._target_scene_count)} scenes.
   For each, specify:
   - The narrative role it plays
   - The unique purpose and angle (what new information or perspective it brings)
   - How it connects to the previous and next scene
   - The type of visual that would accompany it

Use the following template roles as a starting point — you may expand or adapt them
to fit the topic depth:
{roles_text}

Output ONLY a raw JSON object. Do not use markdown. Do not wrap in fences.

Schema:
{{
  "narrative_arc": "Brief description of the overall story arc.",
  "scenes": [
    {{
      "role": "Hook",
      "purpose": "What this scene uniquely contributes.",
      "continuity": "How it connects to surrounding scenes.",
      "visual_style": "Type of stock footage suitable (e.g. establishing wide, close-up detail, animated graph)."
    }}
  ]
}}

Rules:
1. Each scene must serve a unique narrative purpose.
2. Avoid repetitive language across role descriptions.
3. Visual styles should be diverse (wide shots, close-ups, graphic overlays, nature, urban, etc.).
4. The arc must have a clear beginning, middle, and end.
"""
        return self._provider.generate_json(prompt)

    # ── Phase 2: Scene generation ───────────────────────────────────────

    def _generate_scenes(self, topic: str, outline_json: str) -> str:
        """Produce full scene dicts from the outline."""

        words_per_duration = get_config("planner.words_per_second", 3)
        narration_style = get_config("planner.narration_style", "informative but conversational")
        query_style = get_config("planner.search_query_style", "descriptive, landscape stock footage terms")

        prompt = f"""You are the Director Agent for a YouTube documentary channel.

Topic: "{topic}"
Target Scenes: {self._target_scene_count}
Target Duration: {self._target_duration} seconds
Narration Style: {narration_style}
Search Query Style: {query_style}

You have ALREADY created the following narrative outline.
Use it as your blueprint — do NOT deviate from its structure.

=== NARRATIVE OUTLINE ===
{outline_json}
=== END OUTLINE ===

Phase 2: Now expand the outline into a complete set of scene descriptions.

Each scene MUST:
- Serve the exact narrative role defined in the outline.
- Have a unique search_query (optimised for stock footage libraries).
- Have narration text matching the scene purpose.
- Estimate duration so that narration ≈ {words_per_duration} words/second.
- Maintain continuity with surrounding scenes.

Output ONLY a raw JSON object. Do not use markdown. Do not wrap in fences.

Schema:
{{
  "scenes": [
    {{
      "scene_id": 1,
      "title": "Scene title capturing the moment",
      "search_query": "descriptive stock footage keyword set",
      "narration": "Narration text (~{words_per_duration} words per second of estimated_duration).",
      "estimated_duration": 10
    }}
  ]
}}

Rules:
1. scene_id starts at 1 and increments by 1.
2. Number of scenes must be between {max(8, self._target_scene_count)} and 15.
3. search_query must be unique across all scenes.
4. Narration must be roughly {words_per_duration} words per second of estimated_duration.
5. Ensure logical progression — open strongly, develop the argument, conclude.
6. No duplicated scenes, titles, or narration.
7. Smooth narrative transitions between consecutive scenes.
8. Search queries must be optimised for finding high-quality stock footage.
9. Vary the search_query style across scenes (wide landscapes, close details, action shots, etc.).
"""
        return self._provider.generate_json(prompt)
