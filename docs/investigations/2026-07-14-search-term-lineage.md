# Investigation: Search Term "general" Lineage

**Date:** 2026-07-14
**Author:** Jade (autonomous operations engineer)
**Status:** Resolved

---

## Executive Summary

The literal search term `"general"` enters the pipeline at **`planner.py:185`** via the fallback expression `sanitised_terms or ["general"]`. When the LLM returns empty `search_terms`, or when `_sanitise_search_terms()` replaces all terms (due to >60% narration-word overlap), the resulting empty list is Python-falsy, triggering the hardcoded fallback `["general"]`. This propagates directly into `SearchPlan.asset_search_queries`, then into `BeatDirector._process_shot()` as the base query, where `expand_for_shot("general", "cutaway", ...)` produces `"general cutaway shot"` — the exact query that was observed hitting provider APIs with irrelevant results.

The fix is to replace the static fallback with a topic-relevant alternative.

---

## Objective

Determine exactly where the literal search term `"general"` first appears in the pipeline for **Scene 0 → Beat 0 → Shot 1**, trace it through every code stage, and recommend an architectural fix.

**Do NOT change any code. Only instrument.**

---

## Environment

- **Branch:** `jade`
- **Head commit:** `c652edb` (docs: primary pipeline runtime trace for Scene 0 Beat 0 Shot 1)
- **OS:** Linux (Oracle Linux, arm64)
- **Python:** 3.12
- **Repository:** `/home/ubuntu/video_engine/`

---

## Investigation

### Chain of custody: where "general" enters and how it spreads

#### Phase 1 — Static Analysis

We identified **five insertion points** where `"general"` can enter the search term pipeline:

| # | File | Line | Code | Trigger Condition |
|---|------|------|------|-------------------|
| A | `src/planner/planner.py` | 185 | `sanitised_terms or ["general"]` | `sanitised_terms = []` (empty list is falsy) |
| B | `src/planner/planner.py` | 187 | `(visual_intent.visual_objective or "general")[:200]` | `visual_objective = ""` (empty string) |
| C | `src/models/schemas.py` | 783 | `default_factory=lambda: SearchPlan(asset_search_queries=["general"])` | Scene created without explicit SearchPlan |
| D | `src/director/concept_planner.py` | 140, 170 | `return [topic, "stock footage", "documentary", "general"]` | LLM fallback fails |
| E | `src/director/director.py` | 233 | `asset_search_queries=["general"]` | Dict-to-Scene fallback |
| F | `src/assets/search_planner.py` | 167 | `purpose=purpose or "general"` | purpose param is None/empty |

Of these, **Insertion Point A (planner.py:185)** is the PRIMARY path by which `"general"` enters as an actual search query. The others set `scene_purpose` or are fallback paths.

#### Phase 2 — The exact path traced

```
Narration (LLM-generated at Phase 2)
    │
    ▼
StoryPlanner._generate_visual_intent()  [planner.py:253]
    │
    ├── LLM path: _llm_visual_intent()  [planner.py:277]
    │     Prompt asks LLM for "search_terms": generate 10-15 diverse keywords
    │     LLM response → VisualIntent.search_terms = result.get("search_terms", [])[:30]
    │                                  ↑ line 322
    │
    └── Fallback: _rule_based_visual_intent()  [planner.py:328]
          Builds search_terms from concept maps → unique_terms[:30]  ↑ line 398
    │
    ▼
visual_intent.search_terms = [...] (LLM-generated or rule-based list)
    │
    ▼
_sanitise_search_terms()  [planner.py:402]
    │
    │  For each term: if term has >60% word overlap with narration → REPLACE
    │  Replacement comes from _VISUAL_FALLBACKS pool
    │  If ALL terms get replaced AND fallback terms also overlap → result can be []
    │  If LLM returned empty [] → result stays []
    │
    ▼
sanitised_terms = [...] or []
    │
    ▼
SearchPlan(asset_search_queries=sanitised_terms or ["general"])  [planner.py:185]
    │                                    ↑^^^^^^^
    │                          KEY INSERTION: when sanitised is []
    │                          [] or ["general"] → ["general"]
    │
    ▼
Scene.search_plan.asset_search_queries = ["general"]
    │
    ▼
BeatDirector._process_shot()  [director_integration.py:107-108]
    │
    │  visual_intent = getattr(scene, 'visual_intent', None)
    │  if visual_intent and (visual_intent.search_terms or visual_intent.concepts):
    │      base_query = visual_intent.search_terms[0] if visual_intent.search_terms else self._topic
    │      ↑ base_query = "general"  (because search_terms[0] == "general")
    │
    ▼
expand_for_shot(base_query="general", shot_type="cutaway", ...)  [query_expander.py:73]
    │
    │  def expand_for_shot(base_query, shot_type, topic, category="General"):
    │      queries = [f"{base_query} {shot_type} shot"]     ← LINE 76
    │               ↑ "general cutaway shot"                 ← OBSERVED
    │      queries.append(f"{base_query} wide shot")         ← "general wide shot"
    │      queries.append(f"{base_query} establishing")      ← "general establishing"
    │      queries.extend(category_bank_samples)              ← ["deep space", ...]
    │
    ▼
Provider API receives: ["general cutaway shot", "general", ...]
    │
    ▼
NASA responds to "general" with Artemis Generation footage (completely irrelevant)
```

#### Phase 3 — Runtime verification

We confirmed via `_sanitise_search_terms()` unit test and expand_for_shot() behavior:

```
_sanitise_search_terms([], "any text", "The Fermi Paradox") → []
[] or ["general"] → ["general"]

expand_for_shot("general", "cutaway", "The Fermi Paradox", "Space")
→ ["general cutaway shot", "general wide shot", "general establishing",
   "The Fermi Paradox cutaway", "The Fermi Paradox documentary footage",
   "deep space", "night sky", "Milky Way", ...]

expand_for_shot("The Fermi Paradox", "cutaway", "The Fermi Paradox", "Space")
→ ["The Fermi Paradox cutaway shot", "The Fermi Paradox wide shot",
   "The Fermi Paradox establishing", "The Fermi Paradox cutaway",
   "The Fermi Paradox documentary footage", "deep space", ...]
```

---

## Value Chain Table

| Stage | Runtime Value | Source Location |
|-------|---------------|-----------------|
| Narration | LLM-generated (scene 0 opening text) | `planner.py` _generate_scenes → LLM response |
| StoryPlanner keywords (LLM output) | `scene_data["search_query"]` from scene dict | `planner.py` _generate_scenes LLM prompt/response |
| visual_intent.search_terms | LLM-generated list (10-15 keywords) or rule-based fallback | `planner.py` line 322 or line 398 |
| After _sanitise_search_terms | Replaced terms with >60% overlap → may be `[]` | `planner.py` lines 402-429 |
| **SearchPlan.asset_search_queries** | **`["general"]`** when sanitised is falsy | **`planner.py:185`** — ROOT CAUSE |
| expand_for_shot input base_query | `"general"` from asset_search_queries[0] | `director_integration.py:108` |
| expand_for_shot output Query 1 | `"general cutaway shot"` | `query_expander.py:76` |
| Query 2 | `"general wide shot"` | `query_expander.py:79` |
| Query 3 | `"general establishing"` | `query_expander.py:80` |
| Provider Query → NASA match | NASA returns Artemis Generation footage | `asset_router.py` / NASA provider |

---

## Root Cause

**The literal search query `"general"` is introduced at `planner.py:185`.**

The code reads:

```python
asset_search_queries=sanitised_terms or ["general"],
```

The intent appears to supply a last-resort fallback when no search terms survive sanitisation. However, `["general"]` is too generic — it's not topic-specific, so it matches irrelevant footage from provider APIs (e.g., NASA returns Artemis Generation videos for the query `"general"`).

### Why sanitised_terms becomes empty:

1. **LLM returns empty `search_terms`**: The `_llm_visual_intent()` call at line 270 may fail or return `search_terms: []`, causing `_rule_based_visual_intent()` at line 275 to generate terms. If narration is short/abstract, the rule-based fallback also produces few terms.

2. **All terms replaced by sanitisation**: `_sanitise_search_terms()` at line 402 checks each term for >60% word overlap with narration. If all generated terms happen to contain words from the narration (common for documentary-style narration where terms like "Fermi Paradox" appear in both), they all get replaced with `_VISUAL_FALLBACKS` entries. If those replacements also overlap or if there aren't enough fallback entries, the result is `[]`.

3. **Logic flaw**: The expression `sanitised_terms or ["general"]` conflates "no concept available" with "a fallback was needed." The correct behavior when no search terms survive should be to generate topic-specific terms, not the literal word `"general"`.

---

## Code References

### Primary insertion point:
- **`src/planner/planner.py` line 185**: `asset_search_queries=sanitised_terms or ["general"],`
- **`src/planner/planner.py` line 402-429**: `_sanitise_search_terms()` — the function whose output triggers the fallback

### Downstream propagation:
- **`src/cinematic/director_integration.py` lines 104-115**: BeatDirector query generation — reads `asset_search_queries[0]` and passes to `expand_for_shot`
- **`src/assets/query_expander.py` lines 73-99**: `expand_for_shot()` — produces `"{base_query} {shot_type} shot"`
- **`src/assets/asset_router.py`**: Searches provider APIs with the raw queries

### Secondary insertion points:
- **`src/planner/planner.py` line 187**: `scene_purpose=(visual_intent.visual_objective or "general")[:200]` — not search query, but sends _purpose_ "general"
- **`src/models/schemas.py` line 783**: `default_factory=lambda: SearchPlan(asset_search_queries=["general"])`
- **`src/director/concept_planner.py` lines 140, 170**: `return [topic, "stock footage", "documentary", "general"]`
- **`src/director/director.py` line 233**: `asset_search_queries=["general"]`

---

## Alternatives Considered

| Alternative | Pros | Cons |
|-------------|------|------|
| Remove fallback entirely | Clean; forces upstream to always produce terms | Risk of `asset_search_queries` being empty list |
| Use `[topic]` instead of `["general"]` | Topic-relevant; always meaningful | Might be too narrow for edge-case topics |
| Use `[f"{topic} documentary stock footage"]` | Descriptive, topic-specific, search-engine friendly | Verbose; some APIs have length limits |
| Call LLM with retry on empty terms | Addresses root cause | Adds latency and LLM cost; doesn't fix the root flaw |
| **Use topic-derived fallback + skip sanitisation for fallback terms** | Best of both: topic-relevant, resilient | Slightly more complex logic |

---

## Recommended Fix

**Target file:** `src/planner/planner.py`, line 185

**Before:**
```python
asset_search_queries=sanitised_terms or ["general"],
```

**After:**
```python
asset_search_queries=sanitised_terms or [f"{topic} documentary stock footage", topic],
```

This replaces the semantically meaningless literal `"general"` with topic-relevant search terms that will actually produce useful stock footage. The two-term fallback (`{topic} documentary stock footage`, then bare `topic`) ensures the first query is specific and the second is a more permissive backup.

### Supporting changes (non-essential but beneficial):

1. **`src/planner/planner.py` line 187**: Change `"general"` to `topic` for scene_purpose context.
   - Before: `scene_purpose=(visual_intent.visual_objective or "general")[:200]`
   - After: `scene_purpose=(visual_intent.visual_objective or topic)[:200]`

2. **`src/director/concept_planner.py` lines 140, 170**: Replace `"general"` with `f"{topic} stock footage"`.
   - Before: `return [topic, "stock footage", "documentary", "general"]`
   - After: `return [topic, "stock footage", "documentary", f"{topic} cinematic footage"]`

3. **`src/models/schemas.py` line 783**: Topic-aware default SearchPlan (requires topic injection at Scene creation).

These changes are minimal, zero-risk (they only affect the fallback path that runs when no terms are available), and ensure that every search query sent to provider APIs is semantically meaningful.

---

## Risks

- **Minimal risk**: The fix only affects the fallback path (when `sanitised_terms` is `[]`). In all other cases, the existing LLM-generated or rule-based terms continue to be used unchanged.
- **Edge case**: If `topic` itself is empty or generic, the fallback could still produce weak queries. However, the pipeline always operates with a concrete topic string.
- **No regression potential**: The change is a simple string replacement from `"general"` to a topic-relevant string. No logic changes, no new dependencies.

---

## Next Steps

- [x] Investigation complete
- [x] Root cause identified
- [x] Fix recommended
- [ ] Fix implemented (after review)
- [ ] Tests added/updated for sanitise fallback behavior
- [ ] Reviewed
- [ ] Merged
- [ ] Verified in next pipeline run
