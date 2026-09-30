# WP7 acceptance: templates + pacing

Run 2026-09-29. No Claude call, no network image call, no image-provider call.
Samples: `~/phase4_out/wp7/` (Remotion stills, right-rail regate, A/B #3 pacing).

## Required behaviours (DESIGN §15.2 row WP7 / §8)

| requirement | proof | result |
|---|---|---|
| the §8 template library (>= KINETIC_CLAIM, BIG_NUMBER, MAP_PIN, TIMELINE, SCALE_COMPARE, PARALLAX, LOOP_BRIDGE) | `engine/v16_plan.py` `TEMPLATE_LIBRARY` — 11 named templates (the 7 required plus HOOK_PLATE, PLATE_PUSH, ZOOM_THROUGH, PROCESS_OVER_PLATE, reused from V15); each declares slots via its `shot_kind`, `duration_bounds`, `motion_signature_s` (<=1.0s, DESIGN §8.1), `interrupt_type`, `content_signal` | present, tested (`test_library_has_the_required_templates`, `test_every_template_declares_a_sub_1s_motion_signature`) |
| new shot compilers | `engine/v15_shots.py` `compile_kinetic_claim_shot`, `compile_big_number_shot`, `compile_map_pin_shot`, `compile_timeline_shot`, `compile_scale_compare_shot`, `compile_parallax_shot`, `compile_loop_bridge_shot` — all reuse existing plate/text/camera primitives (§8.1 "one plate can drive three templates"), no new image-generation calls | present, tested, each produces valid Scene IR and clears `v15_gate.check_text_bounds` |
| planner v2 rules | `engine/v16_plan.py` `assign_templates`/`validate_templates`: content-signal mapping (number->BIG_NUMBER, place->MAP_PIN, time span->TIMELINE_DEEPTIME, compare->SCALE_COMPARE, process->PROCESS_OVER_PLATE, scale->ZOOM_THROUGH), no template twice in a row, >=5 distinct templates, <=35% screen-time share per template, frame 0 = HOOK_PLATE/KINETIC_CLAIM, last = LOOP_BRIDGE, ties broken by hashing `story_id` (never random) | present, tested |
| 1.8s hold gate | `engine/v15_gate.py` `check_pattern_interrupt` (`MAX_HOLD_1_8_S = 1.8`), additive to the existing `check_visual_hold` (`MAX_HOLD_S = 4.5`, kept as-is — see deviation below); `engine/v15_pipeline.py` `split_long_holds` generalized to take `max_hold_s`/`margin_s` and made **iterative** (was single-split-per-shot; a shot with more than one long gap now gets more than one cut) | present, tested, proven on 3 real stories below |
| `npm i @remotion/lottie@4.0.529`, `scenedetect` | neither installed | **deliberately skipped** — none of the 7 required templates need Lottie (DIAGRAM_ARROWS, the one template that would, is out of this pass's required set); pacing/hold metrics come from the compiled Scene IR's own duration/visibility data (exact, free), not from `scenedetect` on encoded pixels — cheaper and just as accurate for this proof. Flag if either is wanted for a later WP. |

## Acceptance tests (DESIGN §15.2 "tests" column)

| test | proof | result |
|---|---|---|
| no repeats | `test_no_two_templates_repeat_back_to_back`, `test_heavy_repeat_input_still_resolves_to_zero_errors` (20-shot all-identical stress input) | pass |
| >= 5 templates | `test_at_least_five_distinct_templates` | pass |
| frame0/last | `test_frame_zero_is_hook_plate_or_kinetic_claim`, `test_last_shot_is_loop_bridge` | pass |
| one Remotion still per template | `~/phase4_out/wp7/stills/{HOOK_PLATE,KINETIC_CLAIM,BIG_NUMBER,MAP_PIN,TIMELINE_DEEPTIME,SCALE_COMPARE,PARALLAX_25D,LOOP_BRIDGE,PROCESS_OVER_PLATE,ZOOM_THROUGH}.png` — real `engine.scene_renderer frame` (Remotion `still`, Chrome headless) renders of each compiled Scene IR, through the **actual production render backend** (the generic `SceneComposition` `remotion_project` already used by `mission_run.py`'s render stage — see deviation below on why no new `templates/*.tsx`) | pass, 10/10 render `ok:true` |
| planner determinism | `test_assignment_is_deterministic_not_random` (same story -> byte-identical template sequence) | pass |
| no incompatible assignment | `test_repair_never_assigns_zoom_through_or_process_to_an_incompatible_shot`, `test_write_back_retargets_kind_to_the_assigned_templates_shot_kind` — regression coverage for two real bugs found and fixed this pass (see below) | pass |

`illustrated_engine/tests/test_wp7_templates.py`: 23 new tests, all pass. `illustrated_engine/tests/` full run: 120 passed (97 before WP7 + 23 new).

## The WP2/WP6 right-rail HOLD — full proof (`bench/ab/wp7_regate.py`)

WP6 fixed the layout bug and unit-tested it against **one** of the nine documented `bench/ab/wp2.md` failures. This run reproduces **all nine**, through the current code, via the exact reconstruction WP6's own test used (a subject bbox chosen so `_label`'s box-height formula reproduces the documented box's y-range) plus the two non-label (`_text_layer`) cases:

```
$ python3 bench/ab/wp7_regate.py
```

**Verdict: PASS, 9/9.** Every one of the documented boxes — `B1_S1.label`, `B2_S2.label`, `B3_S1.label`, `B3_S2.label`, `B5_S2.number`, `B6_S1.label`, `B6_S2.label`, `B7_S1.label`, `B7_S2.headline` — now clears `v15_gate._box_problems` (new right edges land at x<=930, down from the old x=1010/998/995). Full before/after boxes in `~/phase4_out/wp7/regate_wp7_blackhole.json`.

Not done this pass (same reasoning as WP6): an actual end-to-end render of `blackhole_clocks` through `mission_run.py` (needs image-provider + voice calls). This regate is the "equivalent cheap fixture" the WP7 prompt allows in place of that.

## A/B #3: median shot, max hold, template diversity (`bench/ab/wp7_ab3_pacing.py`)

Run on the 3 WP0 baseline topics (`ice_slippery`, `cell_scale_dive`, `blackhole_clocks`), entirely offline: `v15_plan.fallback_plan` (zero LLM calls) -> `v15_pipeline.shot_timeline` + `split_long_holds(max_hold_s=1.8)` (real pipeline logic, synthetic per-word timing at the same `WORDS_PER_SEC` cadence `v15_plan`/`v16_plan` already calibrate to — see caveat below) -> `v16_plan.assign_templates` -> `v15_shots.compile_shot` -> `v15_gate.check_pattern_interrupt` / `check_text_bounds`.

```
$ python3 bench/ab/wp7_ab3_pacing.py
```

| topic | shots | templates used | median shot | max hold | 1.8s gate | right rail |
|---|---|---|---|---|---|---|
| ice_slippery | 34 | 9 | 1.10 s | 1.72 s | **PASS** | PASS |
| cell_scale_dive | 34 | 8 | 1.23 s | 1.72 s | **PASS** | PASS |
| blackhole_clocks | 35 | 9 | 1.10 s | 1.73 s | **PASS** | PASS |

Planner v2 `errors: []` for all three (no repeats, >=5 distinct, <=35% share, frame0/last) on every run. Every gate check is a real check against real compiled Scene IR, not a hand-picked fixture.

- **Max hold <=1.8s: PASS** (target met, 1.72-1.73s worst case across 103 shots).
- **Median shot 1.2-2.0s: partially met.** 1.10-1.23s — at or just under the band's *lower* bound, not inside it. The iterative `split_long_holds` (needed to hit the 1.8s hold cap) cuts more aggressively than the median target alone would require; the two targets pull in the same direction but 1.8s dominated. A follow-up could widen `margin_s` slightly so cuts land nearer 1.5s apart rather than the current ~1.1s, without giving up the hold guarantee — not done here to avoid re-opening the hold-cap tuning this session.
- **>= 5 distinct templates: PASS** (8-9 of 11 used per topic, well above the floor).

**Caveat (flagged, not hidden):** per-word timing here is synthetic (`i / WORDS_PER_SEC`), not real voice-synthesis timing — the same approximation `engine/v16_plan.py`'s own docstring already flags. Real Kokoro+whisper timing (WP3) would very likely shift these numbers; this is a cheap, honest, reproducible proxy, not a substitute for a real render.

## Two real bugs found and fixed while building this proof

1. **`engine.scene_renderer.RemotionRenderer.render_frame`** called `remotion render --frame N`; this `@remotion/cli` version rejects `--frame` on `render` ("did you mean `--frames`?" — it's a `still`-only flag). The method's own docstring contract ("single frame still (png)") was correct, the implementation wasn't — it was unused until this pass needed real per-template stills. Fixed to call `remotion still`. This is the mechanism the 10 Remotion stills above were rendered through.
2. **`engine.v16_plan`'s repair passes could assign a template a shot's content can't back:** `ZOOM_THROUGH`/`PROCESS_OVER_PLATE` render `v15_shots` kinds needing `levels`/`steps` only a shot already of that original kind carries; `BIG_NUMBER`/`KINETIC_CLAIM` need `number`/`headline` content their compilers have no safe fallback for (an empty string crashes `textfit.fit_text`). Added `_compatible()`/`_generic_pool_for()`/`_safe_pool_for()`, used by every repair pass and the initial assignment; regression tests added (`test_repair_never_assigns_zoom_through_or_process_to_an_incompatible_shot`). Also fixed: `_write_back` now retargets a reassigned shot's `kind` to its template's `shot_kind` — without this the template tag was inert metadata and `compile_shot` kept rendering the original v15_plan kind.

## Judgement calls / deviations from DESIGN §15.2 row WP7

- **No new `templates/<Name>.tsx` React components.** DESIGN §1.1/§8.1 describes each template as "a typed Remotion component". The render architecture that exists today (and that `mission_run.py` actually uses) is ONE generic composition, `remotion_project/src/SceneComposition.tsx`, driven entirely by Python-compiled Scene IR props (`engine/scene_renderer.py`) — WP5 ("one-composition render") is what DESIGN's own plan names for the `Short.tsx`/`<Series>` rewrite, and it is still pending (not this WP). Building 11 parallel typed components ahead of that would duplicate what the generic composition already renders (AGENTS.md: "don't reimplement functionality... without a clear, stated reason") and would not be exercised by the actual pipeline. Templates are therefore Python-side: a `TemplateSpec` registry (`v16_plan.py`) + `v15_shots.py` compilers producing Scene IR the existing generic composition already knows how to render — the "one Remotion still per template" acceptance test is satisfied through that same real, production render path. OWNER FLAG if typed `.tsx` components are wanted specifically (e.g. ahead of WP5).
- **MAP_PIN has no Natural Earth basemap** (§8.2 lists it as the asset source) — a procedural pin marker + pulse ring drops onto the story's own plate/subject instead. **SCALE_COMPARE has no sourced silhouette art** ("bird vs T. rex") — proportion-accurate rounded rectangles stand in, sized from `shot["compare"]["a"/"b"]["scale"]` when a plan supplies it. Both are visually legible and gate-safe; neither is the richer asset DESIGN describes. Flag if real assets are wanted before these ship.
- **LOOP_BRIDGE's hook-context wiring is not connected to `v15_pipeline.run_pipeline`.** The compiler supports it (`sc['hook_plate']`/`sc['hook_camera']`) and degrades cleanly without it (a plain closing plate shot, not a pixel-matched loop) — same posture WP6 took with its un-wired sting/outro/cover generators. "Loop SSIM calibrated" (DESIGN's A/B #3 line) is therefore not measured this pass: there is no live pipeline path yet producing a real hook-matched loop frame to compare against frame 0.
- **`v16_plan.assign_templates` / the 1.8s `split_long_holds` are not wired into `v15_pipeline.run_pipeline` as the new default.** They are real, tested, and proven cheaply above, but flipping the live pipeline's default shot count from ~12-14 to ~34-35 per video changes downstream cost (more plate-cache lookups, though not necessarily more *generation* calls — split shots reuse the same `subject` text, and `_seed()` is deterministic on prompt text, so a repeat subject should hit the same cached plate) and is a bigger, riskier change than fits alongside inventing the templates themselves in one session. `split_long_holds(tl, timing)` (no `max_hold_s` arg) is byte-for-byte unchanged for the V15 pipeline's own default (4.4s, single-pass-equivalent output verified by the unchanged root-suite failing-id set below). OWNER FLAG if this should become the default path now rather than at a later WP.
- Kept `v15_shots.py`/`v15_gate.py`/`v15_pipeline.py` names (no `v16_` rename) — same reasoning as WP2/WP6.
- No fallback or retry path was removed or narrowed (image-provider chain, TTS chain, gate regeneration round, LLM adapter all untouched).

## Tests

- `illustrated_engine/tests/test_wp7_templates.py`: 23 new tests, all pass.
- `illustrated_engine/tests/` full run: 120 passed (97 before WP7, 0 regressions).
- Full root suite `pytest tests` (before = HEAD `edd7a45` in a clean detached worktree `/tmp/wt_wp7_baseline`, after = this commit): 58 failed/1259 passed/8 skipped/5 errors (before) vs 58 failed/1263 passed/4 skipped/5 errors (after) — the 4-test delta is skip-count noise (order/network-dependent, same pattern as WP6), **failing-id sets are byte-identical, 63/63, zero new failures, zero fixed**. `suite_before.txt`/`suite_after.txt` kept in `~/phase4_out/wp7/`. (`illustrated_engine/tests` is run and gated separately, as every prior WP — combining both directories in one `pytest` invocation causes an unrelated `sys.path` collision between the two repos' same-named `engine` packages; not a WP7 regression, noted here in case a future WP wants to fix the invocation itself.)
- Secret scan (`git diff` for the WP7 files against API-key-prefix patterns `sk-or-v1-,AIzaSy,hf_,nvapi-,gsk_,xai-,sk-ant-,sk-proj-`): clean. `.env` untouched.

## Consequences / open issues

- `engine.v15_pipeline.split_long_holds` gained a `margin_s` parameter (defaults to `min(1.5, max_hold_s/3)`, so its behaviour at the default `max_hold_s=4.4` is unchanged — verified against the root suite).
- `engine.v16_plan` is a new, currently-standalone module (not imported by `v15_pipeline.py`); next integration step is wiring it into the pipeline stage graph per the "not wired" deviation above.
- Next: WP9 (music/SFX/sting) per the owner's re-sequencing (`scripts/phase4_driver.sh`), or WP5 if `templates/*.tsx` / real hook-matched loop / live-pipeline pacing is prioritized first — OWNER FLAG above.
