"""
visual_intent_planner.py — Determines what the viewer should *see* for each scene.

Transforms narration + scene metadata into a structured VisualIntent that
guides all downstream asset retrieval. No provider search occurs before this layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional

from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider


# ═══════════════════════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════════════════════

class SceneType(str, Enum):
    EXPLANATION = "explanation"
    NARRATIVE = "narrative"
    VISUALIZATION = "visualization"
    TRANSITION = "transition"
    ESTABLISHING = "establishing"
    DEMONSTRATION = "demonstration"
    COMPARISON = "comparison"
    TIMELINE = "timeline"


class VisualCategory(str, Enum):
    SPACE = "space"
    SCIENCE = "science"
    NATURE = "nature"
    TECHNOLOGY = "technology"
    HISTORY = "history"
    MEDICAL = "medical"
    ENGINEERING = "engineering"
    FINANCE = "finance"
    LABORATORY = "laboratory"
    ANIMATION = "animation"
    ABSTRACT = "abstract"


class CameraStyle(str, Enum):
    SLOW_CINEMATIC = "slow_cinematic"
    DYNAMIC = "dynamic"
    TIMELAPSE = "timelapse"
    MACRO = "macro"
    AERIAL = "aerial"
    STEADICAM = "steadicam"
    POV = "pov"
    STATIC = "static"


class AssetType(str, Enum):
    STOCK_FOOTAGE = "stock_footage"
    ANIMATION = "animation"
    NASA_FOOTAGE = "nasa_footage"
    MANIM_GENERATED = "manim_generated"
    DATA_VISUALIZATION = "data_visualization"


@dataclass
class VisualIntent:
    """Complete visual intent for a single scene.

    This is the single source of truth for what assets to retrieve.
    """

    scene_type: SceneType = SceneType.EXPLANATION
    scientific_topic: str = ""
    visual_category: VisualCategory = VisualCategory.SCIENCE
    camera_style: CameraStyle = CameraStyle.SLOW_CINEMATIC
    asset_type: AssetType = AssetType.STOCK_FOOTAGE
    preferred_sources: list[str] = field(default_factory=lambda: ["pexels", "nasa"])
    must_have: list[str] = field(default_factory=list)
    must_not_have: list[str] = field(default_factory=lambda: ["people", "concerts", "sports"])
    animation_candidate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VisualIntent":
        # Handle enum fields stored as strings
        for enum_field, enum_cls in [
            ("scene_type", SceneType),
            ("visual_category", VisualCategory),
            ("camera_style", CameraStyle),
            ("asset_type", AssetType),
        ]:
            if enum_field in d and isinstance(d[enum_field], str):
                try:
                    d[enum_field] = enum_cls(d[enum_field])
                except ValueError:
                    pass
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a documentary visual director. Given a narration and scene title, produce a structured VisualIntent JSON object.

The VisualIntent describes what the viewer should SEE, not what the narration says.

Fields:
- scene_type: explanation|narrative|visualization|transition|establishing|demonstration|comparison|timeline
- scientific_topic: one-line topic this scene covers
- visual_category: space|science|nature|technology|history|medical|engineering|finance|laboratory|animation|abstract
- camera_style: slow_cinematic|dynamic|timelapse|macro|aerial|steadicam|pov|static
- asset_type: stock_footage|animation|nasa_footage|manim_generated|data_visualization
- preferred_sources: ["pexels", "nasa", "pixabay", "wikimedia"]
- must_have: ["objects that MUST appear on screen"]
- must_not_have: ["objects that MUST NOT appear"]
- animation_candidate: true if this topic is best shown as animation (black holes, redshift, equations, etc.)

Return ONLY the JSON object, no commentary.

Example:
{
  "scene_type": "explanation",
  "scientific_topic": "Fermi Paradox",
  "visual_category": "space",
  "camera_style": "slow_cinematic",
  "asset_type": "stock_footage",
  "preferred_sources": ["nasa", "pexels"],
  "must_have": ["radio telescope", "starry sky"],
  "must_not_have": ["people", "concerts"],
  "animation_candidate": false
}
"""


class VisualIntentPlanner:
    """Plan visual intent for each scene.

    Usage::

        planner = VisualIntentPlanner()
        intent = planner.plan(narration="Fermi asked...", scene_title="The Question")
    """

    def __init__(self, provider: Optional[LLMProvider] = None):
        self._provider = provider or self._default_provider()

    def plan(self, narration: str, scene_title: str = "") -> VisualIntent:
        """Produce a VisualIntent for a given narration + scene title."""
        try:
            prompt = f"Scene: {scene_title}\nNarration: {narration}\n\nVisualIntent:"
            full_prompt = f"{SYSTEM_PROMPT}\n\nScene: {scene_title}\nNarration: {narration}\n\nVisualIntent:"
            raw = self._provider.generate_text(full_prompt)
            intent = self._parse(raw)
            if intent:
                return intent
        except Exception as e:
            print(f"[VisualIntentPlanner] LLM failed: {e}")

        return self._default_intent(scene_title)

    # ── Internal ───────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw: str) -> Optional[VisualIntent]:
        """Parse LLM JSON response into VisualIntent."""
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
        return VisualIntent.from_dict(data)

    @staticmethod
    def _default_intent(scene_title: str) -> VisualIntent:
        """Sensible default when LLM is unavailable."""
        return VisualIntent(
            scientific_topic=scene_title,
            visual_category=VisualCategory.SCIENCE,
            must_have=[scene_title] if scene_title else ["science footage"],
        )

    @staticmethod
    def _default_provider() -> LLMProvider:
        factory = ProviderFactory()
        return factory.get_llm_provider_for_role("planner")
