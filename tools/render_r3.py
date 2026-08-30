#!/usr/bin/env python3
"""render_r3.py — dino_v2 r3 render driver (V4 phase 4).

Re-renders the edited plan (tools/edit_dino_r3.py) with the event-capable
renderers (engine/v4/motion_toolkit.py adapters), assembles master_r3.mp4
and runs the full §19 publish gate with per-shot audits, plan-time hold
approvals and dark_atmospheric design metadata.

Scope guards (phase-4 constraints):
  * AI_VIDEO is disabled — no provider attempts (quota is out; the pending
    hero i2v pass is owned by the 11:30 UTC cron agent, hero keyframes in
    results/dino_v2/hero_keyframes/ are NOT touched).
  * No selective-regen loop; fallback chains still apply per shot.
  * r2 artifacts (master_r2.mp4, publish_gate_r2.json, ...) are untouched.

Usage: venv/bin/python tools/render_r3.py [--no-vision] [--skip-qa]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("render_r3")

OUT_DIR = PROJECT_ROOT / "results" / "dino_v2"
R3_SHOTS_DIR = OUT_DIR / "shots" / "r3"
FPS = 30
WIDTH, HEIGHT = 1920, 1080


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--skip-qa", action="store_true",
                    help="skip shot QA (gate VISUAL gate will be partial)")
    ap.add_argument("--gate-only", action="store_true",
                    help="reuse existing r3 records, assemble + gate only")
    args = ap.parse_args(argv)

    from engine.v3.assemble.assembler import assemble_master
    from engine.v3.qa.shot_qa import qa_shotlist
    from engine.v3.render.runner import render_shot
    from tools.edit_dino_r3 import apply_edits

    t0 = time.time()
    style = json.loads((OUT_DIR / "style.json").read_text())
    script_doc = json.loads((OUT_DIR / "script.json").read_text())
    shotlist = json.loads((OUT_DIR / "shotlist.json").read_text())
    research = json.loads((OUT_DIR / "research.json").read_text())

    script_doc, shots, edit_log = apply_edits(script_doc, shotlist["shots"])
    (OUT_DIR / "edit_log_r3.json").write_text(json.dumps(
        {"edit_log": edit_log, "planned_duration_sec":
            round(sum(float(s.get("duration_sec") or 0) for s in shots), 2)},
        indent=2))
    logger.info("edits applied: %s shot(s) removed, %s narration trim(s); "
                "planned %.2fs", len(edit_log["removed_shots"]),
                len(edit_log["narration_trims"]),
                sum(float(s.get("duration_sec") or 0) for s in shots))

    # ── render (AI_VIDEO off: quota guard, §7 handoff untouched) ──
    records_path = OUT_DIR / "render_records_r3.json"
    records: dict[str, dict] = {}
    if args.gate_only and records_path.exists():
        records = json.loads(records_path.read_text())
        logger.info("gate-only: reused %s records", len(records))
    else:
        def available(rid: str) -> bool:
            return rid != "AI_VIDEO"  # §7 hero pass is the cron agent's job

        for shot in shots:
            rec = render_shot(shot, style, R3_SHOTS_DIR, fps=FPS,
                              resolution=(WIDTH, HEIGHT), aspect="16:9",
                              attempt=0, available=available)
            records[shot["shot_id"]] = rec
            ok = "OK " if rec.get("ok") else "FAIL"
            logger.info("  %s %s via %s", shot["shot_id"], ok,
                        rec.get("renderer_used"))
            records_path.write_text(json.dumps(records, indent=2,
                                               default=str))
        ok_n = sum(1 for r in records.values() if r.get("ok"))
        logger.info("render: %s/%s shots OK (%.0fs)",
                    ok_n, len(shots), time.time() - t0)
        if ok_n < len(shots):
            logger.warning("FAILED shots: %s",
                           [k for k, v in records.items() if not v.get("ok")])

    # ── shot QA (vision online, content-hash cached) ──
    reports: dict[str, dict] = {}
    if not args.skip_qa:
        reports = qa_shotlist(shots, records, OUT_DIR / "qa" / "shots",
                              use_vision=not args.no_vision,
                              min_height=HEIGHT // 2, force_fail=False,
                              cache=True)
        avg = sum(r.get("score", 0) for r in reports.values()) / max(
            len(reports), 1)
        logger.info("shot_qa: avg %.0f over %s", avg, len(reports))

    # ── assemble master_r3 ──
    assembled = assemble_master(
        shotlist.get("topic", "dino_v2"), shots, script_doc, records,
        OUT_DIR, width=WIDTH, height=HEIGHT, fps=FPS, audio_master=True)
    master_r3 = OUT_DIR / "master_r3.mp4"
    master_new = OUT_DIR / "master.mp4"
    if master_new.exists() and master_new != master_r3:
        master_new.replace(master_r3)
    logger.info("assembled %s (%s KB, %.1fs)", master_r3.name,
                master_r3.stat().st_size // 1024,
                assembled.get("video_duration") or 0)

    # align plan durations to the final timeline (same as run.py)
    final_durs = {a["shot_id"]: a["final"]
                  for a in assembled.get("timing_adjustments", [])
                  if "shot_id" in a}
    for s in shots:
        if s["shot_id"] in final_durs:
            s["duration_sec"] = final_durs[s["shot_id"]]

    # ── §19 publish gate with per-shot audits + design metadata ──
    from engine.v3.qa.video_qa import publish_gate

    gate = publish_gate(
        master_r3, shots, script_doc, research, style, reports,
        OUT_DIR / "publish_gate_r3.json",
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
