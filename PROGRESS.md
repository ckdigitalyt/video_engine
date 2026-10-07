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
- WP12: DONE `bd9482f` — batch runner (preflight, topic selection, quota pause/resume, packaging); **real 2-video render acceptance deliberately deferred** (see below), machinery proven with fixtures + real-but-cheap pieces instead
- WP13, WP14: DEFERRED (owner decision #11, 2026-10-02) — replaced by the Q1-Q5+PR queue below
- Q1 (voice WER): DONE (2026-10-02) — see run summary below.
- Q2-Q5, PR: PAUSED (owner decision #12, 2026-10-02) — replaced by the VIS package below, pending owner verdict on the first real sample.
- VIS (B1-B5): DONE (2026-10-02) — see run summary below.
- Decision #12 part C (new sample): DONE (2026-10-03) — see run summary below. Q2-Q5/PR still PAUSED pending owner verdict on both samples.

## Owner decisions (binding, all still in force)
1. **Brand (2026-09-28):** "Ink & Ember" + boxed keyword hook labels (t=0-1s) + dark-plate variant for space topics; no mascot; brand params config-driven, no literals in code.
2. **Voice (2026-09-28):** Kokoro is the sole channel voice; Fish disabled by default (FISH_PLAN gate kept in code, not removed).
3. **Model/adapter (2026-09-28):** Claude CLI is the adapter default; no auto-fallback to expensive models beyond haiku; SiliconFlow/HF dropped, NIM benchmark-only.
4. **Secrets (2026-09-28, standing):** never print secret values, masked output only (len/prefix-4/set-unset); never edit `.env`; owner edits it himself.
5. **Standing go (2026-09-28):** standing go for every Phase 4 WP in plan order, no approval needed between packages unless a stop condition applies: a new test failure you can't fix within the package; a change needing `.env`/secrets/new paid services/accounts; destructive git ops or deletes outside `phase4_out`; a change beyond the plan's scope; the same failure 3x in a row.
6. **Gate to advance:** full test suite passes apart from the known baseline failures (see below), secret scan clean, commits pushed, PROGRESS.md + a `bench/ab/*.md` acceptance report written. A HOLD/FAIL verdict on a sample video is fine when it's the correct, honest result.
7. **Re-sequencing (2026-09-29, then adjusted 2026-09-30):** plan order re-sequenced for fastest publishable Short: **WP6 → WP7 → WP9 → WP10 → WP8 → WP5 → WP11 → WP12 → WP13 → WP14**. WP8 was pulled ahead of WP5/WP11-14 on 2026-09-30 because WP10's real render proved every plate was `commercial_ok:false` — WP8 is a genuine license-gate blocker, not just robustness work.
8. **Video-render cap (2026-09-30):** at most **2 full video renders total** for the rest of Phase 4 (WP10's render used 1; 1 remains — WP12 deliberately did not spend it, see its PROGRESS entry below; still available for WP13 or a future WP12 real-batch follow-up). Scale WP12's "5 videos" acceptance down to 2, WP13's "7 topics" down to 2 representative topics. Code/gates must still work generically — only the count of renders actually produced is capped.
9. **Driver / check-ins (2026-09-30):** LLM check-ins replaced by a deterministic driver, `scripts/phase4_driver.sh` (untracked infra, not a WP deliverable) — gates each WP with pytest-diff-vs-baseline + a secret-scan grep (key-prefix/assignment patterns only, not narrative word matches), handles usage-limit resets (both 5-hour session and weekly limits) by sleeping and resuming, posts to Discord via the `openclaw message` CLI only (no model call for status posts).
10. **Token optimization (2026-09-30):** keep PROGRESS.md lean going forward — append new WP summaries in the condensed style below (facts + flags + numbers, no repeated boilerplate), and fold anything older than the 2 most recent WPs into PROGRESS_ARCHIVE.md periodically.
11. **Plan reset (2026-10-02):** WP13/WP14 DEFERRED — replaced by a quality-gap-closing queue aimed at an autonomous daily video pipeline, not individual videos. New queue: **Q1 (voice WER) → Q2 (hook timing) → Q3 (caption safe zone) → Q4 (plates) → Q5 (re-render Tunguska, all 13 gates) → PR (production-readiness driver)**. Render policy replaces the old 2-video cap: component checks (voice/hook/caption-layout/single-plate, no Claude calls) are unlimited; full end-to-end test renders are capped at 2/day during tuning. Each Q package ships `bench/checks/QN.sh` exiting 0 only when its exit criterion is met (gate-checked by the driver). PR builds `scripts/daily_run.sh` as the one entry point (topic→fact-check→script→voice→visuals→render→gates→package), triggered by **system crontab only** (no OpenClaw/LLM scheduling for the video runs themselves), with a lock file, log, cleanup, and single quota-reset wait. PR's exit criterion (3 back-to-back cron-triggered runs, 2+ PASS) is inherently multi-day and is checked later, not inside one worker run. YouTube upload stays manual until explicit approval. Driver fixes: queue now derives from `.jade/state/finished.txt` (never re-runs a finished package); gate requires HEAD moved + clean working tree + the package's `bench/ab/*.md` report exists + `bench/checks/QN.sh` exits 0 + no new test-failure IDs + clean secret scan; 1 automatic retry on gate failure, then stop; `claude -p` now runs `--effort medium` (no `--max-turns` flag exists in this CLI version — turn discipline is enforced in-prompt instead); all renders already run synchronously (unchanged). Workers: read only condensed PROGRESS.md + their own prompt + in-scope files; DESIGN.md/archive only for named sections. **Pre-existing, unrelated finding:** `crontab -l` already has a legacy (v13, Aug 2026) daily cron `tools/daily_video.sh --runner stills --upload` — separate from this plan, enforces unlisted-only and upload-only-on-PUBLISH_READY itself, and has been `BLOCKED` (no publishable artifact) every day for the last several days, so nothing has actually auto-uploaded. Left untouched; PR's new crontab entry will be added alongside it, not replacing it.
12. **Plan reset round 2 (2026-10-02):** GitHub Pages / OAuth-verification task CANCELLED (owner: auto-upload on hold, manual upload only, no credentials needed). Q2-Q5/PR PAUSED, replaced by: **A** delivery format (upload step OFF via `configs/publish.yaml` upload.enabled:false, checked in `tools/daily_video.sh`, code/OAuth untouched, commit `add0792`; every finished video gets a <10MB 1080x1920 two-pass H.264/AAC-128k preview posted to Discord + title/description/tags as copyable plain text + one gate-verdict line; full file stays in `results/`), **B** VIS package (captions: on-screen digits not spelled-out numbers, 2-5 word phrase splits at clause boundaries, clear of the right rail/bottom UI, new gates for all three; species-accuracy prompt library + anatomical pass/fail on the vision judge + regen up to 3x; visual variety >=1 unique image/beat ~18-20 per 60s each <=3s, each shot gets pan/zoom, image reuse capped at 1x; hook shows both subjects frame 0 + voice <=0.25s + ending loops to hook; metadata (title/description/5-8 tags) generated into the manifest) — max 2 worker attempts, stop and report if not done in 7 days, **C** one real sample afterward on a new topic (not T-Rex/Stegosaurus) in format A, render through even on HOLD. No new gates beyond B's, no refactors. Status replies capped at 5 lines.

## Known test-failure baseline
Root `tests/` suite: 64 failing IDs as of 2026-10-03 (was recorded as 63
through WP8-VIS; corrected via a clean-worktree diff during decision #12
part C — one extra pre-existing failure, not a Phase 4 regression), unrelated
to Phase 4 work. `illustrated_engine/tests`: 0 known failures (190/190 as of
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

### WP12 (2026-10-01, `bd9482f`)
Batch runner (DESIGN §13): `v16_batch.py` — preflight (real Claude-CLI
quota/voice/image-tier/music-SFX/disk checks, no secrets), topic
selection (≤2/cluster cap over `v16_topics`), quota pause/resume (gates
*before* a video starts on `llm.available()`, since `text_ask`/`vision_ask`
already swallow `LLMUnavailable` into a fallback by design — real
"resume after a simulated quota at S6" test proven), per-video packaging
(final/proxy/cover/metadata/manifest/scorecard). **Deliberately did not
spend the last render-cap slot**: `LEAD_S=0.30` in `v15_pipeline.py` is
still > the hook-timing gate's 0.25s bound (story-independent, the exact
failure mode WP10's real render hit), and WP10's voice-WER/caption-safe-zone
failures are on shared code no WP since has touched — a real run would
very likely reproduce an already-diagnosed FAIL. Proved real instead:
live preflight, one real `select_topics(2)` call ($0.061), real `ffmpeg`
packaging against an existing `final.mp4`. Tests: 11 new, 227/227 full
suite, root 63/63 unchanged. Report `bench/ab/wp12.md`.

### Q1 (2026-10-02, voice WER)
Audited the metric before touching the pipeline (owner's step 1): found
`qa.asr_model` was `base.en` (confirmed too weak — hallucinated a name +
inserted a phantom word on a real beat) and two real tokenisation bugs
double-penalizing *correct* transcripts (thousands-grouped numbers split by
ASR into fragments that mis-normalise to "zero"; ordinal suffixes like
"30th" expecting a literal unspoken "th" token). Fixed: `asr_model` →
`small.en`, `_merge_number_fragments()` in `align.py`, ordinal-suffix
stripping in `text.py`'s `_NUM` regex, `travelling`/`travelled` added to the
spelling table, 3 lexicon `heard_as` entries (`airburst`, `barographs`,
`meltwater`) for ASR-plausible-spelling misses on real audio. No Kokoro/
pronunciation/pacing changes — the metric itself accounted for WP10's 0.0542
number. Measured on real cached beat audio (no new renders): `tunguska_1908`/
`venus_day`/`fever_thermostat` all 0.0 WER (was 0.0542 FAIL on tunguska).
`bench/checks/Q1.sh` exits 0. Tests: illustrated_engine 227/227 (baseline
227/227), root `tests/` 63/63 failing IDs identical to baseline (diffed via
clean worktree). Report `bench/ab/q1.md` (also flags residual ASR-noise gaps
on 2 other scripts, out of this package's 3-script scope, not fixed).

### VIS (2026-10-02, B1-B5, `3e6b98e`+`92b385a`+`809a244`+`af7411a`+`9cf7190`)
Fixed every failure in the real `t_humans_closer_trex` sample's gate report
without spending a new render. B1 captions: digits on screen
("155-145 million") via `numeralize_cue_words`, narration keeps spelled-out
numbers; 3 new gate checks (numerals/clause-breaks/safe-zone); fixed the
real root cause of the rail overlap (caption box width wasn't capped
against the rail, only the frame margin). B2 species: `species.yaml`
anatomy library + prompt injection + an `anatomy_ok` judge question
(extends the existing plate_qa call, not a new one) + regen loop widened
1->3 rounds. B3: fixed the real cause of the judge's 5 "no_change" frames —
punch-in splits were reusing the identical cached plate; now request a
distinct tight-crop image. B4: `LEAD_S` 0.30->0.18 (hook gate bound is
0.25s; Q2 never ran — checked git log, confirmed). B5: real LLM call
(`v16_metadata.build_metadata`) into pipeline_report.json + manifest.json.
Tests: illustrated_engine 227/227 (baseline), root `tests/` 63/63 failing
IDs identical (1 unrelated pre-existing untracked-dir difference, not from
this change). Report `bench/ab/vis.md` (residuals honestly flagged: no new
full render to prove B2's regen loop or B3's shot-count target live; B4's
hook-both-subjects prompt change unproven on a story that wouldn't already
do it by luck).

### Decision #12 part C (2026-10-03, `56b4955`)
Second real sample, new topic: "A Figure Skater Spins Faster Without Any
Outside Push" (spectacle_physics, score 92 from WP11's real queued set;
T-Rex/Stegosaurus and anything already used excluded). Quote-exists checked
against 3 independent Wikipedia sources — corrected the queued title's
"without adding any energy" overstatement (angular momentum is conserved,
kinetic energy is not; the extra energy comes from the skater's own
muscles). Full real `v15_pipeline` render, synchronous, not forced: **HOLD**,
10/13 gate checks pass (fails: `caption_clause_breaks` 4 cues end on a
function word, `voice` beat B6 WER over the 0.03 limit, `distinctness` shot/
template sequence too close to both prior samples). Delivery format A
preview (5.8MB, two-pass H.264/AAC-128k) + full scorecard in
`~/phase4_out/sample2/`. No code/gates/upload-config touched. Tests:
illustrated_engine 227/227; root `tests/` 64 failing IDs diffed identical
(zero regressions) against a clean worktree of the same HEAD — PROGRESS's
recorded "63" baseline is stale by one test, not a new failure. Report
`bench/ab/topic_figure_skater_source_check.md`.

### Decision #13 (2026-10-03, `0ecca5a`..`05ec835`) — FINAL package before verdict
Six-item package the owner asked for before a go/no-go call. All 6 done;
item 6's real dry run surfaced two real bugs (fixed, not just reported).

1. **Gate fixes** (`0ecca5a`): `check_voice`'s fail message was reporting
   the whole-video AGGREGATE WER mislabeled as one failing beat's own score
   (Sample 2's B6 showed "WER 0.0061" when B6 itself actually scored
   0.0435) — now reports each held beat's real per-beat WER. Root-caused
   B6 itself: `small.en` ASR voiced a correctly-read "ice" as "eyes"
   (near-homophone); added to the lexicon's `heard_as`, confirmed via
   cached audio + `round_trip` simulation (0.0435 FAIL -> 0.0 PASS).
   `distinctness`/`caption_clause_breaks` demoted HOLD -> warning
   (`verdict_of` skips `warning=True` checks) — checks unchanged, severity
   only.
2. **Image-narration matching** (`1450cb9`): `plate_qa`'s existing batched
   judge call gained a `narration_match` question (fails
   `narration_mismatch`, same `MAX_PLATE_REGEN=3` loop already handles any
   fail reason) + a `FRAMING_GUIDANCE` prompt clause against ambiguous
   limb/torso close-ups. Found and fixed a real pre-existing bug along the
   way: `llm/schemas/plate_qa.json`'s `fail` enum never got `bad_anatomy`
   added when VIS B2 shipped it, so a judge response that actually used it
   failed strict schema validation and silently degraded the WHOLE
   `plate_qa` call to `checked:false` — added both `bad_anatomy` and
   `narration_mismatch`.
3. **Subject consistency** (`f1a43c6`): `engine/subject_bible.py` — one
   appearance+clothing description per video (busiest `story["concepts"]`
   entry), generated once via `text_ask`, cached by content hash
   (`v16_metadata` convention), spliced into every matching shot's
   image prompt. Known limitation flagged in the module: plain substring
   match on the concept id, same class of heuristic as `engine.species`.
4. **Topic engine** (`d188ebe`): new `still_image_fit` rubric (0-5,
   weighted 10/100, rebalanced from visualisability/hook_strength) —
   "can a still image carry this topic's core payoff, or is it a dynamic
   process/mechanism?" A score <= 1 hard-skips the candidate (score 0),
   same treatment as an excluded cluster, per the owner's "penalize/skip"
   wording.
5. **Daily-mode cron** (`d08dbd4`, `e8e4eb0`, `05ec835`): closed the gap
   `v16_batch.py`'s own docstring flagged — "turning a freshly ideated
   topic into a renderable story.json needs the research+script engine
   wired live, which it is not yet." New `engine/v16_sources.py`
   (real Wikipedia fetch) + `engine/v16_autostory.py` (topic -> sources ->
   `build_facts` -> `write_story` -> beat-level story.json, HOLDs honestly
   at every stage) wired into `v16_batch --n`. `tools/daily_shorts.sh`
   (cron entry, added to crontab **disabled**, pending this verdict) +
   `tools/daily_shorts_deliver.py` (Discord delivery, format A on PASS,
   reason-only on HOLD, idempotent). Two real bugs found live and fixed
   during the dry run (see item 6): Wikipedia's API 403s without a
   descriptive User-Agent; a materialize-stage HOLD (before any
   `batch_report.json` row exists) was never posted at all.
6. **Dry run** (real, `./tools/daily_shorts.sh 1`, 2026-10-03 10:28 UTC):
   topic engine selected "Earth's Missing Billion Years Hide in Plain
   Rock" (spectacle_physics, score — see `topics_queued.json`); real
   Wikipedia sources fetched, real `research_extract` claims passed the
   quote-check, real `script_write` ran through code-checks + one critic
   rewrite — **HOLD**: critic still scored below the quality bar
   (`hook_strength` 4, `curiosity_gap`/`escalation`/`human_voice`/
   `emotional_charge` 3, mean < 4.0) after the one allowed rewrite, so it
   never became a story dir and never spent a render. Delivered to the
   Discord channel as the HOLD reason, no video (message id
   1555890142521196666) — proves the "HOLD posts the reason, not the
   video" path for real, but **not yet proven**: a topic that clears
   script generation and goes all the way through a real
   render+gate+package+PASS Discord delivery. That is the next thing a
   second dry run would need to hit, whenever the owner authorizes one.

Tests: illustrated_engine 245/245 (237 baseline + 8 new); root `tests/`
1293 passed, 64 failing IDs identical to the known-stale baseline across
every commit in this package (diffed after each commit, not just once at
the end). No secrets committed, no `--no-verify`, `configs/publish.yaml`
`upload.enabled` untouched (still false) — the Discord post in item 5/6 is
a Discord-channel delivery, not a platform upload. Owner's verdict call is
next; no further daily-mode runs until it lands.

### Decision #14 (2026-10-03, `6490d1b`..`9a2e3a1`) — rewrite budget, topic fallback, second dry run
Five-item follow-up to decision #13's single HOLD: give the pipeline more
chances to pass before giving up on a night, and re-check the real pass
rate with a small real sample instead of guessing at it.

1. **Critic scale/threshold** (no change, just documented): `v16_script.py`
   `CRITIC_MEAN_MIN, CRITIC_FLOOR = 4.0, 3` — 8 dimensions scored 1-5 each;
   pass requires mean >= 4.0 AND every dimension >= 3.
2. **Rewrite budget + topic fallback** (`6490d1b`, `9d59673`):
   `MAX_SCRIPT_REWRITES` 1 -> 2 (shared pool across code-error and critic
   rewrites). `materialize_candidates` now falls back to the next-ranked
   topic on a HOLD, up to `MAX_TOPICS_PER_SLOT=3` total per slot, logging
   every attempt (topic id, title, status, reason) to
   `materialize_report.json`'s `attempts` list so a HOLD night is fully
   auditable, not just the final failure.
3. **Step 3 — real 5-topic sample before any prompt change**
   (`illustrated_engine/build_reports/decision14/step3_before_prompt_fix.json`):
   5 real next-ranked topics pulled live off the topic engine's queue, run
   topic -> `script_write` -> critic, no render. Result: **0/5 passed**.
   Per-dimension scores showed `escalation` (1-2 across all 5) and
   `payoff_clarity` (1-2 across 4/5) as the consistent weak dimensions —
   not `human_voice`, which was the original guess going into this.
4. **One allowed prompt fix, then step 4 re-check** (`b4cddf1`,
   `illustrated_engine/build_reports/decision14/step4_after_prompt_fix.json`):
   `llm/prompts/script_write.md` rule 2 rewritten to target escalation and
   payoff clarity directly (`prompt_version` 2 -> 3). Re-ran the *same* 5
   topics end to end (fresh LLM calls, confirmed via new `llm_ledger.jsonl`
   entries and cache files, not a stale copy). Result: **0/5 passed,
   unchanged** — every topic's per-dimension scores and failure reasons
   are byte-identical to the before-fix file. Two of the five topics
   (oceans, lightning) actually fail on the pure-code `check_digits` rule
   (narration numbers vs. on-screen numbers), not the critic at all, so a
   prompt-only fix aimed at critic dimensions couldn't move them regardless.
   Honest finding: **the one allowed prompt fix did not raise the sampled
   pass rate.** The 3-topic fallback chain (item 2) is what actually gives
   a night a better chance to land a render, not the prompt tweak.
5. **Dry run 2** (real, `./tools/daily_shorts.sh 1`,
   2026-10-03 14:59 UTC): topic engine selected a slot; first pick ("The
   Grand Canyon's Rocks Have a Missing Billion-Year Gap") held on
   `check_digits` number mismatches, fell back to the next topic ("Earth
   Once Had a Second Moon That Crashed Into the First") which held the
   same way, fell back to the third and last topic ("This Spacecraft Had
   to Fly Through the Sun's Atmosphere") which held on critic score
   (`escalation`/`loop_coherence` 3, mean < 4.0) after 2 rewrites — all 3
   attempts logged in `materialize_report.json`'s `attempts` list per
   item 2's design. Nothing materialized into a story dir, so nothing
   rendered or spent a render budget. Delivered to the Discord channel as
   the HOLD reason only, no video (message id 1555959337468432547) — the
   fallback-chain + HOLD-posts-reason-only path both worked exactly as
   designed, but given step 3/4's 0/5 sampled pass rate a HOLD here is the
   expected real-world outcome, not a surprise.

Tests: illustrated_engine 248/248; root `tests/` 59 failed + 5 errors = 64
failing IDs, identical to the known-stale baseline (diffed, not assumed).
No secrets committed, no `--no-verify`. `tools/daily_shorts.sh` crontab
entry stays commented out/disabled; `configs/publish.yaml` `upload.enabled`
stays `false`. Net effect of this package: the pipeline now tries up to 3
topics and 2 rewrites per slot before giving up (more resilient to a bad
night), but the underlying script-quality bar is still only clearing on a
minority of sampled topics — that's a content/prompt problem beyond one
rule tweak, not a budget/fallback problem, and is the natural next thing
to dig into before relying on this for unattended nightly output.

### Decision #15 (2026-10-03, `ace72a8`..`b49f933`) — critic calibration,
rank-not-block, dry run 3
Owner's conclusion going in: the script critic itself is miscalibrated
(not just the sampled scripts), because it was scoring 0/10 real sampled
scripts across two separate decision #14 tests. Four items to test that
and build around it.

1. **Calibration** (`ace72a8`, diagnostic only, no code change): ran the
   CURRENT, unchanged `script_critic` (prompt_version 1) against the two
   real samples the owner has actually read. Skater (`56b4955`,
   `t_figure_skater_spin`, owner-rated **ACCEPTABLE**): mean **2.75**, min
   **2** (`curiosity_gap`, `emotional_charge`) — below the OLD
   `CRITIC_MEAN_MIN=4.0`/`CRITIC_FLOOR=3` bar on the owner's own accepted
   sample. T-Rex (`0c7a93f`, `t_humans_closer_trex`, real generated
   `script.txt`/`story_engine.json` existed — not fabricated): mean
   **3.75**, min **3**. Confirms the critic is miscalibrated relative to
   the owner's real bar, not just that the sampled scripts are bad.
2. **Rank-not-block** (`5a3bc9f`): replaced decision #14's "try one topic,
   fall back to the next only on a HOLD" chain with generating scripts for
   up to 3 topics per render slot UP FRONT (≤1 rewrite each if the first
   draft fails the existing `critic_pass` bar), scoring all 3 with the
   real critic, and picking the highest-scoring one. That pick is produced
   only if it clears `RANK_FLOOR_MEAN = min(3.4, 2.75-0.1) = 2.65` with no
   dimension below `RANK_FLOOR_DIM=3` (owner's literal floor formula,
   `SKATER_CALIBRATION_MEAN=2.75` from item 1). New
   `engine.v16_script.rank_write_story` + `engine.v16_autostory.
   generate_story_ranked`; `v16_batch.materialize_candidates` now offers
   each slot 3 topics in one call instead of one-at-a-time. `_pipeline`'s
   fact_check+metadata tail factored into a shared `_finalize` so
   `write_story` (unchanged, still used elsewhere) and the new flow don't
   duplicate that logic. Tests: rewrote the two decision #14 fallback-chain
   tests to the new up-front semantics, added 3 new tests for
   `generate_story_ranked` (picks + finalizes the winner; holds when none
   clears the floor; a research-stage hold on one topic doesn't block the
   other two).
3. **Real 5-topic-infra rank-not-block run** (`b49f933`, no render): 3
   fresh topics off the live topic engine's queue through the new flow.
   Result: **HOLD** — all 3 scored (3.125, 2.75, 3.125 means) but every one
   failed on `RANK_FLOOR_DIM` (min 2, `escalation`/`emotional_charge`
   stuck at 2), the same per-dimension floor the owner's own accepted
   skater sample also fails — not the mean floor. Full critic critiques +
   full plain-text scripts for all 3 candidates saved (the public
   `rank_write_story`/`generate_story_ranked` result deliberately strips
   script text; a standalone re-run hit the same llm-cache keys at zero
   extra cost to recover it for the owner to read).
4. **Dry run 3** (real, `./tools/daily_shorts.sh 1`, 2026-10-03 16:27 UTC):
   ran the new rank-not-block flow through the real cron entry point.
   Topic engine selected a slot; rank-not-block offered 3 topics up front
   ("Siberia's Ancient Eruption...", "Earth Was Once Frozen Solid...",
   "Engineers Once Planned to Ride Nuclear Bombs..."); first two scored
   (3.125, 3.25 means, both min 2) but neither cleared `RANK_FLOOR_DIM`;
   the third held on a pure-code `check_digits` rule before ever reaching
   the critic. Highest scorer (3.25) logged and not picked for render since
   it didn't clear the floor — **HOLD**, delivered to the Discord channel
   as the hold reason only, no video (message id 1555981029498552442) —
   proves rank-not-block's real wiring (3 topics tried up front in one
   call, all logged, best-but-still-failing one correctly not shipped) but
   does not change the underlying sampled pass rate: the real blocker
   across items 3 and 4 is specifically the per-dimension floor
   (`escalation`/`emotional_charge` near-universally scoring 2), the exact
   dimensions decision #14 already flagged as the weak spot.

Tests: illustrated_engine 251/251 (248 - 2 rewritten + 5 new, all green).
Root `tests/`: 59 failed + 5 errors = 64 failing IDs, diffed identical to
the known-stale baseline (zero regressions). No secrets committed, no
`--no-verify`. `tools/daily_shorts.sh` crontab entry stays commented
out/disabled; `configs/publish.yaml` `upload.enabled` stays `false`.
Honest finding: rank-not-block is real, tested, and wired into the live
cron entry point, but on this evidence the quality bar's remaining
blocker is the **per-dimension floor**, not the mean — a script that is
good enough for the owner (skater, mean 2.75) can still fail every
RANK_FLOOR_DIM check the same way an unreviewed topic does, because both
land on `min=2`. That is the next thing worth the owner's attention before
relying on rank-not-block for unattended nightly output.

### Decision #16 (2026-10-03, `ace3c65`..`9a4ac76`) — floor rework, absolute-
claim check, dry run 4
Owner called this the last change before a go-live verdict (within the
2026-10-06 cap), with explicit instruction to still NOT enable the cron —
that's a separate decision the owner hasn't made yet. Three items.

1. **Per-dimension floor rework** (`ace3c65`): decision #15's floor
   (`RANK_FLOOR_MEAN = min(3.4, 2.75-0.1) = 2.65`, `RANK_FLOOR_DIM = 3`, a
   single scalar applied to every dimension) was stricter than the owner's
   own accepted skater sample (mean 2.75, min 2 on
   escalation/emotional_charge) and every real sampled script in step 3 —
   all landed on `min=2`, the exact floor that was supposed to pass them.
   New floor, per the owner's literal re-spec: **mean >= 3.0, every
   dimension >= 2, EXCEPT `payoff_clarity` and `one_idea_only` which must
   each be >= 3.** `RANK_FLOOR_DIM` is now a map
   (`RANK_FLOOR_DIM_DEFAULT=2`, `RANK_FLOOR_DIM_STRICT={"payoff_clarity":
   3, "one_idea_only": 3}`), not a single int; new
   `engine.v16_script.dim_floor()`/`clears_rank_floor()` helpers.
   `rank_write_story`'s picked-candidate check now calls
   `clears_rank_floor()` against the real per-dimension critic scores
   instead of comparing a single scalar `min` to a single scalar floor.
   The rank-not-block mechanics (3 topics up front, <=1 rewrite each, pick
   highest mean, HOLD only if none clears the floor) are unchanged — only
   the floor's values/shape moved. 4 new tests
   (`test_wp4_story.py`).
2. **Absolute-claim check** (`9a4ac76`): new
   `engine.v16_script.check_absolute_claims`, wired into `code_checks`
   alongside `check_script`/`check_facts`/`check_digits` — same rewrite
   budget pipeline, not a separate gate. A sentence making an
   absolute/superlative claim (only, first, never, always, biggest, no
   one, ...; case-insensitive, word-boundary regex,
   `ABSOLUTE_CLAIM_RE`) must be backed by one of ITS OWN cited facts that
   itself states that specific uniqueness/exclusivity — a related fact
   about the same event is not enough, mirroring the bar `check_digits`
   already applies to numbers. Pure-code heuristic, no LLM call: the cited
   fact's own `claim`/`evidence`/`quote` text must carry a matching
   absolute marker. Worked example (decision #15 step 3's real Everest
   script, `build_reports/decision15/step3_full_scripts.json`): "That's
   been done only once, by Tim Macartney-Snape's team in 1990" cites
   `f_sea_level_climb` — Macartney-Snape's 1990 climb was solo/unsupported
   but NOT unique (Kropp made a full sea-level ascent too, in 1996), so a
   fact describing only his climb (without itself claiming nobody else
   has done one) correctly **fails** the check (forcing a rewrite that
   softens to e.g. "solo" + a note that others made similar climbs,
   instead of claiming exclusivity); a fact that *does* explicitly state
   that exclusivity **passes**. No `facts.json` survived from that
   decision #15 run (only `script_text`/`sentences` were saved in the
   build report), so the test fixture
   (`EVEREST_FACT_UNSUPPORTED`/`EVEREST_FACT_SUPPORTED`) is constructed in
   the real `v16_research.build_facts` shape
   (id/claim/evidence/quote/source_id/quote_verified/nuance), not copied
   from a surviving file. 5 new tests (`test_wp4_story.py`): the Everest
   case unsupported (fails) and supported (passes), a softened rewrite of
   the same sentence (no claim left to support), four other
   absolute-claim phrasings (biggest/no one/never/always), and a
   `code_checks` integration test deliberately using a real Tunguska fact
   (`f_eyewitness_vanavara`) chosen because it carries no absolute marker
   of its own — unlike `f_kulik_1927`, whose real claim text happens to
   contain "the first" and would otherwise falsely "support" any absolute
   claim that cited it.
3. **Dry run 4** (real, `./tools/daily_shorts.sh 1`, 2026-10-03 19:23 UTC):
   ran the new floor + the new absolute-claim check live through the real
   cron entry point. Topic engine selected a slot; rank-not-block offered
   3 real topics up front ("The Oldest Living Tree on Earth Predates the
   Pyramids", "Astronomers Found a Planet Made Almost Entirely of
   Diamond", "A Fuel-Free Solar Sail Could Outrun Any Rocket to the
   Stars"); the `llm_ledger.jsonl` pattern for all 3 (script_write,
   script_write, script_critic) confirms every candidate's first draft
   failed a code check (new absolute-claim check live in the mix with the
   rest of `code_checks`) and used its one rewrite before ever reaching
   the critic. Real critic scores: 2.75/min 2, 2.625/min 1, 2.75/min 2 —
   all **below the new RANK_FLOOR_MEAN=3.0** (the per-dimension floor was
   never reached as the binding constraint this time; the mean floor was).
   **HOLD** — nothing materialized into a story dir, so nothing rendered
   or spent a render budget; delivered to the Discord channel as the hold
   reason only, no video (message id `1556025031358812366`,
   `materialize_report.json` + `delivered.json` under
   `illustrated_engine/build/v16/batches/daily_2026-10-03_192311/`). Does
   NOT reach a real render+gate+package+PASS delivery — still the thing a
   future dry run would need to hit. Honest finding: the new floor's mean
   bar (3.0) is now the binding constraint on these 3 real topics, not the
   per-dimension floor decision #15 flagged — a direct sign the floor
   rework moved the real bottleneck rather than eliminating it; raising
   the sampled pass rate itself (prompt/content quality) remains a
   separate, unstarted problem.

Tests: illustrated_engine 260 total, 259 passed (251 baseline + 4 (item 1)
+ 5 (item 2) = 260; one unrelated pre-existing failure,
`test_wp3_voice.py::test_live_lexicon_fixes_tyrannosaurus`, a `KeyError`
reproducing identically on a clean checkout of the prior commit, unrelated
to this change). Root `tests/`: 59 failed + 5 errors = 64 failing IDs,
diffed identical to the known-stale baseline after both commits (zero
regressions). No secrets committed, no `--no-verify`. `tools/
daily_shorts.sh` crontab entry stays commented out/disabled (confirmed
unchanged before and after the dry run); `configs/publish.yaml`
`upload.enabled` stays `false` (confirmed unchanged). Per the owner's
explicit instruction, the cron was NOT enabled despite this being called
the last change before go-live — that remains the owner's separate call.

### Decision #17 (2026-10-04, `282609c`..`2d219aa`) — remove the
critic-score floor, dry run 5
Owner's conclusion going in: the critic itself is unreliable as a
pass/fail gate — it scored the owner's own accepted skater script only
2.75 (decision #15 step 1), and decision #16's dry run 4 showed scores
trending down on objectively stronger topics, not up. Two items.

1. **Remove the floor** (`282609c`): `engine.v16_script.rank_write_story`
   no longer calls `clears_rank_floor()` before finalizing the picked
   candidate — `RANK_FLOOR_MEAN`, `RANK_FLOOR_DIM_DEFAULT`/`STRICT`,
   `dim_floor()`, `clears_rank_floor()` are all removed. The critic still
   runs and scores every one of the (up to 3) candidates — those scores
   are still logged in `candidates`/`materialize_report.json` — but it is
   now a pure ranker: whichever candidate has the highest mean is always
   finalized and returned as the producible story. `generate_story_ranked`
   (`engine/v16_autostory.py`) can now only return `"status": "hold"` if
   every one of the (up to 3) topics fails a HARD check first — a
   research-stage hold (too few sources, failed quote-check) or a
   script-rule `code_checks` failure (`check_script`/`check_facts`/
   `check_digits`/decision #16's `check_absolute_claims`) surviving its
   `RANK_REWRITE_BUDGET=1` rewrite — never on critic score alone.
   Unchanged, confirmed by code inspection: fact verification/sourcing
   checks, the absolute-claim check, every other `code_checks` rule, and
   every downstream video/render gate (voice, captions, distinctness,
   plate_qa/judge, etc.) — none of those are reachable from
   `rank_write_story`/`clears_rank_floor` and nothing in those modules was
   touched. Tests: `test_wp4_story.py` — removed the 4 decision #16 tests
   that directly tested the now-deleted `dim_floor()`/`clears_rank_floor()`
   helpers (no replacement needed; the functions no longer exist, so there
   is nothing left to test). `test_v16_autostory.py` — replaced decision
   #15's `test_generate_story_ranked_holds_when_every_candidate_is_below_
   the_floor` with `test_generate_story_ranked_holds_only_when_every_
   candidate_fails_a_hard_check` (both topics' scripts fail `code_checks`
   twice — bare-question hook — and never reach the critic) plus a new
   `test_generate_story_ranked_picks_the_lowest_scoring_candidate_when_it_
   is_the_only_one` (a single candidate scoring a flat 1 on every
   dimension, mean 1.0, is still picked and finalized — proving there is
   no floor left to clear).
2. **Dry run 5** (real, `./tools/daily_shorts.sh 1`, 2026-10-04 03:14-04:16
   UTC, batch `daily_2026-10-04_031422`): ran the floor-free rank-not-block
   flow through the real cron entry point end to end. Topic engine offered
   3 real topics up front ("The Dinosaurs Never Saw the Rocky Mountains
   Rise", "A Rocket Launched From Earth's Equator Gets a Free Speed
   Boost", "Astronomers Found a Star That Shouldn't Exist Yet"); all 3
   reached the critic this time (no research-stage holds, no code-check
   holds) — scores 2.5/min 1, 2.75/min 2, 3.125/min 2 (recovered verbatim
   from the `llm_cache` entries the critic calls hit, same technique as
   decision #15 step 3). The decision #16 floor would still have HELD
   this exact slot before it ever reached render: the winning candidate's
   `payoff_clarity` scored 2, below decision #16's `RANK_FLOOR_DIM_STRICT`
   requirement of >= 3 for that dimension, even though its mean (3.125)
   cleared `RANK_FLOOR_MEAN=3.0` — a direct demonstration of the floor
   blocking a candidate that, with the floor gone, made it all the way to
   a real render and a real (non-critic) HOLD reason instead. With
   decision #17's floor removed, the highest-scoring candidate
   ("Astronomers Found a Star That Shouldn't Exist Yet", mean 3.125) was
   finalized, retitled by the
   script/metadata stage to "The Dwarf Planet's Disappearing Atmosphere",
   and reached a REAL render for the first time across dry runs 3-5:
   22 min of local plate generation (24 image calls), ffmpeg assembly, and
   the full gate suite (`wall_s=2778.9`). **Real outcome: HOLD at the
   video gate, not the script stage** — `batch_report.json`'s `failures`:
   `caption_clause_breaks` (2 cues ending mid-clause on a function word),
   `judge` (vision judge flagged 6/15 frames, 2 critical frame issues —
   `subject_unrecognizable`/`empty_or_flat` — plus "scenes feel templated"),
   and `distinctness` (template sequence too close to 3 prior videos,
   `t_figure_skater_spin`/`t_humans_closer_trex`/`tunguska_1908`, all under
   the `distance < 0.3` threshold). None of these three gates were touched
   by item 1 — this is exactly the "all other downstream gates stay live"
   behavior the decision called for: removing the critic floor got the
   pipeline past script generation to a real render for the first time,
   and the existing video-quality gates still correctly held it there on
   real defects. Delivered to the Discord channel as the hold reason only,
   no video (per the owner's standing instruction; `delivered.json` marks
   `t_the_dwarf_planet_s_disappearing_atmosphe` delivered, delivery script
   exit 0). Per the owner's instruction for this dry run, full script text
   + critic scores for the picked (and only scored) candidates are
   reported alongside this PASS/HOLD outcome in the dry run's own report,
   not re-litigated here.

Tests: illustrated_engine 257/257 (260 baseline − 4 removed (item 1,
now-deleted floor helpers) + 1 net new (item 1, hold-vs-pick tests) = 257;
the one pre-existing unrelated failure flagged in decision #16
(`test_wp3_voice.py::test_live_lexicon_fixes_tyrannosaurus`) now passes
clean, confirming it was flaky/environmental, not a regression). Root
`tests/`: 59 failed + 5 errors = 64 failing IDs, diffed identical to the
known-stale baseline (zero regressions). No secrets committed, no
`--no-verify`. `tools/daily_shorts.sh` crontab entry stays commented
out/disabled (confirmed unchanged before and after the dry run);
`configs/publish.yaml` `upload.enabled` stays `false` (confirmed
unchanged). No other changes were made, per the owner's explicit "no
other changes" instruction — items 1-2 only.

## Next
Awaiting owner verdict on the dry-run-5 video. The Q2–Q5, PR, WP13 and
WP14 queue is cancelled per decisions #12–#17.
