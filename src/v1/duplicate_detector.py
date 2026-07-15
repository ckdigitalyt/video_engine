"""
duplicate_detector.py — V1 duplicate detection using VisualMemory.
"""

from __future__ import annotations

from typing import Any, Optional

from src.director.visual_memory import VisualMemory


class DuplicateDetector:
    """Detects and prevents duplicate visual content.

    Wraps VisualMemory with scene-level duplicate detection.
    """

    def __init__(self, window_seconds: float = 60.0):
        self._memory = VisualMemory(window_seconds=window_seconds)

    def check(self, objects: list[str], threshold: float = 0.7) -> bool:
        """Returns True if content is a duplicate."""
        return self._memory.is_duplicate(objects, threshold=threshold)

    def record(self, objects: list[str], provider: str = "", **kwargs: Any) -> None:
        """Record content in memory."""
        self._memory.record(objects, provider=provider, **kwargs)

    def get_stats(self) -> dict[str, Any]:
        return self._memory.get_stats()

    def clear(self) -> None:
        self._memory.clear()
