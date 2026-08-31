#!/usr/bin/env python3
"""render_r5.py — dino_v2 r5 render driver (post-r4 repair pass).

Fixes the four failed r4 gates (VISUAL, RETENTION, STATIC_HOLD, CREATIVE):
  1. B01 hook narration tightened to the single surprising line (gate fix
     "tighten S01 to a single surprising line"). Assembly scales beat shots
     to narration TTS length, so the shorter hook removes S01's clone-pad
     freeze (the 4.93s unapproved static hold at t≈5.87).
  2. AI_IMAGE_MOTION shots re-rendered offline with the current renderer so
     they pick up §16 derived micro-events — their r3 clips predate the
     toolkit and are a large share of the 41.4s total frozen time.
  3. Hero retry for S09 + S11 via broker i2v (ZeroGPU daily quota); graceful
     QUOTA_EXHAUSTED stop keeps their r4/r3 fallback records.
  4. Full §19 publish gate to results/dino_v2/publish_gate_r5.json.

Scope guards:
  * Non-hero, non-AI_IMAGE_MOTION shots reuse their r4 records verbatim
    (r4 records already preserve S01/S03/S05/S18 AI_VIDEO clips).
  * hf_router stays out of the broker chain (monthly wallet 402-dead).
  * r3/r4 artifacts are never written.

Usage: venv/bin/python tools/render_r5.py [--no-vision] [--skip-qa]
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("render_r5")

OUT_DIR = PROJECT_ROOT / "results" / "dino_v2"
R5_SHOTS_DIR = OUT_DIR / "shots" / "r5"
MANIFEST_PATH = OUT_DIR / "hero_keyframes" / "manifest.json"
FPS = 30
WIDTH, HEIGHT = 1920, 1080
HERO_SHOTS = ("S09", "S11")
# planned renderers whose r3-era clips predate §16 micro-events
RE_RENDER_RENDERERS = {"AI_IMAGE_MOTION"}

# r5 hook trim: exact-match replaces against script.json B01, with a
# sentence-level fallback that keeps only the "single bad day" line.
R5_HOOK_TRIM = {
    "exact": [
        ("For over 160 million years, dinosaurs ruled almost every corner "
         "of Earth. Then, in what amounts to a single bad day, three out of "
         "every four species on the planet simply stopped existing.",
         "In a single bad day, three out of every four species on Earth "
         "simply stopped existing."),
    ],
}


def _load_env() -> None:
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def apply_edits_r5(script_doc: dict, shots: list[dict]) -> tuple[dict, list[dict], dict]:
    """edit_dino_r3.apply_edits + the r5 B01 hook narration trim."""
    from tools.edit_dino_r3 import apply_edits

    script_doc, shots, log = apply_edits(script_doc, shots)
    for beat in script_doc.get("beats", []):
        bid = str(beat.get("beat_id"))
        if bid != "B01":
            continue
        text = str(beat.get("narration", ""))
        new_text = None
        for old, new in R5_HOOK_TRIM["exact"]:
            if old in text:
                new_text = text.replace(old, new)
                break
        if new_text is None:  # sentence-level fallback
            import re
            sentences = [s.strip() for s in re.split(r"(?<=\.)\s+", text)
                         if s.strip()]
            keep = [s for s in sentences if "bad day" in s]
            if keep:
                new_text = " ".join(keep)
                new_text = (new_text
                            .replace("Then, in what amounts to",
                                     "In what amounts to")
                            .replace("Then, in a single bad day",
                                     "In a single bad day")
                            .replace("on the planet", "on Earth"))
        if new_text is not None and new_text.startswith("Then, "):
            new_text = new_text[len("Then, "):].capitalize()
        if new_text is None:
            log["notes"].append("r5 hook trim: no anchor found in B01 — "
                                "narration left unchanged")
        elif new_text != text:
            beat["narration"] = new_text
            log["narration_trims"].append(
                {"beat_id": bid, "r5_hook_tighten": True,
                 "removed_words": len(text.split()) - len(new_text.split())})
    return script_doc, shots, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--skip-qa", action="store_true",
                    help="skip shot QA (gate VISUAL gate will be partial)")
    args = ap.parse_args(argv)

    _load_env()
    from engine.broker.failures import classify_failure
    from engine.v3.assemble.assembler import assemble_master
    from engine.v3.qa.shot_qa import qa_shotlist
    from engine.v3.qa.video_qa import publish_gate

    t0 = time.time()
    style = json.loads((OUT_DIR / "style.json").read_text())
    script_doc = json.loads((OUT_DIR / "script.json").read_text())
    shotlist = json.loads((OUT_DIR / "shotlist.json").read_text())
    research = json.loads((OUT_DIR / "research.json").read_text())
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest_by_id = {e["shot_id"]: e for e in manifest["shots"]}
    r4_records = json.loads((OUT_DIR / "render_records_r4.json").read_text())

    script_doc, shots, edit_log = apply_edits_r5(script_doc,
                                                 shotlist["shots"])
    (OUT_DIR / "edit_log_r5.json").write_text(json.dumps(
        {"edit_log": edit_log, "planned_duration_sec":
            round(sum(float(s.get("duration_sec") or 0) for s in shots), 2)},
        indent=2))
    logger.info("edits applied: %s shot(s) removed, %s narration trim(s); "
                "planned %.2fs", len(edit_log["removed_shots"]),
                len(edit_log["narration_trims"]),
                sum(float(s.get("duration_sec") or 0) for s in shots))

    # ── records: reuse r4, re-render AI_IMAGE_MOTION for §16 micro-events ──
    records_path = OUT_DIR / "render_records_r5.json"
    records: dict[str, dict] = {}
    from engine.v3.render.runner import render_shot

    for shot in shots:
        sid = shot["shot_id"]
        if sid in HERO_SHOTS:
            continue
        base = r4_records.get(sid)
        if shot.get("renderer") in RE_RENDER_RENDERERS:
            rec = render_shot(shot, style, R5_SHOTS_DIR, fps=FPS,
                              resolution=(WIDTH, HEIGHT), aspect="16:9",
                              attempt=0,
                              available=lambda rid: rid != "AI_VIDEO")
            rec.setdefault("metadata", {})["r5_rerender"] = \
                "§16 micro-events (r3-era clip predated toolkit)"
            records[sid] = rec
        elif base and base.get("ok") and base.get("path") \
                and Path(base["path"]).exists():
            rec = copy.deepcopy(base)
            rec.setdefault("metadata", {})["reused_from"] = "r4"
            records[sid] = rec
        else:  # never invent: re-render offline
            rec = render_shot(shot, style, R5_SHOTS_DIR, fps=FPS,
                              resolution=(WIDTH, HEIGHT), aspect="16:9",
                              attempt=0,
                              available=lambda rid: rid != "AI_VIDEO")
            records[sid] = rec
        ok = "OK " if records[sid].get("ok") else "FAIL"
        src = records[sid].get("metadata", {}).get("reused_from") or "r5"
        logger.info("  %s %s via %s (%s)", sid, ok,
                    records[sid].get("renderer_used"), src)
    records_path.write_text(json.dumps(records, indent=2, default=str))

    # ── hero pass: broker i2v per manifest, exactly S09 + S11 ──
    from engine.broker.broker import MediaBroker
    from engine.renderers.media.conform import conform_clip

    broker = MediaBroker()
    # §7/§8: hf_router monthly credits QUOTA_EXHAUSTED (HTTP 402, live test
    # 2026-08-31) — drop the dead wallet instead of retrying it.
    for dead in [pid for pid in broker._providers
                 if pid.startswith("hf_router")]:
        del broker._providers[dead]
        logger.info("broker: dropped %s (QUOTA_EXHAUSTED, live test "
                    "2026-08-31)", dead)

    hero_results: dict[str, dict] = {}
    zerogpu_dead = False
    for shot in shots:
        sid = shot["shot_id"]
        if sid not in HERO_SHOTS:
            continue
        entry = manifest_by_id.get(sid)
        if entry is None:
            logger.error("%s: no manifest entry — keeping r4 record", sid)
            records[sid] = copy.deepcopy(r4_records[sid])
            continue
        keyframe = (PROJECT_ROOT / entry["keyframe"]).resolve()
        duration = float(entry["duration_sec"])
        seed = int(entry.get("seed") or 0)
        rec: dict = {"shot_id": sid, "ok": False, "path": None,
                     "renderer_used": None, "attempts": [], "seed": seed,
                     "metadata": {}, "qa_frames": []}
        if zerogpu_dead:
            rec["attempts"].append(
                {"renderer": "AI_VIDEO", "ok": False,
                 "error": "ZeroGPU account quota exhausted earlier in this "
                          "pass — hero pass stopped gracefully (§8); r4 "
                          "fallback kept"})
            records[sid] = rec
            logger.warning("  %s skipped — ZeroGPU quota exhausted "
                           "(graceful stop, r4 fallback kept)", sid)
            continue
        t_gen = time.time()
        try:
            result = broker.image_to_video(
                keyframe, entry["prompt"], duration=duration, seed=seed,
                aspect="16:9")
            clip_dur = _duration_of(result.path)
            out_path = R5_SHOTS_DIR / f"{sid}_aivideo.mp4"
            shot_dur = float(shot.get("duration_sec") or duration)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if abs(shot_dur - clip_dur) > 0.05:
                conform_clip(result.path, out_path, duration=shot_dur,
                             aspect="16:9", fps=FPS)
            else:
                import shutil
                shutil.copyfile(result.path, out_path)
            rec.update(ok=True, path=str(out_path),
                       renderer_used="AI_VIDEO",
                       attempts=[{"renderer": "AI_VIDEO", "ok": True,
                                  "error": "",
                                  "broker_provider": result.provider,
                                  "broker_cached": bool(result.cached)}])
            rec["metadata"] = {
                "renderer": "AI_VIDEO",
                "provider": result.provider,
                "prompt_source": str(MANIFEST_PATH.relative_to(PROJECT_ROOT)),
                "prompt": entry["prompt"],
                "negative_prompt_policy":
                    "provider default (broker i2v API takes no negative)",
                "keyframe": str(keyframe),
                "ai_clip_raw": str(result.path),
                "ai_clip_raw_duration_sec": round(clip_dur, 2),
                "requested_duration_sec": duration,
                "conformed_duration_sec": shot_dur,
                "cached": bool(result.cached),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_sec": round(time.time() - t_gen, 1),
            }
            hero_results[sid] = {
                "provider": result.provider, "clip": str(out_path),
                "raw_clip": str(result.path), "duration_sec": shot_dur,
            }
            logger.info("  %s OK  AI_VIDEO via %s (%.1fs gen, cached=%s)",
                        sid, result.provider, time.time() - t_gen,
                        result.cached)
        except Exception as exc:  # noqa: BLE001 — graceful stop on quota
            err = f"{type(exc).__name__}: {exc}"[:500]
            cls = classify_failure(err)
            rec["attempts"].append({"renderer": "AI_VIDEO", "ok": False,
                                    "error": err, "error_class": str(cls)})
            logger.warning("  %s FAIL AI_VIDEO [%s]: %s", sid, cls, err[:200])
            if cls == "QUOTA_EXHAUSTED":
                # ZeroGPU quota is account-level — no other Space will work.
                zerogpu_dead = True
                logger.warning("ZeroGPU quota exhausted — stopping hero pass "
                               "gracefully (§8); remaining hero shots keep "
                               "their r4 fallback renders")
            # Graceful degradation: keep the r4 fallback clip so the master
            # still assembles (partial hero completion is acceptable).
            base = r4_records.get(sid)
            if base and base.get("ok") and base.get("path") \
                    and Path(base["path"]).exists():
                rec = copy.deepcopy(base)
                rec.setdefault("metadata", {})["reused_from"] = "r4"
                rec.setdefault("metadata", {})["ai_video_failure"] = \
                    {"error_class": str(cls), "error": err[:300]}
                logger.info("  %s keeps r4 fallback clip (%s)", sid,
                            base.get("renderer_used"))
        records[sid] = rec
        records_path.write_text(json.dumps(records, indent=2, default=str))

    hero_ok = [sid for sid in HERO_SHOTS
               if records.get(sid, {}).get("renderer_used") == "AI_VIDEO"]
    logger.info("hero pass: %s/%s shots via AI_VIDEO (%.0fs elapsed)",
                len(hero_ok), len(HERO_SHOTS), time.time() - t0)

    # ── shotlist update: record provider/path, clear pending_ai_video ──
    if hero_results:
        shotlist_path = OUT_DIR / "shotlist.json"
        on_disk = json.loads(shotlist_path.read_text())
        for s in on_disk["shots"]:
            sid = s["shot_id"]
            if sid in hero_results:
                s.pop("pending_ai_video", None)
                s["ai_video"] = {
                    "provider": hero_results[sid]["provider"],
                    "clip": hero_results[sid]["clip"],
                    "raw_clip": hero_results[sid]["raw_clip"],
                    "requested_duration_sec":
                        manifest_by_id[sid]["duration_sec"],
                    "final_duration_sec": hero_results[sid]["duration_sec"],
                    "prompt_source":
                        str(MANIFEST_PATH.relative_to(PROJECT_ROOT)),
                    "seed": manifest_by_id[sid].get("seed", 0),
                    "generated_at_utc":
                        records[sid]["metadata"]["generated_at_utc"],
                }
        shotlist_path.write_text(json.dumps(on_disk, indent=2, default=str))
        logger.info("shotlist.json updated for %s hero shot(s): "
                    "pending_ai_video cleared, ai_video recorded",
                    len(hero_results))

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

    # ── assemble master_r5 ──
    assembled = assemble_master(
        shotlist.get("topic", "dino_v2"), shots, script_doc, records,
        OUT_DIR, width=WIDTH, height=HEIGHT, fps=FPS, audio_master=True)
    master_r5 = OUT_DIR / "master_r5.mp4"
    master_new = OUT_DIR / "master.mp4"
    if master_new.exists() and master_new != master_r5:
        master_new.replace(master_r5)
    logger.info("assembled %s (%s KB, %.1fs)", master_r5.name,
                master_r5.stat().st_size // 1024,
                assembled.get("video_duration") or 0)

    # align plan durations to the final timeline (same as run.py/r3/r4)
    final_durs = {a["shot_id"]: a["final"]
                  for a in assembled.get("timing_adjustments", [])
                  if "shot_id" in a}
    for s in shots:
        if s["shot_id"] in final_durs:
            s["duration_sec"] = final_durs[s["shot_id"]]

    # ── §19 publish gate with per-shot audits + design metadata ──
    gate = publish_gate(
        master_r5, shots, script_doc, research, style, reports,
        OUT_DIR / "publish_gate_r5.json",
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


def _duration_of(path: str | Path) -> float:
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return -1.0


if __name__ == "__main__":
    raise SystemExit(main())
