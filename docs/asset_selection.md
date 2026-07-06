# Asset Selection — video_engine

## Overview

Asset selection is the process of choosing the best video clip for each
scene from the available candidates returned by a provider (e.g. Pexels).

Since commit `e0845d5` the pipeline uses a **deterministic scoring formula**
instead of blindly picking the first API result.  Up to 10 candidates are
fetched per query, scored, sorted, and the highest-scoring one is used.

## Scoring Algorithm

Every candidate receives a score in **[0, 1]** computed as the weighted sum
of three sub-scores:

```
total = W_res × res_score + W_dur × dur_score + W_hd × hd_score
```

### Weights (from `configs/providers.yaml`)

| Component              | Weight | Default | Rationale                              |
|------------------------|--------|---------|----------------------------------------|
| Resolution score       | 0.40   | Captures crispness and screen fit      |
| Duration match score   | 0.40   | Minimises freeze-frames or wasted clip |
| HD bonus               | 0.20   | Prefers high-quality source when equal |

Weights are configurable and should sum to 1.0.

### Resolution Score

```
res_score = min((width × height) / (1920 × 1080), 1.0)
```

- 1920×1080 or larger → 1.0
- 1280×720 → 0.44
- 640×360 → 0.11

### Duration Match Score

The clip duration is compared to the scene's `estimated_duration` (set by
the planner).  Clips shorter than the target are penalised more heavily
(they require freeze-frames).  Clips longer than the target are penalised
gently (they get trimmed anyway).

```
ratio = clip_duration / target_duration

if ratio < 1.0:
    dur_score = max(0, 1 - (1 - ratio) × 2)
else:
    dur_score = max(0, 1 - (ratio - 1) × 0.5)
```

Examples with a 10-second target:

| Clip duration | Ratio | Score | Reason                   |
|---------------|-------|-------|--------------------------|
| 10 s          | 1.0   | 1.000 | Perfect match            |
| 15 s          | 1.5   | 0.750 | Slightly long (trimmed)  |
| 25 s          | 2.5   | 0.250 | Very long                |
| 8 s           | 0.8   | 0.600 | Slightly short (freeze)  |
| 5 s           | 0.5   | 0.000 | Half duration (bad)      |

### HD Bonus

```
hd_score = 1.0 if any video_file has quality == "hd" else 0.0
```

A flat bonus for clips that provide an HD-quality stream.

## Tie-Breaking

When two candidates receive identical scores (unlikely but possible),
the candidate that appeared first in the Pexels API response wins
(the stable sort preserves insertion order).

## Fallback Behaviour

- If the API returns zero candidates, an empty list is returned and the
  orchestrator falls back to `pipeline.fallback.video`.
- If scoring encounters a missing key or zero dimension, that sub-score
  is treated as 0.0 (no crash).
- If scoring weights are missing from the config, the hard-coded defaults
  are used as a safety net.

## Logging

After scoring, every candidate and its score is printed:

```
  Candidate 1: id=15735937 1920x1080 dur=120s score=0.875 ← SELECTED
  Candidate 2: id=13820491 1280x720  dur=30s  score=0.713
  Candidate 3: id=16123456 640x360   dur=8s   score=0.302
```

The `← SELECTED` marker identifies the clip that will be downloaded.

## Cache Interaction

On a cache **miss**: the provider fetches up to 10 candidates from the API,
scores them all, selects the best, and registers only the best clip's URL
in the SQLite cache.

On a cache **hit**: the cached URL is returned immediately (it was already
scored when first selected).  No re-scoring occurs on subsequent runs.

## Future Extensibility

The `_score_candidates` method is a static method on `PexelsProvider`.
It can be:

- Extended with additional signals: popularity, user rating, file size,
  colour histogram diversity, text-to-video relevance.
- Overridden in subclasses to implement provider-specific scoring.
- Extracted to a standalone service when multiple providers are used
  (Pexels, Pixabay, NASA) and need a uniform comparison scale.
