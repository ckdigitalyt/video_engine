# WP2 acceptance: fail-closed QA

Run 2026-09-28. No Claude call, no render, no image call (unit/fixture proof and a re-gate of the existing Phase 2 blackhole artifacts). Samples: `~/phase4_out/wp2/`.

## Required behaviours
| requirement | proof | result |
|---|---|---|
| "plate QA did not run" (`checked:false`, missing, or `--no-plate-qa`) => HOLD | `test_plate_qa_not_run_is_hold` (None, `{}`, `{checked:false}`) | HOLD, reason "plate QA did not run: ..." |
| Phase 2 watermark plate => FAIL | `test_watermark_plate_fails_even_when_qa_passed_or_skipped` (fixture = edge strips of the shipped `c0e3b646508cd5f1.png`, "pollinations.ai") | FAIL, both when plate QA passed and when it never ran |
| clean plate is not flagged | `test_ocr_filter_hits_watermark_not_clean_plate`; OCR over 40 random cached plates: 1 hit (the watermark), 0 false positives, 1 unreadable file reported as unverified | ok |
| one critical judge frame fails | `test_one_critical_frame_fails` (text_garbled / watermark / overlap); soft issues keep the 2-frame HOLD rule | ok |
| right rail + caption safe zone | `test_right_rail_text_box`, `test_caption_safe_zone_and_rail` | ok |
| Phase 2 blackhole final now fails | `bench/ab/wp2_regate.py ~/phase2_out/e2e_blackhole` -> `regate_phase2_blackhole.json`; full `run_gate(use_judge=False)` on the same dir -> `run_gate_phase2_blackhole.json` | **PASS -> FAIL** |

## Why the Phase 2 blackhole fails now (was PASS)
- `plates`: `c0e3b646508cd5f1.png` (B7_S1, Pollinations) is stamped "pollinations.ai" -> critical; and "plate QA did not run: judge unavailable" (the Gemini quota skip) -> unverified.
- `text_bounds`: 9 headline/label/number boxes inside the right UI rail (e.g. "THE BLACK HOLE" x 605-1010, y 794-878).
- `caption_safe`: passes (widest caption ink ends at x=920 < 930).
- The garbled pocket-watch numerals (`40c775abbfd1e24a`) are a vision/judge finding (WP1 run: plate QA flagged it as `text` with Claude); OCR does not catch them and is not meant to.

## Tests
- `illustrated_engine/tests/test_wp2_gate.py`: 11 tests, all pass (also under pytest); `tests/test_v15.py` all pass; illustrated_engine/tests 31 passed.
- Full root suite `pytest` (before = HEAD 1198afa in a clean worktree, after = this commit): both **58 failed, 5 errors**, failure sets IDENTICAL (`suite_before.txt` / `suite_after.txt`). New failures: none. NOTE: the "known baseline" in PROGRESS (4 subtitles + provider_interfaces + engine_hardening) understated the real pre-existing set: it spans 17 files (visual_director 16, pixabay 7, effects 6, renderer 6, timeline_builder 5, ...). `tests/test_llm_adapter.py::test_director_shims_keep_legacy_contract` fails in the full run but passes alone (test-order dependence, present before WP2 too).
- `mission_run.py --help` and `python -m engine.v15_pipeline --help` run; `engine.v15_pipeline` imports.

## Judgement calls / deviations from DESIGN 15.2 row WP2
- Kept the filenames `v15_gate.py` / `v15_plates.py` (no `v16_*` rename): renaming before a v16 pipeline exists only churns imports.
- Caption "safe zone" enforces the horizontal frame and the right rail; DESIGN §7's top-220/bottom-1440 insets and the 84 px caption-size rule are deferred to WP6/WP5, because the V15 caption band sits at y~1500-1600 and would fail every render for a layout WP6 replaces.
- The gate re-runs OCR on every plate itself instead of trusting the pipeline flag, so `--no-plate-qa` cannot ship a stamped plate.
- Verdicts gained `FAIL` (confirmed defect) beside `HOLD` (unverified / soft). Consumers only test `== "PASS"`.

## Consequences / open issues
- Every V15 render will now HOLD on the right rail: labels are right-aligned at x~1010, y~800. Expected until the WP6/WP7 layout work.
- OCR reads ~2 s per new plate (cached afterwards); tesseract CLI is a system dependency (missing => plates check HOLDs, never passes).
- OCR only catches known stamp tokens / domains by design; other watermarks rely on the vision call.
