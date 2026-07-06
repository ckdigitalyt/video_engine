# Subtitles — video_engine

## Overview

The subtitle system generates **word-level, animated subtitles** synchronised
with the narration audio, burns them into the final rendered video, and also
produces standalone SRT and WebVTT files for external use.

Subtitles improve **viewer engagement** (YouTube retention) and
**accessibility** (hearing-impaired viewers, non-native speakers).

---

## Architecture

```
Narration audio (WAV)
       │
       ▼
SubtitleEngine.generate(audio_path, text)
       │
       ├── pydub silence detection → phrase boundaries
       ├── word distribution → word-level start/end timestamps
       ├── line grouping (max_words_per_line)
       └── animation effect applied
              │
              ▼
       Renderer clips ──→ MoviePyRenderer.composite() ──→ final video
       SRT output        (or any future renderer)
       WebVTT output
```

The subtitle timeline is **renderer-agnostic** — a list of plain dicts with
`start_ms`, `end_ms`, `text`, and animation fields.  Any renderer (MoviePy,
FFmpeg burn-in, HTML5 overlay) can consume the same data.

---

## How Timing Works

1. The narration WAV is loaded with **pydub** (`AudioSegment.from_wav`).
2. `detect_silence()` (from `pydub.silence`) finds natural pauses.
3. Non-silent (voice) segments are extracted from the pause boundaries.
4. Words are distributed proportionally across each voice segment.
5. If the audio is completely silent (no voice segments detected), words
   are distributed evenly across the full duration as a fallback.

This gives reasonably accurate word-level timing without forced-alignment
models or external APIs.

### Configuration tuning

| Config key | Default | Effect |
|---|---|---|
| `min_silence_ms` | `200` | Minimum silence gap (ms) to split phrases. Lower = more segments. |
| `silence_thresh` | `-40` | Silence threshold in dBFS. Lower = quieter detection. |

---

## Output Formats

### SRT

Standard SubRip format:

```
1
00:00:00,000 --> 00:00:01,250
The universe is vast

2
00:00:01,250 --> 00:00:02,500
and full of wonders
```

### WebVTT

W3C standard web format:

```
WEBVTT

00:00:00.000 --> 00:00:01.250
The universe is vast

00:00:01.250 --> 00:00:02.500
and full of wonders
```

### Internal JSON

Renderer-agnostic dict list consumed by the video compositor:

```json
[
  {
    "word": "the",
    "start_ms": 0.0,
    "end_ms": 125.0,
    "line": 0,
    "is_first_in_line": true,
    "is_last_in_line": false
  }
]
```

---

## Animation System

Animations are defined in `src/subtitles/animation.py`.

| Style | Description |
|---|---|
| `static` | Plain text — fully visible for the word's duration |
| `fade` | Fade-in at start, fade-out at end of each word |
| `karaoke` | Current word highlighted, previous words dimmed |
| `pop` | Scale up slightly on appearance |

### Adding a new style

1. Write a function matching `AnimationFn = (list[WordTiming]) -> list[WordTiming]`.
2. Register it in the `ANIMATION_STYLES` dict.
3. The style is automatically available via the `animation` config key.

---

## Configuration (`configs/render.yaml`)

```yaml
subtitles:
  enabled: true
  font: "Arial"
  font_size: 28
  color: "#FFFFFF"
  outline: "#000000"
  shadow: "#000000"
  bottom_margin: 80
  max_words_per_line: 4
  animation: "fade"       # static | fade | karaoke | pop
  min_silence_ms: 200
  silence_thresh: -40
```

Setting `enabled: false` skips subtitle generation entirely (the pipeline
runs faster).

---

## Integration Points

| Layer | File | What changed |
|---|---|---|
| **Engine** | `src/subtitles/engine.py` | Word timing, SRT/VTT/JSON formatting |
| **Animation** | `src/subtitles/animation.py` | Extensible animation styles |
| **Renderer ABC** | `src/renderer/__init__.py` | Added optional `subtitles` param to `render()` |
| **MoviePy** | `src/renderer/moviepy_renderer.py` | Composites `TextClip` overlays from clip dicts |
| **Orchestrator** | `orchestrator.py` | Calls `SubtitleEngine.generate()` per scene, passes clips to renderer |
| **Config** | `configs/render.yaml` | Full subtitle section |

---

## Test Strategy

| Area | What it verifies |
|---|---|
| **Generate** | Word entries, timing, monotonicity, line assignment, fallback timing |
| **Formats** | SRT/VTT structure, time formatting, empty input |
| **JSON** | Round-trip serialization |
| **Renderer clips** | All required keys present, count matches words |
| **Animation** | All styles registered, defaults, field injection |
| **Renderer integration** | Optional subtitles param accepted, backward compat |
| **Edge cases** | Long narration, single word, disabled mode, resolution override |
| **Config** | All YAML keys load correctly |
