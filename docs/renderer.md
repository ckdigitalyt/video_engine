# Renderer

The renderer layer is responsible for consuming a **timeline JSON** file
produced by the Execution node and producing the final `.mp4` output.

---

## Architecture

### Abstract Interface: `Renderer` (`src/renderer/__init__.py`)

```python
class Renderer(ABC):
    @abstractmethod
    def render(self, timeline_path: str, output_path: str) -> None: ...
```

The orchestrator depends on `Renderer` alone — it never imports a concrete
class directly.  This makes it trivial to swap renderers (e.g. MoviePy →
FFmpeg) without changing pipeline code.

### Concrete Implementation: `MoviePyRenderer` (`src/renderer/moviepy_renderer.py`)

`MoviePyRenderer` is the sole concrete implementation.  It decodes audio/video
clips using MoviePy (which wraps FFmpeg), composites them, and encodes the
final output via `write_videofile`.

### Backward Compatibility (`renderer.py`)

The top-level `renderer.py` module re-exports `MoviePyRenderer` and provides
module-level `render_timeline()` / `_parse_timeline()` functions so that code
importing the old API continues to work unchanged.

---

## Rendering Flow

```
timeline.json
      │
      ▼
  parse_timeline() ─────────────────────────────────────────┐
      │                                                     │
      ├── Audio clips: each audio_timeline entry            │
      │     → AudioFileClip(file).set_start(start_time)     │
      │     → CompositeAudioClip(all)                       │
      │                                                     │
      ├── Video clips: each video_timeline entry             │
      │     → VideoFileClip(file)                            │
      │     → .resize(newsize=target_resolution)             │
      │     → .set_start(start_time).set_end(end_time)      │
      │     → CompositeVideoClip(all, size=target_res)      │
      │                                                     │
      └── final_video.set_audio(final_audio)                │
              │                                              │
              ▼                                              │
      write_videofile(output, fps, codec, ...) ─────────────┘
              │
              ▼
      final_output.mp4
```

---

## Dependency Injection in the Orchestrator

```python
from src.renderer import Renderer
from src.renderer.moviepy_renderer import MoviePyRenderer

renderer: Renderer = MoviePyRenderer()
renderer.render("timeline.json", "final_output.mp4")
```

To swap renderers, import a different concrete class and inject it — no other
code changes are needed.

---

## Adding a New Renderer

1. Create a new module under `src/renderer/`, e.g. `ffmpeg_renderer.py`.
2. Implement the `Renderer` ABC:

```python
from src.renderer import Renderer

class FFmpegRenderer(Renderer):
    def render(self, timeline_path: str, output_path: str) -> None:
        # Build FFmpeg filter graph from timeline JSON
        ...
```

3. Inject it in `orchestrator.py`:

```python
renderer: Renderer = FFmpegRenderer()
```

---

## Pillow / MoviePy Compatibility

MoviePy 1.0.3 references the deprecated `PIL.Image.ANTIALIAS` constant, which
was removed in Pillow 11.  A compatibility shim at the top of
`src/renderer/moviepy_renderer.py` restores the alias:

```python
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
```

---

## Timeline JSON Schema

See the [Timeline Builder documentation](timeline_builder.md) or the schema
reference in the original renderer docs.

---

## Configuration (from `configs/render.yaml`)

| Parameter    | Default    | Description               |
|--------------|------------|---------------------------|
| `codec`      | `"libx264"`| Video codec               |
| `audio_codec`| `"aac"`    | Audio codec               |
| `threads`    | `4`        | CPU threads for encoding  |
| `preset`     | `"fast"`   | x264 encoding preset      |

---

## Test Strategy

Tests mock all MoviePy classes (`VideoFileClip`, `AudioFileClip`,
`CompositeVideoClip`, `CompositeAudioClip`) so no real FFmpeg encoding
occurs.  The interface tests verify:
- ABC cannot be instantiated
- `MoviePyRenderer` satisfies the `Renderer` contract
- `render()` reads, parses, composites, and encodes
- Invalid JSON / missing files raise appropriate errors
- Backward-compat module-level functions still work
