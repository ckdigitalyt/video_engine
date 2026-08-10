#!/usr/bin/env python3
"""
repair_plan.py — Translate reviewer defect IDs into a pipeline repair plan.

The v20 review schema returns machine-actionable defects:

    {"scene": 7, "shot": "s07_sh02", "problem": "irrelevant_asset",
     "severity": "fatal", "action": "regenerate_visual"}

This tool reads every review_*.json in a run dir, merges the defects, and
emits a repair plan keyed by scene/asset with the exact mission_stills.py
flags to run it (--scenes / --assets), which the manifest dependency graph
then executes selectively.

Usage:
    python3 tools/repair_plan.py --run results/is_time_real
    python3 tools/repair_plan.py --run results/is_time_real --json
"""

import argparse
import glob
import json
import os
import sys

ACTION_TO_FLAGS = {
    "regenerate_visual": "assets",     # per-shot id, cheapest
    "rewrite_script": "scenes",        # scene-level (script change cascades)
    "regenerate_audio": "scenes",      # scene-level
    "regenerate_subtitles": "scenes",  # scene-level
    "fix_transition": "scenes",        # scene-level re-render
    "reassemble": "scenes",            # scene-level (no-op if unchanged)
    "none": None,
}


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def collect_defects(run_dir: str) -> list[dict]:
    defects = []
    for path in sorted(glob.glob(os.path.join(run_dir, "review_*.json"))):
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        raw = data.get("defects") or data.get("machine_actionable_defects") or []
        for d in raw:
            if isinstance(d, dict) and d.get("action"):
                d["_source"] = os.path.basename(path)
                defects.append(d)
    return defects


def build_plan(run_dir: str) -> dict:
    defects = collect_defects(run_dir)
    scenes = {}   # scene idx -> list of actions
    assets = set()  # shot ids
    by_severity = {"fatal": 0, "high": 0, "medium": 0, "low": 0}
    for d in defects:
        sev = (d.get("severity") or "medium").lower()
        by_severity[sev] = by_severity.get(sev, 0) + 1
        action = d.get("action")
        scene = d.get("scene")
        shot = d.get("shot")
        if action == "regenerate_visual" and shot:
            assets.add(shot)
        elif scene is not None:
            scenes.setdefault(int(scene), set()).add(action)
        elif action == "reassemble":
            scenes.setdefault(0, set()).add("reassemble")
    return {
        "run_dir": run_dir,
        "defect_count": len(defects),
        "severity_counts": by_severity,
        "scenes": {str(k): sorted(v) for k, v in sorted(scenes.items())},
        "assets": sorted(assets),
    }


def plan_to_flags(plan: dict) -> list[str]:
    flags = []
    scenes = [int(k) for k in plan.get("scenes", {})]
    if scenes:
        flags.append("--scenes " + ",".join(str(s) for s in sorted(scenes)))
    if plan.get("assets"):
        flags.append("--assets " + ",".join(plan["assets"]))
    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="results/<slug> dir")
    ap.add_argument("--json", action="store_true", help="emit JSON plan only")
    args = ap.parse_args()

    plan = build_plan(args.run)
    if args.json:
        print(json.dumps(plan, indent=2))
        return

    print(f"REPAIR PLAN — {args.run}")
    print(f"  defects found: {plan['defect_count']} "
          f"(fatal {plan['severity_counts']['fatal']}, "
          f"high {plan['severity_counts']['high']}, "
          f"medium {plan['severity_counts']['medium']}, "
          f"low {plan['severity_counts']['low']})")
    if plan["scenes"]:
        print("  scene-level repairs:")
        for sc, actions in plan["scenes"].items():
            print(f"    scene {sc}: {', '.join(actions)}")
    if plan["assets"]:
        print("  asset-level repairs (cheapest, one image each):")
        for a in plan["assets"]:
            print(f"    {a}")
    if not plan["scenes"] and not plan["assets"]:
        print("  no actionable defects — nothing to repair")
        return
    flags = plan_to_flags(plan)
    topic_hint = os.path.basename(args.run.rstrip("/")).replace("_", " ")
    print("\n  suggested command:")
    print(f"    python3 mission_stills.py --topic \"{topic_hint}\" "
          + " ".join(flags) + " --reuse")


if __name__ == "__main__":
    main()
