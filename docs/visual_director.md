# Visual Director Architecture

## Overview

The Visual Director replaces the pipeline's linear stock-footage retrieval
with a closed-loop, director-driven system. Every stage can reject, repair,
and regenerate outputs until hard quality gates are satisfied.

The objective is to evolve from a linear retrieval pipeline into a
director-driven, self-correcting documentary generation system.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Visual Director                      │
│                                                         │
│  ┌──────────────┐   ┌──────────────────┐                │
│  │  VisualStyle  │   │  ConceptPlanner   │                │
│  │  (global)     │──▶│  (per scene)      │                │
│  └──────────────┘   └────────┬─────────┘                │
│                              │                          │
│                              ▼                          │
│  ┌──────────────────────────────────┐                   │
│  │         AssetRouter              │                   │
│  │  (multi-query, multi-provider)   │                   │
│  └────────────┬─────────────────────┘                   │
│               │                                         │
│               ▼                                         │
│  ┌──────────────────────────────────┐                   │
│  │   SemanticValidator (0.75 gate)   │                   │
│  │   ┌───────────────────────────┐  │                   │
│  │   │ Reject → retry next query │  │                   │
│  │   │ All exhausted → regenerate│  │                   │
│  │   └───────────────────────────┘  │                   │
│  └────────────┬─────────────────────┘                   │
│               │                                         │
│               ▼                                         │
│  ┌──────────────────────────────────┐                   │
│  │    Aesthetic Consistency Agent   │                   │
│  │  Detects & prevents style breaks │                   │
│  └────────────┬─────────────────────┘                   │
│               │                                         │
│               ▼                                         │
│  ┌──────────────────────────────────┐                   │
│  │        Hard Quality Gates        │                   │
│  │  ┌────────┐ ┌───────┐ ┌───────┐ │                   │
│  │  │Semantic│ │Reuse  │ │Aesth. │ │                   │
│  │  │>= 0.75 │ │check  │ │check  │ │                   │
│  │  └────────┘ └───────┘ └───────┘ │                   │
│  └────────────┬─────────────────────┘                   │
│               │                                         │
│               ▼                                         │
│         ┌──────────┐                                    │
│         │ ACCEPTED │──▶ Scene added to timeline         │
│         └──────────┘                                    │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. VisualStyle (`src/director/visual_style.py`)

Global visual identity created once before scene generation. Defines:
- **aesthetic**: `photorealistic` | `cinematic` | `documentary` | `archival` | `space` | `educational`
- **sub_aesthetic**: Refinement (e.g. `space`, `historical`)
- **color_palette**: Suggested hex colours for grading
- **mood**: `bright` | `dramatic` | `neutral` | `mysterious` | `warm`
- **pace**: `fast` | `medium` | `slow`
- **provider_prefs**: Preferred provider priority for this style

**Creation:**
```python
style = VisualStyle.for_topic("The Fermi Paradox", "Space")
# aesthetic="space", mood="mysterious", pace="slow"
```

**Style→topic mapping** (config: `visual_director.aesthetic_mapping`):
| Category    | Style           |
|-------------|-----------------|
| Space       | space           |
| History     | archival        |
| Science     | photorealistic  |
| Nature      | photorealistic  |
| Technology  | cinematic       |
| Finance     | educational     |
| General     | documentary     |

### 2. ConceptPlanner (`src/director/concept_planer.py`)

Replaces literal keyword-based query generation with concept-driven visual
planning. Generates search queries targeting:
- Visual metaphors for abstract concepts
- Scientific phenomena visualisations
- Cinematic compositions
- Diverse perspectives (wide, close-up, aerial, detail)

**Example:** For "gravitational waves ripple through spacetime":
```
Old: "gravitational waves spacetime ripple"
New: ["interferometer laser beams", "fabric of space distortion",
      "particle collision simulation", "ripple on water surface",
      "Einstein thought experiment"]
```

### 3. SemanticValidator (`src/validation/semantic_validator.py`)

**Authoritative gate** — assets below threshold (default `0.75`) are
HARD REJECTED. The pipeline must find an alternative.

When LLM is available, uses a prompt to score relevance. Falls back to
keyword-overlap heuristic.

### 4. AestheticAgent (`src/director/aesthetic_agent.py`)

Tracks the visual style category of every selected asset and detects
incompatible transitions:
- `real_drone` + `historic_image` → compatible
- `historic_image` + `cgi_render` → incompatible
- `space_photo` + `infographic` → incompatible

Style classification uses provider, query, tags, and category metadata.

### 5. QualityGates (`src/director/quality_gate.py`)

Four hard gates that all assets must pass:

| Gate       | Condition                                |
|------------|------------------------------------------|
| Semantic   | `semantic_score >= 0.75`                 |
| Aesthetic  | Style compatible with recent history     |
| Reuse      | Same URL/id not used in last 5 scenes    |
| Duplicate  | Not visually identical to recent assets  |

If any gate fails, the pipeline retries the next query. If all queries
exhausted, the scene narration is regenerated via LLM. If regeneration
also fails, a warning is logged and the best available asset is used.

### 6. VisualDirector (`src/director/director.py`)

Orchestrates all components in a closed loop:

```python
director = VisualDirector(topic, llm_provider, scene_data)
scene_assets = director.run()
```

For each scene:
1. ConceptPlanner generates 5-10 concept-driven queries
2. AssetRouter searches each query through provider chain
3. SemanticValidator scores at 0.75 threshold
4. AestheticAgent checks style consistency
5. QualityGates enforce all gates
6. If rejected → retry next query
7. If exhausted → regenerate narration
8. If all retries exhausted → fallback with warning

## Critic Fail-Closed

The multimodal critic now fails closed:
- **All errors** (quota, auth, config, API) set `approved = False`
- Resource exhaustion: retries with exponential backoff (2s, 4s, 8s)
- No "auto-approve on failure" paths remain

## Files Created
- `src/director/__init__.py` — Director package
- `src/director/visual_style.py` — VisualStyle definition
- `src/director/concept_planner.py` — Concept-driven search planner
- `src/director/aesthetic_agent.py` — Aesthetic consistency checker
- `src/director/quality_gate.py` — Hard quality gates
- `src/director/director.py` — VisualDirector orchestrator
- `configs/visual_director.yaml` — Director configuration
- `docs/visual_director.md` — This document

## Files Modified
- `orchestrator.py` — execution_node uses VisualDirector; critic fail-closed
- `src/validation/semantic_validator.py` — Default threshold 0.75, authoritative
- `src/providers/stubs.py` — Removed stub classes (all providers are real)
- `src/providers/__init__.py` — Import real NasaMedia/Wikimedia from asset_provider
- `src/assets/asset_router.py` — Import real providers, `_is_provider_ready()` check
- `src/assets/asset_library.py` — Clip diversity tracking

## Key Changes from Previous Architecture

| Previous                    | Now                              |
|-----------------------------|----------------------------------|
| Linear retrieval pipeline   | Closed-loop director             |
| Semantic validation logs    | Semantic validation rejects      |
| 0.5 threshold               | 0.75 hard gate                   |
| Literal keyword queries     | Concept-driven visual queries    |
| No style tracking           | Global VisualStyle per video     |
| No style consistency        | AestheticAgent prevents breaks   |
| Critic fails open           | Critic fails closed              |
| Stub providers used         | All real providers (NASA, Wiki)  |
| No quality gates            | 4 hard gates (semantic/reuse/aesthetic/duplicate) |
| Single-pass asset fetch     | Retry → regenerate → fallback    |
