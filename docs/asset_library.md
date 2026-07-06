# Asset Library — video_engine

## Overview

The **Asset Library** is a local-first lookup layer that sits between the
orchestrator and external asset providers (Pexels).  Its goal is to reuse
previously downloaded assets before making new API calls, which:

- **Reduces Pexels API usage** — fewer calls means lower costs and less risk
  of hitting rate limits.
- **Improves rendering speed** — reusing a local file is instant compared to
  downloading.
- **Improves visual consistency** — videos built from overlapping queries
  naturally reuse high-quality clips, giving a more coherent look.
- **Avoids duplicate downloads** — the same asset is never downloaded twice.

---

## Lookup Flow

```
Caller (orchestrator)
       │
       ▼
AssetLibrary.search(query)
       │
       ├── [reuse enabled] → _lookup_similar(query)
       │       │
       │       ├── match found (similarity ≥ threshold)
       │       │       └── return cached result   ← NO provider call
       │       │
       │       └── no match (similarity < threshold)
       │               └── fall through ↓
       │
       └── PexelsProvider.search(query)
               │
               └── download(url) → AssetLibrary.download()
                                        │
                                        └── _index_asset()   ← auto-index
```

### Key decision points

1. **Reuse enabled?** — Configurable via `providers.pexels.reuse.enabled`.
   When `false`, every search goes directly to the external provider.
2. **Similarity threshold** — Configurable Jaccard threshold (see below).
   Only cached entries whose keyword overlap exceeds this value are reused.
3. **File still exists on disk?** — Even if the database says an asset exists,
   the library verifies the file is present before returning it.

---

## Similarity Algorithm

The library uses **Jaccard similarity** on keyword tokens:

1. Normalise both queries: lowercase, strip whitespace, split into tokens.
2. Compute:

   ```
   similarity = |tokens(query₁) ∩ tokens(query₂)|
               ──────────────────────────────────
               |tokens(query₁) ∪ tokens(query₂)|
   ```

   where ∩ is set intersection and ∪ is set union.

3. If `similarity ≥ threshold` (default 0.45), the cached entry is a match.
4. Among all matches, the entry with the **highest similarity** is returned.

### Example

| Indexed query | New query | Jaccard | Match? (≥ 0.45) |
|---|---|---|---|
| `deep space galaxy` | `deep space galaxy` | 1.000 | Yes |
| `milky way galaxy` | `milky way stars` | 0.500 | Yes |
| `deep space galaxy` | `space galaxy nebula` | 0.667 | Yes |
| `deep space galaxy` | `cat dog fish` | 0.000 | No |

---

## Configuration

Added to `configs/providers.yaml` under `providers.pexels.reuse`:

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Enable local-first lookup |
| `similarity_threshold` | `0.45` | Minimum Jaccard score for reuse |
| `max_candidates` | `5` | Max cached entries to consider when evaluating candidates |

---

## Indexing

Indexing happens **automatically** on every download through `AssetLibrary.download()`.

- The indexed query is the **last search query** that preceded the download.
- The cache uses `provider="asset_library"` and `search_query=<normalized>` as
  the primary key, keeping each query indexed exactly once (upsert).
- Files are stored under `cache/video/` per the existing pipeline cache layout.

### What about direct PexelsProvider usage?

When the orchestrator uses `AssetLibrary` (which wraps `PexelsProvider`), every
download is automatically indexed.  If `PexelsProvider` is used directly
(bypassing the library), indexing does **not** occur — the library only intercepts
calls made through its own `search()` and `download()` methods.

---

## Future Embedding Support

The similarity algorithm is intentionally isolated in the
`AssetLibrary._lookup_similar()` method.  To switch to embedding-based vector
search:

1. Replace `_keyword_similarity()` with a call to an embedding model (e.g.
   `text-embedding-3-small` from OpenAI or `models/text-embedding-004` from
   Gemini).
2. Store embedding vectors alongside each cached entry (e.g. as a new column
   in the `assets` table or a separate vector store).
3. Replace the Jaccard scoring loop with a cosine-similarity search.

The public interface (`search()`, `download()`) and the orchestrator code
require **no changes** — only `_lookup_similar()` needs updating.

---

## Test Strategy

| Test area | What it verifies |
|---|---|
| **Similarity** | Tokenisation, Jaccard computation, edge cases (empty, single token) |
| **Exact reuse** | Same query → cache hit on second call |
| **Partial reuse** | Overlapping keywords → cache hit above threshold |
| **Cache miss** | No overlap → provider called; deleted file → provider called |
| **Disabled reuse** | Every search goes to provider; no indexing |
| **Download** | Delegation, auto-indexing, deduplication (upsert) |
| **Config** | Constructor overrides, YAML defaults |
| **Provider fallback** | Errors propagate from the backing provider |
