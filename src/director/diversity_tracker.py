"""
diversity_tracker.py — Asset Diversity Score and Duplicate Detection.

Tracks accepted assets across scenes and detects repeated use of similar
content.  Prevents the pipeline from selecting the same clip (or visually
similar clips) for multiple scenes without authorisation.

Integrates with QualityGates via a new DuplicateGate that checks against
the tracker's history instead of just comparing against the last N URLs.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

from src.models.schemas import AssetPlan, DiversityRecord


# ── Word-level Jaccard similarity ─────────────────────────────────────


def _jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two strings (word-level)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _content_fingerprint(filepath: str, num_bytes: int = 4096) -> str:
    """Compute a hash of the first *num_bytes* of a file.

    Used to detect identical video files that may have different URLs
    (e.g. same content served from different CDN endpoints).

    Returns a hex digest, or an empty string if the file doesn't exist.
    """
    if not filepath or not os.path.isfile(filepath):
        return ""
    try:
        with open(filepath, "rb") as f:
            data = f.read(num_bytes)
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        return ""


# ── Config defaults ────────────────────────────────────────────────────

_DEFAULT_SIMILARITY_THRESHOLD = 0.80
_DEFAULT_HISTORY_SIZE = 20


class DiversityTracker:
    """Tracks accepted assets and enforces diversity across scenes.

    Maintains a rolling history of ``DiversityRecord`` entries and
    provides methods to check new candidates for similarity against
    recently accepted assets.

    Usage::

        tracker = DiversityTracker()
        ok, reason = tracker.check_candidate(asset_id, query, filepath)
        if ok:
            tracker.record_accepted(scene_id, provider, asset_id, query, filepath)
    """

    def __init__(
        self,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
        history_size: int = _DEFAULT_HISTORY_SIZE,
    ):
        self._threshold = similarity_threshold
        self._history_size = history_size
        self._history: list[DiversityRecord] = []

    # ── Public API ─────────────────────────────────────────────────────

    def check_candidate(
        self,
        asset: AssetPlan,
        asset_id: str = "",
        provider: str = "",
    ) -> tuple[bool, str]:
        """Check a candidate asset against the diversity history.

        Three checks, ordered from cheapest to most expensive:

        1. **Provider + asset_id match**: Exact same asset used before.
        2. **Query similarity**: Search query word-overlap > threshold.
        3. **Content fingerprint**: File hash matches a recent asset.

        Returns (accepted, reason).
        """
        if not self._history:
            return True, "no prior assets"

        # Check 1: Provider + asset_id match
        if asset_id and provider:
            for record in self._history:
                if record.asset_id == asset_id and record.provider == provider:
                    return False, (
                        f"duplicate detected: same asset {provider}/{asset_id} "
                        f"was already used in scene {record.scene_id}"
                    )

        # Check 2: Query similarity
        query_used = asset.query_used
        if query_used:
            for record in self._history[-10:]:
                sim = _jaccard_similarity(query_used, record.query_used)
                if sim >= self._threshold:
                    return False, (
                        f"query similarity {sim:.2f} with scene {record.scene_id}: "
                        f"'{query_used[:60]}' vs '{record.query_used[:60]}'"
                    )

        # Check 3: Content fingerprint (existing file only)
        if asset.filepath and os.path.isfile(asset.filepath):
            fp = _content_fingerprint(asset.filepath)
            if fp:
                for record in self._history[-10:]:
                    if record.content_hash == fp:
                        return False, (
                            f"content fingerprint match with scene {record.scene_id}"
                        )

        return True, "diversity check passed"

    def record_accepted(
        self,
        scene_id: int,
        provider: str,
        asset_id: str = "",
        query_used: str = "",
        filepath: str = "",
    ) -> None:
        """Record an accepted asset for future diversity checks."""
        fp = _content_fingerprint(filepath) if filepath else ""

        # Determine similarity group from provider + asset_id (truncated to 100)
        sim_group = (f"{provider}/{asset_id}" if provider and asset_id else provider)[:100]

        record = DiversityRecord(
            scene_id=scene_id,
            provider=provider,
            asset_id=asset_id,
            query_used=query_used,
            content_hash=fp,
            similarity_group=sim_group,
        )

        self._history.append(record)

        # Trim history
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

    def get_diversity_violations(self) -> list[str]:
        """Analyse the full history and report any long-range diversity
        issues (same asset used more than twice, same provider dominating).

        Returns a list of human-readable issue descriptions.
        """
        violations: list[str] = []

        # Group by similarity group
        groups: dict[str, list[int]] = {}
        for record in self._history:
            if record.similarity_group:
                groups.setdefault(record.similarity_group, []).append(record.scene_id)

        # Flag groups used more than once
        for group, scenes in groups.items():
            if len(scenes) > 1:
                violations.append(
                    f"Asset '{group}' used in {len(scenes)} scenes: {scenes}"
                )

        # Flag single-provider dominance
        provider_counts: dict[str, int] = {}
        for record in self._history:
            if record.provider:
                provider_counts[record.provider] = provider_counts.get(record.provider, 0) + 1

        total = sum(provider_counts.values())
        for prov, count in provider_counts.items():
            if total > 0 and count / total > 0.5 and count >= 3:
                violations.append(
                    f"Provider '{prov}' dominates: {count}/{total} assets ({100*count//total}%)"
                )

        return violations

    @property
    def history(self) -> list[DiversityRecord]:
        """Read-only view of the diversity history."""
        return list(self._history)

    def reset(self) -> None:
        """Clear all diversity tracking (for a new video)."""
        self._history.clear()
