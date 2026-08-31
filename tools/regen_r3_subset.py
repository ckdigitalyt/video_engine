#!/usr/bin/env python3
"""regen_r3_subset.py — selective shot re-render for the r3 repair pass.

Re-renders ONLY the listed shots through the same render_shot path
render_r3.py uses (edits applied, AI_VIDEO unavailable), merges the new
records into render_records_r3.json and re-runs shot QA for those shots.
The full assemble + gate stays with tools/render_r3.py --gate-only.

Usage: venv/bin/python tools/regen_r3_subset.py --shots S04,S07,S12
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
logger = logging.getLogger("regen_r3")

OUT_DIR = PROJECT_ROOT / "results" / "dino_v2"
R3_SHOTS_DIR = OUT_DIR / "shots" / "r3"
FPS = 30
WIDTH, HEIGHT = 1920, 1080


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True,
                    help="comma-separated shot ids to re-render")
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--attempt", type=int, default=0,
                    help="render attempt (varies motion seed; image stays "
                         "pinned via asset_requirements.still_path)")
    args = ap.parse_args(argv)
    targets = [s.strip().upper() for s in args.shots.split(",") if s.strip()]

    from engine.v3.qa.shot_qa import qa_shotlist
    from engine.v3.render.runner import render_shot
    from tools.edit_dino_r3 import apply_edits

    t0 = time.time()
    style = json.loads((OUT_DIR / "style.json").read_text())
    script_doc = json.loads((OUT_DIR / "script.json").read_text())
    shotlist = json.loads((OUT_DIR / "shotlist.json").read_text())
    script_doc, shots, edit_log = apply_edits(script_doc, shotlist["shots"])
    by_id = {str(s.get("shot_id")): s for s in shots}

    records_path = OUT_DIR / "render_records_r3.json"
    records = json.loads(records_path.read_text()) if records_path.exists() \
        else {}

    def available(rid: str) -> bool:
        return rid != "AI_VIDEO"  # §7 hero pass is the cron agent's job

    done: list[str] = []
    for sid in targets:
        shot = by_id.get(sid)
        if shot is None:
            logger.warning("shot %s not in edited plan — skipped", sid)
            continue
        rec = render_shot(shot, style, R3_SHOTS_DIR, fps=FPS,
                          resolution=(WIDTH, HEIGHT), aspect="16:9",
                          attempt=args.attempt, available=available)
        records[sid] = rec
        done.append(sid)
        ok = "OK " if rec.get("ok") else "FAIL"
        logger.info("  %s %s via %s (%.0fs)", sid, ok,
                    rec.get("renderer_used"), time.time() - t0)
    records_path.write_text(json.dumps(records, indent=2, default=str))
    logger.info("records updated for %s", done)

    # QA for the re-rendered shots only (content-hash cached per clip)
    target_records = {sid: records[sid] for sid in done if sid in records}
    target_shots = [by_id[sid] for sid in done if sid in by_id]
    if target_records:
        reports = qa_shotlist(target_shots, target_records,
                              OUT_DIR / "qa" / "shots",
                              use_vision=not args.no_vision,
                              min_height=HEIGHT // 2, force_fail=False,
                              cache=True)
        for sid, r in sorted(reports.items()):
            logger.info("  QA %s score=%s action=%s", sid, r.get("score"),
                        r.get("action"))
    logger.info("elapsed %.0fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
