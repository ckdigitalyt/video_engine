"""
storyboard_planner.py — Storyboard planning before asset retrieval.

Generates a full storyboard plan per shot BEFORE downloading anything.
Each shot specifies: purpose, emotion, camera, duration, movement, asset source,
transition, overlay, animation. Then we perform retrieval against the plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider
from src.assets.visual_intent import VisualIntent, AssetType
from src.knowledge.visual_knowledge_library import KnowledgeEntry


# ═══════════════════════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════════════════════

class ShotPurpose(str, Enum):
    ESTABLISH = "establish"
    EXPLAIN = "explain"
    ILLUSTRATE = "illustrate"
    TRANSITION = "transition"
    EMPHASIZE = "emphasize"
    CONTRAST = "contrast"
    REVEAL = "reveal"
    SUMMARY = "summary"


class ShotEmotion(str, Enum):
    NEUTRAL = "neutral"
    WONDER = "wonder"
    MYSTERY = "mystery"
    TENSION = "tension"
    REVELATION = "revelation"
    CONTEMPLATION = "contemplation"
    URGENCY = "urgency"


class CameraMovement(str, Enum):
    STATIC = "static"
    SLOW_PAN = "slow_pan"
    SLOW_ZOOM_IN = "slow_zoom_in"
    SLOW_ZOOM_OUT = "slow_zoom_out"
    TRUCK = "truck"
    DOLLY = "dolly"
    TILT = "tilt"
    HANDHELD = "handheld"


class ShotTransition(str, Enum):
    CUT = "cut"
    CROSS_DISSOLVE = "cross_dissolve"
    FADE = "fade"
    DIP_TO_BLACK = "dip_to_black"
    ZOOM = "zoom"


@dataclass
class StoryboardShot:
    """A single shot in the storyboard.

    Enhanced fields:
      - asset_source: Provider/source name (stock, nasa, manim, wikimedia, etc.)
      - asset_type: Type of asset (stock_video, manim, nasa, chart, etc.)
      - fallback_plan: What to try if primary source fails
      - provider_hints: Preferred providers in priority order
    """

    index: int = 0
    purpose: ShotPurpose = ShotPurpose.ILLUSTRATE
    emotion: ShotEmotion = ShotEmotion.NEUTRAL
    camera: CameraMovement = CameraMovement.STATIC
    duration: float = 5.0
    movement: str = "static"
    asset_source: str = "stock"
    asset_type: str = "stock_video"
    fallback_plan: str = "stock"
    provider_hints: list[str] = field(default_factory=lambda: ["pexels", "pixabay"])
    transition: ShotTransition = ShotTransition.CROSS_DISSOLVE
    overlay: str = "none"
    animation: bool = False
    search_query: str = ""
    narration_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "purpose": self.purpose.value,
            "emotion": self.emotion.value,
            "camera": self.camera.value,
            "duration": self.duration,
            "movement": self.movement,
            "asset_source": self.asset_source,
            "asset_type": self.asset_type,
            "transition": self.transition.value,
            "overlay": self.overlay,
            "animation": self.animation,
            "search_query": self.search_query[:80],
        }


@dataclass
class StoryboardScene:
    """Storyboard for a single scene containing multiple shots."""

    scene_id: int = 0
    title: str = ""
    shots: list[StoryboardShot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "title": self.title,
            "shots": [s.to_dict() for s in self.shots],
        }


# ═══════════════════════════════════════════════════════════════════════════
# Storyboard Planner
# ═══════════════════════════════════════════════════════════════════════════

STORYBOARD_PROMPT = """You are a documentary storyboard director. Given a narration, scene title, and shot list, produce a detailed storyboard plan.

For each shot, specify:
- purpose (establish, explain, illustrate, transition, emphasize, contrast, reveal, summarize)
- emotion (neutral, wonder, mystery, tension, revelation, contemplation, urgency)
- camera (static, slow_pan, slow_zoom_in, slow_zoom_out, truck, dolly, tilt, handheld)
- duration (seconds)
- movement description
- asset_source (stock, animation, nasa, generated)
- transition (cut, cross_dissolve, fade, dip_to_black, zoom)
- overlay (none, text_overlay, subtitle)
- animation (true/false)
- search_query (what to search for in stock footage — visible objects ONLY)

Return JSON array of shot objects.
"""


class StoryboardPlanner:
    """Generate storyboard plans before any asset retrieval.

    Enhanced with VisualIntent + KnowledgeEntry support for editorial
    intelligence.  Each shot now carries asset_type, fallback_plan,
    and provider hints in addition to the existing fields.

    All search queries are generated AFTER the storyboard is complete,
    not before (search generation happens in ``build_search_queries()``).

    Usage::

        planner = StoryboardPlanner()
        scene = planner.plan_scene(
            scene_id=0,
            title="The Question",
            narration="In 1950, Fermi asked...",
            visual_intent=intent,          # from EditorialPlanner
            knowledge_entry=entry,         # from Knowledge Library
            num_shots=4,
        )
        # Generate all searches after storyboard is complete
        planner.build_search_queries(scene)
        for shot in scene.shots:
            result = router.search(shot.search_query)
    """

    def __init__(self, provider: Optional[LLMProvider] = None):
        factory = ProviderFactory()
        self._provider = provider or factory.get_llm_provider_for_role("planner")

    def plan_scene(
        self,
        scene_id: int,
        title: str,
        narration: str,
        visual_intent: Optional[VisualIntent] = None,
        knowledge_entry: Optional[KnowledgeEntry] = None,
        num_shots: int = 4,
    ) -> StoryboardScene:
        """Plan a full scene storyboard from narration + title.

        Args:
            scene_id: Scene index.
            title: Scene title.
            narration: Narration text.
            num_shots: Target number of shots.

        Returns:
            StoryboardScene with planned shots.
        """
        scene = StoryboardScene(scene_id=scene_id, title=title)

        # Include VisualIntent and KnowledgeEntry context in prompt
        intent_context = ""
        if visual_intent is not None:
            intent_context = (
                f"VisualIntent:\n"
                f"  - Concept: {visual_intent.scientific_concept}\n"
                f"  - Asset type: {visual_intent.asset_type.value}\n"
                f"  - Animation candidate: {visual_intent.animation_candidate}\n"
                f"  - Must have: {', '.join(visual_intent.must_have_objects)}\n"
                f"  - Must NOT have: {', '.join(visual_intent.must_not_have_objects)}\n"
                f"  - Camera style: {visual_intent.preferred_camera_style.value}\n"
                f"  - Preferred providers: {', '.join(visual_intent.preferred_providers)}\n"
            )

        lib_context = ""
        if knowledge_entry is not None:
            lib_context = (
                f"Knowledge Library entry for '{knowledge_entry.concept}':\n"
                f"  - Motifs: {', '.join(knowledge_entry.preferred_visual_motifs[:4])}\n"
                f"  - Animal strategy: {knowledge_entry.preferred_animation_strategy}\n"
                f"  - Avoid: {', '.join(knowledge_entry.keywords_to_avoid[:4])}\n"
                f"  - Fallback: {knowledge_entry.recommended_fallback_sequence[:3]}\n"
            )

        try:
            prompt = (
                f"Scene: {title}\n"
                f"Narration: {narration}\n"
                f"Target shots: {num_shots}\n\n"
                f"{intent_context}"
                f"{lib_context}"
                "Storyboard:"
            )
            full_prompt = f"{STORYBOARD_PROMPT}\n\n{prompt}"
            raw = self._provider.generate_text(full_prompt)
            shots = self._parse_shots(raw, num_shots)
            if shots:
                scene.shots = shots
                return scene
        except Exception as e:
            print(f"[StoryboardPlanner] LLM failed: {e}")

        # Fallback: generate simple shot plan
        remaining = narration
        words = remaining.split()
        chunk_size = max(1, len(words) // max(num_shots, 1))
        for i in range(num_shots):
            chunk = " ".join(words[i * chunk_size:(i + 1) * chunk_size])
            scene.shots.append(StoryboardShot(
                index=i,
                purpose=ShotPurpose.ILLUSTRATE,
                emotion=ShotEmotion.NEUTRAL,
                duration=5.0,
                search_query=chunk[:60] if chunk else "science documentary footage",
                narration_text=chunk[:80],
            ))
        return scene

    def plan_shots(
        self,
        shot_descriptions: list[dict[str, Any]],
    ) -> list[StoryboardShot]:
        """Plan shots from pre-existing descriptions."""
        shots = []
        for i, desc in enumerate(shot_descriptions):
            shots.append(StoryboardShot(
                index=i,
                purpose=ShotPurpose(desc.get("purpose", "illustrate")),
                emotion=ShotEmotion(desc.get("emotion", "neutral")),
                camera=CameraMovement(desc.get("camera", "static")),
                duration=desc.get("duration", 5.0),
                search_query=desc.get("search_query", ""),
                narration_text=desc.get("narration", ""),
            ))
        return shots

    @staticmethod
    def _parse_shots(raw: str, expected: int) -> list[StoryboardShot]:
        """Parse LLM JSON response into StoryboardShot list."""
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

        if not isinstance(data, list):
            return []

        shots = []
        for i, item in enumerate(data[:expected]):
            if not isinstance(item, dict):
                continue
            shot = StoryboardShot(
                index=i,
                purpose=ShotPurpose(item.get("purpose", "illustrate")) if item.get("purpose") else ShotPurpose.ILLUSTRATE,
                emotion=ShotEmotion(item.get("emotion", "neutral")) if item.get("emotion") else ShotEmotion.NEUTRAL,
                camera=CameraMovement(item.get("camera", "static")) if item.get("camera") else CameraMovement.STATIC,
                duration=float(item.get("duration", 5.0)),
                movement=str(item.get("movement", "static")),
                asset_source=str(item.get("asset_source", "stock")),
                transition=ShotTransition(item.get("transition", "cross_dissolve")) if item.get("transition") else ShotTransition.CROSS_DISSOLVE,
                overlay=str(item.get("overlay", "none")),
                animation=bool(item.get("animation", False)),
                search_query=str(item.get("search_query", "")),
            )
            shots.append(shot)

        return shots

    # ═══════════════════════════════════════════════════════════════════
    # Phase 3 additions — editorial intelligence query generation
    # ═══════════════════════════════════════════════════════════════════

    def plan_from_editorial_intent(
        self,
        scene_id: int,
        title: str,
        narration: str,
        editorial_shot_sequence: list[Any],
        visual_intent: Optional[VisualIntent] = None,
        knowledge_entry: Optional[KnowledgeEntry] = None,
        transition_plan: Optional[list[str]] = None,
    ) -> StoryboardScene:
        """Build a storyboard from editorial plan shot intents.

        The editorial planner provides shot intents (purpose, emotion,
        asset type, search guidance).  This method converts those
        into StoryboardShot objects and generates search queries.
        """
        scene = StoryboardScene(scene_id=scene_id, title=title)

        for i, shot_data in enumerate(editorial_shot_sequence):
            asset_type = getattr(shot_data, 'asset_type', 'stock_video')
            purpose_str = getattr(shot_data, 'purpose', 'illustrate')
            emotion_str = getattr(shot_data, 'emotion', 'neutral')

            asset_source_map = {
                "stock_video": "stock",
                "nasa": "nasa",
                "pexels": "stock",
                "pixabay": "stock",
                "manim": "animation",
                "wikimedia": "wikimedia",
                "chart": "animation",
                "timeline": "animation",
                "map": "stock",
                "photo": "stock",
                "archive": "wikimedia",
            }
            asset_source = asset_source_map.get(asset_type, "stock")

            try:
                purpose_enum = ShotPurpose(purpose_str)
            except ValueError:
                purpose_enum = ShotPurpose.ILLUSTRATE

            try:
                emotion_enum = ShotEmotion(emotion_str)
            except ValueError:
                emotion_enum = ShotEmotion.NEUTRAL

            shot = StoryboardShot(
                index=i,
                purpose=purpose_enum,
                emotion=emotion_enum,
                duration=float(getattr(shot_data, 'duration_seconds', 5.0)),
                asset_source=asset_source,
                asset_type=asset_type,
                fallback_plan=getattr(shot_data, 'fallback_plan', 'stock'),
                provider_hints=(
                    visual_intent.preferred_providers
                    if visual_intent is not None
                    else ["pexels", "pixabay"]
                ),
                animation=(asset_type == "manim"),
                narration_text=narration[:80],
            )
            scene.shots.append(shot)

        # Generate search queries after storyboard is complete
        self.build_search_queries(scene, knowledge_entry, visual_intent)

        return scene

    def build_search_queries(
        self,
        scene: StoryboardScene,
        knowledge_entry: Optional[KnowledgeEntry] = None,
        visual_intent: Optional[VisualIntent] = None,
    ) -> None:
        """Generate search queries for all shots AFTER the storyboard.

        This is the key Phase 3 requirement: plan the scene first, then
        build searches.  Queries draw from knowledge library entries,
        shot purpose, and asset type — not raw narration words.
        """
        for shot in scene.shots:
            query_parts = []

            # Use knowledge entry's preferred searches by asset type
            if knowledge_entry is not None:
                if shot.asset_type in ("stock_video", "pexels", "pixabay"):
                    sources = knowledge_entry.preferred_stock_footage_searches
                    if sources and shot.index < len(sources):
                        query_parts.append(sources[shot.index])
                    else:
                        motifs = knowledge_entry.preferred_visual_motifs
                        if motifs:
                            query_parts.append(motifs[shot.index % len(motifs)])
                elif shot.asset_type == "nasa":
                    sources = knowledge_entry.preferred_nasa_searches
                    if sources and shot.index < len(sources):
                        query_parts.append(sources[shot.index])
                elif shot.asset_type == "wikimedia":
                    sources = knowledge_entry.preferred_wikimedia_searches
                    if sources and shot.index < len(sources):
                        query_parts.append(sources[shot.index])

            # Fall back to purpose as modality hint
            if not query_parts:
                if shot.asset_type in ("chart", "timeline"):
                    query_parts.append(f"{shot.purpose.value} chart diagram")
                elif shot.asset_type == "manim":
                    query_parts.append(f"animation {shot.purpose.value}")
                else:
                    query_parts.append(f"{shot.purpose.value} shot")

            shot.search_query = " ".join(query_parts) if query_parts else "documentary scientific footage"
