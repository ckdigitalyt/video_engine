# Search Planner — Multi-Query Asset Search

## Overview

The **SearchPlanner** generates multiple visually diverse search queries
per scene instead of relying on a single literal search phrase.  The
AssetRouter evaluates these queries one by one, stopping on the first
sufficiently high-quality result.  This improves visual relevance and
reduces the chance of poor-looking placeholder assets.

## Architecture

```
┌─────────────────────────┐
│     Scene Narration     │
│     Scene Title         │
│     Video Topic         │
│     Scene Purpose       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│     SearchPlanner       │
│  (LLM or keyword-fb)    │
│                         │
│  Generates 5–10 diverse │
│  search queries per     │
│  scene                  │
└────────┬────────────────┘
         │ queries[]
         ▼
┌─────────────────────────┐
│     AssetRouter         │
│  .multi_query_search()  │
│                         │
│  Tries each query       │
│  through provider chain │
│  Stops on first result  │
│  ≥ min_acceptable_score │
└────────┬────────────────┘
         │ best asset
         ▼
┌─────────────────────────┐
│     Download + Cache    │
└─────────────────────────┘
```

## Configuration

All settings live in `configs/search_planner.yaml`:

```yaml
search_planner:
  num_queries: 7            # Queries generated per scene
  min_acceptable_score: 0.75 # Stop searching when quality ≥ this
  max_provider_attempts: 15  # Total API calls across all queries
  diversity_weighting: 0.2   # Bonus for diverse assets (0–1)
```

## Components

### `SearchPlanner` (src/assets/search_planner.py)

**Public methods:**

| Method | Description |
|--------|-------------|
| `generate_queries(narration, title, topic, purpose)` | Returns 5–10 diverse queries |

**LLM-based generation:**

When an `LLMProvider` is configured, the planner sends a structured prompt
requesting visually distinct search queries optimized for stock footage
libraries.  The prompt specifies:

- Concrete, searchable elements (locations, objects, actions)
- Mix of wide shots, close-ups, aerial views, slow-motion
- Landscape compositions
- No abstract concepts or metaphors

**Fallback (no LLM):**

When no provider is available, the planner extracts keywords from the
narration and combines them with visual descriptor templates:

- `{keyword} wide angle`
- `{keyword} close up`
- `{keyword} aerial view`
- `{keyword} slow motion`
- `{keyword} cinematic`
- `{keyword} landscape`
- `{keyword} time lapse`

### `AssetRouter.multi_query_search()` (src/assets/asset_router.py)

Processes queries in order:

1. For each query, search providers in category priority order
2. Score the best result using the same formula as `PexelsProvider`
3. If score ≥ `min_acceptable_score` → return immediately (early exit)
4. Otherwise track the best score and continue to next query
5. After all queries, return the highest-scoring result

**Diversity bonus:** When no early exit occurs, the final selection applies
a small diversity bonus (configurable via `diversity_weighting`) to prefer
visually different assets.

**Logging:** Every scene logs:
- All queries tried
- Provider status per query
- Selected provider and query
- Reason (score)

## Extension Points

**Adding an embedding-based diversity scorer:**

```python
class SemanticDiversityScorer:
    def score(query, asset_embeddings, existing_embeddings):
        return cosine_distance between embedding sets
```

The `_diversity_bonus()` method on `AssetRouter` is designed to be swapped
with a semantic/embedding-based implementation without changing the calling
signature.

**Adding new visual descriptors for fallback:**

Edit `_FALLBACK_TEMPLATES` in `src/assets/search_planner.py`:

```python
_FALLBACK_TEMPLATES = [
    "{kw} wide angle",
    "{kw} close up",
    # Add more templates here
]
```

**Using a different LLM provider:**

The `SearchPlanner` accepts any `LLMProvider` implementation:

```python
planner = SearchPlanner(provider=gemini)
queries = planner.generate_queries(narration, title=topic, topic=video_topic)
```

## Integration

The SearchPlanner is instantiated in the orchestrator's `execution_node`
and called once per scene before the asset search loop:

```python
search_planner = SearchPlanner(provider=zai)

for scene_data in scenes_data:
    queries = search_planner.generate_queries(
        narration=scene.narration,
        title=scene_data.get("scene_title", ""),
        topic=topic,
        purpose=scene_data.get("purpose", "general"),
    )
    mq_result = router.multi_query_search(queries, ...)
    videos = mq_result["assets"]
```

No changes are required to the planner, renderer, or provider interfaces.
