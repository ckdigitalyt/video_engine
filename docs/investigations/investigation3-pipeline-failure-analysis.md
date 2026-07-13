# Investigation #3: Shot-Level Primary Pipeline Failure Analysis

**Date:** 2026-07-13
**Investigator:** Jade
**Target:** Scene 0, Beat 0, Shot 1 (first non-primary shot of the video)
**Trace log:** `docs/investigations/investigation3_trace.log`

---

## Objective

Determine why the primary asset pipeline succeeds for Shot 0 (first shot of beat 0) but fails for Shot 1 (cutaway shot in the same beat), forcing a fallback to `FallbackDirector`.

## Methodology

Monkey-patched `BeatDirector._process_shot` to insert 8 checkpoints logging every step of the primary pipeline. Only the **target shot** (Scene 0, Beat 0, Shot 1) was instrumented; all other shots passed through unmodified. The pipeline ran against "The Fermi Paradox" topic with all provider API keys validated and functional.

## Condensed Trace

### Scene 0, Beat 0 structure

| Shot | Type | Duration | Outcome |
|---|---|---|---|
| Shot 0 | Primary | — | **SUCCESS** (Pexels, 42 MB) |
| Shot 1 | **Cutaway** | 1.37s | **FAILED → fallback** (target) |

### Attempt 1: query='general cutaway shot'

| Checkpoint | Data |
|---|---|
| **CP1** (provider search) | Provider: **none**; Candidates: 0 |
| **CP2** (candidate scoring) | No candidates to score |
| → All 4 providers (nasa, pexels, pixabay, wikimedia) returned 0 results |

### Attempt 2: query='general'

| Checkpoint | Data |
|---|---|
| **CP1** (provider search) | Provider: **nasa**; Candidates: **1** |
| **CP2** (candidate scoring) | ID: `unknown` (no `id` field in NASA's normalised result); Width: 0, Height: 0, Duration: 0; Score: 0.2 |
| **CP3** (extract URL) | `video_files` count: 1; Link: `http://images-assets.nasa.gov/video/NHQ_2019_0719_…Artemis…/…mp4`; **Link empty? False** |
| Semantic validation score | **0.0000** (threshold: **0.75**) |
| **CP4** (pre-download) | URL: `…Artemis…mp4`; Dest: `cache/video/scene_0_b0_s1.mp4` |
| **CP5** (post-download) | Success: **True**; File exists: True; Size: **13,577,378 bytes** (13.5 MB) |
| **CP6** (quality gates) | Duration: **71.84s**; Resolution: **1280×720**; Decision: **REJECTED** |
| | **Exact rejection:** `SemanticGate: semantic_score 0.000 < threshold 0.75` |
| → File **deleted** after rejection |

### Attempt 3: query='The Fermi Paradox documentary stock footage'

| Checkpoint | Data |
|---|---|
| **CP1** (provider search) | Provider: **none**; Candidates: 0 |
| → All providers returned 0 results |

### All queries exhausted

| Checkpoint | Data |
|---|---|
| **CP7** (fallback reason) | No assets returned by any provider for the 3rd query |
| **CP8** (post-fallback) | Type: **NASA image + Ken Burns**; Path: `cache/video/nasa_fallback_kenburns_97197.mp4`; Exists: True; Size: **1,013,995 bytes** |

---

## Root Cause Analysis

### Primary failure: Semantic gate rejection of a valid NASA video

The pipeline **did** find and download a real video asset (13.5 MB, 1280×720, from NASA's media library). However, the `SemanticValidator` scored it at **0.0000** — well below the 0.75 threshold — because:

1. The narration discusses the **Fermi Paradox** (aliens, galaxy, silence)
2. The NASA asset returned was an **Artemis moon mission promotional video** ("We Go as the Artemis Generation")
3. Zero keyword overlap between narration and asset metadata
4. The deterministic fallback scorer (`_score_fallback`) uses word-level token matching — no embedding or semantic understanding

### Underlying cause: Query generation

The queries reaching `multi_query_search` were:

```
Attempt 1: "general cutaway shot"
Attempt 2: "general"
Attempt 3: "The Fermi Paradox documentary stock footage"
```

The base query is `"general"` because `visual_intent.search_terms[0]` was set to `"general"` by the StoryPlanner. This means:

- **All per-shot queries are prefix-weak** — they start from "general" not "Fermi Paradox"
- Attempt 1 returns nothing because "general cutaway shot" is too vague
- Attempt 2 returns an irrelevant NASA video (best match for "general")
- Attempt 3 returns nothing because the topic string doesn't match stock footage catalogs

### Why Shot 0 succeeded

Shot 0 (primary) used the *same* `visual_intent.search_terms[0] = "general"` and the *same* `expand_for_shot` function. Its queries were:

```
"general primary shot", "general wide shot", "general establishing", ...
```

The difference: `multi_query_search` searched 4 providers for **each** of those queries. Pexels happened to return a generic "space"-tagged stock video that:
- Had a valid download URL
- Downloaded quickly (42 MB in reasonable time)
- Had non-zero keyword overlap with the narration (both mentioned "space" or "galaxy")
- Passed the 0.75 semantic threshold

The cutaway shot's queries simply didn't hit a provider catalog that returned a matching video with sufficient semantic overlap.

### Secondary issue: Empty `shot.description`

The `ShotPlan.description` field is empty for this cutaway shot. The `_process_shot` code uses `shot.description or beat.visual_purpose[:100]`. If both are empty or generic, the query expansion has no signal to work with.

---

## Checkpoint Summary

| CP | Description | Key Finding |
|---|---|---|
| 1 | Provider search | NASA found 1 candidate for query "general"; 0 for the other 2 |
| 2 | Candidate scoring | Candidate ID absent; score ~0.2 (no width/height metadata) |
| 3 | Download URL extraction | `vf_link` present, non-empty: `…Artemis…mp4` |
| 4 | Pre-download | URL + dest path valid |
| 5 | Post-download | **13.5 MB downloaded successfully** |
| 6 | Quality gates | **REJECTED: semantic_score 0.0 < 0.75** |
| 7 | Fallback reason | Primary pipeline exhausted after 3 queries |
| 8 | Post-fallback | NASA Ken Burns image animation (1014 KB) |

---

## Recommendations

1. **Fix StoryPlanner search terms.** The scene's `search_plan.asset_search_queries` should contain actual topic descriptions (e.g., "Fermi Paradox space stars galaxy" or narration-derived keywords) rather than the literal `"general"`.

2. **Propagate shot descriptions.** The `ShotPlanner.plan_shots()` sets `description` as `"Primary shot for beat N"` or `"Cutaway detail"` — static strings with no narration or topic content. Replace these with content derived from the beat's narration text so `expand_for_shot` has real signal.

3. **Add fuzzy semantic scoring.** The deterministic keyword-overlap fallback scorer is too brittle. A simple embedding-based similarity check (or even TF-IDF cosine similarity) would have scored the Artemis video at > 0 since it shares space-related vocabulary with the narration.

4. **Don't delete rejected downloads.** The pipeline downloaded 13.5 MB and then deleted it. If the asset physically exists, keep it cached; future re-runs or different narration regenerations may accept it.

5. **Add shot-level query logging to production.** The production `_process_shot` currently has no `print()` or `logging.debug()` calls — just a terse `"Shot accepted"` message. Adding structured query-level logging would make future investigations faster.
