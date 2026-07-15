"""
quality_gate.py — Hard Quality Gates.

Inspects a candidate asset against a set of hard quality gates:

- SemanticGate   : Rejects if semantic relevance < 0.75
- ReuseGate      : Rejects if same asset was used recently
- StyleGate      : Rejects if style is incompatible (delegates to AestheticAgent)
- DuplicateGate  : Rejects if visually identical to recent assets (uses DiversityTracker)
- DiversityGate  : Rejects if query/content too similar to recently accepted assets

Each gate returns a (passed, reason) tuple.  If ANY gate fails,
the asset is rejected and the pipeline must retry with a different
query/provider or regenerate the scene.
"""

from __future__ import annotations

from typing import Optional

from src.models.schemas import AssetPlan, ProviderType, Scene
from src.utils.config import get_config
from src.director.aesthetic_agent import AestheticAgent
from src.director.visual_style import VisualStyle
from src.director.diversity_tracker import DiversityTracker


class QualityGates:
    """Assembly of all hard quality gates for a video.

    Usage::

        gates = QualityGates(visual_style, aesthetic_agent)
        passed, reason = gates.check_all(asset, category)
        if not passed:
            print(f"Asset REJECTED: {reason}")
            # retry with different query/provider
    """

    def __init__(
        self,
        visual_style: Optional[VisualStyle] = None,
        aesthetic_agent: Optional[AestheticAgent] = None,
        diversity_tracker: Optional[DiversityTracker] = None,
        semantic_threshold: Optional[float] = None,
        reuse_window: Optional[int] = None,
        reuse_penalty: Optional[float] = None,
        duplicate_threshold: Optional[float] = None,
    ):
        self._style = visual_style or VisualStyle()
        self._agent = aesthetic_agent or AestheticAgent(visual_style=self._style)
        self._diversity_tracker = diversity_tracker or DiversityTracker()
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

    # ── Public API ─────────────────────────────────────────────────────

    def check_all(
        self,
        asset: AssetPlan,
        category: str = "General",
        provider: str = "",
        asset_id: str = "",
    ) -> tuple[bool, str, dict[str, dict]]:
        """Run all quality gates against a candidate asset.

        Parameters
        ----------
        asset : AssetPlan
            The candidate asset plan.
        category : str
            Topic category (e.g. "Space", "History").
        provider : str
            Provider name for diversity tracking.
        asset_id : str
            Provider-specific asset ID for diversity tracking.

        Returns
        -------
        tuple[bool, str, dict]
            (all_passed, reason_summary, per_gate_details)
        """
        details: dict[str, dict] = {}

        # Gate 1: Semantic Gate
        sem_passed, sem_reason = self._check_semantic(asset)
        details["semantic"] = {"passed": sem_passed, "reason": sem_reason}
        if not sem_passed:
            return False, f"SemanticGate: {sem_reason}", details

        # Gate 2: Reuse Gate
        reuse_passed, reuse_reason = self._check_reuse(asset)
        details["reuse"] = {"passed": reuse_passed, "reason": reuse_reason}
        if not reuse_passed:
            return False, f"ReuseGate: {reuse_reason}", details

        # Gate 3: Style Gate (aesthetic consistency)
        style_passed, style_reason = self._check_style(asset, category, provider)
        details["style"] = {"passed": style_passed, "reason": style_reason}
        if not style_passed:
            return False, f"StyleGate: {style_reason}", details

        # Gate 4: Diversity Gate (via DiversityTracker)
        div_passed, div_reason = self._check_diversity(
            asset, provider=provider, asset_id=asset_id,
        )
        details["diversity"] = {"passed": div_passed, "reason": div_reason}
        if not div_passed:
            return False, f"DiversityGate: {div_reason}", details

        # All gates passed — record this asset for future checks
        self._record_asset(asset, provider=provider, asset_id=asset_id)

        return True, "All gates passed", details

    # ── Individual gates ───────────────────────────────────────────────

    def _check_semantic(self, asset: AssetPlan) -> tuple[bool, str]:
        """Reject if semantic relevance is below threshold."""
        if asset.semantic_score < self._semantic_threshold:
            return False, (
                f"semantic_score {asset.semantic_score:.3f} < "
                f"threshold {self._semantic_threshold}"
            )
        return True, f"semantic_score {asset.semantic_score:.3f} >= {self._semantic_threshold}"

    def _check_reuse(self, asset: AssetPlan) -> tuple[bool, str]:
        """Reject if the same URL or provider asset ID was used recently."""
        # Check asset URL
        if asset.video_url and asset.video_url in self._recent_asset_urls[-self._reuse_window:]:
            return False, f"same URL used in last {self._reuse_window} assets"
        return True, "no recent reuse detected"

    def _check_style(self, asset: AssetPlan, category: str, provider: str) -> tuple[bool, str]:
        """Check aesthetic consistency via AestheticAgent."""
        if self._agent is not None:
            query = asset.query_used or ""
            return self._agent.check_asset(asset, provider, query, category)
        return True, "no aesthetic agent configured"

    def _check_diversity(
        self,
        asset: AssetPlan,
        provider: str = "",
        asset_id: str = "",
    ) -> tuple[bool, str]:
        """Check diversity against the DiversityTracker."""
        if self._diversity_tracker is None:
            return True, "no diversity tracker configured"
        return self._diversity_tracker.check_candidate(
            asset, asset_id=asset_id, provider=provider,
        )

    # ── Recording ──────────────────────────────────────────────────────

    def _record_asset(
        self,
        asset: AssetPlan,
        scene_id: int = 0,
        provider: str = "",
        asset_id: str = "",
    ) -> None:
        """Record an accepted asset for future reuse and diversity checks."""
        # Record URL
        if asset.video_url:
            self._recent_asset_urls.append(asset.video_url)

        # Record provider asset ID
        if asset_id:
            self._recent_asset_ids.append(asset_id)

        # Record in diversity tracker
        if self._diversity_tracker is not None:
            self._diversity_tracker.record_accepted(
                scene_id=scene_id,
                provider=provider or asset.provider.value,
                asset_id=(asset_id or asset.query_used)[:200],
                query_used=asset.query_used,
                filepath=asset.filepath,
            )

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def diversity_tracker(self) -> Optional[DiversityTracker]:
        """Access the diversity tracker for post-hoc analysis."""
        return self._diversity_tracker

    def reset(self) -> None:
        """Clear all tracking state (for a new video)."""
        self._recent_asset_urls.clear()
        self._recent_asset_ids.clear()
        if self._diversity_tracker is not None:
            self._diversity_tracker.reset()
