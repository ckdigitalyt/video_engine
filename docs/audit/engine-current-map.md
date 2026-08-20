# Engine Current-State Map — v0.3 Upgrade Audit

- **Date:** 2026-08-20
- **Repo:** `/home/ubuntu/video_engine`, branch `jade`
- **HEAD:** `8b698b5` ("engine(v4): publishing metadata+thumbnail, voice-dominant composition, benchmark tool")
- **Audit type:** READ-ONLY. No files modified, no commits made.
- **Scope:** The new `engine/` package (the re-engineered deterministic pipeline). The legacy `src/` + `orchestrator.py` + `mission_run.py` pipeline is noted only where it overlaps (configs, docs, tests).

---

## 1. Pipeline stages — what exists vs missing

Actual production path is `engine/cli/run.py::run()` (engine/cli/run.py:211). Stage-by-stage:

| # | Stage | Status | Where |
|---|-------|--------|-------|
| 1 | **Research** | ❌ MISSING (stub) | `engine/research/__init__.py` is empty (0 lines). `visual_director.direct()` accepts `research_facts` but run.py never passes any (run.py:221 comment: "research is minimal for benchmark; expand later"). No web research, no fact extraction, no verification in the engine path. |
| 2 | **Story** | ⚠️ PARTIAL | `engine/story/__init__.py` empty. Story = hardcoded default narration string (run.py:100-107) or `--narration` CLI arg. No outline/story-template stage in engine. |
| 3 | **Script** | ⚠️ PARTIAL | No script stage. Narration text goes straight to TTS. `script.json` is *derived after the fact* from TTS word timing (run.py:144-168, written at run.py:343). |
| 4 | **Beats** | ✅ EXISTS (in VisualDirector) | BeatSheet produced by `visual_director.direct()` (visual_director.py:126) — deterministic Kaprekar template (:328), generic narrative template (:213), or LLM path (:151). `engine/beats/__init__.py` is empty (no separate beat module). |
| 5 | **Visuals** | ✅ EXISTS | BeatSheet + ShotList → VisualSpec (`run.py:46` `_compile_visualspec`), compiled to Manim by `compiler.py` (compiler.py:475 `emit_scene`). |
| 6 | **Render** | ✅ EXISTS | `run.py:70` `_render_scene` (manim CLI → mp4). One scene for the whole video; per-beat incremental rendering is *described* in comments (§31) but not implemented — composition concats a single clip (ffmpeg_compositor.py:52 `concat_clips` supports lists, unused). |
| 7 | **Audio** | ✅ EXISTS (core) / ⚠️ partial (music/SFX) | TTS synthesized FIRST as temporal source of truth (run.py:232-263); Kokoro (local) primary, Edge-TTS fallback (timeline.py:171-215). Music: `MusicTrack` + ducking exist (timeline.py:43, :312) but run.py passes `music=None` (run.py:304). SFX: cues exist in schema + `SFXTrack.validate()` (timeline.py:51) but no SFX synthesis/placement in run.py. |
| 8 | **Composition** | ✅ EXISTS | `ffmpeg_compositor.py` — concat, narration→48k stereo AAC, loudnorm −14 LUFS, SRT subtitle burn, black-pad tail fallback (never frozen frame) (compositor.py:100 `compose_final`). |
| 9 | **QA** | ✅ EXISTS | 10 checks in `engine/qa/gates.py::run_all` (:457) — see §5. |
| 10 | **Publish** | ⚠️ PARTIAL | `engine/publishing/metadata.py` (374 lines) + `thumbnail.py` (298 lines) exist with CLI (`python -m engine.publishing.thumbnail <run_dir>`), but are **NOT wired into run.py** (grep confirms no import in engine/cli/run.py). No YouTube upload, no publish gate in engine. |

**Missing/notable:** research, story, script (as first-class stages); publish not wired; incremental per-beat rendering not implemented; no SFX/music assets; `engine/subtitles/__init__.py` empty (SRT generation lives in ffmpeg_compositor.py:246 + caption logic in run.py:101).

---

## 2. Gap matrix vs JADE_TO_DO v0.3 spec items

Status legend: ✅ exists · ⚠️ partial · ❌ missing.

| # | Spec item | Status | Where / notes |
|---|-----------|--------|---------------|
| 1 | **World model (WorldState entities/relationships/forces)** | ❌ | `SceneState` (scene_state.py:87) tracks entities (id/type/value/zone/persistent) but has **no relationships, no forces, no simulation**. It is a stage-object registry, not a world model. Legacy `src/research/knowledge_graph.py` is a research-fact graph, not wired to engine. |
| 2 | **Relationship graph in VisualSpec** | ❌ | `visualspec_v1.schema.json` has `objects[]` + `transformations[]` only; no `relationships`/`edges` field. `ObjectSpec` has no relation/force fields. |
| 3 | **Action grammar (orbit/fall/collide semantic actions)** | ⚠️ | Schema Transformation enum includes `orbital`, `converge`, `count_down` (visualspec_v1.schema.json) and `_TRANSFORM_MAP` (compiler.py:69) maps `orbital`→ConvergenceParticles, `converge`→AttractorDiagram, `count_down`→ConvergenceParticles. **`fall`/`collide` absent**; also `move`/`swap`/`multiply` are in the schema but NOT in `_TRANSFORM_MAP` → raise CompileError (fail-closed, no silent no-op). |
| 4 | **Representation selection (DIRECT_DIAGRAM/SIMULATION/… classes)** | ❌ | No representation-selection taxonomy in engine. `visual_type` strings are narrative classes (`kinetic_title|question|claim|comparison|cycle|digit_sort|subtract|attractor|fixed_point|exception|conclusion|highlight|iterate`, compiler.py:83). Legacy `src/manim/planner.py:38-56` has a `VisualType` enum incl. `ORBIT_SIMULATION` but it is **not connected** to the engine compiler. |
| 5 | **Kinetic-text-as-fallback** | ⚠️ | `KineticTypography` primitive exists (manim_primitives.py:704) and `kinetic_title` maps to it (compiler.py:83-88), but it is used as a *primary narrative visual*, not as an explicit *fallback when a diagram cannot be rendered*. No decision logic "diagram unavailable → kinetic text". |
| 6 | **Visual explanation score (0–5 per beat)** | ❌ | No per-beat explanation score anywhere in engine. QA has no notion of "did this beat's visuals explain the narration" beyond the weak `gate_semantic` heuristic (gates.py:107). |
| 7 | **Mute-test QA** | ❌ | No mute-test gate (visuals must be comprehensible with audio off). Nothing in gates.py measures text-free comprehensibility. |
| 8 | **No-text review mode** | ❌ | No render/review mode that strips text (kinetic/claims/subtitles) for layout review. |
| 9 | **hero_mechanism output** | ❌ | No `hero_mechanism` field in any schema or director output. (Legacy `src/planner` concepts exist; nothing in engine.) |
| 10 | **Story template library** | ⚠️ | `configs/planner.yaml` defines 4 templates (documentary/problem_resolution/timeline/listicle) — but this config **drives the legacy `src/` planner only**. Engine `_direct_generic` uses a hardcoded `intent_cycle` (visual_director.py:229). No template library consumed by engine. |
| 11 | **Deterministic simulation helpers** | ⚠️ | `engine/validation/math_verify.py` is a deterministic verifier (Kaprekar step :46, sequence/orbit :69, attractor property :114, arithmetic :136, label count :156). Compiler computes verified trajectories (`_trajectories_for` compiler.py:161). **Topic-specific (4-digit Kaprekar)** — not a general simulation helper library. |
| 12 | **Factual constraints (formula/units/source) in world model** | ❌ | No formula/units/source constraints. `verify_arithmetic`/`verify_label_count` are generic-ish but only wired for Kaprekar digits. No source citations. |
| 13 | **Audio return (TTS + timing + music + SFX + mastering)** | ⚠️ | TTS ✅ (Kokoro→Edge, word timing, timeline.py:187), timing ✅ (narration-first; word runs → SRT, run.py:101), mastering ✅ (loudnorm −14 LUFS/TP −1.5, timeline.py:287; ebur128 measure :224), music ⚠️ (ducking implemented :312, but run.py passes `music=None`), SFX ❌ (schema + validate only, no synthesis/placement). |
| 14 | **Primitive promotion process** | ❌ | `PRIMITIVES` registry exists (manim_primitives.py:751) but there is no documented promotion process (no checklist/review step for promoting a new primitive into the trusted set). Compiler maps are hand-maintained (`_TRANSFORM_MAP` compiler.py:69). |
| 15 | **Visual regression tests** | ❌ | No rendered-frame regression suite. `tests/test_kaprekar_correctness.py` uses a headless `StubScene` (records `play()` calls; manim never draws). Legacy `src/qa/deterministic_qa.py` has `dhash()` but is not in engine and not a pytest suite. |
| 16 | **Autonomous topic→video test set** | ⚠️ | The deterministic generic director (`_direct_generic` visual_director.py:213) can turn *any* topic + narration into a video without an LLM (results dirs show collatz/mcgurk/space_black runs). But there is **no formal parametrized test set** asserting topic→video outcomes. |
| 17 | **Technical vs perceptual QA** | ✅ | `run_all` computes `technical_correctness` (gates schema/mathematical/technical/audio) and `perceptual_quality` (semantic/layout/motion/continuity) as two independent scores; composite `score = 0.6·tech + 0.4·perc` (gates.py:457+, around :540-560). |
| 18 | **ebur128** | ✅ | `measure_loudness` (timeline.py:224) parses the final `Summary:` section of `ebur128=peak=true` (I: integrated LUFS, Peak: true peak). `gate_audio` consumes it (gates.py:226). |
| 19 | **dHash** | ❌ | Not in engine. `src/qa/deterministic_qa.py:32` has `dhash()` for the legacy pipeline. Engine frame QA uses pixel-diff motion ratios instead (`frame_visual_qa` gates.py:347). |
| 20 | **ffprobe validation** | ✅ | `probe_streams`/`probe_duration_ffprobe` (gates.py:66, :81); `gate_technical` (:247) verifies h264, resolution, fps (±0.6), aac, 48 kHz, stereo, duration via real ffprobe JSON. |
| 21 | **Deterministic seeds** | ⚠️ | Engine pipeline is deterministic *by construction* (no RNG in compiler/primitives/director; no seed API needed). `configs/render.yaml` `effects.random_seed: 42` exists for the legacy pipeline only. No explicit seed plumbing in engine. |
| 22 | **Strict schemas** | ✅ | `schemas/*.json` (beatsheet_v1, shotlist_v1, visualspec_v1, audio_cue_v1, style_spec_v1, qa_report_v1) + `engine/validation/schema.py` validators (:68-91) + `check_cross_references` (:93). Gate 1 enforces. `additionalProperties: false` throughout. |
| 23 | **YAML config** | ⚠️ | `engine/config/loader.py` merges **only** `engine/config/*.yaml` (currently just `style.yaml`) + legacy `configs/style.yaml` fallback. **The root `configs/*.yaml` (pipeline, render, voices, providers, models, planner, research, visual_director) are NOT read by the engine** — they drive the legacy `src/` pipeline. Engine ignores render.yaml (4K) and voices.yaml (fish) entirely. |

**Other notable gaps:** Gate 5 "contrast" and a 10th "overall" gate appear in `qa_report_v1.schema.json` but are **not implemented** in gates.py (8 gate keys + 2 frame analyzers run). Camera specs are schema-validated and carried into the VisualSpec (run.py:46-69) but **never executed** by the compiler (no camera handling in `_compile_beat`).

---

## 3. VisualDirector data flow

**Entry:** `direct(topic, narration, research_facts=None, story_structure=None, use_llm=True, target_duration=None)` (visual_director.py:126).

**Inputs (LLM path):** JSON prompt built at `_direct_llm` (visual_director.py:151-185):
`{topic, exact_narration, research_facts, story_structure, style_spec (from get_style()), instruction}`; `_verify_math_in_prompt` (:106) appends deterministic Kaprekar orbit verification as authoritative. LLM call via `_llm_json` (:63) → DeepSeek (`DEEPSEEK_API_KEY`/`OPENAI_API_KEY`, `deepseek-chat`, temp 0.4, `response_format=json_object`, 2 retries). Output is schema-validated (`validate_beatsheet` + `validate_shotlist` + `check_cross_references`) or the call fails.

**Inputs (deterministic path):** `(topic, narration, target_duration)` only. Two directors:
- `_direct_deterministic` (:328) — Kaprekar: 11-beat plan (hook→question→sort→subtract→iterate→converge→reveal→exception→conclusion), fixed shot_template table, verified orbit for 3524, scales beat durations to `target_duration` (narration length) when provided.
- `_direct_generic` (:213) — any topic: sentence-splits narration, cycles intents, maps intent→visual via `_NARRATIVE_SHOT` (:199), injects `from/to` concept-keyword tokens so the motion gate sees real state changes.

**Outputs (both paths):** tuple `(beatsheet, shotlist)`:
- **BeatSheet** `{version, beats[], metadata}` — per beat: `beat_id, start, end, duration, narration, intent, importance, objects[ids], visual_change_required, audio_cues[{type,relative_time,volume}]`.
- **ShotList** `{version, shots[], metadata}` — per shot: `shot_id, beat_id, visual_type, renderer:"manim", duration, objects[{id,type,value?}], actions[{type,from?,to?,mode?}], camera{type,target?}, emphasis[], audio_cues[]`.

**Per beat it emits:** actions (transforms), object specs, camera, audio cues, narration. Compiled into VisualSpec by `run.py:46` `_compile_visualspec` (adds `visual_type`, `importance`, `camera`, `audio_cues`, `transformations=shot.actions`).

**Relationships/forces/simulation:** ❌ NOT supported. No relationship edges, no force fields, no simulation states. The action vocabulary is digit/number-centric (`sort/reverse/digit_permute/subtract/transform/morph/count_down/converge/orbital/reveal/highlight` mapped in compiler.py:69-81).

---

## 4. SceneState

**File:** `engine/visuals/scene_state.py` (untracked/new in working tree).

**Holds:**
- `objects: dict[oid → SemanticObject]` (scene_state.py:96-100). `SemanticObject` (:48) = `id, obj_type, value, zone (Zone enum :30: top/center/bottom/left/right/focus/support), persistent, temporary, mobject (opaque Manim handle), last_beat, entered_beat, exit_beat, update_ops[]`.
- `log: list[BeatLifecycleRecord]` — per-beat record (:78) of `entering[]/updating[]/exiting[]/persisting[]` snapshots.
- `_seq` counter; `_current` beat record being filled.

**Lifecycle API (file:line):**
- `begin_beat(beat_id)` (:160) — finalizes "now" bookkeeping into the named beat, appends a new record.
- `enter(oid, obj_type, value, zone, persistent, mobject)` (:121) — creates object, marks `entered_beat`.
- `update(oid, op, value, mobject)` (:134) — appends op to `update_ops`, updates value/mobject; returns None if object missing (compiler treats as bug→fail).
- `exit(oid)` (:148) — sets `exit_beat`.
- `record_enter/update/exit/persist` (:187-205) — write snapshots into current beat record.
- `active()/ids()` (:105, :109) — objects with `exit_beat is None`.
- `to_log()/write_log()` (:207, :219) — `VE_SCENE_STATE_LOG` env dumps per-beat lifecycle JSON.
- `object_counts()` (:225), `zone_conflicts()` (:233) — semantic overlap guard.

**How the compiler drives it (compiler.py `_compile_beat` :260):** per beat → `state.begin_beat` → **EXIT sweep** (objects whose role ended and not in future refs get `exit_object` + `state.exit`+`record_exit`) → **ENTER sweep** (persistent `number_main`/`attractor` created once) → transforms call state-aware primitives that `state.update` + `record_update` → `record_persist`. Primitives also record ENTER/EXIT internally (e.g. `apply_kaprekar_step` manim_primitives.py:305 enters/updates/removes ascending/equation/result within the beat). Anti-accumulation: each beat ends with only persisted objects on stage; tests assert next beat starts with `["number_main"]` only.

---

## 5. QA gates

**File:** `engine/qa/gates.py`. `run_all` at :457.

| Gate | Name | Type | Logic (file:line) |
|------|------|------|-------------------|
| 1 | schema | tech | validates beatsheet+shotlist+visualspec (:92) |
| 2 | semantic | perc | narration↔transform agreement (warnings only) (:107) |
| 3 | mathematical | tech | `verify_kaprekar_step` on every `subtract` (:123) |
| 4 | layout | perc | structural warnings + real frame zone-density conflicts (:140) |
| 6 | motion | perc | real frame metrics: dead air ≥6 s fails, 4–6 s = purposeful pause, avg motion <0.002 warn; structural fallback (:162) |
| 7 | continuity | perc | `number_main` persistence heuristic (:206) |
| 8 | audio | tech | LUFS within −14±4, true peak > −1 dB fails, clipping fails (:226) |
| 9 | technical | tech | ffprobe: h264, exact res, fps ±0.6, aac 48 kHz stereo, duration>0 (:247) |
| — | frame_visual_qa | perc evidence | 1 fps gray sampling → pixel motion ratios, static intervals, scene changes, brightness/contrast (:347) |
| — | frame_layout_qa | perc evidence | 4×3 zone grid ink density, crowded-zone adjacency = conflict (:405) |

**Thresholds (gates.py:32-36):** `TARGET_LUFS=-14.0`, `STATIC_THRESHOLD_S=4.0`, `DEAD_AIR_THRESHOLD_S=6.0`, `TECH_PASS_THRESHOLD=80`, `PERC_PASS_THRESHOLD=70`.

**Split (run_all :457):** `tech_gates = [schema, mathematical, technical, audio]`; `perc_gates = [semantic, layout, motion, continuity]`; each score = % passed; perceptual deductions −15 (dead air ≥6 s), −10 (layout conflicts); final `score = 0.6·tech + 0.4·perc`; `passed = tech≥80 and perc≥70`. Report validated against `qa_report_v1.schema.json`. Gate 5 (contrast) and "overall" exist in the schema but are not implemented.

---

## 6. Audio

**File:** `engine/audio/timeline.py`.

**Provider chain (TTS):**
- Registry `_PROVIDERS` (timeline.py:171): `kokoro` (KokoroProvider :121) then `edge_tts` (EdgeTTSProvider :84). `get_provider` (:177) prefers explicit name, else first available; `synthesize_narration` (:187) iterates registry, returns `(wav|mp3, words[])`, raises if none produce audio.
- **kokoro IS wired** — it is the engine's primary local provider: `KokoroProvider.synthesize` (:130) instantiates `kokoro_onnx.Kokoro("kokoro-v0_19.onnx", "voices.bin")` (both files present at repo root; 325 MB model + 5.7 MB voices.bin), 24 kHz mono WAV, sentence-level word timing (each word gets the sentence's start..end), default voice `af_sarah`. `kokoro-onnx==0.5.0` pinned in requirements.txt; `kokoro_onnx` importable in `venv`. Edge-TTS fallback (:94) produces mp3 + real WordBoundary timings.
- **fish is NOT wired in engine.** `configs/voices.yaml` declares `provider: fish` (s2.1-pro-free, voice_id 0327fdb5…, chatterbox fallback, kokoro bm_george/en-gb), but **nothing in `engine/` reads voices.yaml** (engine loader only globs `engine/config/*.yaml`). Fish/Chatterbox/ElevenLabs exist only in the legacy `src/`/`mission_run.py` path. No ElevenLabs provider in engine.

**Timeline sync:** narration is synthesized **before** planning (run.py:232-263, "temporal source of truth" §19/§20). Word timing → `narration_dur` → `target_duration` → VisualDirector sizes beats so visuals match voice (no frozen tail). Captions: word runs grouped with shared-timestamp subdividing (`_caption_entries_sequential` run.py:101) → SRT (`generate_srt` compositor.py:246) → burned in compose. `script.json` + `audio_timing.json` derived post-hoc (run.py:343-350).

**Music/SFX/mastering state:**
- Music: `MusicTrack` dataclass (:43) + `duck_music_under_narration` sidechaincompress (:312) + `normalize_to_target` loudnorm (:287) exist — but `run.py:304` calls `compose_final(..., music=None)`. No music asset is ever selected/loaded in the engine path.
- SFX: `SFXTrack` (:51) + `validate()` + cues in schemas; no synthesis, no placement, no mixing in run.py.
- Mastering: ✅ `compose_final` (compositor.py:100) always forces 48 kHz stereo AAC, loudnorm I=−14/TP=−1.5/LRA=11, apad + tpad black tail (PAD_MODE="add", compositor.py:41) if narration outlasts video.

---

## 7. CLI entrypoints

**Engine:** `python -m engine.cli.run` (run.py:430 `main`).
- Args: `--topic` (default "Kaprekar's constant"), `--out` (default `results/kaprekar_bench_engine`), `--narration` (exact text; default = built-in Kaprekar script run.py:100), `--use-llm` (DeepSeek Visual Director; default deterministic), `--dev` (1280×720 vs default **1920×1080** — note: engine default is 1080p, NOT the 4K in configs/render.yaml which is legacy-only).
- Flow: TTS first → `direct()` → cross-ref check → `_compile_visualspec` → `compile_to_file` → `_render_scene` (manim, quality flag by height: −ql/−qm/−qh/−qk) → `compose_final` → `run_all` QA → artifacts (beatsheet.json, shotlist.json, visualspec.json, qareport.json, script.json, audio_timing.json, scene_state_log.json, render_diagnostics.json, contact_sheet.jpg). Prints PASS/FAIL with errors.
- Configs that drive it: **only `engine/config/style.yaml`** (via `get_style()`). Manim binary: `venv/bin/manim` fallback to PATH.

**Publishing (not wired into run):** `python -m engine.publishing.thumbnail <run_dir> [topic]` (thumbnail.py:280) — deterministic metadata.json + 1280×720 thumbnail PNG/SVG from run artifacts.

**Legacy (out of scope for engine):** `orchestrator.py` (LangGraph planner→execution→render→critic, :380-383), `mission_run.py`/`mission_stills.py` runners, `renderer.py`/`audio_engine.py`.

---

## 8. Tests

`venv/bin/python -m pytest --collect-only -q` → **803 tests collected** (3.74 s), `testpaths=tests`, `pythonpath=.` (pytest.ini). Per-file counts (top):

| File | Tests | Target |
|------|------:|--------|
| test_v2_types.py | 47 | legacy src/models |
| test_asset_router.py | 44 | legacy assets |
| test_visual_quality_v1.py | 38 | legacy QA |
| test_subtitles.py | 37 | legacy subtitles |
| test_models.py / test_evaluator.py / test_memory_manager.py | 36/35/34 | legacy |
| test_visual_director.py | 33 | legacy src/director |
| test_kaprekar_correctness.py | 12 | **engine** (untracked, new) |
| test_v13_qa_gates.py | 13 | legacy gates |
| … (35 files total, 803 tests) | | |

**Engine coverage is thin:** only `tests/test_kaprekar_correctness.py` (12 tests) exercises the new `engine/` package — digit-reorder object identity, permutation mapping, morph identity, compiler CompileError on untargeted/unmapped/duration-overflow/math failures, emitted-scene state wiring, `compile_to_file`, SceneState ENTER/UPDATE/EXIT recording, kaprekar-step clean lifecycle, math guard. **No test covers**: visual_director deterministic directors, gates.run_all, timeline providers, ffmpeg_compositor, run.py pipeline, schema validators, publishing.

**How rendering is tested:** headless only — a `StubScene` records `play()`/`wait()` calls (test_kaprekar_correctness.py:27-36); manim never draws a frame. Legacy tests mock MoviePy/ffmpeg/Kokoro/Gemini (conftest.py fixtures). No test invokes real Manim rendering or frame-pixel assertions in the engine context.

---

## 9. Uncommitted changes

`git status` on `8b698b5`: 8 modified files, 2 new engine files, 1 new test, plus large deletions of tracked run artifacts (logs/*, results/*, .coverage) and assorted untracked junk (concat_list.txt, .env.bak, video_engine_consolidated.py, rebuild_smoke.py, media/*, tmp/).

**`git diff --stat` (engine-relevant):**

```
engine/audio/timeline.py                |  69 +-   (ebur128 summary parsing fix, normalize/duck helpers)
engine/cli/run.py                       | 303 +-   (full pipeline rewrite: TTS-first, QA wiring, artifacts)
engine/composition/ffmpeg_compositor.py | 135 +-   (black-pad fallback, 48k stereo enforce, SRT)
engine/primitives/manim_primitives.py   | 871 +-   (state-aware primitives + SceneState recording)
engine/qa/gates.py                      | 429 +-   (10-gate engine, tech/perc split, frame QA)
engine/renderers/manim/compiler.py      | 563 +-   (SceneState lifecycle, math guard, trajectories)
engine/validation/math_verify.py        |   2 +-   (one-line condition flip bug fix)
engine/visuals/visual_director.py       |  41 +-   (target_duration, generic director)
```
Plus **untracked new**: `engine/primitives/layout.py`, `engine/visuals/scene_state.py`, `tests/test_kaprekar_correctness.py`; and deletion of tracked `logs/*`, `results/*`, `.coverage` (housekeeping of old run artifacts).

**Verdict — YES, this is the correctness sprint, must be preserved:**
1. **SceneState** (new `scene_state.py`) — the anti-accumulation ENTER/UPDATE/EXIT lifecycle, wired through compiler + primitives. This is the central correctness fix.
2. **Math verification** — compiler `_math_guard` (:117) routes every transformation through `math_verify`; `_trajectories_for` (:161) verifies orbits deterministically; math_verify.py's one-line diff flips `if from_value is not None and _digits_ok(...)` → `and not _digits_ok(...)` (bug fix: previously an invalid `from_value` silently skipped the verification branch).
3. **Gates rewrite** — correct ebur128 summary parsing (the earlier "first I: line" bug), technical/perceptual score split, real ffprobe validation, frame-based motion/layout QA.
4. **Voice-dominant composition** — TTS-first timing, black-pad tail instead of frozen frame, LUFS mastering, sequential captions.
5. **Deterministic generalization** — `_direct_generic` + `target_duration` scaling let any topic run without an LLM.

The diffs are additive/rewrite (1,981 insertions vs 432 deletions across engine; ~3.5k lines of correctness work in total incl. untracked files). They should be **committed as the correctness-sprint baseline before any v0.3 work**, and the working-tree deletions of `logs/`/`results/` should be reviewed for accidental loss (they are old run outputs, but `.coverage` + result JSONs were tracked; confirm intent before `git add -A`).

---

## Appendix — key file:line index

| Concern | Location |
|---|---|
| Pipeline runner | engine/cli/run.py:211 (`run`), :430 (`main`) |
| VisualSpec assembly | engine/cli/run.py:46 |
| Manim render | engine/cli/run.py:70 |
| Caption timing | engine/cli/run.py:101 |
| Visual Director entry | engine/visuals/visual_director.py:126 |
| Deterministic Kaprekar director | engine/visuals/visual_director.py:328 |
| Generic narrative director | engine/visuals/visual_director.py:213 |
| LLM director | engine/visuals/visual_director.py:151 |
| Compiler / emit_scene | engine/renderers/manim/compiler.py:475, _compile_beat :260, _math_guard :117 |
| Transform map | engine/renderers/manim/compiler.py:69 |
| SceneState | engine/visuals/scene_state.py:87 (enter :121, update :134, exit :148, begin_beat :160) |
| Primitives registry | engine/primitives/manim_primitives.py:751 |
| Layout zones | engine/primitives/layout.py:17 |
| QA run_all | engine/qa/gates.py:457 |
| Frame visual QA | engine/qa/gates.py:347 |
| TTS providers | engine/audio/timeline.py:171 (registry), :121 (Kokoro), :84 (Edge) |
| Loudness (ebur128) | engine/audio/timeline.py:224 |
| Ducking | engine/audio/timeline.py:312 |
| Composition | engine/composition/ffmpeg_compositor.py:100 |
| Schema validators | engine/validation/schema.py:68-91 |
| Math verifier | engine/validation/math_verify.py:46-156 |
| Config loader | engine/config/loader.py:20 |
| StyleSpec (only engine YAML) | engine/config/style.yaml |
| Publishing (unwired) | engine/publishing/metadata.py, thumbnail.py |
