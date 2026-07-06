"""
report.py — Report generation for the evaluation framework.

The ``ReportGenerator`` consumes ``EvalSnapshot`` data and produces:

- **JSON** — machine-parseable structured data.
- **CSV** — tabular summary suitable for spreadsheets.
- **Markdown** — human-readable report with headings, tables, and summaries.

All output is configurable from ``configs/evaluator.yaml``.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.utils.config import get_config
from .metrics import EvalSnapshot


class ReportGenerator:
    """Generates evaluation reports in JSON, CSV, and Markdown formats.

    Parameters
    ----------
    output_dir : str, optional
        Directory for report files.  Defaults to ``evaluator.output_dir``
        from config (``"eval_reports"``).
    """

    def __init__(self, output_dir: Optional[str] = None) -> None:
        self._output_dir = output_dir or get_config("evaluator.output_dir", "eval_reports")

    # ── JSON ────────────────────────────────────────────────────────────

    def to_json(self, snapshot: EvalSnapshot, path: Optional[str] = None) -> str:
        """Write a JSON report and return the path."""
        path = path or os.path.join(self._output_dir, "eval_report.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        data = asdict(snapshot)
        data["_generated_at"] = datetime.utcnow().isoformat() + "Z"
        data["_report_format"] = "json"

        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    # ── CSV ─────────────────────────────────────────────────────────────

    def to_csv(self, snapshot: EvalSnapshot, path: Optional[str] = None) -> str:
        """Write a CSV summary and return the path."""
        path = path or os.path.join(self._output_dir, "eval_report.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        data = asdict(snapshot)
        flat = self._flatten(data)

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            for key, val in sorted(flat.items()):
                writer.writerow([key, val])
        return path

    # ── Markdown ────────────────────────────────────────────────────────

    def to_markdown(self, snapshot: EvalSnapshot, path: Optional[str] = None) -> str:
        """Write a human-readable Markdown report and return the path."""
        path = path or os.path.join(self._output_dir, "eval_report.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        lines: list[str] = []
        lines.append("# Evaluation Report")
        lines.append("")
        lines.append(f"_Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC_")
        lines.append("")

        # ── Performance ─────────────────────────────────────────────
        lines.append("## Performance (seconds)")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|------:|")
        lines.append(f"| Planning time | {snapshot.planning_time_s:.2f} |")
        lines.append(f"| Execution time | {snapshot.execution_time_s:.2f} |")
        lines.append(f"| Render time | {snapshot.render_time_s:.2f} |")
        lines.append(f"| Critic time | {snapshot.critic_time_s:.2f} |")
        lines.append(f"| **Total time** | **{snapshot.total_time_s:.2f}** |")
        lines.append("")

        # ── Asset pipeline ──────────────────────────────────────────
        lines.append("## Asset Pipeline")
        lines.append("")
        total_asset_ops = (
            snapshot.cache_hits + snapshot.cache_misses + snapshot.library_reuses
        )
        hit_rate = (
            round(snapshot.cache_hits / total_asset_ops * 100, 1)
            if total_asset_ops > 0
            else 0.0
        )
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|------:|")
        lines.append(f"| Cache hits | {snapshot.cache_hits} |")
        lines.append(f"| Cache misses | {snapshot.cache_misses} |")
        lines.append(f"| Library reuses | {snapshot.library_reuses} |")
        lines.append(f"| Downloads attempted | {snapshot.downloads_attempted} |")
        lines.append(f"| Downloads succeeded | {snapshot.downloads_succeeded} |")
        lines.append(f"| Downloads avoided (reuse) | {snapshot.downloads_avoided} |")
        lines.append(f"| Cache hit rate | {hit_rate}% |")
        lines.append("")

        # ── Scene / narration ───────────────────────────────────────
        lines.append("## Scene & Narration")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|------:|")
        lines.append(f"| Scene count | {snapshot.scene_count} |")
        lines.append(f"| Total narration words | {snapshot.total_narration_words} |")
        lines.append(f"| Avg words / scene | {snapshot.avg_narration_words_per_scene} |")
        lines.append(f"| Total estimated duration | {snapshot.total_estimated_duration:.1f}s |")
        lines.append(f"| Avg estimated duration / scene | {snapshot.avg_estimated_duration:.1f}s |")
        lines.append("")

        # ── Search queries ──────────────────────────────────────────
        lines.append("## Search Queries")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|------:|")
        lines.append(f"| Average query length (chars) | {snapshot.avg_search_query_length} |")
        lines.append(f"| Unique queries | {snapshot.unique_search_queries} |")
        lines.append(f"| Duplicate queries | {snapshot.duplicate_search_query_count} |")
        lines.append("")

        # ── Subtitles ───────────────────────────────────────────────
        if snapshot.subtitle_clip_count > 0:
            lines.append("## Subtitles")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|------:|")
            lines.append(f"| Total subtitle words | {snapshot.subtitle_word_count} |")
            lines.append(f"| Subtitle clips | {snapshot.subtitle_clip_count} |")
            lines.append("")

        # ── Output ──────────────────────────────────────────────────
        lines.append("## Output Video")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|------:|")
        lines.append(f"| Resolution | {snapshot.output_resolution} |")
        lines.append(f"| FPS | {snapshot.output_fps} |")
        if snapshot.final_duration_s is not None:
            lines.append(f"| Duration | {snapshot.final_duration_s:.2f}s |")
        if snapshot.output_file_size_bytes is not None:
            size_mb = snapshot.output_file_size_bytes / (1024 * 1024)
            lines.append(f"| File size | {size_mb:.1f} MB |")
        if snapshot.output_path:
            lines.append(f"| Output path | {snapshot.output_path} |")
        lines.append("")

        # ── Effects ─────────────────────────────────────────────────
        lines.append("## Effects")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|------:|")
        lines.append(f"| Non-cut transitions | {snapshot.num_transitions_non_cut} |")
        lines.append(f"| Motion types used | {', '.join(sorted(set(snapshot.motion_types_used))) if snapshot.motion_types_used else 'none'} |")
        lines.append("")

        # ── Critic ──────────────────────────────────────────────────
        if snapshot.critic_approved is not None:
            lines.append("## Critic")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|------:|")
            lines.append(f"| Approved | {'Yes' if snapshot.critic_approved else 'No'} |")
            lines.append(f"| Iterations | {snapshot.iteration_count} |")
            lines.append("")

        # ── Tags ────────────────────────────────────────────────────
        if snapshot.tags:
            lines.append("## Tags")
            lines.append("")
            for key, val in snapshot.tags.items():
                lines.append(f"- **{key}**: {val}")
            lines.append("")

        md = "\n".join(lines)
        with open(path, "w") as f:
            f.write(md)
        return path

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Flatten a nested dict into dot-separated keys."""
        result: dict[str, Any] = {}
        for key, val in data.items():
            fq_key = f"{prefix}.{key}" if prefix else key
            if isinstance(val, dict):
                result.update(ReportGenerator._flatten(val, fq_key))
            elif isinstance(val, list):
                result[fq_key] = json.dumps(val) if val else ""
            else:
                result[fq_key] = val
        return result
