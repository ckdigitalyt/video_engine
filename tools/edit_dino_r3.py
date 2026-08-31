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

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REMOVE_SHOTS = ("S02", "S10")
# r3.2 recut EXPERIMENT: CREATIVE top cut (remove S04, narration duplicates
# S03) was executed once per the max-1-recut rule and REGRESSED the artifact
# (VARIETY/SHOT_DIVERSITY maxrun 3, CREATIVE 4.5→4.2, timeline vision 25→12).
# Reverted; the redundancy complaint is recorded as a blocked editorial item.

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

# Motion Canvas EXPLANATORY graphics: data-driven plates (timeline events,
# stat bars, lineage diagram) whose dark template aesthetic registers as
# "flat" at analysis resolution. Not narration-repeat text cards (§13):
# each carries real shot data and no verbatim narration overlay.
DESIGNED_GRAPHIC: dict[str, str] = {
    "S07": "impact-marker map plate — data-driven Motion Canvas "
           "explanatory graphic, not a narration-repeat label",
    "S12": "cascading-collapse timeline — data-driven Motion Canvas "
           "explanatory graphic, not a narration-repeat label",
    "S15": "giants-vs-survivors split-screen — data-driven comparison "
           "graphic, not a narration-repeat label",
    "S17": "forest-state stat bars — data-driven Motion Canvas "
           "explanatory graphic, not a narration-repeat label",
    "S19": "lineage diagram — data-driven Motion Canvas explanatory "
           "graphic, not a narration-repeat label",
}

# §22 selective-regen precedent (r1/r2 render_records): S14's pixi scene
# references a PLATE asset that was never generated, so the pixi render is
# an empty near-black frame; every prior iteration rerouted it.
REROUTE_RENDERER: dict[str, tuple[str, str]] = {
    "S14": ("AI_IMAGE_MOTION",
            "pixi scene references never-generated PLATE_S14 — §22 reroute "
            "to AI_IMAGE_MOTION (same routing as r1/r2)"),
    "S04": ("MOTION_CANVAS",
            "both broker-cached AI stills for the rock-numbers chart are "
            "garbled-text failures (QA 45/49); the plan already carries a "
            "comparison template with the real figures — §22 reroute to "
            "MOTION_CANVAS (typed text, no hallucinated glyphs)"),
}

# r3.2: broker image generation is offline (siliconflow 401, no
# NVIDIA_API_KEY), so any cache miss falls back to a solid-color still
# (S14 rendered GREEN). Wire the proven r2-era broker-cached stills
# directly — same asset family, QA-verified in r2 (S14 88; S04 69 vs 45
# on the r3 cache image).
STILL_OVERRIDES: dict[str, str] = {
    "S14": "cache/broker/ef/ef051a29dbdf0633c6a81e922dff499dd9d27a5889"
           "be48ef4308e20513d71026.png",
    "S04": "cache/broker/25/25b9a98abd3140286ce86b55c7f233e113bed60a113d"
           "5ab2689e51f674b3bf7c.png",
    "S08": "cache/broker/b1/b1655780164391a0c827e45c59cf8fba20558fba6ace0"
           "9cb17ed623d4e198508.png",
    "S22": "cache/broker/5c/5c1fd3b143bf2147e3a8645919c826e0e85ae9b3ecaf6"
           "fee96646398368c1790.png",
}

# S15: the before_after template drew flat color panels with no subjects
# (r3 QA 46: "no giants depicted — just a flat green plate"). Add the
# size-comparison figures the claim is about (§24: show the claim).
S15_FIGURES: dict[str, dict] = {
    "before": {"kind": "sauropod", "height_frac": 0.62, "x": 0.42,
               "color": "rgba(18,14,10,0.72)"},
    "after": {"kind": "mammal", "height_frac": 0.16, "x": 0.5,
              "color": "rgba(18,14,10,0.72)"},
}

# S20: keep PIXIJS (it carries the §17 scene-animation mandate) but point
# the scene at REAL library assets — pull-out camera on a t_rex character
# over the jungle backdrop tells the shrinking-scale story (§5: what should
# the viewer SEE before renderer choice).
S20_SCENE_OVERRIDE: dict = {
    "background": {"asset": "jungle", "depth": 1.0, "scale": 1.15},
    "characters": [{"type": "t_rex", "position": [0.5, 0.88],
                    "action": "transform", "scale": 0.9,
                    "end_scale": 0.12}],
    "camera": {"move": "pull_out", "duration": 3.5},
    "particles": {"kind": "dust", "count": 40},
    "atmosphere": None,
    "props_objects": [],
}


def apply_edits(script_doc: dict, shots: list[dict]) -> tuple[dict, list[dict], dict]:
    """Return (edited_script, edited_shots, edit_log). Pure; no mutation."""
    script_doc = json.loads(json.dumps(script_doc))
    working = [dict(s) for s in shots]
    log: dict = {"removed_shots": [], "narration_trims": [],
                 "design_metadata": {}, "notes": []}

    by_id = {str(s.get("shot_id")): s for s in working}

    # R1/R2: remove shots (with their beat sentences per R6); redistribute
    # the removed shot's planned duration to its beat siblings so the beat's
    # planned total stays ≈ its narration duration — otherwise assembly
    # clone-pads the remaining clip's tail (frozen frames → static hold).
    for sid in REMOVE_SHOTS:
        shot = by_id.get(sid)
        if shot is None:
            continue
        bid = (shot.get("metadata") or {}).get("beat_id")
        siblings = [s for s in working
                    if (s.get("metadata") or {}).get("beat_id") == bid
                    and s is not shot]
        removed = float(shot.get("duration_sec") or 0)
        pool = sum(float(s.get("duration_sec") or 0) for s in siblings)
        for s in siblings:
            share = float(s.get("duration_sec") or 0) / pool if pool else 0
            s["duration_sec"] = round(
                float(s.get("duration_sec") or 0) + removed * share, 2)
        working.remove(shot)
        log["removed_shots"].append(
            {"shot_id": sid, "duration_redistributed_sec": removed,
             "to": [s["shot_id"] for s in siblings]})

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
        if sid in DESIGNED_GRAPHIC:
            s.setdefault("design", {})["designed_graphic"] = {
                "justification": DESIGNED_GRAPHIC[sid]}
            log["design_metadata"][sid] = "designed_graphic"
        # design.approved_hold: deliberately none — holds are fixed
        # renderer-side via the §16 motion toolkit event layer.

    # §22 renderer reroutes (S14) — logged, fallback preserved
    for s in working:
        sid = str(s.get("shot_id"))
        if sid in REROUTE_RENDERER:
            new_rid, why = REROUTE_RENDERER[sid]
            s["fallback_renderer"] = s.get("renderer")
            s["renderer"] = new_rid
            s.setdefault("metadata", {})["reroute_rationale"] = why
            log["rerouted"] = log.get("rerouted", []) + [
                {"shot_id": sid, "to": new_rid, "why": why}]
        if sid == "S20":
            s.setdefault("motion", {})["scene"] = dict(S20_SCENE_OVERRIDE)
            log["scene_fix"] = log.get("scene_fix", []) + [
                {"shot_id": sid,
                 "why": "scene pointed at never-generated PLATE_S20; "
                        "rewritten to real library assets (jungle + "
                        "t_rex + pull_out camera)"}]
        if sid in STILL_OVERRIDES:
            p = PROJECT_ROOT / STILL_OVERRIDES[sid]
            if p.exists():
                s.setdefault("asset_requirements", {})["still_path"] = \
                    str(p)
                log["still_overrides"] = log.get("still_overrides", []) + [
                    {"shot_id": sid, "still": str(p)}]
        if sid == "S19":
            mprops = s.setdefault("motion", {}).setdefault("props", {})
            # row layout turned the fork into a chain (r3 QA: "no branch
            # structure"); tree layout + fate styling shows the split:
            # non-avian branches fade (dead), ground birds carry through.
            mprops["layout"] = "tree"
            mprops["fate"] = {"1": "dead", "2": "surviving"}
            log["scene_fix"] = log.get("scene_fix", []) + [
                {"shot_id": sid,
                 "why": "diagram row layout hid the branch fork; switched "
                        "to tree layout with dead/surviving fate styling"}]
        if sid == "S15":
            mprops = s.setdefault("motion", {}).setdefault("props", {})
            # brighter split panels: the dark originals sat dhash-close to
            # the other dark MC plates (SHOT_DIVERSITY cluster) and read as
            # empty plates; mid-tone panels + dark silhouettes separate the
            # shot's coarse luminance map from every other MC stage.
            mprops["before_color"] = "#6f9668"
            mprops["after_color"] = "#7d6247"
            # stage_override: variant 18 puts the glow top-centre on the
            # brightest dust field — maximally far from S07's stage so the
            # two dark plates stop dhash-clustering (SHOT_DIVERSITY).
            mprops.setdefault("variant", {})["stage_override"] = 18
            mprops.setdefault("before", {})["figure"] = \
                dict(S15_FIGURES["before"])
            mprops.setdefault("after", {})["figure"] = \
                dict(S15_FIGURES["after"])
            log["scene_fix"] = log.get("scene_fix", []) + [
                {"shot_id": sid,
                 "why": "before_after panels were flat color plates with "
                        "no subjects; added size-comparison figures "
                        "(sauropod vs small mammal)"}]

    # avoid identical consecutive compositions after removals (VARIETY)
    _dedupe_compositions(working, log)
    return script_doc, working, log


def _composition_class(shot: dict) -> str:
    comp = str(shot.get("composition") or "").lower()
    for marker in ("wide", "close", "overhead", "profile", "macro",
                   "aerial", "diagram", "typography"):
        if marker in comp:
            return marker
    return "default"


def _dedupe_compositions(shots: list[dict], log: dict) -> None:
    alternates = ["wide establishing", "close-up detail",
                  "overhead graphic", "medium shot", "silhouette wide"]
    fixed: list[dict] = []
    prev_cls: str | None = None
    idx = 0
    for s in shots:
        cls = _composition_class(s)
        if prev_cls is not None and cls == prev_cls:
            for alt in alternates:
                if _composition_class({"composition": alt}) != prev_cls:
                    fixed.append({"shot_id": s["shot_id"],
                                  "from": s.get("composition"), "to": alt})
                    s["composition"] = alt
                    cls = _composition_class(s)
                    break
        prev_cls = cls
        idx += 1
    if fixed:
        log["composition_fixes"] = fixed


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
