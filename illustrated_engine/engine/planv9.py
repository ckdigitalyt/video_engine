"""V12 P0 — Visual experience planner (planv9).  Jade_todo_v12 §P0.

Wraps the existing planv8 chain (planv8 -> planv7 -> planv2) — the engine is
EXTENDED, not rewritten.  planv9 adds the story-dependent layer planv8 lacks:

  1. CANVAS ARCHITECTURE per shot from the canvas_grammar registry
     (composition / background / panel usage / chrome density / caption
     architecture / transition vocabulary / camera doctrine) — the
     presentation panel becomes one option among many, used only when the
     story's grammar says so.
  2. BEAT MODEL: narration beat -> viewer question -> visual intent ->
     visual experience -> state transformation -> payoff.  Every major beat
     declares WHAT THE VIEWER SEES CHANGE (canvas_grammar.
     VALID_TRANSFORMATIONS); camera moves/particles/number pops are never
     accepted as primary gain.
  3. HOOK PLAN: subject visible ~1s, curiosity by 2s, question by 5s, no
     unnecessary black/fade at 0.5s.
  4. VISUAL CONTRADICTION: a REAL visual reveal (declared, located in the
     plan, honored = the reveal shot exists with a reveal-class change).
  5. PAYOFF IMAGE: the final 3-5s compress the causal model into one
     memorable image (declared spec; no generic end card, no hero-enlarge
     default).
  6. CROSS-VIDEO TEMPLATE LOOP: plan-level fingerprint vs previous stories
     ("mute narration + replace nouns -> same video?") — on same_video the
     planner regenerates with the next DIFFERENT valid grammar, bounded
     attempts, honest final verdict either way.

Backward compatible: stories without the new schema fields get classified
grammars + derived beat model; planv8 output fields are untouched.

CLI: openclaw cli.py plan9 <story_id> (drop-in for plan8).
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import antitemplate, canvas_grammar, planv8

MAX_REGENERATIONS = 2  # directive: bounded 2-3 regeneration attempts


# ---------------------------------------------------------------------------
# Story schema accessors (all optional -> backward compatible)


def _declared_grammars(story: dict) -> list:
    g = story.get("visual_grammars") or []
    if isinstance(g, str):
        g = [g]
    return [str(x) for x in g if str(x) in canvas_grammar.KITS]


def _contradiction(story: dict) -> dict:
    c = story.get("visual_contradiction") or {}
    if not isinstance(c, dict):
        return {}
    out = {k: str(c.get(k) or "").strip() for k in
           ("seems", "actually", "reveal", "beat")}
    out["beat"] = out["beat"].upper()
    return out if any(out.values()) else {}


def _hook_plan(story: dict) -> dict:
    h = story.get("hook_plan") or {}
    if not isinstance(h, dict):
        h = {}
    return {
        "subject_visible_s": float(h.get("subject_visible_s", 1.0)),
        "curiosity_s": float(h.get("curiosity_s", 2.0)),
        "question_s": float(h.get("question_s", 5.0)),
        "no_black_fade_at_0_5": bool(h.get("no_black_fade_at_0_5", True)),
        "declared": bool(story.get("hook_plan")),
    }


def _payoff_image(story: dict) -> dict:
    p = story.get("payoff_image") or {}
    if isinstance(p, str):
        p = {"image": p}
    if not isinstance(p, dict):
        return {}
    out = {
        "image": str(p.get("image") or "").strip(),
        "forbids_generic_end_card": True,
        "forbids_hero_enlarge_default": True,
    }
    if p.get("beat"):
        out["beat"] = str(p["beat"]).upper()
    return out if out["image"] else {}


# ---------------------------------------------------------------------------
# Beat model


def _beat_model(plan: dict, story: dict, kit_id: str) -> dict:
    """Annotate plan['beat_model']: per beat, viewer question -> visual
    intent -> visual experience -> state transformation -> payoff."""
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}
    kit = canvas_grammar.KITS[kit_id]
    rows, problems = {}, []
    for bid, beat in beats.items():
        fn = str(beat.get("function") or "").upper()
        transform = canvas_grammar.KITS[kit_id]["default_transform"].get(
            fn, "cause_to_consequence")
        declared_t = str(beat.get("transformation") or "").strip()
        if declared_t:
            transform = declared_t
        if transform in canvas_grammar.INVALID_TRANSFORMATIONS:
            problems.append(f"{bid}: transformation '{transform}' is camera/"
                            f"decoration, not primary information gain")
        if transform not in canvas_grammar.VALID_TRANSFORMATIONS:
            problems.append(f"{bid}: transformation '{transform}' not in the "
                            f"valid vocabulary")
        shots = [s for s in (plan.get("shots") or [])
                 if str(s.get("beat_id")) == bid]
        experience = str(beat.get("visual_experience") or "").strip() or (
            f"{comp_label(kit, fn)}: "
            f"{str(beat.get('visual_answer') or beat.get('visual_question') or '').strip()}")
        payoff_intent = str(beat.get("payoff") or "").strip()
        rows[bid] = {
            "function": fn,
            "viewer_question": str(beat.get("visual_question") or "").strip(),
            "visual_intent": str(beat.get("visual_answer") or "").strip(),
            "visual_experience": experience,
            "state_transformation": transform,
            "payoff": payoff_intent,
            "n_shots": len(shots),
        }
    return {"grammar": kit_id, "beats": rows,
            "transformation_problems": problems}


def comp_label(kit: dict, fn: str) -> str:
    comp = kit.get("beat_composition", {}).get(
        fn, kit.get("composition", ""))
    return str(comp).replace("_", " ")


# ---------------------------------------------------------------------------
# Contradiction / hook / payoff localization


def _locate_contradiction(plan: dict, story: dict, beats: dict) -> dict:
    con = _contradiction(story)
    if not con:
        return {"declared": False,
                "note": "no visual_contradiction declared (schema optional)"}
    bid = con.get("beat", "")
    reveal_shots = []
    for s in (plan.get("shots") or []):
        sb = str(s.get("beat_id"))
        is_reveal = False
        for st in ((s.get("v8") or {}).get("states") or []):
            if st.get("name") in ("REVEAL", "TRANSFORM") or st.get("event"):
                is_reveal = True
        for e in (s.get("events") or []):
            if str(e.get("kind")) in ("reveal", "frame_reveal", "fill_state"):
                is_reveal = True
        if (not bid or sb == bid) and is_reveal:
            reveal_shots.append(s.get("shot_id"))
    honored = bool(reveal_shots)
    return {"declared": True, "seems": con.get("seems"),
            "actually": con.get("actually"), "reveal": con.get("reveal"),
            "beat": bid, "reveal_shots": reveal_shots, "honored": honored}


def _locate_hook(plan: dict, hook: dict) -> dict:
    shots = plan.get("shots") or []
    if not shots:
        return {"measured": {}}
    s0 = shots[0]
    fade_like = str(s0.get("transition_in") or "").lower() in (
        "fade", "fade_in", "black", "dip_to_black")
    first_action = None
    for s in shots:
        for st in ((s.get("v8") or {}).get("states") or []):
            if st.get("event"):
                t0 = _shot_start(plan, s)
                first_action = round(t0 + float(st.get("t") or 0), 2)
                break
        if first_action is not None:
            break
    first_open = None
    for s in shots:
        if (s.get("v8") or {}).get("opens"):
            first_open = round(_shot_start(plan, s), 2)
            break
    measured = {
        "subject_visible_s": 0.0 if not fade_like else 0.5,
        "first_action_s": first_action,
        "first_question_s": first_open,
        "opening_black_or_fade": fade_like,
    }
    return {"targets": hook, "measured": measured,
            "ok": (measured["subject_visible_s"] <= hook["subject_visible_s"]
                   and not measured["opening_black_or_fade"]
                   and (first_open is None or first_open <= hook["question_s"]))}


def _shot_start(plan: dict, shot: dict) -> float:
    t = 0.0
    for s in (plan.get("shots") or []):
        if s.get("shot_id") == shot.get("shot_id"):
            return t
        t += float(s.get("duration_s") or 0)
    return t


def _locate_payoff(plan: dict, payoff: dict) -> dict:
    shots = plan.get("shots") or []
    if not shots:
        return {"declared": False}
    last = shots[-1]
    t0 = _shot_start(plan, last)
    total = t0 + float(last.get("duration_s") or 0)
    in_window = total - t0 >= 3.0 and total - t0 <= max(8.0, total * 0.35)
    has_state = any(st.get("name") == "PAYOFF"
                    for st in ((last.get("v8") or {}).get("states") or []))
    hero_enlarge = False
    cam = last.get("camera") or {}
    to_scale = float((cam.get("to_scale") if isinstance(cam, dict) else 0) or 0)
    frm = cam.get("from_scale") if isinstance(cam, dict) else None
    if to_scale and frm and to_scale > float(frm) * 1.25:
        hero_enlarge = True  # directive: do NOT simply enlarge the hero
    declared = bool(payoff.get("image"))
    return {"declared": declared, "image": payoff.get("image"),
            "final_shot": last.get("shot_id"),
            "final_window_s": round(total - t0, 2),
            "in_final_3_5s_window": bool(in_window),
            "has_payoff_state": bool(has_state),
            "hero_enlarge_default": hero_enlarge,
            "ok": (declared and has_state and not hero_enlarge)}


# ---------------------------------------------------------------------------
# Canvas application


def apply_canvas(plan: dict, story: dict, kit_id: str) -> int:
    """Write the kit's canvas dict onto every shot + the plan header."""
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}
    n = 0
    for s in (plan.get("shots") or []):
        beat = beats.get(str(s.get("beat_id")), {})
        s["canvas"] = canvas_grammar.shot_canvas(s, beat, kit_id)
        s["caption_zone"] = s["canvas"].get("caption_zone",
                                            s.get("caption_zone"))
        n += 1
    plan["canvas_grammar"] = kit_id
    plan["canvas_grammar_covers"] = canvas_grammar.kit_covers(kit_id)
    return n


# ---------------------------------------------------------------------------
# Main entry


def make_edit_plan_v9(paths, story_id: str, out_name: str = "edit_plan.json",
                      force_grammar: str | None = None) -> tuple[dict, dict]:
    """planv8 plan + story-driven canvas architecture + beat model +
    hook/contradiction/payoff localization + cross-video template loop."""
    story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
    candidates = (_declared_grammars(story) or canvas_grammar.classify_story(story))
    if force_grammar in canvas_grammar.KITS:
        # Forced grammar PREPENDS; regeneration can still fall through to
        # the story's own next valid grammar (the loop needs alternatives).
        candidates = [force_grammar] + [c for c in candidates
                                        if c != force_grammar]
    recent = antitemplate.load_recent(exclude_story=story_id, n=5)

    attempts, chosen, plan, report = [], None, None, {}
    for i, kit_id in enumerate(candidates[: MAX_REGENERATIONS + 1]):
        plan, v8 = planv8.make_edit_plan_v8(paths, story_id, out_name=out_name)
        apply_canvas(plan, story, kit_id)
        sig = antitemplate.build_signature_v2(plan)
        cross = antitemplate.cross_video_compare(sig, recent)
        attempts.append({
            "attempt": i + 1, "grammar": kit_id,
            "mean_structural_distance": cross.get("mean_distance"),
            "verdict": cross.get("verdict"),
            "closest": cross.get("vs"),
        })
        chosen, report = kit_id, {"cross_video": cross, "v2_signature": sig}
        if cross.get("verdict") != "same_video":
            break
        # same-video verdict -> regenerate with the NEXT DIFFERENT valid
        # grammar for this story (never random variation).
    else:
        report["regeneration_exhausted"] = True

    model = _beat_model(plan, story, chosen)
    plan["beat_model"] = model
    plan["visual_contradiction"] = _locate_contradiction(plan, story, {})
    plan["hook_plan"] = _locate_hook(plan, _hook_plan(story))
    plan["payoff_image"] = _locate_payoff(plan, _payoff_image(story))
    plan["v9"] = {
        "schema": "v12.planv9/1.0",
        "grammar_candidates": candidates,
        "grammar_chosen": chosen,
        "regeneration_attempts": attempts,
        "cross_video_template": report.get("cross_video"),
        "transformation_problems": model["transformation_problems"],
    }

    # Persist the plan-level signature so the NEXT story compares against it
    # even before any render exists (fixes the empty no_comparable_history
    # motif store: signatures now exist at plan time).
    sig = report.get("v2_signature") or antitemplate.build_signature_v2(plan)
    sig["story_id"] = story_id
    sig["motif"] = antitemplate.motif_signature(
        Path(paths.stories) / story_id, plan, story)
    antitemplate.save(sig)

    # Persist the annotated snapshot (plan8 wrote edit_plan_<story>.json).
    snap = Path(paths.build) / f"edit_plan_{story_id}.json"
    snap.write_text(json.dumps(plan, indent=1) + "\n")
    return plan, plan["v9"]


def summarize(plan: dict, v9: dict) -> str:
    shots = plan.get("shots") or []
    total = sum(float(s.get("duration_s") or 0) for s in shots)
    con = plan.get("visual_contradiction") or {}
    hook = (plan.get("hook_plan") or {})
    pay = (plan.get("payoff_image") or {})
    cross = v9.get("cross_video_template") or {}
    lines = [
        f"planv9: {len(shots)} shots, {total:.1f}s | grammar: "
        f"{plan.get('canvas_grammar')} ({plan.get('canvas_grammar_covers')})",
        f"  grammar candidates: {', '.join(v9.get('grammar_candidates') or [])}",
        f"  cross-video: {cross.get('verdict')} "
        f"(mean distance {cross.get('mean_distance')} vs "
        f"{len(cross.get('vs') or [])} recent)",
    ]
    for a in v9.get("regeneration_attempts") or []:
        lines.append(f"    attempt {a['attempt']}: {a['grammar']} -> "
                     f"{a['verdict']} (d={a['mean_structural_distance']})")
    lines.append(f"  contradiction: "
                 f"{'honored @ ' + ','.join(con.get('reveal_shots') or []) if con.get('honored') else con.get('note', 'NOT honored')}")
    lines.append(f"  hook: {'ok' if hook.get('ok') else 'FAIL'} "
                 f"{hook.get('measured')}")
    lines.append(f"  payoff: {'ok' if pay.get('ok') else 'FAIL'} "
                 f"final {pay.get('final_shot')} window {pay.get('final_window_s')}s")
    probs = v9.get("transformation_problems") or []
    lines.append(f"  transformations: "
                 f"{'ok' if not probs else 'PROBLEMS: ' + '; '.join(probs[:4])}")
    return "\n".join(lines)
