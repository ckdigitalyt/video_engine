#!/usr/bin/env python3
"""Regenerate a story's audio_bed_plan.json with event-synced SFX.

The V8 living-diagram plan declares explicit visual events per shot
(reveal / isolate / flow / fill_state / consequence / highlight /
number_pop) with in-shot times.  This script maps those events onto the
SFX vocabulary the milestone brief names:

    reveal      -> sfx_whoosh   (the draw-on stroke)
    number_pop  -> sfx_tick     (big on-canvas numbers)
    consequence -> sfx_pulse    (stakes landing)

Beds stay silent (bed_files unchanged — the always-on ambient bed is
retired); the SFX track is the only non-narration layer.

`at` is ABSOLUTE seconds from video start (audio_mix._concat_sfx delays
each entry by `at` ms from track start).  A minimum gap keeps the track
from cluttering; later of two too-close events is dropped.

Usage:  python3 make_sfx_bed.py --story <story_id> [--gap 1.2]
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVENT_MAP = {"reveal": "whoosh", "number_pop": "tick", "consequence": "pulse"}


def build_plan(story_id: str, gap: float) -> dict:
    story_dir = ROOT / "stories" / story_id
    plan = json.loads(
        (ROOT / "build" / f"edit_plan_{story_id}.json").read_text())
    bed_path = story_dir / "audio_bed_plan.json"
    bed = (json.loads(bed_path.read_text())
           if bed_path.exists() else {})
    audio_dir = story_dir / "audio"

    sfx = []
    t0 = 0.0
    for s in plan.get("shots", []):
        dur = float(s.get("duration_s") or 0)
        for e in s.get("events", []):
            kind = EVENT_MAP.get(str(e.get("kind", "")).lower())
            if not kind:
                continue
            sfx.append({"at": round(t0 + float(e.get("t") or 0), 3),
                        "kind": kind})
        t0 += dur

    sfx.sort(key=lambda x: x["at"])
    out, last_by_kind = [], {}
    for x in sfx:
        f = audio_dir / f"sfx_{x['kind']}.wav"
        if not f.exists():
            print(f"[sfx] missing {f.name} for {story_id} — skipped")
            continue
        last = last_by_kind.get(x["kind"])
        if last is not None and x["at"] - last < gap:
            continue  # same-kind clutter; distinct kinds always layer
        out.append({"file": str(f), "at": x["at"], "kind": x["kind"]})
        last_by_kind[x["kind"]] = x["at"]

    new = {"bed_files": bed.get("bed_files")
           or [None] * len(plan.get("shots", [])),
           "sfx": out,
           "bed_crossfade_ms": bed.get("bed_crossfade_ms", 600)}
    bed_path.write_text(json.dumps(new, indent=2) + "\n")
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True)
    ap.add_argument("--gap", type=float, default=1.2)
    a = ap.parse_args()
    plan = build_plan(a.story, a.gap)
    kinds = {}
    for x in plan["sfx"]:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    print(f"{a.story}: {len(plan['sfx'])} sfx {kinds} "
          f"(bed_files silent: {all(b is None for b in plan['bed_files'])})")
    for x in plan["sfx"]:
        print(f"   {x['at']:7.3f}s  {x['kind']}")


if __name__ == "__main__":
    main()
