# JADE V0.3 — Gap Analysis vs the 49-Point Directive

- **Date:** 2026-08-21
- **Repo:** `/home/ubuntu/video_engine`, branch `jade`
- **Mode:** READ-ONLY. No code modified. Evidence = file:symbol references.
- **Inputs:** `docs/v03/JADE_V03_DIRECTIVE.md` (full), `docs/v03/DESIGN.md`, `docs/audit/engine-current-map.md`, `docs/audit/mm-lab-v02-audit.md`, engine sources, schemas, tests, `git status --short` + `git diff --stat HEAD`.

---

## 1. CURRENT-STATE SUMMARY

### 1.1 Entry points (two parallel pipelines)

| Entry | Purpose | Status |
|---|---|---|
| `python -m engine.cli.run` (`engine/cli/run.py::run`, `main` :430) | v1 pipeline: narration → TTS-first timing → `visual_director.direct()` (beatsheet+shotlist) → v1 VisualSpec → `compiler.compile_to_file` → Manim render → compose → `gates.run_all`. Default topic = Kaprekar benchmark. | ✅ works (committed baseline, correctness sprint) |
| `python -m engine.cli.autonomous` (`engine/cli/autonomous.py::run_autonomous`) | v2 autonomous pipeline: **topic-only input** → research → world → representation → story/hero → script → TTS → v2 VisualSpec → `world_compiler.compile_world_to_file` → render → compose → `gates.run_all_v2` → v03_report. Flags: `--res dev/hd/4k`, `--no-render`. | ✅ works for known topics; **untracked** (new in working tree) |

### 1.2 Artifact flow (what is actually written, in order — autonomous.py)

`autonomous.py` `run_autonomous()`:
1. `research.json` — `research(topic)` (`engine/world/knowledge.py:research`) — **deterministic KB lookup, NOT web research**. Empty for unknown topics.
2. `world.json` — `build_world(topic)` (`knowledge.py:build_world`) — per-topic world builders for 5 topics; `_generic_world` fallback (trivial cause→effect).
3. TTS narration synthesized locally (kokoro) → word timing.
4. `visualspec.json` (v2) — `build_visualspec` (`engine/visuals/world_director.py::build_visualspec`) — beats + semantic actions + world + hero + explanation report embedded in metadata.
5. `story_plan.json` — template name/rationale/roles/hero/representation (bundled, not split).
6. `world_scene.py` (in work/) — `compile_world_to_file` (`engine/renderers/manim/world_compiler.py`).
7. Render → `final.mp4` → compose (narration+captions+LUFS master).
8. `qareport.json` — `gates.run_all_v2` (`engine/qa/gates.py`).
9. `script.json`, `audio_timing.json`, `scene_state_log.json`, `render_diagnostics.json`, `contact_sheet.jpg`, `v03_report.json`.

v1 (`run.py`) additionally writes `beatsheet.json` and `shotlist.json`.

### 1.3 What actually runs end-to-end today

- **`results/sky_blue_v03/` is a real completed autonomous run** (2026-08-20 21:01–21:02): research.json, world.json, visualspec.json, story_plan.json, script.json, audio_timing.json, scene_state_log.json, qareport.json, render_diagnostics.json, v03_report.json, contact_sheet.jpg, final.mp4. `qareport.json`: **passed=True, tech=100, perc=100, score=100**, all 10 gates green (incl. explanation avg 3.857 ≥ 3.5, text-dominance 0.143 < 0.35). Log: `logs/sky_blue_v03_run2.log` ends "✅ PASSED".
- **Only the sky-blue topic has been run autonomously.** Satellite/kaprekar/collatz/mcgurk have knowledge entries and would run, but no evidence of recent full runs. Noise-cancelling headphones and popcorn have **no** knowledge entry → would hit the trivial generic fallback (see §4 risks).

### 1.4 Uncommitted vs committed (git status)

**HEAD baseline is committed** (per `docs/audit/engine-current-map.md`, HEAD `8b698b5` = v4 publishing + benchmark tool; correctness-sprint work per diff stat: timeline.py, run.py, ffmpeg_compositor.py, manim_primitives.py, gates.py, compiler.py, math_verify.py, visual_director.py were already committed before this audit? — no: the *current* working tree shows further edits).

**Modified (tracked, uncommitted):**
- `engine/qa/gates.py` (+183 lines — v2 semantic gates: `gate_explanation`, `gate_text_dominance`, `run_all_v2`, v1 shims)
- `engine/validation/schema.py` (+8 — v2/world validators)
- `tests/test_kaprekar_correctness.py` (+11)

**Untracked (new, all of Phase A's v0.3 core):**
- `engine/cli/autonomous.py`, `engine/world/` (whole package: world_model, knowledge, representations, actions, story_templates, scoring), `engine/visuals/world_director.py`, `engine/primitives/world_primitives.py`, `engine/renderers/manim/world_compiler.py`, `engine/validation/physics_verify.py`, `schemas/worldmodel_v1.schema.json`, `schemas/visualspec_v2.schema.json`
- `docs/v03/JADE_V03_DIRECTIVE.md`
- Run artifacts: `results/sky_blue_v03/`, `results/kaprekar_bench_*`, many `results/*/`, `logs/*`, media/, tmp/, tools/ scripts, `video_engine_consolidated.py`, `rebuild_smoke.py`, `concat_list.txt`, `.env.bak`, `configs/voices.yaml.bak-20260816`

**Risk:** the entire v0.3 autonomous architecture is uncommitted. A `git clean`/reset would destroy it. Phase A should start by committing the working tree as the v0.3 baseline.

### 1.5 Module inventory (what exists)

- **world layer** (no Manim imports): `WorldState` + `EntityType` closed registry + `Fact` (formula/units/assumptions/source/verified) (`world_model.py`); `research`/`build_world` KB for 5 topics (`knowledge.py`); `RepType` 16-value enum + keyword rule table (`representations.py`); `Action` 31-action vocabulary + `ACTION_REGISTRY` action→primitives (`actions.py`); 7 `StoryTemplate`s + `select_template` + `hero_for` (`story_templates.py`); per-beat explanation score 0–5 + text-dominance ratio (`scoring.py`).
- **visuals**: `world_director.py` = v2 spec builder with per-representation beat planners (SIGNAL_FLOW / PHYSICAL_MODEL / SIMULATION / MATH / CAUSE_EFFECT); `visual_director.py` = v1 director (LLM path + deterministic kaprekar + generic narrative fallback); `scene_state.py` = ENTER/UPDATE/EXIT lifecycle + zone-conflict guard.
- **primitives**: `world_primitives.py` ≈ 1,545 lines, 42+ primitives: CelestialBody, OrbitPath, MovingBody, FollowBody, FallBody, AccelerateBody, CollideBodies, ImpactBurst, MissBody, CurvePath, TracePath, OscillateBody, VelocityVector, ForceVector, ReferenceFrame, ProjectilePath, LightSource, LightRay, Wave, SignalPulse, ParticleField, ScatteringField, CrossSection, RevealInside, MediumLayer, Node, Connection, FlowThrough, BranchFlow, MergeFlow, Timeline, CauseEffectChain, MeasureValue, EyeGlyph, EarGlyph, BrainGlyph, MouthGlyph, QuestionMark, ExperimentBadge, RevealText, PayoffText, AssembleBodies, DisassembleBodies + `materialize_entity` (ENTITY_MATERIALIZERS :1066) + `apply_action` (ACTION_NATURAL_DURATION :1239).
- **renderers**: `world_compiler.py` (v2; physics guard `_physics_guard`, SceneState lifecycle, camera ops `camera_focus/reset`, duration budget, kinetic-text-last fallback); `compiler.py` (v1, untouched: `_TRANSFORM_MAP`, `_math_guard`, `_trajectories_for`).
- **validation**: `math_verify.py` (kaprekar/arithmetic/labels), `physics_verify.py` (rayleigh ratio, orbital speed, kepler, collatz, free-fall), `schema.py` (v1+v2+world validators, cross-refs).
- **qa**: `gates.py` 12 gates: `gate_schema`(1) `gate_semantic`(2) `gate_mathematical`(3) `gate_layout`(4) `gate_motion`(6) `gate_continuity`(7) `gate_audio`(8) `gate_technical`(9) + `frame_visual_qa`, `frame_layout_qa` + v2 `gate_explanation`, `gate_text_dominance`; `run_all` (v1) and `run_all_v2`.
- **audio/compose**: `engine/audio/timeline.py` (kokoro→edge TTS, ebur128 LUFS, ducking helpers); `engine/composition/ffmpeg_compositor.py` (compose, SRT, contact sheet, mastering).
- **publishing**: `engine/publishing/metadata.py` + `thumbnail.py` exist but are **NOT wired** into run.py or autonomous.py.
- **empty stubs** (0 bytes): `engine/research/`, `engine/story/`, `engine/beats/`, `engine/subtitles/` — `__init__.py` only.
- **schemas** (8): audio_cue_v1, beatsheet_v1, qa_report_v1, shotlist_v1, style_spec_v1, visualspec_v1, **visualspec_v2**, **worldmodel_v1** (new, untracked).
- **configs**: engine reads **only** `engine/config/style.yaml` (loader globs `engine/config/*.yaml`). The 13 root `configs/*.yaml` (pipeline, render, voices, providers, models, planner, research, visual_director, …) drive the **legacy** `src/` pipeline only — the engine ignores them.
- **tests**: 38 files ≈ 800 tests, but engine coverage = **only `tests/test_kaprekar_correctness.py`** (12 tests, headless StubScene: digit reorder identity, CompileError paths, SceneState ENTER/UPDATE/EXIT, compile_to_file). **No test covers** world package, world_director, world_compiler, autonomous.py, run_all_v2, scoring, or physics_verify. `grep -rn "autonomous\|engine.world" tests/` → no hits.

---

## 2. DIRECTIVE COVERAGE TABLE (all 49 points)

Legend: ✅ DONE · 🟡 PARTIAL · ❌ MISSING. Evidence = file:symbol.

| # | Directive point | Status | Evidence | Note |
|---|---|---|---|---|
| 1 | Don't optimize for one benchmark video | 🟡 | `knowledge.py:_WORLD_BUILDERS` (5 topics); `world_compiler` fully generic | No topic-specific *scene code*, but per-topic **world data + facts are hand-authored** for 5 topics; unknown topics get a trivial fallback — the discovery capability is not yet general. |
| 2 | The core product is the program | 🟡 | design + generic pipeline | Architecture is right; no metric tracks manual intervention / generalization (cf. §41–42 missing). |
| 3 | Target end-to-end daily loop | 🟡 | `autonomous.py` covers research→…→QA; no discovery/scoring/thumbnail/publish/repair/learning stages | Half the loop exists; the other half (scout, repair, learn, publish, daily mode) missing. |
| 4 | Make the system agentic (13 roles) | 🟡 | see §3.2 role table | 7 roles exist as code; 6 missing/partial (TopicScout, RepairAgent, LearningAgent, Publisher, FactChecker, AudioDirector partial). |
| 5 | Every stage produces a machine-readable artifact (15 files) | 🟡 | see §3.1 artifact table | ~10 artifacts written, several bundled/misnamed vs spec (no topic.json, facts.json, story.json, hero.json, beats.json, shots.json, visual_plan.json, repair_plan.json, learning.json; audio_timeline.json written as `audio_timing.json`; qa.json written as `qareport.json`). |
| 6 | Long-term knowledge library | ❌ | `knowledge.py` is a hardcoded dict; no `knowledge/` tree (topics/, visual_patterns/, primitives/, simulations/, camera_patterns/, audio_patterns/, successful_shots/, failed_shots/, qa_failures/, learned_rules/) | Nothing persists across runs. |
| 7 | Visual pattern library | 🟡 | `world_director.py:REP_PLANNERS` (5 families) | Patterns exist as code, not as a reusable/persistent library. |
| 8 | Story template library | 🟡 | `story_templates.py:TEMPLATES` (7 templates) | Static code dict, not an evolving library; selection deterministic keyword rules only. |
| 9 | Hero mechanism first-class object | 🟡 | `world_model.py:HeroMechanism` (concept/visualization/target_beat); `story_templates.py:hero_for`; in world.json + visualspec metadata | Spec wants `{concept, representation, objects, actions, why_this_visual}` — **why_this_visual, objects, actions are missing** from the object. |
| 10 | Hero-mechanism quality control | ❌ | no `hero_quality` check anywhere | Hero beat only gets `importance=high` in `world_director.build_visualspec`; no FAIL→revise loop. |
| 11 | Representation selection general, default not text | ✅ | `representations.py:RepType` (16 values), `_RULES` keyword table, `is_kinetic_text_only`; KINETIC_TEXT never a rule outcome | DONE. LLM tie-break param (`llm_override`) exists but autonomous.py never passes it — acceptable (deterministic-first). |
| 12 | "Why this visual?" reasoning per beat | 🟡 | `scoring.py:score_beat` returns per-beat `reason` | The reason is a *score rationale* ("direct demonstration via …"), not the spec's design-intent record `{concept, representation, visual, reason}`. |
| 13 | Visuals must explain, not decorate | 🟡 | `scoring.py` 0–5 levels + `dominated_by_low`; `gates.py:gate_explanation` | Implements the *spirit* (avg ≥3.5, no 0–2 dominance); spec's 6-class taxonomy (demonstrate/illustrate/compare/emphasize/transition/atmosphere) not used. |
| 14 | Kinetic typography demoted | ✅ | `scoring.py:TEXT_PRIMARY_VISUALS` + `text_dominance_ratio` (<0.35); `world_compiler.py:_narrative_call` used only when no semantic calls | DONE + gate enforced (`gate_text_dominance`). |
| 15 | General semantic world model | ✅ | `world_model.py:WorldState` (entities/relationships/states/forces/signals/measurements/labels/facts/paths/camera/hero); `schemas/worldmodel_v1.schema.json`; `validate()` | DONE (events not explicit; sources ride on Fact). |
| 16 | Relationships first-class | 🟡 | `world_model.py:Relationship` + `REL_KINDS` + validation; present in worlds | Relationships are data, but the director can't *request operations on relationships* (show/animate/highlight/reverse/break/strengthen/compare) — actions target entities only. |
| 17 | Expand action grammar | 🟡 | `actions.py:Action` (31 actions) + `ACTION_REGISTRY`; `world_compiler` raises on unknown actions | Spec lists 35 incl. `enter, exit, move, grow, shrink, rotate, diverge, pulse, propagate, hide` — **absent**. `interfere`/`cancel` (needed for noise-cancelling §46) absent. Fail-closed behavior ✅. |
| 18 | Simulation first-class | 🟡 | `physics_verify.py` (rayleigh/orbit/kepler/collatz/free-fall); `_SIMULATION_ACTIONS` in autonomous.py; deterministic primitives (FallBody, ScatteringField, …) | No generic parametrized simulation framework (`{"simulation": "wave_interference", "parameters": {...}}`); no wave-interference/pressure simulations yet. |
| 19 | Separate world model from rendering | ✅ | world package has zero Manim imports; `world_compiler` consumes `WorldState.from_dict` | DONE. |
| 20 | Composition as explicit stage (CompositionPlanner) | ❌ | no composition planner; camera ops are per-beat `_camera_call` in world_compiler | Phase B work; no focal/scale/arrangement/hierarchy/negative-space planning. |
| 21 | Attention as design objective + metrics | ❌ | `frame_layout_qa` zone-density is the only proxy | No focal_area_ratio / semantic_object_area / empty_area_ratio / text_area_ratio / focal_contrast. |
| 22 | Pacing intelligence | 🟡 | narration-sized durations (`autonomous.py:_time_beats`, `run.py` TTS-first); `importance` field | No explicit pacing language (fast reveal/slow explanation/pause/build/escalation/climax/release); all beats ~equal structure. |
| 23 | TTS is temporal input, not story designer | ✅ | `autonomous.py` script → TTS → `_time_beats`; `run.py` TTS-first | DONE. |
| 24 | Daily topic engine (TopicScout) | ❌ | no topic-scoring module | Missing entirely. |
| 25 | Topic diversity / rotation | ❌ | no category/representation tracking across runs | Missing. |
| 26 | Video profile before generation | 🟡 | `story_plan.json` (topic/template/hero/representation/rationale) | Spec profile wants + category, target_duration, visual_style, primary_primitives, risk_flags — missing. |
| 27 | Risk-based planning | ❌ | no risk fields (factual_risk, math_risk, physics_risk, visual_complexity, asset_dependency, copyright_risk, rendering_complexity) | Missing. |
| 28 | Self-critique before render | ❌ | schema/explanation gates run pre-render, but no agentic 9-question critique | Missing. |
| 29 | Self-critique after preview (score/strengths/problems/repair_actions) | ❌ | `contact_sheet.jpg` + frame QA produced, never vision-reviewed | No post-preview critic loop; problems not tied to beats. |
| 30 | Automatic repair must be local | ❌ | single full-scene render (`_render_scene`); no per-beat rerender/recompose | Missing. |
| 31 | Learning agent → learning.json | ❌ | no learning module | Missing. |
| 32 | Learning must not modify code directly | ❌ | no learned_rules.yaml, no proposal→tests→benchmark→acceptance→promote machinery | Missing (promotion mentioned in docstrings only). |
| 33 | Regression benchmark suite (5 topics) | 🟡 | 5 topics present in `knowledge.py`; runnable via same program | No parametrized suite/runner recording story/visual/explanation/text-dominance/QA/render-time/failures across runs. |
| 34 | Unseen-topic evaluation | 🟡 | generic fallback lets *any* topic compile (`_plan_cause_effect`) | True generalization test (noise-cancelling, popcorn, microwave, …) would produce trivial cause→effect visuals — not the distinct grammars required. |
| 35 | Daily autonomous mode (`engine.daily_run`) | ❌ | only per-run CLI `engine.cli.autonomous` | No `results/YYYY-MM-DD/topic_slug/` scheduling. |
| 36 | Daily failure policy (PASS/REPAIR/REGENERATE/ABORT) | ❌ | `qareport.passed` boolean only | No classification, no regeneration/repair/abort decisions. |
| 37 | Budget/compute management (4 CPU/24 GB) | 🟡 | preview-first (`--res dev` default, `--no-render` compile-only) | No caching, no incremental rendering, no limited concurrency. |
| 38 | DeepSeek for high-value reasoning only | 🟡 | deterministic everywhere in autonomous path; LLM only in v1 `visual_director._direct_llm` (optional) | DeepSeek is *not used at all* for story/hero/critique/repair/learning — the intended "high-value" LLM role is unwired in the autonomous path. |
| 39 | Cheaper over time (caching) | ❌ | no caching anywhere | Missing. |
| 40 | Promote successful patterns into library | ❌ | no promotion mechanism | Missing. |
| 41 | QA measures the program, not only the video | ❌ | `v03_report.json` has per-run fields, but no time-series tracking (repair rate, APVR, …) | Missing. |
| 42 | Real success metric (APVR) | ❌ | not computed | Missing. |
| 43 | Don't overfit reference channels | 🟡 | no reference-channel code in engine | Principle respected by construction; nothing to verify. |
| 44 | Keep MathMotion Lab as R&D | ✅ | lab isolated at `~/mathmotion-lab`; provenance list `_FROM_MATHMOTION_LAB` in autonomous.py; mm-lab audit documents promotion path | DONE. |
| 45 | Priority order (Phases A–J) | 🟡 | Phase A exists (autonomous.py + world layer) | Phases B–J not started. |
| 46 | First development test (3 topics, distinct grammars) | 🟡 | sky-blue ✅ PASSED (SIMULATION+SIGNAL_FLOW: light+atmosphere+scattering); noise-cancelling → rules map "sound/wave" → SIMULATION+SIGNAL_FLOW but **no world data** → generic cause→effect beats; popcorn → CAUSE_EFFECT (rules) but **no world data** | Engine can *select* different reps by keyword, but two of three topics lack semantic worlds/primitives → will not yet produce the required wave+microphone+inverse-signal+interference / water+pressure+shell+explosion visuals. |
| 47 | Key design test (JSON plan self-explanatory) | 🟡 | world+actions JSON is semantic and meaningful; `visualspec.json` carries entities/actions/scores | No automated check enforcing "plan readable without narration"; generic fallback plans would fail this test. |
| 48 | Final definition of done | 🟡 | known-topic path: research/story/script/hero/world/rep/beats/animation/audio/QA/final video ✅ | Missing: thumbnail/metadata in autonomous, repair, learning, cross-domain generality, library improvement. |
| 49 | Most important principle (figure out HOW) | 🟡 | architecture is exactly this (semantic world → generic compiler); but 5 hand-authored worlds mean discovery isn't real yet | The engine computes, it does not yet *discover*. |

**Tallies:** ✅ 6 · 🟡 21 · ❌ 22.

---

## 3. PHASE A EXECUTION PLAN

**Goal:** topic-only input → autonomous video for the §46 first dev test: same program on (a) "Why is the sky blue?" (b) "How do noise-cancelling headphones work?" (c) "Why does popcorn pop?" — three *different* visual grammars, no manual storyboards.

### 3.1 Artifact status (15 spec artifacts)

| Artifact | Status | Produced by | Notes |
|---|---|---|---|
| topic.json | ❌ MISSING | — | topic only inside metadata/story_plan |
| research.json | ✅ EXISTS | `autonomous.py` ← `knowledge.py:research` | deterministic KB; empty for unknown topics |
| facts.json | ❌ MISSING | — | facts embedded in research.json + world.json |
| story.json | ❌ MISSING | — | bundled as `story_plan.json` (template/roles/hero/rep) |
| script.json | ✅ EXISTS | `autonomous.py` (`_script_from_words`, post-render) | derived from TTS word timing |
| world.json | ✅ EXISTS | `knowledge.py:build_world` | |
| visual_plan.json | ❌ MISSING | — | role of `visualspec.json` (v2) |
| hero.json | ❌ MISSING | — | inside story_plan.json + visualspec metadata |
| beats.json | ❌ MISSING | — | inside visualspec.json (`beats`) |
| shots.json | ❌ MISSING (v1 only) | `run.py` writes `shotlist.json` (v1) | v2 path has no shots artifact |
| visualspec.json | ✅ EXISTS | `world_director.build_visualspec` | v2, with world+hero+scores |
| audio_timeline.json | 🟡 PARTIAL | `autonomous.py` writes `audio_timing.json` | wrong filename vs spec |
| qa.json | 🟡 PARTIAL | `gates.run_all_v2` → `qareport.json` | wrong filename vs spec |
| repair_plan.json | ❌ MISSING | — | no repair stage |
| learning.json | ❌ MISSING | — | no learning stage |

### 3.2 Agent role status (13 roles)

| Role | Status | Evidence |
|---|---|---|
| TopicScout | ❌ MISSING | — |
| Researcher | 🟡 PARTIAL | `knowledge.py:research` — deterministic KB, no web, no unknown-topic research |
| FactChecker | 🟡 PARTIAL | facts carry sources + `math_verify`/`physics_verify` guards in compiler; no standalone fact-check stage |
| StoryArchitect | ✅ EXISTS | `story_templates.py:select_template` |
| VisualDirector | ✅ EXISTS | `world_director.py:build_visualspec` (+ v1 `visual_director.py:direct`) |
| HeroMechanismDesigner | ✅ EXISTS | `story_templates.py:hero_for` (+ `world_model.HeroMechanism`) |
| WorldBuilder | ✅ EXISTS | `knowledge.py:build_world` |
| AnimationDirector | 🟡 PARTIAL | `world_compiler.py` + `actions.ACTION_REGISTRY` — direction is data-driven; no distinct animation-planning role |
| AudioDirector | 🟡 PARTIAL | `audio/timeline.py` TTS+master; no SFX synthesis, no music selection (music=None in compose) |
| QAReviewer | ✅ EXISTS | `qa/gates.py:run_all` + `run_all_v2` (12 gates) |
| RepairAgent | ❌ MISSING | — |
| LearningAgent | ❌ MISSING | — |
| Publisher | ❌ MISSING (in autonomous) | `publishing/metadata.py`+`thumbnail.py` exist but unwired |

### 3.3 Ordered file-level steps (Phase A → §46 dev test)

**Step 0 — Commit the working tree** (safety, not code):
`git add` engine/world, world_director, world_primitives, world_compiler, autonomous.py, physics_verify, schema.py, gates.py, v2/world schemas, tests; commit as "v0.3 autonomous core baseline". Rationale: the entire Phase A architecture is currently untracked.

**Step 1 — Knowledge data for the 3 test topics** (`engine/world/knowledge.py`):
Add `_KNOWLEDGE` entries + `_WORLD_BUILDERS` for:
- *noise-cancelling headphones*: entities wave/sound → microphone → processor → inverse signal → combined wave; hero = `wave_inverse_interference`; facts: anti-phase cancellation (180° phase, destructive interference).
- *popcorn*: entities water droplet/steam, kernel shell, pressure, explosion; hero = `pressure_build_up_explosion`; facts: ~9 atm burst at ~180 °C, vaporization.
Also add `_ALIASES` entries. (Facts re-verified by Step 5.)

**Step 2 — Representation rules** (`engine/world/representations.py`):
Verify/add keyword rules: "popcorn/pop/steam/pressure/explosion" → EXPERIMENT (+SIMULATION); "noise-cancelling/cancellation/interference/silence" → SIMULATION (+SIGNAL_FLOW). Keep rule order: optics rule currently fires on "light" — check "noise-cancelling" doesn't collide with "sound/wave" rule (it should map to the wave rule, which is correct).

**Step 3 — Hero + story templates** (`engine/world/story_templates.py`):
Extend `_hero_visualization_for` + `concept` map with `wave_inverse_interference` and `pressure_build_up_explosion`; pick template: both → `experiment_driven` (already the default for "why/how" topics).

**Step 4 — Action grammar** (`engine/world/actions.py`):
Add `Action.INTERFERE = "interfere"` and `Action.CANCEL = "cancel"` → `ACTION_REGISTRY` → primitives `["InterferencePattern", "WaveSuperposition"]` (explanation_level 5, camera zoom_to). Also add missing spec actions `grow/shrink/rotate/diverge/pulse/propagate` if cheap, else defer (not needed for §46).

**Step 5 — Physics verifiers** (`engine/validation/physics_verify.py`):
Add `verify_wave_interference(f1, f2, phase_diff)` (destructive at 180°, nodes/antinodes, deterministic) and `verify_pressure_volume_burst(pressure_atm, temp_c)` sanity check. Wire into `world_compiler._physics_guard` for `interfere`/`cancel` (fail-closed like scatter/orbit).

**Step 6 — Primitives** (`engine/primitives/world_primitives.py`):
Add:
- `InterferencePattern` / `WaveSuperposition`: two travelling waves + combined wave (amplitude, phase, frequency params), deterministic.
- `PressureKernel` / `BurstExplosion`: shell + rising pressure gauge → burst ring (reuse `ImpactBurst` pattern).
Register in `ENTITY_MATERIALIZERS` (e.g. `wave→Wave`, new `interference`, `kernel`, `processor`, `microphone` types added to `world_model.EntityType` closed registry) and `ACTION_NATURAL_DURATION`. Add `_NATURAL_ENTER` entries in world_compiler.

**Step 7 — Beat planners** (`engine/visuals/world_director.py`):
- `_plan_wave` (SIGNAL_FLOW/SIMULATION for noise-cancelling): source wave → mic → processor → inverted wave → superposition/interference hero → silence payoff.
- `_plan_experiment` (EXPERIMENT for popcorn): kernel → heat → steam → pressure rises → burst (hero) → fluff payoff.
Register in `REP_PLANNERS`. Reuse `_plan_simulation` for sky (unchanged, already passing).

**Step 8 — Artifact contract** (`engine/cli/autonomous.py`):
Refactor the write block to emit the spec-named 15-artifact set: split `story_plan.json` → `story.json` + `hero.json` + `visual_plan.json` (or add aliases), write `topic.json`, `facts.json`, `beats.json` (from visualspec beats), `shots.json` (derive from beats+actions), rename `audio_timing.json`→`audio_timeline.json` (keep both for compat), `qareport.json`→`qa.json` (keep both), stub `repair_plan.json` + `learning.json` as empty contracts. Deterministic, cheap, no logic change.

**Step 9 — Tests** (new `tests/` files):
- `test_world_director.py`: for each of the 3 topics, `build_visualspec` returns beats with semantic actions, explanation avg ≥3.5, text-dominance <0.35, and **distinct primary representation** per topic (grammar-diversity assertion — the §46 criterion).
- `test_world_compiler.py`: `compile_world_to_file` succeeds for the 3 topics with `--no-render`; physics guard rejects bad interfere params.
- `test_physics_verify.py`: wave-interference + pressure verifier cases.
- `test_autonomous_artifacts.py`: `run_autonomous(..., render=False)` (or a dry-run) writes all 15 spec artifacts.
- `test_scoring.py`: score_beat levels for new action types.

**Step 10 — Run the §46 dev test** (no manual storyboard):
`python -m engine.cli.autonomous --topic "Why is the sky blue?" --out results/dev_test/sky_blue`
`python -m engine.cli.autonomous --topic "How do noise-cancelling headphones work?" --out results/dev_test/noise_cancelling`
`python -m engine.cli.autonomous --topic "Why does popcorn pop?" --out results/dev_test/popcorn`
Acceptance: all three pass `run_all_v2`; `v03_report.json` shows 3 different `representation_types` (SIMULATION+SIGNAL_FLOW / SIMULATION+SIGNAL_FLOW / EXPERIMENT…) with avg explanation ≥3.5 and text-dominance <0.35; visualspec JSON plans are readable without narration (§47).

**Out of scope for Phase A** (later phases per §45): CompositionPlanner (B), hero QC (C), scoring robustness (D), preview critique + local repair (E), learning memory (F), topic scouting (G), 5-topic regression suite (H), unseen-topic eval (I), daily mode (J).

---

## 4. TOP 10 RISKS / GAPS (biggest first)

1. **Unknown topics degrade to a trivial generic world.** `knowledge.py` has hand-authored worlds for exactly 5 topics; `_generic_world` is only cause→effect. Two of the three §46 topics (noise-cancelling, popcorn) have no data → the engine would produce near-identical generic videos, failing the "different visual grammars" test. This is the single biggest blocker.
2. **All of Phase A is uncommitted.** The world package, autonomous.py, world_compiler, world_primitives (≈70 KB), physics_verify, and the v2 schemas are untracked; gates/schema/test files are modified. Any reset/clean loses the entire v0.3 architecture.
3. **No learning loop at all (§31, §32, §39, §40).** No learning.json, no learned_rules.yaml, no persistent knowledge/ library, no caching, no pattern promotion — the system cannot improve run-over-run, which the directive calls the most important agentic addition.
4. **No repair capability (§30, §36).** Single full-scene render, boolean PASS/FAIL only. Any beat defect = full rerender; no PASS/REPAIR/REGENERATE/ABORT policy, no local per-beat rerender+recompose.
5. **No post-preview critique (§29).** Contact sheets are generated but never vision-reviewed; frame QA is pixel heuristics (motion/zone-density) with no score-0–100/strengths/problems/repair_actions tied to beats.
6. **Artifact contract doesn't match the spec (§5).** 6 of 15 artifacts missing (topic, facts, story, hero, beats, shots, visual_plan, repair_plan, learning) or misnamed (audio_timing.json, qareport.json) — breaks the stage-retry/compare/cache/resume design.
7. **Hero mechanism is not first-class with QC (§9–10).** Lacks `why_this_visual`/`objects`/`actions`; no hero_quality FAIL→revise gate before render.
8. **Action grammar gaps for the target domains (§17, §46).** `interfere`/`cancel` absent (needed for noise-cancelling); `enter/exit/move/grow/shrink/rotate/diverge/pulse/propagate` absent. Unknown-action fail-closed is good, but the vocabulary is incomplete.
9. **No composition/attention planning (§20–21).** Camera ops are minimal (`camera_focus`/`reset`); no focal-object/scale/hierarchy/negative-space planning → new topics risk cluttered or static compositions that heuristics can't catch.
10. **Test coverage is a single file.** Only `test_kaprekar_correctness.py` (12 headless tests) exercises the engine; no tests for world/world_director/world_compiler/autonomous/gates_v2/scoring/physics_verify. Phase A changes have no regression net, and the §46 grammar-diversity criterion has no automated assertion yet.
