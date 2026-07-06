"""
evaluator.py — Orchestrating evaluation engine for the video_engine pipeline.

The ``EvaluationEngine`` wraps a ``MetricsCollector`` and a
``ReportGenerator``, providing a single entry point for collecting metrics
during pipeline execution and exporting reports.

Designed to be renderer- and planner-independent.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from src.utils.config import get_config
from .metrics import MetricsCollector, EvalSnapshot
from .report import ReportGenerator


class EvaluationEngine:
    """Top-level evaluation engine for the pipeline.

    Parameters
    ----------
    collector : MetricsCollector, optional
        Metrics collector instance.  Created fresh if omitted.
    report_generator : ReportGenerator, optional
        Report generator instance.  Created fresh if omitted.
    """

    def __init__(
        self,
        collector: Optional[MetricsCollector] = None,
        report_generator: Optional[ReportGenerator] = None,
    ) -> None:
        self.collector = collector or MetricsCollector()
        self.reporter = report_generator or ReportGenerator()
        self._snapshot: Optional[EvalSnapshot] = None

    # ── Timing helpers (delegated to collector) ────────────────────────

    def start_phase(self, phase: str) -> None:
        """Start a timing phase."""
        self.collector.start(phase)

    def stop_phase(self, phase: str) -> None:
        """Stop a timing phase."""
        self.collector.stop(phase)

    # ── Asset helpers (delegated to collector) ─────────────────────────

    def record_cache_hit(self) -> None:
        self.collector.record_cache_hit()

    def record_cache_miss(self) -> None:
        self.collector.record_cache_miss()

    def record_reuse(self) -> None:
        self.collector.record_reuse()

    def record_download(self, succeeded: bool = True) -> None:
        self.collector.record_download(succeeded=succeeded)

    # ── Final evaluation ──────────────────────────────────────────────

    def evaluate(self, **kwargs: Any) -> EvalSnapshot:
        """Build a snapshot from currently collected data.

        All keyword arguments are forwarded to
        ``MetricsCollector.snapshot(...)``.
        """
        self._snapshot = self.collector.snapshot(**kwargs)
        return self._snapshot

    def export_reports(
        self,
        snapshot: Optional[EvalSnapshot] = None,
        formats: Optional[list[str]] = None,
    ) -> dict[str, str]:
        """Generate report files and return a dict mapping format → path.

        Parameters
        ----------
        snapshot : EvalSnapshot, optional
            Snapshot to export.  Uses the latest evaluated snapshot if
            omitted.
        formats : list[str], optional
            Which formats to produce (``"json"``, ``"csv"``, ``"md"``).
            Defaults to all three.

        Returns
        -------
        dict[str, str]
            ``{"json": "path/to/report.json", "csv": ..., "md": ...}``
        """
        snap = snapshot or self._snapshot
        if snap is None:
            raise ValueError("No snapshot to export. Call evaluate() first.")

        if formats is None:
            formats = ["json", "csv", "md"]

        paths: dict[str, str] = {}
        if "json" in formats:
            paths["json"] = self.reporter.to_json(snap)
        if "csv" in formats:
            paths["csv"] = self.reporter.to_csv(snap)
        if "md" in formats:
            paths["md"] = self.reporter.to_markdown(snap)
        return paths

    def reset(self) -> None:
        """Reset all collected data."""
        self.collector.reset()
        self._snapshot = None
