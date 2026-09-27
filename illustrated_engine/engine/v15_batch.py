"""V15 — batch runner: many stories, one command, one report.

Stories run SEQUENTIALLY (CPU budget §26: Remotion concurrency <= 2 inside a
story render). Plate cache, plan cache and TTS caches are global/per-story
and content-addressed, so a crashed batch resumes cheaply: re-running skips
every cached plan, plate, scene render and composite (§25). A story that
HOLDs or errors never stops the batch; it is recorded with its reasons.

Usage:
  python3 -m engine.v15_batch --stories stories/a,stories/b \\
      --work build/v15/batch_2026-09-27 [--no-llm] [--no-judge]
  python3 -m engine.v15_batch --all --work ...        # every story dir
Writes <work>/batch_report.json (+ prints a summary table).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_batch(story_dirs: list, work: Path, **kw) -> dict:
    from engine.v15_pipeline import run_pipeline
    work.mkdir(parents=True, exist_ok=True)
    rows, t0 = [], time.time()
    totals = {"llm_calls": 0, "image_calls": 0, "vision_calls": 0}
    for sd in story_dirs:
        sd = Path(sd)
        ts = time.time()
        row = {"story": sd.name}
        try:
            rep = run_pipeline(sd, work / sd.name, **kw)
            row.update(verdict=rep["publish_gate"],
                       failures=rep["gate"]["failures"],
                       duration_s=rep["gate"]["checks"]["av"].get("duration_s"),
                       plan=rep["plan"]["source"], deck=rep.get("deck"),
                       plates=rep.get("plate_providers"),
                       costs=rep["costs"], timings=rep["timings"])
            for k in totals:
                totals[k] += rep["costs"].get(k, 0)
        except Exception as e:  # never stop the batch
            row.update(verdict="ERROR", error=f"{type(e).__name__}: {e}"[:400],
                       trace=traceback.format_exc()[-1200:])
        row["wall_s"] = round(time.time() - ts, 1)
        rows.append(row)
        (work / "batch_report.json").write_text(json.dumps(
            {"stories": rows, "totals": totals,
             "wall_s": round(time.time() - t0, 1)}, indent=1))
    return {"stories": rows, "totals": totals,
            "wall_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(prog="engine.v15_batch")
    ap.add_argument("--stories", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--work", required=True)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args()
    if a.all:
        dirs = sorted(p.parent for p in (ROOT / "stories").glob("*/story.json"))
    else:
        dirs = [Path(s) for s in a.stories.split(",") if s.strip()]
    if not dirs:
        ap.error("no stories given")
    rep = run_batch(dirs, Path(a.work), use_llm=not a.no_llm,
                    use_judge=not a.no_judge)
    for r in rep["stories"]:
        print(f"{r['story']:<24} {r['verdict']:<6} {r.get('wall_s', 0):>7.1f}s "
              f"{'; '.join(sum((v[:1] for v in (r.get('failures') or {}).values()), []))[:90] or r.get('error', '')}")
    print(json.dumps(rep["totals"]))
    return 0 if all(r["verdict"] == "PASS" for r in rep["stories"]) else 1


if __name__ == "__main__":
    sys.exit(main())
