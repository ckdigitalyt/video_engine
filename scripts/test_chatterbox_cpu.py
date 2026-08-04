#!/usr/bin/env python3
"""Chatterbox CPU feasibility test (isolated venv-cb)."""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
print(f"torch {torch.__version__} | cuda available: {torch.cuda.is_available()}")
print(f"threads: {torch.get_num_threads()}")

from chatterbox import ChatterboxTTS

t0 = time.time()
print("Loading Chatterbox model (downloads weights on first run)...")
model = ChatterboxTTS.from_pretrained("cpu")
print(f"Model loaded in {time.time()-t0:.1f}s")

text = ("The signal was spinning at breakneck speed [chuckle] exactly thirty "
        "rotations every second. This discovery rewrote our understanding of "
        "the universe.")
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "test_chatterbox.wav")
os.makedirs(os.path.dirname(out), exist_ok=True)

t1 = time.time()
print("Generating 2-sentence sample (exaggeration=0.5, cfg_weight=0.5)...")
audio = model.generate(
    text,
    exaggeration=0.5,
    cfg_weight=0.5,
)
dur = time.time() - t1

# audio is a torch tensor (1, N) at 24kHz
import soundfile as sf
import numpy as np
arr = audio.squeeze(0).numpy()
sf.write(out, arr, 24000)
print(f"Saved {out} ({os.path.getsize(out)//1024} KB)")
rtf = dur / (len(arr) / 24000)
print(f"Generated {len(arr)/24000:.1f}s audio in {dur:.1f}s — RTF = {rtf:.2f}x (1.0 = real-time)")
