# Pixabay Video Provider

## Overview

The `PixabayProvider` integrates the [Pixabay Video API](https://pixabay.com/api/docs/#api_videos_search) into the video engine's asset pipeline. It sits alongside the existing `PexelsProvider` as a fully functional, production-ready asset source.

Unlike stubs (NASA, Wikimedia), the `PixabayProvider` performs real API searches, downloads videos, caches results, and participates in deterministic quality scoring — exactly like `PexelsProvider`.

## Architecture

```
Pixabay API
    │
    ▼
PixabayProvider.search(query)
    │
    ├── 1. Check AssetCache (provider="pixabay")
    ├── 2. API call to pixabay.com → hits[]
    ├── 3. Normalise hits → internal asset model
    ├── 4. Score via PexelsProvider._score_candidates()
    ├── 5. Return scored, sorted results
    │
    ▼
PixabayProvider.download(url, path)
    │
    ├── 1. Skip if file exists
    ├── 2. Download via requests.get()
    ├── 3. Update AssetCache with local path
    │
    ▼
AssetRouter
    │
    ├── pixabay is wrapped in AssetLibrary
    └── Tried before Pexels (when configured)
```

## Configuration

### API Key

Set the `PIXABAY_API_KEY` environment variable:

```bash
export PIXABAY_API_KEY="your_pixabay_api_key"
```

When the key is absent, `PixabayProvider.search()` returns an empty list and the `AssetRouter` silently falls back to the next provider (Pexels).

### YAML Configuration

In `configs/providers.yaml`:

```yaml
providers:
  pixabay:
    # Pixabay video search API endpoint
    base_url: "https://pixabay.com/api/videos"

    # Results per page
    per_page: 10

    # Orientation filter: "horizontal", "vertical", or "all"
    orientation: "horizontal"

    # Minimum video width (px) — filters out low-res content
    min_width: 1920

    # Safe search: "true" or "false"
    safesearch: "true"
```

### Routing

The `AssetRouter` includes Pixabay in the priority chain for every category:

| Category | Provider Priority                   |
|----------|--------------------------------------|
| Space    | NASA (stub) → **Pixabay** → Pexels  |
| History  | Wikimedia (stub) → **Pixabay** → Pexels |
| Science  | NASA (stub) → **Pixabay** → Pexels  |
| Nature   | **Pixabay** → Pexels                 |
| Tech     | **Pixabay** → Pexels                 |
| Finance  | **Pixabay** → Pexels                 |
| General  | **Pixabay** → Pexels                 |

Pixabay is wrapped in `AssetLibrary`, so locally cached assets are reused before any API call is made.

## Data Normalisation

Pixabay's API response differs from Pexels. Each hit is normalised to match the internal asset model:

### Pixabay raw hit:
```json
{
  "id": 12345,
  "duration": 10,
  "tags": "nature, forest",
  "videos": {
    "large": {"url": "...", "width": 1920, "height": 1080},
    "medium": {"url": "...", "width": 1280, "height": 720},
    "small": {"url": "...", "width": 640, "height": 360}
  }
}
```

### Normalised output:
```json
{
  "id": 12345,
  "width": 1920,
  "height": 1080,
  "duration": 10,
  "video_files": [
    {"link": "...large.mp4", "quality": "hd"},
    {"link": "...medium.mp4", "quality": "sd"},
    {"link": "...small.mp4", "quality": "sd"}
  ],
  "_raw": {
    "tags": "nature, forest",
    "views": 5000,
    "downloads": 200,
    "user": "username"
  }
}
```

The `_raw` field preserves original metadata for debugging while the rest of the pipeline sees a Pexels-compatible structure.

## Scoring

Pixabay assets use the **identical scoring formula** as Pexels, via `PexelsProvider._score_candidates()`:

- **Resolution (40%)** — pixel area normalised to 1920×1080
- **Duration match (40%)** — how closely the clip duration matches the target
- **HD bonus (20%)** — presence of a "large" (HD-capable) tier

This ensures fair comparison regardless of which provider supplies the asset.

## Caching

PixabayProvider uses the same `AssetCache` as Pexels, with `provider="pixabay"` as the cache key prefix:

- `Cache lookup(provider="pixabay", query)` — reuse previously downloaded assets
- `Cache register(provider="pixabay", query, url)` — pre-register on search
- `Cache update_local_path(provider="pixabay", query, url, path)` — record download
- `Cache touch(provider="pixabay", query)` — refresh LRU timestamp

Pixabay is also wrapped in `AssetLibrary` via the `AssetRouter`, enabling cross-video reuse of downloaded assets.

## Fallback Behaviour

When `PixabayProvider` fails (API error, empty results, no API key), the `AssetRouter` automatically falls through to Pexels. The pipeline never blocks on a Pixabay failure.

| Condition                     | Behaviour                      |
|-------------------------------|--------------------------------|
| No API key                    | Returns [] → fallback to Pexels |
| API returns empty `hits[]`    | Returns [] → fallback to Pexels |
| API connection error          | Returns [] → fallback to Pexels |
| API rate limit exceeded       | Returns [] → fallback to Pexels |
| Normal results                | Returns scored assets           |

## Extending

To add additional Pixabay features:

1. **Quality tier filter** — Add a `min_quality` config that prefers "large" videos
2. **Category filter** — Pixabay's API supports `category` param for curated content
3. **Editors' choice** — The `editors_choice=true` param returns curated picks
4. **Video type** — Support `video_type=film` or `video_type=animation` filtering

All additions go in `PixabayProvider.search()` without changing the public interface.
