#!/usr/bin/env python3
"""resume_r6_gate.py — gate-only resume of the interrupted r6 run.

The r6 pass completed all shot records (22/22; S02/S10 are edit-layer
removals) but was SIGTERM'd before shot QA / assembly / publish gate.
This driver replays exactly the tail of render_r6.py from the on-disk
records: no broker calls, no re-renders, r3/r4/r5 artifacts untouched.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("resume_r6")


def main() -> int:
    from tools.render_r6 import (FPS, HEIGHT, OUT_DIR, WIDTH, _load_env,
                                 apply_content_patches)

    _load_env()
    from engine.v3.assemble.assembler import assemble_master
    from engine.v3.qa.shot_qa import qa_shotlist
    from engine.v3.qa.video_qa import publish_gate
    from tools.render_r5 import apply_edits_r5

    t0 = time.time()
    style = json.loads((OUT_DIR / "style.json").read_text())
    script_doc = json.loads((OUT_DIR / "script.json").read_text())
    shotlist = json.loads((OUT_DIR / "shotlist.json").read_text())
    research = json.loads((OUT_DIR / "research.json").read_text())
    records = json.loads((OUT_DIR / "render_records_r6.json").read_text())

    script_doc, shots, edit_log = apply_edits_r5(script_doc,
                                                 shotlist["shots"])
    patch_log = apply_content_patches(shots)
    (OUT_DIR / "edit_log_r6.json").write_text(json.dumps(
        {"edit_log": edit_log, "content_patches": patch_log,
         "planned_duration_sec":
             round(sum(float(s.get("duration_sec") or 0) for s in shots), 2)},
        indent=2))
    logger.info("resume: %s records, %s timeline shots", len(records),
                len(shots))

    # ── shot QA (vision online; qa_version=2 forces re-run past r5 cache) ──
    reports = qa_shotlist(shots, records, OUT_DIR / "qa" / "shots",
                          use_vision=True, min_height=HEIGHT // 2,
                          force_fail=False, cache=True)
    avg = sum(r.get("score", 0) for r in reports.values()) / max(
        len(reports), 1)
    logger.info("shot_qa: avg %.0f over %s", avg, len(reports))

    # ── assemble master_r6 (v4.1 no-freeze fit runs inside) ──
    assembled = assemble_master(
        shotlist.get("topic", "dino_v2"), shots, script_doc, records,
        OUT_DIR, width=WIDTH, height=HEIGHT, fps=FPS, audio_master=True)
    master_r6 = OUT_DIR / "master_r6.mp4"
    master_new = OUT_DIR / "master.mp4"
    if master_new.exists() and master_new != master_r6:
        master_new.replace(master_r6)
    logger.info("assembled %s (%s KB, %.1fs)", master_r6.name,
                master_r6.stat().st_size // 1024,
                assembled.get("video_duration") or 0)

    # align plan durations to the final timeline (same as run.py/r3/r4/r5)
    final_durs = {a["shot_id"]: a["final"]
                  for a in assembled.get("timing_adjustments", [])
                  if "shot_id" in a}
    for s in shots:
        if s["shot_id"] in final_durs:
            s["duration_sec"] = final_durs[s["shot_id"]]

    # ── §19 publish gate with per-shot audits + design metadata ──
    gate = publish_gate(
        master_r6, shots, script_doc, research, style, reports,
        OUT_DIR / "publish_gate_r6.json",
        use_vision=True, use_llm=True, require_audio=True,
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
