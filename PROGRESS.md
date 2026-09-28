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
