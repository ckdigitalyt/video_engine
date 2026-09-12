"""V11 P1 §2 — Visual surprise: planner tagging + per-story verdict.

Does the story contain at least one GENUINE visual revelation?

Valid surprise classes (directive):
    MICROSCOPIC_ZOOM, HIDDEN_CROSS_SECTION, IMPOSSIBLE_SCALE_TRANSITION,
    SPATIAL_REVEAL, BEFORE_AFTER, CAUSAL_CHAIN_REVEAL,
    UNEXPECTED_TRANSFORMATION

Invalid (never count, even when the plan calls them something else):
    plain zoom, pan, number pop, decorative particle, generic transition —
    camera movement and decoration are not information (P0 motion classes).

Authoring (planner tagging, shot level — visual_plan.json):

  "surprise": {"class": "HIDDEN_CROSS_SECTION",
               "evidence": "quasi-liquid interface exposed below the blade"}

Authored declarations win. Undeclared shots are inferred from their visual
mode + planv8 living events; inference is conservative and every inferred
tag is marked `inferred: true` so reports never confuse authorship with
guesswork.

`run(plan)` → per-story verdict: `surprise_present` (>=1 valid, non-invalid
tagged shot), `weak` (only inferred tags), or `none`.
"""

from __future__ import annotations

VALID = ("MICROSCOPIC_ZOOM", "HIDDEN_CROSS_SECTION", "IMPOSSIBLE_SCALE_TRANSITION",
         "SPATIAL_REVEAL", "BEFORE_AFTER", "CAUSAL_CHAIN_REVEAL",
         "UNEXPECTED_TRANSFORMATION")
INVALID = ("ZOOM", "PAN", "NUMBER_POP", "DECORATIVE_PARTICLE", "GENERIC_TRANSITION")

# visual_mode → valid class (conservative inference)
_MODE_MAP = {
    "MACRO_DETAIL": "MICROSCOPIC_ZOOM",
    "CELLULAR_DIAGRAM": "MICROSCOPIC_ZOOM",
    "MOLECULAR_PROCESS": "MICROSCOPIC_ZOOM",
    "CUTAWAY": "HIDDEN_CROSS_SECTION",
    "CROSS_SECTION": "HIDDEN_CROSS_SECTION",
    "STRUCTURAL_DIAGRAM": "HIDDEN_CROSS_SECTION",
    "ASTRONOMICAL_SCALE": "IMPOSSIBLE_SCALE_TRANSITION",
    "SCALE": "IMPOSSIBLE_SCALE_TRANSITION",
    "MAP_TRANSFORMATION": "SPATIAL_REVEAL",
    "GEOGRAPHIC_TRANSFORMATION": "SPATIAL_REVEAL",
}
# living event kinds → valid class (planv8-stamped). Events alone are NOT
# enough — planv8 stamps reveal/isolate liberally, so event inference also
# requires the shot's authored text to support the class (text lexica below).
_EVENT_MAP = {
    "reveal": "SPATIAL_REVEAL",
    "isolate": "SPATIAL_REVEAL",
    "fill_state": "UNEXPECTED_TRANSFORMATION",
    "consequence": "CAUSAL_CHAIN_REVEAL",
}
_EVENT_LEXICON = {
    "SPATIAL_REVEAL": ("hidden", "beneath", "under", "underneath", "inside",
                       "interface", "cross", "section", "behind", "layer"),
    "UNEXPECTED_TRANSFORMATION": ("transform", "become", "becomes", "turn",
                                  "turns", "melt", "melts", "freeze", "shift"),
    "CAUSAL_CHAIN_REVEAL": ("feeds", "feeds", "because", "cause", "causes",
                            "cascade", "chain", "leads", "triggers"),
}
# modes/flags that are explicitly INVALID as surprise evidence
_INVALID_MODES = {"CINEMATIC", "PAYOFF", "DIAGRAM", "TYPOGRAPHY"}


def classify_shot(s: dict) -> dict | None:
    """One surprise tag per shot: authored declaration wins, else a single
    conservative inference (mode, then living event)."""
    a = s.get("surprise") or (s.get("v8") or {}).get("surprise")
    if isinstance(a, dict) and str(a.get("class") or "").upper():
        cls = str(a["class"]).upper()
        if cls in INVALID:
            return {"class": cls, "valid": False,
                    "note": "authored class is on the invalid list"}
        return {"class": cls, "valid": cls in VALID, "inferred": False,
                "evidence": str(a.get("evidence") or "")}
    mode = str(s.get("visual_mode") or "").upper()
    if mode in _MODE_MAP:
        return {"class": _MODE_MAP[mode], "valid": True, "inferred": True,
                "via": f"visual_mode:{mode}"}
    text = " ".join(str(s.get(k) or "") for k in
                    ("purpose", "evidence", "claim")).lower()
    for e in s.get("events") or []:
        kind = str((e or {}).get("kind") or "").lower()
        cls = _EVENT_MAP.get(kind)
        if cls and any(w in text for w in _EVENT_LEXICON[cls]):
            return {"class": cls, "valid": True, "inferred": True,
                    "via": f"event:{kind}+text"}
    return None


def run(plan: dict) -> dict:
    """Per-story surprise verdict. Stamps `s["v8"]["surprise"]`."""
    rows = []
    for s in plan.get("shots", []):
        tag = classify_shot(s)
        if tag is None:
            continue
        s.setdefault("v8", {})["surprise"] = tag
        rows.append({"shot_id": str(s.get("shot_id")), **tag})
    authored_valid = [r for r in rows if r["valid"] and not r.get("inferred")]
    any_valid = [r for r in rows if r["valid"]]
    verdict = ("surprise_present" if authored_valid else
               "weak" if any_valid else "none")
    return {"verdict": verdict, "n_valid": len(any_valid),
            "n_authored": len(authored_valid), "rows": rows,
            "invalid_classes": INVALID, "valid_classes": list(VALID)}
