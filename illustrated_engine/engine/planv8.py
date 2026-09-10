"""V8 planner: visual state machine, escalation curve, curiosity ladder,
TTS performance plan, hero recognizability, duration policy.

Reuses planv7 (hook block, story_type, concepts, title policy, anti-template)
and rewrites per-shot choreography from DECLARED visual states (brief §1, §3,
§8, §9, §10, §14, §15). States are derived algorithmically from the plate
manifest and story beats — no per-video re-authoring. Where a state genuinely
needs new art the shot is flagged `needs_state_plate` instead of faked.

State model (brief §1): narration beat → visual intent → visual state
sequence → choreography, with ESTABLISH → FOCUS → TRANSFORM → CONSEQUENCE →
PAYOFF available but never all mandatory. Every state transition mutates the
information on screen (reveal/isolate/flow/fill_state/consequence events) —
camera movement alone is never counted as transformation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from engine import semantics, story_grammar as grammar, planv7
from engine.editorial7 import tokens
from engine.planv5 import (_clamp_card_rect, _plate_el_to_card,
                           _plate_manifest)

# beat function → (phase, intensity). Matching is substring, case-insensitive.
PHASE_MAP = [
    (("HOOK", "TEASER", "COLD_OPEN"), ("hook", 0.90)),
    (("ESTABLISH", "MAP", "TIME", "SETUP", "CONTEXT", "ORIENT", "SCENE", "WORLD"),
     ("orientation", 0.50)),
    (("CAUSAL", "MECHANISM", "DRIVERS", "DISCOVERY", "EXPLAIN", "CAUSE", "HOW",
      "PROCESS", "TRANSFORMATION", "HEAT"),
     ("discovery", 0.62)),
    (("CONSEQUENCE", "CASCADE", "CONTRAST", "COMPARISON", "STAKES",
      "ESCALATE", "ESCALATION", "PROBLEM"),
     ("escalation", 0.78)),
    (("REVEAL", "CLIMAX", "TURN"), ("reveal", 0.95)),
    (("PAYOFF", "RESOLUTION", "TAKEAWAY", "RECOVERY", "SO WHAT"), ("payoff", 0.85)),
]
ARC_BY_PHASE = {"hook": "immediate", "orientation": "controlled",
                "discovery": "building", "escalation": "urgent",
                "reveal": "slower", "payoff": "confident"}
_SUPERLAT = re.compile(r"\b(most|least|fastest|slowest|largest|smallest|only|"
                       r"never|always|first|last|worst|best|huge|massive|tiny)\b",
                       re.I)


def _phase_of(fn: str) -> tuple[str, float]:
    f = (fn or "").upper()
    for keys, (phase, val) in PHASE_MAP:
        if any(k in f for k in keys):
            return phase, val
    return "discovery", 0.62


def _rects_of(els: list, cam: dict) -> list[tuple[dict, list]]:
    """Positioned, plausibly-visible elements only: empty text and
    container-sized rects produce phantom highlights on empty space."""
    out = []
    for el in els or []:
        if "cx" in el and "cy" in el:
            if not str(el.get("text") or "").strip():
                continue
            try:
                r = _clamp_card_rect(_plate_el_to_card(el, cam or {}))
            except Exception:
                continue
            if float(r[2]) * float(r[3]) > 0.55:
                continue  # container/background shape, not a labelled part
            out.append((el, r))
    return out


def _tok_set(text: str) -> set:
    return {t for t in tokens(str(text or "")) if len(t) > 2}


def _concept_strs(concepts) -> list:
    """Shot concepts may be dicts {concept:..., ...} or strings — flatten."""
    out = []
    for c in concepts or []:
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, dict):
            out.extend(v for v in c.values() if isinstance(v, str))
        else:
            out.append(str(c))
    return out


def _pick_key(pairs: list, beat: dict, concepts: list) -> tuple[dict, list] | None:
    """Element whose text best matches the beat's claim/question/concepts."""
    probe = _tok_set(" ".join([str(beat.get("claim") or ""),
                               str(beat.get("visual_question") or ""),
                               " ".join(_concept_strs(concepts))]))
    best, best_score = None, -1
    for el, r in pairs:
        et = _tok_set(el.get("text"))
        score = len(et & probe)
        if score > best_score:
            best, best_score = (el, r), score
    if best is None and pairs:
        best = pairs[0]
    return best


def _states_for_shot(s: dict, beat: dict, els: list, pack: dict,
                     is_final: bool) -> tuple[list, list, bool]:
    """Derive the visual state sequence + state events for one shot.

    Returns (states, events, needs_state_plate). Durations gate which states
    the planner uses — not every shot needs every state.
    """
    dur = float(s.get("duration_s") or 0)
    cam = s.get("camera") or {}
    pairs = _rects_of(els, cam)
    manual = [e for e in (s.get("events") or []) if not e.get("auto")]
    busy = [(float(e.get("t", 0)), float(e.get("t", 0)) + 1.6) for e in manual]
    states, events = [], []
    fn = str(beat.get("function") or "")
    phase, _val = _phase_of(fn)

    def t_free(t: float) -> float:
        t = round(min(max(t, 0.4), max(dur - 0.8, 0.4)), 3)
        while any(abs(t - b0) < 0.8 for b0, _b1 in busy):
            t = round(min(t + 0.8, max(dur - 0.8, 0.4)), 3)
        return t

    def emit(name: str, t: float, spec: dict):
        t = t_free(t)
        # V9 compounding: every living-event spec carries its beat's
        # intensity tier so living.py scales magnitude (radius, glow,
        # particle density) instead of using static parameters.
        spec = {**spec, "intensity": round(float(_val), 3)}
        events.append({"kind": spec["kind"].lower(), "t": t, "spec": spec,
                       "auto": True, "state": name})
        busy.append((t, t + 1.6))
        states.append({"name": name, "t": t, "event": spec["kind"].lower()})

    if not pairs:
        states.append({"name": "ESTABLISH", "t": 0.0, "event": None})
        return states, manual, True

    # ESTABLISH — living draw-on: staggered reveal of declared elements
    emit("ESTABLISH", 0.10 * dur,
         {"kind": "REVEAL", "rects": [r for _el, r in pairs][:6],
          "style": "stagger"})
    key = _pick_key(pairs, beat, s.get("concepts") or [])
    second = None
    far = None
    if key:
        krect = key[1]
        # FOCUS — isolate the component the beat is about
        if dur >= 5.0:
            emit("FOCUS", 0.36 * dur, {"kind": "ISOLATE", "rect": krect,
                                       "style": "dim"})
        # TRANSFORM — animate the information itself (brief §3)
        if dur >= 6.5:
            far, fd = None, -1.0
            for el, r in pairs:
                if r is krect:
                    continue
                d = ((r[0] - krect[0]) ** 2 + (r[1] - krect[1]) ** 2) ** 0.5
                if d > fd:
                    far, fd = (el, r), d
            causal = phase in ("discovery", "escalation") or phase == "hook"
            if far and causal and fd > 0.05 and "flow" in pack["event_vocab"]:
                emit("TRANSFORM", 0.58 * dur,
                     {"kind": "FLOW", "from_rect": krect, "to_rect": far[1],
                      "style": "particles"})
            else:
                emit("TRANSFORM", 0.58 * dur,
                     {"kind": "FILL_STATE", "rect": krect, "style": "grow"})
        # CONSEQUENCE — the dependent element shows the effect
        if dur >= 8.0:
            target = (far or (key[0], krect))[1] if dur >= 6.5 else krect
            emit("CONSEQUENCE", 0.78 * dur,
                 {"kind": "CONSEQUENCE", "rect": target, "effect": "glow"})
        second = far
    # PAYOFF — final shot resolves with the key figure/verdict
    if is_final:
        cap_nums = set()
        for c in (s.get("captions") or []):
            if isinstance(c, dict):
                cap_nums |= set(re.findall(r"\d+(?:\.\d+)?",
                                           str(c.get("text") or "")))
        num_el = None
        for el, r in pairs:
            et = str(el.get("text") or "")
            if et and any(n in et for n in cap_nums):
                num_el = (el, r)
                break
        if num_el:
            emit("PAYOFF", 0.86 * dur,
                 {"kind": "NUMBER_POP", "text": str(num_el[0].get("text") or ""),
                  "rect": num_el[1], "pulse": True})
        else:
            emit("PAYOFF", 0.86 * dur,
                 {"kind": "HIGHLIGHT", "rect": (key or pairs[0])[1],
                  "style": "circle", "pulse": True})
    return states, manual + events, False


def _performance(beat: dict, s: dict, phase: str, intensity: float) -> dict:
    """TTS performance plan for one beat (brief §10)."""
    text = str(beat.get("narration") or "")
    if not text:
        text = " ".join(str(c.get("text") or "") for c in (s.get("captions") or []))
    words = [w for w in text.split() if w.strip()]
    dur = max(float(s.get("duration_s") or 0), 0.1)
    wps = len(words) / dur
    pace = "slow" if wps < 2.1 else ("brisk" if wps > 2.9 else "measured")
    emphasis = []
    for w in words:
        clean = w.strip(".,;:!?\"'—").lower()
        if len(clean) > 2 and (clean.isdigit() or _SUPERLAT.search(clean)
                               or len(clean) >= 9):
            emphasis.append(w.strip(".,;:!?\"'"))
        if len(emphasis) >= 3:
            break
    pauses = []
    pos = 0
    for w in words:
        pos += len(w) + 1
        if w.rstrip('"\'').endswith((".", "!", "?")) and pos < len(text) - 2:
            pauses.append({"after_word_pos": pos, "pause_s": 0.35})
    for w in emphasis:
        idx = text.find(w)
        if idx > 0:
            pauses.append({"before_char": idx, "pause_s": 0.2})
    return {"pace": pace, "words_per_s": round(wps, 2), "energy": intensity,
            "emphasis": emphasis, "pauses": pauses[:6],
            "arc": ARC_BY_PHASE.get(phase, "controlled"),
            "intensity": intensity}


def make_edit_plan_v8(paths, story_id: str, out_name: str = "edit_plan.json"):
    """V8 edit plan: planv7 base + visual state machine + V8 metrics."""
    plan, v7 = planv7.make_edit_plan_v7(paths, story_id, out_name=out_name)
    story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
    story_type = plan.get("story_type") or story.get("story_type") or ""
    pack = grammar.pack_for(story_type)
    manifest = _plate_manifest(Path(paths.stories) / story_id)
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}

    actions, warnings = [], []
    intensities, ladder_rows = [], []
    opened, shot_v8s = [], []

    shots = plan.get("shots") or []
    for i, s in enumerate(shots):
        beat = beats.get(str(s.get("beat_id")), {})
        fn = str(beat.get("function") or "")
        phase, intensity = _phase_of(fn)
        intensities.append(intensity)
        els = manifest.get(str(s.get("asset")), []) or []
        is_final = i == len(shots) - 1
        states, new_events, needs_plate = _states_for_shot(
            s, beat, els, pack, is_final)
        s["events"] = new_events
        # Declared key number: pop the beat's key figure big. composev5 draws
        # the pop text itself, so no plate element is required. Skipped when
        # choreography already anchored a pop on a manifest element.
        kn = str(beat.get("key_number") or "").strip()
        if kn and not any(e.get("kind") == "number_pop" for e in s["events"]):
            dur = float(s.get("duration_s", 4.0))
            rect = [float(v) for v in (beat.get("key_number_rect")
                                       or [0.62, 0.20, 0.32, 0.10])]
            s["events"].append({
                "kind": "number_pop",
                "t": round(min(2.2, dur * 0.22), 3),
                "spec": {"kind": "number_pop", "text": kn, "rect": rect,
                         "pulse": False, "declared": True},
            })
        # curiosity ladder from declared visual_question/visual_answer,
        # resolved semantically (declared concepts/facts or alias clusters)
        sids = semantics.concept_ids(s.get("concepts"))
        sfacts = [str(f) for f in (beat.get("fact_ids") or [])]
        vq = str(beat.get("visual_question") or "").strip()
        va = str(beat.get("visual_answer") or "").strip()
        opens, resolves = [], []
        opened_idx_before = len(opened)  # questions opened before this shot
        if vq:
            vqk = _tok_set(vq)
            if not any(len(vqk & o["key"]) >= 2 for o in opened):
                opened.append({"key": vqk, "text": vq, "concepts": sids,
                               "facts": sfacts, "resolved": False})
                opens.append(vq)
        if va:
            # Only LATER beats can resolve an earlier question — the question
            # opened in THIS beat cannot be self-resolved (it was never really
            # open). opened_idx_before marks the boundary.
            for idx, o in enumerate(opened):
                if o["resolved"]:
                    continue
                if idx >= opened_idx_before:
                    continue
                link = semantics.semantic_link(o["text"], va, o["concepts"],
                                               sids, o["facts"], sfacts)
                if link["link"] != "none":
                    o["resolved"] = True
                    resolves.append(f"{link['link']}:{','.join(link['shared'][:3])}")
                    break
        perf = _performance(beat, s, phase, intensity)
        s["v8"] = {
            "intent": (str(beat.get("visual_question") or beat.get("claim") or "")
                       or f"{phase} beat")[:180],
            "phase": phase,
            "states": states,
            "intensity": intensity,
            "needs_state_plate": needs_plate,
            "opens": opens,
            "resolves": resolves,
            "performance": perf,
        }
        shot_v8s.append(s["v8"])
        # running unresolved count: how many open questions are still unresolved after this shot
        unresolved_after = sum(1 for o in opened if not o["resolved"])
        ladder_rows.append({"shot_id": s.get("shot_id"), "phase": phase,
                            "opens": len(opens), "resolves": len(resolves),
                            "unresolved": unresolved_after})
        if states and not needs_plate:
            kinds = [st["event"] for st in states if st.get("event")]
            actions.append(f"{s.get('shot_id')}: {len(states)} states "
                           f"({'+'.join(st['name'] for st in states)}) "
                           f"events[{','.join(kinds)}]")
        if needs_plate:
            warnings.append(f"{s.get('shot_id')}: no positioned elements on "
                            "plate — needs_state_plate (honest flag, not faked)")

    # escalation curve (brief §8)
    mean_i = sum(intensities) / max(len(intensities), 1)
    rng = max(intensities) - min(intensities) if intensities else 0.0
    var = sum((v - mean_i) ** 2 for v in intensities) / max(len(intensities), 1)
    std = var ** 0.5
    last_pre = intensities[-2] if len(intensities) > 1 else 0.0
    esc_ok = rng >= 0.25 and std >= 0.10 and last_pre >= 0.50 + 0.15
    escalation = {"values": intensities, "mean": round(mean_i, 3),
                  "range": round(rng, 3), "std": round(std, 3),
                  "phases": [r["phase"] for r in ladder_rows],
                  "verdict": "pass" if esc_ok else "flat"}

    # curiosity gates (brief §9)
    central = None
    for r, s in zip(ladder_rows, shots):
        if r["opens"]:
            central = s["v8"]["opens"][0]
            break
    # open_timeline = unresolved count after each shot (honest — not net per-shot)
    open_timeline = [r["unresolved"] for r in ladder_rows]
    mid = open_timeline[1:-1] if len(open_timeline) > 2 else []
    open_min = min(mid) if mid else 0
    # final_resolves: the last shot introduced a new open AND resolved something from earlier
    final_shot = ladder_rows[-1] if ladder_rows else None
    final_resolves = bool(final_shot and final_shot["resolves"] >= 1)
    curiosity = {
        "central_question": central,
        "ladder": ladder_rows,
        "open_timeline": open_timeline,
        "gates": {"open_until_final": open_min >= 1,
                  "final_resolves": final_resolves},
        "verdict": "pass" if (open_min >= 1 and final_resolves) else "check",
    }

    # hero recognizability (brief §5)
    hero = shots[0] if shots else {}
    hero_els = manifest.get(str(hero.get("asset")), []) or []
    hero_check = grammar.check_anchors(story_type, hero.get("asset"),
                                       hero_els, plan.get("visual_grammar_plan", {})
                                       .get("subject", ""))

    # duration policy (brief §14): no hard 60s fail; filler candidates only
    total = sum(float(s.get("duration_s") or 0) for s in shots)
    filler = []
    for i in range(1, len(shots)):
        prev = _tok_set(" ".join(str(c.get("text") or "")
                                 for c in (shots[i - 1].get("captions") or [])))
        cur = _tok_set(" ".join(str(c.get("text") or "")
                                for c in (shots[i].get("captions") or [])))
        if prev and cur and len(prev & cur) / max(len(prev | cur), 1) > 0.55:
            filler.append(str(shots[i].get("shot_id")))
    duration_policy = {
        "total_s": round(total, 1),
        "hard_60s_fail": False,
        "filler_candidates": filler,
        "policy": "every beat must earn its place (info gain at qa8); "
                  "length itself is not a defect",
    }

    # grammar validation (brief §4, §16)
    gfindings = []
    for s in shots:
        gfindings += [f"{s.get('shot_id')}: {f}" for f in grammar.validate_states(
            story_type, s["v8"]["states"])]

    v8 = {
        "story_type": story_type,
        "grammar_key": grammar.grammar_key(story_type),
        "state_machine": {"shots_with_states": sum(1 for x in shot_v8s if x["states"]),
                          "needs_state_plate": [str(shots[i].get("shot_id")) for i, x
                                                in enumerate(shot_v8s) if x["needs_state_plate"]]},
        "escalation": escalation,
        "curiosity": curiosity,
        "hero_recognizability": hero_check,
        "duration_policy": duration_policy,
        "grammar_findings": gfindings,
        "actions": actions,
        "warnings": warnings,
    }
    plan["v8"] = {k: v8[k] for k in ("story_type", "grammar_key", "state_machine",
                                     "escalation", "curiosity", "hero_recognizability",
                                     "duration_policy", "grammar_findings")}
    out = Path(paths.build) / out_name
    out.write_text(json.dumps(plan, indent=1) + "\n")
    v8["actions"] = actions
    v8["warnings"] = warnings
    return plan, v8
