#!/usr/bin/env python3
"""
benchmark_image_gen.py — Benchmark AI image generation providers.

Records realism/speed/cost metrics into cache/benchmarks/image_gen.json.
Run before selecting provider defaults (mission: benchmark before defaults).

Usage:
    ./venv/bin/python scripts/benchmark_image_gen.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

PROMPTS = [
    "Photorealistic documentary image of the Voyager 1 spacecraft, large dish antenna, deep interstellar space, cinematic NASA style",
    "Close-up of the Voyager Golden Record, gold-plated copper phonograph record, floating in space, cinematic lighting",
]


def main():
    from src.providers.image_gen import ImageGenFactory

    os.makedirs("cache/benchmarks", exist_ok=True)
    out_path = "cache/benchmarks/image_gen.json"
    results = {}
    factory = ImageGenFactory()

    for name in ("nvidia_nim", "pollinations", "siliconflow", "hf_serverless"):
        prov = factory.get(name)
        results[name] = {"available": prov.is_available()}
        if not prov.is_available():
            results[name]["note"] = "no credentials"
            continue
        for i, prompt in enumerate(PROMPTS):
            t0 = time.time()
            try:
                out = prov.generate(
                    prompt,
                    f"cache/generated/bench_{name}_{i}.png",
                    width=1024, height=576, seed=42,
                )
                dt = time.time() - t0
                sz = os.path.getsize(out) / 1024
                results[name][f"prompt_{i}"] = {
                    "ok": True, "elapsed_s": round(dt, 1), "size_kb": round(sz, 1),
                }
            except Exception as e:
                results[name][f"prompt_{i}"] = {
                    "ok": False, "error": str(e)[:150],
                }

    with open(out_path, "w") as f:
        json.dump({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "prompts": PROMPTS, "results": results}, f, indent=2)
    print(json.dumps(results, indent=2))
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
