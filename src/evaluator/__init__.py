"""
evaluator — Evaluation & benchmark framework for the video_engine pipeline.

Provides a renderer/planner-independent engine that collects performance,
asset-usage, and quality metrics during pipeline execution and exports them
as JSON, CSV, or Markdown.
"""

from .evaluator import EvaluationEngine
from .metrics import MetricsCollector
from .report import ReportGenerator

__all__ = ["EvaluationEngine", "MetricsCollector", "ReportGenerator"]
