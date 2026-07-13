# Primary Pipeline Runtime Trace — Scene 0 Beat 0 Shot 1

**Date:** 2026-07-13  
**Target:** Scene 0, Beat 0, Shot 1 (cutaway, 1.37 s)  
**Raw log:** `docs/investigations/primary-pipeline-trace.log`

---

## Execution

| Step | Outcome |
|---|---|
| **Shot 0 (primary, beat 0)** | SUCCESS — Pexels, `scene_0_b0_s0.mp4` (42 MB) |
| **Shot 1 (cutaway, beat 0)** | Failed → FallbackDirector |

---

## Attempt 1 — query `general cutaway shot`

All 4 providers (nasa, pexels, pixabay, wikimedia) returned **0 candidates**. No download was attempted.

---

## Attempt 2 — query `general`

**Provider search** — NASA returned 1 candidate: an Artemis Generation promotional video.

| Field | Value |
|---|---|
| Provider | nasa |
| Query | general |
| Candidates | 1 |
| Candidate ID | `unknown` (NASA normalised results have no `id` field) |
| Width / Height | 0 / 0 |
| Duration | 0 |

**Download URL extraction** — `vf_link` non-empty.

| Field | Value |
|---|---|
| video_files count | 1 |
| vf_link | `http://images-assets.nasa.gov/video/NHQ_2019_0719_We Go as the Artemis Generation/NHQ_2019_0719_We Go as the Artemis Generation.mp4` |
| vf_link empty? | **False** |

**Semantic validation** — score: **0.0000** against threshold **0.75**.

**Download** — succeeded.

| Field | Value |
|---|---|
| Destination | `cache/video/scene_0_b0_s1.mp4` |
| Success | True |
| File exists | True |
| File size | 13,577,378 bytes |
| Exception | None |

**Quality gates** — **REJECTED**.

| Gate | Passed? | Reason |
|---|---|---|
| SemanticGate | ❌ | `semantic_score 0.000 < threshold 0.75` |
| ReuseGate | — | Not reached |
| StyleGate | — | Not reached |
| DiversityGate | — | Not reached |

The downloaded file was **deleted** after rejection.

---

## Attempt 3 — query `The Fermi Paradox documentary stock footage`

All 4 providers returned **0 candidates**.

---

## Fallback

| Field | Value |
|---|---|
| Reason | All 3 queries exhausted; attempt 2 had an asset but it was rejected by SemanticGate |
| Fallback type | nasa (NASA image + Ken Burns animation) |
| Output path | `cache/video/nasa_fallback_kenburns_97197.mp4` |
| File exists | True |
| File size | 1,013,995 bytes |

---

## Root cause in one paragraph.

The base query for every shot in Scene 0 is `"general"` because the StoryPlanner set `visual_intent.search_terms[0]` to the literal string `"general"`. When `expand_for_shot` generates per-shot queries from that base, it produces vague terms like `"general cutaway shot"` and `"general"` that match irrelevant assets. NASA returned a 71-second Artemis moon launch video for `"general"`, which downloaded successfully (13.5 MB, 1280×720) but scored **0.0000** on the deterministic keyword-overlap SemanticValidator because the video metadata ("Artemis Generation") shares zero tokens with the narration ("Fermi Paradox, aliens, galaxy, silence"), triggering a **SemanticGate** rejection below the 0.75 threshold. Shot 0 survived only because Pexels happened to return a generic space-tagged stock video whose metadata had marginal keyword overlap with the narration.
