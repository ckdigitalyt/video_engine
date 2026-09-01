#!/usr/bin/env python3
"""render_r62.py — dino_v2 r6.2 re-render: timeline-artifact fixes.

The r6.1 gate (FAIL 13/16) left VISUAL failing on exactly one leg: the
timeline vision audit scored 48 < 65 (shot avg 73 and the per-shot floor
both pass). The three audited frames each map to a concrete engine bug:

  * LAST frame (S24, dust+flock): "dozens of small white square/cell
    artifacts" — _draw_motes drew hard size-2 squares with per-frame
    random brightness (flicker) that upscale into ~20px white cells.
    Fix: soft dim radial disks, fixed per-mote brightness (motion_toolkit).
  * MIDDLE frame (S15 card): sauropod silhouette had a rectangular notch
    between the leg pairs (straight-line belly path). Fix: smooth belly
    arch + tapered legs (before_after.mjs). This redesign also breaks the
    SHOT_DIVERSITY dhash cluster ['S07', 'S15'] — the only duplicate
    cluster the r6.1 gate found.
  * FIRST frame (S01): AI_VIDEO cache clip renders blobby anatomy and is
    5.9s vs the 9.64s beat (fit stretch + clone-pad ghosting). Fix: reroute
    S01 → AI_IMAGE_MOTION driven by its pinned hero keyframe (S14/S20
    precedent) — sharp still, exact duration, engine-side.

Rain dashes dimmed 190/140 → 128/92 for the same upscale-artifact reason.

Scope guards:
  * r3/r4/r5/r6/r61 artifacts are never written; new clips go to r62/.
  * S23 reuses its r61 record (flock-only overlay, drawing unchanged).
  * No hero i2v attempts (ZeroGPU quota still exhausted; S09/S11 keep
    their r61 fallback records verbatim).

Usage: venv/bin/python tools/render_r62.py [--no-vision] [--skip-qa]
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("render_r62")

OUT_DIR = PROJECT_ROOT / "results" / "dino_v2"
R62_SHOTS_DIR = OUT_DIR / "shots" / "r62"
FPS = 30
WIDTH, HEIGHT = 1920, 1080

# S01: reroute (blobby AI clip + duration fit); S15: template fix (also
# breaks the S07/S15 dhash cluster); the rest carry dust/rain overlays
# whose drawing changed (soft motes + dimmer rain). S23 is flock-only and
# reuses its r61 clip.
FORCE_RERENDER = ("S01", "S06", "S08", "S11", "S13", "S15", "S16", "S20",
                  "S21", "S22", "S24")
R62_REASON = ("r6.2 timeline fix: soft motes + dim rain / S15 template "
              "redraw / S01 keyframe reroute")


def _patch_s01(shot: dict) -> None:
    """AI_VIDEO cache clip: blobby anatomy, 5.9s vs 9.64s beat. Reroute to
    AI_IMAGE_MOTION on the pinned hero keyframe (S14/S20 precedent)."""
    shot["renderer"] = "AI_IMAGE_MOTION"
    shot.setdefault("metadata", {})["r62_reroute"] = (
        "AI_VIDEO cache clip (blobs + 5.9s-vs-9.64s fit) -> "
        "AI_IMAGE_MOTION on pinned keyframe")
    still = (shot.get("asset_requirements") or {}).get("still_path")
    logger.info("S01 reroute: still_path=%s", still or "<none - broker>")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--skip-qa", action="store_true",
                    help="skip shot QA (gate VISUAL gate will be partial)")
    args = ap.parse_args(argv)

    from tools.render_r6 import _load_env, apply_content_patches
    from tools.render_r5 import apply_edits_r5

    _load_env()
    from engine.v3.assemble.assembler import assemble_master
    from engine.v3.qa.shot_qa import qa_shotlist
    from engine.v3.qa.video_qa import publish_gate
    from engine.v3.render.runner import render_shot

    t0 = time.time()
    style = json.loads((OUT_DIR / "style.json").read_text())
    script_doc = json.loads((OUT_DIR / "script.json").read_text())
    shotlist = json.loads((OUT_DIR / "shotlist.json").read_text())
    research = json.loads((OUT_DIR / "research.json").read_text())
    r61_records = json.loads((OUT_DIR / "render_records_r61.json").read_text())

    script_doc, shots, edit_log = apply_edits_r5(script_doc,
                                                 shotlist["shots"])
    patch_log = apply_content_patches(shots)
    (OUT_DIR / "edit_log_r62.json").write_text(json.dumps(
        {"edit_log": edit_log, "content_patches": patch_log,
         "planned_duration_sec":
             round(sum(float(s.get("duration_sec") or 0) for s in shots), 2)},
        indent=2))
    logger.info("edits applied: %s patch(es), %s narration trim(s)",
                len(patch_log), len(edit_log["narration_trims"]))

    # ── records: reuse r61 verbatim; force re-render the artifact shots ──
    records_path = OUT_DIR / "render_records_r62.json"
    records: dict[str, dict] = {}
    for shot in shots:
        sid = shot["shot_id"]
        if sid == "S01":
            _patch_s01(shot)
        base = r61_records.get(sid)
        if sid in FORCE_RERENDER:
            rec = render_shot(shot, style, R62_SHOTS_DIR, fps=FPS,
                              resolution=(WIDTH, HEIGHT), aspect="16:9",
                              attempt=0,
                              available=lambda rid: rid != "AI_VIDEO")
            rec.setdefault("metadata", {})["r62_rerender"] = R62_REASON
            records[sid] = rec
        elif base and base.get("ok") and base.get("path") \
                and Path(base["path"]).exists():
            rec = copy.deepcopy(base)
            rec.setdefault("metadata", {})["reused_from"] = "r61"
            records[sid] = rec
        else:  # never invent: re-render offline
            rec = render_shot(shot, style, R62_SHOTS_DIR, fps=FPS,
                              resolution=(WIDTH, HEIGHT), aspect="16:9",
                              attempt=0,
                              available=lambda rid: rid != "AI_VIDEO")
            records[sid] = rec
        ok = "OK " if records[sid].get("ok") else "FAIL"
        src = records[sid].get("metadata", {}).get("reused_from") or "r62"
        logger.info("  %s %s via %s (%s)", sid, ok,
                    records[sid].get("renderer_used"), src)
        records_path.write_text(json.dumps(records, indent=2, default=str))

    # ── shot QA (content-hash cached; the new clips re-QA automatically) ──
    reports: dict[str, dict] = {}
    if not args.skip_qa:
        reports = qa_shotlist(shots, records, OUT_DIR / "qa" / "shots",
                              use_vision=not args.no_vision,
                              min_height=HEIGHT // 2, force_fail=False,
                              cache=True)
        avg = sum(r.get("score", 0) for r in reports.values()) / max(
            len(reports), 1)
        logger.info("shot_qa: avg %.0f over %s", avg, len(reports))

    # ── assemble master_r62 (v4.1 no-freeze fit runs inside) ──
    assembled = assemble_master(
        shotlist.get("topic", "dino_v2"), shots, script_doc, records,
        OUT_DIR, width=WIDTH, height=HEIGHT, fps=FPS, audio_master=True)
    master_r62 = OUT_DIR / "master_r62.mp4"
    master_new = OUT_DIR / "master.mp4"
    if master_new.exists() and master_new != master_r62:
        master_new.replace(master_r62)
    logger.info("assembled %s (%s KB, %.1fs)", master_r62.name,
                master_r62.stat().st_size // 1024,
                assembled.get("video_duration") or 0)

    # align plan durations to the final timeline (same as run.py/r3-r61)
    final_durs = {a["shot_id"]: a["final"]
                  for a in assembled.get("timing_adjustments", [])
                  if "shot_id" in a}
    for s in shots:
        if s["shot_id"] in final_durs:
            s["duration_sec"] = final_durs[s["shot_id"]]

    # ── §19 publish gate with per-shot audits + design metadata ──
    gate = publish_gate(
        master_r62, shots, script_doc, research, style, reports,
        OUT_DIR / "publish_gate_r62.json",
        use_vision=not args.no_vision, use_llm=True,
        require_audio=True,
        expected_width=WIDTH, expected_height=HEIGHT,
        records=records)
    logger.info("gate: %s failed=%s", gate["overall"],
                gate["failed_gates"])
    for name, g in gate["gates"].items():
        logger.info("  %-9s %-22s %s", "PASS" if g["pass"] else "FAIL",
                    name, g["detail"][:150])
    logger.info("elapsed %.0fs", time.time() - t0)
    return 0 if gate["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
