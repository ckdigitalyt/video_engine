#!/usr/bin/env python3
"""edit_dino_r3.py — §21 re-edit ops for dino_v2 r3 (phase 4, deliverable 4).

Preferred order: trim → shorten → rearrange → replace → regenerate.
The master duration is narration-TTS-driven (assembler: video_total =
narration_total + TAIL_PAD), so runtime cuts are NARRATION cuts; shots whose
narration disappears are removed with it.

Inputs (from r2 evidence):
  * publish_gate_r2.json CREATIVE critic: recommended_cuts = shorten S02,
    replace S10; problems: repetitive opening, S12 8.9 s hold, flat-card
    time 16.5 %;
  * audit_r2: longest hold 8.9 s (S12 — fixed renderer-side via the §16
    motion toolkit, not by cutting), VISUAL QA failures S04/S19/S20,
    160.1 s runtime > 150 s target.

Ops (all narration-preserving-in-meaning, science accuracy kept):
  R1  remove S02  — 2.1 s fern close-up; retention flagged it repetitive
                    with S01; critic action was "shorten", but the shot is
                    already at the 2 s floor → removal is the honest cut
  R2  remove S10  — critic "replace"; its beat sentence (stratigraphic
                    marker) is cut with it (R6)
  R3  B01 trim    — "in what amounts to a single bad day" → "in a single
                    bad day"
  R4  B02 trim    — drop "itself", "and it started the moment the rock was
                    gone"
  R5  B05 trim    — tighten the food-chain sentence
  R6  B04 trim    — drop the closing fossil-horizon sentence (S10's
                    visual — removed in R2)
  R7  B09 trim    — drop "It's a genuinely open debate." + tighten

Design metadata (deliverable 3), authored HERE at plan time with mandatory
justifications, consumed by the §19 gates:
  design.dark_atmospheric on S06/S11/S13/S21 (intentional dark grades),
  design.approved_hold: none (holds must be fixed renderer-side).
"""

from __future__ import annotations

import json
from pathlib import Path

REMOVE_SHOTS = ("S02", "S10")

NARRATION_TRIMS: dict[str, tuple[str, str]] = {
    # beat_id: (old, new) — applied verbatim; no-op if old not found
    "B01": (
        "Then, in what amounts to a single bad day, three out of every four "
        "species on the planet simply stopped existing.",
        "Then, in a single bad day, three out of every four species on the "
        "planet simply stopped existing.",
    ),
    "B02": (
        "The rock itself only killed what it touched. What ended the age of "
        "dinosaurs was something you can't see — and it started the moment "
        "the rock was gone.",
        "The rock only killed what it touched. What ended the age of "
        "dinosaurs was something you can't see.",
    ),
    "B04": (
        " That thin layer of debris still marks the exact horizon where the "
        "dinosaurs vanish from the fossil record.",
        "",
    ),
    "B05": (
        "And when the base of a food chain collapses, starvation moves "
        "upward in order — herbivores first, then the predators that ate "
        "them.",
        "When the base of a food chain collapses, starvation moves upward — "
        "herbivores first, then the predators.",
    ),
    "B09": (
        "It's a genuinely open debate. But the habitat models are blunt",
        "But the habitat models are blunt",
    ),
}

DARK_ATMOSPHERIC: dict[str, str] = {
    "S06": "continent-scale wildfire at dusk — intentional dark smoke "
           "grade, shot design not a text card",
    "S11": "orbital Earth under a grey dust shroud — intentional "
           "post-impact darkness, shot design not a text card",
    "S13": "ash-winter dead forest under grey ashen snow — intentional "
           "impact-winter gloom, shot design not a text card",
    "S21": "flood-basalt lava fields at twilight — intentional dark "
           "volcanic grade, shot design not a text card",
}


def apply_edits(script_doc: dict, shots: list[dict]) -> tuple[dict, list[dict], dict]:
    """Return (edited_script, edited_shots, edit_log). Pure; no mutation."""
    script_doc = json.loads(json.dumps(script_doc))
    working = [dict(s) for s in shots]
    log: dict = {"removed_shots": [], "narration_trims": [],
                 "design_metadata": {}, "notes": []}

    by_id = {str(s.get("shot_id")): s for s in working}

    # R1/R2: remove shots (with their beat sentences per R6)
    for sid in REMOVE_SHOTS:
        if sid in by_id:
            working.remove(by_id[sid])
            log["removed_shots"].append(sid)

    # R3–R7: narration trims
    for beat in script_doc.get("beats", []):
        bid = str(beat.get("beat_id"))
        text = str(beat.get("narration", ""))
        if bid in NARRATION_TRIMS:
            old, new = NARRATION_TRIMS[bid]
            if old in text:
                beat["narration"] = text.replace(old, new)
                log["narration_trims"].append(
                    {"beat_id": bid, "removed_words":
                        len(old.split()) - len(new.split())})
            else:
                log["notes"].append(f"trim anchor not found in {bid}")

    # deliverable 3: plan-time shot-design metadata with justifications
    for s in working:
        sid = str(s.get("shot_id"))
        if sid in DARK_ATMOSPHERIC:
            s.setdefault("design", {})["dark_atmospheric"] = {
                "justification": DARK_ATMOSPHERIC[sid]}
            log["design_metadata"][sid] = "dark_atmospheric"
        # design.approved_hold: deliberately none — holds are fixed
        # renderer-side via the §16 motion toolkit event layer.

    return script_doc, working, log


def summary(shots: list[dict]) -> float:
    return round(sum(float(s.get("duration_sec") or 0) for s in shots), 2)


if __name__ == "__main__":
    out_dir = Path("results/dino_v2")
    script_doc = json.loads((out_dir / "script.json").read_text())
    shotlist = json.loads((out_dir / "shotlist.json").read_text())
    s2, shots, log = apply_edits(script_doc, shotlist["shots"])
    log["planned_duration_after_edits"] = summary(shots)
    (out_dir / "edit_log_r3.json").write_text(json.dumps(log, indent=2))
    print(json.dumps(log, indent=2))
