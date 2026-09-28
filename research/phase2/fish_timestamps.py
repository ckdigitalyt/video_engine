"""Phase 2: live test of Fish /v1/tts/stream/with-timestamp on the FREE model."""
import base64, json, os, sys, time, urllib.request
sys.path.insert(0, "/home/ubuntu/video_engine/illustrated_engine")
from engine.voice.fish import _load_env_keys
_load_env_keys()
text = "GPS satellites feel this every day. Their clocks run 38 microseconds fast."
payload = {"text": text, "reference_id": "0327fdb5da9e4fd782899a8058c8ae2b", "temperature": 0.6, "top_p": 0.9,
           "prosody": {"speed": 0.95, "volume": 0, "normalize_loudness": True},
           "format": "mp3", "sample_rate": 44100, "mp3_bitrate": 128, "latency": "normal"}
req = urllib.request.Request("https://api.fish.audio/v1/tts/stream/with-timestamp", data=json.dumps(payload).encode(),
    headers={"Authorization": "Bearer " + os.environ["FISH_API_KEY"], "Content-Type": "application/json",
             "model": "s2.1-pro-free", "User-Agent": "Mozilla/5.0"})
t = time.time(); audio = b""; aligns = {}; offs = {}; n = 0
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:"): continue
            ev = json.loads(line[5:]); n += 1
            if ev.get("audio_base64"): audio += base64.b64decode(ev["audio_base64"])
            if ev.get("alignment"):
                aligns[ev.get("chunk_seq", 0)] = ev["alignment"]; offs[ev.get("chunk_seq", 0)] = ev.get("chunk_audio_offset_sec", 0)
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read()[:300]); sys.exit(1)
open("/home/ubuntu/phase2_out/fish_ts.mp3", "wb").write(audio)
segs = [dict(s, start=round(s["start"] + offs[k], 3), end=round(s["end"] + offs[k], 3)) for k in sorted(aligns) for s in aligns[k]["segments"]]
print(json.dumps({"wall_s": round(time.time() - t, 2), "events": n, "chunks": len(aligns), "n_segments": len(segs), "segments": segs, "event_keys": list(ev.keys())}, indent=None)[:2500])
json.dump(segs, open("/home/ubuntu/phase2_out/fish_ts.json", "w"), indent=1)
