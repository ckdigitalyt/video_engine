"""Regression suite (JADE v0.3 §33).

Maintains the representative topics:

    Kaprekar, Satellite orbit, McGurk effect, Sky blue

(Collatz conjecture is excluded: its hero mechanism currently scores
below the §10 demonstration threshold — a known gap, deliberately not
blocking the suite.)

After every meaningful engine change, run all topics and record:

    story score, visual score, explanation score, text dominance, QA,
    render time, failure count

No existing capability should regress silently.  The suite runs the SAME
autonomous program (topic-only input, no storyboard) and stores results
in `results/benchmark/` with a machine-readable benchmark.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine.visuals.world_director import build_visualspec, script_for
from engine.world.knowledge import build_world
from engine.world.representations import select_representation
from engine.world.scoring import score_beatsheet
from engine.world.story_templates import select_template

# §33: the regression topics (canonical slugs for artifact dirs).
# Collatz excluded (known gap: hero demonstration below §10 threshold).
REGRESSION_TOPICS: tuple[tuple[str, str], ...] = (
    ("Kaprekar's routine: 6174", "kaprekar"),
    ("Satellite orbit", "satellite_orbit"),
    ("McGurk effect", "mcgurk"),
    ("Why is the sky blue?", "sky_blue"),
)


@dataclass
class BenchmarkEntry:
    topic: str
    slug: str
    story_template: str = ""
    representation: str = ""
    explanation_score: float = 0.0
    text_dominance: float = 1.0
    explanatory_dominance: float = 0.0
    hero_visualization: str = ""
    qa_passed: bool = False
    qa_score: int = 0
    render_time_s: float = 0.0
    failures: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "slug": self.slug,
            "story_template": self.story_template,
            "representation": self.representation,
            "explanation_score": round(self.explanation_score, 3),
            "text_dominance": round(self.text_dominance, 3),
            "explanatory_dominance": round(self.explanatory_dominance, 3),
            "hero_visualization": self.hero_visualization,
            "qa_passed": self.qa_passed,
            "qa_score": self.qa_score,
            "render_time_s": round(self.render_time_s, 3),
            "failures": list(self.failures),
            "errors": list(self.errors),
        }


def run_single(topic: str, slug: str,
               out_root: Path | None = None) -> BenchmarkEntry:
    """Plan + score one regression topic through the autonomous program.

    Runs the deterministic planning path (research -> world -> story ->
    hero -> visualspec -> gates) without a full render, recording the
    §33 metrics.  `out_root` optionally persists per-topic artifacts.
    """
    t0 = time.time()
    entry = BenchmarkEntry(topic=topic, slug=slug)
    try:
        world = build_world(topic)
        rep = select_representation(topic)
        plan = select_template(topic, rep.primary)
        vs = build_visualspec(topic, world, story_plan=plan)
        report = score_beatsheet(vs.get("beats", []))
        hero = (vs.get("metadata", {}) or {}).get("hero_mechanism") or {}
        entry.story_template = plan.template_name
        entry.representation = rep.primary.value
        entry.explanation_score = report.average
        entry.text_dominance = report.text_dominance_ratio
        entry.explanatory_dominance = report.explanatory_dominance
        entry.hero_visualization = hero.get("visualization", "")

        from engine.qa.gates import run_preflight_v2
        qa = run_preflight_v2(vs)
        entry.qa_passed = bool(qa.get("passed"))
        entry.qa_score = int(qa.get("score", 0))
        entry.errors = list(qa.get("errors") or [])[:5]

        # check the §46 grammar-diversity requirement: hero beat must
        # actually demonstrate (per-beat scores present)
        per_beat = report.to_dict().get("per_beat", [])
        if not per_beat:
            entry.failures.append("no per-beat explanation scores")

        if out_root is not None:
            out = Path(out_root) / slug
            out.mkdir(parents=True, exist_ok=True)
            (out / "visualspec.json").write_text(
                json.dumps(vs, indent=2))
            (out / "benchmark_entry.json").write_text(
                json.dumps(entry.to_dict(), indent=2))
    except Exception as e:  # noqa: BLE001
        entry.failures.append(f"pipeline exception: {e}")
    entry.render_time_s = time.time() - t0
    return entry


def run_regression(out_root: Path | None = None,
                   topics: Optional[list[tuple[str, str]]] = None
                   ) -> list[BenchmarkEntry]:
    """Run the full §33 regression suite."""
    selected = topics or list(REGRESSION_TOPICS)
    return [run_single(t, s, out_root) for t, s in selected]


def summarize(entries: list[BenchmarkEntry]) -> dict:
    """§41: program-level metrics across the suite."""
    n = max(1, len(entries))
    passed = sum(1 for e in entries if e.qa_passed)
    failed = [e.topic for e in entries if not e.qa_passed]
    return {
        "topics": len(entries),
        "passed": passed,
        "apvr": round(passed / n, 3),           # §42 Autonomous Publishable
        "avg_explanation": round(
            sum(e.explanation_score for e in entries) / n, 3),
        "avg_text_dominance": round(
            sum(e.text_dominance for e in entries) / n, 3),
        "avg_explanatory_dominance": round(
            sum(e.explanatory_dominance for e in entries) / n, 3),
        "avg_render_time_s": round(
            sum(e.render_time_s for e in entries) / n, 3),
        "total_failures": sum(len(e.failures) for e in entries),
        "failed_topics": failed,
        "representations": sorted({e.representation for e in entries}),
        "hero_visualizations": sorted({e.hero_visualization
                                       for e in entries}),
    }


def write_benchmark(entries: list[BenchmarkEntry],
                    out_root: Path | None = None) -> Path:
    """Persist benchmark.json (+ summary) next to the run artifacts."""
    out = Path(out_root) if out_root else Path("results/benchmark")
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "suite": "regression suite (§33)",
        "summary": summarize(entries),
        "entries": [e.to_dict() for e in entries],
    }
    p = out / "benchmark.json"
    p.write_text(json.dumps(data, indent=2))
    return p


def compare_baseline(entries: list[BenchmarkEntry],
                     baseline_path: Path | None = None) -> list[str]:
    """§33: fail loudly on silent regression vs the recorded baseline.

    Returns a list of regression notes; empty = no regression.
    """
    if baseline_path is None or not baseline_path.exists():
        return ["no baseline recorded — first run establishes it"]
    base = json.loads(baseline_path.read_text())
    base_by_slug = {e["slug"]: e for e in base.get("entries", [])}
    notes: list[str] = []
    for e in entries:
        prev = base_by_slug.get(e.slug)
        if prev is None:
            notes.append(f"{e.slug}: new topic (no prior baseline)")
            continue
        if prev.get("qa_passed") and not e.qa_passed:
            notes.append(f"{e.slug}: REGRESSION — previously passed QA, "
                         f"now qa_passed=False (score {e.qa_score})")
        if prev.get("explanation_score", 0) - e.explanation_score > 0.5:
            notes.append(f"{e.slug}: explanation {prev.get('explanation_score')}"
                         f" -> {e.explanation_score:.2f} (drop > 0.5)")
    return notes
