#!/usr/bin/env python3
"""Decision #13 item 5 — delivery half of the daily-mode cron: post each
video in one engine.v16_batch run to the requesting Discord channel.

PASS  -> format A: MP4 (under MAX_MB) + title + description + tags + a
         one-line verdict.
HOLD/FAIL/ERROR -> the hold reason only, NEVER the video.

Idempotent: a `delivered.json` state file inside --work records which
story names have already been posted, so re-running after a --resume
(the one allowed usage-limit retry in tools/daily_shorts.sh) never
double-posts an already-delivered video.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MAX_MB = 10


def _delivered_path(work: Path) -> Path:
    return work / "delivered.json"


def _load_delivered(work: Path) -> set:
    p = _delivered_path(work)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except (OSError, json.JSONDecodeError):
        return set()


def _mark_delivered(work: Path, story: str, delivered: set) -> None:
    delivered.add(story)
    _delivered_path(work).write_text(json.dumps(sorted(delivered)))


def post(channel: str, target: str, message: str, media: Path | None = None) -> bool:
    cmd = ["openclaw", "message", "send", "--channel", channel, "--target", target,
          "--message", message]
    if media is not None:
        cmd += ["--media", str(media)]
    return subprocess.run(cmd, check=False).returncode == 0


def deliver_one(work: Path, row: dict, channel: str, target: str) -> None:
    story = row["story"]
    report_path = work / story / "pipeline_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    meta = report.get("metadata") or {}
    title = meta.get("title") or story
    verdict = row.get("verdict", "?")

    if verdict == "PASS":
        pkg = row.get("package") or {}
        final = Path(pkg["final"]) if pkg.get("final") else None
        if pkg.get("ok") and final and final.exists() \
                and final.stat().st_size <= MAX_MB * 1024 * 1024:
            desc = meta.get("description", "")
            tags = ", ".join(meta.get("tags") or [])
            scorecard = row.get("scorecard")
            msg = (f"**{title}**\n\n{desc}\n\nTags: {tags}\n\n"
                  f"Verdict: PASS (scorecard {scorecard})")
            post(channel, target, msg, media=final)
            return
        post(channel, target,
            f"**{title}** — PASS but could not deliver the video (final.mp4 "
            f"missing or over {MAX_MB}MB). See {report_path}.")
        return

    # HOLD/FAIL/ERROR: the reason only, never the video (owner instruction).
    reasons = row.get("failures") or {"error": [row.get("error", "unknown")]}
    reason_txt = "; ".join(f"{k}: {v}" for k, v in reasons.items())[:1500]
    post(channel, target, f"**{title}** — {verdict}. {reason_txt}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--channel", default="discord")
    ap.add_argument("--target", required=True)
    a = ap.parse_args()
    work = Path(a.work)
    report_path = work / "batch_report.json"
    if not report_path.exists():
        print(f"no batch_report.json at {report_path}", file=sys.stderr)
        return 1
    batch = json.loads(report_path.read_text())
    delivered = _load_delivered(work)
    for row in batch.get("rows", []):
        if row["story"] in delivered:
            continue
        deliver_one(work, row, a.channel, a.target)
        _mark_delivered(work, row["story"], delivered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
