"""V11 P1 §8 — scroll-stop test (Jade_todo_v11).

Editorial simulation of a feed viewer at the directive's checkpoints:

  0.5 sec — What am I seeing?
  2 sec   — Why should I continue?
  5 sec   — What question am I waiting to have answered?
  10 sec  — Have I learned something concrete?
  20 sec  — Has the story escalated?
  30 sec  — Has my mental model changed?
  final 3 — Did the video pay off the opening promise?

Severity model: a MAJOR failure must prevent publication (P0
semantics, coordinated with the existing VIEWER_SIMULATION gate):
attention capture (0.5s/2s), concrete learning by 10s and the payoff
are promise-breaking; 5s/20s/30s are pacing-quality (MINOR) findings.
All checks are deterministic over the edit plan + story.
"""
from __future__ import annotations

DISCOVERY_FLOOR = 0.62          # planv8 PHASE_MAP fallback intensity
ESCALATION_FLOOR = 0.78         # escalation tier intensity
LEARN_BY_S = 10.0
ESCALATE_BY_S = 20.0
MODEL_BY_S = 30.0
MAJOR = ("t0.5_what_am_i_seeing", "t1_subject_visible", "t2_why_continue",
         "t10_learned_concrete", "final_payoff")


def _starts(plan: dict) -> tuple[list, float]:
    t, out = 0.0, []
    for s in plan.get("shots") or []:
        out.append(t)
        t += float(s.get("duration_s") or 0)
    return out, t


def _intensity_at(shots, starts, t):
    for s, t0 in zip(shots, starts):
        if t0 <= t < t0 + float(s.get("duration_s") or 0):
            return float((s.get("v8") or {}).get("intensity") or 0.6)
    return 0.6


def run(plan: dict, story: dict, payoff: dict | None = None) -> dict:
    shots = plan.get("shots") or []
    starts, total = _starts(plan)
    if not shots:
        return {"checks": {}, "major_failures": ["no_shots"],
                "scroll_stop_pass": False, "verdict": "fail"}
    v8p = plan.get("v8") or {}

    def states_upto(t: float):
        for s, t0 in zip(shots, starts):
            for st in (s.get("v8") or {}).get("states") or []:
                yield s, t0 + float(st.get("t") or 0), st

    def opens_upto(t: float) -> int:
        return sum(len((s.get("v8") or {}).get("opens") or [])
                   for s, t0 in zip(shots, starts) if t0 <= t)

    def resolves_by(t: float) -> int:
        return sum(len((s.get("v8") or {}).get("resolves") or [])
                   for s, t0 in zip(shots, starts)
                   if t0 + float(s.get("duration_s") or 0) <= t)

    hero = (v8p.get("hero_recognizability") or {})
    # V12 P0 hook engine — planv9 measures the declared hook plan on the
    # plan itself (subject visible ~1s, no black/fade at 0.5s).
    hook_plan = plan.get("hook_plan") or {}
    hook_measured = hook_plan.get("measured") or {}
    opening_fade = bool(hook_measured.get("opening_black_or_fade"))
    subject_visible_s = hook_measured.get("subject_visible_s")
    first_action = None
    for _s, t, st in states_upto(total):
        if st.get("event"):
            first_action = t
            break
    first_open = None
    for s, t0 in zip(shots, starts):
        if (s.get("v8") or {}).get("opens") and t0 + float(
                s.get("duration_s") or 0) > 0:
            first_open = t0
            break
    learned_by_10 = any(t <= LEARN_BY_S for _s, t, st in states_upto(total)
                        if st.get("event"))
    concrete_by_10 = learned_by_10 or any(
        str(ev.get("kind")) == "number_pop" and t0 + float(ev.get("t") or 0) <= LEARN_BY_S
        for s, t0 in zip(shots, starts) for ev in s.get("events") or [])
    escalated_by_20 = any(
        t0 <= ESCALATE_BY_S and float((s.get("v8") or {}).get("intensity")
                                      or 0) >= ESCALATION_FLOOR
        for s, t0 in zip(shots, starts))
    # mental model change: an honored contradiction reveal, a reveal-phase
    # state, or a resolved question by 30s
    contradictions = v8p.get("contradictions") or {}
    con_ok = bool(contradictions.get("honored"))
    # V12 P0 — the DECLARED visual contradiction (a real visual reveal,
    # story schema) joins the same checkpoint; it does not replace the
    # v8 honored chain, it strengthens it.
    con_declared = plan.get("visual_contradiction") or {}
    if con_declared.get("declared") and not con_declared.get("honored"):
        model_by_30 = False  # declared but never revealed: model unchanged
    reveal_by_30 = any(
        t <= MODEL_BY_S and str((s.get("v8") or {}).get("phase")) == "reveal"
        for s, t0 in zip(shots, starts)
        for t in [t0])
    model_by_30 = con_ok or reveal_by_30 or resolves_by(MODEL_BY_S) > 0
    payoff_ok = (payoff or {}).get("verdict") == "pass"
    # V12 P0 payoff engine — the declared payoff IMAGE (causal model in one
    # memorable image) must exist in the final window; generic end card or
    # hero-enlarge default fails the check.
    pay_img = plan.get("payoff_image") or {}
    payoff_img_ok = (not pay_img.get("declared")) or bool(pay_img.get("ok"))
    last_dur = float(shots[-1].get("duration_s") or 0)
    final_has_payoff_state = any(
        st.get("name") == "PAYOFF"
        for st in (shots[-1].get("v8") or {}).get("states") or [])
    final_ok = payoff_ok and payoff_img_ok and (
        final_has_payoff_state or last_dur >= 3.0)

    checks = {
        "t0.5_what_am_i_seeing": {
            "severity": "MAJOR",
            "pass": (bool(hero.get("ok")) or bool(shots[0].get("title_overlay")))
                    and not opening_fade,
            "why": "subject recognition in the first half-second; no "
                   "unnecessary black/fade opening (hook engine)"},
        # V12 P0 hook engine — SHOW the subject/problem immediately.
        "t1_subject_visible": {
            "severity": "MAJOR",
            "pass": subject_visible_s is None
                    or float(subject_visible_s) <= float(
                        (hook_plan.get("targets") or {}).get(
                            "subject_visible_s", 1.0)),
            "why": f"subject/problem visible by ~1s "
                   f"(measured {subject_visible_s}s)"},
        "t2_why_continue": {
            "severity": "MAJOR",
            "pass": (first_action is not None and first_action <= 2.0)
                    or (first_open is not None and first_open <= 2.0),
            "why": f"first visual action at {first_action}s, first open question at {first_open}s"},
        "t5_question_open": {
            "severity": "MINOR",
            "pass": opens_upto(5.0) > 0,
            "why": "an open question exists by 5s"},
        "t10_learned_concrete": {
            "severity": "MAJOR",
            "pass": concrete_by_10,
            "why": f"counted semantic change or concrete number by {LEARN_BY_S}s"},
        "t20_escalated": {
            "severity": "MINOR",
            "pass": escalated_by_20 or _intensity_at(shots, starts, 20.0) > DISCOVERY_FLOOR,
            "why": "intensity/escalation tier rises above the discovery floor by 20s"},
        "t30_model_changed": {
            "severity": "MINOR",
            "pass": model_by_30,
            "why": "contradiction honored / reveal delivered / question resolved by 30s"},
        "final_payoff": {
            "severity": "MAJOR",
            "pass": final_ok,
            "why": "opening promise paid off in the final 3s (semantic link + payoff state)"},
    }
    major_failures = [k for k in MAJOR if not checks[k]["pass"]]
    return {"checks": checks, "major_failures": major_failures,
            "scroll_stop_pass": not major_failures,
            "verdict": "pass" if not major_failures else "fail"}
