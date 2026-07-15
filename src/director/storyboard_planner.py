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
    """A single shot in the storyboard."""

    index: int = 0
    purpose: ShotPurpose = ShotPurpose.ILLUSTRATE
    emotion: ShotEmotion = ShotEmotion.NEUTRAL
    camera: CameraMovement = CameraMovement.STATIC
    duration: float = 5.0
    movement: str = "static"
    asset_source: str = "stock"
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

    Usage::

        planner = StoryboardPlanner()
        scene = planner.plan_scene(
            scene_id=0,
            title="The Question",
            narration="In 1950, Fermi asked...",
            num_shots=4,
        )
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

        try:
            prompt = (
                f"Scene: {title}\n"
                f"Narration: {narration}\n"
                f"Target shots: {num_shots}\n\n"
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
