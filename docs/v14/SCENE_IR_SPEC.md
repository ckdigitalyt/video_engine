# V14 Scene IR — `scene_spec.json` (v1.0)

**Location:** `illustrated_engine/engine/scene_ir.py` (validator/normalizer/hash) ·
**Examples:** `docs/v14/examples/scene_A_rich_subject.json`, `scene_C_scale_dive.json` ·
**Schema version:** `v14.scene_ir/1.0`

The story planner produces Scene IR; renderers consume it (directive §8, §22).
Pure JSON — no backend imports required. Stdlib-only validator: `python3
illustrated_engine/engine/scene_ir.py validate <spec.json>`; canonical cache
hash: `python3 illustrated_engine/engine/scene_ir.py hash <spec.json>`.

## Top-level fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `schema_version` | ✓ | `"v14.scene_ir/1.0"` | |
| `scene_id` | ✓ | string | stable per beat scene |
| `visual_grammar` | ✓ | §9 library id | 20 composition grammars (not templates) |
| `duration_s`, `fps` | ✓ | number > 0 | |
| `size` | ✓ | `[w, h]` ints | production default `[1080, 1920]` |
| `layers` | ✓ | list ≥ 1 | must include a `background`/`environment` layer (§7: a scene establishes a world) |
| `camera` | ✓ | object | `type` + **`purpose` (required)** + optional keyframes |
| `seed` | — | int | deterministic PRNG for procedural layers |
| `style_bible_ref` | — | string/null | style ≠ composition (§10): bible controls palette/texture, not layout |
| `animations` | — | list | each: `target_layer`, `property`, `purpose` (required), `keyframes` |
| `annotations` | — | list | reserved for planner prose consumed by overlay pass |
| `caption_safe_regions` | — | list of `{x,y,w,h}` | captions placed AFTER composition (§18) |
| `meta` | — | object | backend hints, benchmark tags |

## Layer fields

| Field | Required | Type/Values |
|---|---|---|
| `id` | ✓ | unique string |
| `type` | ✓ | `background, environment, subject, secondary_subject, foreground, atmosphere, texture, lighting, scientific_layer, semantic_annotation, text, mask, effect` |
| `semantic_role` | ✓ | string — why the layer exists |
| `source` | ✓ | `ai_image, procedural_svg, vector, raster, generated_gradient, generated_shape, procedural_particles, audio` |
| `payload` | conditional | object — **required for `semantic_annotation`/`text`** (§20: no empty containers) |
| `position` | — | `[x, y]` (default `[0, 0]`) |
| `scale`, `rotation`, `opacity` | — | numbers (defaults 1.0 / 0.0 / 1.0) |
| `z` | — | int z-order |
| `anchor` | — | default `"center"` |
| `depth` | — | 0.0 (far) … 1.0 (near) — drives parallax (§15) |
| `visibility` | — | `[start_s, end_s]` interval |
| `asset` | — | ref for `ai_image`/`raster` sources |

## Camera + animation semantics

- `camera.type` ∈ `static, push_in, pull_out, pan, travel, scale_dive, focus_shift, reveal`
- **`camera.purpose` and every `animations[].purpose` are required non-empty strings** —
  the validator *rejects* purposeless motion (directive §15: no random camera motion).
- Keyframes: `[{t, value, easing?}]`, `easing` ∈ `linear, ease_in_out_cubic, ease_out_cubic, ease_in_cubic`, times non-decreasing.
- `mask` layers can declare `grows_with_camera: true` — screen-space apertures that scale
  with the camera (how the BenchC eye→tissue→DNA dive stays one continuous shot).

## Cache integration (§24)

`spec_hash(spec)` — sha256 over canonical JSON (sorted keys, floats rounded to 1e-6),
first 16 hex chars. Scene render cache key = f(story hash, beat hash, **scene-spec hash**,
style-bible hash, asset hashes, **renderer backend + version**, camera choreography,
narration timing where relevant). Spec change ⇒ new hash ⇒ automatic invalidation.

## Compile path (Stage 5)

`SceneRenderer` adapter: `render(scene_spec) / render_frame(scene_spec, t) /
render_preview(scene_spec) / validate(scene_spec) / capabilities()`.
Implementations: `RemotionRenderer` (compiles IR → composition props), `FallbackRenderer`
(existing composev5/FFmpeg path). Business logic never imports a backend.
