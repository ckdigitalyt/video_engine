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
# "when/then" dropped: rhetorical clauses ("even when you never touch it") and
# discourse markers are not history claims. Singular "year" dropped: seasonal
# idiom ("most of the year") is not temporal. Plural/era markers kept.
TEMPORAL_RE = re.compile(r"\b(ago|decades?|centur(y|ies)|bc|ad|millennia|years)\b", re.I)
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
    for idx, p in enumerate(purpose_map):
        sid = p["shot_id"]
        beat = p.get("beat_id")
        text = beat_narr.get(beat, "") or " " + " " + (p.get("narration_claim") or "")
        req = required_visuals(text)
        shot = shots_by_id.get(sid, {})
        res = satisfied(req, shot, p)
        if str(p.get("beat_function") or p.get("function") or "").upper() in ("HOOK", "CURIOSITY"):
            # Documentary payoff chain: the hook's job is to open the gap, so
            # its number/comparison claim is validly evidenced when a LATER
            # shot carries the matching visual. Videos that never show it
            # still fail — this only credits claims the film actually pays off.
            for r in res:
                if r["req"] in ("number", "comparison") and not r["ok"]:
                    for q in purpose_map[idx + 1:]:
                        qs = shots_by_id.get(q["shot_id"], {})
                        if all(x["ok"] for x in satisfied([r["req"]], qs, q)):
                            r["ok"] = True
                            r["paid_off_later"] = True
                            break
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
