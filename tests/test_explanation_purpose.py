"""Phase D tests (§13): visual explanation scoring robust.

- every beat classifies into one of the 6 purposes
  (demonstrate/illustrate/compare/emphasize/transition/atmosphere)
- explanatory purposes dominate for the three §46 dev topics
- gate_explanation FAILs closed when support purposes dominate
- purpose classification is deterministic and vocabulary-safe
"""

from __future__ import annotations

import pytest

from engine.qa.gates import gate_explanation
from engine.visuals.world_director import build_visualspec
from engine.world.knowledge import build_world
from engine.world.scoring import (
    EXPLANATORY_PURPOSES,
    PURPOSE_ATMOSPHERE,
    PURPOSE_COMPARE,
    PURPOSE_DEMONSTRATE,
    PURPOSE_EMPHASIZE,
    PURPOSE_ILLUSTRATE,
    PURPOSE_TRANSITION,
    VISUAL_PURPOSES,
    classify_visual_purpose,
    score_beatsheet,
)


def _visualspec(topic: str) -> dict:
    return build_visualspec(topic, build_world(topic))


@pytest.mark.parametrize("topic", [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
])
def test_all_beats_have_valid_purpose(topic):
    vs = _visualspec(topic)
    report = score_beatsheet(vs["beats"])
    assert set(report.purpose_counts) <= set(VISUAL_PURPOSES)
    total = sum(report.purpose_counts.values())
    assert total == len(vs["beats"])


@pytest.mark.parametrize("topic", [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
])
def test_explanatory_purposes_dominate(topic):
    vs = _visualspec(topic)
    report = score_beatsheet(vs["beats"])
    assert report.explanatory_dominance >= 0.5, (
        f"{topic}: explanatory {report.explanatory_dominance:.2f} — "
        f"support classes dominate (§13)")


@pytest.mark.parametrize("topic", [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
])
def test_gate_explanation_passes_with_dominance(topic):
    vs = _visualspec(topic)
    g = gate_explanation(vs)
    assert g.passed, f"{topic}: {g.errors}"


def test_demonstrating_action_maps_to_demonstrate():
    beat = {"role": "explanation", "beat_id": "b1",
            "semantic_actions": [{"action": "interfere", "target": "c"}]}
    assert classify_visual_purpose(beat) == PURPOSE_DEMONSTRATE


def test_compare_action_maps_to_compare():
    beat = {"role": "explanation", "beat_id": "b1",
            "semantic_actions": [{"action": "compare", "target": "a"}]}
    assert classify_visual_purpose(beat) == PURPOSE_COMPARE


def test_concept_action_maps_to_illustrate():
    beat = {"role": "explanation", "beat_id": "b1",
            "semantic_actions": [{"action": "reveal", "target": "a"}]}
    assert classify_visual_purpose(beat) == PURPOSE_ILLUSTRATE


def test_camera_only_maps_to_emphasize():
    beat = {"role": "explanation", "beat_id": "b1",
            "semantic_actions": [{"action": "focus_on", "target": "a"}]}
    assert classify_visual_purpose(beat) == PURPOSE_EMPHASIZE


def test_transition_role_maps_to_transition():
    beat = {"role": "transition", "beat_id": "b1"}
    assert classify_visual_purpose(beat) == PURPOSE_TRANSITION


def test_atmosphere_role_maps_to_atmosphere():
    beat = {"role": "atmosphere", "beat_id": "b1"}
    assert classify_visual_purpose(beat) == PURPOSE_ATMOSPHERE


def test_gate_fails_when_support_purposes_dominate():
    vs = _visualspec("Why is the sky blue?")
    # flip every demonstrating beat into a camera-only emphasis beat
    for b in vs["beats"]:
        b["semantic_actions"] = [{"action": "focus_on", "target": "x"}]
        b["role"] = "transition"
    g = gate_explanation(vs)
    assert not g.passed
    assert any("support purposes" in e for e in g.errors)


def test_report_serializes_purpose_fields():
    vs = _visualspec("Why does popcorn pop?")
    report = score_beatsheet(vs["beats"])
    d = report.to_dict()
    assert "purpose_counts" in d
    assert "explanatory_dominance" in d
    assert "explanatory_dominated" in d
    for s in d["per_beat"]:
        assert s["purpose"] in VISUAL_PURPOSES
