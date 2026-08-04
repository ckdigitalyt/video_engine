# Jade Operating Spec — v9 Implementation Map

Implemented 2026-08-04 in `video_engine` (branch `jade`), commit v9.
Every spec section → concrete module/gate. Deterministic checks need no LLM.

## 1) Narration and voice synthesis — `src/qa/voice_lock.py`
- `lock_voice()` selects+persists ONE narrator (provider, voice_id, speaker_id,
  rate/pitch) at project start → `cache/voice_lock.json`.
- `stage_narration_dynamic()` (mission_run.py) records the actual per-scene
  voice; a fallback to a different engine is logged as an EXPLICIT override,
  never silent (§1 "never swap without explicit override").
- QA: `check_voice_switching()` (per-scene provider/voice vs lock),
  `check_loudness_consistency()` (RMS spread across scenes — catches timbre
  drift). Wired into both the pre-render and publish gates.
- `reset_episode()` clears per-scene records between episodes.

## 2) Visual consistency — `src/director/style_bible.py`
- `create_style_bible()` locks ONE style per episode (palette + modifier +
  reference frame + subject sheet) → `cache/style_bible.json`.
- AI still prompts already collapse to the single fixed Jade art direction
  (mission_stills `_style_prompt_for` — no per-emotion rotation).
- QA: `check_style_drift()` (every placed AI still must carry the locked
  style token), `check_palette()` (dominant-color distance from palette).
- `reset_episode()` clears per-episode placed records.

## 3) Manim integration — `src/manim/validate.py`
- `validate_manim_script()`: AST parse (fail closed on syntax), bans
  exec/eval/os/subprocess/file writes/unbounded loops, requires a Scene
  subclass with `construct()`, enforces KINETIC content (≥1 self.play(),
  total wait ≤ 6s, single wait ≤ 2.5s warning).
- `validate_manim_facts()`: label/value check against the reviewed script.
- mission_stills injects a Manim clip only if valid + kinetic; jade_gates
  re-validates every registered clip and checks registration in the timeline.

## 4) Audio engineering — `mission_run.py::stage_music_mix`
- Already present (sidechain ducking, loudnorm −14 LUFS, limiter, silent-bed
  detection/synth fallback, event-driven SFX).
- NEW: music bed fades in (1s) and out (last 1.5s) — no abrupt starts/stops.
- Publish gate adds `dead_air_audio` (silence runs ≥ 1.2s) + clipping check.

## 5) Retention and pacing — `src/qa/jade_gates.py`
- Pre-render `shot_hold` check (longest shot ≤ 10s).
- Publish `hook_strength` (≥ 2 distinct visuals in the first 15s),
  `opening_black_frames` (first 0.5s luma above black threshold).
- Coverage guard (≥ 2 shots/scene) + Ken Burns camera motion were already in
  mission_stills (v7/v8).

## 6) Script and fact checking
- Already present: `stage_fact_verification` + 4-persona `script_review.py`.
- Manim label facts now validated against script values (§3 gate).

## 7) Asset selection and disambiguation
- Already present: `asset_verifier.py` OFF_TOPIC_SIGNALS (fatal guard),
  Wikimedia fetch-time title filter, bare-query disambiguation
  (`_disambiguate_query`), EntitySpec multi-signal + vision fallback.
- Pre-render `off_topic_assets` check: any unverified asset in the timeline
  blocks render.

## 8) Context and memory management
- Architecture keeps planner context lean (compact JSON between modules);
  heavy outputs live on disk (timeline.json, run_report, qa/publish gates).

## 9) Deterministic QA gates BEFORE render — `src/qa/jade_gates.py::PreRenderGate`
Runs on the timeline plan + locks, blocks render on any failure:
- voice_lock / voice_switching / voice_loudness_consistency
- style_bible / style_drift
- off_topic_assets (unverified in timeline)
- manim_registration / manim_kinetic / manim_facts
- shot_hold (≤ 10s) / dead_air (narration gaps ≤ 2s) / generation_complete

## 10) Publish readiness gate — `src/qa/jade_gates.py::PublishGate`
Runs on the final mixed video; `publish_ready` = no blocking failures:
- full DeterministicQA (encoding, resolution, repeated assets, frozen shots,
  excessive static, silence, clipping) + hook_strength + voice_consistency +
  style_locked + manim_registered + dead_air_audio + opening_black_frames.
- Writes `publish_gate.json` in the run dir; recorded in `run_report.json`.

## 11) Implementation priority — all 8 items done in order
1. voice lock across the video ✔  2. one visual style per episode ✔
3. ducking + loudness ✔ (fades added)  4. shorter holds + motion ✔
5. semantic asset disambiguation ✔  6. Manim as kinetic explainer ✔
7. deterministic QA gates ✔  8. lean context ✔

## Wiring
- `mission_stills.py` (primary runner): locks at start, passes voice_lock to
  narration, style_bible to stills, runs PreRenderGate before render,
  PublishGate on the final video.
- `mission_run.py`: same locks + gates in main(); stage_narration records
  voice per scene.
- Smoke test: `scripts/smoke_v9_gates.py` (validates all gates + negative
  cases against real artifacts: black_holes/mars videos pass every real
  check; injected bad style token is correctly caught).
