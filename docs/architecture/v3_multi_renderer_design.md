# Jade v3 — Multi-Renderer Architecture (Wave 1 Foundation)

_Design for the v3 upgrade per `docs/directives/v3_master_brief_2026-08-30.md`.
Wave 1 scope: schemas, renderer interface + adapters, renderer router, AI Media
Broker, HF ZeroGPU client, tests. No production run, no new renderer bodies._

## 1. Target flow

```
OPENCLAW → RESEARCH → TOPIC / VIRAL ANGLE ANALYSIS → SCRIPT → STORY STRUCTURE
        → SHOT PLAN            (Story: narrative beats, roles, narration windows)
        → VISUAL DIRECTOR      (fills Shot/VisualSpec v3 fields, enforces variety policy §B)
        → ASSET PLANNER        (asset_requirements → broker requests, licenses, local library)
        → RENDERER ROUTER      (pure-Python scoring → renderer + fallback chain per shot)
        → INDIVIDUAL SHOT GENERATION   (per-shot render via Renderer interface)
        → SHOT QA              (technical + visual, per-shot qa_frames inspection)
        → ASSEMBLY             (FFmpeg, existing composition layer)
        → AUDIO MASTERING      (existing audio pipeline; per-shot music_state/sfx/duck)
        → FULL VIDEO QA        (technical/temporal/editorial/platform)
        → RETENTION CRITIC     (creative QA, §21)
        → SELECTIVE RECUT      (regenerate bad shots only, version video_01_rN)
        → FINAL VIDEO
```

The unit of planning is the **Shot** (`schemas/shot_v3.schema.json`), not the
scene. The LLM (visual director) authors Shot specs; renderers implement them
deterministically. Manim is a specialist renderer for math precision — never
the default.

## 2. Shot / VisualSpec v3

- `schemas/shot_v3.schema.json` — first-class Shot: `shot_id`, `duration_sec`,
  `narration_start/end`, `narrative_role`, `visual_goal`, `renderer`,
  `fallback_renderer`, `style`, `subject`, `background`, `camera`, `motion`,
  `composition`, `text_overlay`, `sfx`, `music_state`, `duck_music_db`,
  `asset_requirements`, `generation_priority`, `qa_requirements`,
  `visual_budget_ref`.
- `schemas/style_spec_v2.schema.json` — VideoStyleSpec (§17): `style_name`,
  `palette`, `typography`, `camera_language`, `lighting`, `texture`,
  `motion_language`, `transition_language`, `character_style`,
  `caption_style`. Every renderer receives this as render context.
- `schemas/visual_budget_v1.schema.json` — target renderer mix (§16),
  e.g. `{hero_ai_video_shots: 3, ai_image_motion_shots: 5, ...}`.
- Compatibility: `visualspec_v2` (beat-level Manim pipeline) is untouched;
  ManimRendererAdapter consumes it. Shot v3 is additive — no existing consumer
  breaks.

## 3. Renderer interface

`engine/renderers/base.py`:

```python
class Renderer(ABC):
    id: str                                        # "MANIM", "AI_VIDEO", ...
    def capabilities(self) -> RendererCapability   # from configs/renderers.yaml
    def validate(self, shot: dict, style: dict | None = None) -> list[str]
    def render(self, shot: dict, style: dict | None, ctx: RenderContext) -> ShotRenderResult
```

`ShotRenderResult`: `path` (rendered artifact), `metadata` (dict), `qa_frames`
(list of frame paths for vision QA).

Adapters (Wave 1):

| id | status | body |
|----|--------|------|
| `MANIM` | live adapter | wraps `engine.renderers.manim.compiler.compile_to_file` (VisualSpec v2 → scene file); zero behavior change |
| `MEDIA`, `VECTOR` | conformance adapters | registered, validate shots; render bodies arrive in Wave 2 |
| `AI_VIDEO`, `AI_IMAGE_MOTION`, `STOCK_VIDEO`, `ARCHIVAL`, `MOTION_CANVAS`, `PIXIJS`, `GODOT`, `OPEN_TOONZ` | registered stubs | `render()` raises `RendererNotImplemented`; Wave 2 fills |

## 4. Capability registry

`configs/renderers.yaml` → `engine/renderers/registry.py`. Per renderer
(`schemas/renderer_capability_v1.schema.json`): `strengths`, `input_kinds`,
`output`, `cost_tier` (LOW/MEDIUM/HIGH/HERO), availability flags
(`enabled`, `offline_capable`, `requires_network`), and ten quality
dimensions in `[0,1]`: realism, physical_motion, math_precision,
character_interaction, emotional_impact, historical_authenticity,
diagrammatic, camera_movement, text_heavy, stylization.

## 5. Renderer router

`engine/renderers/router.py` — pure Python, deterministic, no LLM/network:

```python
select_renderer(shot, *, availability=None, quota=None, style=None) -> RouterDecision
# RouterDecision: renderer_id, score, ranked list [(id, score)...],
#                 fallback_chain [ids], reasons [str]
```

Scoring model:

```
score(r) = Σ_d w_d · q_d(r) − cost_penalty(r) − quota_penalty(r) − variation_penalty(r)
```

- `w_d` = 1.0 for each dimension the shot flags (from `requirements` block),
  0.15 baseline for unflagged dimensions (keeps ranking stable, not flat).
- `cost_penalty`: shot `generation_priority` LOW/MEDIUM vs renderer cost tier
  HIGH/HERO → −0.6/−0.3 (surfaces cheap renderers unless realism/impact dims
  dominate). HERO priority gives +0.25 bonus to HIGH/HERO-tier renderers.
- `quota_penalty`: provider quota fraction < 1 scales remote renderers down.
- Unavailable renderers (explicitly off, or disabled in registry) are excluded
  from the primary choice but kept, marked, in the fallback chain.
- Fallback chain = chosen renderer first, then the canonical degradation
  chain §24 (AI_VIDEO → AI_IMAGE+MOTION → STOCK_VIDEO → MOTION_CANVAS →
  PIXIJS → MANIM) filtered to availability, ARCHIVAL spliced after
  STOCK_VIDEO when historical_authenticity is flagged.

## 6. AI Media Broker

`engine/broker/broker.py` — hides model/provider details from the pipeline:

```python
class MediaBroker:
    generate_image(prompt, *, style, aspect, seed, ...)  -> BrokerResult
    generate_video(prompt, *, image, duration, aspect, ...) -> BrokerResult
    image_to_video(image, prompt, *, duration, ...)      -> BrokerResult
    edit_image(image, instruction, ...)                  -> BrokerResult
    check_provider_health() -> dict[provider_id, bool]
    get_quota() -> dict[provider_id, QuotaState | None]
    get_capabilities() -> list[ProviderDescriptor]
    generate_high_value_hero_shot(shot, *, style) -> BrokerResult  # §9/§11
```

- `providers/base.py` — `MediaProvider` ABC (`id`, `kind`, `capabilities`,
  `health_check`, `quota`, and generation ops that default to
  `ProviderError("not supported")`).
- `providers/deepseek.py` — DeepSeek API provider. Note: the DeepSeek API has
  **no image-generation endpoint**; its multimodal model
  (`deepseek-v4-flash-vision-exp`) does image *understanding*. This provider
  therefore implements vision analysis (`analyze_image`) used by shot QA, plus
  `health_check`/`capabilities`; `generate_image` fails over to image-capable
  providers (SiliconFlow FLUX / NVIDIA NIM, mirroring `src/providers/image_gen.py`).
- `providers/stock.py` — Pexels + Pixabay stock providers (keys in `.env`,
  wrapping the proven `src/providers/asset_provider.py` search/download logic)
  with license metadata + deterministic cache.
- `providers/hf_zerogpu.py` — generic Gradio Space client (below).
- Provider registry: `configs/providers.yaml`-style registry inside the broker
  (`schemas/provider_registry_v1.schema.json`), ordered failover per kind.

## 7. HF ZeroGPU client

`engine/broker/providers/hf_zerogpu.py` — generic, endpoint-name-agnostic:

1. `discover(space_id)` (dry-run, no submit): GET
   `https://<space>/gradio_api/info` (fallback: `/config`), print/return
   named endpoints + parameter schemas.
2. `call(endpoint_name, data)`: POST `/gradio_api/call/<endpoint>`
   `{"data": [...]}` → `event_id`; GET
   `/gradio_api/call/<endpoint>/<event_id>` SSE stream; parse
   `event: generating|complete|error` lines; queue-aware with timeout.
3. Download result file URLs (HF_TOKEN as `Bearer` header, **never logged**).
4. Validate output: exists, min size, magic bytes (JPEG/PNG/MP4/WebP).
5. Cache hits via the broker cache; intelligently retry transient failures,
   then fail over to next provider.

Unit tests use recorded/mock HTTP; one optional `@pytest.mark.live` smoke test.

## 8. Cost tiers and visual budget

- Shot `generation_priority`: `low | normal | high | hero` mapped to cost tiers
  LOW/MEDIUM/HIGH/HERO (§26). Only HIGH/HERO shots normally consume remote
  video-generation quota.
- `visual_budget_v1` (§16) declares the target renderer mix before rendering;
  the visual director + router must reconcile shot plans against it
  (reconciliation tooling lands in Wave 2).

## 9. Offline fallback chain (§24)

`AI_VIDEO → AI_IMAGE+MOTION → STOCK_VIDEO → MOTION_CANVAS → PIXIJS → MANIM`

Every shot carries `fallback_renderer`; the router emits a full chain. With
all remote services down, MANIM (offline_capable) always terminates the
chain — the pipeline never collapses.

## 10. Caching

`engine/broker/cache.py`: deterministic key =
`sha256(prompt + model + seed + input_hash + style_hash + duration + aspect + renderer_version)`.
Layout: `cache/broker/<aa>/<key>.<ext>`. All broker operations consult the
cache before any network call; stock downloads cache by source URL + license
metadata sidecar. Rendered shots and QA results reuse the same pattern
(Wave 2 hooks).

## 11. Wave-2 implementation notes (2026-08-30)

All canonical-chain renderers now have real bodies (offline-capable unless
noted). Commit history carries the individual units.

### §6 MOTION_CANVAS — headless tradeoff (IMPORTANT)

Motion Canvas 3.x ships **no first-class headless CLI**: rendering requires
driving a browser (vite editor / puppeteer). On this CPU-only arm64 box that
harness is fragile, so the template library executes on a minimal
**node-canvas 2D engine** (`motion/templates/*.mjs` + `motion/render.mjs`)
with the SAME template JSON contract (`mc-json-v1`). All 11 §6 templates are
implemented (kinetic_title, timeline, map_zoom, infographic, comparison,
diagram, callout, number_counter, quote_card, before_after, reveal) plus
sequence compositions for zoom_sequence / scientific_process /
character_intro. A later migration to true Motion Canvas swaps only the node
runner — the Python adapter and scene JSON are unchanged.

### §7 PIXIJS — implementation tradeoff

pixi.js-legacy v7 cannot run under node-canvas ("document is not defined";
the @pixi/node shim targets the unmaintained v6 line). Verified experimentally
2026-08-30. The scene framework therefore runs directly on node-canvas
(`pixi/lib/scene.mjs`) with the §7 scene JSON contract: parallax layers,
seeded particles (dust/embers/stars/asteroid_field), cutout characters with
bob/run actions, camera push_in/pan/pull_out/shake, fly-in props. Ten
locally-authored SVG assets live in `engine/assets/library/` (attribution in
`engine/assets/library/ATTRIBUTION.md`). A puppeteer-based migration keeps
the Python adapter unchanged.

### §11/§12 AI_VIDEO + AI_IMAGE_MOTION

- Broker image providers: siliconflow → nvidia_nim → hf space (failover).
  SiliconFlow key returned 401 in this environment (2026-08-30) — failover
  and the offline solid-still path cover it.
- AI video providers: Wan 2.2 I2V + LTX via free HF ZeroGPU Spaces
  (configs/providers.yaml `hf_video`). LIVE-VERIFIED: LTX image-to-video
  (Lightricks/ltx-video-distilled, 4s 704x512 mp4 in ~12s). MiniMax H3 is
  paid-only → registered `enabled:false` with cost note (§26).
- hf_zerogpu client: Wave-2 live-routing fix — Gradio APIs are served on the
  Space's direct `<owner>-<name>.hf.space` subdomain (huggingface.co does not
  proxy /gradio_api/*); subdomain-first with cached working base + multipart
  file upload.

### §13 Archival licensing

NASA images API, Wikimedia Commons (CC0/PD-only gate) and Internet Archive
(publicdomain licenseurl gate) providers with license metadata sidecars and
deterministic download cache. Assets whose license cannot be established are
NEVER downloaded — candidates are skipped and the chain degrades.

### §16 Budget reconciliation

`engine/renderers/budget.py::reconcile_budget` — pure greedy post-pass after
the router: demotes over-budget buckets down the §24 chain (hero shots
protected, availability filtered), reports under-budget buckets as notes.

### Manim adapter fix

`ManimRenderer.validate` now validates against visualspec_v1 (the compiler's
actual schema) instead of v2 — the Wave-1 adapter rejected every spec the
compiler accepts.
