"""Information velocity (V4 §2).

Estimates whether each ~3–5 s interval of the video delivers meaningful NEW
information: new fact / relationship / comparison / scale / question /
explanation / reveal / consequence. Camera movement and repeated imagery do
NOT count.

Score = share of 4-second windows that contain at least one info unit, where
info units come from the shot-purpose map + events (number pop = new scale,
stage overlay = new explanation, highlight/callout = annotation, comparison
shots, beat narration keywords).
"""

from __future__ import annotations

import re

INFO_WORDS = re.compile(
    r"\b(because|which means|that means|compared|than|twice|half|"
    r"\d[\d,\.]*)", re.I)

# per-shot info units, by descending reliability
UNIT_WEIGHTS = {"number_pop": 1.0, "stage_overlay": 1.0, "comparison": 1.0,
                "annotation": 0.8, "callout": 0.7, "typography_event": 0.7,
                "highlight": 0.5}


def info_units_per_shot(purpose_map: list, plan_shots: list) -> dict:
    """shot_id -> [unit kinds] from explicit events + purpose claims."""
    shot_events = {str(s["shot_id"]): s.get("events", []) for s in plan_shots}
    pm = {p["shot_id"]: p for p in purpose_map}
    out = {}
    for sid, evs in shot_events.items():
        units = []
        for e in evs:
            k = str(e.get("kind", "")).lower()
            if k in UNIT_WEIGHTS:
                units.append(k)
        p = pm.get(sid, {})
        role = p.get("role", "")
        if role in ("COMPARISON",):
            units.append("comparison")
        if role in ("DIAGRAM", "HISTORICAL"):
            units.append("explanation")
        # a purpose text with numbers/comparatives implies an info claim
        if INFO_WORDS.search(p.get("narration_claim", "") or ""):
            units.append("fact")
        out[sid] = units
    return out


def information_velocity(purpose_map: list, plan_shots: list,
                         total_duration: float, window: float = 4.0) -> dict:
    """Share of `window`-second windows (default 4 s) containing >=1 info
    unit. Beat narration keyword density is used as a weak secondary signal.
    """
    units = info_units_per_shot(purpose_map, plan_shots)
    # build timeline: (shot start, shot end, units)
    timeline = []
    acc = 0.0
    for s in plan_shots:
        sid = str(s["shot_id"])
        dur = float(s.get("duration_s", 4.0))
        timeline.append((acc, acc + dur, units.get(sid, [])))
        acc += dur
    total = float(total_duration or acc)

    windows = []
    t = 0.0
    while t < total - 0.5:
        t1 = min(total, t + window)
        has = False
        for (s0, s1, u) in timeline:
            if s1 > t and s0 < t1 and u:      # overlap and has units
                has = True
                break
        windows.append({"t0": round(t, 2), "t1": round(t1, 2), "info": has})
        t += window
    covered = sum(1 for w in windows if w["info"])
    score = round(100.0 * covered / max(1, len(windows)), 1)
    # flag low-information stretches (consecutive empty windows)
    stretches, cur = [], None
    for w in windows:
        if not w["info"]:
            cur = w if cur is None else {"t0": cur["t0"], "t1": w["t1"]}
        else:
            if cur:
                stretches.append(cur)
            cur = None
    if cur:
        stretches.append(cur)
    return {"score": score, "windows": len(windows), "covered": covered,
            "stretches": stretches,
            "ok": score >= 80.0}
