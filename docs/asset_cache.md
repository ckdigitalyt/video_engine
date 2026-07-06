# Asset Cache

The **Asset Cache** (`src/assets/asset_cache.py`) is a managed SQLite-backed
cache for downloaded media assets.  It prevents redundant API calls and
downloads by recording previous search results and their local file paths.

---

## Schema

The cache uses a single table `assets`:

```
assets
─────────────────────────────────────────────────────
 provider      TEXT  NOT NULL  — e.g. "pexels"
 search_query  TEXT  NOT NULL  — the search string
 asset_url     TEXT  NOT NULL  — original remote URL
 local_path    TEXT            — file path on disk
 use_count     INTEGER        — times this asset was used
 last_used     REAL           — unix timestamp of last access
 created_at    REAL           — unix timestamp of creation

 PRIMARY KEY (provider, search_query)
 INDEX idx_assets_url (asset_url)
 INDEX idx_assets_last_used (last_used)
```

Each (provider, query) pair has at most one row — repeated searches for the
same term simply reuse the cached entry.

---

## Lookup Flow

```
search(query)
    │
    ├─ cache.lookup(provider, query)
    │     │
    │     ├─ HIT + file exists → return cached asset_url immediately
    │     │                        (skip API call entirely)
    │     │
    │     └─ MISS → call provider API
    │                  │
    │                  └─ register(provider, query, url)
    │                        (record the URL; local_path is still None)
    │
    └─ return result list to orchestrator

download(url, output_path)
    │
    ├─ output_path already exists → touch cache, return
    │
    └─ download from URL → save to output_path
         │
         └─ update_local_path(url, output_path)
               (fills in local_path so future lookups resolve fully)
```

### Cache Hit

When a search query matches an existing cache entry **and** the local file
still exists on disk, the orchestrator receives a mock response that contains
the cached `asset_url`.  The subsequent `download()` call finds the file
already present and skips the download.  The `use_count` and `last_used`
timestamp are updated.

### Cache Miss

The provider calls the external API, pre-registers the first result URL in the
cache, and returns the full result list.  When `download()` completes, the
cache row is updated with the real `local_path`.

---

## Cleanup Policy

The cache enforces an LRU (least-recently-used) eviction policy.

| Config key | Default | Description |
|------------|---------|-------------|
| `pipeline.cache_db` | `"cache/asset_cache.db"` | SQLite database file path |
| `pipeline.cache_max_size_mb` | `500` | Maximum total on-disk size for cached files (MB) |

`AssetCache.cleanup()` performs the following:

1. List all cached files ordered by `last_used ASC` (oldest first).
2. Sum their on-disk sizes.
3. If the total exceeds `max_size_mb`, delete the oldest files (and their
   database rows) until the total is under the limit.

Call `cleanup()` periodically (e.g. after each pipeline run) to keep the cache
within budget.  It returns the number of files deleted.

---

## Usage

```python
from src.assets.asset_cache import AssetCache

cache = AssetCache()
result = cache.lookup("pexels", "milky way galaxy")
if result:
    print(f"Cached at {result['local_path']}")
else:
    cache.register("pexels", "milky way galaxy", "https://...")
```

Providers that receive a `cache` argument will share the same database:

```python
from src.assets.asset_cache import AssetCache
from src.providers import PexelsProvider

shared_cache = AssetCache()
pexels = PexelsProvider(cache=shared_cache)
```

---

## Future Provider Support

The cache is provider-agnostic — any future provider (NASA, Pixabay, etc.)
can use the same cache simply by using its own `provider` string:

```python
# Future: Pixabay
cache.register("pixabay", query, asset_url, local_path)
cached = cache.lookup("pixabay", query)
```

| Provider | Cache key prefix |
|----------|------------------|
| Pexels   | `"pexels"`       |
| NASA     | `"nasa"` (future)|
| Pixabay  | `"pixabay"` (future) |

No schema changes are needed — the `provider` column already partitions the
namespace.
