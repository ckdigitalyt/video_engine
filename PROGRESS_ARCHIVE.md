# shorts-v3 Progress Archive

Full history moved out of PROGRESS.md (2026-09-30, token-optimization pass —
PROGRESS.md had grown to 43KB and every unattended worker read it in full at
the start of every WP run). Read this file only if you need the detail
behind an older decision; PROGRESS.md's condensed status table + the binding
owner-decision blocks are normally enough.

## Phase 1 (Gap Analysis) — COMPLETE 2026-09-27
- illustrated-engine confirmed as the live branch line; shorts-v3 created from checkpoint 6df5bc0.
- Headless claude CLI lockdown verified: `--strict-mcp-config --allowedTools "Read Grep Glob Bash Write Edit" --disallowedTools "Task Skill SendMessage CronCreate CronDelete CronList DesignSync EnterWorktree ExitWorktree ListAgents PushNotification RemoteTrigger ScheduleWakeup WebFetch WebSearch NotebookEdit"` (add WebFetch/WebSearch back for research phases). Note: --allowedTools is not a strict allowlist; --disallowedTools is the real restriction.
- AUDIT.md (330 lines): V15 already covers rendering/QA well; gaps are upstream (no story/hook/topic engine, no brand bible, thin pacing, small captions, generic music, Fish Audio free-tier risk).
- Security finding: commit `ef77f54` (2026-08-02) leaked a full `.env.bak` with 8 keys (DEEPSEEK/GEMINI/NASA/NVIDIA/PEXELS/PIXABAY/SLACK_APP/SLACK_BOT) into git history, confined to history (not current HEAD). Owner rotated all 8. Repo is public-ish (github.com:ckdigitalyt/video_engine.git) — history scrub (filter-repo/BFG) still worth considering if not already done.
- Owner decisions round 1 (2026-09-27): Fish primary + local fallback; brand must fit @most.amazing.wonders, Phase 2 analyzes channel via YouTube OAuth (upload-scope only); NVIDIA NIM not approved for production; OpenRouter GLM demoted, Claude becomes adapter default; DeepSeek removal queued as a Phase 4 task (tracked files only, not .env/server config).

## Phase 2 (Research) — COMPLETE 2026-09-28
- Hit the Claude 5-hour session limit once (2026-09-27 18:56 UTC), resumed via `claude -p --resume <session-id>`; a backgrounded e2e render had actually finished before the parent was killed, reused rather than re-run. Gap found: no check-in was scheduled for Phase 2 specifically, so the limit hit wasn't noticed for ~7.5h — later phases got explicit check-ins (later superseded by the deterministic driver).
- RESEARCH.md written. Fresh cold e2e (blackhole_clocks) PASSED but plate QA was silently skipped (Gemini 20 RPD quota) and a watermarked + garbled-text plate shipped — this is exactly what WP1/WP2 later fixed.
- Owner decisions round 2 (2026-09-28): voice provider-agnostic (Fish API + Kokoro am_michael), design must not rely on Fish free tier; dead SiliconFlow/HF replaced by local klein + Cloudflare Workers AI (owner added CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN to .env); topic engine driven by channel data (dinosaur/deep-time + spectacle physics, ~18x V15 Shorts); credential rule — never try a key against a service it wasn't issued for.

## Phase 3 (Design) — COMPLETE 2026-09-28 04:42 UTC
- DESIGN.md (815 lines, 15 Phase-4 work packages WP0-WP14) + 3 brand options (A Ink & Ember, B Deep Signal, C Wonder Almanac) + Fish vs Kokoro voice samples.
- Owner decisions round 3 (2026-09-28 04:54 UTC, Phase 4 greenlit):
  1. Brand: A "Ink & Ember" + C's boxed keyword hook labels (t=0-1s) + dark-plate variant for space topics; no mascot; all brand params config-driven (brand/<name>/yaml, no literals in code).
  2. Voice: Kokoro sole channel voice; Fish disabled by default (FISH_PLAN gate kept in code). Owed: 3-voice/2-speed sample set (delivered in WP3), pronunciation lexicon + whisper round-trip QA (delivered in WP3).
  3. DESIGN §15.3: Claude adapter default approved; drop SiliconFlow/HF, NIM benchmark-only; retire the Python caption overlay only after A/B parity (WP5's job); git-tag old paths before removal.
  4. Secrets: tmp/tempenv.txt shredded; never print secret values, masked output only; owner edits .env himself.
  5. Phase 4 order = DESIGN.md §15.2; small tested commits; PROGRESS.md updated before each package; DeepSeek removal is part of WP1.

## Phase 4 run 1 (2026-09-28) — WP0 + WP1
- WP0 `f3022a7`: baseline.md/json + bench/quality harness; topic packs 1/3 flagged verified:false (source-checked later, 2026-09-29).
- WP1 `cacb1c4`+`be12e92`+`250d4bd`+`d0a6c36`: Claude-CLI-default LLM adapter (`llm/`, `configs/llm.yaml`), DeepSeek removed from tracked config/code, Gemini/OpenRouter ported but disabled. Acceptance (blackhole, 5 Claude calls, ~$0.12): correctly HOLDs once plate QA actually runs (catches the Phase-2 watermark/garbled plates).
- OWNER FLAG (still live): default judge/plan chain is Claude CLI, no auto-fallback to expensive models beyond haiku.

## Phase 4 run 2 (2026-09-28) — WP2 `cf70724`
- Fail-closed QA: gate now OCRs every plate itself (tesseract, edge strips, stamp/domain tokens), one critical judge frame fails the video, caption safe-zone + right-rail checks added. `checked:false` => HOLD; Phase-2 watermark fixture => FAIL; Phase-2 blackhole re-gated PASS→FAIL (stamped plate + 9 right-rail boxes).
- OWNER FLAG: every V15 render now HOLDs on the right rail (x~1010,y~800) until WP6/WP7 re-layout — the blocker WP6/WP7 later fixed.
- Corrected the test-failure baseline count: pre-existing root-suite failures span 17 files (far more than an earlier 5-file estimate).

## Phase 4 run 4 (2026-09-28) — WP3 `45e69b5`
- Voice layer: Kokoro sole voice, Fish paid-gated, lexicon (15 entries), faster-whisper round-trip QA (WER<=0.03), whole-video Kokoro fallback. Topic-1 WER 0.000 PASS.
- Caption-timing target (p90<=0.12s) NOT verified — only measured against synthesis-truth (partly circular) or a whisper model (model disagreement, not ground truth); needs Fish paid timestamps or hand labels.
- 3-voice/2-speed samples delivered for owner pick (am_michael/am_onyx/bm_lewis); onyx/lewis picked from F0+WER numbers only, phonemes never listened to.

## Phase 4 run 5 (2026-09-28) — WP4 code `81812b3`+`411d5be`+`487f95a`
- Story engine S1-S4 (research→facts w/ quote check→script→critic→rewrite→fact_check→metadata), 29 tests.
- Live tunguska script 3/3 HOLDs at the critic (mean 3.5→3.75, bar 4.0) — OWNER DECISION needed on the bar; not resolved by code, later made moot by the 2026-09-29 re-sequencing/owner go.
- Source-check of topic packs 1/3 not finished this run (done later, 2026-09-29, see PROGRESS.md's source-check commit `aceeee6`).

## Phase 4 run 6 (2026-09-29) — WP6 `62be5eb`
- Brand bible: brand/ink_ember/ (brand.yaml, grade.cube), engine/brand.py (roles, LUT, props lint, sting/outro/cover), right-rail fix in v15_shots.py (rail_safe_x1, re-fit narrower instead of overflow).
- Not proven this pass: a full pipeline render/re-gate (deferred to WP7 to avoid extra image/Claude calls) — later done for real in WP7/WP9/WP10.

## Phase 4 run 7 (2026-09-30) — WP7 `3fec714`
- Template library: v16_plan.py planner v2 (11 templates incl. all 7 required: KINETIC_CLAIM/BIG_NUMBER/MAP_PIN/TIMELINE/SCALE_COMPARE/PARALLAX/LOOP_BRIDGE), 1.8s pattern-interrupt gate, iterative hold-splitter.
- Right-rail HOLD proof: all 9 WP2-documented failing boxes now clear `check_text_bounds` — the WP2/WP6 blocker is fixed.
- 2 real bugs found+fixed: scene_renderer was calling a rejected `remotion render --frame` (needs `still`); planner could assign a template a shot's content can't back (added compatibility gating).
- Deferred (flagged, not silent): no typed `.tsx` template components yet (WP5's job); MAP_PIN/SCALE_COMPARE use procedural stand-in art; planner/hold-splitter proven standalone, not yet wired as v15_pipeline's live default.

## 2026-09-29: source-check + facts corrections
- Topic packs 1 (birds/dinosaurs) and 3 (time crystals): all 12 claims checked against primary/reputable sources (`bench/ab/source_check.md`); 5 claims (3 in pack 1, 2 in pack 3) got corrected wording. All 12 now `verified: true`. Commit `aceeee6`.

## Full text of very old run summaries
If you need the verbatim original run-1/2/4/5/6/7 summaries (word-for-word,
not the condensed version above), they're in git history: `git show
<commit>:PROGRESS.md` for any commit before `2026-09-30`'s trim, or `git log
-p -- PROGRESS.md`.
