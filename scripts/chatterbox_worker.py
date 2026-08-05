#!/usr/bin/env python3
"""
chatterbox_worker.py — Persistent Chatterbox TTS worker (isolated venv-cb).

Loads the Chatterbox model ONCE and keeps it loaded (the CPU equivalent of
KEEP_MODEL_LOADED), then serves JSON-lines requests on stdin/stdout:

  REQUEST  (one line):  {"id": 0, "text": "...", "out": "/abs/path.wav",
                         "exaggeration": 0.5, "cfg_weight": 0.5,
                         "temperature": 0.8, "voice": "resemble",
                         "audio_prompt": "/abs/ref.wav"}   # optional clone ref
  RESPONSE (one line):  {"id": 0, "ok": true, "duration_s": 8.6,
                         "sr": 24000, "elapsed_s": 110.0}
                        or {"id": 0, "ok": false, "error": "..."}

Output audio is 24 kHz mono float WAV (Chatterbox native), watermarked
with PerTh (imperceptible traceability watermark, per expert doc §1.3).

Why a separate venv: chatterbox-tts pins numpy 1.26.4 / torch 2.6.0 while
the main pipeline venv runs numpy 2.5.1 — isolating avoids clobbering the
render stack.
"""

import json
import os
import sys
import time

import torch

MODEL_DEVICE = os.environ.get("CHATTERBOX_DEVICE", "cpu")


def main():
    from chatterbox import ChatterboxTTS

    sys.stderr.write("[chatterbox-worker] loading model (first load downloads weights)...\n")
    sys.stderr.flush()
    t0 = time.time()
    model = ChatterboxTTS.from_pretrained(MODEL_DEVICE)
    sys.stderr.write(f"[chatterbox-worker] model ready in {time.time()-t0:.1f}s\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            rid = req.get("id", 0)
            text = req.get("text", "")
            out = req.get("out", "")
            if not text or not out:
                _resp(rid, ok=False, error="missing text/out")
                continue
            t1 = time.time()
            audio = model.generate(
                text,
                audio_prompt_path=req.get("audio_prompt") or None,
                exaggeration=float(req.get("exaggeration", 0.5)),
                cfg_weight=float(req.get("cfg_weight", 0.5)),
                temperature=float(req.get("temperature", 0.8)),
            )
            elapsed = time.time() - t1
            # audio: torch tensor (1, N) at 24 kHz
            arr = audio.squeeze(0).cpu().numpy()
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            import soundfile as sf
            sf.write(out, arr, 24000)
            dur = len(arr) / 24000
            _resp(rid, ok=True, duration_s=round(dur, 3), sr=24000,
                  elapsed_s=round(elapsed, 2))
        except Exception as e:  # noqa: BLE001
            _resp(req.get("id", -1), ok=False, error=str(e)[:300])


def _resp(rid, ok, **kw):
    payload = {"id": rid, "ok": ok, **kw}
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
