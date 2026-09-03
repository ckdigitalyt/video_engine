"""Narration → visual alignment (V4 §3).

For every shot: WHAT is the narration saying, and WHAT should the viewer see
at that moment? Detects concrete claim types in narration and checks the
shot carries matching visual evidence:

    number present          -> number pop / comparison / diagram key number
    temporal ("ago/years")  -> timeline / diagram / historical
    comparative ("than")    -> comparison role / comparison events
    anatomy ("strip/cube/core") -> highlight / annotation / evidence overlay
    question                -> hook visual present (opening/hero)

Generic pretty imagery cannot satisfy a concrete claim.
"""

from __future__ import annotations

import re

NUM_RE = re.compile(r"\d[\d,\.]*")
TEMPORAL_RE = re.compile(r"\b(ago|years|year|bc|ad|century|when|then)\b", re.I)
COMPARATIVE_RE = re.compile(r"\b(than|twice|half|more|less|compared|vs)\b", re.I)
ANATOMY_RE = re.compile(
    r"\b(strip|cube|core|crust|surface|rings|beams|sphere|skin|bark|seed)\b", re.I)
QUESTION_RE = re.compile(r"\?")


def required_visuals(text: str) -> list:
    req = []
    if NUM_RE.search(text):
        req.append("number")
    if TEMPORAL_RE.search(text):
        req.append("timeline")
    if COMPARATIVE_RE.search(text):
        req.append("comparison")
    if ANATOMY_RE.search(text):
        req.append("annotation")
    if QUESTION_RE.search(text):
        req.append("hook")
    return req


def satisfied(req: list, shot: dict, purpose: dict) -> list:
    evs = [str(e.get("kind", "")).lower() for e in shot.get("events", [])]
    role = purpose.get("role", "")
    out = []
    for r in req:
        if r == "number":
            ok = ("number_pop" in evs) or role in ("COMPARISON", "DIAGRAM", "PAYOFF")
        elif r == "timeline":
            ok = any(k == "stage_overlay" for k in evs) or role in ("DIAGRAM", "HISTORICAL")
        elif r == "comparison":
            ok = role in ("COMPARISON", "DIAGRAM") or role == "PAYOFF"
        elif r == "annotation":
            ok = any(k in ("highlight", "callout", "number_pop", "stage_overlay") for k in evs) \
                 or role in ("EVIDENCE", "DIAGRAM", "DETAIL")
        else:  # hook
            ok = bool(purpose.get("beat_function") in ("HOOK", "CURIOSITY"))
        out.append({"req": r, "ok": bool(ok)})
    return out


def narration_visual_alignment(purpose_map: list, plan_shots: list,
                               story: dict) -> dict:
    """Score = share of required visuals that are satisfied. Flags shots
    where a concrete claim gets only generic imagery."""
    beat_narr = {b.get("beat_id"): (b.get("narration") or "") for b in story.get("beats", [])}
    shots_by_id = {str(s["shot_id"]): s for s in plan_shots}
    pm = {p["shot_id"]: p for p in purpose_map}
    rows = []
    total_req, total_ok = 0, 0
    for p in purpose_map:
        sid = p["shot_id"]
        beat = p.get("beat_id")
        text = beat_narr.get(beat, "") or " " + " " + (p.get("narration_claim") or "")
        req = required_visuals(text)
        shot = shots_by_id.get(sid, {})
        res = satisfied(req, shot, p)
        ok = all(r["ok"] for r in res)
        dur = float(shot.get("duration_s", 4.0))
        rows.append({
            "shot_id": sid, "required": req, "results": res, "ok": ok,
            "generic_risk": bool(req) and not ok,
            "empty_risk": (not req) and p.get("role") in ("DIAGRAM", "EVIDENCE"),
            "annotation_risk": ("annotation" in req) and not any(r["ok"] for r in res if r["req"] == "annotation"),
            "too_long": dur > 11.0,
        })
        total_req += len(req)
        total_ok += sum(1 for r in res if r["ok"])
    score = round(100.0 * total_ok / max(1, total_req), 1)
    return {"score": score, "shots": rows, "ok": score >= 80.0}
