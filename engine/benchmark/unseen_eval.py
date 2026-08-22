"""Unseen-topic evaluation (JADE v0.3 §34).

The five regression topics are not enough.  This module periodically
generates COMPLETELY NEW topics — never-seen, no manual storyboard —
and runs them through the exact same autonomous program (topic-only
input).  These are the true generalization tests: if the engine can
only make the benchmark topics look good it has failed §34.

The §34 topic list:
    noise-cancelling headphones, popcorn, microwave, ice, airplane
    lift, GPS relativity, mirrors, barcode, camera autofocus

Each topic is planned + scored + gated exactly like a regression topic
(no topic-specific code paths).  Results persist to
`results/unseen/benchmark.json` with the same summary shape as the
regression suite so APVR is comparable across both.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine.benchmark.suite import (
    BenchmarkEntry, run_single, summarize, write_benchmark,
)

# §34: unseen topics (topic, slug) — NEVER given a manual storyboard.
UNSEEN_TOPICS: tuple[tuple[str, str], ...] = (
    ("How noise-cancelling headphones work", "noise_cancelling"),
    ("Why popcorn pops", "popcorn"),
    ("How a microwave heats food", "microwave"),
    ("Why ice is slippery", "ice"),
    ("Why airplane wings generate lift", "lift"),
    ("Why GPS needs relativity", "gps"),
    ("Why mirrors reverse left-right", "mirrors"),
    ("How a barcode works", "barcode"),
    ("How a camera autofocuses", "autofocus"),
)

# Minimum generalization bar for the §34 evaluation: a weak engine that
# only handles its benchmark topics must FAIL this gate.
MIN_UNSEEN_APVR = 0.5
MIN_UNSEEN_REPS = 3          # §46: distinct visual grammars required
MIN_UNSEEN_HEROES = 3        # distinct hero mechanisms required


@dataclass
class UnseenReport:
    apvr: float = 0.0
    passed: int = 0
    total: int = 0
    representations: list[str] = field(default_factory=list)
    hero_visualizations: list[str] = field(default_factory=list)
    failed_topics: list[str] = field(default_factory=list)
    avg_explanation: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "suite": "unseen-topic evaluation (§34)",
            "apvr": round(self.apvr, 3),
            "passed": self.passed,
            "total": self.total,
            "representations": sorted(self.representations),
            "hero_visualizations": sorted(self.hero_visualizations),
            "failed_topics": list(self.failed_topics),
            "avg_explanation": round(self.avg_explanation, 3),
            "notes": list(self.notes),
        }


def run_unseen_eval(topics: Optional[list[tuple[str, str]]] = None,
                    out_root: Path | None = None) -> tuple[list[BenchmarkEntry],
                                                           UnseenReport]:
    """Run the §34 unseen topics through the autonomous program.

    Returns (entries, report).  `out_root` optionally persists
    per-topic artifacts (same layout as the regression suite).
    """
    selected = topics or list(UNSEEN_TOPICS)
    entries = [run_single(t, s, out_root) for t, s in selected]
    s = summarize(entries)
    report = UnseenReport(
        apvr=s["apvr"],
        passed=s["passed"],
        total=s["topics"],
        representations=s["representations"],
        hero_visualizations=s["hero_visualizations"],
        failed_topics=s["failed_topics"],
        avg_explanation=s["avg_explanation"],
    )
    # §34: the generalization bar
    if s["apvr"] < MIN_UNSEEN_APVR:
        report.notes.append(
            f"APVR {s['apvr']:.2f} < {MIN_UNSEEN_APVR} — engine does not "
            "generalize to unseen topics")
    if len(s["representations"]) < MIN_UNSEEN_REPS:
        report.notes.append(
            f"only {len(s['representations'])} distinct representations "
            f"(need >= {MIN_UNSEEN_REPS}) — visual grammar is not adapting")
    if len(s["hero_visualizations"]) < MIN_UNSEEN_HEROES:
        report.notes.append(
            f"only {len(s['hero_visualizations'])} distinct hero "
            f"mechanisms (need >= {MIN_UNSEEN_HEROES})")
    if not report.notes:
        report.notes.append(
            f"generalizes: {s['passed']}/{s['topics']} unseen topics pass")
    return entries, report


def write_unseen_benchmark(entries: list[BenchmarkEntry],
                           report: UnseenReport,
                           out_root: Path | None = None) -> Path:
    """Persist the §34 evaluation next to the regression benchmark."""
    out = Path(out_root) if out_root else Path("results/unseen")
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "suite": "unseen-topic evaluation (§34)",
        "report": report.to_dict(),
        "entries": [e.to_dict() for e in entries],
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    p = out / "benchmark.json"
    p.write_text(json.dumps(data, indent=2))
    return p


def load_unseen_benchmark(path: Path) -> dict:
    """Load a previously written §34 benchmark for comparison."""
    return json.loads(Path(path).read_text())
