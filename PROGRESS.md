# shorts-v3 Progress Log

Mission brief: ~/UPGRADE_BRIEF.md
Branch: shorts-v3 (rebuilt on illustrated-engine @ 6df5bc0, the V15-checkpoint commit)
Orchestrator: Jade (Sonnet 5, Discord #illustration-video)

## Status: Phase 1 (Gap Analysis / Audit) — IN PROGRESS

## Done
- 2026-09-27: Confirmed illustrated-engine is the latest branch line (jade/jade-local are stale, last touched 2026-09-01/08-31).
- 2026-09-27: Committed pre-existing uncommitted V15 WIP on illustrated-engine as checkpoint 6df5bc0 (timing caches, editorial signatures, UPGRADE_LOG.md), excluding new orchestration files.
- 2026-09-27: Recreated shorts-v3 from 6df5bc0. Added PROGRESS.md + .gitignore for .jade/ (commit b20406f).
- 2026-09-27: Verified headless tool lockdown for unattended claude CLI runs:
  flags: --strict-mcp-config --allowedTools "Read Grep Glob Bash Write Edit" --disallowedTools "Task Skill SendMessage CronCreate CronDelete CronList DesignSync EnterWorktree ExitWorktree ListAgents PushNotification RemoteTrigger ScheduleWakeup WebFetch WebSearch NotebookEdit"
  Verified granted tool set: Bash, Edit, Glob, Grep, Monitor, Read, ReportFindings, TaskStop, ToolSearch, Write. mcp_servers: [] (Gmail/Docs/etc all excluded).
  Note: --allowedTools is NOT a strict allowlist (a baseline safe tool set is always granted); --disallowedTools is the real restriction mechanism. Always pair both, plus --strict-mcp-config, on every headless run.
- 2026-09-27: Discovered repo already has a mature V15 upgrade (engine/v15_*.py, build/v15/, V15_PLAN.md, UPGRADE_LOG.md) covering plates/brand-bible/gate/batch work, largely overlapping this mission's goals. Phase 1 reframed as gap analysis against V15 baseline, not a from-scratch audit.
- 2026-09-27: Phase 1 (Opus, gap-analysis prompt, locked-down tools) launched in tmux session `jade-phase1`, session_id b30fbbdd-2d71-456a-b7bf-9ddfc0596917, log at .jade/phase1.log.

## Next
- Monitor Phase 1 tmux session for completion, usage-limit pause, or error.
- On completion: review AUDIT.md, report to owner, wait for approval before Phase 2.

## Open questions
- None yet.

## Claude Code session IDs
- Phase 1: b30fbbdd-2d71-456a-b7bf-9ddfc0596917 (.jade/phase1_session_id.txt)

## Phase 1 COMPLETE (2026-09-27)
- AUDIT.md written (330 lines), Opus session exited cleanly, stopped as instructed (did not proceed to Phase 2).
- Confirmed Bash execution in headless run is real: 37 Bash tool_use calls in .jade/phase1.log, with genuine outputs (file cat/ls/wc-l results), not permission denials.
- Runtime: Phase 1 took ~6 minutes wall time (started 18:32:35, finished before 18:39 check), well under any usage-limit concern. No need for the scheduled 90-min check-in — reported directly instead.
- Key findings: V15 already covers rendering/QA well (native 9:16, plates, gate, judge). Gaps are upstream: no story/hook/topic engine, no channel brand bible, thin pacing/motion density, captions too small/low, generic music, and several credit/trial-limited services (Fish Audio TTS especially — free window documented as ending 2026-08-31, no fallback wired into V15).
- 5 open questions for owner before Phase 2 (see AUDIT.md §7): Fish Audio commercial/free status, brand direction, NVIDIA NIM trial acceptability, OpenRouter GLM billing, dead DeepSeek key removal.

## Next (blocked on owner approval + answers to §7 open questions)
- Phase 2 (Opus, research): re-enable WebSearch + WebFetch in tool flags (still no MCP, no Skill, no SendMessage) per owner instruction 2026-09-27.

## Owner decisions received (2026-09-27, post-AUDIT.md)
1. Fish Audio: keep primary, verify account/commercial terms, add local fallback (Chatterbox/Kokoro benchmark) — in Phase 2 scope.
2. Brand: must fit @most.amazing.wonders; Phase 2 analyzes channel via existing YouTube Data API OAuth (upload-scope only — see security note below); Phase 3 proposes 2-3 branded options.
3. NVIDIA NIM: not approved for production; Phase 2 finds zero-cost alternative image source.
4. OpenRouter GLM: demoted out of the required path; adapter defaults to Claude (Phase 3 design), GLM becomes optional.
5. DeepSeek: queued as a Phase 4 task — remove references from tracked repo config/code only (~20 files: providers, schemas, configs, CI — NOT .env, NOT server/OpenClaw config). Not done now; needs careful edits + test run, appropriately a Phase 4 (Sonnet, tested commits) task, not a rushed mid-Phase-2 patch.

## Security finding (git history secret scan, done directly, not delegated)
- Ran a pickaxe scan (`git log --all -S<pattern>`) across all branches for common API key prefixes (sk-or-v1-, AIzaSy, hf_, nvapi-, gsk_, xai-, sk-ant-, sk-proj-).
- Found ONE real leaked secret: commit `ef77f54` (2026-08-02, "v4: NVIDIA NIM AI imagery provider...") added a full `.env.bak-20260802-065549` file containing 8 keys: DEEPSEEK, GEMINI, NASA, NVIDIA, PEXELS, PIXABAY, SLACK_APP, SLACK_BOT.
- That file is NOT present at current HEAD on any branch (removed later) — the leak is confined to history, not the working tree.
- Owner confirmed (2026-09-27) all 8 keys were rotated after this exposure. No further action needed.
- Repo has a real GitHub remote: git@github.com:ckdigitalyt/video_engine.git. Visibility (public/private) not checked from here — recommend the owner confirm, and if any of those 8 keys (esp. GEMINI, PEXELS, PIXABAY, SLACK, and NVIDIA if not yet rotated) are still live, rotate them and consider scrubbing history (git filter-repo / BFG) given it's already pushed.
- Current untracked `.env.bak*` files in the working tree ARE correctly gitignored (`.env*` pattern) — no fresh leak risk there.

## Status: Phase 2 (Research) — IN PROGRESS
- Launched in tmux `jade-phase2`, session_id d661add2-9ec7-437b-8dfd-84dd4eb1da3e, log .jade/phase2.log.
- Tools verified: Bash, Edit, Glob, Grep, Monitor, Read, ReportFindings, TaskStop, ToolSearch, WebFetch, WebSearch, Write. mcp_servers: [].
- Prompt at .jade/phase2_prompt.txt covers: Fish verification + local TTS fallback benchmark, @most.amazing.wonders channel analysis (with explicit instruction to never print client_secret.json/token.json contents, and not to attempt OAuth scope expansion), zero-cost image source research (NIM excluded from production), Claude-first adapter direction (GLM demoted), one fresh timed E2E run, plus original niche/tool-survey scope. Deliverable: RESEARCH.md. Stops after, does not proceed to Phase 3.

## Phase 2 usage-limit hit + resumed (2026-09-28)
- Phase 2 hit the Claude 5-hour session limit at 2026-09-27 18:56 UTC, ~4 min into the run, while waiting on a backgrounded e2e render task. Exit: is_error=true, "You've hit your session limit · resets 7:30pm (UTC)" (i.e. 2026-09-27 19:30 UTC). Cost to that point: $1.23, 33 turns.
- Gap: this wasn't caught until the owner asked for a progress update at 2026-09-28 02:35 UTC (~7.5h after the limit reset) — no monitoring/check-in was scheduled for Phase 2 specifically. Noting this so future phases get an explicit check-in scheduled at launch, not just Phase 1.
- Verified no stray processes or partial artifacts were left behind by the killed background task — clean state.
- Resumed via `claude -p --resume <session-id>` (same locked-down flags) at 02:36:53 UTC. Session picked back up mid-task: found the backgrounded e2e run had actually completed (tunguska_1908 story, 17m13s wall, all 17 scenes PASS) before the parent got killed — reusing that result rather than re-rendering.
- Currently continuing toward RESEARCH.md. Will report when done or if it hits the limit again.

## Phase 2 COMPLETE (2026-09-28)
- RESEARCH.md written (evidence-labelled, one recommendation per component). Scripts in research/phase2/ (untracked, not committed); outputs in ~/phase2_out/, models in ~/models/. No pipeline code modified.
- Fresh cold e2e (blackhole_clocks): 17 min 13 s total, PASS — but plate QA was silently skipped (Gemini 20 RPD quota) and a watermarked + a garbled-text plate shipped (RESEARCH §2.3).
- Owner actions raised (RESEARCH §11): Fish commercial clearance; approve Fish→Kokoro fallback; approve replacing dead plate links (SiliconFlow 401, HF 410); optional Cloudflare account; YouTube OAuth re-consent (token invalid_grant); rotate GEMINI_API_KEY (partially echoed into the session log).
- Stopped before Phase 3 as instructed.

## Owner decisions round 2 (2026-09-28) + Phase 3 launch
- Voice: provider-agnostic (Fish API + Kokoro am_michael); design must not rely on Fish free tier for monetized output; Phase 3 renders same script in both for owner comparison. Kokoro fallback approved.
- Approved replacing dead SiliconFlow/HF with local klein + Cloudflare Workers AI. Owner creates account; env file /home/ubuntu/video_engine/.env, vars CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN.
- Topic engine driven by channel data (dinosaur/deep-time + single-spectacle physics ~18x V15 Shorts).
- Credential rule: never try a key against a service it was not issued for. Gemini key redacted from .jade/phase2.log and the Claude session jsonl (verified no 16-char fragment remains). Owner to rotate GEMINI_API_KEY regardless.
- OpenClaw compaction: config NOT touched; proposal sent to owner.
- Phase 3 (Opus, no web tools) launched 04:26 UTC in tmux jade-phase3, session in .jade/phase3_session_id.txt, log .jade/phase3.log. Deliverables: DESIGN.md, 2-3 brand options with sample frames, Fish vs Kokoro voice samples. Background watcher armed for completion/limit.

## Phase 3 COMPLETE (2026-09-28 04:42 UTC) — awaiting owner approval
- DESIGN.md (815 lines, 15 Phase-4 work packages), research/phase3/ scripts. Media in ~/phase3_out/ (brand/{A_ink_ember,B_deep_signal,C_wonder_almanac}, comparison.jpg, voice/{fish,kokoro}.wav). Opus cost $3.39, 38 turns, 16.6 min, no limit hit.
- Cloudflare creds added to .env (CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN) from tmp/tempenv.txt; user-token verify OK; Workers AI call OK. tmp/tempenv.txt still on disk (gitignored) — owner to delete.
- Watcher could not be armed (background bash denied); Phase 3 finished before it mattered.
- Awaiting: brand choice (A/B/C), voice decision (Fish-paid vs Kokoro), DESIGN §15.3 sign-offs, then approval for Phase 4 (Sonnet).

## Owner decisions round 3 (2026-09-28 04:54 UTC) — Phase 4 greenlit
1. Brand: A "Ink & Ember" + C's high-contrast boxed keyword labels for hook text at t=0-1s only + dark-plate variant for space topics; NO mascot; B rejected. All brand params config-driven (brand/<name>/ yaml, no literals in code).
2. Voice: Kokoro is the sole channel voice; Fish disabled by default (code kept, FISH_PLAN gate). Owed to owner: render the same 73-word script in 3 Kokoro voices (am_michael + 2 best male alternatives) at 1.0x and 1.1x for selection. Build pronunciation lexicon (Tyrannosaurus etc.) + whisper round-trip check flagging mispronounced keywords. (Part of WP3.)
3. §15.3: approve item 1 (Claude default) and 2 (drop SiliconFlow/HF, NIM benchmark-only). Item 3 superseded by decision 2. Item 4 (retire Python caption overlay / per-scene Remotion) ONLY after A/B parity; git-tag old paths BEFORE removal (e.g. pre-wp5-caption-overlay).
4. Secrets: tmp/tempenv.txt DELETED (shredded) 2026-09-28. Rule: never print secret values; verify with masked output only (e.g. len/prefix-4 or "set/unset"). Owner rotates Cloudflare token and edits .env himself — do not touch .env.
5. Owed: OpenClaw compaction config proposal (sent in chat; config not modified).
6. Phase 4 (Sonnet) in DESIGN.md §15.2 order: small tested commits, A/B checkpoints. Update PROGRESS.md BEFORE each package. After each package that changes visible output, post short status + sample render to owner. DeepSeek reference removal from tracked files is part of WP1.

## Phase 4 launched (2026-09-28)
- Run 1 scope: WP0 (baseline + bench harness) then WP1 (LLM adapter + Claude CLI). Stop after WP1 and report. Prompt .jade/phase4_run1_prompt.txt, script .jade/run_phase4.sh, log .jade/phase4_run1.log.
- Resume rule: read this file + DESIGN.md §15.2, continue with the first WP not marked DONE below.

### WP status
- WP0: DONE f3022a7 (baseline.md/json + bench/quality; topic packs 1 and 3 unverified)
- WP1: DONE cacb1c4 (adapter) + be12e92 (DeepSeek removal) + 250d4bd (CHANGELOG) + d0a6c36 (acceptance report bench/ab/wp1.md)
- WP2: DONE cf70724 (code+tests+CHANGELOG) + acceptance report bench/ab/wp2.md
- WP3: DONE 45e69b5 (voice layer) + acceptance report bench/ab/wp3.md
- WP4: code DONE 81812b3 + 411d5be + 487f95a (story engine S1-S4, 29 tests) + acceptance report bench/ab/wp4.md. A/B #1 PENDING: topic 2 script-level run HOLDs at the critic (3.75 < 4.0); topics 1 and 3 not run (source check only partly applied); no renders
- WP5–WP14: pending

## Phase 4 run 1 summary (2026-09-28) — WP0 + WP1 done, stopped before WP2
1. Commits: WP0 f3022a7; WP1 cacb1c4 (llm/ adapter, configs/llm.yaml, director shims), be12e92 (DeepSeek removal from tracked code/config), 250d4bd (CHANGELOG), d0a6c36 (acceptance report).
2. Tests: tests/test_llm_adapter.py (28) + tests/test_bench_quality.py (3) pass; illustrated_engine/tests 20/20 pass; pre-existing failures unchanged before/after (test_provider_interfaces 2F+3E, test_subtitles/test_engine_hardening 5F). mission_run.py --help and engine.v15_pipeline import OK.
3. Adapter: Claude CLI default (sonnet; plate_qa chain sonnet->haiku); Gemini/OpenRouter ported but enabled:false; structured payload field pinned as `structured_output` (recorded fixture). Quota cooldown/repair/retry/cache/ledger per DESIGN 2.4.
4. Acceptance (blackhole, 5 Claude calls, ~$0.12 list-price equiv., no retries): visual_plan, plate_qa x2, final_judge all via adapter; ledger at illustrated_engine/build/llm_ledger.jsonl (copy ~/phase4_out/wp1/ledger.jsonl).
5. Result is HOLD, correctly: with plate QA actually running, the watermark/garbled-text plates that shipped in the Phase 2 baseline are caught and regeneration does not fix them; judge also flags a weak hook frame. See bench/ab/wp1.md.
6. Samples: ~/phase4_out/wp1/{judge_sheet,plate_sheet,plate_sheet_regen}.jpg, frame_{1,17,40}s.jpg, report.json, pipeline_run.log (work dir ~/phase4_out/wp1/blackhole is 766 MB, deletable).
7. WP0 baseline (bench/ab/baseline.md): V15 ice/cell/blackhole all PASS, but blackhole had plate QA skipped; topic packs 1 (birds) and 3 (time crystals) are worker-curated with verified:false claims (no web in Phase 4) — need a source check before WP4 scoring.
8. OWNER FLAG (AGENTS.md 15.3 item 1): V15 judge/plan default chain changed from Gemini->GLM to Claude CLI; no fallback to expensive models (only haiku, cheaper). mission_run.py's own src/providers chain is untouched.
9. Kept deliberately: leak_scan MODEL_TOKENS still contains DEEPSEEK (it blocks the name from being drawn on screen); historical .md/logs mention DeepSeek and were not edited. Fixed a latent KeyError in `cli.py semqa` (read res["deepseek"], key is "judges").
10. Open issues: research/phase2/llm_compare.py uses removed private helpers (one-off script); WP2 must make "plate QA did not run" a HOLD; Claude quota use per video (about 5-9 calls) is shared with the owner's Pro plan; next up WP2 (not started).


## Owner standing go (2026-09-28 10:18 UTC)
- Standing go for every Phase 4 WP in plan order; no approval between packages unless a stop condition applies (new unfixable test failure; .env/secrets/new paid services/accounts; destructive git or deletes outside phase4_out; scope/plan change; same failure 3x).
- Gate to advance: full suite passes apart from known baseline failures, secret scan clean, commits pushed, PROGRESS + bench/ab acceptance report written. HOLD on a sample video is fine when correct.
- Usage limit hit: pause, schedule one-shot resume after reset, post one line, no retry before. Minimum Claude calls per acceptance run. Clean large work dirs after each acceptance run. Chained 45-min one-shot check-ins (never recurring). Fresh session per WP after PROGRESS + check-in.
- Carried into plan: (a) WP2: "plate QA did not run" = HOLD. (b) Source-check topic packs 1 (birds) and 3 (time crystals) BEFORE any WP4 scoring.

## Subtitle test baseline (verified 2026-09-28)
- tests/test_subtitles.py at 3f77256 (pre-WP0, separate worktree) vs 77f28c8 (HEAD): IDENTICAL 4 failures / 33 pass: TestGenerate::test_line_assignment, TestRendererClips::test_long_line_splits_into_phrase_clips, TestEdgeCases::test_very_long_narration, TestConfig::test_default_config_keys_exist. Not caused by WP1. (Earlier "5F" was a combined subtitles+engine_hardening count.) These are the known baseline.
- Housekeeping: ~/phase4_out/wp1/blackhole deleted (samples kept); research/phase2/llm_compare.py header-marked broken since WP1.

## Phase 4 run 2 summary (2026-09-28) — WP2 done, stopped before WP3
1. Commits: cf70724 (WP2 code, tests, CHANGELOG), then a docs commit with bench/ab/wp2.md + this summary.
2. Tests: new illustrated_engine/tests/test_wp2_gate.py 11/11; test_v15 all pass; illustrated_engine/tests 31 pass; root suite 58F+5E, IDENTICAL to HEAD before WP2 (diffed in a clean worktree), no new failures.
3. Known-baseline correction: the pre-existing root-suite failures span 17 files (visual_director 16, pixabay 7, effects 6, renderer 6, timeline_builder 5, subtitles 4, ...), far more than the earlier list. test_llm_adapter shim test fails in the full run only (order dependence, also before WP2).
4. Verdict: PASS. "checked:false" => HOLD; Phase 2 watermark plate fixture => FAIL (even if vision QA passed or was skipped); Phase 2 blackhole re-gated PASS -> FAIL (stamped plate + 9 boxes in right rail).
5. Behaviour: verdicts PASS/HOLD/FAIL; gate OCRs every plate itself (tesseract CLI, edge strips, stamp tokens/domains, sidecar-cached); one critical judge frame (garbled text/watermark/overlap) fails; right-rail + caption safe-zone checks.
6. No fallback/retry path removed or narrowed (regen round, provider and judge chains untouched).
7. Samples (~/phase4_out/wp2/): regate_phase2_blackhole.json, run_gate_phase2_blackhole.json, phase2_blackhole_plates_montage.jpg, suite_{before,after}.txt. No Claude calls, no renders, no large work dirs.
8. Deviations: kept v15_gate.py/v15_plates.py names (no v16 rename); top-220/bottom-1440 insets, 84 px caption size and 1 s/2 s judge cadence deferred to WP6/WP5/S11.
9. OWNER FLAG: every V15 render now HOLDs on the right rail (labels sit at x~1010, y~800) until WP6/WP7 re-layout. OCR only catches known stamps; other watermarks need the vision call.
10. Open: research/phase2/llm_compare.py still broken; topic packs 1 and 3 still need source-check before WP4 scoring; next is WP3 (voice layer, needs faster-whisper install).

## Phase 4 run 4 summary (2026-09-28) — WP3 done, stopped before WP4
1. Resumed run 3's uncommitted WP3 tree, kept it (reviewed, sound), fixed one wrong live test input (bare Kokoro misreads "Tyrannosaurus rex" only sentence-initially). Commit 45e69b5 + docs commit.
2. New: engine/voice/ (Kokoro fp32 am_michael, Fish paid-gated + disabled by default, lexicon phonemes, faster-whisper base.en timing aligned to script, round-trip QA WER<=0.03 + hard tokens, whole-video fallback), configs/voice.yaml, brand/ink_ember/lexicon.yaml (15 entries), gate check `voice` (QA not run/failed/not commercial -> HOLD). faster-whisper 1.2.1 in venv + requirements (local, no credentials).
3. Tests: test_wp3_voice.py 18 new, illustrated_engine/tests 49/49. Root suite 58F+5E identical failing ids before (clean worktree of 6576602) and after. Secret scan of diff clean. .env untouched.
4. Acceptance: topic-1 script WER 0.000 PASS (RTF 0.68); forced Fish failure -> whole-video Kokoro (unit test); lexicon fixes Tyrannosaurus (live).
5. Caption timing: sentence onset p90 0.024 s vs synthesis truth (partly circular); word starts vs whisper small.en p90 0.16 s (model disagreement, not ground truth). The 0.12 s target is NOT verified; needs Fish paid timestamps or hand labels. Old silence_v1 was p90 0.34 s.
6. OWNER SAMPLES (need your ears): ~/phase4_out/wp3/samples/{am_michael,am_onyx,bm_lewis}_{1.0x,1.1x}.wav, -14 LUFS. onyx/lewis chosen from F0 + WER numbers only, out of 9 shortlisted voices.
7. OWNER FLAG: V15's "Fish only, STOP" replaced by Kokoro-first; chain holds only Kokoro. Removed the Fish free-tier-pinned path in engine/tts.py (not a fallback chain); silence_v1 kept as offline last resort. No fallback/retry narrowed.
8. Not done: full V15 render with the new voice (needs Claude calls); lexicon phonemes never listened to; 6 lexicon entries have respelling only.
9. Housekeeping: /tmp/wt_prev worktree removed, ~/phase4_out/wp3/tmp deleted (15 MB left).
10. Open: llm_compare.py still broken; topic packs 1 and 3 source-check before WP4 scoring; next is WP4.

## Phase 4 run 5 summary (2026-09-28) — WP4 code done, A/B #1 PENDING, stopped before WP5
1. Commits: 81812b3 (S1-S4 modules, 5 prompts + schemas, tests), 411d5be, 487f95a (voice-safe digits rule, script_write v2, `kulik` lexicon entry, CHANGELOG), then bench/ab/wp4.md + this summary. Pushed.
2. New: engine/v16_research.py (quote-exists check, claim-adds-number check, curated packs), engine/v16_script.py (length/hook/role/loop/digit/title rules, critic->rewrite->fact_check->metadata, PASS/HOLD), llm/prompts.py + llm/prompts/*.md + llm/schemas/*.json. No fallback or retry path removed.
3. Tests: test_wp4_story.py 29 new; illustrated_engine/tests 78 pass. Root suite 58F+5E, IDENTICAL 63 failing ids before (clean worktree of 6c8ec87) and after. Secret scan clean, .env untouched.
4. Live (topic 2 tunguska, script level, no render): 3 runs, all HOLD at the critic (mean 3.5 -> 3.75 after rewrite, bar 4.0). Draft passes every code rule: 136 words, 9-word claim hook, Kokoro 57.95 s, voice onset 0.021 s (V15: 199 words, 78 s). Metadata and fact_check smoke-tested live.
5. Source check: bench/ab/source_check.md + source_check fields appeared UNCOMMITTED mid-run; only 4/6 claims per pack verified:true, corrections pending. Topics 1 and 3 NOT run; I did not commit those files. Once final: run `python -m engine.v16_script --curated bench/quality/topics/0N_... --topic ... --out ...` from illustrated_engine/ with venv python.
6. Calls: 15 fresh Claude calls (10 Opus, 5 Sonnet, ~$0.77 list-price equiv.); a clean pass is 4 calls. Samples: ~/phase4_out/wp4/{tunguska,tunguska_run2,tunguska_v1}, suite_{before,after}.txt (5.7 MB, no large work dirs).
7. OWNER DECISION: the critic bar (mean >= 4.0, none < 3, one rewrite) HOLDs 3/3 on tunguska; options: second rewrite, bar 3.75, or review HOLDs. I did not change the bar. Critic scores are uncalibrated against channel winners.
8. WP3 gaps found: round-trip QA HOLDs on "fifteen hundred" (Whisper "1500") and "2 ,000"; Kokoro misreads "2,000". WP4 forbids comma/decimal/5+ digit numbers in narration; the QA normaliser is not fixed.
9. Deviations: title honesty is code-only (cited fact ids + numbers + trope ban), no extra LLM call; loop coherence left to the critic (lexical overlap fails DESIGN's own example); fact_check is noisy and uncalibrated (prompt v3 asks for the note first). S1 build_facts never saw a real fetched page (no web).
10. Open: llm_compare.py still broken; A/B #1 for topics 1-3 (render + scoring) PENDING; next is WP5 once the owner rules on item 7.

## Phase 4 run 6 summary (2026-09-29) - WP6 done (WP5 deferred), commit 62be5eb
1. Owner re-sequenced the plan (scripts/phase4_driver.sh, untracked): WP6 -> WP7 -> WP9 -> WP10 first (fastest publishable Short), WP5/WP8/WP11-14 later. This run picked up WP6 code already written but uncommitted in the tree, verified it, filled in the acceptance report, and committed.
2. New: brand/ink_ember/ (brand.yaml, grade.cube), engine/brand.py (roles, LUT, props lint, sting/outro/cover generators), fonts+OFL licences. No fallback/retry path removed.
3. Right-rail fix: v15_shots.py _text_layer/_label/compile_process_shot now call brand.rail_safe_x1 and re-fit narrower instead of overflowing into the UI rail (x>930,y>760). Reproduces the exact WP2 "THE BLACK HOLE" case + 3 more scenarios, unit-tested.
4. Tests: test_wp6_brand.py 19/19; illustrated_engine/tests 97/98 (1 known order-dependent flake, passes isolated). Root suite: 63/63 failing ids identical before/after (clean worktree of aceeee6 vs this commit) - zero new failures. Secret scan clean (one hf_ substring false-positive in unrelated pre-existing code), .env untouched.
5. Deviations (flagged, not silent): v15_style.py's 5 per-story palette decks are NOT yet roles-only (bigger change, deferred); sting/outro/cover generators exist and are tested but not yet wired into the render/assembly timeline (no WP touches assembly yet).
6. Not proven this pass: a fresh end-to-end render + re-gate of a real story through the fixed compiler (deferred to WP7 per its own prompt, to avoid extra image-provider/Claude calls in WP6).
7. Samples: ~/phase4_out/wp6/ (sting/cover/bloom pngs, suite_before.txt/suite_after.txt).
8. Report: bench/ab/wp6.md.
9. Pushed.
10. Next: WP7 (templates + pacing) - including the deferred full-pipeline right-rail proof.

## Status: Phase 4 WP7 (Templates + pacing) - DONE 3fec714 (2026-09-30)

## Phase 4 run 7 summary (2026-09-30) - WP7 done, commit 3fec714
1. Resumed run 6's uncommitted WP7 tree (found sound on inspection: reviewed every diff/new file line-by-line before touching anything), verified all claims live, then committed + pushed.
2. New: engine/v16_plan.py (planner v2: TEMPLATE_LIBRARY of 11 templates incl. all 7 required, deterministic assign_templates/validate_templates - content-signal mapping, no-repeat, >=5 distinct, <=35% share, frame0/last, hash-broken ties, never random). 7 new engine/v15_shots.py compilers (kinetic_claim/big_number/map_pin/timeline/scale_compare/parallax/loop_bridge), all reusing existing plate/text/camera primitives. engine/v15_gate.py check_pattern_interrupt (1.8s), sharing _hold_gaps with the unchanged 4.5s check_visual_hold. engine/v15_pipeline.py split_long_holds refactored to take max_hold_s/margin_s and split iteratively (V15's own default call unchanged). No fallback/retry path touched.
3. Tests: test_wp7_templates.py 23/23; illustrated_engine/tests 120/120 (97 before + 23 new, 0 regressions). Root suite tests/ 63/63 failing ids identical before (clean worktree of edd7a45) vs after - zero new failures, zero fixed (4-skip delta is order/network noise, same pattern WP6 saw). Secret scan of the staged diff clean, .env untouched.
4. Right-rail HOLD (carried from WP2/WP6): bench/ab/wp7_regate.py reproduces all 9 documented bench/ab/wp2.md failing boxes through current code - PASS, 9/9 clear v15_gate.check_text_bounds.
5. A/B #3 (bench/ab/wp7_ab3_pacing.py, offline, real pipeline logic on the 3 WP0 topics): max hold 1.72-1.73s (PASS, target <=1.8s); median shot 1.10-1.23s (at/just under the 1.2-2.0s band's floor - the iterative hold-splitter cuts more aggressively than the median target alone needs; flagged, not silently accepted); >=5 distinct templates per topic (8-9 of 11, PASS). Caveat: per-word timing is synthetic (WORDS_PER_SEC), not real voice timing.
6. Also verified: 10 real Remotion stills (one per template, incl. the 4 pre-existing V15 kinds) rendered through the actual production backend (engine.scene_renderer, Chrome headless `remotion still`) - all ok:true, real 1080x1920 PNGs, kept at ~/phase4_out/wp7/stills/.
7. Two real bugs found and fixed while proving this (not invented for the sake of it): scene_renderer.RemotionRenderer.render_frame was calling `remotion render --frame` (rejected by this CLI version, needs `still`); v16_plan's repair passes could assign a template a shot's content can't back (ZOOM_THROUGH/PROCESS_OVER_PLATE/BIG_NUMBER/KINETIC_CLAIM) - added _compatible/_generic_pool_for/_safe_pool_for gating every assignment/repair pass, plus regression tests.
8. `npm i @remotion/lottie@4.0.529` / `scenedetect`: deliberately not installed - none of the 7 required templates need Lottie, and exact Scene IR duration/visibility data is a cheaper, more accurate pacing source than scenedetect on encoded pixels. Flag if wanted for DIAGRAM_ARROWS later.
9. OWNER FLAGS (all in bench/ab/wp7.md, not blocking): (a) no new templates/*.tsx components this pass - templates are Python-side Scene-IR compilers through the one existing generic Remotion composition; typed .tsx components are WP5's own rewrite. (b) MAP_PIN/SCALE_COMPARE have no sourced basemap/silhouette art (procedural stand-ins, gate-safe). (c) LOOP_BRIDGE's hook-context wiring exists but is not connected to v15_pipeline.run_pipeline, so loop SSIM is not measured yet. (d) v16_plan.assign_templates and the 1.8s split_long_holds are proven standalone, not yet wired into v15_pipeline.run_pipeline as the live default (would ~2.5x live shot count per video - bigger, riskier change deferred).
10. Pushed. Housekeeping: /tmp/wt_wp7_baseline worktree removed after use. Next per scripts/phase4_driver.sh re-sequencing: WP9 (music/SFX/sting).
