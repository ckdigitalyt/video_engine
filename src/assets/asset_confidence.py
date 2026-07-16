"""
asset_confidence.py — Composite confidence scoring for candidate assets.

Every candidate asset receives a multi-dimensional confidence score.
Only assets above a configurable threshold enter the render queue.

Scoring dimensions:
  - semantic_relevance    (25%) — how well the asset matches narration
  - documentary_suitability (15%) — fits documentary aesthetic
  - motion_quality        (10%) — camera motion quality
  - visual_quality        (10%) — resolution, framing
  - duplicate_penalty     (-10%) — penalty for repeated content
  - text_logo_penalty     (-10%) — penalty for text/watermarks/logos
  - provider_confidence    (5%) — historical reliability of provider
  - llm_critic_score      (10%) — LLM evaluation of visual-narration match
  - knowledge_library_consistency (15%) — matches what the Knowledge Library expects
"""

from __future__ import annotations

import os
from typing import Any, Optional

from src.knowledge.visual_knowledge_library import KnowledgeEntry, VisualKnowledgeLibrary
from src.assets.visual_intent import VisualIntent


# ── Default weights ─────────────────────────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic_relevance": 0.25,
    "documentary_suitability": 0.15,
    "motion_quality": 0.10,
    "visual_quality": 0.10,
    "duplicate_penalty": -0.10,
    "text_logo_penalty": -0.10,
    "provider_confidence": 0.05,
    "llm_critic_score": 0.10,
    "knowledge_library_consistency": 0.15,
}

DEFAULT_THRESHOLD = 0.60


class ConfidenceResult:
    """Result of a confidence evaluation."""

    def __init__(
        self,
        scores: dict[str, float],
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self.scores = dict(scores)
        self.threshold = threshold

    @property
    def composite(self) -> float:
        total = 0.0
        for dim, score in self.scores.items():
            weight = DEFAULT_WEIGHTS.get(dim, 0.0)
            total += score * weight
        return max(0.0, min(1.0, total))

    @property
    def passed(self) -> bool:
        return self.composite >= self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite": round(self.composite, 4),
            "threshold": self.threshold,
            "passed": self.passed,
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
        }


class AssetConfidenceEngine:
    """Computes composite confidence scores for candidate assets.

    Usage::

        engine = AssetConfidenceEngine()
        result = engine.evaluate(
            asset=provider_result,
            narration="In 1950, Fermi asked...",
            knowledge_entry=knowledge_lib.lookup("Fermi Paradox"),
            visual_intent=intent,
        )
        if result.passed:
            timeline.add_asset(asset)
    """

    def __init__(
        self,
        knowledge_library: Optional[VisualKnowledgeLibrary] = None,
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self._knowledge_library = knowledge_library or VisualKnowledgeLibrary()
        self._threshold = threshold
        # Track asset URLs to detect duplicates across calls
        self._seen_urls: set[str] = set()

    def evaluate(
        self,
        asset: dict[str, Any],
        narration: str = "",
        knowledge_entry: Optional[KnowledgeEntry] = None,
        visual_intent: Optional[VisualIntent] = None,
    ) -> ConfidenceResult:
        """Compute composite confidence score for a single asset.

        Args:
            asset: Provider result dict (must have "url" key, optionally
                   "duration", "width", "height", "score", "provider").
            narration: Scene narration text for semantic comparison.
            knowledge_entry: KnowledgeLibrary entry for consistency check.
            visual_intent: VisualIntent for suitability assessment.

        Returns:
            ConfidenceResult with composite, per-dimension scores, pass/fail.
        """
        scores: dict[str, float] = {}

        scores["semantic_relevance"] = self._score_semantic_relevance(asset, narration)
        scores["documentary_suitability"] = self._score_documentary_suitability(asset, visual_intent)
        scores["motion_quality"] = self._score_motion_quality(asset)
        scores["visual_quality"] = self._score_visual_quality(asset)
        scores["duplicate_penalty"] = self._score_duplicate_penalty(asset)
        scores["text_logo_penalty"] = self._score_text_logo_penalty(asset)
        scores["provider_confidence"] = self._score_provider_confidence(asset)
        scores["llm_critic_score"] = self._score_llm_critic(asset, narration)
        scores["knowledge_library_consistency"] = self._score_knowledge_consistency(
            asset, knowledge_entry
        )

        result = ConfidenceResult(scores, self._threshold)

        # Track seen URLs
        url = asset.get("url", "")
        if url:
            self._seen_urls.add(url)

        return result

    def batch_evaluate(
        self,
        assets: list[dict[str, Any]],
        narration: str = "",
        knowledge_entry: Optional[KnowledgeEntry] = None,
        visual_intent: Optional[VisualIntent] = None,
    ) -> list[ConfidenceResult]:
        """Evaluate multiple assets and return results, sorted by composite."""
        results = [
            self.evaluate(a, narration, knowledge_entry, visual_intent)
            for a in assets
        ]
        results.sort(key=lambda r: r.composite, reverse=True)
        return results

    def reset(self) -> None:
        """Clear seen-URL tracking for a new video."""
        self._seen_urls.clear()

    # ── Scoring dimensions ────────────────────────────────────────────

    @staticmethod
    def _score_semantic_relevance(asset: dict, narration: str) -> float:
        """Score how well the asset matches the narration.

        Uses the provider's native score if available; otherwise falls
        back to a heuristic based on query overlap with narration.
        """
        native = asset.get("score", None)
        if native is not None:
            return min(float(native), 1.0)

        # Heuristic: check if search_query keywords appear in narration
        query = (asset.get("search_query", "") or "").lower()
        nar = narration.lower()
        if not query or not nar:
            return 0.5

        words = set(query.split())
        matches = sum(1 for w in words if len(w) > 3 and w in nar)
        score = matches / max(len(words), 1) * 0.8 + 0.2
        return min(score, 1.0)

    @staticmethod
    def _score_documentary_suitability(asset: dict, visual_intent: Optional[VisualIntent]) -> float:
        """Score how well the asset fits a documentary aesthetic.

        Favors: high resolution, natural lighting, landscape orientation.
        """
        w = asset.get("width", 0) or 0
        h = asset.get("height", 0) or 0

        score = 0.7  # baseline

        # Landscape orientation is preferred for documentary
        if w > h and w > 0 and h > 0:
            score += 0.15
        elif h > w:
            score -= 0.2  # portrait is unusual for documentary

        # HD or higher
        if w >= 1920 and h >= 1080:
            score += 0.1
        elif w >= 1280 and h >= 720:
            score += 0.05

        # Provider hint
        provider = asset.get("provider", "")
        if provider in ("nasa", "wikimedia"):
            score += 0.05
        elif provider == "pixabay":
            score -= 0.05  # lower quality typical

        # Apply must_not_have penalty if visual_intent provided
        if visual_intent and visual_intent.must_not_have_objects:
            desc = (asset.get("description", "") or "").lower()
            must_not = set(str(o).lower() for o in visual_intent.must_not_have_objects)
            if any(kw in desc for kw in must_not):
                score -= 0.3

        return max(0.0, min(1.0, score))

    @staticmethod
    def _score_motion_quality(asset: dict) -> float:
        """Score the motion quality of the asset.

        Higher for steady, cinematic footage; lower for fast, shaky camera.
        """
        provider = asset.get("provider", "")
        if provider == "manim":
            return 0.9  # clean rendered animations
        if provider == "chart":
            return 0.85  # static charts

        duration = asset.get("duration", 0) or 0
        if duration >= 5:
            return 0.7  # long clips tend to be slower, more cinematic
        elif duration >= 3:
            return 0.6
        else:
            return 0.5

    @staticmethod
    def _score_visual_quality(asset: dict) -> float:
        """Score visual quality based on resolution, duration, format."""
        w = asset.get("width", 0) or 0
        h = asset.get("height", 0) or 0
        dur = asset.get("duration", 0) or 0

        score = 0.5

        # Resolution
        pixels = w * h
        if pixels >= 1920 * 1080:
            score += 0.3
        elif pixels >= 1280 * 720:
            score += 0.15

        # Duration — very short clips are lower quality
        if dur >= 5:
            score += 0.1
        elif dur >= 2:
            score += 0.05
        else:
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _score_duplicate_penalty(self, asset: dict) -> float:
        """Penalty for assets already seen.

        Returns 0.0 for new assets, -1.0 for exact duplicates.
        """
        url = asset.get("url", "")
        if not url:
            return 0.0
        if url in self._seen_urls:
            return -1.0
        return 0.0

    @staticmethod
    def _score_text_logo_penalty(asset: dict) -> float:
        """Penalty for assets likely to have text/watermarks/logos.

        Currently heuristic-based; in production this would use a vision
        model to detect text overlays in the first frame.
        """
        provider = asset.get("provider", "")
        description = (asset.get("description", "") or "").lower()

        penalty = 0.0

        # Known watermark words
        watermark_words = ["getty", "shutterstock", "pixabay", "watermark",
                           "stock footage", "royalty-free", "istock",
                           "adobe stock", "pond5"]
        if any(w in description for w in watermark_words):
            penalty = -0.5

        # Wikimedia often has labeled diagrams (not a penalty — valuable)
        if provider == "wikimedia" and "diagram" in description:
            penalty = 0.0  # diagrams are useful, not watermarked

        return penalty

    @staticmethod
    def _score_provider_confidence(asset: dict) -> float:
        """Score based on historical reliability of the provider."""
        provider = asset.get("provider", "")
        confidence_map = {
            "pexels": 0.9,
            "nasa": 0.85,
            "manim": 1.0,
            "chart": 0.95,
            "wikimedia": 0.7,
            "pixabay": 0.6,
            "emergency": 0.2,
        }
        return confidence_map.get(provider, 0.5)

    @staticmethod
    def _score_llm_critic(asset: dict, narration: str) -> float:
        """Score from the LLM visual critic.

        If the asset already has a critic score, use it.
        Otherwise default to neutral (0.5) — the critic runs explicitly
        for border cases, not for every asset.
        """
        critic = asset.get("critic_score", None)
        if critic is not None:
            return min(float(critic) / 100.0 if critic > 1 else float(critic), 1.0)
        return 0.5

    def _score_knowledge_consistency(
        self,
        asset: dict,
        knowledge_entry: Optional[KnowledgeEntry],
    ) -> float:
        """Score how consistent the asset is with Knowledge Library guidance.

        Checks:
        - Asset type matches what the entry recommends
        - Provider is in the entry's preferred list
        - Doesn't contain keywords_to_avoid
        """
        if knowledge_entry is None:
            return 0.5  # neutral when no entry exists

        score = 0.5

        asset_type = asset.get("asset_type", "stock_video")
        provider = asset.get("provider", "")
        query = (asset.get("search_query", "") or "").lower()
        description = (asset.get("description", "") or "").lower()
        combined = query + " " + description

        # Check preferred animation strategy
        if asset_type == "manim" and knowledge_entry.preferred_animation_strategy == "manim":
            score += 0.3
        elif asset_type == "chart" and lens(knowledge_entry.diagrams_charts_timelines):
            score += 0.2

        # Check provider alignment
        all_searches = (
            knowledge_entry.preferred_stock_footage_searches
            + knowledge_entry.preferred_nasa_searches
            + knowledge_entry.preferred_wikimedia_searches
        )
        if all_searches and provider in ("pexels", "pixabay", "nasa", "wikimedia"):
            score += 0.1

        # Penalty for keywords to avoid
        if knowledge_entry.keywords_to_avoid:
            for kw in knowledge_entry.keywords_to_avoid:
                if kw.lower() in combined:
                    score -= 0.2
                    break

        return max(0.0, min(1.0, score))


def lens(lst: list) -> int:
    """Safe len() that handles None."""
    return len(lst) if lst else 0
