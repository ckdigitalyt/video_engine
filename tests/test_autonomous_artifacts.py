"""Phase A tests: spec-§5 artifact contract (15 named artifacts)."""

import json

from engine.cli.autonomous import run_autonomous

SPEC_ARTIFACTS = [
    "topic.json", "research.json", "facts.json", "story.json",
    "script.json", "world.json", "visual_plan.json", "hero.json",
    "beats.json", "shots.json", "visualspec.json", "audio_timeline.json",
    "qa.json", "repair_plan.json", "learning.json",
]


def test_compile_only_writes_all_spec_artifacts(tmp_path):
    out = tmp_path / "run"
    report = run_autonomous(
        "Why does popcorn pop?", out, render=False)
    present = [a for a in SPEC_ARTIFACTS if (out / a).exists()]
    missing = [a for a in SPEC_ARTIFACTS if a not in present]
    # render-gated artifacts (script/audio/qa) need a real render; the
    # pre-render contract must be complete
    pre_render = [a for a in SPEC_ARTIFACTS
                  if a not in ("script.json", "audio_timeline.json",
                               "qa.json")]
    missing_pre = [a for a in pre_render if not (out / a).exists()]
    assert not missing_pre, f"missing pre-render artifacts: {missing_pre}"
    # topic / research / facts must be meaningful JSON
    topic = json.loads((out / "topic.json").read_text())
    assert topic["topic"]
    facts = json.loads((out / "facts.json").read_text())
    assert isinstance(facts, list)
    beats = json.loads((out / "beats.json").read_text())
    assert beats
    shots = json.loads((out / "shots.json").read_text())
    assert len(shots) == len(beats)
    repair = json.loads((out / "repair_plan.json").read_text())
    assert repair["status"] == "not_run"
    learning = json.loads((out / "learning.json").read_text())
    assert learning["status"] == "not_run"


def test_compile_only_report_has_v03_fields(tmp_path):
    out = tmp_path / "run"
    report = run_autonomous(
        "How do noise-cancelling headphones work?", out, render=False)
    v27 = report.get("v03_report", report)
    assert v27["topic"]
    assert v27["representation_types"]
    assert v27["beat_count"] > 0
