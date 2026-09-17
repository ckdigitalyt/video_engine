"""V7 editorial metric suite (brief P0-1/2/9/11, P1-4/5/6/10).

Spec-level, deterministic metrics computed from the edit plan + story JSON.
No pixel guessing: the plan declares what is on screen; if it declares no
evidence, there is none.  Frame-level technical gates stay in qa5full.

Outputs (per story): build/qa/qa7_<story>.json + the extended report block.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from engine.visualclass import classify_plan
from engine import antitemplate

STOP = set("""a an the and or but if then than that this these those of to in on at
by for with from as is are was were be been being it its it's their there here
what how why when where which who whom whose not no yes up down out over under
into onto about across after before between during through very really just
also too so such own same can could will would should shall may might must do
does did done has have had having get gets got make makes made one two three""".split())

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _stem(w: str) -> str:
    for suf in ("ies", "ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text: str) -> list:
    return [_stem(t) for t in TOKEN_RE.findall(str(text or "").lower())
            if t not in STOP and not t.isdigit()]


# ---------------------------------------------------------------- P0-1 gates
def coverage_metrics(shots: list, classes: list) -> dict:
    total = sum(float(s.get("duration_s") or 0) for s in shots) or 1.0
    d = {k: 0.0 for k in ("evidence", "cinematic", "breathing", "blur")}
    for s, c in zip(shots, classes):
        dur = float(s.get("duration_s") or 0)
        if c["is_evidence"]:
            d["evidence"] += dur
        if c["is_cinematic"]:
            d["cinematic"] += dur
        if c["is_breathing"]:
            d["breathing"] += dur
        if c["is_generic_blur"]:
            d["blur"] += dur
    ev, cin = d["evidence"] / total * 100, d["cinematic"] / total * 100
    out = {
        "evidence_pct": round(ev, 1), "cinematic_pct": round(cin, 1),
        "breathing_pct": round(d["breathing"] / total * 100, 1),
        "generic_blur_pct": round(d["blur"] / total * 100, 1),
        "evidence_plus_cinematic_pct": round(ev + cin, 1),
    }
    out["gate_evidence_cinematic_80"] = out["evidence_plus_cinematic_pct"] >= 80.0
    out["gate_breathing_20"] = out["breathing_pct"] <= 20.0
    out["gate_blur_10"] = out["generic_blur_pct"] <= 10.0
    return out


# ------------------------------------------------------------------- P0-2 hook
def hook_score(plan: dict, story: dict, classes: list) -> dict:
    shots = plan["shots"]
    beats = story.get("beats", [])
    b0 = beats[0] if beats else {}
    hook = plan.get("hook") or {}
    hook_claim = hook.get("claim") or b0.get("claim") or ""
    gap = hook.get("curiosity_gap") or b0.get("visual_question") or ""
    payoff_decl = hook.get("payoff") or (beats[-1].get("function") == "PAYOFF" if beats else False)
    opening = shots[0] if shots else {}
    opening_class = classes[0] if classes else {}

    s01 = shots[0] if shots else {}
    proof_events = [e for e in (s01.get("events") or [])
                    if float(e.get("t", 99)) <= 2.0
                    and str(e.get("kind")) in ("number_pop", "highlight", "annotation",
                                               "callout", "label", "quantitative")]
    hook_visual_ok = bool(opening_class.get("is_evidence")) and (
        bool(proof_events) or bool(hook.get("visual")) or str(s01.get("evidence") or "").strip() != "")
    early_gap = bool(re.search(r"\?|\b(what|how|why|but|however|impossible|never)\b",
                               str(b0.get("narration") or ""), re.I)) or bool(gap)

    parts = {
        "hook_claim_present": 20.0 if hook_claim else 0.0,
        "hook_visual_within_2s": 30.0 if hook_visual_ok else 0.0,
        "curiosity_gap_immediate": 30.0 if early_gap else 0.0,
        "payoff_declared": 20.0 if payoff_decl else 0.0,
    }
    score = round(sum(parts.values()), 1)
    return {
        "hook_claim": hook_claim, "curiosity_gap": gap,
        "hook_visual": hook.get("visual") or str(s01.get("evidence") or "")[:120],
        "opening_proof_events_le2s": len(proof_events),
        "components": parts, "score": score, "gate_hook_70": score >= 70.0,
    }


# ------------------------------------------------------- P1-5 transformation
_ANNOT_KINDS = {"number_pop", "highlight", "pulse", "label", "callout"}


def its_score(shots: list, classes: list) -> dict:
    per = []
    prev = None
    for i, (s, c) in enumerate(zip(shots, classes)):
        if i == 0:
            per.append({"shot_id": s.get("shot_id"), "strength": None,
                        "note": "opening"})
            prev = s
            continue
        dims = {}
        dims["new_asset"] = (s.get("asset") != prev.get("asset")) if prev else True
        dims["new_evidence_structure"] = (
            str(s.get("evidence_type")) != str(prev.get("evidence_type"))
            or str(s.get("visual_mode")) != str(prev.get("visual_mode")))
        k_new = (s.get("kinetic") or {}).get("type") if isinstance(s.get("kinetic"), dict) else s.get("kinetic")
        k_old = (prev.get("kinetic") or {}).get("type") if isinstance(prev.get("kinetic"), dict) else prev.get("kinetic")
        dims["new_kinetic"] = bool(k_new) and k_new != k_old
        dims["comparison"] = str(s.get("role")).upper() in ("COMPARISON", "COMPARE") \
            or str(s.get("visual_mode")).upper() in ("COMPARE", "SPLIT", "COMPARISON")
        # V7 concept verbs (state changes); v5 plans have no concept refs
        dims["concept_state_change"] = bool(_concept_verbs(s))
        # number-pop-only beats never count (brief P1-5)
        evs = [str(e.get("kind")) for e in (s.get("events") or [])]
        only_annotation = evs and all(k in _ANNOT_KINDS for k in evs) \
            and not any(dims.values())
        strength = min(1.0, 0.5 * dims["new_asset"]
                       + 0.5 * dims["new_evidence_structure"]
                       + 0.3 * dims["new_kinetic"]
                       + 0.2 * dims["comparison"]
                       + 0.5 * dims["concept_state_change"])
        if only_annotation:
            strength = 0.0
        per.append({"shot_id": s.get("shot_id"),
                    "strength": round(strength, 2), "dims": dims})
        prev = s
    scored = [(float(s.get("duration_s") or 0), p["strength"] or 0.0)
              for s, p in zip(shots[1:], per[1:])]
    total = sum(d for d, _ in scored) or 1.0
    mean = sum(d * st for d, st in scored) / total
    share = sum(d for d, st in scored if st >= 0.5) / total
    return {"per_beat": per, "mean_strength": round(mean, 3),
            "transformed_share": round(share, 3),
            "gate_its_share_50": share >= 0.5}


def _concept_verbs(shot: dict) -> list:
    cons = shot.get("concepts")
    if not isinstance(cons, list):
        return []
    verbs = set()
    for c in cons:
        if isinstance(c, dict):
            verbs.add(str(c.get("verb") or c.get("action") or "").lower())
    return {v for v in verbs if v}


# ---------------------------------------------------------- P1-6 redundancy
def _event_sig(s: dict) -> tuple:
    """Choreography signature: event kinds with normalized timings.  A shot
    with staggered reveals is a progressive visual, not a static hold."""
    dur = float(s.get("duration_s") or 0) or 1.0
    evs = s.get("events") or []
    sig = tuple(sorted((str(e.get("kind")), round(float(e.get("t", 0)) / dur, 1))
                       for e in evs))
    return sig


def _fingerprint(s: dict, c: dict) -> tuple:
    cam = s.get("camera") or {}
    kin = s.get("kinetic")
    kin_t = kin.get("type") if isinstance(kin, dict) else kin
    return (s.get("asset"), c["primary"], str(s.get("visual_mode")),
            round(float(cam.get("to_scale") or cam.get("from_scale") or 1.0), 2),
            round(float(cam.get("cx") or 0.5), 2), round(float(cam.get("cy") or 0.5), 2),
            str(kin_t), _event_sig(s))


def redundancy(shots: list, classes: list) -> dict:
    """Rolling 5s windows: narration changes but visual fingerprint constant."""
    t = 0.0
    timeline = []
    for s, c in zip(shots, classes):
        dur = float(s.get("duration_s") or 0)
        timeline.append((t, t + dur, s, c, _fingerprint(s, c)))
        t += dur
    total = t or 1.0
    win, step, redundant = 5.0, 2.5, 0.0
    flags = []
    w0 = 0.0
    while w0 < total - 0.5:
        w1 = min(w0 + win, total)
        seg = [x for x in timeline if x[0] < w1 - 1e-6 and x[1] > w0 + 1e-6]
        if seg:
            fps = {x[4] for x in seg}
            texts = {str(cap.get("text") or "").strip()
                     for x in seg for cap in (x[2].get("captions") or [])
                     if isinstance(cap, dict) and cap.get("text")}
            # a shot with >=2 staggered events is choreographed: the visual
            # genuinely changes inside the window (progressive reveal)
            choreographed = any(len(x[4][7]) >= 2 for x in seg)
            if len(fps) == 1 and len(texts) >= 2 and not choreographed:
                redundant += w1 - w0
                flags.append({"window": [round(w0, 1), round(w1, 1)],
                              "shots": [x[2].get("shot_id") for x in seg],
                              "kind": "static_visual_narration_changes"})
            elif all(x[3]["is_generic_blur"] for x in seg) and len(seg) >= 2:
                redundant += w1 - w0
                flags.append({"window": [round(w0, 1), round(w1, 1)],
                              "shots": [x[2].get("shot_id") for x in seg],
                              "kind": "consecutive_blur_cards"})
        w0 += step
    pct = redundant / total * 100
    return {"redundant_pct": round(pct, 1), "flags": flags[:12],
            "n_flags": len(flags), "gate_redundancy_25": pct <= 25.0}


# ------------------------------------------------------- P1-4 continuity
def continuity_score(shots: list, classes: list) -> dict:
    seen_assets, seen_concepts = set(), set()
    linked_d, total_d = 0.0, 0.0
    per = []
    for s, c in zip(shots, classes):
        dur = float(s.get("duration_s") or 0)
        total_d += dur
        refs = s.get("concepts") if isinstance(s.get("concepts"), list) else []
        ref_ids = {str(x.get("id")) for x in refs if isinstance(x, dict) and x.get("id")}
        link = None
        if ref_ids and (ref_ids & seen_concepts):
            link = "concept_reuse"
        elif s.get("asset") and s.get("asset") in seen_assets:
            link = "asset_reuse"
        else:
            et = set(tokens(str(s.get("evidence"))))
            if et & _core_terms:
                link = "subject_term_reprise"
        if link:
            linked_d += dur
        per.append({"shot_id": s.get("shot_id"), "link": link})
        seen_assets.add(s.get("asset"))
        seen_concepts |= ref_ids
    share = linked_d / (total_d or 1.0)
    return {"per_shot": per, "linked_share": round(share, 3),
            "gate_continuity_50": share >= 0.5}


_core_terms = set()


def _set_core_terms(story: dict):
    terms = set()
    for b in story.get("beats", []):
        terms |= set(tokens(json.dumps(b)))
    terms |= set(tokens(str(story.get("title") or "")))
    _core_terms.clear()
    _core_terms.update(terms)


# ------------------------------------------------------------- P0-9 payoff
def payoff_score(plan: dict, story: dict, classes: list) -> dict:
    shots = plan["shots"]
    beats = story.get("beats", [])
    last_s, last_b = shots[-1] if shots else {}, beats[-1] if beats else {}
    first_b = beats[0] if beats else {}
    is_payoff = str(last_s.get("role")).upper() == "PAYOFF" \
        or str(last_b.get("function")).upper() == "PAYOFF" \
        or bool(last_s.get("end_card"))
    gap_terms = set(tokens(first_b.get("visual_question") or "")) | \
        set(tokens(first_b.get("narration") or "")) | \
        set(tokens((plan.get("hook") or {}).get("curiosity_gap") or ""))
    payoff_text = " ".join([str(last_b.get("narration") or ""),
                            str(last_s.get("purpose") or ""),
                            str(last_s.get("claim") or "")])
    pay_terms = set(tokens(payoff_text))
    resolves = (len(gap_terms & pay_terms) / len(gap_terms)) if gap_terms else 0.0
    early_terms = set()
    for b in beats[:-1]:
        early_terms |= set(tokens(str(b.get("narration") or "")))
    final_terms = set(tokens(str(last_b.get("narration") or "")))
    new_ratio = (len(final_terms - early_terms) / len(final_terms)) if final_terms else 0.0
    final_visual_strong = bool(classes[-1]["is_evidence"] or classes[-1]["is_cinematic"]) \
        if classes else False
    parts = {
        "payoff_beat": 30.0 if is_payoff else 0.0,
        "resolves_hook": round(40.0 * min(1.0, resolves * 2), 1),
        "no_new_fact": round(30.0 * (1.0 if new_ratio <= 0.45 else max(0.0, 1.4 - new_ratio * 1.6)), 1),
    }
    score = round(sum(parts.values()) * (1.0 if final_visual_strong else 0.85), 1)
    return {"is_payoff_beat": is_payoff, "hook_overlap": round(resolves, 2),
            "new_fact_ratio": round(new_ratio, 2),
            "final_visual_strong": final_visual_strong,
            "components": parts, "score": score, "gate_payoff_70": score >= 70.0}


# ------------------------------------------------- P0-11 human editor test
def human_editor_test(coverage: dict, hook: dict, its: dict, red: dict,
                      cont: dict, payoff: dict, anti: dict, shots: list) -> dict:
    seq = [c["primary"] for c in classify_plan(shots)]
    periodic = len(seq) >= 6 and all(seq[i] == seq[i % 2] for i in range(len(seq)))
    q = {}
    q["q1_slideshow"] = {"answer": not (its["transformed_share"] >= 0.5
                                        and red["redundant_pct"] <= 25.0
                                        and not periodic),
                         "basis": {"its_share": its["transformed_share"],
                                   "redundancy_pct": red["redundant_pct"],
                                   "periodic_sequence": periodic}}
    q["q2_every_beat_meaningful"] = {"answer": coverage["gate_evidence_cinematic_80"],
                                     "basis": {"ev_cin_pct": coverage["evidence_plus_cinematic_pct"]}}
    q["q3_visual_explains_sentence"] = {"answer": None,
                                        "basis": {"evidence_pct": coverage["evidence_pct"]},
                                        "note": "vision-assisted check stays in qa5full subject gate"}
    q["q4_hook_2s"] = {"answer": hook["gate_hook_70"], "basis": {"hook_score": hook["score"]}}
    q["q5_genuine_transformation"] = {"answer": its["transformed_share"] >= 0.6,
                                      "basis": {"share": its["transformed_share"]}}
    q["q6_continuity"] = {"answer": cont["gate_continuity_50"],
                          "basis": {"linked_share": cont["linked_share"]}}
    q["q7_filler"] = {"answer": coverage["gate_breathing_20"] and coverage["gate_blur_10"],
                      "basis": {"breathing_pct": coverage["breathing_pct"],
                                "blur_pct": coverage["generic_blur_pct"]}}
    q["q8_payoff"] = {"answer": payoff["gate_payoff_70"], "basis": {"payoff_score": payoff["score"]}}
    q["q9_noun_swap_template"] = {"answer": anti.get("verdict") != "template_clone",
                                  "basis": {"anti_template": anti}}
    deliberate = sum(1 for s in shots if str(s.get("motion_reason") or "").strip()
                     and str(s.get("purpose") or "").strip()) / max(len(shots), 1)
    q["q10_deliberate_choices"] = {"answer": deliberate >= 0.9,
                                   "basis": {"deliberate_share": round(deliberate, 2)}}
    gates = [k for k in ("q1_slideshow", "q2_every_beat_meaningful", "q4_hook_2s",
                         "q8_payoff", "q9_noun_swap_template")]
    q["editor_gates_pass"] = all(q[k]["answer"] is True for k in gates)
    return q


# ---------------------------------------------------------------- driver
def evaluate(plan: dict, story: dict, video_path=None, save_sig: bool = True,
             exclude_self: bool = True) -> dict:
    shots = plan.get("shots", [])
    classes = classify_plan(shots)
    _set_core_terms(story)
    coverage = coverage_metrics(shots, classes)
    hook = hook_score(plan, story, classes)
    its = its_score(shots, classes)
    red = redundancy(shots, classes)
    cont = continuity_score(shots, classes)
    payoff = payoff_score(plan, story, classes)
    sig = antitemplate.build_signature(plan, classes)
    recent = antitemplate.load_recent(exclude_story=sig["story_id"] if exclude_self else None)
    anti = antitemplate.compare(sig, recent)
    # V12 P0 — cross-video template fingerprint v2: "mute narration +
    # replace nouns -> same video?" over the directive's structural field
    # list.  v2 fields live IN the same persisted signature (one store).
    sig_v2 = antitemplate.build_signature_v2(plan)
    for k, v in sig_v2.items():
        sig[k] = v
    cross = antitemplate.cross_video_compare(sig, recent)
    anti["cross_video"] = cross
    # V11 P1 §3/P2 — cross-topic motif fingerprint (brand ≠ visual
    # vocabulary). Stored in the signature for future comparisons;
    # verdict reported alongside the structural anti-template verdict.
    story_dir = Path("stories") / str(sig["story_id"])
    if story_dir.exists():
        sig["motif"] = antitemplate.motif_signature(story_dir, plan, story)
        anti["motif"] = antitemplate.compare_motifs(sig, recent)
    if save_sig:
        antitemplate.save(sig)
    editor = human_editor_test(coverage, hook, its, red, cont, payoff, anti, shots)
    gates = {
        "evidence_cinematic_80": coverage["gate_evidence_cinematic_80"],
        "breathing_20": coverage["gate_breathing_20"],
        "generic_blur_10": coverage["gate_blur_10"],
        "hook_70": hook["gate_hook_70"],
        "its_share_50": its["gate_its_share_50"],
        "redundancy_25": red["gate_redundancy_25"],
        "continuity_50": cont["gate_continuity_50"],
        "payoff_70": payoff["gate_payoff_70"],
        "anti_template": anti.get("verdict") != "template_clone",
        # V12 P0 — the stronger cross-video test: plan-level structural
        # fingerprint vs previous <=5 stories.  same_video => gate fails.
        "cross_video_template": cross.get("verdict") != "same_video",
        "human_editor_gates": editor["editor_gates_pass"],
    }
    return {
        "story_id": story.get("story_id") or plan.get("story_id"),
        "v7_schema": "1.0",
        "coverage": coverage, "hook": hook, "information_transformation": its,
        "redundancy": red, "continuity": cont, "payoff": payoff,
        "anti_template": anti, "structural_signature": sig,
        "human_editor_test": editor, "gates": gates,
        "V7_EDITORIAL_PASS": all(gates.values()),
    }


def write_report(result: dict, qa_dir: Path) -> Path:
    qa_dir.mkdir(parents=True, exist_ok=True)
    p = qa_dir / f"qa7_{result['story_id']}.json"
    p.write_text(json.dumps(result, indent=1))
    return p
