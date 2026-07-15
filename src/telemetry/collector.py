"""
collector.py — Telemetry collector for the video engine pipeline.

Measures: provider hit rate, provider latency, semantic score, critic score,
fallback %, duplicate %, cache %, download failures, retry count, blank frame %,
render success. Produces a dashboard after every video.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from src.utils.config import get_config


@dataclass
class TelemetryEvent:
    """Single telemetry measurement."""

    event_type: str
    timestamp: float = 0.0
    duration_ms: float = 0.0
    provider: str = ""
    query: str = ""
    topic: str = ""
    scene_id: int = 0
    success: bool = True
    score: float = 0.0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TelemetryCollector:
    """Collects and reports telemetry for the video pipeline.

    Usage::

        telemetry = TelemetryCollector(topic="The Fermi Paradox")
        telemetry.record_provider_call("pexels", "spiral galaxy", success=True, duration_ms=150)
        telemetry.record_critic_score(85)
        telemetry.record_fallback_use()
        report = telemetry.summary()
    """

    def __init__(
        self,
        topic: str = "",
        output_dir: str = "",
    ):
        self._topic = topic
        self._output_dir = output_dir or get_config("telemetry.output_dir", "results/validation")
        os.makedirs(self._output_dir, exist_ok=True)

        self._events: list[TelemetryEvent] = []
        self._start_time = time.time()

        # Aggregated counters
        self._provider_calls: dict[str, int] = {}
        self._provider_hits: dict[str, int] = {}
        self._provider_latency: dict[str, list[float]] = {}
        self._critic_scores: list[int] = []
        self._semantic_scores: list[float] = []
        self._fallback_count: int = 0
        self._duplicate_count: int = 0
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._download_failures: int = 0
        self._retry_count: int = 0
        self._blank_frames: int = 0
        self._render_success: bool = False

    # ── Record methods ─────────────────────────────────────────────────

    def record_provider_call(
        self,
        provider: str,
        query: str = "",
        success: bool = True,
        duration_ms: float = 0.0,
        error: str = "",
    ) -> None:
        """Record a provider search call."""
        self._provider_calls[provider] = self._provider_calls.get(provider, 0) + 1
        if success:
            self._provider_hits[provider] = self._provider_hits.get(provider, 0) + 1
        if provider not in self._provider_latency:
            self._provider_latency[provider] = []
        self._provider_latency[provider].append(duration_ms)

        self._events.append(TelemetryEvent(
            event_type="provider_call",
            timestamp=time.time(),
            duration_ms=duration_ms,
            provider=provider,
            query=query[:60],
            topic=self._topic,
            success=success,
            error=error,
        ))

    def record_critic_score(self, score: int) -> None:
        """Record a visual critic score."""
        self._critic_scores.append(score)
        self._events.append(TelemetryEvent(
            event_type="critic_score", score=float(score),
            timestamp=time.time(),
        ))

    def record_semantic_score(self, score: float) -> None:
        """Record a semantic validation score."""
        self._semantic_scores.append(score)
        self._events.append(TelemetryEvent(
            event_type="semantic_score", score=score,
            timestamp=time.time(),
        ))

    def record_fallback_use(self) -> None:
        """Increment fallback counter."""
        self._fallback_count += 1

    def record_duplicate(self) -> None:
        """Increment duplicate counter."""
        self._duplicate_count += 1

    def record_cache_hit(self) -> None:
        """Increment cache hit counter."""
        self._cache_hits += 1

    def record_cache_miss(self) -> None:
        """Increment cache miss counter."""
        self._cache_misses += 1

    def record_download_failure(self, error: str = "") -> None:
        """Record a download failure."""
        self._download_failures += 1
        self._events.append(TelemetryEvent(
            event_type="download_failure",
            timestamp=time.time(),
            success=False,
            error=error[:120],
        ))

    def record_retry(self) -> None:
        """Increment retry counter."""
        self._retry_count += 1

    def record_blank_frame(self) -> None:
        """Record a blank frame detection."""
        self._blank_frames += 1

    def record_render_success(self) -> None:
        """Mark render as successful."""
        self._render_success = True
        self._events.append(TelemetryEvent(
            event_type="render_success", timestamp=time.time(),
        ))

    def record_event(self, event: TelemetryEvent) -> None:
        """Record a generic telemetry event."""
        self._events.append(event)

    # ── Reporting ──────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Generate a dashboard-quality summary of all metrics."""
        total_calls = sum(self._provider_calls.values())

        # Provider hit rates
        provider_stats: dict[str, dict] = {}
        for provider in sorted(self._provider_calls.keys()):
            calls = self._provider_calls[provider]
            hits = self._provider_hits.get(provider, 0)
            latency_list = self._provider_latency.get(provider, [])
            provider_stats[provider] = {
                "calls": calls,
                "hits": hits,
                "hit_rate": round(hits / max(calls, 1) * 100, 1),
                "avg_latency_ms": round(sum(latency_list) / max(len(latency_list), 1), 1),
            }

        # Cache stats
        cache_total = self._cache_hits + self._cache_misses
        cache_rate = round(self._cache_hits / max(cache_total, 1) * 100, 1)

        # Critic stats
        critic_avg = round(
            sum(self._critic_scores) / max(len(self._critic_scores), 1), 1
        ) if self._critic_scores else 0.0

        # Semantic stats
        semantic_avg = round(
            sum(self._semantic_scores) / max(len(self._semantic_scores), 1), 2
        ) if self._semantic_scores else 0.0

        elapsed = round(time.time() - self._start_time, 1)

        report = {
            "topic": self._topic,
            "elapsed_seconds": elapsed,
            "render_success": self._render_success,
            "provider_stats": provider_stats,
            "total_provider_calls": total_calls,
            "critic_scores": {
                "count": len(self._critic_scores),
                "average": critic_avg,
                "min": min(self._critic_scores) if self._critic_scores else 0,
                "max": max(self._critic_scores) if self._critic_scores else 0,
            },
            "semantic_scores": {
                "count": len(self._semantic_scores),
                "average": semantic_avg,
            },
            "fallback_count": self._fallback_count,
            "duplicate_count": self._duplicate_count,
            "cache_stats": {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate": cache_rate,
            },
            "download_failures": self._download_failures,
            "retry_count": self._retry_count,
            "blank_frames": self._blank_frames,
            "events_count": len(self._events),
        }
        return report

    def write_report(self, output_path: str = "") -> str:
        """Write summary report to JSON file."""
        path = output_path or os.path.join(
            self._output_dir, f"telemetry_{self._topic.lower().replace(' ', '_')}.json"
        )
        report = self.summary()
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"[Telemetry] Report written to {path}")
        return path

    def dashboard_text(self) -> str:
        """Return a human-readable dashboard string."""
        s = self.summary()
        lines = [
            f"╔══ TELEMETRY DASHBOARD ═══",
            f"║ Topic: {s['topic']}",
            f"║ Duration: {s['elapsed_seconds']}s",
            f"║ Render: {'✅' if s['render_success'] else '❌'}",
            f"║",
            f"║ Providers ({s['total_provider_calls']} calls):",
        ]
        for p_name, p_stats in s.get("provider_stats", {}).items():
            lines.append(
                f"║   {p_name}: {p_stats['hit_rate']}% hit rate "
                f"({p_stats['calls']} calls, "
                f"avg {p_stats['avg_latency_ms']}ms)"
            )
        lines += [
            f"║",
            f"║ Critic: avg={s['critic_scores']['average']} "
            f"(n={s['critic_scores']['count']})",
            f"║ Semantic: avg={s['semantic_scores']['average']} "
            f"(n={s['semantic_scores']['count']})",
            f"║ Fallsbacks: {s['fallback_count']}",
            f"║ Duplicates: {s['duplicate_count']}",
            f"║ Cache: {s['cache_stats']['hit_rate']}% "
            f"({s['cache_stats']['hits']} hits, "
            f"{s['cache_stats']['misses']} misses)",
            f"║ Downloads failed: {s['download_failures']}",
            f"║ Retries: {s['retry_count']}",
            f"║ Blank frames: {s['blank_frames']}",
            f"╚══ END ═══",
        ]
        return "\n".join(lines)
