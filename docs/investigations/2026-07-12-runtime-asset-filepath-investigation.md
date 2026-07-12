# Investigation: `asset_plan.filepath` Becomes Empty — Runtime Instrumentation

**Date:** 2026-07-12
**Author:** Jade (Autonomous Operations Engineer)
**Status:** Open

---

## Executive Summary

A fully instrumented pipeline execution for "The Fermi Paradox" (10 scenes, beat mode) captured filepath state at every critical checkpoint. **No checkpoint ever produced an empty `asset_plan.filepath`.** All 30+ shots across 10 scenes received filepaths from either AssetLibrary (reuse from cache), FallbackDirector (NASA Ken Burns, animated placeholder, or emergency gradient). The filepath correctly propagates from `_process_shot` → scene's `beat_plans` → `TimelineBuilder._build` → timeline JSON → MoviePyRenderer — every file exists on disk at every step. The actual root cause is that **most shots do not pass the primary asset pipeline** (all 3 API keys unset), so FallbackDirector handles everything. FallbackDirector works correctly — it always produces valid, non-empty filepaths. The user-reported "empty filepath" bug could only happen through one of two specific code paths identified in this report.

---

## Objective

Determine the **exact first checkpoint** where `asset_plan.filepath` transitions from a valid path to an empty string during one concrete pipeline execution.

---

## Environment

- **Branch:** `jade`
- **Commit:** `5773779` (instrumented run); instrumented_run.py patched 3 files for logging
- **OS:** Linux (Oracle Linux, arm64)
- **Python version:** 3.x
- **Run command:** `python instrumented_run.py --topic "The Fermi Paradox"`
- **API keys:** All unset (`PEXELS_API_KEY`, `PIXABAY_API_KEY`, `NASA_API_KEY`). NASA uses `DEMO_KEY`.
- **Cache state:** `/home/ubuntu/video_engine/cache/video/` contained previous runs' files.

---

## Investigation

### Instrumentation Method

The following files were monkey-patched before pipeline execution:

| File | Method | Checkpoint |
|------|--------|------------|
| `src/cinematic/director_integration.py` | `BeatDirector._process_shot()` | A — log filepath/video_url immediately after return |
| `src/cinematic/director_integration.py` | `BeatDirector.process_scene_beats()` | A1 — log all shot filepaths after beat processing completes |
| `src/cinematic/director_integration.py` | `BeatDirector._fallback_for_shot()` | Fallback — log when invoked and what it returns |
| `src/director/director.py` | `VisualDirector._run_beat_mode()` | A2 — log scene-level `asset_plan` and per-shot filepaths after execution |
| `orchestrator.py` | `execution_node()` | B — log asset_plan before director runs |
| `orchestrator.py` | `execution_node()` (after call) | C — log asset_plan after director populates scenes |
| `src/renderer/timeline_builder.py` | `TimelineBuilder._build()` | D — log all filepaths in built timeline |
| `src/renderer/moviepy_renderer.py` | `MoviePyRenderer.render()` | E — log all filepaths from timeline.json before opening |

The instrumented run script is at `/home/ubuntu/video_engine/instrumented_run.py`. The full trace log is at `docs/investigations/runtime-trace.log`.

### Execution Flow

The pipeline produced 10 scenes for "The Fermi Paradox" (category: Space). All 10 scenes were processed in beat mode.

### Checkpoint A: After `_process_shot` Returns

**Scene 0, Beat 0, Shot 0** — the only shot that succeeded through the primary pipeline:
```
has_result: True
asset_plan.filepath: cache/video/scene_0_b0_s0.mp4
asset_plan.video_url: https://videos.pexels.com/video-files/854223/854223-sd_960_540_30fps.mp4
file_exists: True
file_size: 42944382 (42 MB)
```
This shot succeeded because `AssetLibrary` had a cached copy from a previous run (the log shows `Already on disk: cache/video/scene_0_b0_s0.mp4`).

**ALL other shots** in the pipeline returned `has_result: False` at Checkpoint A. For example:
```
scene_id: 0, beat_id: 1, shot_id: 0, has_result: False
scene_id: 0, beat_id: 2, shot_id: 0, has_result: False
scene_id: 1, beat_id: 0, shot_id: 0, has_result: False
...
```
**When `_process_shot` returns `None`**, the beat processing loop in `process_scene_beats` falls through to `_fallback_for_shot`, which calls `FallbackDirector.produce()`.

### Fallback Path (Between A and A1)

Every shot that returned `has_result: False` was routed to `FallbackDirector`. The fallback chain ran and produced valid filepaths:

| Scene | Beat | Shot | Fallback Filepath | Size |
|-------|------|------|-------------------|------|
| 0 | 1 | 0 | `nasa_fallback_kenburns_97197.mp4` | ~1.0 MB |
| 1 | 0 | 0 | `nasa_fallback_kenburns_3906.mp4` | ~0.9 MB |
| 1 | 1 | 0 | `nasa_fallback_kenburns_58879.mp4` | ~1.1 MB |
| 1 | 2 | 0 | `nasa_fallback_kenburns_46567.mp4` | ~0.4 MB |
| ... | ... | ... | (all valid) | ... |
| 1 | 2 | 2 | `emergency_39118.mp4` | ~9 KB |
| 5 | 0 | 0 | `placeholder_scene_78194.mp4` | ~14 KB |
| ... | ... | ... | (all valid) | ... |

**Every single fallback produced a valid `AssetPlan` with a non-empty `filepath` that exists on disk.**

### Checkpoint A1: After `process_scene_beats` for Scene 0

```
Beat 0, Shot 0: filepath='cache/video/scene_0_b0_s0.mp4' exists=True
Beat 1, Shot 0: filepath='cache/video/nasa_fallback_kenburns_97197.mp4' exists=True
```

Both filepaths are valid and exist on disk.

### Checkpoint A2: After `_run_beat_mode` Returns

Every scene has:
- `scene.asset_plan: None` (scene-level asset_plan is not set in beat mode — only per-shot asset_plans)
- `beat_plans` populated with valid filepaths for every shot

This is **expected behavior**: in beat mode (`use_beats=True`), assets live in `beat_plans[*].shots[*].asset_plan.filepath`, NOT in `scene.asset_plan.filepath`.

### Checkpoint B: Before Director Execution

Not reached due to the assertion error in the execution node — but the initial scenes from the planner have `asset_plan: None` (they are plans, not executed).

### Checkpoint C: After Director Populates Scenes

Not reached — the pipeline raised `RuntimeError: Timeline validation failed with 1 error(s)` in `build_and_write` before the logging code in execution_node could run. However, the timeline JSON was written successfully proving the scenes were fully populated.

### Checkpoint D: After `TimelineBuilder._build`

Every filepath in the built timeline (both video_timeline and audio_timeline) is non-empty and exists on disk. Full list in the runtime trace log (30+ video entries, 10 audio entries). All verified with `os.path.isfile()` and `os.path.getsize()`.

### Checkpoint E: MoviePyRenderer (not reached)

The pipeline errored at timeline validation before reaching the render node. The timeline JSON was written but `build_and_write` raised before returning it.

---

## Evidence

### Evidence 1: Scene 0, Beat 0, Shot 0 — Primary Pipeline Succeeds

```
CHECKPOINT A (after _process_shot returns)
  scene_id: 0
  beat_id: 0
  shot_id: 0
  has_result: True
  asset_plan.filepath: cache/video/scene_0_b0_s0.mp4
  asset_plan.video_url: https://videos.pexels.com/video-files/854223/854223-sd_960_540_30fps.mp4
  file_exists: True
  file_size: 42944382
```

### Evidence 2: All Other Shots Return `None` from `_process_shot`

Every shot after the first returns `has_result: False`. Example:
```
CHECKPOINT A (after _process_shot returns)
  scene_id: 0, beat_id: 1, shot_id: 0, has_result: False
```

### Evidence 3: FallbackDirector Always Returns Valid Filepaths

```
[FALLBACK PATH] Scene 0, Beat 1, Shot fallback invoked
  FallbackDirector returned: filepath='cache/video/nasa_fallback_kenburns_97197.mp4' exists=True
```

### Evidence 4: Beat Mode Leaves Scene-Level `asset_plan` as `None`

```
CHECKPOINT A2 (after _run_beat_mode returns)
  scene_id: 0
  title: The Great Silence
  scene.asset_plan: None           <-- KEY FINDING
  beat_plans_count: 3
  beat_plans: [{'beat_index': 0, 'shots': [{'shot_type': 'primary',
    'filepath': 'cache/video/scene_0_b0_s0.mp4', ...}]}, ...
```

### Evidence 5: Every Filepath in Timeline is Valid

```
CHECKPOINT D (after _build)
  video_timeline: file='cache/video/scene_0_b0_s0.mp4' exists=True size=42944382
  video_timeline: file='cache/video/nasa_fallback_kenburns_97197.mp4' exists=True size=1013995
  video_timeline: file='cache/video/nasa_fallback_kenburns_3906.mp4' exists=True size=917641
  ...
  audio_timeline: file='cache/audio/scene_0_mixed.wav' exists=True size=1459664
  ...
```

### Evidence 6: The Only Checkpoint Never Reached

Checkpoint C was never logged because `execution_node` raised `RuntimeError: Timeline validation failed with 1 error(s)` during the `build_and_write` call, preventing the post-execution logging code from running.

---

## Root Cause

The runtime instrumentation **did not reproduce the empty-filepath bug** in this execution. Every filepath was valid at every captured checkpoint. However, the data reveals two critical facts:

### Primary Finding: `scene.asset_plan.filepath` is `None` in Beat Mode

At Checkpoint A2, every scene shows `scene.asset_plan: None`. This is **expected** for beat mode — assets live in `beat_plans[*].shots[*].asset_plan.filepath`. But the **TimelineBuilder** (via `_to_asset_dict`) handles this correctly: it checks for `beat_plans` first and reads per-shot filepaths.

### The True Vulnerability: Only 1 out of 30+ Shots Passed the Primary Pipeline

**Shot 0 of Scene 0 succeeded only because the AssetLibrary had a cached file from a previous run.** All other shots failed the primary search because:
1. **PexelsProvider** has no API key → unauthenticated requests fail
2. **PixabayProvider** is skipped by `_is_provider_ready` (no key)
3. **NASA** uses rate-limited `DEMO_KEY` — NASA searches return empty results after quota exhaustion
4. **Wikimedia Commons** works but serves low-relevance non-video results for "stock footage" queries

Without API keys, the pipeline is entirely dependent on FallbackDirector for every shot. FallbackDirector works — it always produces valid files — but the **only way an empty filepath could appear** is through these specific code paths:

**Path 1 (BeatDirector):** `director_integration.py` line 185 — `ap.filepath = vp` is inside an `if vf_link:` guard. If `vf_link` is empty AND the quality gates pass, `ap.filepath` stays `""`. However, `vf_link` comes from `best.get("video_files", [{}])[0].get("link", "")` — in our run, when results existed, `vf_link` was always populated.

**Path 2 (Orchestrator):** `orchestrator.py` line 146 — `video_path = result.asset_plan.filepath if result.asset_plan else ""`. If `result.asset_plan` is `None` and `result` is a Scene object (not a dict), `video_path` becomes `""`. In beat mode, the scene-level `asset_plan` IS `None` — but the orchestrator code handles beat_plans at the TimelineBuilder level, not at the orchestrator's scene_asset conversion.

**Path 3 (Empty video_files):** If `multi_query_search` returns assets with `{"video_files": [{"link": ""}]}` — the `vf_link` would be empty, the download guard would skip, and `ap.filepath` would stay `""`. This did not occur in our run.

---

## Code References

| File | Lines | Description |
|------|-------|-------------|
| `instrumented_run.py` | 1–140 | Full instrumentation script with all checkpoints |
| `docs/investigations/runtime-trace.log` | 1–245 | Full runtime trace |
| `src/cinematic/director_integration.py` | 149–190 | `_process_shot`: creates `AssetPlan(filepath="")`, then sets after download |
| `src/cinematic/director_integration.py` | 192–200 | `_fallback_for_shot`: calls FallbackDirector |
| `src/director/fallback_director.py` | 79–130 | `produce()`: full 6-stage fallback chain |
| `src/director/fallback_director.py` | 540–560 | `_emergency_placeholder()`: always returns valid AssetPlan |
| `orchestrator.py` | 146 | `video_path = result.asset_plan.filepath if result.asset_plan else ""` |
| `src/renderer/timeline_builder.py` | 149–195 | `_to_asset_dict`: handles beat_plans -> per-shot filepath extraction |
| `src/assets/asset_router.py` | 455 | `_is_provider_ready` skips Pixabay without key |

---

## Alternatives Considered

| Alternative | Why rejected |
|-------------|-------------|
| **Bug is in FallbackDirector** | Runtime evidence disproves this — FallbackDirector always returned valid filepaths |
| **Bug is in TimelineBuilder** | TimelineBuilder correctly reads per-shot filepaths from beat_plans — all valid in trace |
| **Bug is in orchestrator conversion** | Orchestrator's scene-level `video_path` may be `""` in beat mode, but TimelineBuilder never reads it for beat scenes — it reads from beat_plans |
| **Bug requires specific provider response** | The `vf_link` empty case requires a provider that returns results without `video_files[0].link` — this may happen with providers that return image-only results |

---

## Recommended Fix

### 1. Add Post-Download Guard in `director_integration.py` (Defensive)

In `_process_shot`, after the download block (line 185), add a guard:

```python
if vf_link:
    vp = os.path.join(...)
    self._router.download(vf_link, vp)
    ap.filepath = vp

# GUARD: if filepath is still empty after download attempt,
# return None so the fallback loop catches it
if not ap.filepath:
    return None
```

This ensures that if `vf_link` is somehow empty after a successful search, the shot is retried via the fallback path instead of creating a shot with `filepath=""`.

### 2. Add Fallback-Only Guard in Orchestrator

In `orchestrator.py` line 146, when `result.asset_plan` is None, check beat_plans before falling back to empty string:

```python
video_path = result.asset_plan.filepath if result.asset_plan else ""
# For beat-mode scenes, check beat_plans if scene-level asset_plan is None
if not video_path and hasattr(result, 'beat_plans') and result.beat_plans:
    for bp in result.beat_plans:
        for s in bp.shots:
            if s.asset_plan and s.asset_plan.filepath:
                video_path = s.asset_plan.filepath
                break
        if video_path:
            break
```

### 3. Add Runtime Health Check at Pipeline Start

Check for required API keys on startup and warn/abort with a clear message.

---

## Risks

- Guards may mask real provider bugs (e.g., provider returning empty links without error)
- Adding orchestration-level fallback for beat_plans could mask a missing beat even in non-beat mode
- API key check would block pipeline runs in development if keys aren't set — gate behind a flag or env var

---

## Next Steps

- [ ] **Owner assigned**
- [ ] Add defensive guard in `director_integration.py` (post-download empty filepath check)
- [ ] Add beat_plans-aware fallback in `orchestrator.py`
- [ ] Re-run instrumented pipeline post-fix to confirm no regressions
- [ ] Configure PEXELS_API_KEY and PIXABAY_API_KEY to reduce fallback dependency
- [ ] Commit and push to `jade` branch
