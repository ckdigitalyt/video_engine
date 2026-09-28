"""Phase 2: minimal live Fish Audio check (uses the repo provider, free tier pin).
BROKEN since WP3: engine.tts._get_provider / ffprobe_duration were removed (Fish is paid-gated in engine/voice/fish.py). One-off script, kept for the record."""
import json, os, sys, time, urllib.request
sys.path.insert(0, "/home/ubuntu/video_engine")
sys.path.insert(0, "/home/ubuntu/video_engine/illustrated_engine")
from engine.tts import _get_provider, ffprobe_duration
p = _get_provider()
out = "/home/ubuntu/phase2_out/fish_check.wav"
text = "In nineteen oh eight, a fireball flattened eighty million trees in Siberia."
t = time.time()
p.generate_voice(text, out)
el = time.time() - t
d = ffprobe_duration(out)
print(json.dumps({"ok": True, "wall_s": round(el, 2), "audio_s": d, "rtf": round(el / d, 3)}))
# account credit endpoint (prints only the response body, not the key)
for path in ("/wallet/self/api-credit", "/wallet/self/package"):
    try:
        r = urllib.request.Request("https://api.fish.audio" + path,
            headers={"Authorization": "Bearer " + os.environ["FISH_API_KEY"]})
        with urllib.request.urlopen(r, timeout=30) as resp:
            print(path, resp.status, resp.read()[:600].decode())
    except Exception as e:
        print(path, "ERR", str(e)[:200])
