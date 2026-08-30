# Viral Platform Review — video_engine @ jade (50a57dd), 2026-08-27

**Review type:** Senior-level code + architecture review (read-only; no code modified).
**Reviewer:** Main agent deep read + GLM (glm-5.3-flash via Z.AI) as independent second opinion on the synthesis.

## Objective (everything below is evaluated against this)

> **"This is an agentic AI algorithm platform that must generate viral YouTube videos every day, autonomously, with minimal human intervention."**

**Headline verdict:** Today the system is a *deterministic video compiler with a 9-video ceiling, no distribution wiring, and zero world signal*. "Daily" is currently unmet in practice (the cron path has returned BLOCKED 4+ consecutive days, `logs/daily_cron_runner.log`), and "viral" is unreachable because nothing measures the real world. The engineering quality of the new `engine/` package is genuinely good — clean gates, honest failure classification, real frame-level QA — but it is a science project not yet pointed at production, and the platform-level loop (research → publish → measure → learn) has three of four quadrants missing.

**Scorecard (1–10 vs the objective):**

| # | Dimension | Score | One-line verdict |
|---|---|---|---|
| 1 | Agentic autonomy | **3/10** | Single-shot pipeline; failure = dead end; cron runs the *legacy* stack and has silently failed 4 days straight |
| 2 | Topic scouting for virality | **2/10** | Keyword heuristics over a fixed 13-topic pool; no trends, no saturation detection |
| 3 | Content quality ceiling | **2/10** | 9 hardcoded topics; `engine/research/` is an empty package; unknown topic ⇒ hard-abort |
| 4 | Virality engineering | **4/10** | Good fact-derived hook discipline; no CTA, no packaging, no duration strategy, no music |
| 5 | Measurement/feedback loop | **1/10** | None. QA is technical-only; `learning.json` literally says `"not_run"` today |
| 6 | Robustness/ops | **3/10** | Good local QA gates; no retry/resume/idempotency/alerting; upload not wired to the new path |
| 7 | Code health | **6/10** | New engine package is well-tested and readable; heavy legacy duplication and version skew at repo root |

---

## 1. Agentic autonomy — 3/10

**What works (worth keeping):**
- Genuine self-rejection discipline: no-facts hard-abort (`engine/daily_run.py:150-157`), preflight-before-render budget rule (`daily_run.py` §37 flow), PASS/REPAIR/REGENERATE/ABORT classification (`engine/qa/repair.py:168-191`), and it never forces a failed plan to PASS (`daily_run.py:178-179`).
- Repair loop exists at plan level with max 3 iterations (`daily_run.py:MAX_REPAIR_ITERATIONS`, `engine/qa/repair.py:apply_repair`).

**What's missing:**
- **No retry/supervisor.** `run_daily` catches any exception → ABORT → writes `daily_report.json` → exits (`daily_run.py:248-254`). There is no second attempt, no queue, no next-day escalation, no cross-day state other than `topic_history.json`.
- **Post-render failure is a dead end.** Empirically today (2026-08-27): `results/2026-08-27/gabriel_s_horn_the_shape_you_can_fill_but_never_/daily_report.json` shows `outcome: REPAIR` with `repair_iterations: 0` after full-QA black-frame failure — nothing in the codebase ever acts on a post-render REPAIR. The state machine says REPAIR but no repair agent for post-render failures exists.
- **Preflight/render gate mismatch.** Today's run passed preflight 100 (`preflight_passed: true`) yet rendered 8.0s of black at 0.00–8.00s and 6.5s at 33.75–40.25s (`qa.json` errors). The scene-coverage gate judges the plan; the pixels disagree. Per-beat pre-concat luminance checks are the missing layer.
- **Cron runs the wrong stack.** `crontab`: `0 3 * * * cd /home/ubuntu/video_engine && ./tools/daily_video.sh --runner stills --upload` — this invokes the legacy `mission_stills.py` (140KB monolith) path, **not** `engine/daily_run.py`. `logs/daily_cron_runner.log` shows BLOCKED (exit 3, "no publishable artifact") on 2026-08-24, 25, 26, 27 with no alert and no retry. The new engine has zero production miles.
- **No idempotency/resume.** Re-runs overwrite `results/<day>/<slug>/` in place; a crash mid-render leaves no re-entry point; there is no run ledger.

**Silent degradation points:**
- `record_topic()` is called even when the run failed (`daily_run.py:228` executes before outcome check on the render path... actually it runs unconditionally after step 6, including REPAIR/ABORT outcomes) — failed topics get recency-suppressed, silently shrinking tomorrow's candidate pool.
- Bare `except Exception` swallows real bugs: `daily_run.py:229` and `:240-242` — the learning stage has been silently skipping with `{"status": "not_run"}` because `distill_learning` is passed dicts where `Critique`/`RepairPlan` dataclasses are expected (`daily_run.py:233-236` vs `engine/learning/memory.py:87-90` accessing `critique.problems`). AttributeError → except → "not_run", every single day.

## 2. Topic scouting for virality — 2/10

- `engine/scout/topic_scout.py:default_scores()` is pure keyword matching: "why"/"how" ⇒ curiosity 0.8, visual keywords ⇒ visual_potential 0.85, `search_interest` is a **constant 0.5** (`topic_scout.py:96`). Nothing reads search trends, YouTube suggest, or any external demand signal.
- **Saturation detection is only "topic string in last 10"** (`record_topic`, `max_recent=10`, `topic_scout.py:140-152`). There is no notion of "we've covered pressure physics 5 times this month" beyond a keyword-guessed category penalty, and `_category_penalty` contains dead code — a `for` loop whose body is `pass` (`topic_scout.py:160-162`).
- The candidate pool is hardcoded: 4 regression + 9 unseen topics (`daily_run.py:94-99`, `engine/benchmark/suite.py:38-41`, `engine/benchmark/unseen_eval.py:32-42`). The pool never grows, so "daily topic selection" is really "rotate through 13 fixed strings."
- `record_topic` writes `topic_history.json` to `Path.cwd()` (`topic_scout.py:129-131, 149-151`) — fragile and CWD-dependent; it currently works only because cron `cd`s to the repo root.

## 3. Content quality ceiling — 2/10

- `engine/world/knowledge.py` is a hardcoded `_KNOWLEDGE` dict with exactly **9 topics** (sky blue, satellite orbit, kaprekar, collatz, noise cancelling, popcorn, mcgurk, gabriels horn, monty hall — `knowledge.py:40-417`) plus 9 hand-built semantic worlds (`_WORLD_BUILDERS`, `knowledge.py:880-889`).
- Unknown topic ⇒ `research()` returns zero facts ⇒ `run_daily` ABORTs with `no_topic_knowledge` (`daily_run.py:150-157`). Worse: 7 of the 9 "unseen" eval topics (microwave, ice, lift, GPS, mirrors, barcode, autofocus) have **no knowledge entries**, so the scout's own pool is mostly booby-trapped with topics that abort on contact.
- **Architecture fix (specific):** replace the dict lookup inside `research()` with a three-stage research pipeline:
  1. **Planner stage** (LLM): given topic, produce a research plan (claims to verify, entities, hero mechanism candidate) — `engine/research/` already exists as an empty package (`engine/research/__init__.py`, 0 bytes) waiting for exactly this.
  2. **Evidence stage**: web search (citations required) + deterministic verification reusing the existing `engine/validation/math_verify.py` / `physics_verify.py` pattern; store facts as the existing `Fact(claim, formula, units, assumptions, source)` dataclass so the entire downstream pipeline is untouched.
  3. **Acceptance gate**: a `gate_research` QA gate (≥3 facts, ≥1 numeric claim, ≥1 cited source, no unsupported superlatives) so research quality is gated like render quality. Cache accepted research into a `knowledge/topics/*.json` library (the §6 library tree in `engine/learning/memory.py:28-41` — which has never been created; `knowledge/` doesn't exist at repo root) so day N reuses day N's verified work and the platform compounds.
- The `_generic_world` fallback (`knowledge.py:838-857`) produces a 2-entity "cause → effect" world with no facts — with the new no-facts abort, it is now dead code reachable only via `build_world` outside daily mode; delete or gate it.

## 4. Virality engineering — 4/10

**Exists:**
- Hook discipline: `_fact_hook` forces a concrete ≤12-word, numeric-preferring hook and `_fact_payoff` forces a numeric payoff (`engine/visuals/world_director.py:69-93`) — a genuinely good first-3s rule.
- Template-leak and specificity gates (post-50a57dd) prevent the topic-agnostic script failure (`engine/qa/gates.py:gate_script_specificity`, `gate_scene_coverage`).
- Beat durations rescale to narration (`engine/cli/autonomous.py:_time_beats`), black-frame publish gate, LUFS mastering at −14 (mobile-appropriate).

**Missing:**
- **No CTA / comment-bait / loop mechanics anywhere** — grep confirms no CTA logic in `engine/`. Payoff is always a static end-card measure.
- **No duration strategy.** Output is ~40s by accident of 6–9 beats × 2.4–3.0s defaults (`world_director.py` beat planners). Shorts (≤60s) vs long-form is an unmade decision, and it inverts packaging priorities (Shorts: retention/swipe dominates; long-form: title/CTR dominates).
- **Packaging exists but is unwired and untested in anger**: `engine/publishing/metadata.py` (deterministic titles/tags) and `engine/publishing/thumbnail.py` (single fixed-layout thumbnail, no variants) are never imported by `daily_run.py` or `cli/autonomous.py`. No A/B variants, no CTR-driven selection.
- **No music.** `compose_final(..., music=None, ...)` (`cli/autonomous.py:~370`) — music is a known retention lever and is simply absent from the v0.3 path (the legacy stack had it).
- Topic-specific planners are creeping back into the "generic" director: `_plan_gabriel`, `_plan_monty`, `_plan_collatz` keyed on hero-visualization strings (`world_director.py:711, 806, 867, 979-988`). This is exactly the coupling the module docstring disclaims ("No topic-specific scene selection"), and it means topic N+1 with no authored planner falls to `_plan_cause_effect` — the weakest visual grammar.

## 5. Measurement / feedback loop — 1/10

- **Zero real-world signal.** No YouTube Data API analytics ingestion anywhere (`grep -r analytics engine/ tools/` → nothing relevant). QA gates measure pixels and loudness, never retention, CTR, or AVD.
- The internal learning loop is also broken in practice: `daily_run.py:233-236` passes dicts where `distill_learning(topic, qa_report, critique: Critique, repair_plan: RepairPlan)` expects dataclasses (`engine/learning/memory.py:79-90`) ⇒ AttributeError ⇒ bare except ⇒ `learning.json` = `{"status": "not_run"}` (confirmed in today's artifacts). The §6 knowledge library has never been created (`knowledge/` absent; no `results/benchmark/`, no `results/unseen/` artifacts either — the §33/§34 suites have never been run to artifact).
- `engine/benchmark/suite.py` and `unseen_eval.py` exist with APVR scoring and are good scaffolding — they are just never invoked in production flow, and `learned_rules.yaml` acceptance flow (`memory.py:propose_rule/promote_rule`) has no consumer that feeds rules back into generation.
- **What a real loop looks like (concrete):** after upload (even unlisted), nightly job pulls Analytics API (impressions, CTR, AVD, retention curve at 0s/3s/30s/50%) keyed by run slug into `data/analytics/<slug>.json`; `select_daily_topic` and the hook/title generators read a rolling leaderboard (top/bottom quartile by retention@3s and CTR); variant fields (hook style, title style) are stamped into each run's `daily_report.json` so correlations are attributable.

## 6. Robustness / ops — 3/10

- **Observability is good inside a run** (per-artifact JSON: `qa.json`, `render_diagnostics.json`, `contact_sheet.jpg`, `v03_report.json`), and `logs/llm_metrics/` exists for the legacy path. But there is **no run ledger across days** and **no alerting**: 4 consecutive cron BLOCKED days produced only a log line (`logs/daily_cron_runner.log`).
- **No retry/backoff or provider-failure handling in the v0.3 path** — it's fully deterministic/local (kokoro TTS via `engine/audio/timeline.py:187-211` with Edge-TTS fallback; manim local), which is a robustness *strength*, but it also means zero LLM/web research exists to even have quota problems. When the research stage (P0) lands, add per-run token budget + daily spend cap + circuit breaker then.
- **Crash recovery: none.** `run_autonomous` has no checkpointing; a 4K render failure at minute 5 restarts from zero. `_render_scene` purges the manim media cache per render (`engine/cli/run.py:44-50`) — good fix — yet today's output still has 8s of black opening, so the black-frames root cause is in scene construction (likely beats whose objects/kinetic title compile to nothing against the navy background), not staleness. Bisect by rendering each beat type standalone with frame-hash diffs — it's deterministic, so this is cheap.
- **YouTube upload**: `tools/youtube_upload.py` exists with the unlisted hard-guard (correct; keep) but is only invoked by the legacy `daily_video.sh`. The new engine path has no publish step at all.
- `topic_history.json` written to CWD (see §2). `daily_video.sh` rotates through 5 fixed topics by day-of-year (`tools/daily_video.sh:36-42`) — not a scout, a counter.

## 7. Code health — 6/10

- **The `engine/` package itself is healthy**: 52 test files, the virality gates have a dedicated regression test rooted in the real failure (`tests/test_virality_gates.py`), schemas are validated, and the QA report distinguishes technical vs perceptual scores honestly. Strong work.
- **Repo-root duplication / version skew is severe**: `mission_run.py` (152K), `mission_stills.py` (140K), `orchestrator.py`, `video_engine_consolidated.py`, `fermi_render*.py`, `olbers_render_v2/v3.py`, `render_v4/v5/v5_1.py`, `fix_purpose*.py`, plus `src/` — three generations of engine coexist. `engine/qa/gates.py`'s `__main__` block is itself broken (references undefined `vs` at `gates.py:1153` — would NameError).
- The v1→v2 shim layer (`gates.py:_v1_shims`, `_V1_TYPE_MAP`) is honest about the skew but means two type systems must be kept coherent forever; plan the v1 retirement.
- Config sprawl: `configs/voices.yaml` governs the legacy stack (Fish TTS); the v0.3 path uses kokoro with `voice=""` (`cli/autonomous.py:~120`) — two narrator regimes, and the TOOLS.md "ElevenLabs Declan Sage" note matches neither path. One voice config should serve both or the old one must die with the legacy stack.
- Dead code: `_generic_world` (post no-facts-abort), `_category_penalty`'s `pass` loop (`topic_scout.py:160-162`), `gates.py:__main__`, `engine/research/` empty package.

---

## Prioritized Roadmap

### P0 — make the daily artifact real and observable (this week, all <1 day each)

1. **Fix the state machine's post-render dead end** (`engine/daily_run.py:206-215`): when full QA fails with `outcome=REPAIR`, actually run a stage-scoped response — at minimum one re-render with the failing beats isolated; if not fixable, emit `ABORT` + alert, never a silent REPAIR. Also map "preflight passed but render failed" to a distinct outcome code so the gate mismatch is measurable.
2. **Per-beat pre-concat QA** (`engine/cli/run.py:_render_scene` / `engine/composition/ffmpeg_compositor.py:compose_final`): after manim renders each clip, sample 1 fps grayscale and apply the existing `gate_black_frames` logic per clip before composing; retry the single failed beat once (different seed/camera). Converts run-killing failures into beat-level retries. Then bisect the current 0–8s black opening by rendering `b001`/`b002` standalone with frame-hash diffs (deterministic ⇒ cheap root-cause).
3. **Cut over the cron to the new engine** and freeze the legacy path: change the crontab entry to `./venv/bin/python -m engine.daily_run --res 4k --render --upload`, and port (a) the `youtube_upload.py` invocation and (b) STATUS/PUBLISH gating into `daily_run.py` as a step 9. Delete or archive `mission_stills.py`/`daily_video.sh` once green for 5 consecutive runs (do not dual-run — one production stack).
4. **Honest failure + alerting**: add a dead-man's switch (healthchecks.io ping or Discord webhook) on any non-PASS daily outcome, and fix `topic_history.json` to write to the repo root regardless of CWD (`engine/scout/topic_scout.py:129-131,149-151`). Stop calling `record_topic` on non-PASS runs (`daily_run.py:228`).
5. **Fix the learning-call bug** (`engine/daily_run.py:231-242`): construct real `Critique`/`RepairPlan` objects (or add a dict-accepting overload in `engine/learning/memory.py:distill_learning`), and ban bare `except Exception` around it — the AttributeError it masked is the reason `learning.json` has said `not_run` forever.
6. **Wire packaging into the daily path**: call `engine.publishing.metadata.generate_metadata` + `engine.publishing.thumbnail` from `run_daily` step 8, and emit 2–3 title/thumbnail variants per run so the future analytics ledger has variants to compare from day one.

### P1 — the two structural unlocks (research + measurement)

7. **LLM research stage with deterministic verification** (replaces the 9-topic ceiling; implement in the empty `engine/research/`):
   - `engine/research/agent.py`: topic → LLM research plan → web evidence fetch (citations mandatory) → `Fact(...)` list using the existing dataclass.
   - `engine/validation/verify_claims.py`: numeric/formula claims verified via the existing `math_verify`/`physics_verify` pattern; unverifiable numeric claims are dropped, not softened.
   - `engine/qa/gates.py:gate_research`: ≥3 facts, ≥1 numeric claim, ≥2 distinct sources; wire into `run_preflight_v2`.
   - Cache accepted research at `knowledge/topics/<slug>.json` (creates the §6 library); `research()` becomes cache-first, LLM-second. Include per-run token budget + daily spend cap here.
8. **Analytics ingestion + leaderboard** (`tools/analytics_pull.py` new, plus `engine/learning/leaderboard.py`): nightly YouTube Analytics API pull (impressions, CTR, AVD, retention@3s/@30s) keyed by run slug → `data/analytics/`; `select_daily_topic` and the hook/title generators consume a rolling top/bottom-quartile report. This is the precondition for anything labeled "viral optimization."

### P2 — virality depth and hygiene

9. **Scout rebuild on demand signals**: replace `default_scores` keyword heuristics with YouTube search-volume/trends scoring + saturation check (topic and *semantic neighbors* vs full `topic_history`, not just last-10 strings); delete the dead `pass` loop (`topic_scout.py:160-162`).
10. **Stage supervisor with persisted state**: per-stage artifacts + re-entry points (plan→preflight→render→qa→publish as resumable stages with a ~100-line state file; no Temporal/Airflow needed for one daily job).
11. **Duration/format decision + CTA**: decide Shorts vs long-form explicitly; if Shorts, add first-3s motion guarantee (gate: scene-change within 1.5s), end-loop, and comment-bait payoff lines; add a music bed to `compose_final` (the parameter already exists).
12. **Version-skew retirement**: plan the v1 gate type retirement, unify narrator config across stacks, remove `_generic_world`, `gates.py:__main__`, and repo-root one-off scripts into `docs/archive/` or `scripts/legacy/`.

---

## GLM second opinion — points of disagreement / sharpening (verbatim highlights)

- "You have one production stack (legacy) and one science project (engine). Don't wire the new engine to cron as an experiment — port upload/fallback, cut over, delete legacy."
- "Cache purge was a red herring. Black output persisting post-purge means scene *construction* is broken for certain beat types... Stop treating it as an environment problem."
- "Post-render repair is the wrong layer entirely... don't build a post-render repair loop at all — build per-beat/per-stage retry."
- "`record_topic` on failed runs is a live scout bug: failed topics get recency-suppressed... silently compounds the 9-topic ceiling."
- "Unlisted-enforced upload is correct — keep it for now... loosen the gate only after N consecutive clean runs *and* measured metrics."
- "Decide Shorts vs long-form now... that makes black 0–8s *existentially* fatal."

## Bottom line

The engine got dramatically better this week (the 50a57dd gates are the right instincts), but it still can't run daily (cron on the wrong, failing stack), can't make a new video (9-topic ceiling), and can't learn (no loop, learning stage broken). Sequence: P0 reliability (≤1 week) → research pipeline + analytics loop (the two structural builds) → virality optimization feeds off real data. Until the measurement loop exists, every "virality" change is guesswork.
