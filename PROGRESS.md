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
