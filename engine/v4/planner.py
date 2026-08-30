"""planner.py — V4 two-stage planning hierarchy (directive §5, §12, §13, §14, §24).

The V3 planner asked "what should this shot look like?" and let the router
pick a renderer — which produced the dino_v1 slideshow: 63.5 % frozen
runtime, 0.078 scene-internal events/10s, six dhash-identical Motion Canvas
infographics, and a verbatim narration-repeat text card on a flat frame.

V4 plans in the §5 order — narrative event → viewer perception →
cinematography → motion → renderer LAST — as a structured two-stage flow:

  STAGE A (director LLM, per chunk of shots — no renderer anywhere):
      narrative_event, viewer_perception, cinematography (shot_scale,
      camera_move, transitions), motion (subject/environment/lighting/
      depth), emotional_intent, viewer_attention_target, shot_class,
      text_card. Deterministic heuristic fallback keeps the offline path
      end-to-end.

  STAGE B (deterministic realization):
      shot classes → generation_priority/routing requirements (§12, §7
      AI_VIDEO-first HERO semantics) → renderer via the v3 router →
      micro_events timeline (§4) → class-mix reconciliation (§12) →
      pattern-interrupt enforcement (§14) → show-don't-label post-check
      (§13/§24).

Output shots are validated against schemas/shot_v4.schema.json (backward
compatible with shot_v3 consumers: every v3 field keeps its meaning).
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from engine.renderers.budget import BUCKET_RENDERERS, reconcile_budget
from engine.renderers.router import select_renderer
from engine.validation.schema import validate as validate_schema
from engine.v3.plan.planner import _skeleton_shots, default_budget
from engine.v3.plan.variety import analyze_variety, enforce_variety
from engine.v4.microevents import (
    MICRO_EVENT_KINDS,
    derive_micro_events,
    required_event_count,
    shot_index_of,
)
from engine.v3.story.llm import LLMError, ask_json

logger = logging.getLogger(__name__)

# ask_json is the LLM seam for stage A; tests patch
# engine.v4.planner.ask_json directly (module-level re-binding).

SHOT_SCALES = ("wide", "medium", "close", "macro")
CAMERA_MOVES = ("static", "push_in", "pull_out", "pan", "tilt", "orbit",
                "tracking", "whip", "dolly", "handheld")
SHOT_CLASSES = ("HERO", "EXPLANATORY", "BRIDGE")

# §12 target mix (fraction of shots per class).
CLASS_MIX_TARGETS = {"HERO": (0.20, 0.30), "EXPLANATORY": (0.40, 0.50),
                     "BRIDGE": (0.20, 0.30)}

# §14: significant perceptual change at least every ~5-8 s.
INTERRUPT_MIN_GAP_SEC = 5.0
INTERRUPT_MAX_GAP_SEC = 8.0

# §13: full-screen text cards longer than this need a dramatic-beat
# justification; they may never paraphrase the narration (§24).
TEXT_CARD_MAX_SEC = 1.5
NARRATION_REPEAT_RATIO = 0.60

_HERO_ROLES = {"hook", "reveal", "climax"}
_BRIDGE_ROLES = {"transition", "callback", "promise", "outro"}


# ════════════════════════════════════════════════════════════════════════════
# STAGE A — narrative → perception → cinematography → motion (NO renderer)
# ════════════════════════════════════════════════════════════════════════════

STAGE_A_SYSTEM = (
    "You are the visual director of a cinematic documentary. You plan each "
    "shot in strict order: (1) NARRATIVE EVENT — what is happening; "
    "(2) VIEWER PERCEPTION — what the viewer must see and feel; "
    "(3) CINEMATOGRAPHY — how the camera experiences it; "
    "(4) MOTION — what physically moves. "
    "You do NOT choose renderers, engines, software or file formats — "
    "renderer choice happens in a later stage from your fields. Show, don't "
    "label: prefer a visual event over any on-screen text; on-screen text "
    "must never paraphrase the narration. Output ONLY valid JSON."
)

_STAGE_A_PROMPT = """Topic: "{topic}"

Shots to plan (id, narrative role, duration, narration):
{shot_lines}

For EVERY shot, plan it as STRICT JSON — narrative first, renderer LAST (choose none):
{{"shots": [
  {{"shot_id": "S01",
    "narrative_event": "<what is happening in this shot, one sentence>",
    "viewer_perception": "<what the viewer should see/feel>",
    "shot_scale": "wide|medium|close|macro",
    "camera_move": "static|push_in|pull_out|pan|tilt|orbit|tracking|whip|dolly|handheld",
    "subject_motion": "<what physically moves in-frame>",
    "environment_motion": "<what moves in the environment: wind, dust, water, vegetation>",
    "lighting_change": "<how light changes during the shot>",
    "depth_change": "<how depth/parallax changes>",
    "visual_event": "<the single most important thing that HAPPENS>",
    "transition_in": "<how the shot enters>",
    "transition_out": "<how the shot leaves>",
    "emotional_intent": "<the feeling to evoke>",
    "viewer_attention_target": "<where the eye must be at the peak>",
    "shot_class": "HERO|EXPLANATORY|BRIDGE",
    "text_card": {{"present": false, "text": "", "duration_sec": 0,
                  "justification": "<required only if duration_sec > 1.5: which dramatic beat demands a full-screen text card>"}}
  }}]}}

Rules:
- shot_class HERO = spectacle (real animals, destruction, natural phenomena,
  emotional reaction) — at most ~1 in 4 shots; EXPLANATORY = diagrams/maps/
  infographics; BRIDGE = short transitions and motion graphics.
- Every shot needs at least one concrete VISUAL EVENT — something enters,
  exits, transforms, collides, or the camera/scene changes state.
- text_card present=true is a LAST RESORT and must show something narration
  cannot; it may not restate the narration."""


def _heuristic_stage_a(skeleton: list[dict]) -> list[dict]:
    """Deterministic §5 stage A — offline fallback, still narratively aware.

    Cinematography rotates deterministically per shot so consecutive shots
    differ in scale/camera (the variety pass also guards this), and every
    shot gets a concrete visual_event built from its narration."""
    out: list[dict] = []
    scale_cycle = ["wide", "medium", "close", "medium", "wide", "macro"]
    camera_by_class = {
        "HERO": ("push_in", "tracking", "whip", "dolly", "orbit"),
        "EXPLANATORY": ("pan", "tilt", "push_in", "static", "pull_out"),
        "BRIDGE": ("pan", "whip", "pull_out", "static", "push_in"),
    }
    for i, sk in enumerate(skeleton):
        narr = str(sk.get("narration") or "").strip()
        role = str(sk.get("role") or "context")
        shot_class = classify_shot_class({"narrative_role": role,
                                          "duration_sec": sk.get("duration_sec")})
        subject = narr if len(narr) <= 160 else narr[:157] + "…"
        words = [w for w in re.findall(r"[a-z']{4,}", narr.lower())]
        event_verb = (words[0] if words else "the subject") + " enters and the scene responds"
        transition_out = "cut to next beat" if shot_class != "BRIDGE" else "whip cut"
        out.append({
            "shot_id": sk["shot_id"],
            "narrative_event": narr[:200] or "the beat's core claim visualised",
            "viewer_perception": f"{role}: the viewer watches {subject[:120]}",
            "shot_scale": scale_cycle[i % len(scale_cycle)],
            "camera_move": camera_by_class[shot_class][i % 5],
            "subject_motion": "primary subject moves through frame" if shot_class == "HERO"
            else "subject shifts subtly within frame",
            "environment_motion": "atmospheric particles and ambient wind" if shot_class == "HERO"
            else "light ambient drift",
            "lighting_change": ("dramatic key light sweeps" if shot_class == "HERO"
                                else "steady soft light with slow shift"),
            "depth_change": "parallax deepens toward the subject",
            "visual_event": event_verb,
            "transition_in": "cut in" if i == 0 else "match cut",
            "transition_out": transition_out,
            "emotional_intent": {"HERO": "awe and urgency", "EXPLANATORY": "clarity",
                                 "BRIDGE": "momentum"}[shot_class],
            "viewer_attention_target": "the moving subject",
            "shot_class": shot_class,
            "text_card": {"present": False, "text": "", "duration_sec": 0,
                          "justification": ""},
        })
    return out


def _llm_stage_a(skeleton: list[dict], script_doc: dict) -> list[dict]:
    """§5 stage A via the director LLM, chunked (8 shots/call) to stay clear
    of output-token ceilings (observed live 2026-08-30 on the v3 path)."""
    CHUNK = 8
    merged: dict[str, dict] = {}
    for i in range(0, len(skeleton), CHUNK):
        chunk = skeleton[i:i + CHUNK]
        shot_lines = "\n".join(
            f'- {sk["shot_id"]} [{sk["role"]}, {sk["duration_sec"]}s]: '
            f'"{sk["narration"]}"' for sk in chunk)
        prompt = _STAGE_A_PROMPT.format(
            topic=script_doc.get("topic", ""), shot_lines=shot_lines)
        doc = ask_json(STAGE_A_SYSTEM, prompt, temperature=0.6, max_tokens=3500)
        for d in doc.get("shots", []) or []:
            if isinstance(d, dict) and d.get("shot_id"):
                merged[str(d["shot_id"])] = d
    if not merged:
        raise LLMError("stage A returned no usable shots")
    return [merged.get(sk["shot_id"], {}) for sk in skeleton]


def _clamp_stage_a(fields: dict, sk: dict) -> dict:
    """Repair LLM drift: clamp enums, drop renderer mentions, guarantee the
    required fields exist (heuristic values fill holes)."""
    base = _heuristic_stage_a([sk])[0]
    out = dict(base)
    if not isinstance(fields, dict):
        return out
    for key in ("narrative_event", "viewer_perception", "subject_motion",
                "environment_motion", "lighting_change", "depth_change",
                "visual_event", "transition_in", "transition_out",
                "emotional_intent", "viewer_attention_target"):
        val = str(fields.get(key) or "").strip()
        if val:
            out[key] = val[:240]
    if fields.get("shot_scale") in SHOT_SCALES:
        out["shot_scale"] = fields["shot_scale"]
    if fields.get("camera_move") in CAMERA_MOVES:
        out["camera_move"] = fields["camera_move"]
    if fields.get("shot_class") in SHOT_CLASSES:
        out["shot_class"] = fields["shot_class"]
    else:
        out["shot_class"] = classify_shot_class(
            {"narrative_role": sk.get("role"),
             "duration_sec": sk.get("duration_sec")})
    tc = fields.get("text_card")
    if isinstance(tc, dict) and tc.get("present"):
        out["text_card"] = {
            "present": True,
            "text": str(tc.get("text") or "")[:80],
            "duration_sec": min(3.0, max(0.5, float(tc.get("duration_sec") or 1.0))),
            "justification": str(tc.get("justification") or "")[:200],
        }
    else:
        out["text_card"] = {"present": False, "text": "", "duration_sec": 0,
                            "justification": ""}
    return out


# ════════════════════════════════════════════════════════════════════════════
# Shot classes (§12)
# ════════════════════════════════════════════════════════════════════════════

def classify_shot_class(shot: dict) -> str:
    """Deterministic HERO/EXPLANATORY/BRIDGE classification (§12).

    HERO      — spectacle: hook/reveal/climax roles or realism+motion+impact
    BRIDGE    — transitions/short connective shots (< 2.5 s)
    otherwise — EXPLANATORY
    """
    role = str(shot.get("narrative_role") or shot.get("role") or "")
    duration = float(shot.get("duration_sec") or 0)
    req = shot.get("requirements") or {}
    if role in _HERO_ROLES or req.get("realism") and req.get("physical_motion") \
            and req.get("emotional_impact"):
        return "HERO"
    if role in _BRIDGE_ROLES or duration < 2.5:
        return "BRIDGE"
    return "EXPLANATORY"


def class_fractions(shots: list[dict]) -> dict[str, float]:
    n = max(1, len(shots))
    counts = {c: 0 for c in SHOT_CLASSES}
    for s in shots:
        c = s.get("shot_class") or classify_shot_class(s)
        counts[c] = counts.get(c, 0) + 1
    return {c: round(v / n, 3) for c, v in counts.items()}


def reconcile_class_mix(shots: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Enforce the §12 target mix (HERO 20-30 %, EXPLANATORY 40-50 %,
    BRIDGE 20-30 %) by reclassifying boundary shots.

    Reclassification is legitimate planning correction (the classes are a
    production plan, not ground truth): excess HERO demotes the least
    spectacle-critical shots to EXPLANATORY; a HERO shortfall promotes the
    most spectacle-capable EXPLANATORY shots (adds realism/impact
    requirements + generation_priority=hero, which routes them AI_VIDEO-
    first at §7). Fractions that cannot be met without inventing spectacle
    are reported honestly as notes, never faked.
    """
    changes: list[dict] = []
    notes: list[str] = []
    n = len(shots)
    if n == 0:
        return shots, changes, {"fractions": {}, "notes": notes}

    def frac(cls: str) -> float:
        return sum(1 for s in shots if s.get("shot_class") == cls) / n

    def set_class(shot: dict, cls: str, reason: str) -> None:
        old = shot.get("shot_class")
        if old == cls:
            return
        shot["shot_class"] = cls
        if cls == "HERO":
            shot["generation_priority"] = "hero"
            req = shot.setdefault("requirements", {})
            req["realism"] = True
            req["physical_motion"] = True
            req["emotional_impact"] = True
            req["spectacle"] = True
            req["cinematic"] = True
        elif old == "HERO":
            shot["generation_priority"] = "normal"
        changes.append({"shot_id": shot.get("shot_id"), "field": "shot_class",
                        "from": old, "to": cls, "reason": reason})

    hero_lo, hero_hi = CLASS_MIX_TARGETS["HERO"]
    expl_lo, expl_hi = CLASS_MIX_TARGETS["EXPLANATORY"]
    bridge_lo, bridge_hi = CLASS_MIX_TARGETS["BRIDGE"]

    # HERO overshoot → demote non-critical HERO shots.
    for s in [s for s in shots if s.get("shot_class") == "HERO"]:
        if frac("HERO") <= hero_hi:
            break
        if str(s.get("narrative_role")) in _HERO_ROLES:
            continue  # hook/reveal/climax stay HERO (narrative spine)
        set_class(s, "EXPLANATORY", "class mix: HERO over 30 %")

    # HERO shortfall → promote spectacle-capable EXPLANATORY shots.
    if frac("HERO") < hero_lo:
        candidates = [s for s in shots
                      if s.get("shot_class") == "EXPLANATORY"
                      and str(s.get("narrative_role")) not in _BRIDGE_ROLES]
        candidates.sort(key=lambda s: (
            str(s.get("narrative_role")) in ("escalation", "payoff"),
            -float(s.get("duration_sec") or 0)), reverse=True)
        promoted_any = False
        for s in candidates:
            if frac("HERO") >= hero_lo:
                break
            set_class(s, "HERO", "class mix: HERO under 20 % — promoted")
            promoted_any = True
        if not promoted_any:
            notes.append(
                f"HERO fraction {frac('HERO'):.0%} below target "
                f"{hero_lo:.0%}-{hero_hi:.0%}: no shot can carry spectacle "
                "without inventing content (reported, not faked)")

    # BRIDGE bounds — reclassify by duration.
    for s in shots:
        f = frac("BRIDGE")
        if f <= bridge_hi and f >= bridge_lo:
            break
        if s.get("shot_class") == "BRIDGE" and f > bridge_hi:
            if float(s.get("duration_sec") or 0) >= 2.5:
                set_class(s, "EXPLANATORY", "class mix: BRIDGE over 30 %")
        elif s.get("shot_class") == "EXPLANATORY" and f < bridge_lo:
            if float(s.get("duration_sec") or 0) < 2.5:
                set_class(s, "BRIDGE", "class mix: BRIDGE under 20 %")

    # EXPLANATORY lower bound: demote surplus BRIDGE to EXPLANATORY.
    if frac("EXPLANATORY") < expl_lo:
        for s in shots:
            if frac("EXPLANATORY") >= expl_lo:
                break
            if s.get("shot_class") == "BRIDGE" and \
                    float(s.get("duration_sec") or 0) >= 2.5 and \
                    str(s.get("narrative_role")) not in _BRIDGE_ROLES:
                set_class(s, "EXPLANATORY", "class mix: EXPLANATORY under 40 %")

    fractions = class_fractions(shots)
    report = {"fractions": fractions, "targets": CLASS_MIX_TARGETS,
              "changes": changes, "notes": notes}
    return shots, changes, report


# ════════════════════════════════════════════════════════════════════════════
# Show-don't-label (§13, §24)
# ════════════════════════════════════════════════════════════════════════════

def _narrations(shots: list[dict]) -> list[str]:
    return [str(s.get("metadata", {}).get("narration") or "").strip()
            for s in shots]


def _overlay_text(shot: dict) -> str:
    tc = shot.get("text_card") or {}
    if isinstance(tc, dict) and tc.get("present") and tc.get("text"):
        return str(tc["text"])
    return str(shot.get("text_overlay") or "")


def text_card_issues(shots: list[dict]) -> list[str]:
    """§13/§24 planner post-check (no repair — see repair_text_cards).

    Fails when:
      * on-screen text paraphrases/repeats the narration (verbatim or
        high-similarity) — the visual must carry the explanation;
      * a text card runs > 1.5 s without a dramatic-beat justification;
      * a text card exists on a shot with zero micro events (a label
        standing in for a missing visual).
    """
    issues: list[str] = []
    narrations = _narrations(shots)
    for shot, narr in zip(shots, narrations):
        sid = shot.get("shot_id", "?")
        overlay = _overlay_text(shot)
        if not overlay:
            continue
        low_overlay = overlay.lower().strip()
        if narr:
            low_narr = narr.lower()
            if low_overlay in low_narr or low_narr in low_overlay:
                issues.append(
                    f"{sid}: on-screen text {overlay[:60]!r} repeats the "
                    "narration verbatim (§24)")
            else:
                ratio = SequenceMatcher(None, low_overlay,
                                        low_narr[: len(low_overlay) * 2]).ratio()
                if ratio >= NARRATION_REPEAT_RATIO:
                    issues.append(
                        f"{sid}: on-screen text {overlay[:60]!r} paraphrases "
                        f"the narration (similarity {ratio:.0%}, §24)")
        dur = float((shot.get("text_card") or {}).get("duration_sec") or 0)
        if dur > TEXT_CARD_MAX_SEC and \
                not str((shot.get("text_card") or {}).get("justification") or "").strip():
            issues.append(
                f"{sid}: text card {dur:.1f}s > {TEXT_CARD_MAX_SEC}s without "
                "dramatic-beat justification (§13)")
        if not shot.get("micro_events"):
            issues.append(
                f"{sid}: text card with zero micro_events — show the claim "
                "instead of labelling it (§13)")
    return issues


def repair_text_cards(shots: list[dict]) -> tuple[list[dict], list[dict]]:
    """Auto-repair §13/§24 violations: strip narration-repeating overlays
    and unjustified long cards (converted into an attention-target note so
    the slot becomes a visual, not a label)."""
    repairs: list[dict] = []
    issues = set(text_card_issues(shots))
    narrations = _narrations(shots)
    for shot, narr in zip(shots, narrations):
        sid = shot.get("shot_id", "?")
        overlay = _overlay_text(shot)
        if not overlay:
            continue
        violated = any(i.startswith(f"{sid}:") for i in issues)
        if not violated:
            continue
        low_overlay = overlay.lower().strip()
        verbatim = bool(narr) and (low_overlay in narr.lower()
                                   or narr.lower() in low_overlay)
        old = shot.get("text_overlay")
        if verbatim or not str((shot.get("text_card") or {}).get(
                "justification") or "").strip():
            shot["text_overlay"] = None
            shot["text_card"] = {"present": False, "text": "",
                                 "duration_sec": 0, "justification": ""}
            repairs.append({"shot_id": sid, "field": "text_overlay",
                            "from": old, "to": None,
                            "reason": "show-don't-label: narration-repeat or "
                                      "unjustified card stripped (§13/§24)"})
    return shots, repairs


# ════════════════════════════════════════════════════════════════════════════
# Pattern interrupts (§14)
# ════════════════════════════════════════════════════════════════════════════

_MEDIUM_CLASS = {
    "AI_VIDEO": "realistic", "AI_IMAGE_MOTION": "realistic",
    "STOCK_VIDEO": "realistic", "ARCHIVAL": "realistic",
    "MOTION_CANVAS": "diagram", "MANIM": "diagram",
    "PIXIJS": "cartoon", "GODOT": "realistic", "OPEN_TOONZ": "cartoon",
}


def perceptual_signature(shot: dict) -> tuple:
    """The §14 perceptual class of a shot: medium, scale, brightness, motion.

    A significant pattern interrupt = any component changes between
    consecutive shots (live→animation, wide→close, bright→dark, motion→
    freeze, character→diagram…)."""
    renderer = str(shot.get("renderer") or "")
    medium = _MEDIUM_CLASS.get(renderer, renderer or "unknown")
    scale = str(shot.get("shot_scale") or "")
    lighting = str(shot.get("lighting_change") or "").lower()
    brightness = "dark" if any(w in lighting for w in ("dark", "fade", "dim", "blocked")) \
        else ("bright" if any(w in lighting for w in ("bright", "flash", "sun", "glow"))
              else "neutral")
    motion = "moving" if (str(shot.get("camera_move") or "static") != "static"
                          or str(shot.get("subject_motion") or "").strip()
                          or str(shot.get("environment_motion") or "").strip()) \
        else "calm"
    return (medium, scale, brightness, motion)


def pattern_interrupt_report(shots: list[dict]) -> dict:
    """Measure the runtime gaps between significant perceptual changes."""
    gaps: list[float] = []
    changes: list[float] = [0.0]
    prev: tuple | None = None
    t = 0.0
    for s in shots:
        sig = perceptual_signature(s)
        if prev is not None and sig != prev:
            changes.append(round(t, 2))
        prev = sig
        t += float(s.get("duration_sec") or 0)
    for a, b in zip(changes, changes[1:]):
        gaps.append(round(b - a, 2))
    tail = round(t - changes[-1], 2) if changes else 0.0
    over = [g for g in gaps + ([tail] if tail > INTERRUPT_MAX_GAP_SEC else [])
            if g > INTERRUPT_MAX_GAP_SEC]
    return {
        "change_times": changes,
        "gaps": gaps,
        "max_gap_sec": max(gaps + [tail]) if (gaps or tail) else 0.0,
        "gaps_over_max": over,
        "min_gap_sec": INTERRUPT_MIN_GAP_SEC,
        "max_gap_sec_limit": INTERRUPT_MAX_GAP_SEC,
        "satisfied": not over,
    }


def _continuous(shot: dict, index: int, shots: list[dict]) -> bool:
    """Narrative-aware exemption (§14: interrupts must not shatter a
    deliberate continuous sequence — hero sequences, matched cuts)."""
    if shot.get("metadata", {}).get("continuous_sequence"):
        return True
    if index > 0 and shots[index - 1].get("metadata", {}).get(
            "continuous_sequence") and index + 1 < len(shots) and \
            shots[index + 1].get("metadata", {}).get("continuous_sequence"):
        return True
    return False


def enforce_pattern_interrupts(shots: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """§14 enforcement + repair pass.

    Walks the timeline; whenever a run longer than INTERRUPT_MAX_GAP_SEC
    passes with no perceptual change, repairs the midpoint shot (skipping
    narrative-protected shots) by changing, in order of preference:
    shot_scale → camera_move → medium (renderer). Deterministic."""
    changes: list[dict] = []
    scales = SHOT_SCALES
    moves = [m for m in CAMERA_MOVES if m != "static"]
    for _pass in range(len(shots) + 1):  # bounded repair attempts
        report = pattern_interrupt_report(shots)
        if report["satisfied"]:
            break
        # find the longest offending gap and repair its midpoint
        change_times = report["change_times"]
        total = sum(float(s.get("duration_sec") or 0) for s in shots)
        bounds = change_times + [round(total, 2)]
        best = None  # (gap, start, end)
        for a, b in zip(bounds, bounds[1:]):
            gap = b - a
            if gap > INTERRUPT_MAX_GAP_SEC and (best is None or gap > best[0]):
                best = (gap, a, b)
        if best is None:
            break
        _gap, a, b = best
        t_mid = (a + b) / 2.0
        acc = 0.0
        mid_idx = None
        for i, s in enumerate(shots):
            acc += float(s.get("duration_sec") or 0)
            if acc >= t_mid:
                mid_idx = i
                break
        if mid_idx is None or _continuous(shots[mid_idx], mid_idx, shots):
            # try neighbouring shots before giving up on this gap
            for alt in range(len(shots)):
                cand = (mid_idx + (alt if alt % 2 else -alt)) % len(shots)
                if not _continuous(shots[cand], cand, shots) and \
                        a <= sum(float(x.get("duration_sec") or 0)
                                 for x in shots[:cand + 1]) - 0.01 and \
                        cand != 0:
                    mid_idx = cand
                    break
            else:
                break
        s = shots[mid_idx]
        i = shot_index_of(s)
        prev_sig = perceptual_signature(shots[mid_idx - 1]) if mid_idx else None
        repaired = False
        # 1. scale change
        new_scale = scales[(scales.index(s.get("shot_scale", "wide")) + 2) % len(scales)] \
            if s.get("shot_scale") in scales else scales[i % len(scales)]
        if new_scale != s.get("shot_scale"):
            old = s.get("shot_scale")
            s["shot_scale"] = new_scale
            changes.append({"shot_id": s.get("shot_id"), "field": "shot_scale",
                            "from": old, "to": new_scale,
                            "reason": "pattern interrupt: scale change (§14)"})
            repaired = True
        # 2. camera change
        if not repaired or perceptual_signature(s) == prev_sig:
            new_move = moves[(moves.index(s["camera_move"]) + 1) % len(moves)] \
                if s.get("camera_move") in moves else moves[i % len(moves)]
            if new_move != s.get("camera_move"):
                old = s.get("camera_move")
                s["camera_move"] = new_move
                changes.append({"shot_id": s.get("shot_id"),
                                "field": "camera_move", "from": old,
                                "to": new_move,
                                "reason": "pattern interrupt: camera change (§14)"})
                repaired = True
        if repaired and perceptual_signature(s) != prev_sig:
            continue  # gap repaired; re-measure on the next loop pass
        # 3. medium change (renderer) — last resort
        old_rid = s.get("renderer")
        alt = s.get("fallback_renderer") or "PIXIJS"
        if alt and alt != old_rid:
            s["renderer"] = alt
            s.setdefault("metadata", {})["pattern_interrupt"] = True
            changes.append({"shot_id": s.get("shot_id"), "field": "renderer",
                            "from": old_rid, "to": alt,
                            "reason": "pattern interrupt: medium change (§14)"})
    report = pattern_interrupt_report(shots)
    return shots, changes, report


# ════════════════════════════════════════════════════════════════════════════
# STAGE B — renderer LAST + micro events
# ════════════════════════════════════════════════════════════════════════════

def _stage_b_requirements(fields: dict, shot_class: str) -> dict:
    """Map stage-A cinematography to router requirement flags (§7/§18)."""
    req: dict[str, bool] = {}
    if shot_class == "HERO":
        req.update(realism=True, physical_motion=True, emotional_impact=True,
                   spectacle=True, cinematic=True, camera_movement=True)
    else:
        ve = str(fields.get("visual_event") or "").lower()
        if any(w in ve for w in ("enters", "exits", "impact", "transform",
                                 "collide", "erupt")):
            req.update(physical_motion=True)
        if str(fields.get("subject_motion") or "").strip():
            req.update(physical_motion=True)
        if str(fields.get("camera_move") or "static") != "static":
            req.update(camera_movement=True)
        if shot_class == "EXPLANATORY":
            req.update(diagrammatic=True)
    return req


def _stage_b(shots: list[dict], availability: dict[str, bool] | None,
             use_llm: bool, only_ids: set[str] | None = None,
             *, refresh_events: bool = True) -> tuple[list[dict], list[dict]]:
    """Realize stage A into renderer + micro_events (renderer LAST, §5).

    *only_ids* restricts re-routing to the given shot ids (used by the
    post-class-mix pass so budget decisions are not silently undone)."""
    routing_changes: list[dict] = []
    for shot in shots:
        shot_class = shot.get("shot_class") or classify_shot_class(shot)
        shot["shot_class"] = shot_class
        shot.setdefault("requirements", {})
        for k, v in _stage_b_requirements(shot, shot_class).items():
            if v:
                shot["requirements"][k] = True
        if shot_class == "HERO":
            shot["generation_priority"] = "hero"
            # §7: AI_VIDEO → intelligent retry → another AI_VIDEO provider →
            # then downgrade. The chain itself is recorded at render time;
            # the policy travels with the shot so the runner can honour it.
            shot.setdefault("metadata", {})["ai_video_policy"] = {
                "preferred": True,
                "order": ["AI_VIDEO", "AI_VIDEO_retry_intelligent",
                          "AI_VIDEO_alt_provider",
                          "AI_IMAGE_MOTION (downgrade)"],
                "record": ["attempted_provider", "failure_reason",
                           "fallback_reason"],
            }
        if refresh_events:
            micro = shot.get("micro_events") or derive_micro_events(shot)
            shot["micro_events"] = micro
            shot.setdefault("metadata", {})["event_density"] = {
                "events": len(micro),
                "required": required_event_count(float(shot.get("duration_sec") or 0)),
            }

        if only_ids is not None and shot.get("shot_id") not in only_ids:
            continue
        # Renderer LAST (§5): route from the *final* requirements.
        old_renderer = shot.get("renderer") or ""
        decision = select_renderer(shot, availability=availability or None)
        if decision.renderer_id != old_renderer:
            routing_changes.append({
                "shot_id": shot.get("shot_id"), "field": "renderer",
                "from": old_renderer, "to": decision.renderer_id,
                "reason": "stage B re-route from cinematography (§5/§7): "
                          + "; ".join(decision.reasons[:2])})
        shot["renderer"] = decision.renderer_id
        chain = [c for c in decision.fallback_chain
                 if not str(c).startswith("off:") and c != decision.renderer_id]
        if chain:
            shot["fallback_renderer"] = chain[0]
        shot.setdefault("metadata", {})["router"] = {
            "score": decision.score, "reasons": decision.reasons[:4]}
    return shots, routing_changes


# ════════════════════════════════════════════════════════════════════════════
# Main entry
# ════════════════════════════════════════════════════════════════════════════

def plan_shots_v4(script_doc: dict, style: dict, *, budget: dict | None = None,
                  availability: dict[str, bool] | None = None,
                  use_llm: bool = True, max_shots: int | None = None,
                  seed: int = 0) -> dict:
    """Produce the V4 shot plan document (two-stage §5 hierarchy).

    Wraps the proven v3 pipeline (skeleton → router → budget → variety) and
    re-plans it through stage A/B, upgrading every shot to shot_v4.
    """
    budget = budget or default_budget()
    availability = availability or {}

    # Base skeleton (same as v3 — narration placement is load-bearing).
    skeleton = _skeleton_shots(script_doc, max_shots)

    # ── STAGE A ── narrative → perception → cinematography → motion ──
    stage_a_source = "heuristic"
    if use_llm and skeleton:
        try:
            stage_a = [_clamp_stage_a(f, sk)
                       for f, sk in zip(_llm_stage_a(skeleton, script_doc),
                                        skeleton)]
            stage_a_source = "llm"
        except LLMError as exc:
            logger.warning("stage A LLM failed: %s — heuristic fallback", exc)
            stage_a = _heuristic_stage_a(skeleton)
    else:
        stage_a = _heuristic_stage_a(skeleton)

    shots: list[dict] = []
    for sk, fields in zip(skeleton, stage_a):
        shot = _v4_shot_from_skeleton(sk, fields, style)
        shots.append(shot)

    # ── STAGE B ── renderer LAST + micro events ──
    shots, routing_changes = _stage_b(shots, availability, use_llm)

    # Budget reconciliation (§16) over the stage-B assignments.
    recon = reconcile_budget(shots, budget, availability=availability or None)
    budget_changes: list[dict] = []
    for change in recon.changes:
        sid = change["shot_id"]
        for s in shots:
            if s["shot_id"] == sid and s.get("renderer") != change["to"]:
                old = s.get("renderer")
                s["renderer"] = change["to"]
                s.setdefault("metadata", {})["budget_demoted"] = True
                budget_changes.append({**change, "from": old})
                break

    # §12 class mix.
    shots, class_changes, class_report = reconcile_class_mix(shots)
    # Re-route ONLY class-changed shots (their requirements changed); a full
    # re-pass would undo budget reconciliation decided above.
    changed_ids = {c["shot_id"] for c in class_changes}
    if changed_ids:
        shots, reroute = _stage_b(shots, availability, use_llm,
                                  only_ids=changed_ids, refresh_events=False)
        routing_changes += reroute

    # Variety enforcement (§2B) on the final renderer mix.
    shots, v_changes, _ = enforce_variety(shots, availability=availability or None)

    # §14 pattern interrupts.
    shots, pi_changes, pi_report = enforce_pattern_interrupts(shots)

    # §13/§24 show-don't-label post-check + repair.
    shots, label_repairs = repair_text_cards(shots)
    label_issues = text_card_issues(shots)

    # Fresh micro-event density (camera/scale rewrites may need topping up).
    for s in shots:
        s["micro_events"] = derive_micro_events(s)
        s.setdefault("metadata", {})["event_density"] = {
            "events": len(s["micro_events"]),
            "required": required_event_count(float(s.get("duration_sec") or 0)),
        }

    # Schema safety net.
    for s in shots:
        errs = validate_schema(s, "shot_v4")
        if errs:
            logger.debug("shot %s v4 schema drift repaired: %s",
                         s["shot_id"], errs[:3])
            s = _repair_v4_shot(s)
    shots = [_repair_v4_shot(s) for s in shots]

    for shot in shots:
        _fill_narration_refs(shot, skeleton)

    variety_report = analyze_variety(shots)
    return {
        "version": "v4",
        "topic": script_doc.get("topic", ""),
        "style_name": style.get("style_name", ""),
        "budget": budget,
        "shots": shots,
        "planning_hierarchy": {
            "stage_a": {"source": stage_a_source,
                        "order": ["narrative_event", "viewer_perception",
                                  "cinematography", "motion"],
                        "renderer_position": "last"},
            "stage_b": {"routing_changes": routing_changes,
                        "budget_changes": budget_changes,
                        "class_changes": class_changes},
        },
        "class_mix_report": class_report,
        "pattern_interrupt_report": pi_report,
        "pattern_interrupt_changes": pi_changes,
        "label_check": {"issues": label_issues, "repairs": label_repairs},
        "planner_notes": {
            "budget_changes": budget_changes,
            "budget_notes": recon.notes,
            "budget_bucket_counts": recon.bucket_counts,
            "variety_changes": v_changes,
            "routing_changes": routing_changes,
        },
        "variety_report": variety_report,
    }


def _v4_shot_from_skeleton(sk: dict, fields: dict, style: dict) -> dict:
    """Build a shot_v4 dict from the skeleton + stage-A fields."""
    tc = fields.get("text_card") or {}
    overlay = None
    if isinstance(tc, dict) and tc.get("present") and tc.get("text"):
        overlay = str(tc["text"])
        dur = float(sk.get("duration_sec") or 0)
        tc = {**tc, "duration_sec": min(float(tc.get("duration_sec") or 1.0), dur)}
    shot_class = fields.get("shot_class") or classify_shot_class(
        {"narrative_role": sk.get("role"),
         "duration_sec": sk.get("duration_sec")})
    shot = {
        "version": "v4",
        "shot_id": sk["shot_id"],
        "duration_sec": float(sk["duration_sec"]),
        "narration_start": float(sk.get("narration_start", 0.0)),
        "narration_end": float(sk.get("narration_end", 0.0)),
        "narrative_role": sk["role"],
        "visual_goal": str(fields.get("narrative_event")
                           or sk.get("narration") or "")[:300],
        "renderer": "",            # stage B fills (renderer LAST, §5)
        "fallback_renderer": "",
        "style": style.get("style_name", "cinematic_documentary"),
        "subject": str(fields.get("viewer_perception")
                       or sk.get("narration") or "")[:300],
        "background": "cinematic environment with depth",
        "camera": str(fields.get("camera_move") or "static"),
        "motion": str(fields.get("subject_motion") or "")[:200],
        "composition": str(fields.get("shot_scale") or "medium"),
        "text_overlay": overlay,
        "sfx": [],
        "music_state": "ambient",
        "duck_music_db": -12,
        "asset_requirements": [],
        "generation_priority": "hero" if shot_class == "HERO" else "normal",
        "qa_requirements": [],
        # ── v4 cinematography fields (§6) ──
        "shot_scale": fields.get("shot_scale") or "medium",
        "camera_move": fields.get("camera_move") or "static",
        "subject_motion": fields.get("subject_motion") or "",
        "environment_motion": fields.get("environment_motion") or "",
        "lighting_change": fields.get("lighting_change") or "",
        "depth_change": fields.get("depth_change") or "",
        "visual_event": fields.get("visual_event") or "",
        "transition_in": fields.get("transition_in") or "",
        "transition_out": fields.get("transition_out") or "",
        "emotional_intent": fields.get("emotional_intent") or "",
        "viewer_attention_target": fields.get("viewer_attention_target") or "",
        "shot_class": shot_class,
        "text_card": tc if isinstance(tc, dict) else None,
        "metadata": {"beat_id": sk.get("beat_id"), "seed_base": 0,
                     "stage_a": fields.get("_source", "heuristic")},
    }
    return shot


def _fill_narration_refs(shot: dict, skeleton: list[dict]) -> None:
    for sk in skeleton:
        if sk["shot_id"] == shot["shot_id"]:
            shot["metadata"]["narration"] = sk["narration"]
            shot["metadata"]["beat_id"] = sk.get("beat_id")
            return


def _repair_v4_shot(shot: dict) -> dict:
    """Last-resort deterministic repair (strip unknown keys, clamp enums)."""
    shot["duration_sec"] = max(1.0, min(60.0, float(shot["duration_sec"])))
    allowed = {
        "version", "shot_id", "duration_sec", "narration_start",
        "narration_end", "narrative_role", "visual_goal", "renderer",
        "fallback_renderer", "style", "subject", "background", "camera",
        "motion", "composition", "text_overlay", "sfx", "music_state",
        "duck_music_db", "asset_requirements", "generation_priority",
        "qa_requirements", "visual_budget_ref", "requirements", "metadata",
        "visualspec", "seed", "micro_events", "shot_scale", "camera_move",
        "subject_motion", "environment_motion", "lighting_change",
        "depth_change", "visual_event", "transition_in", "transition_out",
        "emotional_intent", "viewer_attention_target", "shot_class",
        "text_card",
    }
    for k in list(shot):
        if k not in allowed:
            shot.pop(k)
    if shot.get("camera_move") not in CAMERA_MOVES:
        shot["camera_move"] = "static"
    if shot.get("shot_scale") not in SHOT_SCALES:
        shot["shot_scale"] = "medium"
    if shot.get("shot_class") not in SHOT_CLASSES:
        shot["shot_class"] = classify_shot_class(shot)
    micro = shot.get("micro_events")
    if isinstance(micro, list):
        clean = []
        for e in micro:
            if not isinstance(e, dict) or not e.get("event"):
                continue
            e = {k: e[k] for k in ("t", "duration", "event", "kind", "intensity")
                 if k in e}
            if e.get("kind") not in MICRO_EVENT_KINDS:
                e.pop("kind", None)
            clean.append(e)
        shot["micro_events"] = clean
    else:
        shot.pop("micro_events", None)
    return shot
