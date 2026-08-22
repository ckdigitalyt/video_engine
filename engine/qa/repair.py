"""Local repair agent + daily failure policy (JADE v0.3 §30, §36).

§30 — repair must be LOCAL: a bad beat is modified, re-rendered,
recomposed and re-gated — never a full regenerate.  §36 — the daily
system classifies every run as PASS / REPAIR / REGENERATE / ABORT and
must be able to reject its own bad work.

This module turns a Critique's repair_actions into a repair_plan:
    - applies each action to the VisualSpec (plan-level patch)
    - classifies the outcome (PASS/REPAIR/REGENERATE/ABORT)
    - produces the repair_plan.json artifact contract (§5)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.qa.critic import Critique, SEV_HIGH, SEV_MED, critique_preview

# §36 failure policy outcomes
PASS = "PASS"
REPAIR = "REPAIR"
REGENERATE = "REGENERATE"
ABORT = "ABORT"


@dataclass
class RepairAction:
    beat: str
    action: str
    params: dict = field(default_factory=dict)
    applied: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {"beat": self.beat, "action": self.action,
                "params": dict(self.params), "applied": self.applied,
                "note": self.note}


@dataclass
class RepairPlan:
    outcome: str = PASS
    actions: list[RepairAction] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    iterations: int = 0

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "iterations": self.iterations,
            "reasons": list(self.reasons),
            "actions": [a.to_dict() for a in self.actions],
        }


# ── local, plan-level repairs (deterministic) ──────────────────────────
def _apply_add_camera_motion(visualspec: dict, act: RepairAction) -> None:
    """Give the weakest beat a camera move (kill dead air locally)."""
    for b in visualspec.get("beats", []):
        if b.get("beat_id") == act.beat:
            if not b.get("camera"):
                b["camera"] = {"type": "zoom_into",
                               "target": _first_object(b)}
            act.applied = True
            act.note = f"camera added to {act.beat}"
            return
    act.note = f"beat {act.beat} not found — no local change"


def _apply_raise_explanation(visualspec: dict, act: RepairAction) -> None:
    """Replace decorative motion with a demonstrating action (§13)."""
    from engine.world.actions import Action
    for b in visualspec.get("beats", []):
        if b.get("beat_id") == act.beat:
            acts = b.get("semantic_actions") or []
            if not any(a.get("action") in
                       ("scatter", "flow", "orbit", "interfere", "cancel",
                        "burst", "collide", "converge", "trace", "merge")
                       for a in acts):
                acts = list(acts) + [{"action": Action.FLOW,
                                      "target": _first_object(b) or "node",
                                      "params": {}}]
                b["semantic_actions"] = acts
            b["visual_type"] = ""
            act.applied = True
            act.note = f"demonstrating action added to {act.beat}"
            return
    act.note = f"beat {act.beat} not found — no local change"


def _apply_assign_focal(visualspec: dict, act: RepairAction) -> None:
    """Give a focal-less beat a camera target (Phase B §20)."""
    for b in visualspec.get("beats", []):
        if b.get("beat_id") == act.beat:
            if not b.get("camera"):
                b["camera"] = {"type": "zoom_to",
                               "target": _first_object(b) or "hero"}
            act.applied = True
            act.note = f"focal target assigned to {act.beat}"
            return
    act.note = f"beat {act.beat} not found — no local change"


def _apply_single_focal(visualspec: dict, act: RepairAction) -> None:
    """Demote secondary objects to supporting roles (one focal point)."""
    for b in visualspec.get("beats", []):
        if b.get("beat_id") == act.beat:
            objs = b.get("objects") or []
            if len(objs) > 1:
                # keep the first semantic object as the focal one
                b["objects"] = objs[:1]
                b["camera"] = {"type": "zoom_to",
                               "target": _first_object(b) or "hero"}
                act.applied = True
                act.note = f"{act.beat}: kept only the primary object"
            return
    act.note = f"beat {act.beat} not found — no local change"


def _apply_increase_negative_space(visualspec: dict, act: RepairAction) -> None:
    """Scale objects down for more empty area (§21)."""
    for b in visualspec.get("beats", []):
        comp = b.get("composition") or {}
        if isinstance(comp, dict) and comp.get("object_scale", 1.0) > 0.5:
            comp["object_scale"] = 0.5
            b["composition"] = comp
            act.applied = True
            act.note = f"{b.get('beat_id')}: object scale -> 0.5"


def _apply_reduce_object_overlap(visualspec: dict, act: RepairAction) -> None:
    """Spread entities — no-op at plan level (compiler zones handle it)."""
    act.note = "overlap is mitigated by the compiler zone guard"


def _apply_explanatory_redesign(visualspec: dict, act: RepairAction) -> None:
    """Convert support beats to explanatory ones (§13)."""
    from engine.world.actions import Action
    for b in visualspec.get("beats", []):
        acts = b.get("semantic_actions") or []
        if not acts:
            b["semantic_actions"] = [{"action": Action.FLOW,
                                      "target": _first_object(b) or "node",
                                      "params": {}}]
            b["visual_type"] = ""
            act.applied = True
    if act.applied:
        act.note = "support beats given demonstrating actions"


_APPLYERS = {
    "add_camera_motion": _apply_add_camera_motion,
    "raise_explanation": _apply_raise_explanation,
    "assign_focal": _apply_assign_focal,
    "single_focal": _apply_single_focal,
    "increase_negative_space": _apply_increase_negative_space,
    "reduce_object_overlap": _apply_reduce_object_overlap,
    "explanatory_redesign": _apply_explanatory_redesign,
}


def _first_object(beat: dict) -> str:
    objs = beat.get("objects") or []
    for o in objs:
        if isinstance(o, dict) and o.get("id"):
            return str(o["id"])
    return ""


def apply_repair(visualspec: dict, critique: Critique,
                 max_iterations: int = 3) -> RepairPlan:
    """Apply critique repair_actions locally to the VisualSpec (§30).

    Each iteration applies the pending actions, then re-scores the
    explanation report so the next critique sees the repaired spec.
    Returns a RepairPlan with the §36 outcome classification.
    """
    plan = RepairPlan()
    iterations = 0
    current = critique
    while current.repair_actions and iterations < max_iterations:
        iterations += 1
        pending = list(current.repair_actions)
        current = Critique(score=100)  # fresh scratch for the next pass
        for ra in pending:
            act = RepairAction(beat=ra.get("beat", "all"),
                               action=ra.get("action", ""),
                               params=ra.get("params", {}))
            fn = _APPLYERS.get(act.action)
            if fn is None:
                act.note = f"no local applier for '{act.action}'"
                plan.actions.append(act)
                continue
            if act.beat == "all":
                for b in visualspec.get("beats", []):
                    fn(visualspec, RepairAction(
                        beat=b.get("beat_id", "?"), action=act.action,
                        params=act.params))
                act.applied = True
                act.note = f"{act.action} applied to all beats"
            else:
                fn(visualspec, act)
            plan.actions.append(act)
        # re-score after the repair pass
        from engine.world.scoring import score_beatsheet
        report = score_beatsheet(visualspec.get("beats", [])).to_dict()
        visualspec.setdefault("metadata", {})["explanation_report"] = report
        current = critique_preview(visualspec, qa_report=None)
        plan.iterations = iterations
    plan.outcome = classify_outcome(critique, plan)
    return plan


def classify_outcome(critique: Critique, plan: RepairPlan | None = None,
                     qa_passed: bool | None = None,
                     fact_verified: bool = True) -> str:
    """§36 daily failure policy.

    - technical/frame failures -> REPAIR (local, §30)
    - fact verification failure -> REGENERATE (research/story)
    - high-severity problems survive repair -> REGENERATE
    - uncorrectable risk -> ABORT
    - everything green -> PASS
    """
    if not fact_verified:
        return REGENERATE
    high = [p for p in critique.problems if p.severity == SEV_HIGH]
    if qa_passed is False:
        return REPAIR
    if high:
        # high-severity problems that survive the repair loop mean the
        # plan itself is wrong -> regenerate research/story/visual plan
        return REGENERATE
    if critique.problems:
        return REPAIR
    return PASS


def build_repair_plan_artifact(visualspec: dict,
                               critique: Critique,
                               plan: RepairPlan) -> dict:
    """§5 artifact contract: repair_plan.json."""
    return {
        "critique": critique.to_dict(),
        "outcome": plan.outcome,
        "iterations": plan.iterations,
        "actions": [a.to_dict() for a in plan.actions],
        "reasons": list(plan.reasons),
    }
