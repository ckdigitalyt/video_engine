"""
visual_intent.py — The contract between planning and asset retrieval.

VisualIntent is the single structured model that tells the AssetRouter
*what* to search for, *where* to search, and *how* the result should look.
It is produced by the EditorialPlanner (or fallback planners) and consumed
by the VisualDirector.

Do NOT embed VisualIntent inside StoryPlanner or any other module.
It is a standalone contract that crosses module boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════


class AssetType(str, Enum):
    """The type of visual asset a scene or shot requires.

    The planner selects AssetType.  The renderer remains provider-agnostic.
    The AssetType determines which providers are consulted and in what order.
    """
    STOCK_VIDEO = "stock_video"
    NASA = "nasa"
    PEXELS = "pexels"
    PIXABAY = "pixabay"
    WIKIMEDIA = "wikimedia"
    MANIM = "manim"
    SVG = "svg"
    TIMELINE = "timeline"
    MAP = "map"
    CHART = "chart"
    PHOTO = "photo"
    ARCHIVE = "archive"


class CameraStyle(str, Enum):
    """Visual style for camera work."""
    SLOW_CINEMATIC = "slow_cinematic"
    DYNAMIC = "dynamic"
    TIMELAPSE = "timelapse"
    MACRO = "macro"
    AERIAL = "aerial"
    STEADICAM = "steadicam"
    POV = "pov"
    STATIC = "static"
    KEN_BURNS = "ken_burns"
    HANDHELD = "handheld"
    DRONE = "drone"
    SLOW_MOTION = "slow_motion"
    HYPER_LAPSE = "hyper_lapse"


class VisualCategory(str, Enum):
    """Category of visual content."""
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
    ARCHIVAL = "archival"
    EDUCATIONAL = "educational"
    DOCUMENTARY = "documentary"


# ═══════════════════════════════════════════════════════════════════════════
# VisualIntent — the contract
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class VisualIntent:
    """Complete visual intent for a single scene.

    This is the single contract between planning and retrieval.
    Every scene passes through VisualIntent before any provider search begins.

    Fields:
        scene_id: Index of the scene.
        scientific_concept: The core concept this scene covers.
        visual_objective: What the audience should *see* and understand.
        asset_type: Primary asset type for this scene.
        preferred_providers: Which providers to query (priority order).
        preferred_camera_style: How the camera should behave.
        animation_candidate: True if this concept is best shown as animation.
        animation_templates: Specific Manim templates to use.
        must_have_objects: Objects that MUST appear in the visual.
        must_not_have_objects: Objects that MUST NOT appear.
        confidence: How confident the planner is in this intent (0-1).
    """

    scene_id: int = 0
    scientific_concept: str = ""
    visual_objective: str = ""
    asset_type: AssetType = AssetType.STOCK_VIDEO
    visual_category: VisualCategory = VisualCategory.DOCUMENTARY
    preferred_providers: list[str] = field(default_factory=lambda: ["pexels", "pixabay", "nasa"])
    preferred_camera_style: CameraStyle = CameraStyle.SLOW_CINEMATIC
    animation_candidate: bool = False
    animation_templates: list[str] = field(default_factory=list)
    must_have_objects: list[str] = field(default_factory=list)
    must_not_have_objects: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "scientific_concept": self.scientific_concept,
            "visual_objective": self.visual_objective,
            "asset_type": self.asset_type.value,
            "visual_category": self.visual_category.value,
            "preferred_providers": list(self.preferred_providers),
            "preferred_camera_style": self.preferred_camera_style.value,
            "animation_candidate": self.animation_candidate,
            "animation_templates": list(self.animation_templates),
            "must_have_objects": list(self.must_have_objects),
            "must_not_have_objects": list(self.must_not_have_objects),
            "confidence": self.confidence,
        }

    @classmethod
    def from_editorial_plan(
        cls,
        scene_id: int,
        editorial_objective: Any,
        shot_sequence: list[Any],
        knowledge_entry_used: str = "",
    ) -> "VisualIntent":
        """Build a VisualIntent from an EditorialPlanner's output."""
        # The first shot determines the primary asset type
        primary_asset_type = AssetType.STOCK_VIDEO
        is_animation = False
        if shot_sequence:
            first_type = shot_sequence[0].asset_type
            if first_type == "manim":
                primary_asset_type = AssetType.MANIM
                is_animation = True
            elif first_type == "nasa":
                primary_asset_type = AssetType.NASA
            elif first_type == "chart" or first_type == "timeline":
                primary_asset_type = AssetType.CHART

        return cls(
            scene_id=scene_id,
            scientific_concept=knowledge_entry_used or editorial_objective.scene_title,
            visual_objective=editorial_objective.visual_goal,
            asset_type=primary_asset_type,
            animation_candidate=is_animation,
            confidence=0.7 if is_animation else 0.6,
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VisualIntent":
        """Reconstruct from dict (for serialisation)."""
        asset_type_str = d.get("asset_type", "stock_video")
        try:
            asset_type = AssetType(asset_type_str)
        except ValueError:
            asset_type = AssetType.STOCK_VIDEO

        camera_str = d.get("preferred_camera_style", "slow_cinematic")
        try:
            camera_style = CameraStyle(camera_str)
        except ValueError:
            camera_style = CameraStyle.SLOW_CINEMATIC

        cat_str = d.get("visual_category", "documentary")
        try:
            visual_category = VisualCategory(cat_str)
        except ValueError:
            visual_category = VisualCategory.DOCUMENTARY

        return cls(
            scene_id=d.get("scene_id", 0),
            scientific_concept=d.get("scientific_concept", ""),
            visual_objective=d.get("visual_objective", ""),
            asset_type=asset_type,
            visual_category=visual_category,
            preferred_providers=d.get("preferred_providers", ["pexels", "pixabay"]),
            preferred_camera_style=camera_style,
            animation_candidate=d.get("animation_candidate", False),
            animation_templates=d.get("animation_templates", []),
            must_have_objects=d.get("must_have_objects", []),
            must_not_have_objects=d.get("must_not_have_objects", []),
            confidence=d.get("confidence", 0.5),
        )
