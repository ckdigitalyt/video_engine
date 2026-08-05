#!/usr/bin/env python3
"""Round 3: voices inspired by Kurzgesagt + Astrum narrator styles.

No celebrity cloning — we approximate CHARACTERISTICS:
  kurzgesagt-like : warm, friendly, energetic British narrator
                    -> Chatterbox clone of SYNTHETIC edge-tts
                       en-GB-ThomasNeural reference (clean speech,
                       English-matched, not a real person)
  astrum-like     : calm, measured, clear documentary narrator
                    -> Chatterbox clone of SYNTHETIC edge-tts
                       en-GB-RyanNeural reference
  + two DSP variants of the built-in voice (fast, no extra TTS):
      energetic (Kurzgesagt energy) and measured (Astrum calm)
"""
import asyncio
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/ubuntu/video_engine")
os.chdir("/home/ubuntu/video_engine")

text = open("/tmp/test_narration.txt").read().strip()
out_dir = "/home/ubuntu/video_engine/cache/voice_tests"
os.makedirs(out_dir, exist_ok=True)
ref_dir = os.path.join(out_dir, "refs")
os.makedirs(ref_dir, exist_ok=True)

from src.providers.tts_provider import ChatterboxProvider


def edge_ref(voice: str, out_path: str) -> bool:
    """Generate a synthetic British-English reference clip via edge-tts."""
    import edge_tts
    async def _run():
        c = edge_tts.Communicate(text, voice, rate="-5%")
        await c.save(out_path)
    try:
        asyncio.run(_run())
        return os.path.exists(out_path) and os.path.getsize(out_path) > 20000
    except Exception as e:
        print(f"  [ref] {voice} failed: {str(e)[:120]}")
        return False


def dsp_shift(src: str, dst: str, tempo: float, pitch_ratio: float,
              eq: str) -> bool:
    """Pitch+tempo shift preserving duration, plus EQ.  Uses ONLY explicit
    numeric args (this ffmpeg build does not evaluate filter expressions)."""
    sr_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate", "-of", "csv=p=0", src],
        capture_output=True, text=True)
    sr = int(sr_probe.stdout.strip() or 24000)
    asetrate = int(round(sr * pitch_ratio))
    atempo = round(1.0 / pitch_ratio * tempo, 6)
    af = f"asetrate={asetrate},aresample={sr},atempo={atempo},{eq}"
    r = subprocess.run(["ffmpeg", "-y", "-i", src, "-af", af,
                        "-c:a", "pcm_s16le", dst],
                       capture_output=True, text=True, timeout=180)
    return r.returncode == 0 and os.path.exists(dst)


results = []

# ── 1) synthetic references (fast) ────────────────────────────────────
ref_thomas = os.path.join(ref_dir, "ref_thomas.wav")   # warm/friendly
ref_ryan = os.path.join(ref_dir, "ref_ryan.wav")       # calm/natural
print("[refs] generating edge-tts references...", flush=True)
ok_t = edge_ref("en-GB-ThomasNeural", ref_thomas)
ok_r = edge_ref("en-GB-RyanNeural", ref_ryan)
print(f"  thomas={ok_t} ryan={ok_r}", flush=True)

# ── 2) Chatterbox clones from synthetic refs (SLOW, ~7 min each) ─────
cb = ChatterboxProvider()
try:
    if ok_t:
        out = os.path.join(out_dir, "variant_kurzgesagt_like.wav")
        print("[clone] kurzgesagt_like: Thomas ref, ex=0.50 cfg=0.32", flush=True)
        cb.generate_voice(text, out, exaggeration=0.50, cfg_weight=0.32,
                          audio_prompt=ref_thomas)
        results.append({"variant": "kurzgesagt_like", "engine": "chatterbox",
                        "reference": "edge-tts en-GB-ThomasNeural (synthetic)",
                        "exaggeration": 0.50, "cfg_weight": 0.32, "file": out})
        print("  [clone] kurzgesagt_like done", flush=True)
    if ok_r:
        out = os.path.join(out_dir, "variant_astrum_like.wav")
        print("[clone] astrum_like: Ryan ref, ex=0.38 cfg=0.30", flush=True)
        cb.generate_voice(text, out, exaggeration=0.38, cfg_weight=0.30,
                          audio_prompt=ref_ryan)
        results.append({"variant": "astrum_like", "engine": "chatterbox",
                        "reference": "edge-tts en-GB-RyanNeural (synthetic)",
                        "exaggeration": 0.38, "cfg_weight": 0.30, "file": out})
        print("  [clone] astrum_like done", flush=True)
finally:
    cb.shutdown()

# ── 3) DSP variants of built-in voice (fast, reuse existing audio) ────
warm_eq = ("highpass=f=70,equalizer=f=250:t=q:w=1:g=2.5,"
           "equalizer=f=3500:t=q:w=1:g=1.5")
clean_eq = ("highpass=f=60,equalizer=f=200:t=q:w=1:g=1.5,"
            "equalizer=f=5000:t=q:w=1:g=-1")

base_energy = os.path.join(out_dir, "variant_default.wav")   # ex .5 cfg .5
base_measured = os.path.join(out_dir, "variant_calmer.wav")  # ex .4 cfg .35

d1 = os.path.join(out_dir, "variant_energetic_dsp.wav")   # Kurzgesagt-ish energy
d2 = os.path.join(out_dir, "variant_measured_dsp.wav")    # Astrum-ish calm
if os.path.exists(base_energy) and dsp_shift(base_energy, d1, 1.06, 1.03, warm_eq):
    results.append({"variant": "energetic_dsp", "engine": "builtin+dsp",
                    "base": "default", "tempo": 1.06, "pitch": "+3%",
                    "eq": "warm+presence", "file": d1})
    print("[dsp] energetic done", flush=True)
if os.path.exists(base_measured) and dsp_shift(base_measured, d2, 0.96, 0.98, clean_eq):
    results.append({"variant": "measured_dsp", "engine": "builtin+dsp",
                    "base": "calmer", "tempo": 0.96, "pitch": "-2%",
                    "eq": "clean", "file": d2})
    print("[dsp] measured done", flush=True)

with open(os.path.join(out_dir, "variants3.json"), "w") as f:
    json.dump(results, f, indent=2)
print("ROUND3 DONE", flush=True)
