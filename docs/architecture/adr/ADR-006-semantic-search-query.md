# ADR-006: Semantic Search Query Generation

**Date:** 2026-07-15
**Status:** Implemented

## Context

Asset retrieval is keyword-driven: LLM extracts literal terms from narration, feeds them to providers. This produces mismatches like searching for "Fermi" or "Frank Drake" (people names) instead of "scientists discussing around conference table".

## Decision

Replace keyword extraction with semantic query generation. A new `SemanticQueryPlanner` module:

1. Takes narration text
2. Extracts the **scene meaning** — what the viewer should *see*
3. Generates search queries describing **visible objects, locations, phenomena**
4. Applies explicit filters: never search for person names, metaphors, verbs, emotion words

**Search rules:**
- ✅ Visible objects, locations, phenomena, scientific equipment, natural events, animations
- ❌ Person names, metaphors, verbs, emotion words

**Module:** `src/assets/semantic_query_planner.py`
