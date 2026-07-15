"""
visual_memory.py — Scene diversity tracker for duplicate detection.

Maintains a rolling window of recently seen visual objects, colors, providers,
camera angles, and compositions. Prevents the same planet, telescope, astronaut,
or galaxy from appearing twice within 60 seconds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class VisualMemoryEntry:
    """A single entry in visual memory."""

    timestamp: float
    objects: list[str]
    provider: str
    colors: list[str]
    camera_angle: str
    shot_type: str

    def __repr__(self) -> str:
        objs = ", ".join(self.objects[:3])
        return f"[{self.shot_type}] {objs} ({self.provider}) @ t={self.timestamp:.1f}s"


class VisualMemory:
    """Rolling window of visual content seen in the last N seconds.

    Prevents visual repetition by tracking what has been shown and rejecting
    duplicates within the configured window.

    Usage::

        memory = VisualMemory(window_seconds=60)
        memory.record(["Andromeda Galaxy", "spiral", "stars"], "pexels", "wide")
        if memory.is_duplicate(["Andromeda Galaxy"]):
            # Don't show this again
    """

    def __init__(self, window_seconds: float = 60.0):
        self._window = window_seconds
        self._entries: list[VisualMemoryEntry] = []
        self._sequence_count: int = 0

    # ── Public API ─────────────────────────────────────────────────────

    def record(
        self,
        objects: list[str],
        provider: str = "",
        camera_angle: str = "",
        shot_type: str = "",
        colors: Optional[list[str]] = None,
    ) -> None:
        """Record a shot in visual memory."""
        self._prune()
        self._entries.append(VisualMemoryEntry(
            timestamp=time.time(),
            objects=[o.lower() for o in objects],
            provider=provider,
            colors=colors or [],
            camera_angle=camera_angle,
            shot_type=shot_type,
        ))
        self._sequence_count += 1

    def is_duplicate(self, objects: list[str], threshold: float = 0.7) -> bool:
        """Check if any object in the list has appeared within the window.

        Args:
            objects: List of object names to check.
            threshold: Similarity threshold (0-1).

        Returns:
            True if a match is found within the window.
        """
        self._prune()
        if not objects:
            return False

        objs_lower = [o.lower() for o in objects]

        for entry in self._entries:
            overlap = set(objs_lower) & set(entry.objects)
            if overlap:
                return True

        return False

    def is_same_provider_recent(self, provider: str, max_in_window: int = 3) -> bool:
        """Check if a provider has been used too many times in the window."""
        self._prune()
        count = sum(1 for e in self._entries if e.provider == provider)
        return count >= max_in_window

    def get_recent_objects(self, n: int = 5) -> list[str]:
        """Get the most recent N unique objects seen."""
        self._prune()
        seen: set[str] = set()
        result: list[str] = []
        for entry in reversed(self._entries):
            for obj in entry.objects:
                if obj not in seen:
                    seen.add(obj)
                    result.append(obj)
                    if len(result) >= n:
                        return result
        return result

    def get_provider_diversity(self) -> dict[str, int]:
        """Count of entries per provider within the window."""
        self._prune()
        counts: dict[str, int] = {}
        for entry in self._entries:
            counts[entry.provider] = counts.get(entry.provider, 0) + 1
        return counts

    def get_stats(self) -> dict[str, Any]:
        """Return summary of current memory state."""
        self._prune()
        return {
            "window_seconds": self._window,
            "current_entries": len(self._entries),
            "total_sequence": self._sequence_count,
            "provider_counts": self.get_provider_diversity(),
            "recent_objects": self.get_recent_objects(10),
        }

    def clear(self) -> None:
        """Reset memory entirely."""
        self._entries.clear()
        self._sequence_count = 0

    # ── String representation for reports ──────────────────────────────

    def __repr__(self) -> str:
        return (
            f"VisualMemory(window={self._window}s, "
            f"entries={len(self._entries)}, "
            f"seq={self._sequence_count})"
        )

    # ── Internal ───────────────────────────────────────────────────────

    def _prune(self) -> None:
        """Remove entries older than the window."""
        cutoff = time.time() - self._window
        self._entries = [e for e in self._entries if e.timestamp >= cutoff]
