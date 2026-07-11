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

from src.models.schemas import Scene, SceneNarration, VisualPlan, VisualIntent, SearchPlan, EditingPlan
from src.providers.llm_provider import LLMProvider
from src.providers.factory import ProviderFactory


# ── Visual-only fallback terms ────────────────────────────────────────

_VISUAL_FALLBACKS: dict[str, list[str]] = {
    "Space": [
        "deep space nebula 4K",
        "starfield timelapse cosmos",
        "galaxy spiral astronomy footage",
        "celestial space environment",
        "interstellar cosmic landscape",
        "astronomical deep field zoom",
        "solar system planet orbit animation",
        "Milky Way night sky panorama",
        "cosmic dust nebula close-up",
        "space documentary establishing shot",
        "universe background stars motion",
        "Hubble telescope deep space view",
    ],
}
from src.utils.config import get_config
from .templates import get_template, StoryTemplate


# ── Domain-specific concept maps for query expansion ──────────────────

_CONCEPT_MAPS: dict[str, dict[str, list[str]]] = {
    "Space": {
        "black sky": ["deep space", "night sky", "void of space", "cosmic darkness"],
        "stars": ["starfield", "celestial bodies", "stellar formation", "Milky Way"],
        "light": ["photons", "light spectrum", "electromagnetic waves", "visible light"],
        "vacuum": ["interstellar medium", "cosmic void", "empty space", "space vacuum"],
        "atmosphere": ["Earth atmosphere", "atmospheric scattering", "sky blue", "sunlight scattering"],
        "telescope": ["Hubble Space Telescope", "JWST", "observatory", "astronomical telescope"],
        "galaxy": ["spiral galaxy", "Andromeda", "deep field", "galactic cluster"],
        "wavelength": ["spectrum chart", "frequency diagram", "light wave", "electromagnetic spectrum"],
        "universe": ["observable universe", "cosmic web", "deep field", "universe expansion"],
        "sun": ["solar surface", "sunlight", "solar flare", "sun in space"],
        "earth": ["Earth from space", "blue marble", "planet Earth", "Earth orbit"],
        "astronaut": ["astronaut spacewalk", "ISS", "International Space Station", "space suit"],
        "infographic": ["science diagram", "educational graphic", "labeled chart", "data visualization"],
    },
}

_KEN_BURNS_CONCEPTS = {
    "nebula", "galaxy", "starfield", "deep space", "planet", "moon", "astronaut",
}

_DIAGRAM_CONCEPTS = {
    "wavelength", "spectrum", "frequency", "photon", "inverse-square",
    "orbital", "scale", "comparison", "timeline", "cross-section",
}

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
            # Generate visual intent from the scene content
            visual_intent = self._generate_visual_intent(
                scene_data, topic, i,
            )

            # ── Sanitise search terms against narration overlap ──────
            narration_text = scene_data.get("narration", "")
            sanitised_terms = self._sanitise_search_terms(
                visual_intent.search_terms,
                narration_text,
                topic,
            )

            scene = Scene(
                scene_id=i,
                title=scene_data.get("title", f"Scene {i}"),
                expected_duration=scene_data.get("estimated_duration", 12.0),
                topic=topic,
                narration=SceneNarration(
                    spoken_narration=scene_data.get("narration", "narration pending"),
                ),
                visual_intent=visual_intent,
                search_plan=SearchPlan(
                    asset_search_queries=sanitised_terms or ["general"],
                    primary_topic=topic,
                    scene_purpose=(visual_intent.visual_objective or "general")[:200],
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

    # ── Visual Intent generation ────────────────────────────────────────

    def _generate_visual_intent(
        self,
        scene_data: dict,
        topic: str,
        scene_index: int,
    ) -> VisualIntent:
        """Generate structured visual metadata for a scene.

        First attempts LLM-based generation. Falls back to rule-based
        expansion from the concept map when the LLM call fails or
        returns unusable output.
        """
        narration = scene_data.get("narration", "")
        title = scene_data.get("title", f"Scene {scene_index}")
        estimated_dur = scene_data.get("estimated_duration", 12.0)

        # Attempt LLM generation first
        intent = self._llm_visual_intent(narration, title, topic, estimated_dur)
        if intent is not None:
            return intent

        # Fallback: rule-based expansion from concept map
        return self._rule_based_visual_intent(narration, title, topic, scene_index)

    def _llm_visual_intent(
        self,
        narration: str,
        title: str,
        topic: str,
        duration: float,
    ) -> Optional[VisualIntent]:
        """Ask the LLM to generate structured visual metadata."""
        topic_category = self._classify_topic_for_intent(topic)

        prompt = f"""You generate structured visual metadata for documentary video scenes.

Topic: {topic}
Category: {topic_category}
Scene: {title}
Duration: {duration}s
Narration: {narration}

Generate a JSON object with:
- "visual_objective": what this scene should show VISUALLY (1 sentence)
- "concepts": up to 8 key concepts as a list of strings
- "required_assets": list of needed asset types from ["stock_video", "photograph", "diagram", "animation", "infographic", "timelapse"]
- "preferred_asset_types": list from ["wide_shot", "close_up", "infographic", "animation", "diagram", "timelapse", "macro"]
- "animation_requirements": describe any needed animation (e.g. "manim_photon_travel") or leave empty
- "camera_style": one of "static_diagram", "slow_pan", "ken_burns", "dynamic", "tilt_shift"
- "motion_style": one of "gentle", "dynamic", "none", "timelapse"
- "fallback_strategy": one of "fallback_to_diagram", "fallback_to_reuse", "fallback_to_photograph", ""
- "search_terms": generate 10-15 diverse search keywords for stock footage (e.g. "deep space nebula", "starfield 4K")

Return ONLY raw JSON. No markdown. No code fences."""

        try:
            result_str = self._provider.generate_json(prompt)
            if not result_str or len(result_str) < 20:
                return None
            result = json.loads(result_str)
            return VisualIntent(
                visual_objective=result.get("visual_objective", ""),
                concepts=result.get("concepts", [])[:20],
                required_assets=result.get("required_assets", [])[:5],
                preferred_asset_types=result.get("preferred_asset_types", [])[:10],
                animation_requirements=result.get("animation_requirements", ""),
                camera_style=result.get("camera_style", ""),
                motion_style=result.get("motion_style", ""),
                fallback_strategy=result.get("fallback_strategy", ""),
                search_terms=result.get("search_terms", [])[:30],
            )
        except Exception as exc:
            logger.debug("LLM visual intent failed for scene '%s': %s", title, exc)
            return None

    def _rule_based_visual_intent(
        self,
        narration: str,
        title: str,
        topic: str,
        scene_index: int,
    ) -> VisualIntent:
        """Generate visual intent from concept maps when LLM is unavailable."""
        narration_lower = narration.lower()
        concepts: list[str] = []
        search_terms: list[str] = []
        required_assets: list[str] = ["stock_video"]
        preferred_types: list[str] = ["wide_shot"]
        animation_req = ""
        camera_style = "slow_pan"
        motion_style = "gentle"
        fallback = ""

        # Build search terms from concept map
        category_map = _CONCEPT_MAPS.get(topic, {})
        for concept, keywords in category_map.items():
            if concept in narration_lower:
                concepts.append(concept)
                search_terms.extend(keywords)

        # Add topic-level keywords
        if search_terms:
            search_terms.append(f"{topic.lower()} documentary")
            search_terms.append(f"{topic.lower()} 4k")
            search_terms.append(f"{topic.lower()} footage")
        else:
            # Generic fallback
            search_terms = [
                f"{topic.lower()} documentary",
                f"{topic.lower()} stock footage",
                "science documentary",
                "educational footage",
            ]

        # Determine asset types from narration
        diag_keywords = {"wavelength", "spectrum", "frequency", "photon", "diagram", "scale", "comparison"}
        if diag_keywords & set(narration_lower.split()):
            required_assets.append("diagram")
            preferred_types.append("infographic")
            animation_req = "diagram_explainer"
            camera_style = "static_diagram"
            motion_style = "none"

        # Vary camera style per scene
        styles = ["slow_pan", "ken_burns", "static", "dynamic", "gentle_zoom"]
        camera_style = styles[scene_index % len(styles)]

        # De-duplicate search terms while preserving order
        seen: set[str] = set()
        unique_terms: list[str] = []
        for term in search_terms:
            t = term.strip().lower()
            if t and t not in seen:
                seen.add(t)
                unique_terms.append(term.strip())

        return VisualIntent(
            visual_objective=f"Visually illustrate: {title}",
            concepts=concepts[:20],
            required_assets=required_assets[:5],
            preferred_asset_types=preferred_types[:10],
            animation_requirements=animation_req,
            camera_style=camera_style,
            motion_style=motion_style,
            fallback_strategy=fallback,
            search_terms=unique_terms[:30],
        )

    @staticmethod
    def _sanitise_search_terms(
        search_terms: list[str],
        narration: str,
        topic: str,
    ) -> list[str]:
        """Replace any search term that has >60% word overlap with narration.

        The validator in Scene.check_no_narration_leak_in_search rejects
        queries whose word overlap with spoken narration exceeds 90%%.
        To stay well clear of that boundary we apply a 60%% pre-check.
        """
        if not narration or not search_terms:
            return search_terms

        narration_words: set[str] = set(narration.lower().split())
        if len(narration_words) < 3:
            return search_terms

        # Determine the topic category so we can pick appropriate fallbacks
        category = StoryPlanner._classify_topic_for_intent(topic)
        fallback_pool: list[str] = _VISUAL_FALLBACKS.get(
            category,
            _VISUAL_FALLBACKS.get("Space", []),
        )
        fallback_idx = 0

        result: list[str] = []
        for term in search_terms:
            query_words: set[str] = set(term.lower().split())
            if len(query_words) < 3:
                result.append(term)
                continue

            overlap = len(narration_words & query_words) / len(query_words)
            if overlap > 0.60:
                # Replace with a visual-only alternative from the fallback pool
                replacement = fallback_pool[fallback_idx % len(fallback_pool)]
                fallback_idx += 1
                logger.info(
                    "Replaced search term '%s' (%.0f%% word overlap) with '%s'",
                    term, overlap * 100, replacement,
                )
                result.append(replacement)
            else:
                result.append(term)

        return result

    @staticmethod
    def _classify_topic_for_intent(topic: str) -> str:
        """Simple topic classification for visual intent generation."""
        topic_lower = topic.lower()
        if any(w in topic_lower for w in ["space", "star", "galaxy", "universe", "planet"]):
            return "Space"
        if any(w in topic_lower for w in ["history", "war", "empire", "ancient", "medieval"]):
            return "History"
        if any(w in topic_lower for w in ["science", "physics", "biology", "chemistry"]):
            return "Science"
        if any(w in topic_lower for w in ["nature", "animal", "ocean", "forest"]):
            return "Nature"
        if any(w in topic_lower for w in ["tech", "computer", "ai", "robot"]):
            return "Technology"
        if any(w in topic_lower for w in ["finance", "money", "economy", "market"]):
            return "Finance"
        return "General"


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
