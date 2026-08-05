#!/usr/bin/env python3
"""Regenerate warmdeep variant with explicit numeric DSP args (the previous
run used un-evaluated filter expressions and garbled the audio)."""
import os
import subprocess
import sys

sys.path.insert(0, "/home/ubuntu/video_engine")
os.chdir("/home/ubuntu/video_engine")

text = open("/tmp/test_narration.txt").read().strip()
out_dir = "/home/ubuntu/video_engine/cache/voice_tests"

from src.providers.tts_provider import ChatterboxProvider

raw = os.path.join(out_dir, "_raw_warmdeep.wav")
final = os.path.join(out_dir, "variant_warmdeep.wav")

cb = ChatterboxProvider()
try:
    print("[gen] warmdeep TTS (ex=0.42 cfg=0.33)...", flush=True)
    cb.generate_voice(text, raw, exaggeration=0.42, cfg_weight=0.33)
finally:
    cb.shutdown()

# Numeric-only DSP: pitch -3% (42777/44100 = 0.97), duration-preserving,
# then warm EQ.  NO filter expressions (this ffmpeg build doesn't eval them).
dsp = (
    "asetrate=42777,aresample=44100,atempo=1.030928,"
    "highpass=f=60,equalizer=f=200:t=q:w=1:g=2,"
    "equalizer=f=3000:t=q:w=1:g=-0.5,equalizer=f=6000:t=q:w=1:g=-1.5"
)
r = subprocess.run(["ffmpeg", "-y", "-i", raw, "-af", dsp,
                    "-c:a", "pcm_s16le", final],
                   capture_output=True, text=True, timeout=180)
print(f"[gen] dsp rc={r.returncode}", flush=True)
if r.returncode == 0 and os.path.exists(final):
    os.remove(raw)
    print("WARMDEEP DONE", flush=True)
else:
    print("WARMDEEP FAILED", r.stderr[-300:], flush=True)
