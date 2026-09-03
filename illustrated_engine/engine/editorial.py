"""Editorial intelligence (V4 §7 §11 §13 §14).

Beat functions (retention structure), shot-purpose maps, asset roles and the
human-editor 8-question test. All additive — stories that don't carry the
new fields fall back to neutral values.
"""

from __future__ import annotations

BEAT_FUNCTIONS = ("HOOK", "CURIOSITY", "REVEAL", "EXPLANATION", "ESCALATION",
                  "TWIST", "PAYOFF")
ASSET_ROLES = ("HERO", "DETAIL", "EVIDENCE", "DIAGRAM", "COMPARISON",
               "HISTORICAL", "PAYOFF")

# Role-aware QA thresholds (§7: not one universal bar)
ROLE_THRESHOLDS = {
    "HERO":       {"style": 0.50, "palette": 0.60},
    "PAYOFF":     {"style": 0.50, "palette": 0.60},
    "DETAIL":     {"style": 0.42, "palette": 0.55},
    "EVIDENCE":   {"style": 0.42, "palette": 0.55, "needs_annotation": True},
    "DIAGRAM":    {"style": 0.35, "palette": 0.40, "readability_dominant": True},
    "COMPARISON": {"style": 0.42, "palette": 0.55, "needs_two_elements": True},
    "HISTORICAL": {"style": 0.42, "palette": 0.55},
}


def beat_functions(story: dict) -> dict:
    """Map beat_id -> narrative function (from story.json beat.function)."""
    return {b.get("beat_id"): str(b.get("function", "")).upper()
            for b in story.get("beats", [])}


def validate_retention_structure(story: dict) -> dict:
    """§11: modelled as HOOK→CURIOSITY→REVEAL→EXPLANATION→ESCALATION→TWIST→
    PAYOFF; not every story needs all seven. Hard rules: first beat is HOOK,
    last beat is PAYOFF, every beat declares a function."""
    fns = beat_functions(story)
    beats = list(story.get("beats", []))
    problems = []
    if not beats:
        return {"ok": False, "problems": ["no beats"]}
    if fns.get(beats[0].get("beat_id")) != "HOOK":
        problems.append(f"first beat {beats[0].get('beat_id')} is not HOOK")
    if fns.get(beats[-1].get("beat_id")) != "PAYOFF":
        problems.append(f"last beat {beats[-1].get('beat_id')} is not PAYOFF")
    for b in beats:
        if not fns.get(b.get("beat_id")):
            problems.append(f"{b.get('beat_id')} has no function")
    unknown = {f for f in fns.values() if f and f not in BEAT_FUNCTIONS}
    if unknown:
        problems.append(f"unknown functions: {sorted(unknown)}")
    return {"ok": not problems, "problems": problems, "functions": fns}


def shot_purpose_map(story: dict, visual_plan: dict) -> list:
    """§13: for every shot record WHY it exists.

    Sources shot fields from visual_plan: purpose, claim (narration_claim),
    evidence (visual_evidence), motion_reason, transition_reason.
    Falls back to beat narration + shot_type when absent.
    """
    fns = beat_functions(story)
    beat_of = {}
    for b in visual_plan.get("beats", []):
        for s in b.get("shots", []):
            beat_of[str(s["shot_id"])] = b.get("beat_id")
    out = []
    for b in visual_plan.get("beats", []):
        for s in b.get("shots", []):
            out.append({
                "shot_id": str(s["shot_id"]),
                "beat_id": b.get("beat_id"),
                "beat_function": fns.get(b.get("beat_id"), ""),
                "shot_type": str(s.get("shot_type", "")),
                "role": str(s.get("role", "")).upper(),
                "shot_purpose": s.get("purpose", ""),
                "narration_claim": s.get("claim", ""),
                "visual_evidence": s.get("evidence", ""),
                "reason_for_motion": s.get("motion_reason", ""),
                "reason_for_transition": s.get("transition_reason", ""),
            })
    return out


def human_editor_test(purpose_map: list, alignment: dict, density: dict,
                      velocity: dict) -> dict:
    """§14: per-shot 8-question checklist. Uses measured signals where they
    exist; shot map fields otherwise. Returns per-shot answers + flags.
    """
    flags = []
    rows = []
    shot_align = {a["shot_id"]: a for a in alignment.get("shots", [])}
    for s in purpose_map:
        sid = s["shot_id"]
        align = shot_align.get(sid, {})
        answers = {
            "1_new_information": bool(s["shot_purpose"]),
            "2_visual_explains_narration": bool(align.get("ok")),
            "3_main_element_obvious": not bool(align.get("generic_risk")),
            "4_unnecessary_empty_space": not bool(align.get("empty_risk")),
            "5_shot_too_long": bool(align.get("too_long")),
            "6_motion_meaningful": bool(s["reason_for_motion"]),
            "7_annotation_would_help": bool(align.get("annotation_risk")),
            "8_transition_has_reason": bool(s["reason_for_transition"]),
        }
        n_no = sum(1 for v in answers.values() if not v)
        row = {"shot_id": sid, **answers, "no_count": n_no}
        rows.append(row)
        if n_no >= 4:
            flags.append({"shot_id": sid, "no_count": n_no})
    return {"rows": rows, "flagged": flags,
            "pass": not flags}
