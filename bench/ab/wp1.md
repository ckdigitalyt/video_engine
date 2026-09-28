# WP1 acceptance: V15 plan + plate QA + judge through the LLM adapter (blackhole_clocks)

Run 2026-09-28, default chain = Claude CLI (sonnet). Artifacts: `~/phase4_out/wp1/` (`ledger.jsonl`, `report.json`, `judge_sheet.jpg`, `plate_sheet*.jpg`, `frame_*s.jpg`, `pipeline_run.log`).

| stage | provider/model | latency | list-price equiv. | result |
|---|---|---|---|---|
| visual_plan (forced fresh, separate cache) | claude_cli/sonnet | 13.8 s + 13.9 s (V15's own validate-and-retry loop used the 2nd call) | $0.026 + $0.027 | valid plan, 15 shots, `source: llm_retry` |
| plate_qa (1st sheet) | claude_cli/sonnet | 8.9 s | $0.031 | flagged plates #2 and #14 as `text` |
| plate_qa (after regeneration) | claude_cli/sonnet | 4.9 s | $0.011 | both still `text` -> HOLD |
| final_judge | claude_cli/sonnet | 18.3 s | $0.025 | `hook_stops_scroll:false`; #1, #5 subject_unrecognizable, #14 empty_or_flat -> HOLD |

Total 5 calls, about $0.12 list-price equivalent, no retries, no fallback used. Ledger written to `illustrated_engine/build/llm_ledger.jsonl`.

## Reading the result
- The adapter path works end to end: schema-validated `plate_qa` / `final_judge` output, Read-tool vision via the Claude CLI, ledger, cache.
- **Plate QA now actually runs.** In the Phase 2 baseline it was silently skipped (Gemini 20 RPD quota) and a watermarked plus a garbled-text plate shipped as PASS. With Claude it catches them, regeneration (NIM/Pollinations) does not fix them, and the gate returns HOLD. That is the correct verdict; WP2 makes "QA did not run" a HOLD as well.
- The judge's findings match the contact sheet (frame 1 is a statue-like spire under the hook text; frame 14 is mostly empty; frame 9 repeats frame 8).
- Rendering was repeated only because the regenerated plates changed scene hashes (~16 min wall, of which 8 min Remotion).
- Baseline comparison: V15 baseline blackhole was PASS (plate QA skipped, 1033 s); this run is HOLD (plate QA + judge ran, 937 s).

## Not covered
- The A/B on benchmark topics 1-3 (DESIGN 15.1) is a WP4 checkpoint; WP1 changes no visible output except that the V15 gate is now stricter because its judges actually run.
