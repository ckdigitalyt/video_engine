"""
postmortem.py — Structured learning system.

After every completed project, writes a structured postmortem recording:
successful/failed techniques, prompt improvements, visual/narration/rendering
optimizations, review feedback, and benchmark results.

Outputs:
  - docs/mission/postmortems/postmortem-<slug>.md  (human-readable)
  - cache/memory.db                                (structured, via memory_manager)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

POSTMORTEM_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "mission", "postmortems",
)


class PostmortemRecorder:
    """Records structured postmortems for the learning system."""

    def __init__(self, db_path: str = "cache/memory.db", out_dir: str = POSTMORTEM_DIR):
        self._db_path = db_path
        self._out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────

    def record(
        self,
        topic: str,
        *,
        techniques_succeeded: Optional[list[str]] = None,
        techniques_failed: Optional[list[str]] = None,
        prompt_improvements: Optional[list[str]] = None,
        visual_improvements: Optional[list[str]] = None,
        narration_improvements: Optional[list[str]] = None,
        rendering_optimizations: Optional[list[str]] = None,
        review_feedback: Optional[list[str]] = None,
        benchmark_results: Optional[dict] = None,
        metrics: Optional[dict] = None,
        artifacts: Optional[dict] = None,
    ) -> str:
        """Record a postmortem; returns the markdown file path."""
        slug = self._slug(topic)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry = {
            "topic": topic,
            "slug": slug,
            "timestamp": ts,
            "techniques_succeeded": techniques_succeeded or [],
            "techniques_failed": techniques_failed or [],
            "prompt_improvements": prompt_improvements or [],
            "visual_improvements": visual_improvements or [],
            "narration_improvements": narration_improvements or [],
            "rendering_optimizations": rendering_optimizations or [],
            "review_feedback": review_feedback or [],
            "benchmark_results": benchmark_results or {},
            "metrics": metrics or {},
            "artifacts": artifacts or {},
        }

        # Structured store
        self._write_db(entry)

        # Human-readable
        path = os.path.join(self._out_dir, f"postmortem-{slug}.md")
        with open(path, "w") as f:
            f.write(self._render_md(entry))
        return path

    def list(self) -> list[dict]:
        """Recent postmortems from the DB (most recent first)."""
        if not os.path.exists(self._db_path):
            return []
        try:
            con = sqlite3.connect(self._db_path)
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT topic, timestamp, metrics_json FROM postmortems ORDER BY id DESC LIMIT 20"
            ).fetchall()
            con.close()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []

    # ── Internals ──────────────────────────────────────────────────────

    def _write_db(self, entry: dict):
        try:
            con = sqlite3.connect(self._db_path)
            con.execute(
                """CREATE TABLE IF NOT EXISTS postmortems (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    slug TEXT,
                    timestamp TEXT,
                    body_json TEXT,
                    metrics_json TEXT
                )"""
            )
            con.execute(
                "INSERT INTO postmortems (topic, slug, timestamp, body_json, metrics_json) VALUES (?,?,?,?,?)",
                (
                    entry["topic"], entry["slug"], entry["timestamp"],
                    json.dumps(entry, default=str),
                    json.dumps(entry.get("metrics", {}), default=str),
                ),
            )
            con.commit()
            con.close()
        except sqlite3.Error as e:
            print(f"[Postmortem] DB write failed (non-fatal): {e}")

    @staticmethod
    def _render_md(e: dict) -> str:
        lines = [
            f"# Postmortem — {e['topic']}",
            f"**When:** {e['timestamp']}",
            "",
        ]
        for label, key in [
            ("Techniques that worked", "techniques_succeeded"),
            ("Techniques that failed", "techniques_failed"),
            ("Prompt improvements", "prompt_improvements"),
            ("Visual improvements", "visual_improvements"),
            ("Narration improvements", "narration_improvements"),
            ("Rendering optimizations", "rendering_optimizations"),
            ("Review feedback", "review_feedback"),
        ]:
            lines.append(f"## {label}")
            items = e.get(key) or []
            if items:
                lines += [f"- {i}" for i in items]
            else:
                lines.append("_(none recorded)_")
            lines.append("")

        if e.get("benchmark_results"):
            lines.append("## Benchmark results")
            lines.append("```json")
            lines.append(json.dumps(e["benchmark_results"], indent=2, default=str))
            lines.append("```")
            lines.append("")

        if e.get("metrics"):
            lines.append("## Metrics")
            lines.append("```json")
            lines.append(json.dumps(e["metrics"], indent=2, default=str))
            lines.append("```")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _slug(topic: str) -> str:
        import re
        s = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        return s[:60] or "project"


if __name__ == "__main__":
    rec = PostmortemRecorder()
    path = rec.record(
        "Smoke test",
        techniques_succeeded=["module wiring"],
        metrics={"duration_s": 1},
    )
    print(f"Postmortem written: {path}")
