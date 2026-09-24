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
  7. CLAIM CONFIDENCE (V12 P1): facts.json nuance classifications wire into
     the beat model — every beat carries the confidence of the claims it
     narrates (ESTABLISHED..UNCERTAIN) and contested claims are NEVER drawn
     as definitive mechanism (cause_to_consequence / mechanism_visible /
     object_transforms downgrade to hypothesis_branches, recorded as a
     confidence_override, never silent).

Backward compatible: stories without the new schema fields get classified
grammars + derived beat model; planv8 output fields are untouched.

CLI: openclaw cli.py plan9 <story_id> (drop-in for plan8).
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import antitemplate, canvas_grammar, nuance, planv8, visual_grammar
from engine.facts import load_facts

MAX_REGENERATIONS = 2  # directive: bounded 2-3 regeneration attempts

# V12 P1 — confidence taxonomy (same classes as engine/nuance.py), ordered
# weakest last so beats carrying several claims take the MOST contested one.
CONFIDENCE_SEVERITY = nuance.CLASSES
# Transforms that draw causation/mechanism as SETTLED fact. A beat whose
# claims are contested (nuance.CONTESTED) may not use these as primary
# visual grammar — the directive: contested causation cannot be drawn as
# definitive mechanism arrows.
DEFINITIVE_TRANSFORMS = ("cause_to_consequence", "mechanism_visible",
                         "object_transforms")


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


def _claims_by_beat(story_dir: Path) -> dict:
    """beat_id -> {confidence, claim_ids} from facts.json nuance classes.

    A beat narrating several claims takes the MOST CONTESTED class (the
    visual grammar must satisfy the weakest claim it carries). Claims with
    no authored classification fall back to nuance's conservative lexicon.
    Missing/unreadable facts.json -> {} (backward compatible, reported).
    """
    try:
        facts = load_facts(story_dir)
    except Exception:
        return {}
    out: dict = {}
    for c in facts.get("claims", []):
        cls = str((c.get("nuance") or {}).get("classification") or "").upper()
        if cls not in CONFIDENCE_SEVERITY:
            cls = nuance.classify_claim(c)[0]
        for bid in c.get("beats", []) or []:
            bid = str(bid)
            cur = out.get(bid)
            if cur is None or (CONFIDENCE_SEVERITY.index(cls)
                               > CONFIDENCE_SEVERITY.index(cur["confidence"])):
                out[bid] = {"confidence": cls,
                            "claim_ids": [str(c.get("id"))]}
            elif cur["confidence"] == cls:
                cur["claim_ids"].append(str(c.get("id")))
    return out


def _claim_texts_by_beat(story_dir) -> dict:
    """V13 M5 — {beat_id: [claim text, ...]} in facts order.  Missing or
    unreadable facts.json -> {} (hook/payoff synthesis degrades honestly,
    backward compatible)."""
    if not story_dir:
        return {}
    try:
        facts = load_facts(Path(story_dir))
    except Exception:
        return {}
    out: dict = {}
    for c in facts.get("claims", []):
        text = str(c.get("claim") or "").strip()
        if not text:
            continue
        for bid in c.get("beats", []) or []:
            out.setdefault(str(bid), []).append(text)
    return out


def _hook_fields(story: dict, beats: dict, claim_texts: dict) -> dict:
    """V13 M5 — hook structure on the FIRST beat (directive P0: the first
    two seconds are a promise — phenomenon + tension).  Authored when the
    story/beat declares the material; otherwise synthesized deterministically
    from declared claim/contradiction/question text only (no invented
    facts).  Diagnostic fields only — no gate reads them yet."""
    first_bid = next(iter(beats), None)
    if first_bid is None:
        return {}
    beat = beats[first_bid] or {}
    hp = story.get("hook_plan") if isinstance(story.get("hook_plan"), dict) else {}
    phenomenon = str(hp.get("phenomenon") or "").strip()
    tension = str(hp.get("tension") or "").strip()
    authored = bool(phenomenon and tension)
    if not phenomenon:
        declared = str(beat.get("phenomenon") or "").strip()
        if declared:
            phenomenon, authored = declared, True
        else:
            texts = claim_texts.get(first_bid) or []
            phenomenon = texts[0] if texts else (
                str(beat.get("visual_answer") or beat.get("visual_question")
                    or "").strip()
                or f"{story.get('subject') or 'the subject'} — seen before "
                   f"it is explained")
    if not tension:
        con = _contradiction(story)  # declared 'seems' is honest tension
        tension = (str(con.get("seems") or "").strip()
                   or str(beat.get("visual_question") or "").strip()
                   or "nothing on screen explains itself yet — the "
                      "mechanism is still hidden")
    return {"phenomenon": phenomenon, "tension": tension,
            "hook_source": "authored" if authored else "synthesized",
            # V13B M4 hook P0 — the opening title is support, never the
            # primary event: composev5/layout render it as a compact line
            # in the chosen caption-safe region on plate shots.
            "title_role": "support"}


def _payoff_fields(story: dict, beats: dict, claim_texts: dict) -> tuple:
    """V13 M5 — causal-chain payoff on the FINAL-ACT beat (first beat with
    function PAYOFF, else the last beat): the ordered claim steps collected
    from preceding beats, which the payoff collapses into one image.
    Diagnostic only."""
    order = list(beats)
    if not order:
        return None, {}
    payoff_bid = next((b for b in order if str((beats[b] or {}).get("function")
                                               or "").upper() == "PAYOFF"),
                      order[-1])
    chain: list = []
    for bid in order:
        if bid == payoff_bid:
            break
        texts = claim_texts.get(bid) or []
        if texts:
            chain.extend(texts)
        else:
            intent = str((beats[bid] or {}).get("visual_answer") or "").strip()
            if intent:
                chain.append(intent)
    beat = beats[payoff_bid] or {}
    pay_img = story.get("payoff_image")
    authored = bool(str(beat.get("payoff") or "").strip()
                    or (isinstance(pay_img, dict)
                        and str(pay_img.get("image") or "").strip()))
    return payoff_bid, {"causal_chain": chain,
                        "payoff_source": "authored" if authored
                        else "synthesized"}


def _beat_model(plan: dict, story: dict, kit_id: str,
                claims: dict | None = None,
                claim_texts: dict | None = None,
                domain_rec: dict | None = None) -> dict:
    """Annotate plan['beat_model']: per beat, viewer question -> visual
    intent -> visual experience -> state transformation -> payoff.
    V13B M2: carries the story domain record (detected once per story by
    the caller) as a model-level stamp; per-beat rows are unchanged."""
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}
    kit = canvas_grammar.KITS[kit_id]
    # V13 M4 — mode→representation mapping: per-beat representation +
    # justification stamped additively (directive P0: the rich plate +
    # overlays is the normal visual; diagrams are evidence).
    subject = str(story.get("subject") or "general")
    # V13 M5 — hook/payoff structure + SCALE_DIVE routing (all diagnostic,
    # additive; legacy plans without the stamps stay valid).
    texts = claim_texts or {}
    hook_fields = _hook_fields(story, beats, texts)
    payoff_bid, payoff_fields = _payoff_fields(story, beats, texts)
    order = list(beats)
    first_bid = order[0] if order else None
    mid_bids = [b for b in order if b not in (first_bid, payoff_bid)]
    dive_bid = next((b for b in mid_bids
                     if visual_grammar.scale_dive_candidate(
                         subject, " ".join(texts.get(b) or []))), None)
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
        # V12 P1 — claim confidence: contested claims are never drawn as a
        # definitive mechanism. The downgrade is recorded, never silent.
        crow = (claims or {}).get(bid) or {}
        conf = crow.get("confidence")
        applied, override = transform, None
        if conf in nuance.CONTESTED and transform in DEFINITIVE_TRANSFORMS:
            applied = "hypothesis_branches"
            override = {"from": transform, "to": applied,
                        "claim_ids": crow.get("claim_ids") or [],
                        "reason": f"claim confidence {conf} — contested "
                                  f"causation is not drawn as a definitive "
                                  f"mechanism"}
            if declared_t:
                problems.append(
                    f"{bid}: declared '{transform}' overridden to "
                    f"'hypothesis_branches' (claim confidence {conf})")
        rec = visual_grammar.recommend_mode_detailed(
            subject, fn, visual_mode=str(beat.get("visual_mode") or ""),
            claim=" ".join(texts.get(bid) or []),
            scale_dive_allowed=(bid == dive_bid))
        rows[bid] = {
            "function": fn,
            "viewer_question": str(beat.get("visual_question") or "").strip(),
            "visual_intent": str(beat.get("visual_answer") or "").strip(),
            "visual_experience": experience,
            "state_transformation": applied,
            "payoff": payoff_intent,
            "n_shots": len(shots),
            "claim_confidence": conf,
            "claim_ids": crow.get("claim_ids") or [],
            "confidence_override": override,
            # V13 M4 — additive stamp (missing field on old plans reads as
            # legacy DIAGRAM via visual_grammar.representation_of).
            "representation": rec["representation"],
            "mode_justification": rec["mode_justification"],
        }
        # V13 integration — rich-plate beats carry a plate spec so the
        # render/plate path (plate_pipeline.generate_plate, pilot run) can
        # consume it. Additive: legacy plans without plate_spec stay valid.
        if str(rec["representation"]) in ("PLATE", "PLATE+OVERLAY", "HYBRID"):
            rows[bid]["plate_spec"] = {
                "subject_bbox_px": [float(v) for v in (
                    beat.get("subject_bbox_px") or (0.2, 0.3, 0.8, 0.7))],
                "texture_tags": [str(rec.get("mode") or "plate").lower()],
                "lighting": (str(rec.get("mode_justification") or "").strip()
                             or "soft ambient"),
                "max_scale": 1.6,
            }
    # V13 M5 — stamp hook fields on the FIRST beat and payoff fields on the
    # final-act beat (same-beat edge on single-beat plans is acceptable:
    # hook opens it, payoff closes it).
    if hook_fields and first_bid in rows:
        rows[first_bid].update(hook_fields)
    if payoff_bid is not None and payoff_bid in rows:
        rows[payoff_bid].update(payoff_fields)
    return {"grammar": kit_id, "beats": rows,
            "hook_beat": first_bid, "payoff_beat": payoff_bid,
            "transformation_problems": problems,
            # V13B M2 — story domain stamp (additive; diagnostic).
            "domain": (domain_rec or {}).get("domain"),
            "domain_confidence": (domain_rec or {}).get("confidence"),
            "claim_confidence": {bid: r["claim_confidence"]
                                 for bid, r in rows.items()
                                 if r["claim_confidence"]}}


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


def detect_domain_for_story(story: dict) -> dict:
    """V13B M2 — detect_domain ONCE per story: story_meta (title/subject
    double-weighted inside detect_domain) plus one narration line per beat
    (narration + claim).  Deterministic; missing beats just contribute less
    evidence."""
    lines = []
    for b in (story.get("beats") or []):
        lines.append(str(b.get("narration") or ""))
        lines.append(str(b.get("claim") or ""))
    return visual_grammar.detect_domain(story, lines)


def apply_canvas(plan: dict, story: dict, kit_id: str,
                 domain_rec: dict | None = None) -> int:
    """V13B M2 — write the DOMAIN-AWARE world canvas onto every shot plus a
    per-shot visual_grammar record {domain, world, composition, overlays,
    accent}.  Selection = domain ordered composition preferences + beat role
    (hook beat -> world composition, panel forbidden; data/list/comparison
    beats may keep a panel, justified).  universal_presentation_panel is
    never an automatic default — it reaches a shot only through the justified
    evidence path or explicit author declaration.  kit_id stays the plan
    header grammar and biases world preference (canvas_grammar.WORLD_BIAS)
    so bounded grammar regeneration remains meaningful.

    Backward compatible: planv5's per-shot visual_grammar keys (subject /
    recommended_mode — depth.py consumers) are preserved; M2 keys merge in
    additively, and shots with no prior record get the full M2 record.
    """
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}
    rec = domain_rec or detect_domain_for_story(story)
    domain = str(rec.get("domain") or "general")
    overlays = list(visual_grammar.overlays_for(domain))
    accent = visual_grammar.accent_for(domain)
    n = 0
    for s in (plan.get("shots") or []):
        beat = beats.get(str(s.get("beat_id")), {})
        comp, just = canvas_grammar.select_world(s, beat, rec, kit_id)
        s["canvas"] = canvas_grammar.world_canvas(s, beat, rec, comp, just,
                                                  family_kit_id=kit_id)
        s["caption_zone"] = s["canvas"].get("caption_zone",
                                            s.get("caption_zone"))
        prior = s.get("visual_grammar") or {}
        s["visual_grammar"] = {**prior,
                               "domain": domain,
                               "world": comp,
                               "composition": comp,
                               "overlays": overlays,
                               "accent": accent,
                               "composition_justification": just}
        n += 1
    plan["canvas_grammar"] = kit_id
    plan["canvas_grammar_covers"] = canvas_grammar.kit_covers(kit_id)
    plan["story_domain"] = {"domain": domain,
                            "confidence": rec.get("confidence"),
                            "evidence": rec.get("evidence") or []}
    return n


# ---------------------------------------------------------------------------
# Main entry


def make_edit_plan_v9(paths, story_id: str, out_name: str = "edit_plan.json",
                      force_grammar: str | None = None) -> tuple[dict, dict]:
    """planv8 plan + story-driven canvas architecture + beat model +
    hook/contradiction/payoff localization + cross-video template loop."""
    story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
    claims = _claims_by_beat(Path(paths.stories) / story_id)
    # V13B M2 — the story domain is detected ONCE (title/subject double
    # weight) and drives per-shot composition selection below.
    domain_rec = detect_domain_for_story(story)
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
        apply_canvas(plan, story, kit_id, domain_rec=domain_rec)
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

    model = _beat_model(plan, story, chosen, claims,
                        claim_texts=_claim_texts_by_beat(
                            Path(paths.stories) / story_id),
                        domain_rec=domain_rec)
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
        "claim_confidence": model.get("claim_confidence") or {},
        # V13B M2 — story domain visibility in the plan report.
        "story_domain": {"domain": domain_rec.get("domain"),
                         "confidence": domain_rec.get("confidence")},
        # V13 M4 — representation mix across beats (evidence the planner did
        # NOT collapse everything into diagram painters).
        "representation_mix": {
            r["representation"]: sum(
                1 for x in model["beats"].values()
                if x["representation"] == r["representation"])
            for r in model["beats"].values()},
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
    # V13 integration — the render/QA path consumes build/edit_plan.json;
    # persist the annotated plan there too (the unsuffixed copy otherwise
    # stays plan8-era: no v9 stamps, no representation, no plate_spec).
    if out_name and out_name != snap.name:
        (Path(paths.build) / out_name).write_text(json.dumps(plan, indent=1) + "\n")
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
        f"  story domain: {(plan.get('story_domain') or {}).get('domain')} "
        f"(confidence {(plan.get('story_domain') or {}).get('confidence')})",
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
    conf = (plan.get("beat_model") or {}).get("claim_confidence") or {}
    ovr = [f"{bid}:{(r.get('confidence_override') or {}).get('from')}->"
           f"{(r.get('confidence_override') or {}).get('to')}"
           for bid, r in (plan.get("beat_model") or {}).get("beats", {}).items()
           if r.get("confidence_override")]
    lines.append(f"  claim confidence: "
                 f"{conf if conf else 'no facts claims wired'}"
                 + (f" | overrides: {', '.join(ovr)}" if ovr else ""))
    return "\n".join(lines)
