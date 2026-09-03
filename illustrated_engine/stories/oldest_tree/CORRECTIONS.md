# OLDEST_TREE FACTUAL CORRECTIONS — V4 P0 AUDIT (2026-09-03)

## Why
The V4 brief makes factual integrity a P0 publish gate: no superlative/record
claim enters a script without explicit verification (claim, definition,
record holder, measured value, date verified, source URL, and whether the
record has historically changed). Proto3's story was audited against that gate.

## Audit findings (proto3 AS RENDERED — audited from tag `proto3`)
`facts verify` on the tagged, as-rendered script: **FAIL**
- 0 verified fact entries at render time (`facts.json` did not exist)
- 4 uncovered superlative/trigger usages:
  - B1 "oldest" — "the oldest living tree on Earth"
  - B5 "most" — "Most of the tree is already dead" (quantifier, not a record;
    handled by adding a verified strip-bark biology claim)
  - B6 "oldest" — "The oldest tree ever found, destroyed in minutes"
  - B7 "oldest" — "The oldest tree on Earth survives because it stays hidden"
- Snapshot: `build/qa/factual_proto3_as-rendered.json`

## Contested-record research (why the qualifiers matter)
- Methuselah: 4,856 yr — oldest **confirmed living, non-clonal** tree
  (Guinness / USDA Forest Service).
- Unnamed Harlan bristlecone: crossdated **5,074 yr** (announced 2009; core
  collected 1957; liveness not re-confirmed) — could displace Methuselah.
- Gran Abuelo (alerce, Chile): claimed **~5,484 yr** (2022; model-based,
  unpublished) — could displace Methuselah if accepted.
- B6 specifically: Prometheus held "oldest known" **in 1964**; today the
  Harlan tree and Gran Abuelo both exceed it. "Oldest tree ever found" is no
  longer true.

## Changes applied (proto3 render itself is NOT modified — tag `proto3` keeps
## the original; future re-renders use the corrected script)
1. `story.json` narration tightened:
   - B1: "the oldest living tree on Earth" -> "the oldest **confirmed** living tree on Earth"
   - B6: "The oldest tree ever found, destroyed in minutes." -> "The oldest tree **then known**, destroyed in minutes."
   - B7: "The oldest tree on Earth survives" -> "The oldest **confirmed** living tree on Earth survives"
2. `facts.json` added — 7 verified claim entries covering every flagged beat
   (B1, B2, B3, B4, B5, B6, B7) with definitions, measured values, dates,
   sources, and `historically_changed` flags (B1/B6 true).

## Result
`facts verify stories/oldest_tree` now **PASSES** the V4 P0 gate.
The fact registry is checked on every `facts`/`qa4` run, and QA never gates
on stale results — it always re-verifies the current script.
