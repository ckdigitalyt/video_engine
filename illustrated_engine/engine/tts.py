"""Narration synthesis: thin adapter from the V14/V15 pipelines to the voice
layer (engine.voice, WP3). The channel voice is Kokoro (configs/voice.yaml);
Fish only runs on a paid plan (FISH_PLAN=paid + commercial_ok). V15 calls
engine.voice.synthesize_video directly (one voice for the whole video, with
whole-video fallback); V14 keeps this per-beat entry point.
"""

from __future__ import annotations

from pathlib import Path

from engine import voice


def tts_beat(story_dir: Path, beat_id: str, text: str, force: bool = False,
             function: str | None = None) -> dict:
    cfg = voice.load_config()
    lex = voice.load_lexicon(cfg)
    voice_id = cfg["channel_voice"]
    info = voice.synthesize_beat(
        story_dir, beat_id, text, function, cfg, voice_id=voice_id,
        lexicon=lex, force=force,
        get_provider=lambda: voice.make_provider(voice_id, cfg, lex))
    return {"file": info["file"], "duration": info["duration"]}
