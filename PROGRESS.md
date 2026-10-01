# shorts-v3 Progress Log

Mission brief: ~/UPGRADE_BRIEF.md
Branch: shorts-v3 (rebuilt on illustrated-engine @ 6df5bc0, the V15-checkpoint commit)
Orchestrator: Jade (Sonnet 5, Discord #illustration-video)

**Token-optimization note (2026-09-30):** this file was trimmed from 43KB to
keep unattended-worker context cost down (every WP run reads this file in
full). Full history of Phases 1-3 and WP0/WP1/WP2/WP3/WP4/WP6/WP7 run
summaries moved to `PROGRESS_ARCHIVE.md` — read it only if you need detail
behind an older decision. Everything still binding (owner decisions, the
WP status table, the current baseline) stays here in full.

## WP status (DESIGN.md §15.2)
- WP0: DONE `f3022a7` — baseline + bench harness
- WP1: DONE `cacb1c4`+`be12e92`+`250d4bd`+`d0a6c36` — LLM adapter, Claude CLI default, DeepSeek removed from tracked config
- WP2: DONE `cf70724` — fail-closed QA gate (OCR watermark pre-filter, right-rail/caption safe-zone check)
- WP3: DONE `45e69b5` — voice layer (Kokoro sole voice, lexicon, round-trip QA)
- WP4: DONE `81812b3`+`411d5be`+`487f95a`, source-check `aceeee6` — story engine S1-S4, topic packs 1/3 fully source-checked and verified
- WP6: DONE `62be5eb` — brand bible, right-rail layout fix
- WP7: DONE `3fec714` — template library (11 templates), 1.8s hold gate, right-rail fix proven end-to-end
- WP9: DONE `a4cf967` — music/SFX/sting, live-wired into v15_pipeline
- WP10: DONE `6ef2cc0`+`98a3267` — scorecard/manifest + real end-to-end render proof (FAIL, honest — see below)
- WP8: DONE `7a27899`+`b12c301` — image-provider chain reordered so a commercial_ok:true source (Cloudflare) runs first
- WP11: DONE `7b911a1` — topic engine (clusters/ideation/dedupe/scoring/series planner/`data/topic_history.jsonl`)
- WP5: DONE `520d9df` — one-composition Remotion render code landed and tested; **real parity gate FAILed honestly** (SSIM 0.93 vs 0.98 required, root cause found and documented), Python caption/assembly pass stays default, `v16_compose` has zero live-pipeline callers
- WP12, WP13, WP14: pending, in that order

## Owner decisions (binding, all still in force)
1. **Brand (2026-09-28):** "Ink & Ember" + boxed keyword hook labels (t=0-1s) + dark-plate variant for space topics; no mascot; brand params config-driven, no literals in code.
2. **Voice (2026-09-28):** Kokoro is the sole channel voice; Fish disabled by default (FISH_PLAN gate kept in code, not removed).
3. **Model/adapter (2026-09-28):** Claude CLI is the adapter default; no auto-fallback to expensive models beyond haiku; SiliconFlow/HF dropped, NIM benchmark-only.
4. **Secrets (2026-09-28, standing):** never print secret values, masked output only (len/prefix-4/set-unset); never edit `.env`; owner edits it himself.
5. **Standing go (2026-09-28):** standing go for every Phase 4 WP in plan order, no approval needed between packages unless a stop condition applies: a new test failure you can't fix within the package; a change needing `.env`/secrets/new paid services/accounts; destructive git ops or deletes outside `phase4_out`; a change beyond the plan's scope; the same failure 3x in a row.
6. **Gate to advance:** full test suite passes apart from the known baseline failures (see below), secret scan clean, commits pushed, PROGRESS.md + a `bench/ab/*.md` acceptance report written. A HOLD/FAIL verdict on a sample video is fine when it's the correct, honest result.
7. **Re-sequencing (2026-09-29, then adjusted 2026-09-30):** plan order re-sequenced for fastest publishable Short: **WP6 → WP7 → WP9 → WP10 → WP8 → WP5 → WP11 → WP12 → WP13 → WP14**. WP8 was pulled ahead of WP5/WP11-14 on 2026-09-30 because WP10's real render proved every plate was `commercial_ok:false` — WP8 is a genuine license-gate blocker, not just robustness work.
8. **Video-render cap (2026-09-30):** at most **2 full video renders total** for the rest of Phase 4 (WP10's render used 1; 1 remains for WP12/WP13). Scale WP12's "5 videos" acceptance down to 2, WP13's "7 topics" down to 2 representative topics. Code/gates must still work generically — only the count of renders actually produced is capped.
9. **Driver / check-ins (2026-09-30):** LLM check-ins replaced by a deterministic driver, `scripts/phase4_driver.sh` (untracked infra, not a WP deliverable) — gates each WP with pytest-diff-vs-baseline + a secret-scan grep (key-prefix/assignment patterns only, not narrative word matches), handles usage-limit resets (both 5-hour session and weekly limits) by sleeping and resuming, posts to Discord via the `openclaw message` CLI only (no model call for status posts).
10. **Token optimization (2026-09-30):** keep PROGRESS.md lean going forward — append new WP summaries in the condensed style below (facts + flags + numbers, no repeated boilerplate), and fold anything older than the 2 most recent WPs into PROGRESS_ARCHIVE.md periodically.

## Known test-failure baseline
Root `tests/` suite: 63 failing IDs, pre-existing (confirmed identical
before/after every WP through WP8 via clean-worktree diffs), unrelated to
Phase 4 work. `illustrated_engine/tests`: 0 known failures (190/190 as of
WP8). Any run reporting a *different* failing-ID set has introduced a real
regression — stop and report, don't just eyeball a count.

## First-publishable-Short milestone status
WP1-4, WP6, WP7, WP9, WP10 landed and were exercised together in one real
end-to-end render (Tunguska, WP10). Result: **honest FAIL**, not a fake
pass — 8/13 hard gates failed (caption safe-zone, plate QA/watermark, voice
WER 0.054>0.03, hook timing, stale-artwork judge flags), plus the
since-fixed license blocker (WP8). This is a **pipeline-capability**
milestone (every stage runs end-to-end and produces an honest verdict), not
yet a claim that a publishable video exists. Content-quality gaps
(caption safe-zone positioning, voice WER, hook timing, judge staleness)
are NOT clearly covered by any remaining planned WP (WP5/11-14) — flag to
owner again before spending the 2nd/last render-cap slot.

## Most recent run summaries (condensed)

### WP9 (2026-09-30, `a4cf967`)
Music/SFX/sting wired live into v15_pipeline (mood-from-arc selection,
licensed CC-BY/CC0 library, sting overlay, beat-detection built but not
wired into cut placement — moving decided shot boundaries is bigger/riskier,
deferred). Real `ice_slippery` render: -14.9 LUFS/-1.2 dBTP, within gates.
Tests 143/143. Report `bench/ab/wp9.md`.

### WP10 (2026-09-30, `6ef2cc0`+`98a3267`)
Scorecard/manifest code + real Tunguska render (see milestone section
above). Manifest complete and correct (`completeness.ok:true`,
`publishable:false`). First attempt of the render was accidentally
backgrounded and abandoned mid-run by a worker that exited early — caught
and re-run synchronously to completion. Report `bench/ab/wp10.md`.

### WP8 (2026-09-30, `7a27899`+`b12c301`)
Image chain reordered (archive → cloudflare_workers_ai → gemini_image →
sdcpp_local → pollinations); live proof: 2/2 real generations landed
`commercial_ok:true` via Cloudflare (was 0/18 pre-WP8). Caveat, flagged not
silent: if Cloudflare is ever down, remaining tiers are either too slow
(sd.cpp ~20min/image) or still `commercial_ok:false` for this channel's
typical topics — license gate can still legitimately HOLD in that case.
No full render spent (proof was unit/fixture + 2 individual generations).
Report `bench/ab/wp8.md`.

### WP11 (2026-10-01, `7b911a1`)
Topic engine (DESIGN §9): clusters/ideation/dedupe/scoring/series planner,
`v16_topics.py` + `topic_ideate`/`topic_score` prompts+schemas, `data/
topic_history.jsonl` seeded from the real channel CSV + 28 V15 stories (110
rows). Tests: 18 new, dedupe fixtures from the real CSV + score
reproducibility both directly proven. Live proof (2 real Claude calls,
$0.149): 20 candidates → 0 duplicates of an existing upload, 4 rejected, 16
ranked (history now 130 rows). illustrated_engine/tests 216/216; root
tests/ 63/63 failing IDs identical to baseline (diffed). Report
`bench/ab/wp11.md`. **OWNER FLAG:** found WP5 (`v16_compose.py`, Remotion
project files, `test_wp5_compose.py`, `bench/ab/wp5_parity.py`,
`requirements.txt` scikit-image) already uncommitted in the tree from an
earlier session that hit a usage limit mid-WP5 — left untouched (out of
this run's WP11-only scope), not evaluated or tested as part of this run.

### WP5 (2026-10-01, `520d9df`)
Reviewed and committed the uncommitted WP5 work flagged by WP11
(`v16_compose.py`, `Short/Captions/Sting/Outro.tsx`, `render_short.mjs`,
`Root.tsx`'s 2nd composition, `test_wp5_compose.py`, `wp5_parity.py`,
`requirements.txt` scikit-image) — sound, additive-only (`v16_compose` has
zero live-pipeline callers). Ran the real frame-parity test for real
(no new Claude calls/plates): **FAIL, mean SSIM 0.93059 / min 0.91455 vs
the 0.98 gate.** Root-caused, not just measured: `CAPTION_COMBINE_MS=40`'s
own "always ≥50ms between cues" assumption is false on the real track
(83/118 gaps ≤40ms), so `@remotion/captions` collapses all 119 words into
one 49s page and `Captions.tsx` shows the same wrong text for the whole
video. Python caption/assembly pass stays default per DESIGN; Short.tsx
landed with no runtime wiring (nothing calls it). Tests:
illustrated_engine 216/216, root 63/63 failing IDs identical to baseline.
Report `bench/ab/wp5.md`. Fix (group by the Python pass's own `cue` id,
not timing gaps) left for a future run — out of this run's "report the
gap" scope.

## Next
WP12 (2-video cap) → WP13 (2-topic cap) → WP14. If WP5's caption-grouping
bug is ever picked up, re-run `bench/ab/wp5_parity.py` before considering
`v16_compose` for live wiring.
