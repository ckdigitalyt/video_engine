"""critic.py — Mandatory human-like creative critic (directive §20).

"Imagine watching this without knowing it was AI-generated. Would you
continue watching?"

The V3 retention critic scored 8.25 on dino_v1 — as a heuristic with the
LLM offline — while the video measured 63.5 % frozen runtime. The §20
critic must be human-like and grounded in the measured artifact: it
receives the shot plan AND the V4 audit metrics (event density, static
holds, flat-card time, dhash duplicates), and answers with the exact §20
output contract:

    hook_strength, visual_interest, pacing, cinematography, story_clarity,
    originality, would_publish, top_5_problems, recommended_cuts,
    recommended_new_shots

A technically valid video with an overall creative score < 8.0/10 MUST
fail (CREATIVE gate in gates.py). Recommended cuts feed the §21 re-edit
engine (reedit.py), which applies trim → shorten → rearrange → replace
BEFORE any regeneration.

LLM path: ZAI GLM (first in the llm.py chain — GLM flash, cheap); the
deterministic heuristic path computes the same contract from audit
metrics so the verdict never silently evaporates offline.
"""

from __future__ import annotations

import logging

from engine.v3.story.llm import LLMError, ask_json
from engine.v3.plan.variety import analyze_variety

logger = logging.getLogger(__name__)

CREATIVE_PASS_MIN = 8.0

CRITIC_SYSTEM = (
    "You are a brutally honest human creative director — a working "
    "professional who has watched thousands of documentaries and knows "
    "exactly when an AI-generated video feels like a slideshow. You judge "
    "the video as a stranger would: 'Imagine watching this without knowing "
    "it was AI-generated. Would you continue watching?' Be specific, quote "
    "shot ids, and never soften problems. Output ONLY valid JSON."
)

CRITIC_PROMPT = """You are reviewing a finished short documentary BEFORE
publish. Judge it like a human creative director, not a checklist.

Topic: "{topic}"

Shot plan (id | class | renderer | duration | scale | camera | narration):
{shot_table}

Measured artifact forensics (offline pixel audit — trust these numbers):
{audit_summary}

Full narration transcript (first 2000 chars):
{narration}

Score each dimension 0-10 and answer:
- hook_strength: would a stranger stop scrolling?
- visual_interest: is anything actually HAPPENING on screen?
- pacing: does it drag (static holds, slow sections)?
- cinematography: camera work, shot scale variety, lighting intent?
- story_clarity: does the narrative land?
- originality: does it feel distinctive or like generic AI content?

Return STRICT JSON:
{{"hook_strength": <0-10>, "visual_interest": <0-10>, "pacing": <0-10>,
 "cinematography": <0-10>, "story_clarity": <0-10>, "originality": <0-10>,
 "would_publish": <true|false>,
 "top_5_problems": ["<specific problem, quote shot ids>", ...max 5],
 "recommended_cuts": [{{"shot_id": "S07", "action": "trim|shorten|rearrange|replace|regenerate",
                       "detail": "<what and why>"}}],
 "recommended_new_shots": ["<shot the video is missing and why>"],
 "reasoning": "<2-4 sentences, honest>"}}

A score below 8.0 overall means the video does NOT publish."""


def _audit_summary(audit: dict | None, shot_audits: dict[str, dict] | None) -> str:
    if not audit:
        return "no artifact audit available (plan-only review)"
    d = audit.get("visual_event_density", {})
    s = audit.get("static_holds", {})
    bf = audit.get("black_flat", {})
    lines = [
        f"- scene-internal visual events: {d.get('events')} "
        f"({d.get('events_per_10s')}/10s) — a professional documentary "
        f"has >={1.5}/10s",
        f"- frozen time: {s.get('total_hold_sec')}s total, longest hold "
        f"{s.get('longest_hold_sec')}s (holds over 2.5s: "
        f"{len(s.get('holds_over_2_5s', []))})",
        f"- flat/text-card time: {bf.get('flat_sec')}s "
        f"({bf.get('flat_fraction', 0):.1%})",
    ]
    if shot_audits:
        classes = {}
        for a in shot_audits.values():
            c = a.get("motion_class", "?")
            classes[c] = classes.get(c, 0) + 1
        lines.append(f"- per-shot motion classes: {classes}")
    return "\n".join(lines)


def _shot_table(shots: list[dict]) -> str:
    lines = []
    for s in shots:
        narr = str(s.get("metadata", {}).get("narration")
                   or s.get("subject") or "")[:70]
        lines.append(
            f"{s.get('shot_id')} | {s.get('shot_class', '?')} | "
            f"{s.get('renderer', '?')} | {s.get('duration_sec')}s | "
            f"{s.get('shot_scale', '?')} | {s.get('camera_move', '?')} | {narr}")
    return "\n".join(lines)


def _normalize(doc: dict, available: bool) -> dict:
    """Coerce any critic output (LLM or heuristic) into the §20 contract."""
    keys = ("hook_strength", "visual_interest", "pacing", "cinematography",
            "story_clarity", "originality")
    scores: dict[str, float] = {}
    for k in keys:
        v = doc.get(k)
        if isinstance(v, (int, float)):
            scores[k] = round(max(0.0, min(10.0, float(v))), 1)
    overall = round(sum(scores.values()) / len(scores), 2) if scores else 0.0
    # §20: score < 8.0 → overall FAIL — would_publish can never be true
    # below the threshold, no matter what the critic said.
    would = bool(doc.get("would_publish")) and overall >= CREATIVE_PASS_MIN
    cuts = []
    for c in (doc.get("recommended_cuts") or [])[:10]:
        if isinstance(c, dict) and c.get("shot_id"):
            cuts.append({
                "shot_id": str(c["shot_id"]),
                "action": str(c.get("action", "trim")).lower(),
                "detail": str(c.get("detail", ""))[:200],
            })
    problems = [str(p) for p in (doc.get("top_5_problems") or [])][:5]
    new_shots = [str(p) for p in (doc.get("recommended_new_shots") or [])][:8]
    return {
        "available": available,
        "scores": scores,
        "overall_score": overall,
        "would_publish": would,
        "top_5_problems": problems,
        "recommended_cuts": cuts,
        "recommended_new_shots": new_shots,
        "reasoning": str(doc.get("reasoning", ""))[:800],
    }


def creative_critic(shots: list[dict], topic: str, *,
                    narration_text: str = "",
                    audit: dict | None = None,
                    shot_audits: dict[str, dict] | None = None,
                    use_llm: bool = True) -> dict:
    """Run the §20 critic (ZAI GLM via the llm.py chain, GLM flash first).

    Falls back to the deterministic heuristic critic (same §20 contract)
    whenever the LLM is unavailable — the verdict degrades, it never
    disappears."""
    if use_llm and shots:
        try:
            prompt = CRITIC_PROMPT.format(
                topic=topic, shot_table=_shot_table(shots),
                audit_summary=_audit_summary(audit, shot_audits),
                narration=(narration_text or "")[:2000])
            doc = ask_json(CRITIC_SYSTEM, prompt, temperature=0.4,
                           max_tokens=1600)
            result = _normalize(doc, available=True)
            if len(result["scores"]) >= 4:
                return result
            logger.warning("creative critic returned too few scores — "
                           "heuristic fallback")
        except LLMError as exc:
            logger.warning("creative critic LLM failed: %s — heuristic", exc)
    return heuristic_critic(shots, audit=audit, shot_audits=shot_audits)


def heuristic_critic(shots: list[dict], *, audit: dict | None = None,
                     shot_audits: dict[str, dict] | None = None) -> dict:
    """Deterministic §20 verdict from measured artifact metrics.

    Calibrated so the dino_v1 artifact (0.078 events/10s, 63.5 % frozen,
    31.5 % flat cards, one-template Motion Canvas cluster) scores well
    below the 8.0 publish threshold."""
    scores: dict[str, float] = {}
    problems: list[str] = []
    cuts: list[dict] = []

    d = (audit or {}).get("visual_event_density", {})
    s = (audit or {}).get("static_holds", {})
    bf = (audit or {}).get("black_flat", {})
    density = float(d.get("events_per_10s", 0) or 0)
    longest = float(s.get("longest_hold_sec", 0) or 0)
    flat = float(bf.get("flat_fraction", 0) or 0)

    # visual_interest ← event density (≥1.5/10s good, 0.078 disastrous)
    if density >= 1.5:
        scores["visual_interest"] = 8.0
    elif density >= 0.8:
        scores["visual_interest"] = 6.0
    elif density >= 0.3:
        scores["visual_interest"] = 4.0
    else:
        scores["visual_interest"] = 2.0
        problems.append(
            f"only {density}/10s scene-internal visual events — the screen "
            "is effectively frozen (slideshow failure)")

    # pacing ← static holds
    if longest <= 2.5:
        scores["pacing"] = 8.0
    elif longest <= 4.0:
        scores["pacing"] = 6.0
    else:
        scores["pacing"] = 3.0
        problems.append(f"static hold of {longest:.1f}s (> 2.5s) — viewers "
                        "leave during dead frames")
    holds = (s.get("holds_over_2_5s") or [])
    for h in holds[:3]:
        cuts.append({"shot_id": "master", "action": "trim",
                     "detail": f"trim frozen hold {h.get('duration_sec')}s "
                               f"at t={h.get('start_sec')}"})

    # cinematography ← field coverage + camera variety + scale variety
    n = max(1, len(shots))
    if shots:
        with_fields = sum(1 for x in shots
                          if x.get("camera_move") and x.get("shot_scale"))
        moves = {str(x.get("camera_move") or "static") for x in shots}
        scales = {x.get("shot_scale") for x in shots if x.get("shot_scale")}
        ratio = (sum(1 for x in shots
                     if str(x.get("camera_move") or "static") != "static")) / n
        if with_fields == len(shots) and len(scales) >= 2 and ratio >= 0.35:
            scores["cinematography"] = 8.0
        elif with_fields > 0:
            scores["cinematography"] = 5.0
            problems.append("cinematography intent missing or uniform — "
                            "no real camera/scale language")
        else:
            scores["cinematography"] = 3.0
            problems.append("no cinematography fields — the plan has no "
                            "camera language (§6)")
        if len(moves) == 1 and "static" in moves:
            problems.append("every shot has a static camera")
    else:
        scores["cinematography"] = 4.0

    # text-card penalty
    if flat >= 0.10:
        scores["originality"] = 4.0
        problems.append(f"{flat:.1%} of runtime is flat text-card frames")
    else:
        scores["originality"] = 7.0

    # hook/story from the plan structure
    if shots:
        hook = shots[0]
        hook_dur = float(hook.get("duration_sec") or 0)
        scores["hook_strength"] = 7.0 if 2.0 <= hook_dur <= 8.0 else 4.0
        roles = {str(x.get("narrative_role")) for x in shots}
        scores["story_clarity"] = 7.0 if roles & {"reveal", "payoff",
                                                  "climax"} else 5.0
    else:
        scores["hook_strength"] = 4.0
        scores["story_clarity"] = 4.0

    # diversity penalty
    report = analyze_variety(shots) if shots else {}
    if shots and report.get("pattern_interrupt_count", 0) == 0:
        problems.append("no pattern interrupts — consecutive shots share "
                        "medium, scale and motion class (§14)")

    result = _normalize({
        "hook_strength": scores.get("hook_strength", 4),
        "visual_interest": scores.get("visual_interest", 2),
        "pacing": scores.get("pacing", 3),
        "cinematography": scores.get("cinematography", 3),
        "story_clarity": scores.get("story_clarity", 4),
        "originality": scores.get("originality", 4),
        "would_publish": False,
        "top_5_problems": problems[:5],
        "recommended_cuts": cuts[:8],
        "recommended_new_shots": [],
        "reasoning": "heuristic critic verdict computed from offline pixel "
                     "audit metrics (LLM unavailable)",
    }, available=False)
    return result
