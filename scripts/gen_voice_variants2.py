#!/usr/bin/env python3
"""Generate 2 extra voice variants (round 2, channel direction 2026-08-05):

  variant_warmdeep.wav   — slightly warmer/deeper timbre
    Chatterbox (ex=0.42, cfg=0.33) + subtle DSP: pitch -3% (≈-0.5 st,
    duration-preserving), warm EQ (low-mid lift, high rolloff).
  variant_slowpremium.wav — slightly slower, more deliberate/premium pacing
    Heavy text-level pause density (space after facts) + lower cfg_weight
    (docs: lower cfg steadies pacing) + 3% tempo slow (pitch-preserving).

No celebrity cloning; built-in voice; clean speech.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/ubuntu/video_engine")
os.chdir("/home/ubuntu/video_engine")

text = open("/tmp/test_narration.txt").read().strip()
out_dir = "/home/ubuntu/video_engine/cache/voice_tests"
os.makedirs(out_dir, exist_ok=True)

from src.providers.tts_provider import ChatterboxProvider
from src.utils.tts_normalize import apply_pacing_pauses

cb = ChatterboxProvider()
results = []
try:
    # ── warmdeep: generate then DSP ───────────────────────────────────
    raw_warm = os.path.join(out_dir, "_raw_warmdeep.wav")
    final_warm = os.path.join(out_dir, "variant_warmdeep.wav")
    print("[gen] warmdeep: ex=0.42 cfg=0.33 -> raw", flush=True)
    cb.generate_voice(text, raw_warm, exaggeration=0.42, cfg_weight=0.33)
    # pitch -3% preserving duration + warm EQ (subtle, not muddy)
    dsp = (
        "asetrate=44100*0.97,aresample=44100,atempo=1/0.97,"
        "highpass=f=60,equalizer=f=200:t=q:w=1:g=2,"
        "equalizer=f=3000:t=q:w=1:g=-0.5,equalizer=f=6000:t=q:w=1:g=-1.5"
    )
    r = subprocess.run(["ffmpeg", "-y", "-i", raw_warm, "-af", dsp,
                        "-c:a", "pcm_s16le", final_warm],
                       capture_output=True, text=True, timeout=180)
    print(f"[gen] warmdeep dsp rc={r.returncode}", flush=True)
    results.append({"variant": "warmdeep", "exaggeration": 0.42,
                    "cfg_weight": 0.33, "dsp": "pitch-3%+warm-eq",
                    "file": final_warm})

    # ── slowpremium: heavy pauses + lower cfg + 3% slower ─────────────
    slow_text = apply_pacing_pauses(text, "heavy")
    raw_slow = os.path.join(out_dir, "_raw_slowpremium.wav")
    final_slow = os.path.join(out_dir, "variant_slowpremium.wav")
    print("[gen] slowpremium: ex=0.38 cfg=0.30 heavy-pauses -> raw", flush=True)
    cb.generate_voice(slow_text, raw_slow, exaggeration=0.38, cfg_weight=0.30)
    # 3% slower, pitch preserved (atempo keeps pitch)
    r = subprocess.run(["ffmpeg", "-y", "-i", raw_slow, "-af", "atempo=0.97",
                        "-c:a", "pcm_s16le", final_slow],
                       capture_output=True, text=True, timeout=180)
    print(f"[gen] slowpremium atempo rc={r.returncode}", flush=True)
    results.append({"variant": "slowpremium", "exaggeration": 0.38,
                    "cfg_weight": 0.30, "pauses": "heavy", "tempo": 0.97,
                    "file": final_slow})
finally:
    cb.shutdown()

# tidy raw intermediates
for raw in ("_raw_warmdeep.wav", "_raw_slowpremium.wav"):
    p = os.path.join(out_dir, raw)
    if os.path.exists(p):
        os.remove(p)

with open(os.path.join(out_dir, "variants2.json"), "w") as f:
    json.dump(results, f, indent=2)
print("ROUND2 DONE", flush=True)
