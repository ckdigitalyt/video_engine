#!/usr/bin/env python3
"""Deterministic post-compaction state digest (Track A, execution directive 2026-09-19).

Reads ONLY existing artifacts (qa8 reports, git log) and writes build/state_digest.json.
Never deletes or modifies history/QA evidence. This file is the anchor Jade reads after
context compaction instead of relying on transcript memory.
"""
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # illustrated_engine/
BUILD = os.path.join(ROOT, "build")
OUT = os.path.join(BUILD, "state_digest.json")


def latest_qa8(limit=6):
    rows = []
    for p in sorted(glob.glob(os.path.join(BUILD, "qa", "qa8_*.json")),
                    key=os.path.getmtime, reverse=True)[:limit]:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        story = d.get("story_id") or os.path.basename(p)[3:-5]
        gates = d.get("gates") or {}
        if isinstance(gates, dict):
            failed = [str(k) for k, v in gates.items() if v is not True]
            total = len(gates)
        else:
            failed, total = [], 0
        rows.append({
            "story": story,
            "source_file": os.path.relpath(p, ROOT),
            "CAN_PUBLISH": d.get("CAN_PUBLISH"),  # verbatim from the qa8 JSON (source of truth)
            "gates_passed": total - len(failed),
            "gates_failed": failed,               # verbatim gate keys
            "mtime": int(os.path.getmtime(p)),
        })
    return rows


def recent_commits(n=10):
    try:
        out = subprocess.run(["git", "log", "--oneline", f"-{n}"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip().splitlines()
    except Exception:
        return []


def main():
    digest = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pipeline": "plan9 -> TTS(Fish) -> plan7 -> plan8 -> render5(4K) -> qa8full --v6",
        "latest_qa8": latest_qa8(),
        "recent_commits": recent_commits(),
        "constraints": ("docs/directives/ + workspace AGENTS.md are authoritative; "
                        "no metric/threshold tuning; no rewrites; deterministic gates win"),
        "next_action_hint": ("read latest_qa8 verdicts; failed gate -> targeted algorithm-level "
                             "fix; all verified PASS -> publish decision stays with deterministic "
                             "gates"),
    }
    os.makedirs(BUILD, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(digest, f, indent=1)
    os.replace(tmp, OUT)
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
