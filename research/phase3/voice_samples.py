"""Phase 3 deliverable C: render one on-channel script with Fish s2.1-pro-free (comparison only,
NOT for publication) and Kokoro am_michael fp32 (local), then loudness-normalise both to -14 LUFS.

  venv/bin/python research/phase3/voice_samples.py [fish|kokoro|norm|all]

The Fish key is read from the repo .env via engine.voice.fish._load_env_keys and is never printed."""
import base64, json, os, re, subprocess, sys, time, urllib.request, wave
from pathlib import Path
import numpy as np

REPO = Path("/home/ubuntu/video_engine")
OUT = Path.home() / "phase3_out" / "voice"; OUT.mkdir(parents=True, exist_ok=True)
MODELS = Path.home() / "models" / "kokoro"
SCRIPT = (
    "That pigeon is a dinosaur. Not related to one. It is one. "
    "Sixty-six million years ago, a rock ten kilometres wide slammed into Mexico, and the age of giants ended. "
    "Tyrannosaurus, gone. Triceratops, gone. "
    "But a few small, feathered dinosaurs made it through. They were tiny, and they could live on seeds. "
    "Their descendants are outside your window right now. "
    "So the next time a pigeon stares at you... remember what it is."
)
FISH_VOICE = "0327fdb5da9e4fd782899a8058c8ae2b"  # "Narrator" (community voice; see RESEARCH 3.2)


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", str(p)]).strip())


def fish():
    sys.path.insert(0, str(REPO / "illustrated_engine"))
    from engine.voice.fish import _load_env_keys
    _load_env_keys()
    payload = {"text": SCRIPT, "reference_id": FISH_VOICE, "temperature": 0.7, "top_p": 0.9,
               "prosody": {"speed": 1.0, "volume": 0, "normalize_loudness": True},
               "format": "mp3", "sample_rate": 44100, "mp3_bitrate": 128, "latency": "normal"}
    req = urllib.request.Request(
        "https://api.fish.audio/v1/tts/stream/with-timestamp", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + os.environ["FISH_API_KEY"], "Content-Type": "application/json",
                 "model": "s2.1-pro-free", "User-Agent": "Mozilla/5.0"})
    t = time.time(); audio = b""; aligns = {}; offs = {}
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            for line in r:
                line = line.decode().strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                if ev.get("audio_base64"):
                    audio += base64.b64decode(ev["audio_base64"])
                if ev.get("alignment"):
                    k = ev.get("chunk_seq", 0); aligns[k] = ev["alignment"]; offs[k] = ev.get("chunk_audio_offset_sec", 0)
    except urllib.error.HTTPError as e:
        # body may echo request metadata; print status only
        sys.exit(f"Fish HTTP {e.code}")
    wall = time.time() - t
    (OUT / "fish_raw.mp3").write_bytes(audio)
    segs = [dict(s, start=round(s["start"] + offs[k], 3), end=round(s["end"] + offs[k], 3))
            for k in sorted(aligns) for s in aligns[k]["segments"]]
    (OUT / "fish_timestamps.json").write_text(json.dumps(segs, indent=1))
    d = dur(OUT / "fish_raw.mp3")
    return {"engine": "fish s2.1-pro-free", "wall_s": round(wall, 2), "audio_s": round(d, 2),
            "rtf": round(wall / d, 3), "n_word_segments": len(segs)}


def kokoro():
    from kokoro_onnx import Kokoro
    t = time.time(); m = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin")); load = time.time() - t
    t = time.time(); x, sr = m.create(SCRIPT, voice="am_michael", speed=1.0, lang="en-us"); wall = time.time() - t
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    peak = float(np.abs(x).max())
    x = np.clip(x, -1, 1)
    with wave.open(str(OUT / "kokoro_raw.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((x * 32767).astype("<i2").tobytes())
    d = len(x) / sr
    return {"engine": "kokoro v1.0 fp32 am_michael", "load_s": round(load, 2), "wall_s": round(wall, 2),
            "audio_s": round(d, 2), "rtf": round(wall / d, 3), "raw_peak": round(peak, 3)}


def measure(p):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    summ = err[err.rfind("Summary:"):]
    return (float(re.search(r"I:\s+(-?[\d.]+) LUFS", summ).group(1)),
            float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ).group(1)))


def loudnorm(src, dst, target=-14.0):
    """Static gain to -14 LUFS, then a sample limiter at -2.4 dBFS (~-1.5 dBTP); repeat until within 0.2 LU.
    (Linear loudnorm refuses the gain speech needs under a TP ceiling; dynamic loudnorm pumps.)"""
    gain = target - measure(src)[0]
    for _ in range(4):
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af",
                        f"aresample=48000,volume={gain:.2f}dB,alimiter=limit=0.76:level=false:attack=2:release=60",
                        "-ac", "1", str(dst)], check=True)
        I, tp = measure(dst)
        if abs(I - target) <= 0.2:
            break
        gain += target - I
    return {"out": dst.name, "lufs": I, "true_peak_dbfs": tp, "gain_db": round(gain, 2), "duration_s": round(dur(dst), 2)}


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    (OUT / "script.txt").write_text(SCRIPT + "\n")
    rp = OUT / "report.json"
    rep = json.loads(rp.read_text()) if rp.exists() else {}
    rep["script_words"] = len(SCRIPT.split())
    if what in ("fish", "all"):
        rep["fish"] = fish()
    if what in ("kokoro", "all"):
        rep["kokoro"] = kokoro()
    if what in ("norm", "all"):
        if (OUT / "fish_raw.mp3").exists():
            rep.setdefault("fish", {})["normalised"] = loudnorm(OUT / "fish_raw.mp3", OUT / "fish.wav")
        if (OUT / "kokoro_raw.wav").exists():
            rep.setdefault("kokoro", {})["normalised"] = loudnorm(OUT / "kokoro_raw.wav", OUT / "kokoro.wav")
    rp.write_text(json.dumps(rep, indent=1)); print(json.dumps(rep, indent=1))
