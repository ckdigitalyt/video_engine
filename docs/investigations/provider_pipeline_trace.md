# Provider Pipeline Trace

**Date:** 2026-07-14
**Topic:** The Fermi Paradox — Scene 0, Beat 0, Shot 0

---

## Query: `"deep space nebula rotating slowly primary shot"`

| Provider | Results | Download URL | Status |
|---|---|---|---|
| **NASA** | 0 | — | No candidates |
| **Pexels** | **10** | `https://videos.pexels.com/video-files/15289793/...` | ✅ Downloaded (11.4 MB) |
| Pixabay | (not reached) | — | Pexels succeeded first |
| Wikimedia | (not reached) | — | Pexels succeeded first |

## Semantic Score: **0.900** (threshold 0.75) ✅

## Quality Gates:
- semantic: 0.900 >= 0.75 ✅
- aesthetic: first asset, style=space_photo ✅
- reuse: no reuse detected ✅
- duplicate: no duplicate detected ✅

## AssetPlan.filepath before return:

```
'cache/video/trace_scene_0_b0_s0.mp4'
```

---

## Finding

The provider pipeline is **functional**. Pexels returned 10 candidates, the best was selected, it passed all quality gates, and the download succeeded at 11.4 MB.

The issue in the BeatDirector is **not** the provider pipeline — it's the `multi_query_search` call parameters. The BeatDirector calls:

```python
self._router.multi_query_search(
    [query], min_acceptable_score=0.0, max_attempts=1,
    diversity_weighting=0.15, target_duration=max(shot.duration, 3.0),
)
```

The `max_attempts=1` limits each `multi_query_search` call to a single provider attempt. The `space` route is `["nasa", "pexels", "pixabay", "wikimedia"]`. With `max_attempts=1`:
- Call 1: Query = `shot_query` → tries NASA (0 results, 1 attempt used) → **returns empty, never reaches Pexels**
- Call 2: Query = `base_query` → tries NASA (0 results, 1 attempt used) → **returns empty**
- Call 3: Query = `topic footage` → tries NASA (0 results, 1 attempt used) → **returns empty**
- **All 3 queries exhausted with 0 results** → falls through to FallbackDirector

The same query sent directly to `prov.search()` bypasses `multi_query_search`'s attempt counter and reaches Pexels immediately.

**The first failing component is `AssetRouter.multi_query_search` because `max_attempts=1` exhausts the attempt budget on NASA's empty result before reaching Pexels, even though Pexels would return 10 valid candidates.**

---

**The first failing component is `AssetRouter.multi_query_search` with `max_attempts=1` because NASA consumes the single attempt budget on a query where it has zero relevant results, preventing Pexels from ever being searched for that same query.**
