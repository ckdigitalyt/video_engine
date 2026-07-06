"""
quality_gate.py — Hard Quality Gates.

Inspects a candidate asset against a set of hard quality gates:

- SemanticGate   : Rejects if semantic relevance < 0.75
- ReuseGate      : Rejects if same asset was used recently
- StyleGate      : Rejects if style is incompatible (delegates to AestheticAgent)
- DuplicateGate  : Rejects if visually identical to recent assets

Each gate returns a (passed, reason) tuple.  If ANY gate fails,
the asset is rejected and the pipeline must retry with a different
query/provider or regenerate the scene.
"""

from __future__ import annotations

from typing import Optional

from src.utils.config import get_config
from src.director.aesthetic_agent import AestheticAgent
from src.director.visual_style import VisualStyle


class QualityGates:
    """Assembly of all hard quality gates for a video.

    Usage::

        gates = QualityGates(visual_style, aesthetic_agent)
        passed, reason = gates.check_all(asset, provider, query, category, semantic_score)
        if not passed:
            print(f"Asset REJECTED: {reason}")
            # retry with different query/provider
    """

    def __init__(
        self,
        visual_style: Optional[VisualStyle] = None,
        aesthetic_agent: Optional[AestheticAgent] = None,
        semantic_threshold: Optional[float] = None,
        reuse_window: Optional[int] = None,
        reuse_penalty: Optional[float] = None,
        duplicate_threshold: Optional[float] = None,
    ):
        self._style = visual_style or VisualStyle()
        self._agent = aesthetic_agent or AestheticAgent(visual_style=self._style)
        self._semantic_threshold = semantic_threshold or get_config(
            "visual_director.quality_gates.semantic_threshold", 0.75
        )
        self._reuse_window = reuse_window or get_config(
            "visual_director.quality_gates.reuse_window", 5
        )
        self._reuse_penalty = reuse_penalty or get_config(
            "visual_director.quality_gates.reuse_penalty", 0.3
        )
        self._duplicate_threshold = duplicate_threshold or get_config(
            "visual_director.quality_gates.duplicate_threshold", 0.85
        )
        self._recent_asset_urls: list[str] = []
        self._recent_asset_ids: list[str] = []

    # ── Combined check ─────────────────────────────────────────────────

    def check_all(
        self,
        asset: dict,
        provider: str,
        query: str,
        category: str,
        semantic_score: float,
    ) -> tuple[bool, str, dict]:
        """Run ALL quality gates on *asset*.

        Returns
        -------
        (passed: bool, reason: str, details: dict)
            *details* contains per-gate results for transparency.
        """
        gates: list[tuple[str, callable]] = [
            ("semantic", lambda: self._check_semantic(semantic_score)),
            ("aesthetic", lambda: self._check_aesthetic(asset, provider, query, category)),
            ("reuse", lambda: self._check_reuse(asset)),
            ("duplicate", lambda: self._check_duplicate(asset)),
        ]

        details: dict[str, dict] = {}
        all_passed = True
        reason_parts: list[str] = []

        for name, gate_fn in gates:
            gate_passed, gate_reason = gate_fn()
            details[name] = {
                "passed": gate_passed,
                "reason": gate_reason,
            }
            if not gate_passed:
                all_passed = False
                reason_parts.append(f"{name}: {gate_reason}")

        if all_passed:
            # Track this asset in reuse/duplicate history
            self._track_asset(asset)
            return True, "all gates passed", details

        return False, "; ".join(reason_parts), details

    # ── Individual gates ───────────────────────────────────────────────

    def _check_semantic(self, score: float) -> tuple[bool, str]:
        """Gate 1: Semantic relevance >= threshold."""
        if score >= self._semantic_threshold:
            return True, f"semantic_score={score:.3f} >= {self._semantic_threshold}"
        return False, f"semantic_score={score:.3f} < {self._semantic_threshold}"

    def _check_aesthetic(
        self, asset: dict, provider: str, query: str, category: str
    ) -> tuple[bool, str]:
        """Gate 2: Aesthetic compatibility (delegates to AestheticAgent)."""
        return self._agent.check_asset(asset, provider, query, category)

    def _check_reuse(self, asset: dict) -> tuple[bool, str]:
        """Gate 3: No recent reuse of the same asset."""
        asset_id = str(asset.get("id", ""))
        video_files = asset.get("video_files", [])
        asset_url = video_files[0].get("link", "") if video_files else ""

        if asset_url and asset_url in self._recent_asset_urls:
            return False, f"asset URL already used (penalty={self._reuse_penalty})"
        if asset_id and asset_id in self._recent_asset_ids:
            return False, f"asset id '{asset_id}' already used"

        return True, "no reuse detected"

    def _check_duplicate(self, asset: dict) -> tuple[bool, str]:
        """Gate 4: Not visually identical to recent assets (by URL).

        Full duplicate detection would compare embeddings or color
        histograms.  Currently checks URL identity (fastest check).
        """
        video_files = asset.get("video_files", [])
        asset_url = video_files[0].get("link", "") if video_files else ""

        if asset_url and asset_url in self._recent_asset_urls[-10:]:
            return False, "duplicate asset (same URL)"
        return True, "no duplicate detected"

    # ── Tracking ───────────────────────────────────────────────────────

    def _track_asset(self, asset: dict) -> None:
        """Add asset to tracking history after acceptance."""
        asset_id = str(asset.get("id", ""))
        video_files = asset.get("video_files", [])
        asset_url = video_files[0].get("link", "") if video_files else ""

        if asset_url:
            self._recent_asset_urls.append(asset_url)
        if asset_id:
            self._recent_asset_ids.append(asset_id)

        # Trim to window
        while len(self._recent_asset_urls) > self._reuse_window:
            self._recent_asset_urls.pop(0)
        while len(self._recent_asset_ids) > self._reuse_window:
            self._recent_asset_ids.pop(0)

    def reset(self) -> None:
        """Clear tracking for a new video run."""
        self._recent_asset_urls.clear()
        self._recent_asset_ids.clear()
        self._agent.reset()
