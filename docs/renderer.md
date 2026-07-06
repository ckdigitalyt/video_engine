# Renderer

`renderer.py` is the video-assembly and encoding module of the video_engine
pipeline.  It consumes a **timeline JSON** file produced by the Execution node
and produces the final `.mp4` output.

---

## Rendering Flow

```
timeline.json
      │
      ▼
  Parse timeline ─────────────────────────────────────────┐
      │                                                    │
      ├── Audio clips: each audio_timeline entry           │
      │     → AudioFileClip(file).set_start(start_time)    │
      │     → CompositeAudioClip(all)                      │
      │                                                    │
      ├── Video clips: each video_timeline entry            │
      │     → VideoFileClip(file)                          │
      │     → .resize(newsize=target_resolution)            │
      │     → .set_start(start_time).set_end(end_time)     │
      │     → CompositeVideoClip(all, size=target_res)     │
      │                                                    │
      └── final_video.set_audio(final_audio)               │
              │                                             │
              ▼                                             │
      write_videofile(output, fps, codec, ...) ────────────┘
              │
              ▼
      final_output.mp4
```

---

## Timeline JSON Schema

The timeline file is a JSON document with three top-level sections:

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
      "end_time": 12.5
    }
  ],
  "video_timeline": [
    {
      "layer": 1,
      "file": "cache/video/scene_1.mp4",
      "start_time": 0.0,
      "end_time": 12.5,
      "transition_out": "none"
    }
  ]
}
```

### `render_settings`

| Field | Type | Description |
|-------|------|-------------|
| `resolution` | `[int, int]` | Output video width and height in pixels |
| `fps` | `int` | Frames per second for the output |

### `audio_timeline[]`

| Field | Type | Description |
|-------|------|-------------|
| `track` | `str` | Logical track name (informational) |
| `file` | `str` | Path to the audio file (WAV/MP3) |
| `start_time` | `float` | Start offset in seconds |
| `end_time` | `float` | End time in seconds |

### `video_timeline[]`

| Field | Type | Description |
|-------|------|-------------|
| `layer` | `int` | Stacking order (higher = on top) |
| `file` | `str` | Path to the video file (MP4) |
| `start_time` | `float` | Start offset in seconds |
| `end_time` | `float` | End time in seconds |
| `transition_out` | `str` | Transition effect (`"none"`) |

---

## MoviePy Responsibilities

- **Decode** audio/video files via FFmpeg (through `AudioFileClip` / `VideoFileClip`)
- **Resize** video clips to the target resolution (`clip.resize(newsize=…)`)
- **Composite** multiple video layers (`CompositeVideoClip`) and audio tracks (`CompositeAudioClip`)
- **Encode** the final output via FFmpeg (`write_videofile`)

### Configuration (from `configs/render.yaml`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `codec` | `"libx264"` | Video codec passed to FFmpeg |
| `audio_codec` | `"aac"` | Audio codec passed to FFmpeg |
| `threads` | `4` | CPU threads for encoding |
| `preset` | `"fast"` | x264 encoding preset |

---

## FFmpeg Responsibilities

FFmpeg is not called explicitly by the renderer — MoviePy wraps it.  The actual
FFmpeg command is constructed internally by `write_videofile` using the codec,
preset, and thread settings provided.  The renderer also calls FFmpeg directly
in the Critic node to extract a single evaluation frame:

```bash
ffmpeg -y -i final_output.mp4 -ss 00:00:02 -vframes 1 cache/video/eval_frame.jpg
```

---

## Pillow / MoviePy Compatibility

MoviePy 1.0.3 references the deprecated `PIL.Image.ANTIALIAS` constant, which
was removed in Pillow 11.  A compatibility shim at the top of `renderer.py`
restores the alias so the latest Pillow works without changes:

```python
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
```

---

## Future Migration Path to Pure FFmpeg

For production-scale rendering, MoviePy can be replaced with direct FFmpeg
invocations.  The advantages would be:

1. **No Python dependency** on moviepy / pillow — fewer breakage points.
2. **Performance** — FFmpeg direct can use hardware acceleration (NVENC,
   VAAPI, VideoToolbox) which MoviePy does not easily expose.
3. **Memory** — FFmpeg streams frames without loading the entire video into
   Python memory.
4. **Reliability** — No version-skew issues like the Pillow compat problem.

### Migration sketch

The `render_timeline()` function would build an FFmpeg filter graph instead of
a MoviePy `CompositeVideoClip`:

```bash
ffmpeg \
  -i bg_video.mp4 \
  -i voiceover.wav \
  -filter_complex "
    [0:v]scale=1920:1080,setsar=1[v0];
    [v0]null[v];
    [1:a]adelay=0[a0]
  " \
  -map "[v]" -map "[a0]" \
  -c:v libx264 -preset fast -threads 4 \
  -c:a aac \
  final_output.mp4
```

This transition would be a separate refactoring effort.  The current MoviePy
layer provides a stable, well-tested baseline.
