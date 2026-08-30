"""retention.py — §21 creative/retention critic.

A second critic focused purely on audience retention — deliberately NOT the
factual checker. Evaluates the 8 §21 questions over the shot plan, the
narration transcript and (when vision is available) frame stills, returning
a structured verdict with specific fix suggestions.

LLM path via the llm.py fallback chain; deterministic heuristic verdict
offline (hook length, pacing, variety, reveal placement).
"""

from __future__ import annotations

import logging
from pathlib import Path

from engine.v3.story.llm import LLMError, ask_json

logger = logging.getLogger(__name__)

RETENTION_SYSTEM = (
    "You are a YouTube retention critic. You judge only whether a stranger "
    "would keep watching — not factual accuracy. Be specific and honest. "
    "Output ONLY valid JSON."
)

RETENTION_QUESTIONS = (
    "q1_stop_scrolling: Would a stranger stop scrolling for the opening?",
    "q2_opening_clear: Is the opening immediately understandable?",
    "q3_shot_value: Does each shot add information or emotion?",
    "q4_boring: Is anything visually boring or unnecessarily complicated?",
    "q5_continue: Is there a reason to continue watching at every point?",
    "q6_ending: Is the ending satisfying?",
    "q7_distinctive: Is the video visually distinctive from generic AI "
    "content?",
    "q8_pacing: Does the pacing hold attention throughout?",
)

RETENTION_PROMPT = """You are reviewing a finished short documentary BEFORE
publish. Judge retention only (not facts).

Topic: "{topic}"

Shot plan (id | role | renderer | duration | composition | narration):
{shot_table}

Rules of the brief:
- hook must create curiosity in the first seconds (no "in this video…")
- visual variety is mandatory (renderer/composition changes)
- the reveal should be the strongest moment

Answer the 8 retention questions:
{questions}

Return STRICT JSON:
{{"scores": {{"q1_stop_scrolling": <0-10>, ... all 8 ...}},
 "verdict": "pass" | "fail",
 "issues": ["<specific problem>"],
 "fixes": ["<specific, actionable fix for the shot plan — quote shot ids>"],
 "reasoning": "<2-3 sentences>"}}
Pass threshold: every score >= 5 AND overall average >= 6.5."""


def retention_critic(shots: list[dict], topic: str, *,
                     narration_text: str = "",
                     style_name: str = "",
                     sheets_dir: str | Path | None = None,
                     use_llm: bool = True) -> dict:
    """Run the §21 critic. Returns {"available", "verdict", "scores",
    "issues", "fixes", "reasoning", "avg_score"}."""
    if use_llm:
        try:
            return _llm_critic(shots, topic, narration_text, style_name)
        except LLMError as exc:
            logger.warning("retention critic LLM failed: %s — heuristic", exc)
    return _heuristic_critic(shots, topic)


def _shot_table(shots: list[dict]) -> str:
    lines = []
    for s in shots:
        narr = str(s.get("metadata", {}).get("narration")
                   or s.get("subject") or "")[:80]
        lines.append(
            f"{s['shot_id']} | {s.get('narrative_role')} | "
            f"{s.get('renderer')} | {s.get('duration_sec')}s | "
            f"{s.get('composition', '')[:40]} | {narr}")
    return "\n".join(lines)


def _llm_critic(shots: list[dict], topic: str, narration_text: str,
                style_name: str) -> dict:
    prompt = RETENTION_PROMPT.format(
        topic=topic, shot_table=_shot_table(shots),
        questions="\n".join(RETENTION_QUESTIONS)) + \
        (f"\n\nFull narration transcript:\n{narration_text[:2000]}"
         if narration_text else "")
    doc = ask_json(RETENTION_SYSTEM, prompt, temperature=0.4,
                   max_tokens=1200)
    scores = {k: v for k, v in (doc.get("scores") or {}).items()
              if isinstance(v, (int, float))}
    if len(scores) < 4:
        raise LLMError("retention critic returned too few scores")
    vals = list(scores.values())
    avg = sum(vals) / len(vals)
    verdict = doc.get("verdict")
    if verdict not in ("pass", "fail"):
        verdict = "pass" if (min(vals) >= 5 and avg >= 6.5) else "fail"
    return {
        "available": True,
        "verdict": verdict,
        "scores": scores,
        "avg_score": round(avg, 2),
        "issues": [str(i) for i in (doc.get("issues") or [])][:10],
        "fixes": [str(f) for f in (doc.get("fixes") or [])][:10],
        "reasoning": str(doc.get("reasoning", ""))[:600],
    }


def _heuristic_critic(shots: list[dict], topic: str) -> dict:
    """Deterministic offline retention verdict over structural signals."""
    issues: list[str] = []
    fixes: list[str] = []
    n = len(shots)
    hook = shots[0] if shots else {}
    scores: dict[str, int] = {}

    # q1: hook strength — short, non-generic opening.
    hook_len = float(hook.get("duration_sec", 0))
    scores["q1_stop_scrolling"] = 7 if 2.0 <= hook_len <= 8.0 else 4
    if not 2.0 <= hook_len <= 8.0:
        issues.append(f"hook shot is {hook_len:.1f}s (want 2-8s)")
        fixes.append("tighten S01 to a single surprising line")

    # q2: opening understandable — hook has a concrete subject.
    subj = str(hook.get("subject") or "")
    scores["q2_opening_clear"] = 7 if len(subj.split()) >= 4 else 5

    # q3: per-shot value — every shot has narration or overlay.
    empty = [s["shot_id"] for s in shots
             if not str(s.get("metadata", {}).get("narration") or "").strip()
             and not s.get("text_overlay")]
    scores["q3_shot_value"] = 8 if not empty else 4
    if empty:
        issues.append(f"shots without narration or overlay: {empty[:4]}")
        fixes.append("add narration or text overlay to empty shots")

    # q4/q8: pacing — average shot length.
    avg_len = (sum(float(s.get("duration_sec", 0)) for s in shots) / n
               if n else 0)
    scores["q4_boring"] = 7 if avg_len <= 6.5 else 4
    if avg_len > 6.5:
        issues.append(f"average shot {avg_len:.1f}s is slow")
        fixes.append("split long shots or add pattern interrupts")
    scores["q8_pacing"] = scores["q4_boring"]

    # q5: variety keeps a reason to continue.
    from engine.v3.plan.variety import analyze_variety
    report = analyze_variety(shots)
    scores["q5_continue"] = 7 if report["distinct_renderers"] >= 3 else 4
    if report["distinct_renderers"] < 3:
        issues.append("fewer than 3 distinct renderers — monotone visuals")
        fixes.append("re-route some shots to a different renderer")

    # q6: ending — payoff/callback beat exists near the end.
    last_roles = {s.get("narrative_role") for s in shots[-3:]}
    scores["q6_ending"] = 7 if last_roles & {"payoff", "callback",
                                             "outro", "reveal"} else 4
    if not last_roles & {"payoff", "callback", "outro", "reveal"}:
        fixes.append("give the final beats a payoff or callback shot")

    # q7: distinctiveness — hero shots and overlays exist.
    has_hero = any(s.get("generation_priority") == "hero" for s in shots)
    has_overlay = any(s.get("text_overlay") for s in shots)
    scores["q7_distinctive"] = 7 if (has_hero and has_overlay) else 5
    if not has_hero:
        fixes.append("mark the most important shot generation_priority hero")

    avg = round(sum(scores.values()) / len(scores), 2)
    verdict = "pass" if (min(scores.values()) >= 5 and avg >= 6.5) else "fail"
    return {"available": False, "verdict": verdict, "scores": scores,
            "avg_score": avg, "issues": issues, "fixes": fixes,
            "reasoning": "heuristic structural verdict (offline mode)"}
