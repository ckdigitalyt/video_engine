"""Phase E tests (§29-30, §36): post-preview critique + local repair.

- critique_preview returns score 0-100 + beat-tied problems/actions
- repair actions are LOCAL (only the named beat changes)
- apply_repair converges (weak beats get demonstrating actions)
- classify_outcome: PASS / REPAIR / REGENERATE / ABORT policy
"""

from __future__ import annotations

import copy

import pytest

from engine.qa.critic import critique_preview
from engine.qa.repair import (
    ABORT, PASS, REGENERATE, REPAIR,
    apply_repair, build_repair_plan_artifact, classify_outcome,
)
from engine.visuals.world_director import build_visualspec
from engine.world.knowledge import build_world
from engine.world.scoring import score_beatsheet


def _visualspec(topic: str) -> dict:
    return build_visualspec(topic, build_world(topic))


def _qa_report() -> dict:
    return {"frame_visual_qa": {"longest_static_interval_s": 0.5},
            "frame_layout_qa": {"conflict_frames": []}}


def test_critique_clean_plan_scores_high():
    vs = _visualspec("Why is the sky blue?")
    c = critique_preview(vs, _qa_report())
    assert 0 <= c.score <= 100
    assert c.score >= 85
    assert c.strengths


def test_critique_returns_beat_tied_problems():
    vs = _visualspec("Why is the sky blue?")
    # force a weak beat
    vs["beats"][-1]["semantic_actions"] = []
    vs["beats"][-1]["visual_type"] = "narrative"
    c = critique_preview(vs, _qa_report())
    if c.problems:
        for p in c.problems:
            assert p.beat  # problems must be tied to beats (§29)
            assert p.repair


def test_critique_dead_air_penalty():
    vs = _visualspec("Why does popcorn pop?")
    qa = {"frame_visual_qa": {"longest_static_interval_s": 9.0},
          "frame_layout_qa": {"conflict_frames": []}}
    c = critique_preview(vs, qa)
    assert any("dead-air" in p.problem for p in c.problems)
    assert any(ra["action"] == "add_camera_motion"
               for ra in c.repair_actions)


def test_critique_layout_conflict_penalty():
    vs = _visualspec("Why does popcorn pop?")
    qa = {"frame_visual_qa": {"longest_static_interval_s": 0.5},
          "frame_layout_qa": {"conflict_frames": ["f001", "f002"]}}
    c = critique_preview(vs, qa)
    assert any("overlap" in p.problem for p in c.problems)


def test_repair_is_local_single_beat():
    vs = _visualspec("Why is the sky blue?")
    # weaken several beats so the spec clearly fails the explanation gate
    for b in vs["beats"][-3:]:
        b["semantic_actions"] = []
        b["visual_type"] = "narrative"
    before = copy.deepcopy(vs)
    c = critique_preview(vs, _qa_report())
    assert c.repair_actions, "critic must propose repairs for a weak spec"
    plan = apply_repair(vs, c)
    assert plan.actions
    # untouched beats must be unchanged (local repair, §30)
    for i, b in enumerate(before["beats"]):
        if not any(a.beat == b["beat_id"] and a.applied
                   for a in plan.actions):
            assert b == vs["beats"][i]


def test_repair_raises_weak_beat_explanation():
    vs = _visualspec("Why is the sky blue?")
    vs["beats"][-1]["semantic_actions"] = []
    vs["beats"][-1]["visual_type"] = "narrative"
    c = critique_preview(vs, _qa_report())
    plan = apply_repair(vs, c)
    report = score_beatsheet(vs["beats"])
    assert report.average >= 3.5, "repair must restore explanation quality"


def test_classify_pass_repair_regenerate():
    clean = critique_preview(_visualspec("Why is the sky blue?"), _qa_report())
    assert classify_outcome(clean, qa_passed=True) == PASS

    # high-severity problem that survives -> REGENERATE (§36)
    vs = _visualspec("Why is the sky blue?")
    vs["metadata"]["hero_mechanism"]["why_this_visual"] = ""
    c = critique_preview(vs, _qa_report())
    assert classify_outcome(c, qa_passed=True) == REGENERATE

    # fact verification failure -> REGENERATE
    assert classify_outcome(clean, qa_passed=True,
                            fact_verified=False) == REGENERATE

    # technical failure -> REPAIR
    vs2 = _visualspec("Why does popcorn pop?")
    vs2["beats"][-1]["semantic_actions"] = []
    vs2["beats"][-1]["visual_type"] = "narrative"
    c2 = critique_preview(vs2, _qa_report())
    assert classify_outcome(c2, qa_passed=False) == REPAIR


def test_repair_plan_artifact_contract():
    vs = _visualspec("Why does popcorn pop?")
    c = critique_preview(vs, _qa_report())
    plan = apply_repair(vs, c)
    art = build_repair_plan_artifact(vs, c, plan)
    assert "critique" in art
    assert "outcome" in art
    assert art["outcome"] in (PASS, REPAIR, REGENERATE, ABORT)
    assert isinstance(art["actions"], list)
