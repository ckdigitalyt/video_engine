# Visual Quality V1

## Overview

Visual Quality V1 is a coordinated set of improvements across the pipeline
that transforms the output from a simple sequence of stock clips into
coherent, human-edited-looking videos.  Each component is independently
configurable and preserves backward compatibility.

## Components (Priority Order)

### 1. Semantic Asset Validation

**File:** `src/validation/semantic_validator.py`

After the `AssetRouter` selects a candidate via technical scoring, the
`SemanticValidator` scores the asset for semantic relevance to the scene
narration.  If the score is below the configured threshold, the pipeline
retries with the next search query.

**Pipeline:**
```
Search queries → retrieve candidates → technical scoring
→ semantic validation → final asset
```

**LLM-based scoring:** Uses the `ZaiProvider` to evaluate whether
the asset matches the narration's subject, context, and mood.

**Fallback scoring:** When no LLM is available, a deterministic
keyword-overlap heuristic compares narration tokens against query +
tag tokens.

**Configuration** (`configs/visual_quality.yaml`):
```yaml
semantic_validation:
  enabled: true
  threshold: 0.5    # Minimum relevance score (0-1)
  max_attempts: 5   # Max retries per scene
```

### 2. Video Duration Verification

**File:** `src/utils/duration.py`

Ensures every video clip is at least as long as its audio narration.
Before rendering, the orchestrator verifies:

```
video_duration >= voice_duration
```

**Auto-fix (in priority order):**
1. Loop the video (preferred, configurable)
2. Slow the video within limits (max_speed_change: 1.5x)

Never allows black frames or missing video.

**Configuration** (`configs/visual_quality.yaml`):
```yaml
duration_verification:
  enabled: true
  max_speed_change: 1.5
  prefer_loop: true
```

### 3. Clip Diversity

**File:** `src/assets/asset_library.py` (extended)

The `AssetLibrary` now tracks recently used assets and search queries.
When considering whether to reuse a cached asset, it applies a penalty
if:

- Same asset URL was used within the last N scenes (`repeat_penalty: 0.3`)
- Same search query was used recently (`query_repeat_penalty: 0.15`)

If the adjusted score falls below the similarity threshold, the library
delegates to the external provider for a fresh asset.

**Configuration** (`configs/visual_quality.yaml`):
```yaml
clip_diversity:
  enabled: true
  recent_window: 5
  repeat_penalty: 0.3
  query_repeat_penalty: 0.15
```

### 4. History Mode (Wikimedia Commons)

**File:** `src/providers/asset_provider.py` — `WikimediaCommonsProvider`

For the History category, the pipeline prefers public-domain historical
images from Wikimedia Commons instead of generic stock videos.

- Searches `https://commons.wikimedia.org/w/api.php` for images
- Returns normalised assets with `_image: true` flag
- Renderer automatically applies Ken Burns slow zoom/pan to still images
- Falls back to Pixabay → Pexels when no suitable image is found

**Routing** (in `configs/providers.yaml`):
```yaml
History: [wikimedia, pixabay, pexels]
```

### 5. Space Mode (NASA Provider)

**File:** `src/providers/asset_provider.py` — `NasaMediaProvider`

Real NASA Image and Video Library API implementation.

- Searches `https://images-api.nasa.gov/search`
- Requires `NASA_API_KEY` env var (uses `DEMO_KEY` for limited access)
- Returns video assets from NASA's public media library
- Falls back to Pixabay → Pexels

**Routing:** `Space: [nasa, pixabay, pexels]`

### 6. Smart Transitions

**File:** `src/effects/transitions.py` — `TransitionEngine.generate_smart()`

The default transition is never "none".  The engine selects transitions
based on scene context:

| Condition | Transition |
|-----------|-----------|
| Same topic category | `cut` (fast pacing) |
| Same provider, different query | `dissolve` |
| New topic / different category | `fade` (new idea) |
| Same asset reused | `dissolve` |

**Configuration** (`configs/visual_quality.yaml`):
```yaml
smart_transitions:
  enabled: true
  same_topic_default: "cut"
  same_provider_default: "dissolve"
  new_idea_default: "fade"
```

### 7. Extended Evaluation Metrics

**File:** `src/evaluator/metrics.py` — `EvalSnapshot`

New metrics collected:

| Metric | Description |
|--------|-------------|
| `semantic_score_avg` | Average semantic relevance score across scenes |
| `asset_diversity_penalties_applied` | Number of times a reuse was skipped for diversity |
| `provider_usage` | Dict mapping provider name to call count |
| `asset_reuse_percentage` | Percentage of assets reused from cache |
| `avg_clip_length_s` | Average video clip length in seconds |
| `avg_transition_duration_s` | Average transition duration in seconds |
| `duration_adjustments` | Number of videos looped/slowed to match audio |

## Files Created
- `src/validation/__init__.py` — Validation package
- `src/validation/semantic_validator.py` — SemanticValidator class
- `src/utils/duration.py` — Duration verification utilities
- `configs/visual_quality.yaml` — All V1 configuration
- `docs/visual_quality_v1.md` — This document

## Files Modified
- `src/providers/asset_provider.py` — Added NasaMediaProvider, WikimediaCommonsProvider
- `src/assets/asset_router.py` — Wrapped real providers in AssetLibrary
- `src/assets/asset_library.py` — Added clip diversity tracking
- `src/effects/transitions.py` — Added smart transition selection
- `src/evaluator/metrics.py` — Extended EvalSnapshot with V1 metrics
- `orchestrator.py` — Integrated semantic validation, duration verification

## Extension Points

**Adding a new semantic scorer:**
```python
class MyScorer:
    def score(self, narration, asset) -> float:
        return my_custom_score
```

**Adding a new transition rule:**
Add conditions to `TransitionEngine._pick_smart()`.

**Adding a new provider:**
1. Implement `AssetProvider` interface
2. Add route in `configs/providers.yaml`
3. Instantiate in `AssetRouter._default_providers()`
