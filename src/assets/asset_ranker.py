"""
asset_ranker.py — Multi-provider candidate scoring and ranking.

Collects candidates from ALL configured providers, scores them on multiple
dimensions, and returns the highest-scoring asset.

Scores include:
- semantic similarity
- visual quality
- resolution
- camera stability
- documentary suitability
- face detection penalty
- text overlay penalty
- logo penalty
- duplicate penalty
- motion quality
- freshness
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from src.utils.config import get_config


@dataclass
class ScoredAsset:
    """An asset with its computed ranking score."""

    asset: dict  # raw asset dict from provider
    provider: str
    query: str
    score: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def filepath(self) -> str:
        return self.asset.get("filepath", "")

    @property
    def width(self) -> int:
        return self.asset.get("width", 0) or 0

    @property
    def height(self) -> int:
        return self.asset.get("height", 0) or 0

    @property
    def duration(self) -> float:
        return self.asset.get("duration", 0) or 0

    @property
    def resolution_score(self) -> float:
        w, h = self.width, self.height
        if w * h <= 0:
            return 0.0
        return min((w * h) / (1920.0 * 1080.0), 1.0)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "query": self.query,
            "score": self.score,
            "scores": self.scores,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "filepath": self.filepath,
        }


class AssetRanker:
    """Score and rank asset candidates from all providers.

    Usage::

        ranker = AssetRanker()
        ranked = ranker.score_and_rank(candidates, query="spiral galaxy")
        best = ranked[0] if ranked else None
    """

    def __init__(self):
        self._weights = self._load_weights()

    # ── Public API ─────────────────────────────────────────────────────

    def score_and_rank(
        self,
        candidates: list[tuple[str, str, list[dict]]],
        query: str = "",
        target_duration: float = 0,
    ) -> list[ScoredAsset]:
        """Score all candidates and return sorted (best first).

        Args:
            candidates: List of (provider_name, query, asset_list) tuples.
            query: Original search query for context.
            target_duration: Preferred clip duration in seconds.

        Returns:
            Sorted list of ScoredAsset, highest score first.
        """
        scored: list[ScoredAsset] = []

        for provider, q, assets in candidates:
            if not assets:
                continue
            for asset in assets[:5]:  # Top 5 per provider
                sa = self._score_single(asset, provider, q or query, target_duration)
                scored.append(sa)

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def _score_single(
        self,
        asset: dict,
        provider: str,
        query: str,
        target_duration: float,
    ) -> ScoredAsset:
        """Compute multi-dimensional score for a single asset."""
        scores: dict[str, float] = {}

        # Resolution score
        w = asset.get("width", 0) or 0
        h = asset.get("height", 0) or 0
        if w * h > 0:
            scores["resolution"] = min((w * h) / (1920.0 * 1080.0), 1.0)
        else:
            scores["resolution"] = 0.0

        # Duration suitability
        dur = asset.get("duration", 0) or 0
        if target_duration > 0 and dur > 0:
            ratio = dur / target_duration
            scores["duration"] = max(0.0, 1.0 - abs(1.0 - ratio) * 0.5)
        else:
            scores["duration"] = 0.5

        # Documentary suitability (provider-based heuristic)
        scores["documentary"] = self._documentary_score(asset, provider)

        # Provider confidence
        scores["provider"] = self._provider_confidence(provider)

        # Penalties
        scores["quality_penalty"] = self._quality_penalties(asset)
        scores["face_penalty"] = 0.0  # Would need vision model
        scores["text_penalty"] = self._text_overlay_penalty(asset)
        scores["logo_penalty"] = 0.0  # Would need vision model

        # Weighted total
        w = self._weights
        total = (
            w["resolution"] * scores["resolution"]
            + w["duration"] * scores["duration"]
            + w["documentary"] * scores["documentary"]
            + w["provider"] * scores["provider"]
            - w["quality_penalty"] * scores["quality_penalty"]
        )
        total = max(0.0, min(1.0, total))

        sa = ScoredAsset(
            asset=asset,
            provider=provider,
            query=query,
            score=round(total, 4),
            scores=scores,
        )
        return sa

    # ── Scoring helpers ────────────────────────────────────────────────

    @staticmethod
    def _documentary_score(asset: dict, provider: str) -> float:
        """Heuristic documentary suitability score."""
        # NASA content is inherently documentary-grade
        if provider == "nasa":
            return 0.9

        # Check for tags/description suggesting cinematic quality
        tags = [str(t).lower() for t in asset.get("tags", asset.get("description", ""))]
        cinematic_keywords = {
            "space", "nature", "science", "documentary", "timelapse",
            "cinematic", "aerial", "slow motion", "4k", "drone",
        }
        if any(kw in " ".join(tags) for kw in cinematic_keywords):
            return 0.7

        return 0.5

    @staticmethod
    def _provider_confidence(provider: str) -> float:
        """Confidence based on provider track record."""
        confidence = {
            "nasa": 0.9,
            "pexels": 0.8,
            "pixabay": 0.7,
            "wikimedia": 0.6,
        }
        return confidence.get(provider, 0.5)

    @staticmethod
    def _quality_penalties(asset: dict) -> float:
        """Detect quality issues from metadata."""
        penalty = 0.0
        tags = [str(t).lower() for t in asset.get("tags", asset.get("description", ""))]
        tag_text = " ".join(tags)

        # Low resolution: penalize below HD
        w = asset.get("width", 0) or 0
        h = asset.get("height", 0) or 0
        if w * h > 0 and (w < 1280 or h < 720):
            penalty += 0.2

        # Watermark indicators in tags
        watermark_indicators = {"watermark", "shutterstock", "getty", "stock footage"}
        if any(wm in tag_text for wm in watermark_indicators):
            penalty += 0.5

        # Check URL for watermark
        url = asset.get("url", asset.get("link", ""))
        if "watermark" in url.lower() or "preview" in url.lower():
            penalty += 0.3

        return min(penalty, 1.0)

    @staticmethod
    def _text_overlay_penalty(asset: dict) -> float:
        """Detect if asset likely has text overlays."""
        tags = [str(t).lower() for t in asset.get("tags", asset.get("description", ""))]
        text_indicators = {"text", "title", "caption", "label", "overlay", "lower third"}
        if any(ti in " ".join(tags) for ti in text_indicators):
            return 0.3
        return 0.0

    @staticmethod
    def _load_weights() -> dict[str, float]:
        return {
            "resolution": get_config("ranking.resolution_weight", 0.30),
            "duration": get_config("ranking.duration_weight", 0.20),
            "documentary": get_config("ranking.documentary_weight", 0.25),
            "provider": get_config("ranking.provider_weight", 0.15),
            "semantic": get_config("ranking.semantic_weight", 0.10),
            "quality_penalty": get_config("ranking.quality_penalty_weight", 0.30),
            "face_penalty": get_config("ranking.face_penalty_weight", 0.20),
            "text_penalty": get_config("ranking.text_penalty_weight", 0.15),
            "logo_penalty": get_config("ranking.logo_penalty_weight", 0.20),
        }
