"""V7 P0-1 — Visual class taxonomy and shot classifier.

Classes (brief P0-1):
  EVIDENCE      diagram, transformation, comparison, map, timeline, process,
                scale, quantitative graphic, cutaway, cause/effect
  CINEMATIC     meaningful subject-specific illustration
  BREATHING     restrained typography / atmosphere
  GENERIC_BLUR  narration text riding a blurred ambient card with no visual
                evidence ("a subtitle over a blurred picture")

A shot may be both EVIDENCE and CINEMATIC (e.g. a full-bleed subject plate
carrying a quantitative annotation).  `primary` picks one class for
signatures/sequences; the coverage math uses the boolean flags so
EVIDENCE + CINEMATIC jointly count toward the >=80% gate.

Classification is spec-driven (the plan knows what is on screen) and
deterministic.  No pixel guessing: if the planner did not declare evidence,
there is none — that is the point of the gate.
"""

from __future__ import annotations

EVIDENCE_MODES = {"DIAGRAM", "SPLIT", "TRANSFORMATION", "TIMELINE", "MAP",
                  "PROCESS", "COMPARE", "COMPARISON", "SCALE", "CUTAWAY",
                  "CAUSE_EFFECT", "QUANTITATIVE"}
EVIDENCE_ROLES = {"DIAGRAM", "COMPARISON"}
EVIDENCE_EVIDENCE_TYPES = {"EXPLANATORY_DIAGRAM", "DIRECT_EVIDENCE"}
CINEMATIC_MODES = {"CINEMATIC", "PAYOFF", "DETAIL"}
CINEMATIC_ROLES = {"HERO", "DETAIL"}

_KINETIC_TYPES = {"streamlines", "clock_sweep", "orbit", "particles", "flow",
                  "heatmap", "pulse", "countup", "drift", "morph"}


def _has_kinetic(shot: dict) -> bool:
    k = shot.get("kinetic")
    if not k:
        return False
    if isinstance(k, dict):
        t = str(k.get("type", "")).lower()
        return bool(t)
    return True


def _evidence_text(shot: dict) -> str:
    return str(shot.get("evidence") or "").strip()


def classify_shot(shot: dict) -> dict:
    """Return class flags + primary class + machine-readable reasons."""
    mode = str(shot.get("visual_mode") or "").upper()
    role = str(shot.get("role") or "").upper()
    etype = str(shot.get("evidence_type") or "").upper()
    ev_text = _evidence_text(shot)
    kinetic = _has_kinetic(shot)

    reasons = []
    is_evidence = False
    if etype in EVIDENCE_EVIDENCE_TYPES:
        # evidence must actually describe a visual, not just a label
        if ev_text:
            is_evidence = True
            reasons.append(f"evidence_type={etype}")
    if mode in EVIDENCE_MODES:
        is_evidence = True
        reasons.append(f"mode={mode}")
    if role in EVIDENCE_ROLES:
        is_evidence = True
        reasons.append(f"role={role}")
    if kinetic:
        is_evidence = True
        reasons.append("kinetic")

    is_cinematic = False
    if etype == "DIRECT_EVIDENCE" and ev_text:
        is_cinematic = True
        reasons.append("direct_evidence_plate")
    if mode in CINEMATIC_MODES:
        is_cinematic = True
        reasons.append(f"mode={mode}")
    if role in CINEMATIC_ROLES:
        is_cinematic = True
        reasons.append(f"role={role}")

    is_breathing = not is_evidence and not is_cinematic

    # Generic blur narration card: breathing-class content on the standard
    # card layout (ambient blurred background + centered narration card).
    # Full-bleed atmospheric plates are breathing but not the blur-card
    # pattern; card shots carry the v6 card geometry contract.
    is_card = bool(shot.get("subject_contract") or shot.get("chrome"))
    is_generic_blur = is_breathing and is_card

    if is_evidence:
        primary = "EVIDENCE"
    elif is_cinematic:
        primary = "CINEMATIC"
    else:
        primary = "BREATHING"

    return {
        "shot_id": shot.get("shot_id"),
        "primary": primary,
        "is_evidence": is_evidence,
        "is_cinematic": is_cinematic and not is_evidence,
        "is_breathing": is_breathing,
        "is_generic_blur": is_generic_blur,
        "reasons": reasons,
        "kinetic": kinetic,
    }


def classify_plan(shots: list) -> list:
    return [classify_shot(s) for s in shots]
