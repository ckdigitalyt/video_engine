# V14 Stage 2/3 — Visual Backend Toolchain Report (Oracle ARM64)

Date: 2026-09-26 · Machine: OCI Always Free, aarch64 4×Ampere-N1, 23 GB RAM, ~39 GB free disk, **no GPU** · Ubuntu 24.04, kernel 6.17.0-1018-oracle

## Tested

| Tool | Version | Install path | Result |
|---|---|---|---|
| Remotion + @remotion/cli | 4.0.529 | npm (remotion_bench/) | ✅ 4/4 scenes rendered headless, CLI-first |
| Motion Canvas (core/2d/ui/vite-plugin) | 3.17.2 | npm (mc_bench/) | ❌ **no headless render CLI** — `motion-canvas` bin absent, `@motion-canvas/ui` exports no bin, no `@motion-canvas/renderer` package on npm |
| Inkscape | 1.2.2 (preinstalled) | apt | ✅ available for SVG validation/conversion (not part of production render path) |
| resvg | — | not in apt (no candidate) | deferred — will install via `@resvg/resvg-js` (native arm64 binding) or static binary when Stage 4/7 needs fast SVG→PNG ops |
| VTracer | — | not installed | deferred — pip install when selective raster→vector layer work starts (Stage 7); usage policy per directive §14 |
| Synfig | 1.5.1 available | apt candidate (not installed) | deferred — optional specialist only; no character-rigging need in current six stories |
| Blender | — | — | not benchmarked per directive (no ARM64 production package) |

## Remotion benchmark metrics (1080×1920 @ 30 fps, --concurrency 2, CPU-only)

| Scene | Duration | Wall time | Peak RSS | Output | Notes |
|---|---|---|---|---|---|
| A rich subject (layered cell, push-in, parallax, annotation, audio) | 7.0 s / 210 fr | 48.3 s | 512 MB | 1.63 MB | audio track verified, A/V diff 0.061 s |
| B circular infographic (ring sweep, epoch labels, giant number) | 7.0 s / 210 fr | 21.7 s | 522 MB | 376 KB | |
| C scale-dive eye→tissue→DNA (continuous 1→30×, nested clip apertures, no crossfade) | 8.0 s / 240 fr | 27.6 s | 526 MB | 4.76 MB | single camera, zero crossfades |
| D parallax environment (5-band pan, fog drift, labels) | 7.0 s / 210 fr | 29.4 s | 512 MB | 1.01 MB | |
| bundle (startup cost) | — | 13.9 s | 1.0 GB | — | one-time per project version |

Throughput: **4.3–9.7 fps render** → a full 9:16 7 s scene in 22–48 s CPU-only; a 6-beat ~50 s video ≈ 5–10 min at 2 workers (bounded per directive §26).

**Determinism: PASS** — identical re-render of scene A produced a byte-identical mp4 (md5 `ed4883945976acb0fc8449c520704dea`).

Feature checks exercised by the scenes: gradients (radial/linear) ✅, filters (feGaussianBlur glow/fog) ✅, clip paths (nested, dynamic radius) ✅, nested groups + per-layer parallax transforms ✅, SVG text/typography (DejaVu Sans) ✅, stroke-dash reveal ✅, seeded PRNG determinism ✅, per-composition partial re-render ✅ (each comp renders independently), audio sync ✅.

## Stage 3 decision

**PRIMARY scene renderer: Remotion 4.0.529** (`visual_backend = remotion`; `visual_backend = auto` resolves to Remotion for rich vector scenes, existing deterministic SVG/FFmpeg path stays as fallback for simple diagrams and raster-cinematic shots per directive §23).

Rationale (quality × controllability × ARM64 viability × CPU cost × autonomous authorability):
1. CLI-first headless rendering, exits 0 unattended — matches the autonomous-pipeline requirement (§34).
2. Byte-identical determinism → cache keys can trust outputs (§24).
3. Programmatic TS scene authoring; one Scene IR can compile to Remotion compositions mechanically.
4. CPU cost within budget: ~0.5 GB RAM/worker, bounded concurrency.
5. H.264 out directly; per-scene partial rerender is native (composition-level).

**Motion Canvas: rejected as production renderer** — installs fine on ARM64 but ships no headless render path (no CLI bin in 3.17.2; rendering requires an interactive browser studio session), failing §1 (headless/scriptable) and §5 (autonomous authorability). Not kept "because interesting" per §6.

FallbackRenderer = existing composev5/FFmpeg pipeline (preserved, §33).

## Cache/partial-rerender notes for Stage 10

Per-composition outputs (out/BenchX.mp4) confirm scene-level granularity: changing one scene = re-render that composition only; final composite rebuilt from scene outputs + audio (FFmpeg concat/mux, existing). Cache key must add: scene-spec hash, renderer backend+version, camera choreography (§24).

## Next

Stage 4 Scene IR formalization (planner → `scene_spec.json`), Stage 5 SceneRenderer adapter (render/render_frame/preview/validate/capabilities + RemotionRenderer + FallbackRenderer), Stage 6 grammar library (3–5 grammars first).
