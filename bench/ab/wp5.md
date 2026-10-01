# WP5 acceptance: one-composition Remotion render (DESIGN.md 15.2 WP5)

Run 2026-10-01. No Claude calls. No new plate generation. Uses the existing
`ice_slippery` WP0 baseline fixture on disk (`illustrated_engine/build/v15/
ice_slippery/`) — a frame-sampled parity measurement only, per the launch
brief; the owner's video-render cap (2 renders remaining as of WP10) was
not spent on this (the one `short.mp4` produced here is the frame-sampled
parity harness's own output, not a pipeline/production render, and was
deleted after measurement — see Housekeeping). Samples: `~/phase4_out/wp5/`.

## Background: starting state of the tree

This run started from uncommitted work left by an earlier WP5 session that
hit a usage limit before committing (first flagged in `bench/ab/wp11.md`'s
"Scope note: WP5 leftovers in the tree," reproduced here for context):
`illustrated_engine/engine/v16_compose.py`, the Remotion project files
(`Short.tsx`, `Captions.tsx`, `Sting.tsx`, `Outro.tsx`, `render_short.mjs`,
`Root.tsx` diff, `package.json`/`package-lock.json` diff), `bench/ab/
wp5_parity.py`, `illustrated_engine/tests/test_wp5_compose.py`, and a
`requirements.txt` diff adding `scikit-image`. `illustrated_engine/tests`
passed with those files present (198/198 before this run), so they were
not broken, but nothing had reviewed them line-by-line, run the parity
test for real, or committed them.

This run reviewed every uncommitted file line-by-line (`git diff`,
`git status`) before touching anything. Verdict: the implementation is
sound, additive-only (does not touch `v15_pipeline.run_pipeline`'s live
compose path), and matches its own design comments almost everywhere — one
real bug was found by actually running the parity test (see below), not by
code reading alone. Kept as-is; the bug is reported, not silently patched,
per this run's scope (report the gap, don't fix it).

## Required behaviours (DESIGN §15.2 row WP5)

| requirement | proof | result |
|---|---|---|
| `Short.tsx` `<Series>` of per-scene `SceneComposition` props | `Short.tsx`, `v16_compose.build_short_props` — same `engine.scene_renderer.compile_spec` props every per-scene render already uses, sequenced via `Series.Sequence` | present, unit-tested |
| Captions inside Remotion (`@remotion/captions`) | `Captions.tsx` using the real `createTikTokStyleCaptions` API on a flat per-word timeline from `engine.v16_compose.build_caption_track` | present, but **the grouping is broken on real data** — see Parity result |
| Sting/outro inside the one render | `Sting.tsx` (ink-bloom overlay, t=0, not a pre-roll), `Outro.tsx` (stamp over the tail of the final scene, not a static end screen) — both reuse WP6 procedural assets, no visual logic reimplemented in TS | present, unit-tested (`total_duration_frames` ignores both — DESIGN S4/7.1) |
| pre-bundled `@remotion/renderer` render | `render_short.mjs` — one `bundle()` call serves every `renderStill`/`renderMedia` call in the process, vs the per-scene backend's one `npx remotion still\|render` CLI cold start per call | present, exercised for real (below) |
| frame-exact parity test vs per-scene Python render, ice, SSIM>=0.98 on 20 frames | `bench/ab/wp5_parity.py`, run for real | **FAIL — mean SSIM 0.93059, min 0.91455** (see below) |
| Render time <=40% of V15 on ice [target] | measured alongside the parity run | **FAIL at face value (188% of V15), but not a fair comparison — see note** |

## Test suite

`illustrated_engine/tests/test_wp5_compose.py` standalone (pure-function
unit tests, no Remotion/Node invocation):

```
$ venv/bin/python3 illustrated_engine/tests/test_wp5_compose.py
8 passed (ALL PASS)
```

`illustrated_engine/tests`, full suite (separate invocation per the WP
ritual):

```
$ venv/bin/python3 -m pytest -q illustrated_engine/tests
216 passed in 77.5s
```

Root `tests/` (separate invocation, clean detached worktree of this tree's
own HEAD, `4d6f65c`, run in parallel with the same suite on this tree):

```
baseline (clean worktree, 4d6f65c): 58 failed, 1283 passed, 8 skipped, 5 errors (252.1s)
current  (this tree, WP5 applied):  58 failed, 1287 passed, 4 skipped, 5 errors (316.0s)
```

63 failing IDs (58 FAILED + 5 ERROR) both before and after — sorted-ID
`comm -13`/`comm -23` diff is **empty**: identical set, zero new failures,
zero fixed. (`+4 passed / -4 skipped` is the same order/network-dependent
skip swing documented in every prior WP's acceptance report, not a WP5
effect — WP5 adds no files under root `tests/`.)

## Parity result: real run, real numbers, FAIL

```
$ venv/bin/python3 -m bench.ab.wp5_parity
scenes=11 total_frames=1510 (assembly_report total_s*fps=1510)
rendered full Short mp4 (1510 frames) in 308.5s -> ~/phase4_out/wp5/short.mp4
```

20 frames sampled evenly across the 1510-frame (50.3s) `ice_slippery`
fixture, `short.mp4` (one Remotion `Short` composition render) vs
`captioned.mp4` (today's live per-scene-render + concat + Python
caption-burn pass):

| frame | t (s) | SSIM |
|---|---|---|
| 2 | 0.07 | 0.97117 |
| 81 | 2.70 | 0.91527 |
| 160 | 5.33 | 0.94571 |
| 240 | 8.00 | 0.92151 |
| 319 | 10.63 | 0.94371 |
| 398 | 13.27 | 0.92320 |
| 477 | 15.90 | 0.94155 |
| 556 | 18.53 | **0.91455 (min)** |
| 636 | 21.20 | 0.92069 |
| 715 | 23.83 | 0.91592 |
| 794 | 26.47 | 0.93391 |
| 873 | 29.10 | 0.92355 |
| 953 | 31.77 | 0.91850 |
| 1032 | 34.40 | 0.93919 |
| 1111 | 37.03 | 0.92616 |
| 1190 | 39.67 | 0.92259 |
| 1269 | 42.30 | 0.92899 |
| 1349 | 44.97 | 0.93784 |
| 1428 | 47.60 | 0.92561 |
| 1507 | 50.23 | 0.94220 |

**mean 0.93059, min 0.91455, threshold 0.98 — FAIL.** Full data:
`~/phase4_out/wp5/wp5_parity.json`.

### Root cause (found by running the test, not by code review)

`v16_compose.py`'s own comment (lines 40-47) claims the live pipeline's
per-word timing "never [has] an intra-cue gap ... and always [has] >=50ms
between cues", so `CAPTION_COMBINE_MS = 40` was picked to sit strictly
between those two bounds and reproduce the Python pass's cue groups
exactly. **That claim does not hold on the real fixture.** Checked the
real 119-word track exported from this run
(`~/phase4_out/wp5/short.short.props.json`): word-to-word gaps range 0ms
to 1120ms, and **83 of 118 consecutive gaps are <=40ms** — not just
within-cue gaps, but most inter-cue gaps too. Feeding that real track into
`@remotion/captions`' `createTikTokStyleCaptions` (checked directly,
`node` + the installed `@remotion/captions` package) confirms the result:
**all 119 words collapse into a single page spanning the whole 49-second
track**, word-concatenated with no spaces
(`"Youcanstandonafrozenlake,yetglideacross..."`). `Captions.tsx` then
displays that one (wrong, overflowing, unstyled) page for the entire
video regardless of the actual current frame — confirmed visually: frames
81 (t=2.70s) and 240 (t=8.00s) render **identical** caption text, while
the correct per-frame Python captions are "YET GLIDE ACROSS" and "THE
TEXTBOOK ANSWER BLAMES" respectively (see
`~/phase4_out/wp5/samples/{short,ref}_f_{81,240}.png`). This is a real
functional bug in the caption-grouping threshold assumption, not the
encode/film-grain decorrelation the script's own comments flagged as the
expected risk — frame 2 (before any caption appears in either version)
scores 0.971, close to the threshold, which is consistent with grain/
re-encode alone costing a few points of SSIM; the ~0.91-0.94 scores on
every captioned frame are the broken-caption bug on top of that baseline
loss. Not fixed in this run — out of scope per the launch brief ("report
the gap"), and AGENTS.md's fallback-change-needs-approval rule plus the
"minimum Claude calls" budget argue against an unreviewed same-session
patch to a load-bearing-adjacent rendering path. Whoever picks up the fix:
the real per-word gap distribution needs to drive either a much smaller
`combineWithinMs` or (more probably correct) a grouping key derived
directly from the Python pass's own cue boundaries (`cue` field already
present in `assembly_report.json`'s `caption_overlays`, but dropped by
`build_caption_track` — it only keeps `text`/`startMs`/`endMs`) rather than
inferring groups from timing gaps at all.

### Render-time note

308.5s to render the whole `Short` composition vs 164.4s for the
fixture's own recorded Python assembly pass (`pipeline_report.json`
`timings.assembly_s`) — slower, not faster, so the DESIGN §15.2 "[target]"
render-time line also misses on this measurement. Not a clean comparison
either way: `short.mp4`'s 308.5s includes one `bundle()` webpack cold
start inside the measured window (the thing `render_short.mjs`'s own
header comment says the pre-bundling is supposed to amortize across many
calls — a single one-shot full-video render doesn't get that benefit), and
164.4s is Python assembly alone, not a full comparable pipeline stage
list. Reported as measured, not adjusted, per the brief ("WP5 measures it
first" — DESIGN.md line 813).

## Verdict and disposition (per the launch brief's branch for a parity FAIL)

Parity does **not** reach 0.98. Per instruction and per `v16_compose.py`'s
own stated design intent: **the Python caption/assembly pass
(`engine.v14_assembly.assemble`) stays the default** — unchanged by this
run, still the only path `v15_pipeline.run_pipeline` calls.
`engine.v16_compose` and the `Short`/`Captions`/`Sting`/`Outro` Remotion
components are landed **behind a flag** in the sense that matters: grepped
the whole tree, `v16_compose` has **zero callers** outside its own tests
and `bench/ab/wp5_parity.py` — nothing in `mission_run.py`,
`mission_stills.py`, or `v15_pipeline.py` reaches it, so there is no
runtime toggle needed to keep it off; it is simply not wired in. DESIGN's
"the Python caption pass is retired only after parity" condition is
unmet, and per this run's brief that retirement is explicitly out of
scope regardless (a bigger step than this WP). The WP5 code itself —
`<Series>` scene sequencing, Sting/Outro overlays, the pre-bundled
renderer driver — is real, tested, and committed; only the caption
grouping needs a fix before another parity attempt.

## Secret scan / `.env`

`git diff --cached` of the staged WP5 files, grepped for the standard
key-prefix/assignment patterns (`sk-or-v1-`, `AIzaSy`, `hf_`, `nvapi-`,
`gsk_`, `xai-`, `sk-ant-`, `sk-proj-`,
`(api_key|secret|password)[:=]"..."`): clean, zero hits. `.env` and every
`.env.bak*` file: untouched.

## Housekeeping

`~/phase4_out/wp5/` trimmed to ~27MB: `wp5_parity.json` (full 20-row
result), `short.short.props.json` (the real exported Short props, used for
the root-cause diagnosis above), and `samples/` (4 representative
short-vs-ref frame pairs: 2, 81, 240, 556 — includes the no-caption
near-match frame and three of the broken-caption frames). The full
`short.mp4` (271MB) and the full 20-frame `short_frames`/`ref_frames`
directories (144MB combined) were deleted after the SSIM numbers were
captured into `wp5_parity.json`. `/tmp/wt_wp5_baseline` worktree removed
after use. No other large work dirs created.

## Next

Fix the caption-grouping bug (see Root cause above — likely: group by the
Python pass's own `cue` id rather than inferring from timing gaps), re-run
`bench/ab/wp5_parity.py` for real, and only then reconsider wiring
`v16_compose` into the live pipeline behind an explicit opt-in. Until then
this WP is **landed-not-adopted**: code committed and tested, Python path
still default, real parity gap documented. Then resume the re-sequenced
plan: WP12 (2-video cap) -> WP13 (2-topic cap) -> WP14.
