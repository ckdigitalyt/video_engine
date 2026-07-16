"""
duplicate_detector.py — Perceptual hash-based duplicate image detection.

Prevents visual repetition in documentary videos by tracking all used
asset paths and rejecting assets that are perceptually similar to ones
already used.  Uses imagehash's phash (perceptual hash) for robust
duplicate detection that tolerates resizing, minor cropping, and
compression artefacts.

Integrates with director_integration.py via the DuplicateDetector class.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import List, Optional, Tuple

try:
    import imagehash
    from PIL import Image
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False


class DuplicateDetector:
    """Tracks used asset paths and penalises re-use during a render run.

    Uses perceptual hashing (phash) so near-duplicates (same image at
    different resolutions, minor crop variations) are detected, not just
    exact file matches.

    Usage::

        detector = DuplicateDetector()
        penalty = detector.check_and_penalise("/path/to/asset.jpg")
        if penalty < 0.5:
            # Acceptable — include asset
            detector.record_use("/path/to/asset.jpg")

    Attributes:
        max_reuses_per_video: Absolute limit on uses of the same image.
        hash_size: Size of the perceptual hash (8 = 64-bit hash).
        similarity_threshold: Hamming distance ratio below which two
            hashes are considered the same image (0.0=identical only,
            1.0=anything matches).
    """

    def __init__(
        self,
        hash_size: int = 8,
        similarity_threshold: float = 0.85,
        max_reuses_per_video: int = 2,
    ):
        if not HAS_IMAGEHASH:
            import warnings
            warnings.warn(
                "imagehash/Pillow not installed — duplicate detection "
                "will fall back to path-based matching only"
            )
        self.hash_size = hash_size
        self.threshold = similarity_threshold
        self.max_reuses_per_video = max_reuses_per_video

        # hash -> list of timestamps (or usage indices)
        self._seen_hashes: dict = defaultdict(list)
        # For path-based fallback
        self._seen_paths: set = set()

    # ── Public API ─────────────────────────────────────────────────────

    def check_and_penalise(self, asset_path: str, timestamp: float = 0.0) -> float:
        """Check an asset path and return a reuse penalty.

        Args:
            asset_path: Local file path to check.
            timestamp: Position in the video timeline (seconds).

        Returns:
            Penalty score 0.0–1.0:
              0.0        — Not seen before, safe to use.
              0.0–0.9    — Seen before; linear penalty per use.
              1.0        — Exceeds max_reuses_per_video; block reuse.
        """
        # Path-based exact-duplicate check (cheapest)
        if asset_path in self._seen_paths:
            return min(0.5, 0.3 * len(self._seen_paths))  # Already seen this exact path

        # Perceptual hash check (more expensive but catches near-dupes)
        if HAS_IMAGEHASH:
            try:
                phash = self._compute_phash(asset_path)
            except Exception:
                # If image loading fails, fall through to path-based
                phash = None

            if phash is not None:
                return self._check_hash(phash, timestamp)

        # Fallback: path-based
        return 0.0

    def record_use(self, asset_path: str, timestamp: float = 0.0) -> None:
        """Record that an asset has been used (after accepting it).

        Must be called *after* check_and_penalise returns an acceptable
        penalty so the detector knows about it for future checks.
        """
        self._seen_paths.add(asset_path)

        if HAS_IMAGEHASH:
            try:
                phash = self._compute_phash(asset_path)
                if phash is not None:
                    self._seen_hashes[phash].append(timestamp)
            except Exception:
                pass

    def reset(self) -> None:
        """Clear all tracking (for a new video render run)."""
        self._seen_hashes.clear()
        self._seen_paths.clear()

    @property
    def used_count(self) -> int:
        """Number of unique asset paths recorded so far."""
        return len(self._seen_paths)

    @property
    def total_reuses(self) -> int:
        """Total number of re-uses across all tracked assets."""
        total = 0
        for times in self._seen_hashes.values():
            if len(times) > 1:
                total += len(times) - 1
        return total

    # ── Internal helpers ───────────────────────────────────────────────

    def _compute_phash(self, asset_path: str):
        """Compute the perceptual hash of an image file.

        Args:
            asset_path: Path to an image or video frame.

        Returns:
            imagehash.ImageHash instance, or None on failure.
        """
        if not os.path.isfile(asset_path):
            return None
        # Convert to greyscale, resize to speed up hash computation
        img = Image.open(asset_path).convert("L").resize((64, 64))
        return imagehash.phash(img, hash_size=self.hash_size)

    def _check_hash(self, phash, timestamp: float) -> float:
        """Check a computed hash against all previously seen hashes.

        Returns a penalty 0.0–1.0 (same semantics as check_and_penalise).
        """
        max_distance = self.hash_size ** 2
        allowed_distance = int(max_distance * (1.0 - self.threshold))

        for seen_hash, times in self._seen_hashes.items():
            hamming = phash - seen_hash
            if hamming <= allowed_distance:
                # Found a similar (or identical) image
                if len(times) >= self.max_reuses_per_video:
                    return 1.0  # Block — exceeded max reuses

                # Linear penalty per previous use
                return min(0.3 * len(times), 0.9)

        return 0.0


# ── Shortcut function ──────────────────────────────────────────────────

def make_duplicate_detector(**kwargs) -> DuplicateDetector:
    """Factory function — creates a configured DuplicateDetector.

    Provides a single import for director_integration.py.
    """
    return DuplicateDetector(**kwargs)
