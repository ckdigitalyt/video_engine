"""
editorial_planner.py — Editorial Intelligence for documentary video.

The EditorialPlanner sits between the StoryPlanner and the VisualDirector.
Instead of relying on LLM-invented search terms, it consults the Visual
Knowledge Library to determine:
  1. What the audience should understand (editorial objective)
  2. What they should see (visual objective)
  3. The emotional arc across scenes (emotional tone)
  4. How shots should progress (visual progression)
  5. Which asset types are appropriate (stock, Manim, NASA, etc.)

Key design principle:
  - Reason about what the audience should *understand*, not which words
    appear in the narration text.
  - Consult the Knowledge Library BEFORE generating any search queries.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from src.knowledge.visual_knowledge_library import (
    VisualKnowledgeLibrary,
    KnowledgeEntry,
)
from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class EditorialObjective:
    """What the audience should understand from a scene.

    This is NOT the narration text — it is the editorial intent.
    """

    scene_id: int
    scene_title: str
    editorial_goal: str  # "explain contradiction", "show scale", "build mystery"
    visual_goal: str  # "show vastness of space", "illustrate cause and effect"
    emotional_tone: str  # "wonder", "tension", "contemplation", "revelation"
    knowledge_entry_used: str  # Concept name that matched in the library


@dataclass
class ShotObjective:
    """A single shot's editorial and visual objective."""

    shot_index: int
    purpose: str  # "establish", "explain", "illustrate", "transition", "emphasize"
    emotion: str
    asset_type: str  # "stock_video", "manim", "nasa", "wikimedia", "chart", "timeline"
    search_guidance: str  # What to search for (not the final query — guidance)
    fallback_plan: str  # What to try if this shot type fails
    duration_seconds: float = 5.0


@dataclass
class SceneEditorialPlan:
    """Complete editorial plan for one scene.

    Generated BEFORE any asset retrieval.
    """

    scene_id: int
    title: str
    editorial_objective: EditorialObjective
    shot_sequence: list[ShotObjective]  # Planned shots
    transition_plan: list[str]  # Transitions between shots
    recommended_asset_types: list[str]  # Priority-ordered asset types
    narrative_role: str  # "hook", "context", "exploration", "climax", "conclusion"
    confidence: float = 0.0  # How confident the planner is in this plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "title": self.title,
            "editorial_objective": asdict(self.editorial_objective),
            "shot_sequence": [asdict(s) for s in self.shot_sequence],
            "transition_plan": list(self.transition_plan),
            "recommended_asset_types": list(self.recommended_asset_types),
            "narrative_role": self.narrative_role,
            "confidence": self.confidence,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════════════════

EDITORIAL_PROMPT = """You are an award-winning documentary editorial director.  Your job is to plan what the audience should *understand* from each scene — not what words the narration contains.

Given a narration, scene title, topic, and optional knowledge entry from our Visual Knowledge Library, produce a complete editorial plan.

For each scene, define:

1. **Editorial goal**: What must the audience *understand* after watching?  (e.g. "The contradiction between high probability of life and lack of contact", "Why gravity is not a force but a curvature")
2. **Visual goal**: What must they *see* to understand it?  (e.g. "show the scale of the Milky Way", "illustrate the rubber sheet analogy")
3. **Emotional tone**: The feeling each scene should evoke (wonder, tension, solemn, contemplative, urgent, triumphant, etc.)
4. **Shot sequence**: For each shot, specify:
   - purpose (establish, explain, illustrate, transition, emphasize, contrast, reveal, summarize)
   - emotion
   - asset type (stock_video, manim, nasa, wikimedia, chart, timeline, photo, animation)
   - search guidance (what to show — NOT a search query, a descriptive intent)
   - fallback plan (what to try if primary asset type fails)
   - duration (seconds)
5. **Transition plan**: How to move between shots
6. **Recommended asset types**: Priority-ordered list

Knowledge entry provided (if available):
{knowledge_context}

Scene title: {title}
Topic: {topic}
Narration: {narration}
Narrative role (hook/context/exploration/climax/conclusion): {role}

Return ONLY valid JSON with this shape:
{{
  "editorial_goal": "...",
  "visual_goal": "...",
  "emotional_tone": "...",
  "shot_sequence": [
    {{
      "purpose": "establish",
      "emotion": "wonder",
      "asset_type": "stock_video",
      "search_guidance": "Milky Way galaxy at night from remote mountain observatory",
      "fallback_plan": "stock_video",
      "duration_seconds": 5.0
    }}
  ],
  "transition_plan": ["dissolve", "crossfade"],
  "recommended_asset_types": ["manim", "stock_video", "nasa"],
  "confidence": 0.85
}}
"""


# ═══════════════════════════════════════════════════════════════════════════
# EditorialPlanner
# ═══════════════════════════════════════════════════════════════════════════


class EditorialPlanner:
    """Plan what the audience should understand and see.

    Usage::

        planner = EditorialPlanner()
        editorial_plans = planner.plan_all(
            scenes=[...],  # list of Scene objects from StoryPlanner
            topic="The Fermi Paradox",
        )
        for plan in editorial_plans:
            # Consult plan.shot_sequence for shot intents
            # Consult plan.recommended_asset_types for routing
    """

    def __init__(
        self,
        knowledge_library: Optional[VisualKnowledgeLibrary] = None,
        provider: Optional[LLMProvider] = None,
    ):
        self._knowledge_library = knowledge_library or VisualKnowledgeLibrary()
        factory = ProviderFactory()
        self._provider = provider or factory.get_llm_provider_for_role("planner")

    # ── Public API ────────────────────────────────────────────────────

    def plan_scene(
        self,
        scene_id: int,
        title: str,
        narration: str,
        topic: str = "",
        narrative_role: str = "exploration",
    ) -> SceneEditorialPlan:
        """Plan a single scene's editorial direction.

        Always consults the Visual Knowledge Library first.

        Args:
            scene_id: Scene index.
            title: Scene title.
            narration: Narration text for this scene.
            topic: Overall video topic.
            narrative_role: Role in the overall narrative arc.

        Returns:
            SceneEditorialPlan with shot sequence, transitions, asset types.
        """
        # Step 1: Consult Knowledge Library
        knowledge_entry = self._find_knowledge_entry(title, narration, topic)

        # Step 2: Build LLM prompt with knowledge context
        plan_data = self._llm_plan(scene_id, title, narration, topic, narrative_role, knowledge_entry)

        # Step 3: Convert to typed plan
        if plan_data:
            return self._to_editorial_plan(scene_id, title, plan_data, knowledge_entry, narrative_role)

        # Fallback: generate plan from knowledge entry only
        return self._fallback_plan(scene_id, title, narration, knowledge_entry, narrative_role)

    def plan_all(
        self,
        scenes_with_narration: list[dict[str, Any]],
        topic: str = "",
    ) -> list[SceneEditorialPlan]:
        """Plan all scenes in a documentary.

        Args:
            scenes_with_narration: List of dicts with keys:
                - scene_id: int
                - title: str
                - narration: str
                - narrative_role: str (optional)
            topic: Overall documentary topic.

        Returns:
            List of SceneEditorialPlan, one per scene.
        """
        # Determine narrative roles if not provided
        total = len(scenes_with_narration)
        roles = ["hook", "context"]
        if total >= 3:
            roles += ["exploration"] * max(0, total - 4)
        if total >= 2:
            roles += ["climax", "conclusion"]

        plans = []
        for i, scene_data in enumerate(scenes_with_narration):
            role = scene_data.get("narrative_role", roles[i] if i < len(roles) else "exploration")
            plan = self.plan_scene(
                scene_id=scene_data.get("scene_id", i),
                title=scene_data.get("title", ""),
                narration=scene_data.get("narration", ""),
                topic=topic,
                narrative_role=role,
            )
            plans.append(plan)

        return plans

    def get_visual_knowledge(self) -> VisualKnowledgeLibrary:
        """Expose the knowledge library for inspection."""
        return self._knowledge_library

    # ── Internal ───────────────────────────────────────────────────────

    def _find_knowledge_entry(self, title: str, narration: str, topic: str) -> Optional[KnowledgeEntry]:
        """Find the best matching knowledge entry for this scene."""
        # Try lookups in priority order
        candidates = [title, topic, narration]
        for text in candidates:
            if not text:
                continue
            entry = self._knowledge_library.lookup(text)
            if entry:
                return entry
            entry = self._knowledge_library.lookup_fuzzy(narration)
            if entry:
                return entry

        return None

    def _llm_plan(
        self,
        scene_id: int,
        title: str,
        narration: str,
        topic: str,
        narrative_role: str,
        knowledge_entry: Optional[KnowledgeEntry],
    ) -> Optional[dict[str, Any]]:
        """Use LLM to generate editorial plan with knowledge context."""
        # Build knowledge context
        if knowledge_entry:
            knowledge_context = (
                f"Concept: {knowledge_entry.concept}\n"
                f"Explanation: {knowledge_entry.documentary_explanation[:200]}\n"
                f"Preferred motifs: {', '.join(knowledge_entry.preferred_visual_motifs[:5])}\n"
                f"Animation strategy: {knowledge_entry.preferred_animation_strategy}\n"
                f"Avoid keywords: {', '.join(knowledge_entry.keywords_to_avoid[:5])}"
            )
        else:
            knowledge_context = "No specific knowledge entry found for this concept."

        prompt = EDITORIAL_PROMPT.format(
            knowledge_context=knowledge_context,
            title=title,
            topic=topic,
            narration=narration,
            role=narrative_role,
        )

        try:
            raw = self._provider.generate_text(prompt)
            return self._parse_llm_response(raw)
        except Exception as e:
            logger.warning(f"EditorialPlanner LLM failed for scene {scene_id}: {e}")
            return None

    @staticmethod
    def _parse_llm_response(raw: str) -> Optional[dict[str, Any]]:
        """Parse LLM JSON response."""
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
            return None

        if not isinstance(data, dict):
            return None

        return data

    @staticmethod
    def _to_editorial_plan(
        scene_id: int,
        title: str,
        data: dict[str, Any],
        knowledge_entry: Optional[KnowledgeEntry],
        narrative_role: str,
    ) -> SceneEditorialPlan:
        """Convert LLM response to typed SceneEditorialPlan."""
        # Build editorial objective
        objective = EditorialObjective(
            scene_id=scene_id,
            scene_title=title,
            editorial_goal=data.get("editorial_goal", "Understand the concept"),
            visual_goal=data.get("visual_goal", "Show relevant visuals"),
            emotional_tone=data.get("emotional_tone", "neutral"),
            knowledge_entry_used=knowledge_entry.concept if knowledge_entry else "none",
        )

        # Build shot sequence
        shot_sequence = []
        for i, shot_data in enumerate(data.get("shot_sequence", [])):
            shot = ShotObjective(
                shot_index=i,
                purpose=shot_data.get("purpose", "illustrate"),
                emotion=shot_data.get("emotion", "neutral"),
                asset_type=shot_data.get("asset_type", "stock_video"),
                search_guidance=shot_data.get("search_guidance", ""),
                fallback_plan=shot_data.get("fallback_plan", "stock_video"),
                duration_seconds=float(shot_data.get("duration_seconds", 5.0)),
            )
            shot_sequence.append(shot)

        # Build plan
        return SceneEditorialPlan(
            scene_id=scene_id,
            title=title,
            editorial_objective=objective,
            shot_sequence=shot_sequence,
            transition_plan=data.get("transition_plan", ["cut"]),
            recommended_asset_types=data.get("recommended_asset_types", ["stock_video"]),
            narrative_role=narrative_role,
            confidence=float(data.get("confidence", 0.5)),
        )

    def _fallback_plan(
        self,
        scene_id: int,
        title: str,
        narration: str,
        knowledge_entry: Optional[KnowledgeEntry],
        narrative_role: str,
    ) -> SceneEditorialPlan:
        """Generate a simple fallback plan when LLM is unavailable."""
        # Use knowledge entry if available
        if knowledge_entry:
            shots = []
            for i, motif in enumerate(knowledge_entry.preferred_visual_motifs[:4]):
                asset_type = "manim" if (
                    knowledge_entry.preferred_animation_strategy == "manim"
                    and i == 0
                ) else "stock_video"
                shots.append(ShotObjective(
                    shot_index=i,
                    purpose="establish" if i == 0 else "illustrate",
                    emotion="wonder" if i == 0 else "neutral",
                    asset_type=asset_type,
                    search_guidance=motif,
                    fallback_plan=(
                        knowledge_entry.recommended_fallback_sequence[i][0]
                        if i < len(knowledge_entry.recommended_fallback_sequence)
                        else "stock_video"
                    ),
                    duration_seconds=6.0 if i == 0 else 4.0,
                ))

            return SceneEditorialPlan(
                scene_id=scene_id,
                title=title,
                editorial_objective=EditorialObjective(
                    scene_id=scene_id,
                    scene_title=title,
                    editorial_goal=knowledge_entry.documentary_explanation[:100],
                    visual_goal="Show " + ", ".join(knowledge_entry.preferred_visual_motifs[:2]),
                    emotional_tone="neutral",
                    knowledge_entry_used=knowledge_entry.concept,
                ),
                shot_sequence=shots,
                transition_plan=knowledge_entry.transition_suggestions[:3],
                recommended_asset_types=["stock_video", "nasa", "wikimedia"],
                narrative_role=narrative_role,
                confidence=0.6,
            )

        # Truly empty fallback
        words = narration.split()
        chunk_size = max(1, len(words) // 4)
        shots = []
        for i in range(min(4, max(1, len(words) // 3))):
            chunk = " ".join(words[i * chunk_size:(i + 1) * chunk_size])
            shots.append(ShotObjective(
                shot_index=i,
                purpose=["establish", "illustrate", "explain", "transition"][i],
                emotion="neutral",
                asset_type="stock_video",
                search_guidance=chunk[:80] if chunk else "science documentary",
                fallback_plan="stock_video",
                duration_seconds=5.0,
            ))

        return SceneEditorialPlan(
            scene_id=scene_id,
            title=title,
            editorial_objective=EditorialObjective(
                scene_id=scene_id, scene_title=title,
                editorial_goal="Inform", visual_goal="Show relevant imagery",
                emotional_tone="neutral", knowledge_entry_used="none",
            ),
            shot_sequence=shots,
            transition_plan=["cut", "dissolve"],
            recommended_asset_types=["stock_video"],
            narrative_role=narrative_role,
            confidence=0.3,
        )
