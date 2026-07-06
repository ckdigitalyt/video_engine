"""
visual_style.py — Global Visual Style object.

Created once before scene generation, ``VisualStyle`` defines the
aesthetic identity for the entire video.  Every scene and asset must
conform to this style.

Aesthetics
----------
- photorealistic     : Real-world photography, natural lighting, minimal CGI
- cinematic          : Film-like (anamorphic flares, shallow DOF, grading)
- documentary        : Neutral, informative, well-lit, straight-on framing
- infographic        : 2D renders, charts, graphs, animated text (future use)
- archival           : Black & white or sepia, historical grain, old footage

Attributes
----------
- aesthetic          : Primary aesthetic category
- sub_aesthetic      : Refinement (e.g. "space", "nature", "historical")
- color_palette      : List of hex colour codes for grading hint
- mood               : "bright" | "dramatic" | "neutral" | "mysterious" | "warm"
- pace               : "fast" | "medium" | "slow"
- preferred_categories : Topic categories that define the visual domain
- avoid_categories   : Categories to avoid (e.g. avoid cartoon for documentary)
- creator_prompt     : LLM prompt fragment for scene generation
- provider_prefs     : Preferred provider names in priority order
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from src.utils.config import get_config


# ── Style definitions ───────────────────────────────────────────────────

STYLE_DEFINITIONS: dict[str, dict] = {
    "photorealistic": {
        "color_palette": ["#87CEEB", "#2F4F4F", "#708090", "#F5F5DC", "#A9A9A9"],
        "mood": "bright",
        "pace": "medium",
        "avoid_categories": ["Animation", "Cartoon", "CGI"],
        "provider_prefs": ["pixabay", "pexels", "nasa"],
        "creator_prompt": (
            "Use photorealistic stock footage. "
            "Prefer real-world photography, natural lighting, and minimal CGI. "
            "All scenes should look like documentary nature footage."
        ),
    },
    "cinematic": {
        "color_palette": ["#1a1a2e", "#16213e", "#0f3460", "#e94560", "#533483"],
        "mood": "dramatic",
        "pace": "slow",
        "avoid_categories": ["Cartoon", "Infographic", "Low-res"],
        "provider_prefs": ["pixabay", "pexels"],
        "creator_prompt": (
            "Use cinematic stock footage with dramatic lighting. "
            "Prefer slow-motion, shallow depth of field, anamorphic flares. "
            "Every frame should look like a film."
        ),
    },
    "documentary": {
        "color_palette": ["#D3D3D3", "#696969", "#F0E68C", "#8FBC8F", "#BC8F8F"],
        "mood": "neutral",
        "pace": "medium",
        "avoid_categories": ["Cartoon", "Infographic", "CGI"],
        "provider_prefs": ["pixabay", "pexels", "wikimedia"],
        "creator_prompt": (
            "Use documentary-style footage. "
            "Prefer neutral, well-lit, informative shots. "
            "Prioritise educational and archival-quality visuals."
        ),
    },
    "archival": {
        "color_palette": ["#8B7355", "#6B4226", "#4A3728", "#2C1810", "#1A0F0A"],
        "mood": "mysterious",
        "pace": "slow",
        "avoid_categories": ["CGI", "Animation", "Colorful"],
        "provider_prefs": ["wikimedia", "pixabay", "pexels"],
        "creator_prompt": (
            "Use archival, historical footage or sepia-toned images. "
            "Prefer black & white, old photographs, historical reenactments. "
            "Avoid modern, colourful, or CGI content."
        ),
    },
    "space": {
        "color_palette": ["#000011", "#0a0a2e", "#1a1a4e", "#FFD700", "#4169E1"],
        "mood": "mysterious",
        "pace": "slow",
        "avoid_categories": ["Animation", "Infographic"],
        "provider_prefs": ["nasa", "pixabay", "pexels"],
        "creator_prompt": (
            "Use space photography and astrophysics visuals. "
            "Prefer NASA imagery, deep space photography, telescope captures. "
            "Avoid artistic CGI unless it depicts known phenomena."
        ),
    },
    "educational": {
        "color_palette": ["#E8F5E9", "#C8E6C9", "#A5D6A7", "#66BB6A", "#2E7D32"],
        "mood": "bright",
        "pace": "fast",
        "avoid_categories": ["Dramatic", "Scary", "Violent"],
        "provider_prefs": ["pixabay", "pexels", "wikimedia"],
        "creator_prompt": (
            "Use clear, educational-style footage. "
            "Prefer diagrams, illustrations, lab settings, classroom environments. "
            "Every scene should support learning."
        ),
    },
}


@dataclass
class VisualStyle:
    """Global visual identity for a video.

    Parameters
    ----------
    aesthetic : str
        Primary aesthetic category (e.g. ``"photorealistic"``).
    sub_aesthetic : str | None
        Optional refinement (e.g. ``"space"``, ``"historical"``).
    color_palette : list[str]
        Hex colour codes suggesting the video's colour grade.
    mood : str
        Emotional tone for the video.
    pace : str
        Editing pace (affects scene duration planning).
    preferred_categories : list[str]
        Topic categories that define the visual domain.
    avoid_categories : list[str]
        Visual categories to avoid.
    provider_prefs : list[str]
        Preferred provider names in priority order.
    creator_prompt : str
        LLM prompt fragment used during scene generation to guide narration style.
    """

    aesthetic: str = "photorealistic"
    sub_aesthetic: Optional[str] = None
    color_palette: list[str] = field(default_factory=lambda: ["#87CEEB", "#2F4F4F", "#708090", "#F5F5DC", "#A9A9A9"])
    mood: str = "neutral"
    pace: str = "medium"
    preferred_categories: list[str] = field(default_factory=lambda: ["General"])
    avoid_categories: list[str] = field(default_factory=list)
    provider_prefs: list[str] = field(default_factory=lambda: ["pixabay", "pexels"])
    creator_prompt: str = "Use photorealistic stock footage."

    # ── Factory ────────────────────────────────────────────────────────

    @classmethod
    def for_topic(
        cls,
        topic: str,
        category: Optional[str] = None,
    ) -> "VisualStyle":
        """Create a VisualStyle appropriate for *topic*.

        The style is inferred from the topic category and configured
        aesthetic mapping.

        Example::

            style = VisualStyle.for_topic("The Fermi Paradox", "Space")
            # aesthetic = "space", mood = "mysterious", pace = "slow"
        """
        # Built-in default mapping (used when config is absent)
        _DEFAULT_AESTHETIC_MAP = {
            "Space": "space",
            "History": "archival",
            "Science": "photorealistic",
            "Nature": "photorealistic",
            "Technology": "cinematic",
            "Finance": "educational",
            "General": "documentary",
        }
        # Read aesthetic mapping from config, fall back to defaults
        aesthetic_map = get_config("visual_director.aesthetic_mapping", {})
        if not aesthetic_map:
            aesthetic_map = _DEFAULT_AESTHETIC_MAP
        aesthetic_name = aesthetic_map.get(category, "photorealistic") if category else "photorealistic"

        # Get style definition or fall back to photorealistic
        definition = STYLE_DEFINITIONS.get(
            aesthetic_name,
            STYLE_DEFINITIONS["photorealistic"],
        )

        preferred = []
        if category:
            # Also load category-specific provider prefs from config routing
            routes = get_config("asset_routing.routes", {})
            preferred = routes.get(category, definition["provider_prefs"])

        return cls(
            aesthetic=aesthetic_name,
            sub_aesthetic=category.lower() if category else None,
            color_palette=list(definition["color_palette"]),
            mood=definition["mood"],
            pace=definition["pace"],
            preferred_categories=[category] if category else ["General"],
            avoid_categories=list(definition["avoid_categories"]),
            provider_prefs=preferred or list(definition["provider_prefs"]),
            creator_prompt=definition["creator_prompt"],
        )

    # ── Description ────────────────────────────────────────────────────

    def describe(self) -> str:
        """Return a human-readable description of this style."""
        parts = [
            f"Aesthetic: {self.aesthetic}",
            f"Mood: {self.mood}",
            f"Pace: {self.pace}",
        ]
        if self.sub_aesthetic:
            parts.append(f"Sub-aesthetic: {self.sub_aesthetic}")
        return " | ".join(parts)

    def to_prompt(self) -> str:
        """Return the style as a prompt fragment for LLM scene generation."""
        return (
            f"Visual style: {self.aesthetic}. "
            f"Mood: {self.mood}. "
            f"Pace: {self.pace}. "
            f"{self.creator_prompt}"
        )
