# Jade Operating Spec — v9 Implementation Map

Implemented 2026-08-04 in `video_engine` (branch `jade`), commit v9.
Every spec section → concrete module/gate. Deterministic checks need no LLM.

## 1) Narration and voice synthesis — `src/qa/voice_lock.py` + Chatterbox
- **Primary narrator: Chatterbox** (Resemble AI, MIT) per the expert TTS
  spec (§1.3): expressive flow-matching TTS with emotion exaggeration +
  native paralinguistic tags ([laugh], [chuckle], [sigh]...).
  - `scripts/chatterbox_worker.py` — persistent worker in an ISOLATED venv
    (venv-cb) because chatterbox-tts pins numpy 1.26.4/torch 2.6.0 while
    the pipeline venv runs numpy 2.5.1; model stays loaded between scenes
    (KEEP_MODEL_LOADED equivalent).  Output is 24 kHz WAV with PerTh
    watermark (expert §1.3).
  - `src/providers/tts_provider.py::ChatterboxProvider` — JSON-lines
    protocol to the worker (robust to stray log lines, matches req id),
    emotion → (exaggeration, cfg_weight) table (`CHATTERBOX_EMOTION_PARAMS`:
    hook 0.8/0.3 lively, somber 0.4/0.7 steady, per §1.3).
  - Whole-scene semantic chunks (NOT sentence-by-sentence — the root
    cause of the old prosody/fallback bug, expert §1.2).
  - Scriptwriter emits `para_tags` (0-2 organic tags per scene); injected
    at natural sentence boundaries; edge/kokoro STRIP tags so they never
    read "[chuckle]" literally.
- **Voice lock** (`src/qa/voice_lock.py`): `lock_voice()` selects+persists
  ONE narrator (chatterbox/resemble in the stills runner) at project start
  → `cache/voice_lock.json`; per-scene voice recording with explicit
  overrides; `check_voice_switching()` + `check_loudness_consistency()`
  QA; `reset_episode()`.
- Fallback chain per expert §1: Chatterbox (primary) → Edge (fallback) →
  Kokoro (emergency, CPU-safe).  A fallback is recorded on the lock as an
  explicit override, never silent.

### Chatterbox on this box (measured 2026-08-04)
- CPU-only (4 cores, no GPU): RTF ≈ 12-14x real-time (8.6s audio in ~110s).
  A full 60s video adds ~12-15 min of narration time on top of the ~15 min
  render.  Model load ~17s, kept loaded across scenes.
- Needs venv-cb (`python -m venv venv-cb && venv-cb/bin/pip install chatterbox-tts`)
  plus `setuptools<81` for pkg_resources (setuptools 83 dropped it).
- The chatterbox-tts package exposes `ChatterboxTTS.from_pretrained("cpu")`
  (import name `chatterbox`, not `chatterbox_tts`).

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

---

## v10 Addendum — Expert Refinement Pass (2026-08-04)

Implemented the 12-point expert instruction set ("better documentary
comprehension").  All changes are topic-free and reusable (rec 12).

| Rec | Expert requirement | Implementation |
|-----|-------------------|----------------|
| 1 | Pacing over speed; space after key facts | `src/cinematic/pacing_engine.py`: per-role WPM bands (hook 158, explanation 138, conclusion 142), comprehension-risk scoring; SCRIPT_PROMPT pacing guidance; pre-render **pacing gate** blocks rushed scenes |
| 2 | Adaptive voice dynamics, not uniform | `_voice_params()` blends emotion + role into Chatterbox exaggeration/cfg (hook energetic ≤0.9, explanation clear 0.3/0.8); per-role pause density |
| 3 | Language-aware text normalization | `tts_normalize.py` v10: `apply_language_layer()` (units, symbols, en-dash ranges, ±, &), `apply_pacing_pauses()` (clause-level breathing), fixed latent percent regex bug (`%\b` never matched) |
| 4 | Publication-safe audio mix | Publish-gate **loudness_master** check: integrated -16..-11 LUFS, TP ≤ -1.0 dBTP, no clipping, LRA ≤ 20 (verified on Moon: -14.5 LUFS / -1.1 TP / LRA 1.7) |
| 5 | Tighten hook, only opening window | Stills planner: scene 0 holds 3.0–3.5s (vs 4.5–5.5s later scenes) — brisk cuts, then comprehensible pace |
| 6 | Semantic alignment, beat-level intent | Pre-render **semantic_alignment** gate: deterministic token overlap between each shot's query/title and its scene narration (pre-verified/pinned exempt) |
| 7 | Subject accuracy strict | Reuses §3/§7 asset gates (EntitySpec multi-signal + vision); semantic gate rejects decorative-but-wrong shots |
| 8 | Visual novelty within long beats | Retained: CameraDirector diversity, perceptual dedup, coverage-guard variant shots; hook window adds turnover |
| 9 | Preserve motion-graphics gains | Unchanged: Manim kinetic validation + registration gates intact |
| 10 | Failure-aware, no silent fallback | `run_report["pacing"]` + degradations entries for rushed/high-risk scenes; pre-render block failures recorded in errors[] |
| 11 | Postmortem learns from pacing failures | `audit_pacing()` metrics (wpm, risk, role bands) into run_report + postmortem metrics (avg_wpm, rushed_scene_count) |
| 12 | Extensible | Everything driven by role/intent keywords + config; zero per-topic branches |

Verified on the Moon run artifacts: semantic_alignment PASS, loudness PASS,
pacing gate correctly blocked a genuinely rushed scene (175 wpm > 172).
