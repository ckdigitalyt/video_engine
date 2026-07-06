"""
metrics.py — Metric collection for the evaluation framework.

The ``MetricsCollector`` gathers timing, asset, quality, and output metrics
during pipeline execution.  It is callable from any pipeline node and
emits ``EvalSnapshot`` dataclasses that the ``EvaluationEngine`` later
aggregates.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ── Snapshot models ───────────────────────────────────────────────────────


@dataclass
class EvalSnapshot:
    """A single point-in-time measurement set."""

    # Timing
    planning_time_s: float = 0.0
    execution_time_s: float = 0.0
    render_time_s: float = 0.0
    critic_time_s: float = 0.0
    total_time_s: float = 0.0

    # Asset pipeline
    cache_hits: int = 0
    cache_misses: int = 0
    library_reuses: int = 0
    downloads_attempted: int = 0
    downloads_succeeded: int = 0
    downloads_avoided: int = 0  # due to library reuse

    # Scene metrics
    scene_count: int = 0
    total_narration_words: int = 0
    avg_narration_words_per_scene: float = 0.0
    total_estimated_duration: float = 0.0
    avg_estimated_duration: float = 0.0

    # Search query stats
    avg_search_query_length: float = 0.0
    unique_search_queries: int = 0
    duplicate_search_query_count: int = 0

    # Subtitle metrics
    subtitle_word_count: int = 0
    subtitle_clip_count: int = 0

    # Output metrics
    output_resolution: str = "1920x1080"
    output_fps: int = 30
    final_duration_s: Optional[float] = None
    output_file_size_bytes: Optional[int] = None
    output_path: Optional[str] = None

    # Critic
    critic_approved: Optional[bool] = None
    iteration_count: int = 1

    # Transitions / motion
    num_transitions_non_cut: int = 0
    motion_types_used: list[str] = field(default_factory=list)

    # Custom tags
    tags: dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Context-manager friendly collector that accumulates ``EvalSnapshot`` data.

    Usage
    -----
    collector = MetricsCollector()
    collector.start("planning")
    # … do planning work …
    collector.stop("planning")
    """

    def __init__(self) -> None:
        self._snapshots: list[EvalSnapshot] = []
        self._timers: dict[str, float] = {}
        self._running: dict[str, float] = {}

    # ── Timing ──────────────────────────────────────────────────────────

    def start(self, phase: str) -> None:
        """Start a phase timer (planning, execution, render, critic)."""
        self._running[phase] = time.perf_counter()

    def stop(self, phase: str) -> None:
        """Stop a phase timer and record elapsed seconds."""
        if phase in self._running:
            elapsed = time.perf_counter() - self._running[phase]
            self._timers[phase] = elapsed
            del self._running[phase]

    def elapsed(self, phase: str) -> float:
        """Return recorded elapsed time for a phase (0 if not recorded)."""
        return self._timers.get(phase, 0.0)

    # ── Asset helpers ──────────────────────────────────────────────────

    def record_cache_hit(self) -> None:
        self._timers.setdefault("_cache_hits", 0)
        self._timers["_cache_hits"] += 1  # type: ignore[operator]

    def record_cache_miss(self) -> None:
        self._timers.setdefault("_cache_misses", 0)
        self._timers["_cache_misses"] += 1  # type: ignore[operator]

    def record_reuse(self) -> None:
        self._timers.setdefault("_reuses", 0)
        self._timers["_reuses"] += 1  # type: ignore[operator]

    def record_download(self, succeeded: bool = True) -> None:
        self._timers.setdefault("_downloads", 0)
        self._timers["_downloads"] += 1  # type: ignore[operator]
        if succeeded:
            self._timers.setdefault("_dl_ok", 0)
            self._timers["_dl_ok"] += 1  # type: ignore[operator]

    # ── Snapshot assembly ─────────────────────────────────────────────

    def snapshot(
        self,
        *,
        scene_count: int = 0,
        narration_words: int = 0,
        estimated_duration: float = 0.0,
        search_query_lengths: Optional[list[int]] = None,
        duplicate_queries: int = 0,
        subtitle_words: int = 0,
        subtitle_clips: int = 0,
        resolution: str = "1920x1080",
        fps: int = 30,
        final_duration: Optional[float] = None,
        file_size: Optional[int] = None,
        output_path: Optional[str] = None,
        critic_approved: Optional[bool] = None,
        iterations: int = 1,
        num_transitions: int = 0,
        motion_types: Optional[list[str]] = None,
        tags: Optional[dict[str, Any]] = None,
    ) -> EvalSnapshot:
        """Build and return an ``EvalSnapshot`` from currently collected data."""
        sq = search_query_lengths or []

        return EvalSnapshot(
            planning_time_s=self._timers.get("planning", 0.0),
            execution_time_s=self._timers.get("execution", 0.0),
            render_time_s=self._timers.get("render", 0.0),
            critic_time_s=self._timers.get("critic", 0.0),
            total_time_s=sum(
                self._timers.get(p, 0.0)
                for p in ("planning", "execution", "render", "critic")
            ),
            cache_hits=int(self._timers.get("_cache_hits", 0)),
            cache_misses=int(self._timers.get("_cache_misses", 0)),
            library_reuses=int(self._timers.get("_reuses", 0)),
            downloads_attempted=int(self._timers.get("_downloads", 0)),
            downloads_succeeded=int(self._timers.get("_dl_ok", 0)),
            downloads_avoided=int(self._timers.get("_reuses", 0)),
            scene_count=scene_count,
            total_narration_words=narration_words,
            avg_narration_words_per_scene=(
                round(narration_words / scene_count, 1) if scene_count > 0 else 0.0
            ),
            total_estimated_duration=estimated_duration,
            avg_estimated_duration=(
                round(estimated_duration / scene_count, 1) if scene_count > 0 else 0.0
            ),
            avg_search_query_length=(
                round(sum(sq) / len(sq), 1) if sq else 0.0
            ),
            unique_search_queries=len([q for q in sq if q > 0]),
            duplicate_search_query_count=duplicate_queries,
            subtitle_word_count=subtitle_words,
            subtitle_clip_count=subtitle_clips,
            output_resolution=resolution,
            output_fps=fps,
            final_duration_s=final_duration,
            output_file_size_bytes=file_size,
            output_path=output_path,
            critic_approved=critic_approved,
            iteration_count=iterations,
            num_transitions_non_cut=num_transitions,
            motion_types_used=motion_types or [],
            tags=tags or {},
        )

    def reset(self) -> None:
        """Clear all collected data."""
        self._snapshots.clear()
        self._timers.clear()
        self._running.clear()
