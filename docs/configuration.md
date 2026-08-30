# Configuration Reference

The video_engine pipeline uses YAML configuration files located in the `configs/`
directory.  All hard-coded values have been moved into these files.  Pipeline
modules load their settings through the `src.utils.config` loader (see
`get_config()` / `load_config()`).

---

## configs/models.yaml — LLM Models

| Key | Default | Description |
|-----|---------|-------------|
| `llm.zai.model` | `"glm-5.3-flash"` | ZAI GLM model identifier |
| `llm.zai.max_tokens` | `8192` | Maximum tokens per LLM call (GLM reasoning tokens count) |
| `llm.zai.temperature` | `0.7` | Generation temperature |
| `llm.gemini.model` | `"models/gemini-2.5-flash-lite"` | Gemini model identifier for the critic |

---

## configs/render.yaml — Rendering

| Key | Default | Description |
|-----|---------|-------------|
| `render.resolution.width` | `1920` | Output video width (px) |
| `render.resolution.height` | `1080` | Output video height (px) |
| `render.fps` | `30` | Frames per second |
| `render.codec` | `"libx264"` | FFmpeg video codec |
| `render.audio_codec` | `"aac"` | FFmpeg audio codec |
| `render.threads` | `4` | CPU threads for encoding |
| `render.preset` | `"fast"` | FFmpeg encoding preset |
| `render.output.default` | `"final_output.mp4"` | Default output filename |

---

## configs/pipeline.yaml — Pipeline Behaviour

| Key | Default | Description |
|-----|---------|-------------|
| `pipeline.max_iterations` | `3` | Maximum critic loops before forced approval |
| `pipeline.cache.video` | `"cache/video"` | Directory for downloaded video clips |
| `pipeline.cache.audio` | `"cache/audio"` | Directory for generated audio files |
| `pipeline.cache.music` | `"cache/music"` | Directory for background music files |
| `pipeline.fallback.video` | `""` | Fallback video path (unused — FallbackDirector handles all degradation) |
| `pipeline.output.default` | `"final_output.mp4"` | Final output video filename |
| `pipeline.critic.frame_extraction_ss` | `"00:00:02"` | FFmpeg seek timestamp for frame extraction |
| `pipeline.critic.eval_frame` | `"cache/video/eval_frame.jpg"` | Path for the extracted evaluation frame |

---

## configs/providers.yaml — External API Providers

| Key | Default | Description |
|-----|---------|-------------|
| `providers.zai.base_url` | `"https://api.z.ai/api/paas/v4"` | ZAI API base URL |
| `providers.pexels.base_url` | `"https://api.pexels.com/videos/search"` | Pexels video search endpoint |
| `providers.pexels.per_page` | `5` | Results per Pexels search request |
| `providers.pexels.orientation` | `"landscape"` | Pexels orientation filter |

---

## configs/voices.yaml — TTS & Audio Mixing

| Key | Default | Description |
|-----|---------|-------------|
| `voices.kokoro.model` | `"kokoro-v0_19.onnx"` | Kokoro ONNX model file |
| `voices.kokoro.voices_bin` | `"voices.bin"` | Kokoro voices binary file |
| `voices.kokoro.default_voice` | `"bm_george"` | Default TTS voice identifier |
| `voices.kokoro.speed` | `1.0` | Speech speed multiplier |
| `voices.kokoro.language` | `"en-gb"` | Language/accent tag |
| `voices.mixing.ducking_db` | `-12` | Decibel reduction for music ducking |
| `voices.mixing.tail_ms` | `2000` | Tail silence appended after voice (ms) |
| `voices.mixing.background_music` | `"cache/music/cinematic.mp3"` | Default background music path |

---

## configs/logging.yaml — Logging

| Key | Default | Description |
|-----|---------|-------------|
| `logging.level` | `"INFO"` | Root logger level |
| `logging.file` | `"logs/video_engine.log"` | Log file path |
| `logging.format` | `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"` | Log message format |

---

## Config Loader API

The `src.utils.config` module provides two functions:

### `load_config(reload=False)` -> dict

Loads and merges all YAML files from `configs/` into a single nested dictionary.
Results are cached; pass `reload=True` to re-read from disk.

### `get_config(key, default=None)` -> any

Retrieve a value using dot-separated key notation.

```python
from src.utils.config import get_config

fps = get_config("render.fps", 30)
model = get_config("llm.zai.model")
```

Returns the configured value, or the provided default if the key does not exist.

---

## Adding a New Config Value

1. Add the key and default to the appropriate `configs/*.yaml` file.
2. Call `get_config("section.key", <default>)` in the Python code.
3. Document the new key in this file.
