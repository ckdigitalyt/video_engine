# Changelog (shorts-v3, Phase 4)

## WP0 — Baseline + benchmark harness skeleton
- Added `bench/quality/` (runner, frozen topic packs 1–3) and `bench/ab/baseline.{md,json}` freezing V15 scores for ice, cell and blackhole from existing reports. No pipeline change.
- Topic packs 1 (birds) and 3 (time crystals) are worker-curated with `verified:false` claims (no web in Phase 4); pack 2 is the verified Tunguska facts from V15. Source-check before WP4 scoring.

## WP1 — LLM adapter + Claude CLI default
- New `llm/` package (repo root) with `ask(stage, prompt, schema=, images=)`, `configs/llm.yaml` (validated at load: unknown stages/providers/pinned-without-model fail loudly), providers `claude_cli` (default), `gemini` and `openrouter` (ported, `enabled:false`).
- Retry/repair/quota per DESIGN §2.4: transport ×2 (5 s, 20 s backoff), one schema-repair round then next chain member, quota → persisted cooldown (`build/llm_state.json`, default 1 h, Claude reset time parsed), auth → immediate `LLMUnavailable`, output always re-validated with `jsonschema`. Cache `build/cache/llm/`, usage ledger `build/llm_ledger.jsonl` (no prompts, no keys). Gemini uses the `x-goog-api-key` header so error text can never echo the key.
- `engine/director.text_ask/vision_ask` are shims over `ask()` (same None-on-failure contract, new optional `stage=`); V15 plan → `visual_plan`, plate QA → `plate_qa` (schema-validated), judge → `final_judge` (schema-validated), semantic QA → `fact_check`, other vision callers → `vision_misc`. `semantic_verify` gates on `llm.client.available()` instead of Gemini/OpenRouter keys. Removed: `_vision_gemini/_vision_glm/_text_gemini/_text_glm` (ported into `llm/providers/`).
- **Flag for owner (AGENTS.md §15.3 item 1):** the V15 judge/plan default chain changes from Gemini→GLM to Claude CLI (`plate_qa` chain: sonnet → haiku). Gemini/OpenRouter remain implemented but disabled. `mission_run.py`'s own `src/providers` chain is untouched.
- Claude CLI structured-output payload field pinned as `structured_output` (recorded fixture `tests/fixtures/llm/`).
- DeepSeek removed from tracked code/config (CI env var, provider-registry doc string, schema descriptions, stale comments, `render_black_hole.py` → zai, dual-review labels → ZAI GLM). `cli.py semqa` had a latent `KeyError` (read `res["deepseek"]`; `semantic_qa` returns `judges`) — fixed. Kept on purpose: `leak_scan.MODEL_TOKENS` still blocks "DEEPSEEK" from ever being drawn on screen (a guard, not a provider). Historical markdown/reports/logs are untouched.
- Known: `research/phase2/llm_compare.py` calls the removed private `_text_gemini/_vision_*` helpers (one-off Phase 2 benchmark script; not part of the pipeline).
