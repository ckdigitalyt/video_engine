"""V7 planner — editorial intelligence layer over planv5.

Wraps the frozen V6.2 planner and applies the V7 brief's editorial pass:

  P0-2   hook block: hook_claim / hook_visual / curiosity_gap / payoff;
         opening must show visual proof within 2s (works muted)
  P0-3   title policy: episode title as a compose overlay that fades out
         by ~2.5s (opt-in per story; new cards stop baking titles)
  P0-9   payoff validation on the final beat (authoring gate, reported)
  P0-10  anti-template: reads recent structural signatures; when the new
         plan is a structural clone, applies DELIBERATE variation
         (act-boundary dip transitions) — never random
  P1-4   concept registry + per-shot concept refs (authored in story.json)
  P1-5/6 choreography: long static beats get staggered evidence events
         (highlights / number pops) anchored on declared plate elements —
         same object -> transformation -> consequence, not new-slide narration
  P1-7   story_type recorded for grammar-aware authoring

Output plan is a schema superset: renders with `render5` unchanged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from engine import planv5
from engine import antitemplate
from engine.visualclass import classify_plan


# ------------------------------------------------------------------ P0-2 hook
def _hook_block(plan: dict, story: dict) -> dict:
    beats = story.get("beats", [])
    b0 = beats[0] if beats else {}
    last = beats[-1] if beats else {}
    shots = plan.get("shots", [])
    opening = shots[0] if shots else {}
    hook = {
        "claim": str(b0.get("claim") or ""),
        "visual": str(opening.get("evidence") or ""),
        "curiosity_gap": str(b0.get("visual_question") or ""),
        "payoff": str(last.get("claim") or ""),
        "muted_ok": bool(str(opening.get("evidence") or "").strip()),
    }
    plan["hook"] = hook
    return hook


# ------------------------------------------------------------- P1-7 story type
def _story_type(plan: dict, story: dict) -> str:
    st = str(story.get("story_type") or "").strip()
    if st:
        return st
    per = (plan.get("visual_grammar_plan") or {}).get("per_shot") or []
    funcs = " ".join(str(p.get("beat_function") or "") for p in per).upper()
    evs = " ".join(str(s.get("evidence") or "") for s in plan.get("shots", []))
    if "MAP" in evs.upper() or "GEOGRAPH" in funcs or "REGION" in funcs:
        return "geography"
    if "CHRONOLOGY" in funcs or "TIMELINE" in evs.upper() or "RECONSTRUCTION" in funcs:
        return "history"
    return "science_process"


# ------------------------------------------------------------------ P1-4 concepts
def _attach_concepts(plan: dict, story: dict) -> bool:
    cons = story.get("concepts")
    if not (isinstance(cons, list) and cons):
        plan["concepts"] = []
        return False
    plan["concepts"] = cons
    by_beat: dict = {}
    for c in cons:
        if not isinstance(c, dict):
            continue
        for bid in c.get("beats", []) or []:
            by_beat.setdefault(str(bid), []).append(
                {"id": c.get("id"), "verb": str(c.get("verb") or "present")})
    for s in plan.get("shots", []):
        refs = by_beat.get(str(s.get("beat_id")), [])
        if refs:
            s["concepts"] = refs
    return True


# ------------------------------------------------- P1-5/6 choreography
def _hold_of(kind: str, t: float, dur: float) -> float:
    return (min(2.6, dur - t) if kind == "number_pop"
            else min(2.8, dur - t))


def _choreograph(plan: dict, paths, story_id: str, v7: dict) -> None:
    """Long static beats (>=5s, <2 rect events, no kinetic layer) get
    staggered events anchored on the card's own declared elements."""
    from engine.planv5 import (_plate_manifest, _plate_el_to_card,
                               _clamp_card_rect)
    manifest = _plate_manifest(Path(paths.stories) / story_id)
    added_total = 0
    needs_states = []
    for s in plan.get("shots", []):
        dur = float(s.get("duration_s") or 0)
        if dur < 5.0:
            continue
        evs = s.get("events") or []
        rect_evs = [e for e in evs if (e.get("spec") or {}).get("rect")]
        if len(rect_evs) >= 2 or s.get("kinetic"):
            continue
        els = manifest.get(str(s.get("asset")), []) or []
        if not els:
            needs_states.append(s.get("shot_id"))
            continue
        busy = []
        for e in rect_evs:
            t0 = float(e.get("t", 0))
            busy.append((t0, t0 + _hold_of(str(e.get("kind")), t0, dur)))

        def free(t, hold):
            return all(t + hold < bs - 0.3 or t > be + 0.3 for bs, be in busy)

        cam = s.get("camera") or {}
        used_texts = {str((e.get("spec") or {}).get("text") or "") for e in rect_evs}
        added = 0

        def add(kind, t, el):
            nonlocal added, added_total
            if "cx" not in el or "cy" not in el:
                return False  # text-only element (parser couldn't evaluate position)
            hold = _hold_of(kind, t, dur)
            if hold < 1.0 or not free(t, hold):
                return False
            r = _clamp_card_rect(_plate_el_to_card(el, cam))
            if kind == "number_pop":
                spec = {"kind": "NUMBER_POP", "text": str(el.get("text") or ""),
                        "rect": r, "pulse": True}
            else:
                spec = {"rect": r, "pulse": True, "style": "circle"}
            s.setdefault("events", []).append(
                {"kind": kind, "t": round(t, 3), "spec": spec})
            busy.append((t, t + hold))
            added += 1
            added_total += 1
            return True

        # 1) number evidence from the narration, if a declared element carries it
        if len(rect_evs) + added < 2:
            cap_nums = set()
            for c in (s.get("captions") or []):
                if isinstance(c, dict):
                    cap_nums |= set(re.findall(r"\d+(?:\.\d+)?", str(c.get("text") or "")))
            if cap_nums:
                for el in els:
                    et = str(el.get("text") or "")
                    if et and et not in used_texts and any(n in et for n in cap_nums):
                        if add("number_pop", max(1.5, 0.45 * dur), el):
                            used_texts.add(et)
                        break
        # 2) highlight on a not-yet-used declared element (progressive reveal)
        if len(rect_evs) + added < 2:
            for el in els:
                et = str(el.get("text") or "")
                if et and et in used_texts:
                    continue
                t = (0.3 if not rect_evs else 0.62) * dur
                if add("highlight", t, el):
                    break
        if added:
            v7["actions"].append(
                f"{s['shot_id']}: +{added} choreography events on {dur:.1f}s static hold")
    if needs_states:
        v7["warnings"].append(
            "static beats without declared card elements (need state-variant "
            f"cards): {', '.join(map(str, needs_states))}")
    v7["choreography_events_added"] = added_total


# ------------------------------------------------------------------- P0-3 title
def _title_policy(plan: dict, story: dict, v7: dict) -> str:
    shots = plan.get("shots", [])
    if not shots:
        return "none"
    opening = shots[0]
    opts = story.get("v7") or {}
    if opts.get("title_overlay"):
        opening["title_overlay"] = {
            "text": str(story.get("title") or "").strip(),
            "fade_out_s": 2.5,
        }
        v7["actions"].append("opening episode title -> compose overlay, fades out by 2.5s")
        policy = "overlay_fade"
    elif str(opening.get("title") or "").strip():
        policy = "baked_opening_title"
    else:
        policy = "none"
    v7["title_policy"] = policy
    return policy


# ------------------------------------------------------------------ P0-10 anti-template
def _anti_template_adapt(plan: dict, story_id: str, v7: dict) -> dict:
    classes = classify_plan(plan.get("shots", []))
    sig = antitemplate.build_signature(plan, classes)
    recent = antitemplate.load_recent(exclude_story=story_id)
    comp = antitemplate.compare(sig, recent)
    # V11 P1 §3/P2 — planner-side cross-topic motif fingerprint: makes the
    # orange-circle/navy-strip/cream-panel reuse visible AT PLAN TIME so the
    # author can vary vocabulary or declare a semantic justification.
    motif = None
    story_dir = Path("stories") / str(story_id)
    if story_dir.exists():
        story = json.loads((story_dir / "story.json").read_text())
        sig["motif"] = antitemplate.motif_signature(story_dir, plan, story)
        motif = antitemplate.compare_motifs(sig, recent)
    if comp.get("verdict") != "template_clone":
        v7["anti_template"] = {"action": "none", "verdict": comp.get("verdict"),
                               "motif": motif}
        return v7["anti_template"]
    # Deliberate variation: dip-to-white at act boundaries (beat function
    # changes) — a chaptering choice, not randomness.
    per = (plan.get("visual_grammar_plan") or {}).get("per_shot") or []
    func_by_id = {str(p.get("shot_id")): str(p.get("beat_function") or "") for p in per}
    prev, dips = None, 0
    for s in plan.get("shots", []):
        f = func_by_id.get(str(s.get("shot_id")), "")
        if prev and f and f != prev and dips < 2:
            s["transition_in"] = "dip_to_white"
            dips += 1
        prev = f or prev
    classes2 = classify_plan(plan.get("shots", []))
    sig2 = antitemplate.build_signature(plan, classes2)
    comp2 = antitemplate.compare(sig2, recent)
    v7["anti_template"] = {"action": "act_boundary_dips" if dips else "none",
                           "dips": dips, "verdict_before": comp.get("verdict"),
                           "verdict_after": comp2.get("verdict"),
                           "motif": motif}
    return v7["anti_template"]


# ------------------------------------------------------------------- P0-9 payoff
def _validate_payoff(plan: dict, story: dict, v7: dict) -> None:
    from engine import editorial7
    classes = classify_plan(plan.get("shots", []))
    pay = editorial7.payoff_score(plan, story, classes)
    hook = editorial7.hook_score(plan, story, classes)
    v7["payoff_check"] = {"score": pay["score"], "gate_pass": pay["gate_payoff_70"],
                          "hook_overlap": pay["hook_overlap"],
                          "new_fact_ratio": pay["new_fact_ratio"]}
    v7["hook_check"] = {"score": hook["score"]}
    if not pay["gate_payoff_70"]:
        v7["warnings"].append(
            f"payoff {pay['score']}/100 < 70 — the final beat must resolve the "
            "curiosity gap (authoring fix, not a planner patch)")


# --------------------------------------------------------------------- driver
def make_edit_plan_v7(paths, story_id: str, out_name: str = "edit_plan.json"):
    plan, rep = planv5.make_edit_plan_v5(paths, story_id)
    story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
    v7: dict = {"story_id": story_id, "actions": [], "warnings": []}

    hook = _hook_block(plan, story)
    plan["story_type"] = _story_type(plan, story)
    concepts_attached = _attach_concepts(plan, story)
    _choreograph(plan, paths, story_id, v7)
    title_policy = _title_policy(plan, story, v7)
    anti = _anti_template_adapt(plan, story_id, v7)
    _validate_payoff(plan, story, v7)

    plan["v7"] = {
        "planner": "v7.0",
        "story_type": plan["story_type"],
        "hook_present": bool(hook["claim"] and hook["curiosity_gap"]),
        "concepts_authored": concepts_attached,
        "title_policy": title_policy,
        "anti_template": anti,
        "choreography_events_added": v7.get("choreography_events_added", 0),
        "payoff_check": v7["payoff_check"],
        "actions": v7["actions"],
    }
    out = Path(paths.build) / out_name
    out.write_text(json.dumps(plan, indent=1) + "\n")
    return plan, v7
