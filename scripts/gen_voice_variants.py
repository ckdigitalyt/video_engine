#!/usr/bin/env python3
"""Generate 3 Chatterbox voice variants for the documentary narrator A/B test
(channel direction 2026-08-05, Set 2 workflow)."""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/video_engine")
os.chdir("/home/ubuntu/video_engine")

text = open("/tmp/test_narration.txt").read().strip()
out_dir = "/home/ubuntu/video_engine/cache/voice_tests"
os.makedirs(out_dir, exist_ok=True)

VARIANTS = [
    ("default",    0.50, 0.50),   # Chatterbox docs defaults
    ("calmer",     0.40, 0.35),   # recommended baseline (voices.yaml)
    ("expressive", 0.50, 0.28),   # slightly more expressive
]

from src.providers.tts_provider import ChatterboxProvider

cb = ChatterboxProvider()
results = []
try:
    for name, ex, cfg in VARIANTS:
        out = os.path.join(out_dir, f"variant_{name}.wav")
        print(f"[gen] {name}: ex={ex} cfg={cfg} -> {out}", flush=True)
        cb.generate_voice(text, out, exaggeration=ex, cfg_weight=cfg)
        results.append({"variant": name, "exaggeration": ex, "cfg_weight": cfg,
                        "file": out})
        print(f"[gen] {name} done", flush=True)
finally:
    cb.shutdown()

with open(os.path.join(out_dir, "variants.json"), "w") as f:
    json.dump(results, f, indent=2)
print("ALL VARIANTS DONE", flush=True)
