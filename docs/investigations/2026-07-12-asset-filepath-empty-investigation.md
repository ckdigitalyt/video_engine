# Investigation: AssetPlan.filepath Becomes Empty at Runtime

**Date:** 2026-07-12
**Author:** Jade (Autonomous Operations Engineer)
**Status:** Open

---

## Executive Summary

`AssetPlan.filepath` (the local filesystem path to a downloaded video asset) is observed to be an empty string during downstream rendering, causing videos to fail with missing-file errors. Investigation reveals three independent code paths that produce `AssetPlan` objects with `filepath=""`, plus a fourth path where an empty filepath can be produced by the download process succeeding but failing to propagate the path. The root cause is a combination of (a) missing API keys causing the primary asset-search path to short-circuit to fallback, (b) the fallback chain itself relying on network-dependent providers that also fail without keys, and (c) a code path in `_process_scene` that initialises `AssetPlan` with `filepath=""` before the download call, with no guard ensuring `filepath` is populated afterward.

---

## Objective

Determine exactly where `asset_plan.filepath` becomes empty during the video generation pipeline, from initial asset selection through to the Scene object consumed by `TimelineBuilder` and `MoviePyRenderer`.

---

## Environment

- **Branch:** `jade`
- **Commit:** `5773779` (at time of investigation)
- **OS:** Linux (Oracle Linux, arm64)
- **Python version:** 3.x (venv at `/home/ubuntu/video_engine/venv/`)
- **Key dependencies:** moviepy, pydub, requests, pydantic, ffmpeg
- **Relevant configuration:** No `.env` file; `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `NASA_API_KEY` are all unset
- **Cache directories:** `cache/video/`, `cache/audio/`, `cache/images/`

---

## Investigation

### 1. Data Model

`AssetPlan` is defined in `src/models/schemas.py` (line 308):

```python
class AssetPlan(BaseModel):
    provider: ProviderType = Field(default=ProviderType.PIXABAY, ...)
    filepath: str = Field(default="", description="Local file path ...")
    video_url: str = Field(default="", ...)
    query_used: str = Field(default="", ...)
```

The `filepath` field defaults to `""`. There is a `field_validator("filepath")` at line 360 that rejects filepaths not ending in `.mp4`, but an empty string passes this validator.

### 2. Code Path A — Primary Scene Processing (`VisualDirector._process_scene`)

**File:** `src/director/director.py`, lines 388–527

Flow:

1. `multi_query_search()` is called. Since all API keys are unset:
   - PexelsProvider is created with `self._api_key = os.environ.get("PEXELS_API_KEY")` → `None`
   - PexelsProvider.search() calls the Pexels API without an API key header → likely fails with 401 or empty results
   - PixabayProvider is skipped by `_is_provider_ready()` because `PIXABAY_API_KEY` is empty (line 455 of `asset_router.py`)
   - NASA and Wikimedia are checked but operate on different content — the router iterates, gets empty results for all

2. `multi_query_search()` returns `{"assets": [], "selected_score": -1.0, ...}`

3. Back in `_process_scene()`, the loop sees `not videos` → `continue` for every query/regeneration attempt.

4. After all regenerations exhausted, the code falls through to the **FallbackDirector** block at line 568:

```python
fallback_asset = self._fallback_director.produce(...)
if fallback_asset and fallback_asset.filepath:
    video_path = fallback_asset.filepath
    ...
```

5. `FallbackDirector.produce()` runs its own chain. Without API keys:
   - `_try_nasa_image()` — NASA API uses `DEMO_KEY` by default (rate-limited, 30 req/hr). May work once, but image search + Ken Burns animation is expensive and may fail or return No Content.
   - `_try_wikimedia_image()` — no auth needed, depends on network. If it works, produces a Ken Burns-animated MP4.
   - `_try_reuse_scene()` — requires previously accepted scenes. On first scenes, this list is empty → returns `None`.
   - `_try_animated_placeholder()` — pure ffmpeg, no API needed. **This always returns a valid AssetPlan with a real filepath.**
   - `_emergency_placeholder()` — last resort, always produces a file.

**Conclusion for Path A:** If FallbackDirector succeeds (placeholder or emergency), `filepath` *is* populated. However, if `_try_animated_placeholder` fails (e.g., ffmpeg issues), the emergency placeholder also produces a valid file. **Path A should always produce a valid filepath in fallback.** But the fallback chain is network-dependent for the first 3 stages and may take a long time to fail.

### 3. Code Path B — Intermediate Temporary AssetPlan With `filepath=""` (Lines 433–449)

In the primary loop of `_process_scene()`, before the download happens, an `AssetPlan` is created at line 434:

```python
best_asset_plan = AssetPlan(
    provider=ProviderType(selected_provider),
    filepath="",           # <--- EMPTY
    video_url=vf_link,
    ...
)
```

This object is then passed to the semantic validator and quality gates with `filepath=""`. If the quality gates check the filepath (they don't at this stage — they check metadata, not file existence), this passes. Then the download happens at line 501:

```python
self._router.download(video_url, video_path)
```

After download, a new `AssetPlan` is built at line 517:

```python
asset_plan = self._build_asset_plan(provider=..., video_path=video_path, ...)
```

**This *does* pass `video_path` as the `filepath`, so if the primary path works, filepath is correctly populated.** But note: the intermediate `best_asset_plan` with `filepath=""` is used for semantic validation (line 454). The semantic validator (`src/validation/semantic_validator.py`, line 225) accesses `asset.filepath` for filename-based hints — it will get an empty string.

### 4. Code Path C — BeatDirector Creates AssetPlan With `filepath=""`

**File:** `src/cinematic/director_integration.py`, lines 157–185

```python
ap = AssetPlan(
    provider=ProviderType(sp), filepath="", video_url=vf_link,  # <--- EMPTY
    ...
)
# ... validation passes ...
if vf_link:
    vp = os.path.join(self._cache_video, f"scene_{scene.scene_id}_b{beat.index}_s{shot_index}.mp4")
    self._router.download(vf_link, vp)
    ap.filepath = vp    # <--- populated AFTER download
```

**Vulnerability:** If `vf_link` is empty (e.g., the search result had no `video_files`), the `if vf_link:` guard is False, and `ap.filepath` stays `""`. This happens when the provider returns a search result without a download link.

### 5. Code Path D — Filepath Lost During Orchestrator Conversion

**File:** `orchestrator.py`, lines 146–180

When the orchestrator converts director results to Scene objects:

```python
video_path = result.asset_plan.filepath if result.asset_plan else ""
```

If `result.asset_plan` is `None`, `video_path` is `""`, and later an `AssetPlan` is created with `filepath=video_path` = `""`.

### 6. The "Zero Bytes" Filepath Path (FallbackDirector)

The handover report mentions `fallback_director.py` was "zero bytes" at some point. This file is now populated and functional. The `_validate_visual()` method in fallback_director.py correctly rejects files smaller than 1024 bytes.

### 7. Confirmed Environment State

```
PEXELS_API_KEY = NOT_SET
PIXABAY_API_KEY = NOT_SET
NASA_API_KEY = NOT_SET
```

No `.env` file was found in `/home/ubuntu/video_engine/.env` (auto-loader at top of `asset_router.py` tries to load it, but it doesn't exist).

---

## Evidence

### Evidence 1: Pixabay provider skipped when API key missing

`asset_router.py` line 455:

```python
@staticmethod
def _is_provider_ready(provider, name):
    if name == "pixabay":
        key = os.environ.get("PIXABAY_API_KEY", "")
        if not key:
            return False
    return True
```

Confirmed: `PIXABAY_API_KEY` is unset, so Pixabay is always skipped in multi-query search.

### Evidence 2: PexelsProvider initialized with empty API key

`asset_provider.py` line 47:

```python
self._api_key = os.environ.get("PEXELS_API_KEY")
```

Confirmed: `PEXELS_API_KEY` is unset → `self._api_key = None`. Pexels `search()` will make an unauthenticated request which the Pexels API rejects.

### Evidence 3: AssetPlan initialised with `filepath=""` before download

`director.py` line 436:

```python
best_asset_plan = AssetPlan(
    provider=ProviderType(selected_provider),
    filepath="",       # Empty
    ...
)
```

### Evidence 4: BeatDirector leaves filepath empty when vf_link is empty

`director_integration.py` lines 157, 185:

```python
ap = AssetPlan(..., filepath="", ...)
# ...
if vf_link:
    ...
    ap.filepath = vp   # Only set if vf_link is truthy
```

### Evidence 5: Orchestrator uses empty filepath from Scene objects

`orchestrator.py` line 146:

```python
video_path = result.asset_plan.filepath if result.asset_plan else ""
```

If `result.asset_plan` is None → `video_path` is `""`.

### Evidence 6: FallbackDirector has a robust fallback chain ending with guaranteed placeholder

`fallback_director.py` — the full chain is:
1. NASA image + Ken Burns (API-dependent, `DEMO_KEY` available but rate-limited)
2. Wikimedia image + Ken Burns (network-dependent, no auth)
3. Generated image (stub — always returns None)
4. Reuse previous scene (depends on prior success)
5. Animated placeholder (pure ffmpeg, no network)
6. Emergency placeholder (pure ffmpeg, no network)

Steps 5 and 6 are guaranteed to produce filepaths when ffmpeg is available.

---

## Root Cause

The root cause is **not a single bug** but a cascade of contributing factors, all stemming from **unconfigured API keys** combined with **insufficient filepath validation**:

### Primary Factor (Operational)
**All three asset-provider API keys (`PEXELS_API_KEY`, `PIXABAY_API_KEY`, `NASA_API_KEY`) are unset.** This causes:

1. **Pixabay** — Skipped entirely by `_is_provider_ready()`
2. **Pexels** — Makes unauthenticated requests that fail
3. **NASA** — Uses `DEMO_KEY` (rate-limited to 30 req/hr, may succeed on first call but unpredictable)
4. **Wikimedia** — No auth required, but search quality is low for stock footage

The result: `multi_query_search()` returns empty results for all queries, forcing the system into the **FallbackDirector** chain for every scene.

### Secondary Factor (Defensive Gap)
**The FallbackDirector chain works correctly** — stages 5 and 6 (animated placeholder + emergency) always produce valid files. However, the chain is slow: it tries NASA, Wikimedia, and attempted image generation before reaching the guaranteed fallbacks. In a production pipeline with many scenes, this latency compounds.

### Tertiary Factor (Missing Guard)
In `director_integration.py` (line 157) and `director.py` (line 434), `AssetPlan` objects are constructed with `filepath=""` and used for semantic validation / quality gates **before** the download happens. If the download is never reached (because the search fails), or if `vf_link` is empty, the `filepath` stays empty. There is **no post-download guard** that checks `filepath` is non-empty before attaching to the Scene object.

---

## Code References

| File | Lines | Description |
|------|-------|-------------|
| `src/models/schemas.py` | 308–362 | `AssetPlan.filepath` default `""`, validator only checks `.mp4` suffix |
| `src/director/director.py` | 434–436 | Temporary `AssetPlan` with `filepath=""` before download |
| `src/director/director.py` | 501–527 | Primary path: download then `_build_asset_plan` with real path |
| `src/director/director.py` | 560–620 | Fallback path: use FallbackDirector, then build AssetPlan |
| `src/cinematic/director_integration.py` | 157–185 | BeatDirector: `AssetPlan` with `filepath=""`, guarded download |
| `src/assets/asset_router.py` | 265, 455 | `_is_provider_ready` skips Pixabay without key |
| `src/providers/asset_provider.py` | 47, 102, 202, 284 | Pexels/Pixabay providers read API keys from env |
| `src/director/fallback_director.py` | 79–200 | Fallback chain logic |
| `orchestrator.py` | 146–180 | Scene-to-AssetPlan conversion, empty filepath handling |

---

## Alternatives Considered

| Alternative | Pros | Cons |
|-------------|------|------|
| **Set API keys** (recommended) | Solves the root cause; primary providers work; fallback used only for true failures | Requires access to Pexels/Pixabay API keys |
| **Hardcode ffmpeg-only path** | Removes network dependency | Defeats purpose of real stock footage |
| **Add runtime `filepath` guard** | Catches empty filepath before render | Treats symptom, not cause |
| **Early-exit in FallbackDirector** | Skip network-dependent stages if offline | Reduces fallback quality |

---

## Recommended Fix

### Immediate (Configuration Fix)
1. **Set required API keys** as environment variables:
   ```bash
   export PEXELS_API_KEY="<your_key>"
   export PIXABAY_API_KEY="<your_key>"
   ```
2. Optionally create a `.env` file at `/home/ubuntu/video_engine/.env` so the auto-loader in `asset_router.py` picks them up:
   ```
   PEXELS_API_KEY=<your_key>
   PIXABAY_API_KEY=<your_key>
   ```

### Short-term (Defensive Fix)
3. In `director_integration.py`, add a guard after the download:
   ```python
   if vf_link:
       ...
       if os.path.isfile(vp) and os.path.getsize(vp) > 0:
           ap.filepath = vp
   # If no valid filepath, fall through to fallback
   if not ap.filepath:
       fallback = self._fallback_for_shot(scene, beat, shot, narration)
       if fallback and fallback.filepath:
           return fallback
       return None
   ```

4. In `director.py` line 434, add a filepath check before returning from the primary path:
   ```python
   if not video_path or not os.path.isfile(video_path):
       # Download failed silently — don't return a broken AssetPlan
       continue  # or fall through to fallback
   ```

### Medium-term
5. Add a health check for API key presence at pipeline startup that warns or fails fast.

---

## Risks

- **Setting API keys** has zero risk — the keys are used for read-only stock media search.
- **Adding defensive guards** may shift the failure from "empty filepath silence" to "fallback director invoked" which is measurable and logged.
- **Adding startup API key check** may cause pipeline startup failures in development; gate it behind a config flag.

---

## Next Steps

- [ ] **Owner assigned**
- [ ] Configure PEXELS_API_KEY and PIXABAY_API_KEY environment variables
- [ ] Add defensive filepath guards in `director_integration.py` and `director.py`
- [ ] Add pipeline startup health check for API key presence
- [ ] Verify end-to-end: run a single scene through the pipeline and confirm `asset_plan.filepath` is non-empty
- [ ] Commit fixes and push to `jade` branch
