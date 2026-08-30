"""script.py — Scriptwriter (Wave 3).

Fills narration text per story beat in a conversational documentary tone,
with target durations (word-count estimate ≈ 155 wpm; refined with real TTS
durations during assembly). LLM path with a deterministic offline fallback.

Output document (results/<id>/script.json):
    {"topic", "beats": [{"beat_id", "role", "goal", "narration",
                         "target_sec", "claim_refs"}...],
     "est_total_sec", "provenance"}
"""

from __future__ import annotations

import logging
from typing import Any

from engine.v3.story.llm import LLMError, ask_json

logger = logging.getLogger(__name__)

SCRIPT_SYSTEM = (
    "You are a documentary narration writer for short YouTube videos. "
    "Tone: conversational documentary — confident, vivid, never academic, "
    "never listy. Hard rules: no 'in this video we will explore'; no "
    "filler; every line earns its seconds; numbers only from the provided "
    "claims; output ONLY valid JSON."
)

WORDS_PER_SEC = 2.6  # ~156 wpm narration estimate


def estimate_duration(text: str) -> float:
    """Word-count duration estimate, clamped to a sane narration beat."""
    words = len([w for w in text.split() if w.strip()])
    return round(min(max(words / WORDS_PER_SEC, 1.5), 45.0), 2)


def write_script(structure: dict, research: dict, *,
                 use_llm: bool = True, max_shots: int | None = None) -> dict:
    """Write narration per beat. Returns the script document."""
    beats = structure.get("beats", [])
    narrations: dict[str, str] | None = None
    errors: list[str] = []
    if use_llm:
        narrations = _llm_script(structure, research, errors)
    if narrations is None:
        narrations = _offline_script(structure, research)

    out_beats: list[dict[str, Any]] = []
    for b in beats:
        text = str(narrations.get(b["beat_id"], "") or "").strip()
        if not text:
            text = _single_fallback(b, research)
        out_beats.append({
            "beat_id": b["beat_id"],
            "role": b["role"],
            "goal": b["goal"],
            "narration": text,
            "target_sec": estimate_duration(text),
            "claim_refs": b.get("claim_refs", []),
        })
    # Optional shot-count cap: fold overflow beats into their predecessor so
    # the shot planner never explodes past --max-shots beats.
    if max_shots and len(out_beats) > max_shots:
        merged = _fold_beats(out_beats, max_shots)
        out_beats = merged
    total = round(sum(b["target_sec"] for b in out_beats), 2)
    return {"topic": structure.get("topic", ""),
            "beats": out_beats, "est_total_sec": total,
            "provenance": "llm" if narrations is not None and not errors
            else "offline_fallback"}


def _fold_beats(beats: list[dict], max_beats: int) -> list[dict]:
    """Deterministically merge the least-structured adjacent beats (role
    escalations fold into neighbours first) until len <= max_beats."""
    beats = [dict(b) for b in beats]
    while len(beats) > max_beats:
        # Prefer merging the shortest escalation beat into the next one.
        idx = None
        for i, b in enumerate(beats):
            if b["role"] == "escalation" and i + 1 < len(beats):
                if idx is None or b["target_sec"] < beats[idx]["target_sec"]:
                    idx = i
        if idx is None:
            idx = len(beats) - 2
        a, nb = beats[idx], beats[idx + 1]
        nb["narration"] = (a["narration"] + " " + nb["narration"]).strip()
        nb["target_sec"] = estimate_duration(nb["narration"])
        nb["claim_refs"] = sorted(set(a["claim_refs"] + nb["claim_refs"]))
        beats.pop(idx)
    return [_reid(i, b) for i, b in enumerate(beats)]


def _reid(i: int, b: dict) -> dict:
    b["beat_id"] = f"B{i + 1:02d}"
    return b


def _llm_script(structure: dict, research: dict,
                errors: list[str]) -> dict[str, str] | None:
    claims = research.get("claims", [])
    claim_lines = "\n".join(f"  [{i}] {c['text']}"
                            for i, c in enumerate(claims))
    beat_lines = "\n".join(
        f"  - {b['beat_id']} ({b['role']}): {b['goal']}"
        for b in structure.get("beats", []))
    prompt = f"""Topic: "{structure.get('topic', '')}"

Story beats (write narration for EACH):
{beat_lines}

Available claims (use these facts; do not invent numbers):
{claim_lines}

Write the narration as STRICT JSON:
{{"beats": {{"{structure['beats'][0]['beat_id']}": "<narration text>", ...}}}}

Rules:
- conversational documentary tone; 8-30 words per beat.
- the hook beat must open mid-thought with the surprise, no greeting.
- no beat says "in this video", "let's explore", "today we".
- end the payoff with a line that lands the meaning, not a summary."""
    try:
        doc = ask_json(SCRIPT_SYSTEM, prompt, temperature=0.7,
                       max_tokens=2000, last_errors=errors)
    except LLMError as exc:
        logger.warning("script LLM failed: %s", exc)
        return None
    out = doc.get("beats")
    if not isinstance(out, dict):
        errors.append("script: LLM doc missing beats map")
        return None
    cleaned = {str(k): str(v).strip() for k, v in out.items()
               if str(v or "").strip()}
    if len(cleaned) < len(structure.get("beats", [])) // 2:
        errors.append("script: too few narrations")
        return None
    return cleaned


def _single_fallback(beat: dict, research: dict) -> str:
    t = research.get("topic", "this story")
    claims = research.get("claims", [])
    role = beat["role"]
    refs = beat.get("claim_refs") or []
    claim = claims[refs[0]]["text"] if refs and refs[0] < len(claims) else (
        claims[0]["text"] if claims else f"this is the story of {t}")
    templates = {
        "hook": f"{claim}",
        "promise": f"And by the end, you'll see what it actually meant — "
                   f"beyond the simple version of {t}.",
        "escalation": f"{claim}",
        "reveal": f"Here's the part that changes everything: {claim}",
        "payoff": f"That's why {t} still matters — it reshaped the world "
                  f"we live in.",
        "callback": f"And it comes back to where we started: {claim}",
        "context": f"{claim}",
        "transition": "But there was another side to this.",
        "outro": f"That is the story of {t}.",
    }
    return templates.get(role, claim)


def _offline_script(structure: dict, research: dict) -> dict[str, str]:
    return {b["beat_id"]: _single_fallback(b, research)
            for b in structure.get("beats", [])}
