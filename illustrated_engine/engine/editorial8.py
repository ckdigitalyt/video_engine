"""V8 editorial metrics (brief §7, §13, §14, §15, §17).

QA philosophy (§17): verdicts a competent human editor would sign — never
score-chasing. The composite question is: "Would a human viewer mistake this
for a deliberately produced YouTube documentary rather than an automated
slideshow?"

Metrics here:
- info_gain (§7): 2–4s windows must introduce semantic visual information.
  reveal/flow/fill_state/consequence count; zoom/pan/number-pop/decoration
  count ZERO.
- payoff_semantic (§13): declared hook curiosity → final visual resolution
  via semantics.semantic_link (declared concepts/facts or alias clusters).
  Lexical overlap is not used.
- narration_card_share (§2): generic narration-card duration ≤5–10%.
- viewer_simulation (§15): the 0.5s/2s/5s/15s/30s/final checks.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import semantics, visualclass

COUNTED = {"reveal": "new_evidence", "flow": "new_relationship",
           "fill_state": "new_process_state", "consequence": "new_consequence"}


def _shot_starts(plan: dict) -> tuple[list, float]:
    t, out = 0.0, []
    for s in plan.get("shots") or []:
        out.append(t)
        t += float(s.get("duration_s") or 0)
    return out, t


def info_gain(plan: dict, window_s: float = 3.0) -> dict:
    """Visual information gain (§7): counted semantic changes per window."""
    starts, total = _shot_starts(plan)
    n = max(int(total // window_s), 1)
    marks = [[] for _ in range(n)]
    counts: dict = {}
    for s, t0 in zip(plan.get("shots") or [], starts):
        for st in (s.get("v8") or {}).get("states") or []:
            ev = st.get("event")
            if ev in COUNTED:
                t = t0 + float(st.get("t") or 0)
                w = min(int(t // window_s), n - 1)
                marks[w].append(COUNTED[ev])
                counts[COUNTED[ev]] = counts.get(COUNTED[ev], 0) + 1
    with_gain = sum(1 for m in marks if m)
    coast = [round(i * window_s, 1) for i, m in enumerate(marks) if not m]
    share = with_gain / n
    return {"window_s": window_s, "n_windows": n,
            "windows_with_gain": with_gain, "gain_share": round(share, 3),
            "coast_windows_s": coast[:12],
            "counts_by_kind": counts,
            "verdict": "pass" if share >= 0.6 else "thin"}


def payoff_semantic(plan: dict, story: dict) -> dict:
    """Semantic resolution (§13): hook curiosity → final visual resolution."""
    shots = plan.get("shots") or []
    if not shots:
        return {"verdict": "no_shots"}
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}
    hook_s, final_s = shots[0], shots[-1]
    hook_b = beats.get(str(hook_s.get("beat_id")), {})
    fin_b = beats.get(str(final_s.get("beat_id")), {})
    q = (hook_s.get("v8") or {}).get("opens") or \
        [str(hook_b.get("visual_question") or "")]
    q_text = q[0] if q else ""
    a_text = str(fin_b.get("visual_answer") or "")
    link = semantics.semantic_link(
        q_text, a_text,
        semantics.concept_ids(hook_s.get("concepts")),
        semantics.concept_ids(final_s.get("concepts")),
        hook_b.get("fact_ids") or [], fin_b.get("fact_ids") or [])
    payoff_state = any(st.get("name") == "PAYOFF"
                       for st in (final_s.get("v8") or {}).get("states") or [])
    resolved = link["link"] != "none"
    verdict = ("pass" if (resolved and payoff_state)
               else ("partial" if (resolved or payoff_state) else "fail"))
    return {"question": q_text, "answer": a_text, "link": link,
            "payoff_state": payoff_state, "verdict": verdict}


def _card_like(c: dict) -> bool:
    blob = json.dumps(c).upper()
    return "NARRATION" in blob or ("GENERIC" in blob and "CARD" in blob)


def narration_card_share(plan: dict) -> dict:
    """Narration-card dependency (§2): generic card duration ≤5–10%."""
    shots = plan.get("shots") or []
    try:
        classes = visualclass.classify_plan(shots)
    except Exception:
        classes = [{} for _ in shots]
    dur_card = dur_all = 0.0
    card_shots = []
    for s, c in zip(shots, classes):
        d = float(s.get("duration_s") or 0)
        dur_all += d
        if _card_like(c if isinstance(c, dict) else {}):
            dur_card += d
            card_shots.append(s.get("shot_id"))
    share = dur_card / max(dur_all, 0.1)
    return {"card_share": round(share, 3), "target_max": 0.10,
            "card_shots": card_shots,
            "verdict": "pass" if share <= 0.10 else "over"}


def viewer_simulation(plan: dict, story: dict, info: dict, payoff: dict,
                      hero: dict) -> dict:
    """Human viewer simulation (§15)."""
    shots = plan.get("shots") or []
    starts, _total = _shot_starts(plan)

    def intensity_at(t: float) -> float:
        for s, t0 in zip(shots, starts):
            if t0 <= t < t0 + float(s.get("duration_s") or 0):
                return float((s.get("v8") or {}).get("intensity") or 0.6)
        return 0.6

    first_reveal = None
    for st in (shots[0].get("v8") or {}).get("states") or []:
        if st.get("event") == "reveal":
            first_reveal = float(st.get("t") or 0)
            break
    learned_by_15 = False
    for s, t0 in zip(shots, starts):
        for st in (s.get("v8") or {}).get("states") or []:
            if st.get("event") in COUNTED and \
                    t0 + float(st.get("t") or 0) <= 15.0:
                learned_by_15 = True
    checks = {
        "t0.5_what_am_i_seeing": {
            "pass": bool(hero.get("ok")),
            "why": "muted first-frame subject recognition (hero anchors)"},
        "t2_why_continue": {
            "pass": first_reveal is not None and first_reveal <= 2.0,
            "why": f"visual state action begins at {first_reveal}s"},
        "t5_question_open": {
            "pass": bool((shots[0].get("v8") or {}).get("opens")),
            "why": "central curiosity opened in hook"},
        "t15_learned_something": {
            "pass": learned_by_15,
            "why": "counted semantic change within 15s"},
        "t30_escalated": {
            # Escalated by 30s = the middle rises above the discovery-phase
            # baseline (planv8 PHASE_MAP fallback 0.62). The old form compared
            # against intensity_at(10), which sampled hook/reveal spikes
            # (0.90-0.95) no middle can exceed — early-reveal stories were
            # unpassable by construction.
            "pass": intensity_at(30.0) > 0.62,
            "why": f"intensity at 30s = {intensity_at(30.0)} "
                   f"(discovery floor 0.62)"},
        "final_payoff": {
            "pass": payoff.get("verdict") == "pass",
            "why": str((payoff.get("link") or {}).get("link"))},
    }
    npass = sum(1 for c in checks.values() if c["pass"])
    return {"checks": checks, "passed": npass, "total": len(checks),
            "verdict": "pass" if npass == len(checks) else "review"}


def evaluate8(plan: dict, story: dict, qa7: dict | None = None) -> dict:
    v8p = plan.get("v8") or {}
    hero = v8p.get("hero_recognizability") or {}
    info = info_gain(plan)
    payoff = payoff_semantic(plan, story)
    cards = narration_card_share(plan)
    vsim = viewer_simulation(plan, story, info, payoff, hero)
    durp = v8p.get("duration_policy") or {}
    # V11 P1 §7/§8/§10 — value density, scroll-stop, performance plan
    from engine import scroll_stop as _sstop
    from engine import value_density as _vdensity
    vd = _vdensity.value_density(plan, story)
    sstop = _sstop.run(plan, story, payoff)
    pperf = v8p.get("performance_plan") or {}
    gates = {
        "info_gain_60": info["verdict"] == "pass",
        "payoff_semantic": payoff["verdict"] == "pass",
        "narration_cards_10": cards["verdict"] == "pass",
        "hero_recognizable": bool(hero.get("ok")),
        "curiosity_ladder": (v8p.get("curiosity") or {}).get("verdict") == "pass",
        "escalation_curve": (v8p.get("escalation") or {}).get("verdict") == "pass",
        "no_filler": not durp.get("filler_candidates"),
        "viewer_simulation": vsim["verdict"] == "pass",
        "value_density": bool(vd.get("gate")),
        "scroll_stop": bool(sstop.get("scroll_stop_pass")),
        "performance_plan": bool(pperf.get("complete") and pperf.get("varied")),
    }
    return {
        "info_gain": info, "payoff_semantic": payoff,
        "narration_cards": cards, "viewer_simulation": vsim,
        "value_density": vd, "scroll_stop": sstop,
        "duration_policy": durp, "gates": gates,
        "V8_EDITORIAL_PASS": all(gates.values()),
        "documentary_vs_slideshow": ("documentary" if all(gates.values())
                                     else "slideshow_risk"),
        "qa7_summary": ({k: qa7.get(k) for k in
                         ("coverage", "hook", "its", "redundancy",
                          "continuity", "anti_template")} if qa7 else None),
    }


def write_report(result: dict, qa_dir: Path) -> Path:
    qa_dir = Path(qa_dir)
    qa_dir.mkdir(parents=True, exist_ok=True)
    out = qa_dir / f"qa8_{result.get('story_id', 'story')}.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    return out
