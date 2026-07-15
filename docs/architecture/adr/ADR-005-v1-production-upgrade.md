# ADR-005: Video Engine v1.0 Production Upgrade

**Date:** 2026-07-15
**Status:** Proposed

## Context

The video engine pipeline successfully generates documentary videos end-to-end (scripting, narration, asset retrieval, rendering), but visual quality is below production standards. Asset retrieval is keyword-driven, has no visual critic, uses basic caching, and produces outputs with blank frames, fallback clips, and inconsistent transitions.

## Decision

Upgrade the engine in 17 incremental phases on the `jade` branch, each with its own ADR, unit tests, and validation, before merging to `main`.

| Phase | Component | Priority |
|---|---|---|
| 1 | Semantic Asset Retrieval | High |
| 2 | VisualIntentPlanner | High |
| 3 | Hierarchical Search Tree | High |
| 4 | Multi-provider Scoring | High |
| 5 | Project-Isolated Caching | High |
| 6 | Asset Validation Pipeline | Medium |
| 7 | Result\<T\> Error Handling | High |
| 8 | LLM Visual Critic | Medium |
| 9 | Scene Diversity / VisualMemory | Medium |
| 10 | Manim Integration | Medium |
| 11 | Storyboard Planning | Medium |
| 12 | Better Transitions | Low |
| 13 | Documentary B-roll Taxonomy | Low |
| 14 | Telemetry Dashboard | Medium |
| 15 | Production Quality Gates | High |
| 16 | Module Architecture Refactor | High |
| 17 | Final Acceptance | High |

## Consequences

- Every phase includes an ADR, implementation, tests, and validation
- The pipeline remains functional after each phase
- Only merge to main after all 17 phases pass quality gates
