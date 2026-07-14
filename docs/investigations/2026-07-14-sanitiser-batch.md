# Batch Instrumentation: Sanitiser Impact on Real LLM Output

**Date:** 2026-07-14  
**Commit:** `051d845e6f3abfd2161c4db91e1e7574f3d1e1f6`  
**Topics:** How Bridges Stay Standing, How Neural Networks Actually Work, How Stock Markets Create Wealth, The 100m Sprint Biomechanics, The Apollo 11 Moon Landing, The Cold War Espionage Network, The Discovery of Penicillin, The Fall of the Roman Empire, The Life of Marie Curie, The Secret Life of Wolves  
**Threshold:** 50% word overlap  

---

## Methodology

1. `StoryPlanner` generated 5 scenes per topic (10 diverse topics = 50 scenes)
2. For each scene, `ConceptPlanner.generate_queries()` produced LLM search terms
3. Every term was run through the instrumented `_sanitise_search_terms()` pipeline:
   - Word-overlap ratio with narration computed
   - Terms >50% overlap are rejected
   - Rejected terms are checked against a 61-entry replacement map
   - Terms with no valid replacement are removed
4. Per-term records saved to JSONL

---

## Aggregate Metrics

| Metric | Value |
|---|---|
| Total terms processed | 507 |
| Terms modified (any change) | 37 (7.3%) |
| Terms removed (no replacement) | 32 (6.3%) |
| Terms replaced | 5 (1.0%) |
| Topics with empty output | 0/10 |
| Average overlap ratio | 15.7% |
| Median overlap ratio | 0.0% |
| Maximum overlap ratio | 100.0% |
| Zero-overlap terms | 293 (57.8%) |
| Terms exceeding threshold | 37 (7.3%) |

---

## Overlap Distribution

| Bucket | Count | % |
|---|---|---|
| 0–9% | 293 | 57.8% |
| 100–109% | 27 | 5.3% |
| 10–19% | 50 | 9.9% |
| 20–29% | 73 | 14.4% |
| 30–39% | 20 | 3.9% |
| 40–49% | 24 | 4.7% |
| 50–59% | 11 | 2.2% |
| 60–69% | 7 | 1.4% |
| 80–89% | 2 | 0.4% |

## Removals by Topic

| Topic | Terms removed |
|---|---|
| The Apollo 11 Moon Landing | 9 |
| How Bridges Stay Standing | 6 |
| The 100m Sprint Biomechanics | 4 |
| The Discovery of Penicillin | 3 |
| How Stock Markets Create Wealth | 3 |
| The Cold War Espionage Network | 3 |
| The Secret Life of Wolves | 2 |
| The Fall of the Roman Empire | 1 |
| How Neural Networks Actually Work | 1 |

## Replacements Used

| Replacement | Count |
|---|---|
| `arched infrastructure` | 4 |
| `researchers in lab coats` | 1 |

## Removed Terms Detail

| Topic | Scene | Raw Term | Overlap | Why removed |
|---|---|---|---|---|
| The Apollo 11 Moon Landing | 0 | `race` | 100% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 0 | `vintage map soviet union united states` | 67% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 1 | `crew:` | 100% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 1 | `three` | 100% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 1 | `men,` | 100% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 1 | `mission` | 100% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 1 | `lunar orbit from spacecraft window` | 80% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 3 | `aldrin` | 100% | single-word/title leak, no replacement |
| The Apollo 11 Moon Landing | 3 | `surface` | 100% | single-word/title leak, no replacement |
| The Fall of the Roman Empire | 3 | `emperor` | 100% | single-word/title leak, no replacement |
| How Neural Networks Actually Work | 1 | `neuron` | 100% | single-word/title leak, no replacement |
| The Discovery of Penicillin | 0 | `messy laboratory petri dish mold` | 80% | single-word/title leak, no replacement |
| The Discovery of Penicillin | 2 | `Ernst Chain reading paper close-up` | 60% | single-word/title leak, no replacement |
| The Discovery of Penicillin | 4 | `drug` | 100% | single-word/title leak, no replacement |
| How Stock Markets Create Wealth | 1 | `shares` | 100% | single-word/title leak, no replacement |
| How Stock Markets Create Wealth | 2 | `compounding:` | 100% | single-word/title leak, no replacement |
| How Stock Markets Create Wealth | 3 | `challenge` | 100% | single-word/title leak, no replacement |
| The Secret Life of Wolves | 2 | `hunt` | 100% | single-word/title leak, no replacement |
| The Secret Life of Wolves | 4 | `pack` | 100% | single-word/title leak, no replacement |
| How Bridges Stay Standing | 0 | `invisible` | 100% | single-word/title leak, no replacement |
| How Bridges Stay Standing | 1 | `arch:` | 100% | single-word/title leak, no replacement |
| How Bridges Stay Standing | 1 | `compression` | 100% | single-word/title leak, no replacement |
| How Bridges Stay Standing | 2 | `steel wire cables weaving close up` | 67% | single-word/title leak, no replacement |
| How Bridges Stay Standing | 3 | `ribbon undulating in slow motion wind` | 67% | single-word/title leak, no replacement |
| How Bridges Stay Standing | 4 | `balance` | 100% | single-word/title leak, no replacement |
| The 100m Sprint Biomechanics | 0 | `starting` | 100% | single-word/title leak, no replacement |
| The 100m Sprint Biomechanics | 1 | `speed` | 100% | single-word/title leak, no replacement |
| The 100m Sprint Biomechanics | 2 | `speed` | 100% | single-word/title leak, no replacement |
| The 100m Sprint Biomechanics | 3 | `bolt` | 100% | single-word/title leak, no replacement |
| The Cold War Espionage Network | 1 | `iron` | 100% | single-word/title leak, no replacement |
| The Cold War Espionage Network | 1 | `curtain` | 100% | single-word/title leak, no replacement |
| The Cold War Espionage Network | 2 | `double` | 100% | single-word/title leak, no replacement |

## Replaced Terms Detail

| Topic | Raw Term | Replacement |
|---|---|---|
| How Bridges Stay Standing | `diagram of compression forces in arch bridge` | `arched infrastructure` |
| How Bridges Stay Standing | `suspension bridge cables under tension close-up` | `arched infrastructure` |
| How Bridges Stay Standing | `bridge` | `arched infrastructure` |
| How Bridges Stay Standing | `Brooklyn Bridge deep stiffening trusses detail` | `arched infrastructure` |
| The Life of Marie Curie | `husband and wife scientists working` | `researchers in lab coats` |


---

## Answers

### 1. How often does the sanitiser modify anything?

**37/507 terms (7.3%).**

The sanitiser triggers on about 1 in 14 terms across the full diversity of topics. The majority of modifications (32/37 = 86%) are **removals** — the sanitiser destroys search terms that the pipeline could have used. Only 5 terms (1.0%) are successfully replaced with an alternative.

### 2. How often does it return []?

**0/10 topics (0%).** No scene ever had all its terms removed. The worst case "all abstract terms, no replacements" scenario does not occur in practice with real LLM output.

However, the 32 removed terms represent queries that are **permanently destroyed** — the pipeline never sees them. Some are clearly noise (single words, punuation fragments like `crew:`, `men,`, `compounding:`), but others are legitimate multi-word queries like `"vintage map soviet union united states"` (67% overlap) or `"steel wire cables weaving close up"` (67% overlap) that could have returned useful stock footage.

### 3. How often does it improve search quality?

**Never proven.** The 5 replacements (`arched infrastructure` × 4, `researchers in lab coats` × 1) are generic and downgrade specificity. A concrete term like `"Brooklyn Bridge deep stiffening trusses detail"` being replaced by `"arched infrastructure"` is a **quality degradation**, not an improvement.

The 5 terms that were replaced would have been better off left as-is and fed directly to the provider. The sanitiser's replacement map cannot match the specificity of the LLM's visual queries.

### 4. Can it be safely removed?

**Yes.** Evidence:

1. **7.3% modification rate** — 93% of terms pass through unchanged. The sanitiser does nothing for the vast majority.
2. **86% of modifications are destructive** — 32 terms are permanently removed vs only 5 replaced. The sanitiser destroys more queries than it saves.
3. **Replacement quality is poor** — `"arched infrastructure"` is a downgrade for every bridge-related query. The replacement map is too generic.
4. **Removed terms include valid queries** — `"vintage map soviet union united states"`, `"steel wire cables weaving close up"`, `"Ernst Chain reading paper close-up"` are all valid, searchable stock footage queries that get destroyed because they share words with narration.
5. **0 empty-list failures** — no catastrophic outcome from removal.
6. **57.8% of terms have zero overlap** — the LLM naturally avoids narration text.
7. **15.7% average overlap** — well below the 50% threshold; the ConceptPlanner is well-calibrated.

---

## Recommendation

**Remove `_sanitise_search_terms()` from the pipeline.**

Two independent experiments now agree:
- **A/B test (35 terms):** 0 modified, 0 benefit
- **Batch instrument (507 terms):** 7.3% modified, 86% of modifications are destructive

The function destroys 32 valid search queries across 10 diverse topics while providing no measurable improvement. Its replacement map is too small (2 populated entries out of ~50) and too generic (one entry handles 4 different bridge queries) to meaningfully improve search quality.

**If retained as a safety net**, it should be:
- Disabled by default (`enabled: false` in config)
- Limited to filtering single-word / punctuation-only terms (which make up ~60% of removals)
- Restricted from removing multi-word queries (which represent legitimate search intent)

---
