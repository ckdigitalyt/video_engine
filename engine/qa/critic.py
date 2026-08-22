"""Post-preview critic (JADE v0.3 §29).

After a preview render the critic inspects the ACTUAL output (QA report
+ composition report + explanation report) and returns:

    {
      "score": 0-100,
      "strengths": [...],
      "problems": [ {beat, problem, severity, repair}, ... ],
      "repair_actions": [ {beat, action, params}, ... ]
    }

Problems are tied to beats (§29).  The critic is deterministic and cheap:
it reads the same reports the gates produce, maps failures to the beats
that caused them, and proposes LOCAL repairs (§30) — never a full
regenerate.  It runs BEFORE any expensive rerender so a bad plan is
repaired at the planning level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# severity levels
SEV_LOW = "low"
SEV_MED = "medium"
SEV_HIGH = "high"


@dataclass
class Problem:
    beat: str
    problem: str
    severity: str = SEV_MED
    repair: str = ""

    def to_dict(self) -> dict:
        return {"beat": self.beat, "problem": self.problem,
                "severity": self.severity, "repair": self.repair}


@dataclass
class Critique:
    score: int = 100
    strengths: list[str] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    repair_actions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "strengths": list(self.strengths),
            "problems": [p.to_dict() for p in self.problems],
            "repair_actions": list(self.repair_actions),
        }


def _beat_duration(beat: dict) -> float:
    return float(beat.get("duration")
                 or (beat.get("end", 0) - beat.get("start", 0)) or 1.5)


def _worst_beats(visualspec: dict, key: str, limit: int = 3) -> list[str]:
    """Beat ids with the lowest explanation_score (worst first)."""
    scored = sorted(
        ((float(b.get("explanation_score", 0) or 0), b.get("beat_id", "?"))
         for b in visualspec.get("beats", [])),
        key=lambda t: t[0])
    return [bid for _, bid in scored[:limit]]


def critique_preview(visualspec: dict, qa_report: dict | None = None,
                     composition_report: dict | None = None,
                     explanation_report: dict | None = None) -> Critique:
    """Deterministic post-preview critique (§29).

    Combines the v2 QA report (frame visual/layout QA), the Phase B
    composition report (attention clarity) and the explanation report
    (§10/§13) into a 0-100 score with beat-tied problems + local
    repair actions (§30).
    """
    c = Critique(score=100)
    beats = visualspec.get("beats", [])
    md = visualspec.get("metadata", {}) or {}
    comp = composition_report or md.get("composition_report") or {}
    # Always recompute the explanation report from the ACTUAL beats: cached
    # planning-time reports go stale after local repair (§30), and scoring
    # is cheap and deterministic.  The passed-in report is honored only
    # when no beats are available to score.
    if beats:
        from engine.world.scoring import score_beatsheet
        expl = score_beatsheet(beats).to_dict()
    else:
        expl = explanation_report or md.get("explanation_report") or {}

    # ── strengths (what the plan already gets right) ───────────────────
    if expl.get("average_explanation_score", 0) >= 3.5:
        c.strengths.append(
            f"avg explanation {expl.get('average_explanation_score')} >= 3.5")
    if expl.get("text_dominance_ratio", 1.0) < 0.35:
        c.strengths.append(
            f"text-dominance {expl.get('text_dominance_ratio')} < 0.35")
    if comp.get("avg_focal_contrast", 0) >= 0.5:
        c.strengths.append(
            f"focal contrast {comp.get('avg_focal_contrast')} >= 0.5")
    if not c.strengths:
        c.strengths.append("plan is structurally complete")

    # ── frame-level problems (from the actual preview) ─────────────────
    fvq = (qa_report or {}).get("frame_visual_qa") or {}
    flq = (qa_report or {}).get("frame_layout_qa") or {}
    longest_static = fvq.get("longest_static_interval_s", 0.0)
    if longest_static >= 6.0:
        worst = _worst_beats(visualspec, "explanation_score")
        c.problems.append(Problem(
            beat=",".join(worst[:2]) or "all",
            problem=f"dead-air static interval {longest_static:.1f}s >= 6s",
            severity=SEV_HIGH,
            repair="add motion/camera to the weakest beats (worst "
                   "explanation scores first)"))
        c.repair_actions.append(
            {"beat": worst[0] if worst else "all",
             "action": "add_camera_motion",
             "params": {"static_threshold_s": 6.0}})
        c.score -= 15
    if flq.get("conflict_frames"):
        n = len(flq["conflict_frames"])
        c.problems.append(Problem(
            beat="all",
            problem=f"{n} frame(s) with overlapping objects (zone conflict)",
            severity=SEV_MED,
            repair="reduce simultaneous entities or spread zones"))
        c.repair_actions.append(
            {"beat": "all", "action": "reduce_object_overlap",
             "params": {"conflict_frames": n}})
        c.score -= 10

    # ── composition problems (attention clarity, §20-21) ───────────────
    # Aligned with gate_composition: focal-less beats are tolerated for
    # release/pause pacing up to max(1, 35% of beats); multiple-focal is
    # always a defect.
    n_beats = max(1, len(beats))
    focal_tolerance = max(1, int(round(n_beats * 0.35)))
    if comp.get("beats_with_multiple_focal"):
        for bid in comp["beats_with_multiple_focal"][:3]:
            c.problems.append(Problem(
                beat=bid, problem="multiple focal points in one beat",
                severity=SEV_MED,
                repair="demote secondary objects to supporting roles"))
            c.repair_actions.append(
                {"beat": bid, "action": "single_focal",
                 "params": {"keep": "primary"}})
            c.score -= 8
    no_focal = comp.get("beats_without_focal") or []
    if len(no_focal) > focal_tolerance:
        for bid in no_focal[:3]:
            c.problems.append(Problem(
                beat=bid, problem="no focal point (attention unclear)",
                severity=SEV_MED,
                repair="assign a clear focal object / camera target"))
            c.repair_actions.append(
                {"beat": bid, "action": "assign_focal",
                 "params": {"target": "hero_or_first_object"}})
            c.score -= 8
    if comp.get("avg_empty_area_ratio", 1.0) < 0.20:
        c.problems.append(Problem(
            beat="all", problem="frame density too high (avg empty < 0.20)",
            severity=SEV_LOW,
            repair="increase negative space, shrink object scale"))
        c.repair_actions.append(
            {"beat": "all", "action": "increase_negative_space",
             "params": {"min_empty": 0.20}})
        c.score -= 5

    # ── explanation problems (§10/§13), tied to the weakest beats ──────
    # Aligned with gate_explanation: individual low beats (hooks, kinetic
    # text — §14) are fine; flag only when the video-level criteria fail.
    per_beat = expl.get("per_beat") or []
    weak = [pb for pb in per_beat if float(pb.get("level", 5)) < 3]
    avg_expl = float(expl.get("average_explanation_score", 0.0))
    if expl.get("dominated_by_level_0_2"):
        c.problems.append(Problem(
            beat=",".join(_worst_beats(visualspec, "explanation_score", 2)),
            problem="video dominated by level 0-2 beats (decoration, not "
                    "explanation)",
            severity=SEV_HIGH,
            repair="give weak beats a semantic demonstration action"))
        c.repair_actions.append(
            {"beat": ",".join(_worst_beats(visualspec,
                                           "explanation_score", 2)),
             "action": "raise_explanation",
             "params": {"min_level": 3}})
        c.score -= 15
    elif avg_expl < 3.5 and weak:
        c.problems.append(Problem(
            beat=weak[0].get("beat_id", "?"),
            problem=f"avg explanation {avg_expl:.2f} < 3.5 — weakest beat "
                    f"explains at level {weak[0].get('level')} < 3",
            severity=SEV_MED,
            repair="replace decorative motion with a demonstrating action"))
        c.repair_actions.append(
            {"beat": weak[0].get("beat_id", "?"),
             "action": "raise_explanation",
             "params": {"min_level": 3}})
        c.score -= 8
    if expl.get("explanatory_dominated"):
        c.problems.append(Problem(
            beat="all",
            problem="support purposes dominate — visuals must explain (§13)",
            severity=SEV_HIGH,
            repair="convert emphasis/atmosphere beats to demonstrate/"
                   "illustrate/compare"))
        c.repair_actions.append(
            {"beat": "all", "action": "explanatory_redesign",
             "params": {"min_explanatory": 0.5}})
        c.score -= 10

    # ── hero QC problems (§10) ─────────────────────────────────────────
    hero = md.get("hero_mechanism") or {}
    if not hero.get("why_this_visual"):
        c.problems.append(Problem(
            beat=hero.get("target_beat", "?"),
            problem="hero mechanism lacks why_this_visual rationale (§12)",
            severity=SEV_HIGH,
            repair="revise hero: what should the viewer remember?"))
        c.score -= 10

    c.score = max(0, min(100, c.score))
    return c
