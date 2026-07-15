# ADR-004: Zero-Result Providers Should Not Consume Attempt Budget

**Date:** 2026-07-14
**Status:** Implemented

---

## Problem

`AssetRouter.multi_query_search()` tracks an `attempts` counter that gates how many provider calls are made (default `max_attempts=15`). The counter was incremented **unconditionally** — before checking whether the provider returned any candidates.

For the "Space" category, the provider route is `["nasa", "pexels", "pixabay", "wikimedia"]`. NASA's API has extremely limited content (only 5 Artemis-related videos). When the `BeatDirector` calls `multi_query_search` with `max_attempts=1`:

1. Query: `'deep space nebula rotating slowly primary shot'` → NASA returns 0 results → `attempts=1` → **budget exhausted**
2. Pexels, Pixabay, Wikimedia are **never called** for this query
3. All subsequent queries follow the same pattern
4. Every shot falls through to `FallbackDirector`

This is the root cause of the 100% fallback rate observed in benchmark runs.

## Change

**File:** `src/assets/asset_router.py`
**Lines:** 259, 280

### Before

```python
for provider_name in provider_order:
    if attempts >= max_attempts:
        break
    attempts += 1                           # ← unconditional

    provider = self._providers.get(provider_name)
    ...
    results = provider.search(query, **kwargs)
    ...
    if results:
        # score, evaluate, etc.
```

### After

```python
for provider_name in provider_order:
    if attempts >= max_attempts:
        break

    provider = self._providers.get(provider_name)
    ...
    results = provider.search(query, **kwargs)
    ...
    if results:
        attempts += 1                        # ← only when candidates exist
        # score, evaluate, etc.
```

## Effect

| Before | After |
|---|---|
| NASA returns 0 → budget consumed → Pexels not reached | NASA returns 0 → budget **not** consumed → Pexels reached |
| Pexels returns 10 results → only reachable if NASA already consumed 0 budget | Pexels returns 10 results → scored and evaluated normally |
| Wikimedia never searched for topic-specific terms | Wikimedia reachable if Pexels/Pixabay also return empty |

## Validation

```
Query: 'deep space telescope time-lapse stars primary shot'

Before fix:
  NASA → 0 results (attempts=1, exhausted) → no Pexels → empty result

After fix:
  NASA → 0 results (attempts=0, continues)
  Pexels → 10 candidates (attempts=1, score=0.920)
  → Asset found, gates passed, download URL: videos.pexels.com/...
```

## Risk Assessment

| Factor | Rating | Notes |
|---|---|---|
| Breakage | **Low** | Only affects cases where a zero-result provider precedes a result-producing one |
| Budget inflation | **Low** | `max_attempts` still caps total evaluation rounds; zero-result calls are free |
| Provider ordering preserved | Yes | Route iteration order unchanged; providers before NASA still work as before |
| Infinite loops | **No risk** | `for provider_name in provider_order` is bounded; `max_attempts` prevents excess evaluations |
| Tests  | All existing pass | 13/13 tests pass with zero modifications |
