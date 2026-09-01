"""Narration synthesis — REUSES the repo's existing TTS stack (read-only).

Reuse path (thinnest, chosen after inspecting configs/voices.yaml +
src/providers/tts_provider.py):
    from src.providers.tts_provider import FishAudioProvider
    provider.generate_voice(text, out.wav)
FishAudioProvider already reads voices.yaml via src.utils.config.get_config
(model s2.1-pro-free, voice 0327fdb5..., temperature/prosody/bitrate caps)
and post-converts to 44.1k stereo WAV via ffmpeg.

HARD LIMIT: FREE tier only.  The model is pinned to "s2.1-pro-free" here;
allow_paid must stay false.  If the Fish API fails or FISH_API_KEY is
missing we STOP and report — never switch provider or tier.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent  # /home/ubuntu/video_engine


def _ensure_env_key() -> None:
    """Load FISH_API_KEY from the repo .env into os.environ (silently)."""
    if os.environ.get("FISH_API_KEY"):
        return
    envp = REPO / ".env"
    if not envp.exists():
        raise RuntimeError(
            "FISH_API_KEY not set and no .env found in repo root — cannot use "
            "Fish Audio (STOP: no provider/tier fallback permitted)")
    for line in envp.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k == "FISH_API_KEY" and v:
            os.environ["FISH_API_KEY"] = v
            return
    raise RuntimeError("FISH_API_KEY not present in repo .env (STOP)")


def _get_provider():
    """Instantiate the repo's Fish provider, pinned to the FREE tier."""
    _ensure_env_key()
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from src.providers.tts_provider import FishAudioProvider
    except Exception as e:
        raise RuntimeError(f"cannot import repo TTS stack: {e} (STOP)")
    # allow_paid must be false in config — refuse paid tiers outright.
    try:
        from src.utils.config import get_config
        if get_config("voices.allow_paid", False) or \
                get_config("voices.fish.allow_paid", False):
            raise RuntimeError("voices.allow_paid is true — HARD LIMIT forbids "
                               "paid TTS (STOP)")
    except RuntimeError:
        raise
    except Exception:
        pass  # config import issue -> the provider itself re-reads config
    provider = FishAudioProvider(model="s2.1-pro-free")  # FREE tier pin
    if provider._model != "s2.1-pro-free":
        raise RuntimeError(f"Fish model drifted to '{provider._model}' — "
                           "refusing non-free tier (STOP)")
    return provider


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise RuntimeError(f"ffprobe could not read duration of {path}")


def tts_beat(story_dir: Path, beat_id: str, text: str, force: bool = False,
             provider=None) -> dict:
    story_dir = Path(story_dir)
    out_dir = story_dir / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / f"beat_{beat_id}.wav"
    if wav.exists() and wav.stat().st_size > 10000 and not force:
        print(f"[tts] beat {beat_id}: cached -> {wav}")
    else:
        provider = provider or _get_provider()
        print(f"[tts] beat {beat_id}: synthesizing ({len(text)} chars)")
        provider.generate_voice(text, str(wav))  # writes 44.1k stereo WAV
    return {"file": f"audio/beat_{beat_id}.wav",
            "duration": round(ffprobe_duration(wav), 3)}


def tts_story(story_dir: Path, force: bool = False) -> Path:
    """Synthesize every beat's narration -> audio/beat_<B>.wav + timing.json."""
    story_dir = Path(story_dir)
    story = json.loads((story_dir / "story.json").read_text())
    provider = None
    timing: dict = {}
    if not force:
        tp = story_dir / "audio" / "timing.json"
        if tp.exists():
            try:
                timing = json.loads(tp.read_text())
            except Exception:
                timing = {}
    for b in story["beats"]:
        bid = b["beat_id"]
        if not force and bid in timing and \
                (story_dir / timing[bid]["file"]).exists():
            print(f"[tts] beat {bid}: cached")
            continue
        provider = provider or _get_provider()
        info = tts_beat(story_dir, bid, b["narration"], force=True,
                        provider=provider)
        timing[bid] = info
    out = story_dir / "audio" / "timing.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(timing, indent=2))
    total = sum(v.get("duration", 0) for v in timing.values())
    print(f"[tts] timing.json written ({len(timing)} beats, {total:.1f}s total)")
    return out
