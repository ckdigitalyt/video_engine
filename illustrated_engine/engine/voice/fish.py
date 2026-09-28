"""Fish Audio provider (with-timestamp endpoint). PAID PLAN ONLY.

Disabled by default: constructing it raises VoiceUnavailable unless
FISH_PLAN=paid is set and the voice entry has commercial_ok: true. The free
model is not configurable (its ToS is non-commercial). The key is read from
the process env or the repo .env and is never printed or logged."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
URL = "https://api.fish.audio/v1/tts/stream/with-timestamp"
SR = 44100
_ENV_KEYS = ("FISH_API_KEY", "FISH_PLAN")


def _load_env_keys() -> None:
    """Load FISH_API_KEY / FISH_PLAN from the repo .env into os.environ."""
    if all(os.environ.get(k) for k in _ENV_KEYS):
        return
    envp = REPO / ".env"
    if not envp.exists():
        return
    for line in envp.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k in _ENV_KEYS and v and not os.environ.get(k):
            os.environ[k] = v


def parse_segments(events: list) -> tuple:
    """SSE event dicts -> (mp3 bytes, [{w,t0,t1}]) with chunk offsets applied."""
    audio, aligns, offs = b"", {}, {}
    for ev in events:
        if ev.get("audio_base64"):
            audio += base64.b64decode(ev["audio_base64"])
        if ev.get("alignment"):
            k = ev.get("chunk_seq", 0)
            aligns[k] = ev["alignment"]
            offs[k] = ev.get("chunk_audio_offset_sec", 0)
    words = [{"w": s["text"].strip(), "t0": round(s["start"] + offs[k], 3),
              "t1": round(s["end"] + offs[k], 3)}
             for k in sorted(aligns) for s in aligns[k]["segments"]
             if s["text"].strip()]
    return audio, words


class FishProvider:
    name = "fish"

    def __init__(self, voice_cfg: dict):
        from engine.voice import VoiceUnavailable
        _load_env_keys()
        if voice_cfg.get("model", "").endswith("-free"):
            raise VoiceUnavailable("fish free tier is non-commercial; refused")
        if os.environ.get("FISH_PLAN") != "paid":
            raise VoiceUnavailable("fish disabled: FISH_PLAN != paid")
        if not voice_cfg.get("commercial_ok"):
            raise VoiceUnavailable("fish disabled: commercial_ok is false")
        if not os.environ.get("FISH_API_KEY"):
            raise VoiceUnavailable("fish disabled: FISH_API_KEY not set")
        self.cfg = voice_cfg

    def synth(self, text: str, speed: float):
        from engine.voice import Clip, VoiceUnavailable
        payload = {"text": text, "reference_id": self.cfg["reference_id"],
                   "temperature": 0.6, "top_p": 0.9,
                   "prosody": {"speed": speed, "volume": 0,
                               "normalize_loudness": True},
                   "format": "mp3", "sample_rate": SR, "mp3_bitrate": 128,
                   "latency": "normal"}
        req = urllib.request.Request(
            URL, data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + os.environ["FISH_API_KEY"],
                     "Content-Type": "application/json",
                     "model": self.cfg["model"], "User-Agent": "Mozilla/5.0"})
        events = []
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                for line in r:
                    line = line.decode().strip()
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:]))
        except urllib.error.HTTPError as e:  # body may echo request metadata
            raise VoiceUnavailable(f"fish HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise VoiceUnavailable(f"fish network: {type(e).__name__}") from None
        mp3, words = parse_segments(events)
        if not mp3:
            raise VoiceUnavailable("fish returned no audio")
        p = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0", "-f", "f32le",
             "-ac", "1", "-ar", str(SR), "-"], input=mp3, capture_output=True)
        if p.returncode != 0:
            raise VoiceUnavailable("fish audio decode failed")
        return Clip(np.frombuffer(p.stdout, dtype=np.float32).copy(), SR,
                    words)
