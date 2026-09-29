# WP6 acceptance: brand bible

Run 2026-09-29. No Claude call, no network image call. Samples: `~/phase4_out/wp6/`.

## Required behaviours (DESIGN §15.2 row WP6)
| requirement | proof | result |
|---|---|---|
| `brand/<chosen>/` | `brand/ink_ember/brand.yaml` (+ `grade.cube`) — DESIGN §7.1/§17 option A "Ink & Ember" | present, validates clean |
| `engine/brand.py` | `load_brand`/`validate_brand`, `role_hex`/`role_rgb`/`resolve`/`renderer_roles`, `lint_props`/`assert_no_literal_hex`, `rail_safe_x1`, `generate_cube`/`cube_sha256`/`verify_cube_hash`/`apply_lut`, `sting_audio`/`ink_bloom_overlay`/`seal_badge`/`render_cover` | present, tested |
| LUT at ingest | `engine.v15_plates.generate_plate` grades every plate through `brand.apply_lut` before caching; `lut_sha256` recorded on the plate meta; `PLATE_VERSION` bumped so pre-WP6 cache entries regenerate | wired, tested against a fake provider |
| roles-only props (no literal hex) | `lint_props`/`assert_no_literal_hex` | mechanism implemented + tested; enforced on the surfaces WP6 owns (captions, sting, outro, cover) — **not yet enforced on `v15_shots.compile_shot`'s own output** (deviation, see below) |
| brand caption style | `engine.captions.chunk_png`/`_chunk_font` source colour (`caption_fill`/`caption_active`) and font (`caption` role = Archivo Black) from the brand, not the per-story bible | wired, tested (rendered pixel check) |
| sting + outro + cover | `brand.sting_audio` (procedural ink-bloom scratch + timpani), `brand.ink_bloom_overlay`, `brand.seal_badge`, `brand.render_cover` | generators present, tested; **not yet called from the render/assembly timeline** (see below) |

## Acceptance tests (DESIGN §15.2 "tests" column)
| test | proof | result |
|---|---|---|
| props lint: no literal hex | `test_lint_props_catches_literal_hex`, `test_lint_props_allows_role_names`, `test_lint_props_ignores_non_colour_keys` | pass |
| LUT-hash test | `test_lut_hash_matches_recorded_sha256` (committed `grade.cube` reproducible from `brand.yaml`'s own params), `test_apply_lut_grades_and_returns_matching_hash` (ffmpeg `lut3d`, real pixel change), `test_plate_ingest_records_lut_hash` (through the actual `generate_plate` ingest path with a fake provider) | pass |
| font licence files present | `test_font_licence_files_present` (every font role's `.ttf` and `OFL_*.txt` exist on disk), `test_ink_ember_validates_clean` (schema validation includes this check) | pass |

## The WP2 right-rail HOLD
`bench/ab/wp2.md` documented every V15 render HOLDing on `text_bounds` because headline/label/number boxes reach x≈1010 at y≈760+ (gate rail: `x>930, y>760`). Root cause: `v15_shots._label`/`_text_layer`/`compile_process_shot` centred/right-anchored text against the outer safe frame (`x1<=1010`) with no awareness of the narrower UI rail beneath y=760.

Fix: all three now call `brand.rail_safe_x1(box_y0, box_y1, default_x1)` and, if the box's y-range dips into the rail, either re-fit narrower (centred text: headline/number/zoom-level labels, process-shot step chips) or clamp the anchor (leader labels), instead of overflowing.

- Reproduced the **exact** documented case (`test_label_clears_right_rail_black_hole_case`): a subject bbox that previously produced "THE BLACK HOLE" at box `[605, 794, 1010, 878]` (flagged by `v15_gate._box_problems`) now produces `[525.3, 794.0, 930.0, 878.0]` — `v15_gate.check_text_bounds` passes.
- Also verified: a long bottom-zone headline (`test_headline_bottom_zone_clears_right_rail`), a 5-step process chip chain (`test_process_step_chip_clears_right_rail`), and that top-zone text (above the rail) is untouched (`test_headline_top_zone_unaffected`).
- **Is the right-rail HOLD resolved?** The specific layout bug that caused it is fixed and unit-tested against the documented failure case and three more scenarios. **Not done this pass:** a fresh end-to-end render + re-gate of a real story through the fixed shot compiler (would need image-provider calls; kept out of "minimum Claude/API calls"). `.jade/phase4_runwp7_prompt.txt` already anticipates this — WP7 is instructed to "finish that fix here" if it isn't fully proved, and to "re-run the Phase 2 blackhole re-gate ... and report PASS/FAIL explicitly." Recommend WP7 (or a short follow-up) do that full-pipeline confirmation.

## Tests
- `illustrated_engine/tests/test_wp6_brand.py`: 19 new tests, all pass (also under pytest).
- `illustrated_engine/tests/` full run: 97 passed (1 known order-dependent flake, `test_wp3_voice.py::test_live_lexicon_fixes_tyrannosaurus`, passes 1/1 in isolation — same class as the pre-existing `test_llm_adapter` shim flake noted since WP1/WP2, not a WP6 regression).
- Full root suite `pytest` (before = HEAD `aceeee6` in a clean detached worktree `/tmp/wt_wp6_baseline`, after = this commit): 1259 passed/58 failed/5 errors (before) vs 1263 passed/58 failed/5 errors (after) — the 4-test delta is skip-count noise (8 skipped before vs 4 after, order/network-dependent), **failing-id sets are byte-identical, 63/63, zero new failures, zero fixed**. `suite_before.txt` / `suite_after.txt` kept in `~/phase4_out/wp6/`.
- Secret scan (`git diff` for the WP6 files against API-key-prefix patterns `sk-or-v1-,AIzaSy,hf_,nvapi-,gsk_,xai-,sk-ant-,sk-proj-`): one substring hit, `PROVIDER_ORDER = ("nvidia_nim", "siliconflow", "hf_serverless", ...)` in unrelated pre-existing code (`hf_` matches inside `hf_serverless`) — not a secret, false positive. `.env` untouched.

## Judgement calls / deviations from DESIGN §15.2 row WP6
- Kept `v15_plates.py` (no `v16_plates.py` rename) — same reasoning as WP2's `v15_gate.py`: renaming before a v16 pipeline exists only churns imports.
- **Scope decision (flagged):** `engine/v15_style.py`'s 5 per-story "decks" (vintage_ink, nocturne_gouache, blueprint, archival_etching, watercolor_atlas — each its own palette, plus a zone-luminance-adaptive ink choice in `v15_shots._inks`) are not replaced with brand roles this pass. DESIGN §7.2 ("stories cannot define a look... the shot compiler rejects any literal colour... in scene props") implies this should eventually be roles-only too, but that means either dropping the per-topic visual-variety/adaptive-legibility system WP1-5 already depend on and test against, or redesigning it to choose among *roles* rather than hex — either is materially bigger than fits in one WP, and `mission_run.py` must stay runnable end-to-end at every commit. `lint_props`/`assert_no_literal_hex` are real and tested; they are just not yet wired into `compile_shot`'s own layer payloads. OWNER FLAG if full pipeline-wide "no literal hex, anywhere" enforcement is wanted sooner than a later layout WP.
- Sting/outro/cover generators exist, are tested, and are NOT yet called from the render/assembly timeline (no code inserts a sting clip, an outro card or a cover frame into the final video). DESIGN's own acceptance for this row is two-step ("A/B #2: on-brand frames; safe zones pass; owner eyeball" — a later checkpoint), so this is left for the WP that next touches assembly rather than added as a rushed extra wire-up here.
- `brand/ink_ember/sting.wav` is a deterministic build artifact of `brand.sting_audio()` (pure function of `brand.yaml`'s `sting.dur_s`) and is git-ignored (`*.wav`, matching how WP3's voice samples are handled) rather than committed; regenerate on demand. `grade.cube` (not `*.wav`) IS committed since `apply_lut` reads it directly from `brand/<id>/` at render time.
- Brand identity: option **A "Ink & Ember"** per the owner's round-3 decision (PROGRESS.md, 2026-09-28) — this was already decided, not a fresh judgement call this run.

## Consequences / open issues
- Cached plates from before this commit are `plate/1` (ungraded); `PLATE_VERSION` bump means they will regenerate (re-download/re-generate through the provider chain) rather than silently ship ungraded. No existing cache was deleted.
- `v15_shots.compile_shot`'s headline/label/number/process-chip fill colours still come from the per-story bible (literal hex), not brand roles — see the deviation above.
- Full pipeline-wide right-rail proof (a fresh render + re-gate) is deferred to WP7 per its own prompt.
