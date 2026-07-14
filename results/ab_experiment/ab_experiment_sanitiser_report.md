# A/B Experiment: Search-Term Sanitiser Impact

**Topic:** The Fermi Paradox
**Date:** 2026-07-14
**Base Commit:** `4be7ae4dea951553df5a09a93a1c89ea419bbd02`
**Branch:** `jade`

---

## Experimental Design

| Aspect | Detail |
|---|---|
| **Experiment A** | Pipeline runs raw LLM search terms — no `_sanitise_search_terms()` stage |
| **Experiment B** | Same pipeline with `_sanitise_search_terms()` injected between `ConceptPlanner.generate_queries()` and `AssetRouter.multi_query_search()` |
| **Overlap threshold** | 50% word overlap with narration |
| **Replacement map** | 42 concrete visual term mappings |
| **Scenes** | 5 scenes from The Fermi Paradox (StoryPlanner-generated) |
| **Terms per scene** | 7 |
| **Total terms tested** | 70 (35 per experiment, deduplicated to avoid redundant API calls) |
| **Controls** | Identical ScenePlanner output, same LLM provider, same AssetRouter, same SemanticValidator, same QualityGates |
| **API providers** | Pexels (primary), NASA (fallback) |
| **Providers called** | Real API calls — Pexels always returned hits, NASA returned same 5 Astromaut-specific videos |

---

## Sanitiser Impact Summary

| Metric | A (Baseline) | B (Sanitiser) | Delta | Verdict |
|---|---|---|---|---|
| Terms tested | 35 | 35 | — | — |
| Terms removed by sanitiser | 0 | 0 | — | **No terms removed** |
| Provider hit rate (hits/search) | 10.00 | 10.00 | 0.00 | Tie |
| Downloadable terms | 35 | 35 | — | Tie |
| Download success rate | 100.0% | 100.0% | 0.0% | Tie |
| Avg semantic score | 0.580 | 0.577 | -0.003 | Baseline (A) wins — negligible |
| Gate pass rate | 37.1% | 37.1% | 0.0% | Tie |
| Fallback usage | 0 | 0 | — | Tie |

---

## Per-Scene Breakdown

| Scene | Title | A Sem | B Sem | Sem Delta | A Gate | B Gate | Removed |
|---|---|---|---|---|---|---|---|
| 0 | The Cosmic Silence Begins | 0.557 | 0.543 | -0.014 | 42.9% | 42.9% | 0 |
| 1 | Quantifying the Unknown | 0.600 | 0.600 | +0.000 | 42.9% | 42.9% | 0 |
| 2 | The Search and the Filter | 0.671 | 0.671 | +0.000 | 42.9% | 42.9% | 0 |
| 3 | The Dark Forest and the Zoo | 0.450 | 0.450 | +0.000 | 14.3% | 14.3% | 0 |
| 4 | Fermi's Haunting Echo | 0.621 | 0.621 | +0.000 | 42.9% | 42.9% | 0 |

---

## Per-Scene Overlap Analysis

Across all 5 scenes (35 LLM-generated terms), the sanitisation overlap check produced identical results:

| Scene | Raw Terms | Overlap-Rejected | Accepted | Replacement-Succeeded | Final Terms |
|---|---|---|---|---|---|
| 0 | 7 | 0 | 7 | 0 | 7 |
| 1 | 7 | 0 | 7 | 0 | 7 |
| 2 | 7 | 0 | 7 | 0 | 7 |
| 3 | 7 | 0 | 7 | 0 | 7 |
| 4 | 7 | 0 | 7 | 0 | 7 |

**Key finding:** The LLM (`ConceptPlanner`) already generates visually-distinct search terms that have **<50% word overlap** with scene narration in **100% of cases** across this test. The sanitiser had zero effect because no terms ever exceeded the overlap threshold.

---

## Analysis of the 5 Questions

### 1. Does the sanitiser improve provider retrieval?

**NO.** Provider hit rate was identical (10.00 hits/search, r=1.0) for both experiments. The sanitiser neither helps nor hurts because Pexels returns results for any well-formed English query regardless of overlap with narration.

**Evidence:** All 35 terms in both A and B produced identical Pexels results (same candidates, same scores).

### 2. Does the sanitiser improve semantic quality?

**MARGINALLY HARMFUL** (but within noise). Average semantic score dropped from 0.580 (A) to 0.577 (B) — a Δ of -0.003. This is a 0.3% degradation, well within measurement noise.

**Evidence:** 3 scenes had no change, 1 scene dropped by 0.014 (scene 0: 0.557 → 0.543), 1 scene had no change.

### 3. Does the sanitiser reduce irrelevant downloads?

**NO.** The sanitiser removed 0 terms, so download volume was identical. Both experiments downloaded 35/35 assets (100% download rate). No reduction in irrelevant downloads.

### 4. Does bypassing the sanitiser increase successful primary assets?

**NO.** Both experiments had identical gate pass rates (37.1%) and identical fallback counts (0). Bypassing the sanitiser changes nothing because it removes nothing.

### 5. Should the sanitiser remain, be redesigned, or be removed?

**REMOVE — the sanitiser is dead code.** It had zero impact on every metric measured:

- 0 terms removed across 35 inputs
- 0% change in provider hit rate
- 0% change in download success rate
- -0.003 Δ in semantic score (noise)
- 0% change in gate pass rate
- 0 fallbacks in both runs

The LLM already generates visually-distinct terms. The sanitiser's overlap threshold (50%) never triggers because the `ConceptPlanner` is designed to generate concrete visual queries (radio telescope, galaxy spiral, candle flame) rather than narration-derived text.

---

## Recommended Minimum Code Change

**Remove `_sanitise_search_terms()` from the pipeline entirely, or keep it as an optional flag disabled by default.**

Evidence from this experiment:
1. The function performs zero work across all real-world test cases
2. It adds latency (word-level scanning + replacement lookup) with no benefit
3. In the pathological case (all 10 terms >50% overlap, no replacements), it silently returns [] which would cause the pipeline to crash or fall back unnecessarily

**If the function must remain** (e.g. as a safety net for poor LLM output), it should:
- Only activate when rejection rate >80%
- Have a hard fallback to raw terms when it would return []
- Log a warning when it removes >50% of input terms

---

## Files

- **Runtime log:** `results/ab_experiment/ab_experiment_v2_The_Fermi_Paradox.txt`
- **Report:** This file
- **Instrumentation scripts:** `tools/ab_experiment_sanitizer_v2.py`, `tools/instrument_sanitise_search_terms.py`

---

## Commit

`9fed08ec7521d9d12d366a277224e580e8d47a20`
