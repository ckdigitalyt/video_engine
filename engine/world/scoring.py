"""Visual explanation scoring (JADE_TO_DO v0.3 §10, §27, §28).

Every planned beat is scored BEFORE rendering:

    0 = narration only
    1 = decorative
    2 = loosely illustrative
    3 = concept visualization
    4 = direct demonstration
    5 = highly informative transformation

Target: average >= 3.5 for a perceptual PASS.  A video dominated by level
0–2 beats must fail or be sent back to the VisualDirector.

Also computes the text-dominance ratio (§9, §28): the fraction of total
duration whose PRIMARY visual is text.  Target < 0.35 — kinetic text for
hooks, critical terms, numbers, short claims, reveals, emphasis; never
whole explanatory sentences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from engine.world.actions import (
    CAMERA_ACTIONS, MATH_VERIFIED_ACTIONS, resolve,
)
from engine.world.world_model import WorldState

# ── text-primary visual types (kinetic text / claims / questions) ────────
TEXT_PRIMARY_VISUALS: frozenset[str] = frozenset({
    "kinetic_title", "kinetic", "question", "claim", "cycle", "conclusion",
    "narrative", "text",
})

# Actions that directly demonstrate the mechanism (level 4-5 material).
_DEMONSTRATING_ACTIONS: frozenset[str] = frozenset({
    "orbit", "fall", "scatter", "collide", "miss", "converge", "oscillate",
    "flow", "branch", "merge", "assemble", "disassemble", "trace",
    "cross_section", "reveal_inside", "accelerate", "decelerate", "curve",
    "subtract", "sort", "measure",
    # §46 acoustics / phase-change
    "interfere", "cancel", "burst",
})

# Actions that visualize a concept but are not the mechanism itself.
_CONCEPT_ACTIONS: frozenset[str] = frozenset({
    "compare", "follow", "transform", "morph", "reveal", "count_down",
})

# ── visual-purpose taxonomy (§13): every beat is classified ───────────
# demonstrate / illustrate / compare are EXPLANATORY classes and must
# dominate; emphasize / transition / atmosphere are support classes that
# must never be the majority (spec §13: "visuals must explain, not
# decorate").
PURPOSE_DEMONSTRATE = "demonstrate"
PURPOSE_ILLUSTRATE = "illustrate"
PURPOSE_COMPARE = "compare"
PURPOSE_EMPHASIZE = "emphasize"
PURPOSE_TRANSITION = "transition"
PURPOSE_ATMOSPHERE = "atmosphere"

VISUAL_PURPOSES: tuple[str, ...] = (
    PURPOSE_DEMONSTRATE, PURPOSE_ILLUSTRATE, PURPOSE_COMPARE,
    PURPOSE_EMPHASIZE, PURPOSE_TRANSITION, PURPOSE_ATMOSPHERE,
)

# The classes that count as "explaining" (§13).
EXPLANATORY_PURPOSES: frozenset[str] = frozenset({
    PURPOSE_DEMONSTRATE, PURPOSE_ILLUSTRATE, PURPOSE_COMPARE,
})

# Support classes that are allowed but must not dominate.
SUPPORT_PURPOSES: frozenset[str] = frozenset(
    set(VISUAL_PURPOSES) - EXPLANATORY_PURPOSES)

# Beat roles -> typical purpose (fallback when actions are ambiguous).
_ROLE_PURPOSE: dict[str, str] = {
    "hook": PURPOSE_EMPHASIZE,
    "question": PURPOSE_EMPHASIZE,
    "pose_question": PURPOSE_EMPHASIZE,
    "payoff": PURPOSE_EMPHASIZE,
    "conclusion": PURPOSE_EMPHASIZE,
    "transition": PURPOSE_TRANSITION,
    "context": PURPOSE_ATMOSPHERE,
    "atmosphere": PURPOSE_ATMOSPHERE,
    "compare": PURPOSE_COMPARE,
    "comparison": PURPOSE_COMPARE,
    "demonstrate_transformation": PURPOSE_DEMONSTRATE,
    "discover_principle": PURPOSE_DEMONSTRATE,
    "show_convergence": PURPOSE_DEMONSTRATE,
    "explain_principle": PURPOSE_DEMONSTRATE,
    "explanation": PURPOSE_DEMONSTRATE,
    "simple_experiment": PURPOSE_ILLUSTRATE,
    "change_variable": PURPOSE_ILLUSTRATE,
    "observe": PURPOSE_ILLUSTRATE,
    "build_intuition": PURPOSE_ILLUSTRATE,
}

# Actions that are pure camera / emphasis work (support classes).
_SUPPORT_ACTIONS: frozenset[str] = frozenset({
    "focus_on", "zoom_into", "zoom_out_of", "highlight", "reveal",
    "cross_section", "reveal_inside",
})

_EXPLANATION_LEVELS = {
    0: "narration only",
    1: "decorative",
    2: "loosely illustrative",
    3: "concept visualization",
    4: "direct demonstration",
    5: "highly informative transformation",
}


def classify_visual_purpose(beat: dict) -> str:
    """§13 taxonomy: one of demonstrate/illustrate/compare/emphasize/
    transition/atmosphere, derived deterministically from role + actions."""
    role = str(beat.get("role", beat.get("intent", ""))).lower()
    actions = _actions_of(beat)
    if any(a in _DEMONSTRATING_ACTIONS for a in actions):
        return PURPOSE_DEMONSTRATE
    if any(a in ("compare", "sort") for a in actions):
        return PURPOSE_COMPARE
    if any(a in _CONCEPT_ACTIONS for a in actions):
        return PURPOSE_ILLUSTRATE
    if any(a in _SUPPORT_ACTIONS for a in actions):
        return PURPOSE_EMPHASIZE
    if role in ("transition",) or "transition" in role:
        return PURPOSE_TRANSITION
    if role in ("context", "atmosphere") or "atmosphere" in role:
        return PURPOSE_ATMOSPHERE
    if role and role in _ROLE_PURPOSE:
        return _ROLE_PURPOSE[role]
    # default by score: a demonstrating score is explanatory; text-only is
    # emphasis; otherwise illustrative.
    vtype = str(beat.get("visual_type", "")).lower()
    if vtype in TEXT_PRIMARY_VISUALS or actions == []:
        return PURPOSE_EMPHASIZE if vtype in TEXT_PRIMARY_VISUALS \
            else PURPOSE_ATMOSPHERE
    return PURPOSE_ILLUSTRATE


@dataclass
class BeatScore:
    beat_id: str
    level: int
    reason: str
    text_primary: bool = False
    purpose: str = PURPOSE_ILLUSTRATE        # §13 taxonomy


@dataclass
class ExplanationReport:
    scores: list[BeatScore] = field(default_factory=list)
    average: float = 0.0
    text_dominance_ratio: float = 0.0
    passed: bool = False
    dominated_by_low: bool = False
    # §13: purpose distribution + explanatory-dominance flag
    purpose_counts: dict[str, int] = field(default_factory=dict)
    explanatory_dominance: float = 0.0        # fraction of beats in
                                              # demonstrate/illustrate/compare
    explanatory_dominated: bool = False       # True when support classes win

    def to_dict(self) -> dict:
        return {
            "average_explanation_score": round(self.average, 3),
            "text_dominance_ratio": round(self.text_dominance_ratio, 3),
            "passed_avg_ge_3_5": self.passed,
            "dominated_by_level_0_2": self.dominated_by_low,
            "purpose_counts": dict(self.purpose_counts),
            "explanatory_dominance": round(self.explanatory_dominance, 3),
            "explanatory_dominated": self.explanatory_dominated,
            "per_beat": [s.__dict__ for s in self.scores],
        }


def _beat_duration(beat: dict) -> float:
    return float(beat.get("duration")
                 or (beat.get("end", 0) - beat.get("start", 0))
                 or 1.5)


def _actions_of(beat: dict) -> list[str]:
    out: list[str] = []
    for tf in beat.get("transformations", []):
        a = str(tf.get("type", ""))
        if a:
            out.append(a)
    for sa in beat.get("semantic_actions", []) or []:
        a = str(sa.get("action", sa.get("type", "")))
        if a:
            out.append(a)
    return out


def score_beat(beat: dict, world: Optional[WorldState] = None) -> BeatScore:
    """Deterministic per-beat visual explanation score (0–5)."""
    bid = str(beat.get("beat_id", "?"))
    vtype = str(beat.get("visual_type", "")).lower()
    actions = _actions_of(beat)
    objects = beat.get("objects", []) or []
    has_text_only = (vtype in TEXT_PRIMARY_VISUALS
                     or (vtype in ("", "narrative") and not objects))
    has_semantic_objects = any(
        isinstance(o, dict) and o.get("type") not in ("text",) and o.get("id")
        for o in objects)
    n_actions = len(actions)
    n_strong = sum(1 for a in actions if a in _DEMONSTRATING_ACTIONS)
    n_concept = sum(1 for a in actions if a in _CONCEPT_ACTIONS)
    has_camera = bool(beat.get("camera"))
    purpose = classify_visual_purpose(beat)

    # 0 — narration only
    if has_text_only and n_actions == 0 and not has_semantic_objects:
        return BeatScore(bid, 0, "narration-only beat (no semantic visuals)",
                         text_primary=True, purpose=purpose)
    # 1 — decorative
    if n_actions == 0 and has_semantic_objects is False:
        return BeatScore(bid, 1, "decorative motion, no semantic content",
                         text_primary=has_text_only, purpose=purpose)
    # 2 — loosely illustrative
    if n_actions == 0 or (n_actions == 1 and actions[0] in CAMERA_ACTIONS):
        if has_semantic_objects or has_text_only:
            return BeatScore(bid, 2, "illustrative still/diagram, no mechanism",
                             text_primary=has_text_only, purpose=purpose)
    # 5 — highly informative transformation: strong semantic action on a
    # real entity (or math-verified transform).
    if n_strong >= 1:
        if has_semantic_objects or n_strong >= 2:
            return BeatScore(bid, 5,
                             f"direct demonstration via {actions}",
                             purpose=purpose)
        return BeatScore(bid, 4, f"demonstration action {actions}",
                         purpose=purpose)
    # 4 — direct demonstration: verified math transform on a number/diagram
    if any(a in MATH_VERIFIED_ACTIONS for a in actions) and has_semantic_objects:
        return BeatScore(bid, 4, f"math-verified transformation {actions}",
                         purpose=purpose)
    # 3 — concept visualization: diagram + concept action + camera
    if n_concept >= 1 and (has_semantic_objects or has_camera):
        return BeatScore(bid, 3, f"concept visualization via {actions}",
                         purpose=purpose)
    # 2 fallback
    return BeatScore(bid, 2, "loosely illustrative",
                     text_primary=has_text_only, purpose=purpose)


def score_beatsheet(beats: list[dict],
                    world: Optional[WorldState] = None) -> ExplanationReport:
    """Score every beat; compute average + text-dominance ratio (§10, §9)."""
    if not beats:
        return ExplanationReport()
    scores = [score_beat(b, world) for b in beats]
    avg = sum(s.level for s in scores) / len(scores)
    total_dur = sum(_beat_duration(b) for b in beats)
    text_dur = sum(_beat_duration(b) for b, s in zip(beats, scores)
                   if s.text_primary)
    ratio = (text_dur / total_dur) if total_dur > 0 else 1.0
    low_count = sum(1 for s in scores if s.level <= 2)
    dominated = low_count > len(scores) / 2
    # §13: purpose distribution + explanatory dominance
    counts: dict[str, int] = {p: 0 for p in VISUAL_PURPOSES}
    for s in scores:
        counts[s.purpose] = counts.get(s.purpose, 0) + 1
    expl_count = sum(v for p, v in counts.items()
                     if p in EXPLANATORY_PURPOSES)
    expl_dom = expl_count / len(scores)
    support_dominated = expl_dom < 0.5
    return ExplanationReport(
        scores=scores,
        average=avg,
        text_dominance_ratio=round(ratio, 3),
        passed=avg >= 3.5,
        dominated_by_low=dominated,
        purpose_counts=counts,
        explanatory_dominance=round(expl_dom, 3),
        explanatory_dominated=support_dominated,
    )
