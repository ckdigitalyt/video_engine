"""planner.py — Shot planner (Wave 3, directive §3/§4/§5/§16).

Turns the script into a validated shot_v3 shotlist:

 1. beat → shot splitting from narration word counts (narration_start/end;
    refined with real TTS durations at assembly time);
 2. visual director LLM authors shot fields (visual_goal, subject,
    background, camera, motion, composition, text_overlay, sfx,
    music_state, generation_priority, narrative_role, requirement flags)
    constrained by schemas/shot_v3.schema.json — deterministic heuristic
    fallback when every provider fails (§24);
 3. renderer router assigns renderer + fallback_renderer (§5);
 4. reconcile_budget adjusts to the visual budget (§16);
 5. variety enforcement pass (§2B, variety.py).

The LLM authors the VisualSpec; renderers implement it deterministically.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from engine.renderers.budget import BUCKET_RENDERERS, reconcile_budget
from engine.renderers.router import select_renderer
from engine.validation.schema import validate as validate_schema
from engine.v3.plan.variety import INTERRUPT_RENDERER, enforce_variety
from engine.v3.story.llm import LLMError, ask_json

logger = logging.getLogger(__name__)

DIRECTOR_SYSTEM = (
    "You are the visual director of a documentary production. For each shot "
    "you decide how it looks on screen: subject, environment, camera, "
    "motion, composition, overlays, sound. You are constrained by the shot "
    "schema; you do NOT choose the renderer — the router does that from your "
    "requirement flags. Output ONLY valid JSON."
)

WORDS_PER_SHOT = (8, 16)  # 3-6s of narration per shot

MUSIC_STATES = ("silence", "ambient", "build", "peak", "drop", "resolve",
                "sustain")

# narrative_role → default visual treatment (deterministic offline path).
_ROLE_TREATMENT: dict[str, dict[str, Any]] = {
    "hook": {"flags": {"realism": True, "emotional_impact": True},
             "camera": "slow push in from wide", "priority": "hero"},
    "promise": {"flags": {"diagrammatic": True, "text_heavy": True},
                "camera": "static wide with kinetic text", "priority": "low"},
    "escalation": {"flags": {"realism": True, "camera_movement": True},
                   "camera": "drifting aerial", "priority": "normal"},
    "reveal": {"flags": {"realism": True, "emotional_impact": True,
                         "physical_motion": True},
               "camera": "slow close-up push", "priority": "hero"},
    "explanation": {"flags": {"diagrammatic": True},
                    "camera": "locked-off diagram framing",
                    "priority": "normal"},
    "climax": {"flags": {"realism": True, "emotional_impact": True,
                         "physical_motion": True},
               "camera": "dynamic sweep", "priority": "hero"},
    "payoff": {"flags": {"emotional_impact": True, "stylization": True},
               "camera": "wide pull-out", "priority": "normal"},
    "callback": {"flags": {"text_heavy": True, "stylization": True},
                 "camera": "static with title card", "priority": "low"},
    "context": {"flags": {"realism": True}, "camera": "medium static",
                "priority": "normal"},
    "transition": {"flags": {"stylization": True}, "camera": "whip pan",
                   "priority": "low"},
    "outro": {"flags": {"text_heavy": True}, "camera": "static end card",
              "priority": "low"},
}

_ESCALATION_ROTATION = ("AI_IMAGE_MOTION", "MOTION_CANVAS", "STOCK_VIDEO",
                        "PIXIJS", "ARCHIVAL")


def plan_shots(script_doc: dict, style: dict, *, budget: dict | None = None,
               availability: dict[str, bool] | None = None,
               use_llm: bool = True, max_shots: int | None = None,
               seed: int = 0) -> dict:
    """Produce the full shot plan document.

    Returns {"topic", "style", "budget", "shots": [...], "planner_notes",
             "variety_report", "budget_changes"}.
    """
    budget = budget or default_budget()
    availability = availability or {}

    skeleton = _skeleton_shots(script_doc, max_shots)
    directed = _direct_shots(skeleton, script_doc, use_llm=use_llm)

    shots: list[dict] = []
    router_notes: list[dict] = []
    for sk, fields in zip(skeleton, directed):
        shot = _merge_shot(sk, fields, style)
        decision = select_renderer(shot, availability=availability or None)
        shot["renderer"] = decision.renderer_id
        chain = [c for c in decision.fallback_chain
                 if not str(c).startswith("off:") and c != decision.renderer_id]
        shot["fallback_renderer"] = chain[0] if chain else "MOTION_CANVAS"
        shot.setdefault("metadata", {})["router"] = {
            "score": decision.score, "reasons": decision.reasons[:4]}
        if shot["renderer"] == "MANIM" and not shot.get("visualspec"):
            # The visual director did not author a Manim VisualSpec —
            # convert to the offline-capable infographic renderer.
            shot["metadata"]["manim_converted"] = True
            shot["renderer"] = INTERRUPT_RENDERER
            if not shot.get("fallback_renderer"):
                shot["fallback_renderer"] = "MOTION_CANVAS"
        shots.append(shot)
        router_notes.append({"shot_id": shot["shot_id"],
                             "renderer": shot["renderer"],
                             "score": decision.score})

    # Budget reconciliation (§16) — pure greedy pass over router choices.
    recon = reconcile_budget(shots, budget, availability=availability or None)
    for change in recon.changes:
        sid = change["shot_id"]
        for s in shots:
            if s["shot_id"] == sid:
                s["renderer"] = change["to"]
                break
    # Variety enforcement (§2B) — after budget, so interrupts target the
    # final mix; budget drift from interrupts is reported, not hidden.
    shots, v_changes, v_report = enforce_variety(
        shots, availability=availability or None)
    # visual_budget_ref bookkeeping (used by the variety report).
    for s in shots:
        s.setdefault("visual_budget_ref", _bucket_label(s.get("renderer")))

    for shot in shots:
        _fill_narration_refs(shot, skeleton)

    return {
        "topic": script_doc.get("topic", ""),
        "style_name": style.get("style_name", ""),
        "budget": budget,
        "shots": shots,
        "planner_notes": {
            "router": router_notes,
            "budget_changes": recon.changes,
            "budget_notes": recon.notes,
            "budget_bucket_counts": recon.bucket_counts,
            "variety_changes": v_changes,
        },
        "variety_report": v_report,
    }


def _bucket_label(renderer_id: str | None) -> str:
    for bucket, ids in BUCKET_RENDERERS.items():
        if renderer_id in ids:
            return bucket
    return ""


def default_budget() -> dict:
    """§16 example budget scaled to a short video (director may override)."""
    return {
        "hero_ai_video_shots": 1,
        "ai_image_motion_shots": 2,
        "stock_or_archival_shots": 3,
        "motion_canvas_shots": 4,
        "pixijs_shots": 1,
        "manim_shots": 0,
        "pattern_interrupts": 2,
    }


# ── 1. Beat → shot skeleton ──────────────────────────────────────────────────

def _skeleton_shots(script_doc: dict,
                    max_shots: int | None = None) -> list[dict]:
    """Split each beat's narration into ~3-6s shots (word counts).

    When *max_shots* is given, shot counts are allocated per beat
    proportionally to beat duration (every beat keeps ≥1 shot — merged
    shots must never span beats, or narration placement breaks).
    """
    beats = [b for b in script_doc.get("beats", [])
             if str(b.get("narration", "")).strip()]
    alloc = [1] * len(beats)
    if max_shots and len(beats) <= max_shots:
        targets = [max(float(b.get("target_sec", 4.0)), 1e-6)
                   for b in beats]
        total = sum(targets)
        alloc = [max(1, round(max_shots * t / total)) for t in targets]
        while sum(alloc) > max_shots:
            # Trim the beat whose shots are densest (shortest per shot).
            i = min((i for i in range(len(alloc)) if alloc[i] > 1),
                    key=lambda i: (targets[i] / alloc[i], i),
                    default=None)
            if i is None:
                break
            alloc[i] -= 1
    shots: list[dict] = []
    t = 0.0
    for beat, n in zip(beats, alloc):
        words = str(beat["narration"]).split()
        chunks = [words] if n <= 1 else _split_n_chunks(words, n)
        for ci, chunk in enumerate(chunks):
            text = " ".join(chunk)
            dur = round(max(len(chunk) / 2.6, 2.0), 2)
            role = beat["role"] if ci == 0 else (
                "escalation" if beat["role"] in ("hook", "reveal")
                else beat["role"])
            shots.append({
                "shot_id": f"S{len(shots) + 1:02d}",
                "beat_id": beat["beat_id"],
                "role": role,
                "narration": text,
                "narration_start": round(t, 2),
                "narration_end": round(t + dur, 2),
                "duration_sec": dur,
            })
            t += dur
    return shots


def _split_n_chunks(words: list[str], n: int) -> list[list[str]]:
    """Split words into n chunks of near-equal length, preferring
    punctuation boundaries."""
    if n <= 1:
        return [words]
    size = max(1, len(words) // n)
    chunks: list[list[str]] = []
    remaining = list(words)
    while len(chunks) < n - 1 and len(remaining) > size:
        # Take `size` words, extend to the next sentence boundary (max +4).
        take = remaining[:size]
        extra = 0
        while take and extra < 4 and \
                not take[-1].rstrip('.,;!?…"').endswith(("!", "?", ".", ";")) \
                and len(remaining) > len(take):
            take.append(remaining[len(take)])
            extra += 1
        chunks.append(take)
        remaining = remaining[len(take):]
    if remaining:
        if chunks and len(remaining) <= max(2, size // 3):
            chunks[-1].extend(remaining)
        else:
            chunks.append(remaining)
    return chunks


def _chunk_words(words: list[str], lo: int, hi: int) -> list[list[str]]:
    """Split words into chunks of [lo, hi] at natural boundaries."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    for w in words:
        cur.append(w)
        end = w.rstrip('.,;!?…"').endswith(("!", "?", ".", ";"))
        if len(cur) >= lo and (end or len(cur) >= hi):
            chunks.append(cur)
            cur = []
    if cur:
        if chunks and len(cur) < lo // 2:
            chunks[-1].extend(cur)
        else:
            chunks.append(cur)
    return chunks


def _merge_tail(shots: list[dict], max_shots: int) -> list[dict]:
    """Safety fallback: merge the smallest adjacent same-beat pair until
    the count fits (merging across beats would break narration placement,
    so a cross-beat surplus is left as-is and reported by the caller)."""
    shots = [dict(s) for s in shots]
    while len(shots) > max_shots:
        best_i = None
        for i in range(len(shots) - 1):
            if shots[i].get("beat_id") != shots[i + 1].get("beat_id"):
                continue
            combined = shots[i]["duration_sec"] + shots[i + 1]["duration_sec"]
            if best_i is None or combined < \
                    shots[best_i]["duration_sec"] + \
                    shots[best_i + 1]["duration_sec"]:
                best_i = i
        if best_i is None:
            break  # cannot merge without crossing beats — leave as-is
        a, b = shots[best_i], shots[best_i + 1]
        a["narration"] = (a["narration"] + " " + b["narration"]).strip()
        a["duration_sec"] = round(a["duration_sec"] + b["duration_sec"], 2)
        a["narration_end"] = b["narration_end"]
        shots.pop(best_i + 1)
    for i, s in enumerate(shots):
        s["shot_id"] = f"S{i + 1:02d}"
    return shots


# ── 2. Visual director ───────────────────────────────────────────────────────

def _direct_shots(skeleton: list[dict], script_doc: dict, *,
                  use_llm: bool) -> list[dict]:
    """One batched LLM call for all shot fields; heuristic fallback."""
    if use_llm and skeleton:
        try:
            return _llm_direct(skeleton, script_doc)
        except LLMError as exc:
            logger.warning("visual director LLM failed: %s — heuristic "
                           "fallback", exc)
    return [_heuristic_direct(sk, i) for i, sk in enumerate(skeleton)]


def _llm_direct(skeleton: list[dict], script_doc: dict) -> list[dict]:
    """Batched LLM direction: shots are directed in chunks of 8 per call.
    A single call over a full ~25-shot list lands near the output-token
    ceiling and truncates mid-JSON (observed live 2026-08-30: 5842/6000
    completion tokens, borderline) — chunking keeps every call well clear
    and merges results by shot_id."""
    if not skeleton:
        return []
    CHUNK = 8
    merged: dict[str, dict] = {}
    for i in range(0, len(skeleton), CHUNK):
        chunk = skeleton[i:i + CHUNK]
        for shot_id, fields in _llm_direct_chunk(chunk, script_doc).items():
            merged[shot_id] = fields
    out = [dict(merged.get(sk["shot_id"], {})) for sk in skeleton]
    if not any(out):
        raise LLMError("visual director returned no usable shots")
    return out


def _llm_direct_chunk(skeleton: list[dict], script_doc: dict) -> dict[str, dict]:
    sk_lines = []
    for sk in skeleton:
        sk_lines.append(
            f'- {sk["shot_id"]} [{sk["role"]}, {sk["duration_sec"]}s]: '
            f'narration: "{sk["narration"]}"')
    prompt = f"""Topic: "{script_doc.get('topic', '')}"

Shots to direct:
{chr(10).join(sk_lines)}

For EVERY shot, author its visual treatment as STRICT JSON:
{{"shots": [
  {{"shot_id": "S01",
    "visual_goal": "<what the frame must achieve>",
    "subject": "<concrete visual subject, phrased for image/video prompts>",
    "background": "<environment>",
    "camera": "<camera behaviour>",
    "motion": "<in-shot motion>",
    "composition": "<framing, e.g. wide establishing / close-up / overhead>",
    "text_overlay": "<short on-screen text or null>",
    "sfx": ["<cue names like whoosh, rumble, pop>"],
    "music_state": "silence|ambient|build|peak|drop|resolve|sustain",
    "duck_music_db": -12,
    "generation_priority": "low|normal|high|hero",
    "requirements": {{"realism": bool, "physical_motion": bool,
      "math_precision": bool, "character_interaction": bool,
      "emotional_impact": bool, "historical_authenticity": bool,
      "diagrammatic": bool, "camera_movement": bool, "text_heavy": bool,
      "stylization": bool}}
  }}]}}

Rules:
- realism/physical_motion/emotional_impact flags justify expensive AI
  video — reserve them for the 1-2 most important shots (mark those
  generation_priority "hero").
- diagrammatic/text_heavy flags route to motion graphics.
- visual variety is mandatory: consecutive shots must differ in
  composition and camera; add pattern interrupts every few shots.
- subject phrasing must be self-contained (a text-to-image prompt without
  the topic context should still produce the right picture)."""
    doc = ask_json(DIRECTOR_SYSTEM, prompt, temperature=0.6, max_tokens=4000)
    return {str(d.get("shot_id")): d for d in doc.get("shots", [])
            if isinstance(d, dict) and d.get("shot_id")}


def _heuristic_direct(sk: dict, index: int) -> dict:
    """Deterministic shot authoring — coherent, varied, schema-safe."""
    role = sk["role"]
    treat = _ROLE_TREATMENT.get(role, _ROLE_TREATMENT["context"])
    narr = str(sk.get("narration") or "").strip()
    subject = narr if len(narr) <= 160 else narr[:157] + "…"
    # Escalation beats rotate visual media for variety (§2B).
    if role == "escalation":
        rid = _ESCALATION_ROTATION[index % len(_ESCALATION_ROTATION)]
        if rid == "STOCK_VIDEO":
            treat = dict(treat)
            treat["flags"] = {"realism": True, "camera_movement": True}
        elif rid == "MOTION_CANVAS":
            treat = dict(treat)
            treat["flags"] = {"diagrammatic": True, "text_heavy": True}
        elif rid == "PIXIJS":
            treat = dict(treat)
            treat["flags"] = {"stylization": True,
                              "character_interaction": True}
        elif rid == "ARCHIVAL":
            treat = dict(treat)
            treat["flags"] = {"historical_authenticity": True,
                              "realism": True}
        # AI_IMAGE_MOTION keeps the default realism flags.
    music = _music_for_role(role, index)
    overlay = None
    if role in ("hook", "reveal", "payoff", "callback") or treat["flags"].get(
            "text_heavy"):
        words = narr.split()
        overlay = " ".join(words[:6]) if words else None
    return {
        "visual_goal": f"{role}: {narr[:120]}".strip(": "),
        "subject": subject or "abstract atmospheric scene",
        "background": _background_for_role(role),
        "camera": treat["camera"],
        "motion": "subtle continuous motion, no cuts inside the shot",
        "composition": _composition_for_index(index),
        "text_overlay": overlay,
        "sfx": _sfx_for_role(role),
        "music_state": music,
        "duck_music_db": -12,
        "generation_priority": treat["priority"],
        "requirements": dict(treat["flags"]),
    }


def _background_for_role(role: str) -> str:
    return {
        "hook": "vast cinematic environment, atmospheric depth",
        "promise": "clean dark studio backdrop",
        "escalation": "naturalistic environment with dramatic sky",
        "reveal": "intimate close environment with dramatic lighting",
        "payoff": "wide peaceful landscape at golden hour",
        "callback": "minimal dark backdrop",
    }.get(role, "naturalistic documentary environment")


def _composition_for_index(index: int) -> str:
    cycle = ["wide establishing", "medium shot", "close-up detail",
             "medium shot", "overhead graphic", "wide silhouette"]
    return cycle[index % len(cycle)]


def _sfx_for_role(role: str) -> list[str]:
    return {
        "hook": ["whoosh"], "reveal": ["sting"], "climax": ["rumble"],
        "payoff": ["pop"], "transition": ["whoosh"],
    }.get(role, [])


def _music_for_role(role: str, index: int) -> str:
    table = {"hook": "build", "promise": "ambient", "escalation": "build",
             "reveal": "peak", "climax": "peak", "payoff": "resolve",
             "callback": "resolve", "outro": "sustain",
             "transition": "drop", "explanation": "ambient",
             "context": "ambient"}
    return table.get(role, "ambient")


# ── 3. Merge skeleton + director fields into schema-valid shots ─────────────

def _merge_shot(sk: dict, fields: dict, style: dict) -> dict:
    shot = {
        "version": "v3",
        "shot_id": sk["shot_id"],
        "duration_sec": float(sk["duration_sec"]),
        "narration_start": float(sk["narration_start"]),
        "narration_end": float(sk["narration_end"]),
        "narrative_role": sk["role"],
        "visual_goal": str(fields.get("visual_goal") or sk["narration"])[:300],
        "renderer": "",            # router fills
        "fallback_renderer": "",   # router fills
        "style": style.get("style_name", "cinematic_documentary"),
        "subject": str(fields.get("subject") or sk["narration"])[:300],
        "background": str(fields.get("background") or "")[:200],
        "camera": str(fields.get("camera") or "")[:200],
        "motion": str(fields.get("motion") or "")[:200],
        "composition": str(fields.get("composition") or "")[:200],
        "text_overlay": fields.get("text_overlay") or None,
        "sfx": [str(x) for x in (fields.get("sfx") or [])][:4],
        "music_state": fields.get("music_state")
        if fields.get("music_state") in MUSIC_STATES else "ambient",
        "duck_music_db": _clamp(float(fields.get("duck_music_db", -12)
                                      if isinstance(fields.get("duck_music_db"), (int, float)) else -12), -40, 0),
        "asset_requirements": [],
        "generation_priority": fields.get("generation_priority")
        if fields.get("generation_priority") in ("low", "normal", "high",
                                                 "hero") else "normal",
        "qa_requirements": [],
        "metadata": {"beat_id": sk.get("beat_id"), "seed_base": 0},
    }
    req = fields.get("requirements")
    if isinstance(req, dict):
        shot["requirements"] = {k: bool(v) for k, v in req.items()
                                if k in _ALLOWED_REQ and v}
    else:
        shot["requirements"] = {}
    # Schema safety net: repair any drift before it enters the pipeline.
    errs = validate_schema(shot, "shot_v3")
    if errs:
        logger.debug("shot %s schema drift repaired: %s",
                     shot["shot_id"], errs[:3])
        shot = _repair_shot(shot)
    return shot


_ALLOWED_REQ = {
    "realism", "physical_motion", "math_precision", "character_interaction",
    "emotional_impact", "historical_authenticity", "diagrammatic",
    "camera_movement", "text_heavy", "stylization",
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _repair_shot(shot: dict) -> dict:
    """Last-resort deterministic repair so a bad LLM field never kills the
    pipeline: strip unknown keys, coerce duration into range."""
    shot["duration_sec"] = _clamp(float(shot["duration_sec"]), 1.0, 60.0)
    shot.pop("narration", None)  # narration lives in skeleton, not schema
    allowed = {
        "version", "shot_id", "duration_sec", "narration_start",
        "narration_end", "narrative_role", "visual_goal", "renderer",
        "fallback_renderer", "style", "subject", "background", "camera",
        "motion", "composition", "text_overlay", "sfx", "music_state",
        "duck_music_db", "asset_requirements", "generation_priority",
        "qa_requirements", "visual_budget_ref", "requirements", "metadata",
        "visualspec", "seed",
    }
    for k in list(shot):
        if k not in allowed:
            shot.pop(k)
    if not shot.get("narration_start"):
        shot["narration_start"] = 0.0
    if not shot.get("narration_end"):
        shot["narration_end"] = shot["narration_start"] + shot["duration_sec"]
    return shot


def _fill_narration_refs(shot: dict, skeleton: list[dict]) -> None:
    """Keep the narration text with the shot metadata (not in the schema)
    so assembly/QA can align audio without re-splitting."""
    for sk in skeleton:
        if sk["shot_id"] == shot["shot_id"]:
            shot["metadata"]["narration"] = sk["narration"]
            shot["metadata"]["beat_id"] = sk.get("beat_id")
            return


def save_plan(plan: dict, out_path: str | Path) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return p
