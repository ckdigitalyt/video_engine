"""Phase H tests (§33): regression suite.

- all canonical topics plan + pass QA through the autonomous
  program (no manual storyboard)
- §46 grammar diversity: the topics produce distinct
  representations + hero visualizations
- benchmark.json + summary (APVR) written correctly
- compare_baseline() flags silent regression

Collatz is a known gap (hero demonstration below §10 threshold) and is
intentionally NOT part of the passing set.
"""

from __future__ import annotations

import json

import pytest

from engine.benchmark.suite import (
    REGRESSION_TOPICS,
    compare_baseline,
    run_regression,
    run_single,
    summarize,
    write_benchmark,
)


def test_all_topics_plan_and_pass_qa(tmp_path):
    entries = run_regression(out_root=tmp_path)
    assert len(entries) == 4
    for e in entries:
        assert e.qa_passed, f"{e.topic}: {e.errors}"
        assert e.explanation_score >= 3.5, (
            f"{e.topic}: explanation {e.explanation_score} < 3.5")
        assert e.text_dominance < 0.35, (
            f"{e.topic}: text dominance {e.text_dominance}")
        assert e.hero_visualization, f"{e.topic}: no hero"
        assert not e.failures, f"{e.topic}: {e.failures}"


def test_grammar_diversity_across_topics():
    entries = run_regression()
    reps = {e.representation for e in entries}
    heroes = {e.hero_visualization for e in entries}
    # §46: the engine must choose DIFFERENT visual grammars per topic
    assert len(reps) >= 3, f"representations too uniform: {reps}"
    assert len(heroes) >= 4, f"hero visualizations too uniform: {heroes}"


def test_summary_apvr():
    entries = run_regression()
    s = summarize(entries)
    assert s["topics"] == 4
    assert 0.0 <= s["apvr"] <= 1.0
    assert "failed_topics" in s
    assert "representations" in s


def test_benchmark_json_written(tmp_path):
    entries = run_regression(out_root=tmp_path)
    p = write_benchmark(entries, out_root=tmp_path)
    assert p.name == "benchmark.json"
    data = json.loads(p.read_text())
    assert data["suite"].startswith("regression")
    assert len(data["entries"]) == 4
    assert "summary" in data
    assert data["summary"]["apvr"] == 1.0


def test_run_single_persists_artifacts(tmp_path):
    e = run_single("Why is the sky blue?", "sky_blue", out_root=tmp_path)
    assert (tmp_path / "sky_blue" / "visualspec.json").exists()
    assert (tmp_path / "sky_blue" / "benchmark_entry.json").exists()


def test_compare_baseline_no_regression(tmp_path):
    entries = run_regression(out_root=tmp_path)
    p = write_benchmark(entries, out_root=tmp_path)
    notes = compare_baseline(entries, baseline_path=p)
    assert notes == [] or all("baseline" not in n for n in notes)


def test_compare_baseline_flags_regression(tmp_path):
    entries = run_regression(out_root=tmp_path)
    p = write_benchmark(entries, out_root=tmp_path)  # good baseline
    # simulate a regression in the CURRENT run (baseline stays good)
    import copy
    bad = [copy.deepcopy(e) for e in entries]
    bad[0].qa_passed = False
    bad[0].explanation_score = 2.0
    notes = compare_baseline(bad, baseline_path=p)
    assert any("REGRESSION" in n for n in notes)


def test_regression_topics_are_canonical():
    slugs = [s for _, s in REGRESSION_TOPICS]
    assert set(slugs) == {"kaprekar", "satellite_orbit",
                          "mcgurk", "sky_blue"}
    # known gap, deliberately excluded (§10 hero demonstration)
    assert "collatz" not in slugs
