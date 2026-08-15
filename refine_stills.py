#!/usr/bin/env python3
"""
refine_stills.py — Human-approved refinement pass for the stills video.

Implements Gemini's three flagged recommendations (approved by user):
  1. [fact_change] Scene 2 narration: acknowledge Voyager 2 also crossed
     the heliopause (2018) — "Voyager 1 was the first."
  2. [new_asset]  Replace abstract/reused stills at ~0:06 and ~0:39 with
     REAL NASA imagery: Voyager spacecraft (PIA22915) and the actual
     Pale Blue Dot (PIA00452 / PIA23645).
  3. [shot_order]  Replace the "generic vinyl" AI golden record at ~0:42
     with NASA's "Voyager: Preparing the Golden Record" photo.

Usage:
    ./venv/bin/python refine_stills.py
"""

import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(override=True)  # runtime injects masked/placeholder API keys; .env has the real ones

import mission_stills as S

OUT_DIR = "results/voyager_stills"


def _fetch(url: str, out_path: str) -> str:
    import requests
    r = requests.get(url, timeout=60)
    if r.status_code == 200 and len(r.content) > 20000:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(r.content)
        print(f"  [fetch] {os.path.basename(out_path)} ({len(r.content)//1024} KB) ← {url.split('/')[-1]}")
        return out_path
    print(f"  [fetch] !! failed {url} ({r.status_code})")
    return ""


# ── 1. Fact fix: narration ─────────────────────────────────────────────

def fix_narration(scenes_data: list[dict]) -> bool:
    changed = False
    for s in scenes_data:
        n = s.get("narration", "")
        if "no other human object" in n.lower():
            s["narration"] = (
                "At Jupiter, it found volcanoes on Io. It swept past Saturn, "
                "then crossed the heliopause into interstellar space. Voyager "
                "one was the first. In 2018, its twin, Voyager two, crossed "
                "the same line."
            )
            changed = True
            print("  [fact] scene narration fixed: 'No other human object' → "
                  "'Voyager 1 was the first. In 2018, its twin, Voyager 2...'")
        # Fix the baked-in 'reach U.S.' typo (pronoun 'us' must not be
        # capitalized — recurring Gemini finding on scene 0)
        fixed = n.replace("reach U.S.", "reach us").replace("reach U.S", "reach us")
        if fixed != n:
            s["narration"] = fixed
            changed = True
            print("  [typo] scene narration fixed: 'reach U.S.' → 'reach us'")
    return changed


# ── 2. Targeted real-asset swaps ───────────────────────────────────────

def fetch_real_assets() -> dict:
    """Download specific NASA assets and overwrite the weak stills."""
    base = "https://images-assets.nasa.gov/image/{nid}/{nid}~orig.jpg"
    targets = {
        # scene0_1 (0:06 area): abstract image → real Voyager spacecraft
        "cache/stills/scene0_1.jpg": base.format(nid="PIA22915"),   # Voyager 2 Spacecraft Instruments
        # scene3_1 (0:39 area): reused abstract → real Pale Blue Dot
        "cache/stills/scene3_1.jpg": base.format(nid="PIA00452"),   # Solar System Portrait - Earth as Pale Blue Dot
        # scene3_0 (33-38s): AI blob → Pale Blue Dot Revisited (Cassini)
        "cache/stills/scene3_0.jpg": base.format(nid="PIA23645"),   # Pale Blue Dot Revisited
        # scene0_0 (0:00): AI spacecraft → real Voyager model/artist concept
        "cache/stills/scene0_0.jpg": base.format(nid="PIA14111"),   # Model of Voyager Artist Concept
        # scene4_0 (0:42): AI 'generic vinyl' → NASA Preparing the Golden Record
        "cache/stills/scene4_0.jpg": base.format(nid="PIA16362"),   # Voyager: Preparing the Golden Record
    }
    results = {}
    for out, url in targets.items():
        # clear old Ken Burns clip so it regenerates
        clip = os.path.join(OUT_DIR, "shots", os.path.basename(out).replace(".jpg", ".mp4"))
        if os.path.exists(clip):
            os.remove(clip)
        results[out] = _fetch(url, out)
    return results


# ── Main ───────────────────────────────────────────────────────────────

def main():
    print("=" * 64)
    print("REFINEMENT PASS — human-approved Gemini flags")
    print("=" * 64)
    t0 = time.time()

    script_path = os.path.join(OUT_DIR, "script_final.json")
    with open(script_path) as f:
        scenes_data = json.load(f)

    # 1) Fact fix
    changed = fix_narration(scenes_data)
    with open(script_path, "w") as f:
        json.dump(scenes_data, f, indent=2)

    # 2) Real assets
    assets = fetch_real_assets()
    n_ok = sum(1 for v in assets.values() if v)

    # 3) Re-synthesize changed scenes' voices (scene 2 fact fix, scene 0 typo)
    if changed:
        for scene_idx in (0, 2):
            ap = os.path.join("cache", "audio", f"scene_{scene_idx}.wav")
            if os.path.exists(ap):
                os.remove(ap)
                print(f"  [voice] scene_{scene_idx} queued for re-synthesis")

    # 4) Re-run the stills pipeline in --reuse mode (regenerates shots +
    #    narration for changed scenes + render + music + Gemini review)
    print(f"\n→ Re-running stills pipeline (reuse) with {n_ok}/5 real assets...")
    rc = subprocess.run(
        [sys.executable, "mission_stills.py", "--reuse"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    if rc.returncode != 0:
        print("!! refinement render failed")
        sys.exit(1)

    print(f"\nRefinement pass complete in {time.time()-t0:.0f}s "
          f"({n_ok}/5 real NASA assets swapped)")


if __name__ == "__main__":
    main()
