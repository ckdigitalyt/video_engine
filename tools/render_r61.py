#!/usr/bin/env python3
"""render_r61.py — dino_v2 r6.1 re-render: composite-cast fix validation.

The r6 gate (FAIL 13/16) traced every remaining green/magenta wash to ONE
engine bug, proven by A/B + bisect on ffmpeg 6.1.1: the `blend` filter
applies screen/multiply to every plane and, with packed rgb24 inputs, still
lands in YUV-plane math — multiply halves neutral chroma 128→64 (green
wash), screen pushes it to 192 (magenta wash). The r3.1 rgb24 "fix" was
inert: a neutral gray still + flock overlay through the old code produced
U=76/V=76 (exact YUV-blend prediction at opacity 0.8). kenburns now runs
the overlay blend in planar gbrp — verified neutral (U=V=128) for
multiply/screen/stacked at opacity 0.8 and 1.0.

This driver force-rerenders exactly the 10 overlay-bearing shots (stills
are chroma-neutral and come from broker cache — no new generation spend),
reuses every other r6 record verbatim, then replays the r6 tail:
shot QA → assemble master_r61 → §19 publish gate → publish_gate_r61.json.

Scope guards:
  * r3/r4/r5/r6 artifacts are never written; new clips go to shots/r61/.
  * No hero i2v attempts (ZeroGPU account quota still exhausted; S09/S11
    keep their r6 fallback records verbatim).
  * hf_router stays out of any broker chain (monthly wallet 402-dead).

Usage: venv/bin/python tools/render_r61.py [--no-vision] [--skip-qa]
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
logger = logging.getLogger("render_r61")

OUT_DIR = PROJECT_ROOT / "results" / "dino_v2"
R61_SHOTS_DIR = OUT_DIR / "shots" / "r61"
FPS = 30
WIDTH, HEIGHT = 1920, 1080

# every r6 clip carrying toolkit overlay layers — chroma scan showed the
# cast on all 10 (multiply overlays → green, screen overlays → magenta)
FORCE_RERENDER = ("S06", "S08", "S11", "S13", "S16", "S20", "S21", "S22",
                  "S23", "S24")
R61_REASON = ("composite cast: ffmpeg 6.1 blend+rgb24 = YUV-plane math "
              "(multiply 128->64 green / screen 128->192 magenta); blend "
              "now runs in gbrp")


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
    r6_records = json.loads((OUT_DIR / "render_records_r6.json").read_text())

    script_doc, shots, edit_log = apply_edits_r5(script_doc,
                                                 shotlist["shots"])
    patch_log = apply_content_patches(shots)
    (OUT_DIR / "edit_log_r61.json").write_text(json.dumps(
        {"edit_log": edit_log, "content_patches": patch_log,
         "planned_duration_sec":
             round(sum(float(s.get("duration_sec") or 0) for s in shots), 2)},
        indent=2))
    logger.info("edits applied: %s patch(es), %s narration trim(s)",
                len(patch_log), len(edit_log["narration_trims"]))

    # ── records: reuse r6 verbatim; force re-render the 10 cast shots ──
    records_path = OUT_DIR / "render_records_r61.json"
    records: dict[str, dict] = {}
    for shot in shots:
        sid = shot["shot_id"]
        base = r6_records.get(sid)
        if sid in FORCE_RERENDER:
            rec = render_shot(shot, style, R61_SHOTS_DIR, fps=FPS,
                              resolution=(WIDTH, HEIGHT), aspect="16:9",
                              attempt=0,
                              available=lambda rid: rid != "AI_VIDEO")
            rec.setdefault("metadata", {})["r61_rerender"] = R61_REASON
            records[sid] = rec
        elif base and base.get("ok") and base.get("path") \
                and Path(base["path"]).exists():
            rec = copy.deepcopy(base)
            rec.setdefault("metadata", {})["reused_from"] = "r6"
            records[sid] = rec
        else:  # never invent: re-render offline
            rec = render_shot(shot, style, R61_SHOTS_DIR, fps=FPS,
                              resolution=(WIDTH, HEIGHT), aspect="16:9",
                              attempt=0,
                              available=lambda rid: rid != "AI_VIDEO")
            records[sid] = rec
        ok = "OK " if records[sid].get("ok") else "FAIL"
        src = records[sid].get("metadata", {}).get("reused_from") or "r61"
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

    # ── assemble master_r61 (v4.1 no-freeze fit runs inside) ──
    assembled = assemble_master(
        shotlist.get("topic", "dino_v2"), shots, script_doc, records,
        OUT_DIR, width=WIDTH, height=HEIGHT, fps=FPS, audio_master=True)
    master_r61 = OUT_DIR / "master_r61.mp4"
    master_new = OUT_DIR / "master.mp4"
    if master_new.exists() and master_new != master_r61:
        master_new.replace(master_r61)
    logger.info("assembled %s (%s KB, %.1fs)", master_r61.name,
                master_r61.stat().st_size // 1024,
                assembled.get("video_duration") or 0)

    # align plan durations to the final timeline (same as run.py/r3-r6)
    final_durs = {a["shot_id"]: a["final"]
                  for a in assembled.get("timing_adjustments", [])
                  if "shot_id" in a}
    for s in shots:
        if s["shot_id"] in final_durs:
            s["duration_sec"] = final_durs[s["shot_id"]]

    # ── §19 publish gate with per-shot audits + design metadata ──
    gate = publish_gate(
        master_r61, shots, script_doc, research, style, reports,
        OUT_DIR / "publish_gate_r61.json",
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
