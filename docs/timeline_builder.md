# Timeline Builder

The **Timeline Builder** (`src/renderer/timeline_builder.py`) is the single
authoritative module for constructing `timeline.json` — the intermediate
document that drives the MoviePy renderer.

It replaces the inline timeline construction that previously lived in
`orchestrator.py::execution_node`, providing deterministic timestamp
calculation, file-existence validation, and structural contract enforcement.

---

## Responsibilities

1. **Read generated audio files** — uses `pydub.AudioSegment` to determine
   exact per-scene audio duration.
2. **Calculate timestamps** — computes monotonic `start_time` / `end_time`
   values for every audio and video clip based on audio length.
3. **Produce the timeline contract** — emits a JSON document that matches
   the schema expected by `renderer.py::render_timeline`.
4. **Validate the timeline** — runs a suite of checks before writing to disk
   (see "Validation Rules" below).
5. **Write to disk** — serialises the validated timeline to `timeline.json`.

---

## Timeline Contract

The builder produces the same schema that the renderer consumes:

```json
{
  "render_settings": {
    "resolution": [1920, 1080],
    "fps": 30
  },
  "audio_timeline": [
    {
      "track": "voice",
      "file": "cache/audio/scene_1.wav",
      "start_time": 0.0,
      "end_time": 5.8
    }
  ],
  "video_timeline": [
    {
      "layer": 1,
      "file": "cache/video/scene_1.mp4",
      "start_time": 0.0,
      "end_time": 5.8,
      "transition_out": "none"
    }
  ]
}
```

### `render_settings`

| Field | Source | Description |
|-------|--------|-------------|
| `resolution` | `configs/render.yaml` | Output width × height in pixels |
| `fps` | `configs/render.yaml` | Frames per second |

### `audio_timeline[]`

| Field | Description |
|-------|-------------|
| `track` | Logical track name (informational) |
| `file` | Path to a WAV audio file |
| `start_time` | Playback start offset in seconds |
| `end_time` | Playback end offset in seconds |

### `video_timeline[]`

| Field | Description |
|-------|-------------|
| `layer` | Compositing layer (higher = on top) |
| `file` | Path to an MP4 video file |
| `start_time` | Playback start offset in seconds |
| `end_time` | Playback end offset in seconds |
| `transition_out` | Transition effect applied at the clip end (`"none"`) |

---

## Validation Rules

`TimelineBuilder.validate()` checks the following before any timeline is
committed to disk:

| # | Check | Error if |
|---|-------|----------|
| 1 | `render_settings` present | Section missing or missing `resolution` / `fps` |
| 2 | File existence (audio) | Any audio file path does not exist on disk |
| 3 | File existence (video) | Any video file path does not exist on disk |
| 4 | Monotonic timestamps | `end_time < start_time` for any entry |
| 5 | No overlap (audio) | An audio entry starts before the previous one ends |
| 6 | No overlap (video) | A video entry starts before the previous one ends |
| 7 | Duration correspondence | Total audio duration and total video duration differ by > 0.1 s |

If any check fails, the builder raises `RuntimeError` and does **not** write
the timeline file. This prevents the renderer from receiving an invalid input.

---

## Usage

```python
from src.renderer.timeline_builder import TimelineBuilder

builder = TimelineBuilder()
timeline_json = builder.build_and_write([
    {
        "scene_id": 1,
        "video_path": "cache/video/scene_1.mp4",
        "audio_path": "cache/audio/scene_1.wav",
    },
    # Future: additional scenes
])
```

The return value is the timeline as a JSON string; the file is written to
`timeline.json` (configurable via the `output_path` argument).

---

## Scene Clock

The builder maintains an internal **scene clock** (`current_time`) that
advances by each scene's audio duration. This ensures:

- **Monotonic** timestamps across scenes (no regressions).
- No manual offset arithmetic in the orchestrator.
- When multi-scene support is added, scenes simply stack end-to-end.

```
Scene 1:  [0.0 ────────────────────── 5.8]
Scene 2:                       [5.8 ───────────── 12.3]
         ^ clock advances by scene 1's audio duration
```

---

## Future Transition Support

The `transition_out` field is present in the schema but only `"none"` is
currently produced. To add cross-fades:

1. Add a `transition_offset` parameter (e.g. 0.5 s for a 0.5 s cross-fade).
2. Adjust `end_time` to extend past the overlap region.
3. The renderer would apply the corresponding MoviePy cross-fade filter.

The clock-advance logic is the single point of change:

```python
# Future: with transition_offset = 0.5
transition_offset = 0.5
current_time = end - transition_offset
```

No orchestrator code would need to change — only the builder's `_build()` method.
