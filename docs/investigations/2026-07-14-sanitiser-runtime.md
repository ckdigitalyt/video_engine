# Investigation: `_sanitise_search_terms()` Returns `[]`

**Date:** 2026-07-14
**Commit:** 4be7ae4dea951553df5a09a93a1c89ea419bbd02 (base)

---

## Executive Summary

`_sanitise_search_terms()` returns an empty list when the LLM generates search terms that are lexically identical to scene narration **and** none of the overlapping words have entries in the replacement map. This creates a fatal gap in the sanitisation pipeline — there is no fallback path after overlap-rejection exhausts the replacement table. Information survival is 0% in this case, meaning the scene will have zero valid search queries and likely fail asset retrieval.

---

## Objective

Prove exactly which stage in `_sanitise_search_terms()` causes the empty return and quantify information loss.

---

## Environment

| Field | Value |
|---|---|
| **Codebase** | `video_engine` @ `4be7ae4` |
| **Repository** | `github.com:ckdigitalyt/video_engine` |
| **Function** | `_sanitise_search_terms()` (instrumented standalone in `tools/instrument_sanitise_search_terms.py`) |
| **Threshold** | 0.50 (50% word overlap) |
| **Test narration** | "the reason why there is a contradiction between the high probability of extraterrestrial life existing and the lack of evidence or contact remains unknown" |

---

## Investigation

### Function Architecture

`_sanitise_search_terms()` has 3 stages executed in sequence:

1. **Overlap Filtering** — Check each raw LLM term against narration using word-overlap ratio. Reject if > 50%.
2. **Replacement** — For rejected terms, attempt word-level lookup in a replacement map. Accept replacement if its own overlap ≤ 50%.
3. **Deduplication** — Remove duplicate normalised strings. Truncate to `num_queries` (default 7).

If stage 1 kills everything and stage 2 finds zero valid replacements, the pipeline returns `[]`.

### Trigger Conditions

The empty return requires BOTH:

1. **ALL raw terms** have > 50% word overlap with narration
2. **NO overlapping words** are present in the replacement map

This happens when:
- The LLM paraphrases narration text directly instead of generating visually-distinct queries
- The vocabulary consists of abstract/conceptual terms (contradiction, probability, evidence, reason, unknown) that aren't in the replacement table

### The Replacement Gap

The replacement map (`_REPLACEMENT_MAP` in the instrumented script) covers ~80 concrete visual words (space, galaxy, telescope, ocean, etc.) but explicitly excludes abstract concepts via `_NO_REPLACEMENT_TERMS`. These abstract terms are precisely the words the LLM tends to produce when it's reasoning about the topic rather than describing visual scenes.

---

## Evidence

### Scene Capture: 10 Raw LLM Terms → `[]`

```
Raw LLM terms:
   [1] 'why there is a contradiction'
   [2] 'high probability of extraterrestrial life'
   [3] 'lack of evidence or contact'
   [4] 'reason remains unknown'
   [5] 'contradiction probability life'
   [6] 'evidence of extraterrestrial contact'
   [7] 'existing life lack evidence'
   [8] 'there is no contact evidence'
   [9] 'extraterrestrial life probability'
  [10] 'unknown reason contradiction'

Stage 1 — Overlap Filtering:
  10/10 rejected (100%). All >50% overlap.
  Rejected words include: contradiction, probability, evidence, reason,
  unknown, contact, lack — all abstract/conceptual.

Stage 1b — Replacement:
  10/10 failed. No word matched the replacement map.
  - contradiction → abstract/conceptual (no replacement)
  - probability → abstract/conceptual (no replacement)
  - reason → abstract/conceptual (no replacement)
  - evidence → not in map
  - contact → not in map
  - lack → not in map
  - existing → not in map
  - unknown → not in map

Stage 2 — Deduplication:
  0 candidates entered. 0 removed. 0 returned.

Returned: []
```

### Binary Survival

```python
raw_terms = 10
passed_overlap = 0
successful_replacements = 0
after_dedup = 0
returned = 0

Information survival: 0/10 = 0%
```

### Root Cause Classification

**Primary:** `OVERLAP_EXHAUSTION`

All 10 original LLM terms exceed the 50% overlap threshold because the LLM is generating conceptually-driven phrases rather than visually-driven search queries. The replacement table lacks entries for the abstract vocabulary used (contradiction, evidence, probability, reason, unknown, lack, contact). With zero replacements available, deduplication has nothing to process, and the function returns `[]`.

**Secondary:** `REPLACEMENT_EXHAUSTION`

Even the replacement map entries that DO exist (galaxy → "spiral nebula deep field", space → "deep space expanse") would have been irrelevant here — none of the 10 terms contained a word present in the map.

---

## Code Reference

### Instrumented Implementation

`tools/instrument_sanitise_search_terms.py` — standalone simulation of the full sanitisation pipeline.

Key section — the replacement gate after overlap filtering:

```python
# After every raw term is rejected by overlap:
for term in rejected_terms:
    replacement = lookup_replacement(term)  # word-level map lookup
    if replacement and check_overlap(replacement, narration) <= THRESHOLD:
        candidates.append(replacement)
    else:
        # No valid replacement → term is permanently lost
        pass
```

### Replacement Map Gaps

No entries exist for: *contradiction, evidence, probability, reason, unknown, lack, contact, existing, remains, between, paradox, theory, hypothesis, concept, phenomenon, question, answer, explanation, mystery, secret, truth, belief, philosophy, thought, meaning, significance, problem, equation, possibility, certainty*

These terms appear commonly in Fermi Paradox–style narration but have no safe visual equivalents.

---

## Alternatives Considered

1. **Lower the overlap threshold** — Not considered; threshold is correct at 50% to prevent narration text from leaking into search queries. Lowering it would introduce false positives.
2. **Expand the replacement map** — Would only patch individual word classes. The fundamental issue is that abstract words (evidence, probability) cannot be mapped to concrete visual search queries without losing meaning.
3. **Pre-process LLM output to reject conceptual terms before sanitisation** — Would require an additional LLM call to determine whether a term is visual or conceptual.
4. **Move fallback generation into the sanitisation function** — This is the recommended approach (see below).

---

## Recommended Minimum Code Change

**Do not modify thresholds. Do not change the overlap logic. Add a fallback path.**

Before entering the replacement stage, when the overlap rejection rate exceeds 80% of raw terms, inject a topic-derived fallback set:

1. Use the `topic` parameter (already available from the scene) as a seed for `_FALLBACK_TEMPLATES` (already defined in `SearchPlanner`)
2. Generate fallback queries: `topic_word + visual_descriptor` (e.g., "Fermi wide angle", "Paradox cinematic")
3. Apply the overlap check against this fallback set
4. Merge survivors into the candidate pool before deduplication

**One-liner change:** `if len(rejected) / len(raw_terms) > 0.80: candidates += _generate_fallback_candidates(topic, narration)`

**Rationale:** The existing `_FALLBACK_TEMPLATES` produce visually descriptive queries (`"{kw} wide angle"`, `"{kw} cinematic"`) that inherently have low word overlap with narration because they append generic visual descriptors. These reliably pass the ≤50% overlap gate.

**Risk:** Minimal — mirrors existing fallback logic that already works in `SearchPlanner._generate_fallback()`.

---

## Next Steps

1. ☐ Implement the recommended code change in `search_planner.py`
2. ☐ Verify that the fallback path produces ≥3 valid queries for the failing scene
3. ☐ Add a test case for the empty-return scenario
4. ☐ Run full pipeline validation with the fix

---

## Runtime Log

The full instrumented runtime log is available at:

**`tools/instrument_sanitise_search_terms.py`** — execute with the failing scene capture:

```bash
python3 tools/instrument_sanitise_search_terms.py --narration "the reason why there is a contradiction between the high probability of extraterrestrial life existing and the lack of evidence or contact remains unknown" --title "The Silence" --topic "Fermi" --purpose "hook" --terms '["why there is a contradiction","high probability of extraterrestrial life","lack of evidence or contact","reason remains unknown","contradiction probability life","evidence of extraterrestrial contact","existing life lack evidence","there is no contact evidence","extraterrestrial life probability","unknown reason contradiction"]'
```

Output includes full per-term logging for all three stages plus the empty-analysis summary.
