# ADR-007: Module Architecture Refactor

**Date:** 2026-07-15
**Status:** Implemented

## Context

All new modules (Phases 1-15) were added to existing packages. This creates an
inconsistent structure with mixed responsibilities. We need clean module
boundaries with single responsibilities, unit tests, structured logs, and metrics.

## Decision

Create `src/v1/` package as the canonical module tree. Each module has:
- Single responsibility
- Unit tests
- Structured logging
- Metrics via TelemetryCollector
- No hidden side effects

## Module Map

```
src/v1/
  __init__.py
  visual_intent_planner.py   — Phase 2: VisualIntent from narration
  storyboard_planner.py       — Phase 11: Storyboard before retrieval
  semantic_query_planner.py   — Phase 1: Semantic query generation
  search_tree.py              — Phase 3: Hierarchical search
  provider_router.py          — Phase 3: Exhaust all providers
  candidate_collector.py      — Phase 4: Collect from all sources
  asset_ranker.py             — Phase 4: Score and rank candidates
  semantic_validator.py       — Phase 1: Validate semantic match
  visual_critic.py            — Phase 8: LLM visual scoring
  asset_validator.py          — Phase 6: Pre-render validation
  duplicate_detector.py       — Phase 9: Scene diversity
  manim_planner.py            — Phase 10: Scientific animation
  transition_planner.py       — Phase 12: Context-aware transitions
  telemetry_collector.py      — Phase 14: Pipeline metrics
  quality_gate.py             — Phase 15: Release gates
  project_cache.py            — Phase 5: Project isolation
  broll_taxonomy.py           — Phase 13: Documentary taxonomy
  result.py                   — Phase 7: Result<T> type
```

## Consequences

- Clear import paths (`from src.v1.asset_ranker import AssetRanker`)
- Each module has exactly one job
- Easy to unit test in isolation
- Existing `src/` modules remain as deprecated wrappers
