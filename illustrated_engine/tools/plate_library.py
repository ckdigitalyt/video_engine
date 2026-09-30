#!/usr/bin/env python3
"""tools/plate_library.py — WP8/DESIGN §6.2 idle-time plate library cron.

"A `tools/plate_library.py` cron job runs only when no render is active
(`nice 19`, one job). It generates brand-style plates for the topic queue's
upcoming subjects, about 70 per day max (RESEARCH §5.3)."

Scope of THIS WP (flagged, not silent): this builds the library — real
plates for real subjects, generated through the same production chain
(`engine.v15_plates.generate_plate`, so archive/cloudflare/gemini/sdcpp_local
/pollinations all apply, in the same order and with the same licence
provenance a live render would get) and recorded with subject-tag metadata
in `build/plate_library/index.json`. DESIGN §6.1 tier 1 ("plate library
match — idle-built library; tag + prompt-embedding-free text match on
subject tags") — i.e. actually CONSULTING this library from a live render's
shot compiler instead of generating fresh — is explicitly marked
"[later WP]" in DESIGN itself and is not wired here.

No real "topic queue" exists yet (WP11, the topic engine, is not built) —
subjects default to the claim text of the existing bench topic packs
(`bench/quality/topics/*/facts.json`), the closest real stand-in available
today; `--subjects-file` overrides with one subject per line for when a
real queue exists.

Usage:
  venv/bin/python3 -m tools.plate_library --max 70 [--dry-run]
  venv/bin/python3 -m tools.plate_library --subjects-file subjects.txt
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent       # illustrated_engine/
REPO = ROOT.parent                                    # video_engine/
for _p in (REPO, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

STATE_PATH = ROOT / "build" / "plate_library_state.json"
INDEX_PATH = ROOT / "build" / "plate_library" / "index.json"
DEFAULT_BIBLE_STORY = ROOT / "stories" / "tunguska_1908"
DEFAULT_TOPICS_DIR = REPO / "bench" / "quality" / "topics"

_STOPWORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "and", "or",
             "is", "was", "were", "are", "with", "for", "by", "about",
             "that", "this", "as", "its", "it", "which", "than", "from"}


def _render_active() -> bool:
    """DESIGN §6.2: "runs only when no render is active". No lock-file
    protocol exists yet (WP12's batch runner would be the natural owner of
    one) — check the process table directly instead of inventing a
    convention nothing else writes to yet."""
    try:
        out = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                             text=True, timeout=10)
    except Exception:
        return False  # can't tell -> don't block the job on an infra hiccup
    return any(("v15_pipeline" in line or "v16_batch" in line)
              and "plate_library" not in line
              for line in out.stdout.splitlines())


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"date": "", "count": 0}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


def subjects_from_topic_packs(topics_dir: Path) -> list:
    """One subject string per claim (bench/quality/topics/*/facts.json) —
    the closest real "upcoming subjects" source available before WP11."""
    subjects = []
    for facts_path in sorted(topics_dir.glob("*/facts.json")):
        try:
            data = json.loads(facts_path.read_text())
        except Exception:
            continue
        for claim in data.get("claims") or []:
            text = claim.get("claim")
            if text:
                subjects.append(text)
    return subjects


def tags_for(subject: str) -> list:
    words = re.findall(r"[a-z0-9]+", subject.lower())
    return sorted({w for w in words if len(w) > 3 and w not in _STOPWORDS})


def build_library(subjects: list, *, bible_story: Path, out_index: Path,
                  max_new: int, dry_run: bool = False) -> dict:
    from engine.v15_plates import PROVIDER_ORDER, generate_plate
    from engine.v15_style import image_prompt, load_style

    bible = load_style(bible_story)
    index = []
    if out_index.exists():
        try:
            index = json.loads(out_index.read_text())
        except Exception:
            index = []
    seen_prompts = {row["prompt"] for row in index}

    generated, skipped, failed = 0, 0, 0
    for subject in subjects:
        if generated >= max_new:
            break
        prompt = image_prompt(bible, subject, "centered")
        if prompt in seen_prompts:
            skipped += 1
            continue
        if dry_run:
            generated += 1
            continue
        from src.providers.image_gen import deterministic_seed
        res = generate_plate(prompt, deterministic_seed(prompt), providers=PROVIDER_ORDER)
        if not res.get("ok"):
            failed += 1
            continue
        index.append({"subject": subject, "tags": tags_for(subject),
                      "prompt": prompt, "path": res["path"],
                      "provider": res["provider"], "key": res["key"],
                      "added": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        seen_prompts.add(prompt)
        generated += 1

    if not dry_run and generated:
        out_index.parent.mkdir(parents=True, exist_ok=True)
        out_index.write_text(json.dumps(index, indent=1))
    return {"generated": generated, "skipped_existing": skipped,
           "failed": failed, "library_size": len(index)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=70,
                    help="RESEARCH §5.3 daily cap")
    ap.add_argument("--topics-dir", type=Path, default=DEFAULT_TOPICS_DIR)
    ap.add_argument("--subjects-file", type=Path, default=None,
                    help="one subject per line, overrides --topics-dir")
    ap.add_argument("--bible-story", type=Path, default=DEFAULT_BIBLE_STORY)
    ap.add_argument("--out-index", type=Path, default=INDEX_PATH)
    ap.add_argument("--force", action="store_true",
                    help="skip the render-active and daily-cap checks (testing only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute subjects/prompts, generate nothing")
    args = ap.parse_args()

    if not args.force and _render_active():
        print(json.dumps({"skipped": "render_active"}))
        return 0

    today = time.strftime("%Y-%m-%d")
    state = _load_state()
    if state.get("date") != today:
        state = {"date": today, "count": 0}
    remaining = max(0, args.max - state["count"]) if not args.force else args.max
    if remaining <= 0:
        print(json.dumps({"skipped": "daily_cap_reached", "count": state["count"]}))
        return 0

    if args.subjects_file:
        subjects = [ln.strip() for ln in args.subjects_file.read_text().splitlines()
                   if ln.strip()]
    else:
        subjects = subjects_from_topic_packs(args.topics_dir)

    if not args.dry_run:
        os.nice(19)  # DESIGN §6.2: "nice 19, one job" — never competes for CPU

    result = build_library(subjects, bible_story=args.bible_story,
                           out_index=args.out_index, max_new=remaining,
                           dry_run=args.dry_run)
    if not args.dry_run:
        state["count"] += result["generated"]
        _save_state(state)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
