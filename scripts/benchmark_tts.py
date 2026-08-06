#!/usr/bin/env python3
"""
benchmark_tts.py — Benchmark TTS providers on identical scripts.

The guidance says: optimize for documentary narration QUALITY, not the
deepest voice.  This benchmark:

  1. Synthesizes an identical script with each provider/voice
  2. Records objective metrics: latency, CPU cost, output duration,
     licensing, offline capability
  3. Sends the audio to Gemini (which can LISTEN) for a blind comparison
     of natural prosody, authority, warmth, and documentary fit

Usage:
    ./venv/bin/python scripts/benchmark_tts.py
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

SCRIPT = (
    "The Sun contains ninety-nine point eight six percent of the mass "
    "of the Solar System. Its core burns at fifteen million degrees "
    "Celsius. Every second, it fuses six hundred million tons of "
    "hydrogen into helium. And yet, it is only an ordinary star."
)

CANDIDATES = [
    ("kokoro", "bm_george"),
    ("edge", "en-US-ChristopherNeural"),
    ("edge", "en-US-GuyNeural"),
    ("edge", "en-GB-RyanNeural"),
    ("edge", "en-US-AndrewNeural"),
]


def _duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _synthesize(provider: str, voice: str, out: str) -> dict:
    from src.providers.tts_provider import KokoroProvider, EdgeTTSProvider
    t0 = time.time()
    if provider == "kokoro":
        KokoroProvider().generate_voice(SCRIPT, out)
        engine = "local-onnx"
    else:
        EdgeTTSProvider(voice=voice).generate_voice(SCRIPT, out)
        engine = "cloud-edge"
    elapsed = time.time() - t0
    return {
        "provider": provider, "voice": voice,
        "latency_s": round(elapsed, 1),
        "duration_s": round(_duration(out), 1),
        "engine": engine,
        "path": out,
        "license": "MIT (kokoro)" if provider == "kokoro" else "proprietary-free (edge)",
        "offline": provider == "kokoro",
        "cpu_cost": "high (local)" if provider == "kokoro" else "~zero (cloud)",
    }


def _gemini_listen(audio_paths: dict) -> dict:
    """Ask Gemini to listen to each narration and rank them."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    labels = list(audio_paths.keys())
    prompt = (
        "You are a documentary voice director. You will hear "
        f"{len(labels)} narrations of the SAME script, labelled "
        f"{', '.join(labels)}. Listen carefully to each. Rank them for "
        "documentary narration quality: natural prosody, authority, warmth, "
        "consistency, and listening comfort. Do NOT prefer the deepest voice — "
        "prefer the most natural and engaging narrator.\n"
        "Respond STRICT JSON:\n"
        "{\n"
        '  "ranked": ["<best label>", "<2nd>", ...],\n'
        '  "scores": {"<label>": {"naturalness": 0-10, "authority": 0-10, '
        '"warmth": 0-10, "overall": 0-10}},\n'
        '  "winner": "<label>",\n'
        '  "justification": "<2-3 sentences>"\n'
        "}"
    )
    parts = [prompt]
    for label in labels:
        p = audio_paths[label]
        mime = "audio/wav" if p.endswith(".wav") else "audio/mpeg"
        parts.append(types.Part.from_bytes(
            data=open(p, "rb").read(), mime_type=mime))
        parts.append(types.Part.from_text(text=f"<audio label={label}>"))
    resp = client.models.generate_content(
        model="gemini-2.5-flash", contents=parts,
        config=types.GenerateContentConfig(
            temperature=0.1, response_mime_type="application/json"),
    )
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def main():
    os.makedirs("cache/benchmarks", exist_ok=True)
    os.makedirs("cache/tts_bench", exist_ok=True)
    results = {}
    audio_paths = {}
    for provider, voice in CANDIDATES:
        out = f"cache/tts_bench/{provider}_{voice.split('-')[-2] if '-' in voice else voice}.mp3"
        if not out.endswith(".mp3"):
            out = out + ".mp3"
        try:
            meta = _synthesize(provider, voice, out)
        except Exception as e:
            meta = {"provider": provider, "voice": voice, "error": str(e)[:120]}
        results[f"{provider}/{voice}"] = meta
        if "error" not in meta and os.path.exists(out):
            audio_paths[f"{provider}:{voice}"] = out
        print(f"  {provider:8s} {voice:26s} latency={meta.get('latency_s','?')}s "
              f"dur={meta.get('duration_s','?')}s")

    print("\n→ Gemini listening comparison...")
    try:
        listen = _gemini_listen(audio_paths)
    except Exception as e:
        listen = {"error": str(e)[:200]}
        print(f"  !! listening failed: {e}")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script": SCRIPT,
        "candidates": results,
        "gemini_listening": listen,
    }
    with open("cache/benchmarks/tts_benchmark.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved → cache/benchmarks/tts_benchmark.json")
    if "winner" in listen:
        print(f"Gemini winner: {listen['winner']}")
        print(f"Justification: {listen.get('justification','')[:200]}")


if __name__ == "__main__":
    main()
