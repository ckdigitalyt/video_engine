"""structure.py — Narrative structurer (Wave 3, directive §15).

Turns a research document into a story structure:

    hook (curiosity-driven — NEVER "in this video we will explore…"),
    promise, 3–5 escalation beats, reveal, payoff, optional callback.

LLM path over the llm.py fallback chain; deterministic offline fallback that
still produces a valid §15 skeleton. Output beats carry role, goal and claim
references — the scriptwriter fills narration next.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.v3.story.llm import LLMError, ask_json

logger = logging.getLogger(__name__)

STRUCTURE_SYSTEM = (
    "You are a story editor for short-form documentary YouTube videos. You "
    "design retention-first structures. Hard rules: the hook must create "
    "curiosity or surprise in one line — never 'in this video we will "
    "explore'; every escalation beat must raise the stakes or add new "
    "information; output ONLY valid JSON, no commentary."
)

ROLE_ORDER: tuple[str, ...] = (
    "hook", "promise", "escalation", "reveal", "payoff", "callback")
MAX_ESCALATIONS = 5


def structure_story(research: dict, *, use_llm: bool = True) -> dict:
    """Structure the story. Returns {"topic", "beats": [...]}.

    Each beat: {"beat_id": "B01", "role", "goal", "claim_refs": [int...]}.
    Roles follow ROLE_ORDER; 3-5 escalations per §15.
    """
    beats: list[dict] | None = None
    errors: list[str] = []
    if use_llm:
        beats = _llm_structure(research, errors)
    if beats is None:
        beats = _offline_structure(research)

    # Deterministic post-pass: enforce §15 shape regardless of source.
    fixed: list[dict] = []
    esc_n = 0
    for i, b in enumerate(beats):
        role = b.get("role") if b.get("role") in ROLE_ORDER else "escalation"
        if role == "escalation" and esc_n and not any(
                x["role"] == "escalation" for x in fixed) and esc_n:
            pass
        if role == "hook" and any(x["role"] == "hook" for x in fixed):
            role = "escalation"
        if role == "escalation":
            esc_n += 1
            if esc_n > MAX_ESCALATIONS:
                continue
        fixed.append({
            "beat_id": f"B{len(fixed) + 1:02d}",
            "role": role,
            "goal": str(b.get("goal", "")).strip()
            or f"advance the {role} beat of the story",
            "claim_refs": [int(r) for r in (b.get("claim_refs") or [])
                           if str(r).strip().isdigit()],
        })
    # Guarantee the mandatory beats exist.
    roles = [b["role"] for b in fixed]
    if "hook" not in roles:
        fixed.insert(0, {"beat_id": "B01", "role": "hook",
                         "goal": _offline_hook(research), "claim_refs": [0]})
        fixed = [_reid(i, b) for i, b in enumerate(fixed)]
    if "reveal" not in roles:
        fixed.append({"role": "reveal", "goal": "land the central reveal",
                      "claim_refs": []})
        fixed = [_reid(i, b) for i, b in enumerate(fixed)]
    if "payoff" not in roles:
        fixed.append({"role": "payoff",
                      "goal": "give the viewer the takeaway that pays off "
                              "the promise", "claim_refs": []})
        fixed = [_reid(i, b) for i, b in enumerate(fixed)]
    return {"topic": research.get("topic", ""), "beats": fixed}


def _reid(i: int, b: dict) -> dict:
    return {"beat_id": f"B{i + 1:02d}", "role": b["role"],
            "goal": b["goal"], "claim_refs": b.get("claim_refs", [])}


def _llm_structure(research: dict, errors: list[str]) -> list[dict] | None:
    claims = research.get("claims", [])
    claim_lines = "\n".join(
        f"  [{i}] ({c.get('confidence', 'medium')}): {c['text']}"
        for i, c in enumerate(claims))
    angles = "\n".join(f"  - {a}" for a in research.get("angles", []))
    prompt = f"""Topic: "{research.get('topic', '')}"

Researched claims (index: confidence: text):
{claim_lines}

Angle ideas:
{angles or "  - (none — invent curiosity angles from the claims)"}

Design the story structure as STRICT JSON:
{{
  "beats": [
    {{"role": "hook|promise|escalation|reveal|payoff|callback",
      "goal": "<one line: what this beat must do on screen>",
      "claim_refs": [<claim indexes used, may be empty>]}}
  ]
}}

Rules:
- exactly one hook first, one promise second, 3-5 escalation beats, one
  reveal, one payoff; add a callback ONLY if it genuinely improves the end.
- hook: one surprising, curiosity-driven idea (no "in this video…").
- escalations must escalate: each raises stakes or adds new information.
- the reveal is the strongest moment; the payoff tells the viewer why it
  mattered."""
    try:
        doc = ask_json(STRUCTURE_SYSTEM, prompt, temperature=0.7,
                       max_tokens=1500, last_errors=errors)
    except LLMError as exc:
        logger.warning("structure LLM failed: %s", exc)
        return None
    beats = doc.get("beats")
    if not isinstance(beats, list) or len(beats) < 4:
        errors.append("structure: LLM beats missing/short")
        return None
    return beats


def _offline_hook(research: dict) -> str:
    angles = research.get("angles") or []
    if angles:
        return f"Open on the curiosity angle: {angles[0]}"
    claims = research.get("claims") or []
    if claims:
        return f"Open on the surprising claim: {claims[0]['text']}"
    return "Open on the single most surprising question the topic raises"


def _offline_structure(research: dict) -> list[dict]:
    """Deterministic §15 skeleton from research claims/angles."""
    claims = research.get("claims", [])
    t = research.get("topic", "this story")
    esc_goals = [
        f"Escalate: establish what makes {t} strange or high-stakes",
        "Escalate: show the moment everything changed",
        "Escalate: reveal why the obvious explanation is incomplete",
        "Escalate: show the evidence that forces a rethink",
        "Escalate: reveal the cascade of consequences still felt today",
    ][:3 if len(claims) < 4 else 4]
    beats: list[dict] = [
        {"role": "hook", "goal": _offline_hook(research),
         "claim_refs": [0] if claims else []},
        {"role": "promise",
         "goal": f"Promise the viewer that by the end they will understand "
                 f"what really happened with {t}, without the usual "
                 f"simplification", "claim_refs": []},
    ]
    for i, g in enumerate(esc_goals):
        ref = [i + 1] if i + 1 < len(claims) else []
        beats.append({"role": "escalation", "goal": g, "claim_refs": ref})
    reveal_ref = [min(2, len(claims) - 1)] if claims else []
    beats.append({"role": "reveal",
                  "goal": "Reveal the central, most surprising truth — the "
                          "moment the viewer gets chills",
                  "claim_refs": reveal_ref})
    beats.append({"role": "payoff",
                  "goal": "Payoff: connect the reveal to what the viewer "
                          "sees around them today", "claim_refs": []})
    return beats
