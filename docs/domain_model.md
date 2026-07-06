# Domain Model Layer

The **Domain Model Layer** (`src/models`) defines typed, validated dataclasses
that represent the core concepts of the video_engine pipeline.  They replace
ad-hoc dicts with explicit contracts while preserving full backward
compatibility with existing serialization formats.

---

## Model Catalogue

### `Scene`

A single scene in a video project.  Produced by the planner from the LLM
output.

| Field | Type | Description |
|-------|------|-------------|
| `scene_id` | `int` | Unique scene number |
| `search_query` | `str` | Query string for asset search |
| `narration` | `str` | Narration / voiceover text |

### `SceneAsset`

Resolved file paths for a scene's media assets after the execution node has
downloaded and generated them.

| Field | Type | Description |
|-------|------|-------------|
| `scene_id` | `int` | Scene number this asset belongs to |
| `video_path` | `str` | Local path to the video clip |
| `audio_path` | `str` | Local path to the TTS audio file |

### `Narration`

Text-to-speech narration parameters (reserved for future multi-voice support).

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Narration text |
| `voice` | `str` | TTS voice identifier |
| `speed` | `float` | Speech speed multiplier |
| `language` | `str` | Language / accent tag |
| `output_path` | `str` | Output WAV path |

### `Timeline`

The complete timeline document consumed by the renderer.  Its `to_dict()`
method produces the exact dict structure that `renderer.py` reads from
`timeline.json`.

| Field | Type | Description |
|-------|------|-------------|
| `render_settings` | `RenderSettings` | Output resolution and FPS |
| `audio_timeline` | `list[TimelineTrack]` | Audio track entries |
| `video_timeline` | `list[TimelineTrack]` | Video track entries |

### `TimelineTrack`

A single entry in the audio or video timeline.

| Field | Type | Description |
|-------|------|-------------|
| `file` | `str` | Path to media file |
| `start_time` | `float` | Start offset (seconds) |
| `end_time` | `float` | End offset (seconds) |
| `track` | `str` | Track label (`"voice"`) |
| `layer` | `int` | Compositing layer |
| `transition_out` | `str` | Transition (`"none"`) |

### `RenderSettings`

Video output rendering parameters.

| Field | Type | Description |
|-------|------|-------------|
| `resolution` | `list[int]` | `[width, height]` in pixels |
| `fps` | `int` | Frames per second |

### `VideoMetadata`

Metadata about a produced video (populated after render).

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | Video topic |
| `duration_seconds` | `float` | Output duration |
| `file_size_bytes` | `int` | Output file size |
| `output_path` | `str` | Path to the output file |
| `approved` | `bool` | Critic approval |
| `iterations` | `int` | Critic loop count |
| `status` | `str` | Pipeline status |

### `VideoProject`

Top-level aggregate for a video production.

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | Topic from the user |
| `scenes` | `list[Scene]` | Planned scenes |
| `metadata` | `VideoMetadata` | Output metadata |
| `timeline` | `Timeline` | Built timeline |
| `iteration` | `int` | Current critic iteration |

### `AssetMetadata`

Metadata about a single asset obtained from a provider.

| Field | Type | Description |
|-------|------|-------------|
| `provider` | `str` | Provider name |
| `search_query` | `str` | Query used |
| `asset_url` | `str` | Remote URL |
| `local_path` | `str` | Local file path |
| `file_size_bytes` | `int` | File size |

### `ProviderResult`

Result from a provider search operation.

| Field | Type | Description |
|-------|------|-------------|
| `items` | `list[AssetMetadata]` | Found assets |
| `error` | `str` | Error message if any |

### `RenderResult`

Result of a video render operation.

| Field | Type | Description |
|-------|------|-------------|
| `output_path` | `str` | Path to output file |
| `duration_seconds` | `float` | Output duration |
| `file_size_bytes` | `int` | Output file size |
| `success` | `bool` | Success flag |
| `error` | `str` | Error message if any |

### `CriticResult`

Result from the Gemini multimodal critic.

| Field | Type | Description |
|-------|------|-------------|
| `approved` | `bool` | Whether the video passed QA |
| `decision` | `str` | Raw critic decision text |
| `error` | `str` | Error message if any |

### `ExecutionResult`

Complete result of a pipeline execution (maps to execution_history).

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | Topic processed |
| `status` | `str` | Pipeline status |
| `plan_json` | `str` | LLM plan JSON |
| `timeline_json` | `str` | Timeline JSON |
| `output_path` | `str` | Output file path |
| `duration_seconds` | `float` | Render duration |
| `iteration_count` | `int` | Critic iterations |
| `critic_approved` | `bool` | Final critic result |
| `error_message` | `str` | Error details |

### `ChannelProfile`

YouTube channel profile (reserved for future publisher integration).

| Field | Type | Description |
|-------|------|-------------|
| `channel_id` | `str` | YouTube channel ID |
| `name` | `str` | Channel name |
| `niche` | `str` | Content niche |
| `target_audience` | `str` | Target demographics |

### `UploadJob`

YouTube upload job (reserved for future publisher integration).

| Field | Type | Description |
|-------|------|-------------|
| `video_path` | `str` | Path to the video file |
| `title` | `str` | Video title |
| `description` | `str` | Video description |
| `tags` | `list[str]` | Video tags |
| `privacy_status` | `str` | Privacy setting |
| `channel_id` | `str` | Target channel |
| `status` | `str` | Upload status |

---

## Relationships

```
VideoProject
 ├── topic: str
 ├── scenes: list[Scene]          ← planner output
 │    ├── scene_id
 │    ├── search_query
 │    └── narration
 ├── metadata: VideoMetadata      ← after render
 ├── timeline: Timeline           ← after timeline builder
 │    ├── render_settings         ← from config
 │    ├── audio_timeline[Track]   ← one per scene
 │    └── video_timeline[Track]   ← one per scene
 └── iteration: int
```

---

## Lifecycle Through the Pipeline

```
 Start
   │
   ▼
 planner_node → Scene (via LLM JSON)
   │
   ▼
 execution_node → SceneAsset (paths resolved)
   │
   ▼
 TimelineBuilder → Timeline (validated)
   │
   ▼
 renderer.py → Timeline model parsed from timeline.json
   │
   ▼
 End
```

---

## Serialization Strategy

Models that need to be serialised (written to `timeline.json` or stored in the
database) provide explicit `to_dict()` / `to_json()` methods.  The serialized
output matches the exact format that the renderer expects, so the file format
is unchanged.

Deserialization happens via constructors from raw dicts — no ORM, no
auto-mapping, no schema migrations.

---

## Design Rules

- **No business logic** — methods are limited to `to_dict()`, `to_json()`,
  and `to_tuple()`.  No calculations, no validation beyond type hints.
- **No provider dependencies** — models do not import providers, configs,
  or pipeline modules.
- **No ORM** — models are plain `dataclasses` with no database coupling.
  Database operations belong in `MemoryManager` / `AssetCache`.
- **No behaviour change** — every model can be constructed from the same raw
  dicts the pipeline already produces, so existing code paths are unaffected.

---

## Future Extensibility

- Add `@dataclass(frozen=True)` for value-object semantics once the codebase
  stops mutating instances.
- Add `__post_init__` validation for invariants (e.g. scene_id > 0).
- Extend `Scene` with `transitions: list[Transition]` when cross-fade support
  is added to the timeline builder.
- Add `UploadResult` once the publisher module is implemented.
