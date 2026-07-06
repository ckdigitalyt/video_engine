# Audio Engine — video_engine

## Overview

The audio engine provides text-to-speech generation (via Kokoro) and
background music mixing for the video pipeline.  It is imported by the
orchestrator and exposes two main functions.

---

## Functions

### `generate_voice(text, output_path)`

Generates a voiceover WAV file from plain text using the configured
Kokoro TTS provider.

| Parameter     | Type   | Description                        |
|---------------|--------|------------------------------------|
| `text`        | `str`  | Narration text to synthesise.      |
| `output_path` | `str`  | Destination path for the WAV file. |

### `mix_audio(voice_path, music_path, output_path, ...)`

Mixes a voiceover WAV with background music, applying ducking, fades,
and volume adjustments.

| Parameter         | Type    | Default | Description                                      |
|-------------------|---------|---------|--------------------------------------------------|
| `voice_path`      | `str`   | —       | Path to the voiceover WAV file.                  |
| `music_path`      | `str`   | —       | Path to the background music file.               |
| `output_path`     | `str`   | —       | Destination path for the mixed WAV.              |
| `fade_in_ms`      | `int`   | 3000    | Fade-in duration for background music (ms).      |
| `fade_out_ms`     | `int`   | 3000    | Fade-out duration for background music (ms).     |
| `music_volume_db` | `float` | 0.0     | Additional gain on music before ducking (dB).    |

**Fallback behaviour:** If `music_path` does not exist, a silent track is
substituted so the pipeline continues normally with voice only.

---

## Pipeline Integration

The orchestrator's **Execution node** (Node 2) calls `mix_audio()` for every
scene after generating the voiceover.  Each scene's audio entry in the
timeline JSON is updated to reference the mixed WAV file.

```
Voice generation ──→ scene_1.wav ──┐
                                   ├── mix_audio() ──→ scene_1_mixed.wav
Background music ──────────────────┘
```

When background music is **disabled** (file not found), the scene WAVs are
used unmodified.

---

## Configuration (`configs/voices.yaml`)

```yaml
voices:
  mixing:
    ducking_db: -12         # Decibel reduction on music during voice
    tail_ms: 2000           # Silence (ms) appended after voice ends
    fade_in_ms: 3000        # Music fade-in duration (ms)
    fade_out_ms: 3000       # Music fade-out duration (ms)
    music_volume_db: 0.0    # Pre-ducking gain on music (dB)
    background_music: "cache/music/cinematic.mp3"
```

All parameters are loaded at runtime, so tweaking ducking or fade timing
requires only a YAML change — no code changes.

---

## Music Folder

The default music folder is `cache/music/` (configured in `pipeline.yaml`
under `pipeline.cache.music`).  Place royalty-free `.mp3` files there and
set `voices.mixing.background_music` to the file you want to use.

---

## Test Strategy

Tests generate real WAV/MP3 audio segments using `pydub.AudioSegment.silent`
and verify:
- File existence and non-zero size
- Duration matches voice + tail within tolerance
- Fade-in reduces RMS at the start
- Fade-out reduces RMS at the tail
- Volume boost increases RMS
- Volume cut decreases RMS
- Short music loops to cover long voice clips
- Missing music file falls back gracefully
- Missing voice file propagates as `FileNotFoundError`
- All mixing parameters have corresponding YAML keys

No external APIs or real Kokoro models are involved in tests — all audio is
generated programmatically.
