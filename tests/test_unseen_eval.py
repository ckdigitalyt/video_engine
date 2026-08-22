"""Phase I tests (§34): unseen-topic evaluation.

- all nine unseen topics run through the SAME autonomous program
  (topic-only, no manual storyboard)
- generalization bar: APVR >= 0.5, >= 3 distinct representations,
  >= 3 distinct hero mechanisms
- benchmark.json written correctly
- the engine is not overfit to the five regression topics
"""

from __future__ import annotations

import json

import pytest

from engine.benchmark.suite import REGRESSION_TOPICS
from engine.benchmark.unseen_eval import (
    MIN_UNSEEN_APVR,
    MIN_UNSEEN_HEROES,
    MIN_UNSEEN_REPS,
    UNSEEN_TOPICS,
    run_unseen_eval,
    write_unseen_benchmark,
)


def test_unseen_topics_are_disjoint_from_regression():
    unseen = {s for _, s in UNSEEN_TOPICS}
    regression = {s for _, s in REGRESSION_TOPICS}
    assert unseen.isdisjoint(regression)


def test_all_unseen_topics_plan_without_pipeline_failure(tmp_path):
    entries, _ = run_unseen_eval(out_root=tmp_path)
    assert len(entries) == len(UNSEEN_TOPICS)
    for e in entries:
        assert not e.failures, f"{e.topic}: {e.failures}"
        assert e.explanation_score > 0, f"{e.topic}: no explanation plan"


def test_unseen_generalization_bar(tmp_path):
    entries, report = run_unseen_eval(out_root=tmp_path)
    assert report.apvr >= MIN_UNSEEN_APVR, (
        f"APVR {report.apvr} < {MIN_UNSEEN_APVR}: "
        f"failed {report.failed_topics}")
    assert len(report.representations) >= MIN_UNSEEN_REPS, (
        f"representations too uniform: {report.representations}")
    assert len(report.hero_visualizations) >= MIN_UNSEEN_HEROES, (
        f"heroes too uniform: {report.hero_visualizations}")
    assert not report.notes or all(
        not n.startswith("APVR") and not n.startswith("only")
        for n in report.notes)


def test_unseen_benchmark_json_written(tmp_path):
    entries, report = run_unseen_eval(out_root=tmp_path)
    p = write_unseen_benchmark(entries, report, out_root=tmp_path)
    data = json.loads(p.read_text())
    assert data["suite"].startswith("unseen-topic")
    assert len(data["entries"]) == len(UNSEEN_TOPICS)
    assert "report" in data
    assert data["report"]["total"] == len(UNSEEN_TOPICS)


def test_unseen_topics_are_the_s34_list():
    topics = [t for t, _ in UNSEEN_TOPICS]
    for expected in ("noise-cancelling", "popcorn", "microwave", "ice",
                     "lift", "GPS", "mirrors", "barcode", "autofocus"):
        assert any(expected.lower() in t.lower() for t in topics), expected
