"""Wave-3 tests: budget reconciliation integration (§16) + planner.

Run: ./venv/bin/python -m pytest tests/test_v3_budget_integration.py -q
"""

from __future__ import annotations

import pytest

from engine.renderers.budget import reconcile_budget
from engine.v3.plan.planner import (
    default_budget,
    plan_shots,
    _skeleton_shots,
)


def _script(n_shots=8):
    beats = []
    roles = ["hook", "promise", "escalation", "escalation", "reveal",
             "payoff"]
    for i, role in enumerate(roles):
        beats.append({
            "beat_id": f"B{i + 1:02d}", "role": role,
            "goal": "g", "narration": f"This is narration sentence number "
                                      f"{i} for the {role} beat of the "
                                      f"video and it carries meaning.",
            "target_sec": 4.0, "claim_refs": []})
    return {"topic": "test topic", "beats": beats, "est_total_sec": 24.0}


STYLE = {"version": "v2", "style_name": "cinematic_documentary"}


def test_offline_plan_is_schema_valid_and_varied():
    plan = plan_shots(_script(), STYLE, use_llm=False, max_shots=8)
    from engine.validation.schema import validate as validate_schema

    for s in plan["shots"]:
        errs = validate_schema(s, "shot_v3")
        assert not errs, f"{s['shot_id']}: {errs}"
    report = plan["variety_report"]
    assert report["max_consecutive_same_renderer"] <= 3
    assert len(plan["shots"]) <= 8


def test_budget_reconcile_demotes_over_budget_renderer():
    from tests.test_v3_variety import shot

    shots = [shot("S01", "AI_IMAGE_MOTION"), shot("S02", "AI_IMAGE_MOTION"),
             shot("S03", "AI_IMAGE_MOTION"),
             shot("S04", "MOTION_CANVAS")]
    budget = {"ai_image_motion_shots": 1, "motion_canvas_shots": 10}
    recon = reconcile_budget(shots, budget)
    assert recon.assignments["S01"] == "AI_IMAGE_MOTION"
    demoted = [c for c in recon.changes if c["from"] == "AI_IMAGE_MOTION"]
    assert demoted, "over-budget shots should demote"
    counts = recon.bucket_counts
    assert counts["ai_image_motion_shots"] <= 1


def test_budget_protects_hero_shots():
    from tests.test_v3_variety import shot

    shots = [shot("S01", "AI_IMAGE_MOTION", hero=True),
             shot("S02", "AI_IMAGE_MOTION")]
    budget = {"ai_image_motion_shots": 1}
    recon = reconcile_budget(shots, budget)
    assert recon.assignments["S01"] == "AI_IMAGE_MOTION"


def test_budget_respects_availability():
    from tests.test_v3_variety import shot

    shots = [shot("S01", "AI_VIDEO")]
    budget = {"hero_ai_video_shots": 5}
    recon = reconcile_budget(shots, budget,
                             availability={"AI_VIDEO": False})
    assert recon.assignments["S01"] != "AI_VIDEO"


def test_skeleton_durations_cover_narration():
    script = _script()
    sk = _skeleton_shots(script, None)
    assert sk
    t = 0.0
    for s in sk:
        assert s["narration_start"] == pytest.approx(t, abs=0.2)
        t += s["duration_sec"]
    assert s["narration_end"] == pytest.approx(t, abs=0.2)


def test_default_budget_shape():
    b = default_budget()
    assert "hero_ai_video_shots" in b
    assert "pattern_interrupts" in b
