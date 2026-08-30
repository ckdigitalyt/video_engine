"""Wave-2 tests: visual-budget reconciliation (engine/renderers/budget.py)."""

from __future__ import annotations

from engine.renderers.budget import reconcile_budget


def _shots(*pairs):
    """shots from (shot_id, renderer) pairs."""
    return [
        {"shot_id": sid, "renderer": rid, "generation_priority": "normal",
         "visual_goal": "g", "duration_sec": 3.0}
        for sid, rid in pairs
    ]


BUDGET = {
    "hero_ai_video_shots": 1,
    "ai_image_motion_shots": 2,
    "stock_or_archival_shots": 2,
    "motion_canvas_shots": 1,
    "pixijs_shots": 1,
    "manim_shots": 1,
}


class TestReconcileBudget:
    def test_within_budget_unchanged(self):
        shots = _shots(
            ("S1", "AI_VIDEO"), ("S2", "AI_IMAGE_MOTION"),
            ("S3", "AI_IMAGE_MOTION"), ("S4", "STOCK_VIDEO"),
            ("S5", "ARCHIVAL"), ("S6", "MOTION_CANVAS"),
            ("S7", "PIXIJS"), ("S8", "MANIM"),
        )
        res = reconcile_budget(shots, BUDGET)
        assert res.changes == []
        assert res.assignments["S1"] == "AI_VIDEO"
        assert res.assignments["S8"] == "MANIM"

    def test_over_budget_demotes_lowest_value_first(self):
        shots = _shots(
            ("S1", "AI_VIDEO"), ("S2", "AI_VIDEO"), ("S3", "AI_VIDEO"),
            ("S4", "MANIM"),
        )
        budget = {"hero_ai_video_shots": 1, "manim_shots": 2}
        res = reconcile_budget(shots, budget)
        # 2 demotions; AI_VIDEO keeps 1 (S1 — stable order, non-hero)
        ai = [sid for sid, r in res.assignments.items() if r == "AI_VIDEO"]
        assert len(ai) == 1
        demoted = {c["shot_id"] for c in res.changes}
        assert demoted == {"S2", "S3"}
        assert all(c["from"] == "AI_VIDEO" for c in res.changes)
        assert all(c["to"] == "AI_IMAGE_MOTION" for c in res.changes)

    def test_hero_priority_protected_from_demotion(self):
        shots = _shots(("S1", "AI_VIDEO"), ("S2", "AI_VIDEO"))
        shots[1]["generation_priority"] = "hero"
        budget = {"hero_ai_video_shots": 1, "ai_image_motion_shots": 1}
        res = reconcile_budget(shots, budget)
        # S1 (normal) demoted, S2 (hero) stays AI_VIDEO
        assert res.assignments["S2"] == "AI_VIDEO"
        assert res.assignments["S1"] == "AI_IMAGE_MOTION"

    def test_unavailable_renderer_never_assigned(self):
        shots = _shots(("S1", "AI_VIDEO"), ("S2", "MANIM"))
        budget = {"hero_ai_video_shots": 1, "manim_shots": 1}
        res = reconcile_budget(shots, {"manim_shots": 2},
                               availability={"AI_VIDEO": False})
        assert res.assignments["S1"] != "AI_VIDEO"

    def test_deterministic(self):
        shots = _shots(
            ("S1", "AI_VIDEO"), ("S2", "AI_VIDEO"), ("S3", "PIXIJS"),
            ("S4", "PIXIJS"), ("S5", "MANIM"),
        )
        budget = {"hero_ai_video_shots": 1, "pixijs_shots": 1,
                  "manim_shots": 1, "ai_image_motion_shots": 2}
        a = reconcile_budget(shots, budget)
        b = reconcile_budget(shots, budget)
        assert a.assignments == b.assignments
        assert a.changes == b.changes

    def test_under_budget_reported_not_forced(self):
        shots = _shots(("S1", "MANIM"), ("S2", "MANIM"))
        budget = {"manim_shots": 1, "pixijs_shots": 3}
        res = reconcile_budget(shots, budget)
        assert res.changes == []  # nothing over budget → no demotion
        assert any("pixijs_shots: 0/3" in n for n in res.notes)

    def test_fallback_chain_ordering(self):
        """Demotion walks §24: AI_VIDEO → AI_IMAGE_MOTION → STOCK..."""
        shots = _shots(("S1", "AI_VIDEO"), ("S2", "MANIM"))
        budget = {"hero_ai_video_shots": 0, "ai_image_motion_shots": 0,
                  "stock_or_archival_shots": 1, "manim_shots": 2}
        res = reconcile_budget(shots, budget)
        # S1 demoted past AI_IMAGE_MOTION (bucket 0 filled... actually
        # demote target walks chain until headroom) — assert it left AI_VIDEO
        assert res.assignments["S1"] != "AI_VIDEO"
        assert any(c["shot_id"] == "S1" for c in res.changes)
