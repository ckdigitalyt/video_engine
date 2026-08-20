# MathMotion Lab v0.2 — Isolation Audit Report (for v0.3 refactor)

- **Audit date:** 2026-08-20
- **Repo:** `/home/ubuntu/mathmotion-lab` (branch `master`, commit `60afb52` "v0.4: algorithmic viral best-practice pipeline", some uncommitted changes)
- **Mode:** READ-ONLY (no files modified, no writes except this report)
- **Scope:** full read of `src/mathmotion/*.py`, `scenes/*.py`, `tests/*.py`, README, pyproject; skim of v0.2 run logs; ffprobe verification of the final MP4.

---

## 0. Verified render facts

`ffprobe -v error -show_entries format=duration,size:stream=codec_type,width,height,r_frame_rate,codec_name -of json output/video/SatelliteOrbit_final.mp4`:

```json
streams: [ { codec_name: "h264", codec_type: "video", width: 1920, height: 1080, r_frame_rate: "30/1" } ]
format:  { duration: "64.233333", size: "2812162" }
```

- Final video: **1920×1080 @ 30/1 fps, H.264, 64.23 s, ≈2.8 MB, no audio stream** (silent by design, see report §logs).
- `output/video/` also holds `SatelliteOrbit_preview.mp4` (854×480 @ 30) plus the legacy `DerivativeTangentScene_{final,preview}.mp4` from the pilot.

**`output/frames_v04/`** (v0.2 QA artifacts, dated 2026-08-18 21:21–21:22): 3 contact sheets (`contact_1.png` Beats 1–3, `contact_2.png` Beats 4–5, `contact_3.png` Beats 6–8) and 24 sampled full frames `f_01.png … f_24.png`. Sibling dirs: `output/frames/` (with `cs/` and `qa/` subdirs of `qa_*.png` at 1 s granularity) and `output/frames_v03/` (`f_01…f_10+`) from the earlier cycle.

**v0.2 pipeline order** (from logs/reports timestamps): final render (`final_render_v02.log`, 21:19:10, mostly cached) → preview render (`preview_render_v02.log`, 21:19:40) → frame extraction + contact sheets (`frames_v04/`, 21:21–21:22) → storyboard doc (`satellite_storyboard.md`, 21:23) → vision QA + settled-state verification (`satellite_qa.md`, 21:31) → final report (`satellite_final_report.md`, 21:31). Render logs confirm Manim Community v0.20.1, per-animation partial-movie caching, rc=0. QA verdict PASS; **16 tests passed**.

---

## 1. Per-file inventory

### 1.1 `src/mathmotion/satellite_scene.py` — the whole animation (topic layer)
The single biggest file; all 8 beats, physics helpers, and per-scene constants.
- Constants: `R_EARTH=2.0` :35, `R_ORBIT=3.4` :36, `SATELLITE_COLOR` :37, `VEL_COLOR` :38, `GRAV_COLOR` :39, `ACCENT` :40, `VEC_LEN=1.7` :43, `BALL_RADIUS=0.15` :46, `R_LAND=R_EARTH+BALL_RADIUS` :47, `R_LAUNCH=2.8` :49, `G_ACCEL=5.0` :51.
- `kepler_period(r, base_r=2.8, base_T=2.0)` :56 — T ∝ r^1.5 lap-time for Beat 6.
- `ballistic_arc(r_launch, theta_deg, g, r_land)` :61 — returns `(ParametricFunction path, t_f, vx)`; inner `f(t,…)` :77 is true constant-gravity projectile motion (x=−vx·t, y=r−½gt²).
- `class SatelliteOrbitScene(Scene)` :84; `__init__` :87 calls `configure_scene(self)` (generic background from viral_config); `construct` :94 sequences the 8 beats.
- Helpers: `make_earth()` :105 (filled disc + limb glow), `side_label(text,color)` :112 (26 pt label factory), `impact_on_surface(center, angle)` :115 (point on radius R_EARTH).
- Beats: `beat_1_hook` :121, `beat_2_drop` :137, `beat_3_throw_faster` :174, `beat_4_crucial_speed` :265 (HERO), `beat_5_velocity` :365, `beat_6_equation` :404, `beat_7_astronaut` :451, `beat_8_final` :493.

### 1.2 `src/mathmotion/satellite_storyboard.py` — storyboard data (topic layer)
- `class SatelliteStoryboard` :7; `__init__` :13; `setup_storyboard` :18 builds 8 dict beats (number/title/duration/description/visuals/requirements); accessors `get_beat` :206, `get_all_beats` :213, `get_total_duration` :217; `print_storyboard` :221; `get_scene_transitions` :242 (cumulative timeline).
- `NASA_SOURCES` dict :260, `SCIENTIFIC_NOTES` string :268 (facts + "gravity never switched off" rules).
- Note: this data class is **not wired into the render pipeline** — it documents the beats; the scene hardcodes them. Duplication risk.

### 1.3 `src/mathmotion/satellite_story.py` — narration script (topic layer)
- `build_satellite_story() -> Storybeat` :18 — 7 `Beat`s (Hook/Drop/Throw faster/Crucial speed/Higher is slower/Astronaut/Close) with kind tags matching the viral scaffold; narration only, structure enforced by script_lab. `if __name__ == "__main__"` prints runtime + validation.

### 1.4 `src/mathmotion/script_lab.py` — **generic** viral-script structure engine
- `@dataclass Beat` :28 (title/narration/duration/kind).
- `@dataclass Storybeat` :39; `add` :45, `total_runtime` :49, `to_segments` :53 → `ScriptSegment` list.
- `validate() -> list[str]` :60 — algorithmic format gates: must open with `hook` (:68–76), must have `centerpiece` + `twist` (:78–82), must end with `close` CTA (:84–89), pacing vs `viral_config.suggested_script_words` with ±25% tolerance (:91–100), ≤100 s Short-repurpose guard (:102–107), explicit engagement CTA keywords in close (:109–123, G5).
- `is_valid` :125; `build_story(title, *, hook, centerpiece, twist, close, escalations, human, hook_dur, beat_dur)` :131 — fixed-order builder, topic-agnostic.

### 1.5 `src/mathmotion/viral_config.py` — **generic** single source of style truth
- `DEFAULT_BACKGROUND_COLOR="#0d1117"` :40, `PRIMARY_TEXT_COLOR` :42, `ACCENT_TEXT_COLOR` :43.
- `SATELLITE_COLORS` dict :48–54 — **topic leakage inside a generic module** (flagged §7).
- `background_color()` :56 (env override `MATHMOTION_BG`), `VOICE_PRIMARY` :70, `VOICE_FALLBACK` :72, `VOICE_OSS_FALLBACK` :74, `elevenlabs_api_key()` :78, `VO_SPEED_WPM=150` :91, `suggested_script_words(runtime)` :94, `retention_checklist()` :105, `configure_scene(scene, background=None)` :121 (applies camera background; called from scene `__init__`).
- Review-driven constants: `MAX_STATIC_WINDOW_SECONDS=3.0` :140 (G2), `BACKGROUND_DITHER_STRENGTH=0.015` :142 (G3), `CAPTIONS_REQUIRED=True` :144 (G4), `CTA_KEYWORDS` :146 (G5), `background_texture_recipe()` :152, `tts_ready()` :159.

### 1.6 `src/mathmotion/viral_gates.py` — **generic** publish gates (G1–G5)
- `_3D_CAPABLE_RENDERERS` :30, `_3D_TOPIC_KEYWORDS` :45; `@dataclass RenderPlan` :79 (topic/renderer/concept_3d/notes); `_auto_detect_3d(topic)` :88; `check_plan(plan)` :93 (G1, plan-time).
- G3: `DITHER_STRENGTH` :119, `apply_background_texture(bg)` :122, `add_background_noise(scene, strength)` :131 (Manim noise overlay tile).
- G2: `max_static_window_seconds(video_path, sample_every=0.5, threshold=2.0)` :153 — ffmpeg `freezedetect` wrapper.
- G4: `caption_track_present(video_path)` :190 — sidecar `.srt` or subtitle stream probe.
- G5: `CTA_KEYWORDS` :210, `script_has_explicit_cta(text)` :216.
- `check_video(video_path, *, script_text, plan, require_captions, max_static)` :225 — runs G1/G2/G4/G5 on a finished MP4; `check_script(text)` :270; `run_all(video, script, topic, renderer, ...)` :283 → verdict dict `PASS|REVISION_REQUIRED` with `plan/script/video` issue buckets.

### 1.7 `src/mathmotion/missing_voice.py` — **generic** ElevenLabs narrator
- `@dataclass ScriptSegment` :37 (text/duration/beat); `@dataclass Narrator` :46; `_ensure_voice_lock` :53 (one-voice-per-video enforcement); `available()` :63; `synthesize(text, out)` :66; `_synthesize_rest` :81 (direct REST, no SDK; voice id env-overridable); `build_narrator()` :130 (reads voice from viral_config only); `synthesize_script(segments, out_dir)` :134 → per-segment `beat-NN.mp3` list.

### 1.8 `src/mathmotion/satellite_voice.py` — **mostly generic** VO orchestrator
- `OUT_DIR` :26; `main(argv)` :29 — builds story (`build_satellite_story` import :10 is the only topic hook), validates, `--dry-run` guard, calls `synthesize_script`, writes `timing.json` manifest (:44–50) mapping `file/beat/duration_s/text`. The pattern (story → validate → TTS → manifest) is fully reusable.

### 1.9 `src/mathmotion/captions.py` — **generic** burned-in captions (G4)
- `words_to_srt(words)` :29, `_ts(sec)` :37 (SRT timestamp), `script_to_srt(text, *, start, words_per_card=3, card_gap=0.18)` :45 (naive word-group cards @ ~2.8 wps), `timing_json_to_srt(timing_path)` :67 (beat-sized cards from timing.json), `burn_captions(video_in, video_out, srt_path)` :84 (ffmpeg subtitles filter, white/bold/outline/Shadow, bottom-center `Alignment=2 MarginV=64`), `main` :108.

### 1.10 `src/mathmotion/satellite_render.py` — satellite render entry
- Constants :14–20 (PROJECT_ROOT/OUTPUT/VIDEO/LOGS/SCENES/SCENE_NAME); `render(quality)` :23 — explicit `-r W,H --fps 30` (no quality presets, :40–58) so fps can't silently change; `--media_dir` isolation :59; mtime-newest candidate selection :67–72 (fixes stale 60 fps shadowing); copies to `output/video/SatelliteOrbit_{preview,final}.mp4` :73–75; `main` :86.

### 1.11 `src/mathmotion/satellite_qa.py` — frame-based QA (beat-aware)
- `BEATS` windows :31–42 (8 beats, contiguous, derived from scene run_times — **duplicated timing**, see §7); `extract_frames(video, outdir, every=1.0)` :43 (ffprobe duration + ffmpeg frame dumps, `qa_%.2fs.png`); `frame_metrics(img)` :62 (grayscale → content mask > 0.08 brightness; coverage, bbox, center_offset, brightness, content_area); `assess(video, outdir)` :85 (per-beat aggregation, near-empty < 1% and clutter > 90% area flags); `main` :122 (`--gates` hooks viral_gates.run_all with `--topic/--renderer/--script`).

### 1.12 Legacy pilot files (superseded, kept for reference per README)
- `src/mathmotion/storyboard.py` — `SceneBeat` :8, `Scene` :16, `DerivativeStoryboard` :23 (`_build_storyboard` :29, `get_summary` :207, `get_scene_code` :225).
- `src/mathmotion/render.py` — `get_scene_name` :23, `render` :29 (uses `-ql/-qh` presets → the 60 fps bug the satellite renderer fixed), `main` :89.
- `src/mathmotion/qa.py` — `QAReport` :14 (to_markdown :31), `_run_ffprobe` :58, `analyze_video` :76 (duration <40 s fail, <1080p warning), `_run_frame_check` :139 (ffmpeg `blackdetect`, >15 % black → issue). **The blackdetect + ffprobe techniques are reusable.**
- `src/mathmotion/pilot.py` — orchestrator `check_manim` :23, `run_qa` :32, `main` :38 (storyboard→render preview→render final→QA→report).
- `scenes/derivative_tangent.py` — `DerivativeTangentScene` :39; helpers `build_axes` :42, `build_graph` :54, `point_at` :63, `label_at` :68, `secant_from_h` :72; scenes `scene_hook` :78 … `scene_final` :276; `construct` :295; hardcoded palette :20–27 and `f`/`fprime`/`A_VAL` :30–36. Notable generic patterns: ValueTracker-driven limiting process (`scene_limit` :185) and updater-attached secant rotation.

### 1.13 `scenes/satellite_orbit.py` — Manim entry wrapper
- sys.path shim :10–14; `class SatelliteOrbitScene(_Base)` :20 — thin subclass so Manim scene discovery works while logic lives in the package. **Good pattern to keep.**

### 1.14 Tests
- `tests/test_satellite.py` — physics sanity: `test_kepler_third_law_ratio` :31, `test_impact_on_surface_lands_on_radius` :41, `test_ballistic_arc_lands_on_surface` :51, `test_ballistic_faster_lands_farther` :63, `test_ballistic_arc_stays_clear_of_earth` :72, `test_vector_length_constant` :81, `test_qa_timeline_covers_runtime` :90.
- `tests/test_viral_gates.py` — G1 accept/reject :10–24, G5 CTA :26, G4 sidecar :31, `run_all` verdict :41.
- `tests/test_pilot.py` — storyboard structure :13, scene import :25, QAReport shape :32.

### 1.15 Root files
- `README.md` — documents the scene, the 8 beats, the v0.4 algorithmic pipeline (background/voice/script), project layout, usage, legacy-pilot note, deliverables.
- `pyproject.toml` — minimal: `manim==0.20.1` only; setuptools `src` layout. (QA deps numpy/PIL are not declared — installed ad hoc in venv.)

---

## 2. Extended Section-3 component table (reusable concepts)

| Component | Reusable? | Proposed generic abstraction | Where (file:line) |
|---|---|---|---|
| Central body with limb glow | partly | `BodyPrimitive` / `CentralBody` (planet/disc + glow) | satellite_scene.py:105 |
| Ghosted/faded trail copy | yes | `GhostTrail` / `TrailGhost` (faded copy of path/trajectory) | satellite_scene.py:188, 203 |
| Impact boom ring | yes | `ImpactBurst` (GrowFromCenter ring at contact point) | satellite_scene.py:160–163 |
| Labeled vector arrow pair | yes | `LabeledVector` (arrow + side label, next_to placement) | satellite_scene.py:147–152, 370–381 |
| Rotating tangent/radial arrows via updaters | yes | `OrbitVectorTracker` (put_start_and_end_on updater) | satellite_scene.py:310–336 |
| Short inward-curved path segment | yes | `CurvedArcSegment` (ArcBetweenPoints) | satellite_scene.py:285–291 |
| Moving dot actor | yes | `Particle` / `MovingActor` | satellite_scene.py:158, 185–186, 301 |
| Phase-offset circular lap path (no teleport) | yes | `PhaseShiftedCirclePath` / `orbit_lap_path(start_prop)` | satellite_scene.py:210–217, 300–306 |
| Kepler period T ∝ r^1.5 | partly (domain physics) | `kepler_period(r, base_r, base_T)` | satellite_scene.py:56 |
| Parametric gravity parabola | partly (domain physics) | `ParametricBallisticPath(launch_r, g, land_r, impact_angle)` | satellite_scene.py:61 |
| Point on circle at angle | yes | `point_on_circle(center, radius, angle)` | satellite_scene.py:115 |
| Gravity free-fall easing | yes | `fall_rate_func` (ease_in_quad; physics-accurate) | satellite_scene.py:153–157 |
| Linear-time path traversal (real-time physics) | yes | `move_along_path_linear(path, run_time)` | satellite_scene.py:219–220, 320, 441 |
| Broadcast-safe margin placement | yes | `place_safe_edge(mobject, edge, buff)` | satellite_scene.py:368, 499–500, 517 |
| Stacked label groups | yes | `stack_labels(anchor, texts, buff)` | satellite_scene.py:140–141, 333–334, 411–413 |
| Bottom-anchored summary block | yes | `bottom_summary(texts, buff)` | satellite_scene.py:246–249 |
| Per-beat lifecycle (enter/stay/transform/exit) | yes | `BeatLifecycle` helpers (fade_in → play → fade_out → clear) | satellite_scene.py:94–103, every beat |
| Updater attach-before-motion + clear | yes | `attach_updater_then_animate` / `clear_updaters` discipline | satellite_scene.py:464–466, 476–478, 510 |
| Hero-shot beat pattern | yes | `hero_shot(scene, setup, main_action, payoff)` | satellite_scene.py:265–364; storyboard.py:127–138 (hero requirement) |
| run_time ∝ physics time | yes | `scale_run_time(physics_t, k)` | satellite_scene.py:219–220 |
| Simultaneous speed comparison (Kepler lap) | partly (domain) | `simultaneous_laps(paths, periods, rate=linear)` | satellite_scene.py:435–441 |
| Explicit resolution+fps render flags | yes | `render(quality, res, fps, out_name)` | satellite_render.py:40–58 |
| mtime-newest artifact selection | yes | `pick_newest(glob)` | satellite_render.py:67–72 |
| Timed story → segments → manifest | yes | `Storybeat.to_segments()` + `timing.json` writer | script_lab.py:53; satellite_voice.py:44–50 |
| Script structure validation | yes | `Storybeat.validate()` | script_lab.py:60 |
| Fixed-order story builder | yes | `build_story(hook, escalations, centerpiece, twist, human, close)` | script_lab.py:131 |
| Global style/voice/pacing config | yes | `viral_config` singleton module | viral_config.py:40–159 |
| Background applied at scene init | yes | `configure_scene(scene, background)` | viral_config.py:121 |
| Background banding dither | yes | `add_background_noise(scene, strength)` | viral_gates.py:131; viral_config.py:152 |
| Plan/script/video publish gates | yes | `run_all(video, script, topic, renderer)` | viral_gates.py:283 |
| TTS narrator with voice lock | yes | `Narrator` + `synthesize_script` | missing_voice.py:46, 134 |
| Burned-in caption cards | yes | `burn_captions(video, srt, style)` | captions.py:84 |
| Frame extraction at interval | yes | `extract_frames(video, outdir, every)` | satellite_qa.py:43 |
| Luminance coverage/framing metrics | yes | `frame_metrics(img)` | satellite_qa.py:62 |
| Beat-window QA aggregation | yes | `assess(video, outdir, beat_windows)` | satellite_qa.py:85 |
| blackdetect black-segment check | yes | `_run_frame_check` / `black_segments(video)` | qa.py:139 |
| freezedetect no-dead-space check | yes | `max_static_window_seconds(video)` | viral_gates.py:153 |
| Stream/format probe (ffprobe) | yes | `probe_video(path)` | qa.py:58; satellite_qa.py:47; viral_gates.py:190 |
| Camera choreography (zoom/pan/dolly) | **no — absent** | (not implemented anywhere; static camera only) | — |
| dHash perceptual frame hashing | **no — absent** | (not implemented; coverage metrics used instead) | — |
| ebur128 loudness check | **no — absent** | (no audio pipeline; final video silent) | — |
| MathTex equation reveal | yes | `reveal_equation(tex, corner)` | satellite_scene.py:407–412; derivative_tangent.py:221–255 |
| ValueTracker limiting animation | yes | `limiting_tracker(start, end, run_time)` | derivative_tangent.py:185–218 |
| Manim-detectable thin wrapper | yes | `scenes/<topic>.py` subclass shim | scenes/satellite_orbit.py:20 |

---

## 3. Topic-specific vs generic classification

### Topic-specific — would break on another topic
| Code | Why | Where |
|---|---|---|
| `R_EARTH / R_ORBIT / VEC_LEN / BALL_RADIUS / R_LAUNCH / G_ACCEL` | scene-unit geometry tuned to this composition | satellite_scene.py:35–51 |
| `kepler_period` | orbital-mechanics domain physics (fine for any orbital topic, wrong elsewhere) | satellite_scene.py:56 |
| `ballistic_arc` | gravity-projectile domain physics | satellite_scene.py:61 |
| All 8 `beat_*` methods | satellite narrative + visuals + timing | satellite_scene.py:121–530 |
| `make_earth`, `impact_on_surface` | Earth visuals/geometry | satellite_scene.py:105, 115 |
| `SatelliteStoryboard` beats + NASA sources + scientific notes | satellite content | satellite_storyboard.py:18–288 |
| `build_satellite_story` narration/beats | satellite script prose | satellite_story.py:18–80 |
| `BEATS` time windows | duplicated scene timing (must be re-derived per scene) | satellite_qa.py:31–42 |
| `SCENE_NAME`, `SCENES`, output names | hardcoded scene identity | satellite_render.py:18–20, 73–75 |
| `SATELLITE_COLORS` in viral_config | satellite palette leaked into generic config | viral_config.py:48–54 |
| `scenes/satellite_orbit.py` | satellite wrapper (pattern generic, content not) | scenes/satellite_orbit.py:20 |
| Derivative pilot: `f`, `fprime`, `A_VAL`, palette, scene_* methods | calculus topic | derivative_tangent.py:20–36, 78–295 |
| Derivative storyboard data | calculus content | storyboard.py:29–206 |

### Generic — works for any topic
| Code | Where |
|---|---|
| `script_lab.py` — Beat/Storybeat/validate/build_story (entire file) | script_lab.py:28–150 |
| `viral_config.py` minus `SATELLITE_COLORS` — background/voice/pacing/gates constants | viral_config.py:40–159 (except :48–54) |
| `viral_gates.py` — RenderPlan, G1/G2/G3/G4/G5, run_all (entire file) | viral_gates.py:30–310 |
| `missing_voice.py` — ScriptSegment/Narrator/synthesize_script (entire file) | missing_voice.py:37–155 |
| `captions.py` — SRT builders + burn (entire file) | captions.py:29–107 |
| `satellite_voice.py` pattern (story hook is the only topic import) | satellite_voice.py:10, 29–65 |
| `satellite_render.py` mechanism (scene name/out names are the only topic parts) | satellite_render.py:23–84 |
| `satellite_qa.py` frame metrics + extraction (BEATS table is the only topic part) | satellite_qa.py:43–119 |
| `qa.py` ffprobe/blackdetect machinery (legacy but transferable) | qa.py:58, 76, 139 |
| `scenes/satellite_orbit.py` sys.path shim + subclass pattern | scenes/satellite_orbit.py:10–22 |
| Physics-sanity + gate unit tests pattern | tests/test_satellite.py, tests/test_viral_gates.py |

---

## 4. The 8 satellite beats → code → QA mapping

| Beat (storyboard) | Storyboard data | Rendering code | Physics/helpers | QA checks |
|---|---|---|---|---|
| 1 Hook (0–4.2 s) | satellite_storyboard.py:25–38 | `beat_1_hook` satellite_scene.py:121 | — | satellite_qa.py BEATS[0] :31; coverage/framing :85; script hook rule script_lab.py:68–76 |
| 2 Drop (4.2–9.9 s) | satellite_storyboard.py:40–56 | `beat_2_drop` satellite_scene.py:137 | `impact_on_surface` :115; ease_in_quad :153–157 | test_impact_on_surface_lands_on_radius test_satellite.py:41; BEATS[1] |
| 3 Throw faster (9.9–22.8 s) | satellite_storyboard.py:58–78 | `beat_3_throw_faster` satellite_scene.py:174 | `ballistic_arc` :61; ghost trails :188/203; orbital capture :206–226 | test_ballistic_* test_satellite.py:51,63,72; vector-const test :81; BEATS[2] |
| 4 Crucial speed — HERO (22.8–35.2 s) | satellite_storyboard.py:80–97 (hero reqs :127–138) | `beat_4_crucial_speed` satellite_scene.py:265 | `orbit_lap_path` :300–306; v/g trackers :310–336 | BEATS[3]; VEC_LEN test :81; vision QA hero verification (satellite_qa.md §6); G2 motion density viral_gates.py:153 |
| 5 Velocity (35.2–40.6 s) | satellite_storyboard.py:99–114 | `beat_5_velocity` satellite_scene.py:365 | label offsets :384–387 | BEATS[4]; label-collision vision check |
| 6 Equation (40.6–48.5 s) | satellite_storyboard.py:116–133 | `beat_6_equation` satellite_scene.py:404 | `kepler_period` :56; simultaneous laps :435–441 | test_kepler_third_law_ratio test_satellite.py:31; BEATS[5]; equation readability vision check (satellite_qa.md §3) |
| 7 Astronaut (48.5–57.5 s) | satellite_storyboard.py:135–152 | `beat_7_astronaut` satellite_scene.py:451 | updater attach-before-lap :464–466; clear_updaters :510 | BEATS[6]; object-lifecycle vision check (satellite_qa.md §2) |
| 8 Final (57.5–65.0 s) | satellite_storyboard.py:154–169 | `beat_8_final` satellite_scene.py:493 | broadcast-safe margins :499–500; final 2.0 s hold :529 | BEATS[7]; G2 static window (2.0 s < 3.0 s max) viral_gates.py:153; final-frame-simpler-than-middle vision check |

Global QA on all beats: `frame_metrics` coverage/bbox/center_offset (satellite_qa.py:62), blackdetect (qa.py:139), ffprobe stream checks (qa.py:58), captions gate G4 (viral_gates.py:190), CTA gates G5 (viral_gates.py:216; script_lab.py:109–123), 3D-plan gate G1 (viral_gates.py:93).

---

## 5. Extraction recommendations (proposed generic APIs, JSON-style)

```jsonc
// Visual primitives
{ "name": "CentralBody", "args": { "radius": 2.0, "body_color": "#14375E", "limb_color": "#3A86D6", "glow_width": 0.05 }, "returns": "VGroup" }
{ "name": "GhostTrail", "args": { "source_path": "ParametricFunction", "opacity": 0.35, "stroke_width": 3.5 } }
{ "name": "ImpactBurst", "args": { "at": "Point", "radius": 0.55, "color": "#FF6B6B", "grow_time": 0.35 } }
{ "name": "LabeledVector", "args": { "start": "Point", "end": "Point", "color": "str", "label": "str", "label_side": "'up'|'down'|'left'|'right'", "buff": 0.15 } }
{ "name": "Particle", "args": { "radius": 0.15, "color": "str" } }

// Motion / path primitives
{ "name": "PhaseShiftedCirclePath", "args": { "center": "V3", "radius": 3.4, "start_proportion": 0.25, "t_range": [0, 1] }, "returns": "ParametricFunction" }
{ "name": "move_along_path_physics", "args": { "mobject": "Mobject", "path": "ParametricFunction", "run_time": 2.4, "rate_func": "'linear'" } }
{ "name": "orbit_vector_tracker", "args": { "actor": "Mobject", "center": "V3", "vec_len": 1.7, "mode": "'tangent'|'radial'|'both'" } }

// Physics (domain-tagged, not core)
{ "name": "kepler_period", "args": { "r": 3.8, "base_r": 2.8, "base_T": 2.0 }, "returns": "float" }
{ "name": "ballistic_arc", "args": { "launch_radius": 2.8, "impact_angle_deg": 140.0, "g": 5.0, "land_radius": 2.15 }, "returns": { "path": "ParametricFunction", "flight_time_s": "float", "vx": "float" } }

// Layout
{ "name": "stack_labels", "args": { "anchor": "Mobject|Point", "texts": ["str"], "colors": ["str"], "direction": "'down'|'up'", "buff": 0.4, "font_size": 26 } }
{ "name": "bottom_summary", "args": { "texts": ["str"], "colors": ["str"], "edge_buff": 0.9 } }
{ "name": "safe_edge", "args": { "mobject": "Mobject", "edge": "'up'|'down'|'left'|'right'", "buff": 1.5 } }

// Beat lifecycle
{ "name": "run_beat", "args": { "enter": ["Animation"], "play": ["Animation"], "exit": ["Mobject"], "clear": true } }
{ "name": "attach_before_move", "args": { "updater_fn": "fn", "target": "Mobject", "then": "Animation" } }  // attach updater BEFORE animating

// Script / story
{ "name": "build_story", "args": { "title": "str", "hook": "str", "escalations": ["str"], "centerpiece": "str", "twist": "str", "human": "str|null", "close": "str", "hook_dur": 7.0, "beat_dur": 8.0 }, "returns": "Storybeat" }
{ "name": "Storybeat.to_segments", "args": {}, "returns": "[ScriptSegment]" }
{ "name": "Storybeat.validate", "args": {}, "returns": "[str]" }

// Voice / captions
{ "name": "synthesize_script", "args": { "segments": "[ScriptSegment]", "out_dir": "Path" }, "returns": "[Path]" }
{ "name": "burn_captions", "args": { "video_in": "str", "video_out": "str", "srt_path": "str", "style_override": "str|null" }, "returns": "str" }
{ "name": "script_to_srt", "args": { "script_text": "str", "start": 0.5, "words_per_card": 3, "card_gap": 0.18 }, "returns": "str" }

// Render
{ "name": "render_scene", "args": { "scene_file": "Path", "scene_name": "str", "quality": "'preview'|'final'", "resolution": [1920, 1080], "fps": 30, "out_name": "str" }, "returns": "Path" }

// QA
{ "name": "probe_video", "args": { "path": "str" }, "returns": { "duration_s": "float", "width": "int", "height": "int", "fps": "float", "codec": "str" } }
{ "name": "extract_frames", "args": { "video": "Path", "outdir": "Path", "every_s": 1.0 }, "returns": "float duration" }
{ "name": "frame_metrics", "args": { "img": "PIL.Image", "background_threshold": 0.08 }, "returns": { "coverage": "float", "bbox": "[x0,y0,x1,y1]", "center_offset": "[dx,dy]", "brightness": "float", "content_area": "float" } }
{ "name": "assess_beats", "args": { "video": "Path", "outdir": "Path", "beat_windows": "[[name,t0,t1]]", "every_s": 1.0 }, "returns": { "duration": "float", "rows": "list", "issues": "[str]" } }
{ "name": "black_segments", "args": { "video": "Path", "min_dur": 0.5, "pix_th": 0.1 }, "returns": "[(start_s, end_s)]" }
{ "name": "max_static_window", "args": { "video": "Path", "sample_every": 0.5, "noise_threshold": 2.0 }, "returns": { "longest_s": "float", "start_s": "float" } }
{ "name": "publish_gates.run_all", "args": { "video_path": "str", "script_text": "str", "topic": "str", "renderer": "str", "require_captions": true }, "returns": { "verdict": "'PASS'|'REVISION_REQUIRED'", "issues": "[str]", "plan": "[str]", "script": "[str]", "video": "[str]" } }

// Style config
{ "name": "configure_scene", "args": { "scene": "Scene", "background": "str|null" } }
{ "name": "add_background_noise", "args": { "scene": "Scene", "strength": 0.015 } }
{ "name": "suggested_script_words", "args": { "runtime_seconds": 64.0 }, "returns": 160 }
```

---

## 6. QA techniques inventory

| Technique | Status | Where (file:line) |
|---|---|---|
| **ffprobe stream/format probing** (codec, resolution, fps, duration, size) | implemented | qa.py:58 (`_run_ffprobe`), qa.py:76–139 (`analyze_video`), satellite_qa.py:47–49 (duration), viral_gates.py:190–208 (`caption_track_present`); verified manually this audit (see §0) |
| **blackdetect black-segment check** (ffmpeg `blackdetect`, >15 % black → issue) | implemented | qa.py:139–176 (`_run_frame_check`) |
| **freezedetect no-dead-space (G2)** (ffmpeg `freezedetect`, >3 s static → fail; `longest,start` returned) | implemented | viral_gates.py:153–188 (`max_static_window_seconds`); threshold constant viral_config.py:140 |
| **Frame extraction at interval** (ffmpeg `-ss … -frames:v 1`, every 1.0 s default) | implemented | satellite_qa.py:43–60 (`extract_frames`) |
| **Frame-level content metrics** (luminance coverage > 0.08 mask, bbox, center_offset, brightness, content_area) | implemented | satellite_qa.py:62–83 (`frame_metrics`) |
| **Beat-window QA aggregation** (avg coverage, max content area; near-empty <1 %, clutter >90 %) | implemented | satellite_qa.py:85–120 (`assess`) |
| **Layout/overlap QA** | **proxy only** | satellite_qa.py:62 (center_offset/content_area are proxies); real collision checks were done by vision model on contact sheets + settled-state frames, documented in output/logs/satellite_qa.md (§4 label collision). No automated text-bbox overlap detector exists — v0.3 gap. |
| **Technical vs perceptual scoring** | partly | technical: qa.py:76–139 + satellite_qa.py:85 (mechanical); perceptual: vision-model review cycle in satellite_qa.md + satellite_final_report.md (scores 9.0–9.5/10, "critical, never inflated"); no in-code perceptual scorer — scores are report artifacts. |
| **No-frozen-tail** | implemented as G2 + blackdetect | viral_gates.py:153 (freeze window must be ≤3 s; Beat 8's 2.0 s final hold satellite_scene.py:529 passes); qa.py:139 (black tail). No dedicated "final 2 s must differ from previous frame" check — G2 covers it. |
| **Caption presence (G4)** | implemented | viral_gates.py:190–208; burn pipeline captions.py:29–107; constant viral_config.py:144 |
| **CTA keyword check (G5)** | implemented | viral_gates.py:210–223, script_lab.py:109–123; keywords viral_config.py:146 |
| **Script structure validation (hook/centerpiece/twist/close/pacing/≤100s)** | implemented | script_lab.py:60–125 |
| **3D-concept plan gate (G1)** | implemented | viral_gates.py:93–117 |
| **Banding prevention (G3)** | implemented (helper) | viral_gates.py:119–151 (`add_background_noise`); recipe viral_config.py:152 |
| **Physics unit tests** (Kepler ratio, surface impact, parabola landing, no-clip) | implemented | tests/test_satellite.py:31–88 |
| **Debug artifacts** (contact sheets, sampled frames, logs, QA + final reports) | implemented | output/frames_v04/contact_{1..3}.png + f_01..24.png; output/frames/{cs,qa}/qa_*.png; output/logs/{preview,final}_render_v02.log, satellite_storyboard.md, satellite_qa.md, satellite_final_report.md |
| **ebur128 loudness** | **NOT implemented** | absent — final video is silent (no audio pipeline); must be added in v0.3 when TTS is wired in |
| **dHash (perceptual hashing)** | **NOT implemented** | absent — coverage metrics used instead; dHash would give frame-difference/frozen-tail + scene-change detection cheaply; v0.3 gap |

---

## 7. What NOT to copy (into the generic v0.3 core)

1. **Scene-unit geometry constants** — `R_EARTH=2.0`, `R_ORBIT=3.4`, `VEC_LEN=1.7`, `BALL_RADIUS=0.15`, `R_LAUNCH=2.8`, `G_ACCEL=5.0` (satellite_scene.py:35–51) are tuned to this 16:9 composition, not reusable numbers.
2. **Hardcoded font sizes / buffs / run_times** — 26/40/48/52 pt text, `buff=0.4/0.8/1.5`, `run_time=1.3/3.4/2.4` etc. are art-direction values baked into beat methods; the *pattern* (safe margins, stacked labels, physics-scaled run times) is reusable, the literals are not.
3. **Duplicated beat timing** — the `BEATS` window table in satellite_qa.py:31–42 re-encodes scene timing by hand; it drifted once (test_qa_timeline_covers_runtime guards it). v0.3 should derive beat windows from the storyboard/scene, not copy them.
4. **Topic palette leaked into generic config** — `SATELLITE_COLORS` (viral_config.py:48–54) sits in the "single source of truth" module while the same colors are re-declared in satellite_scene.py:37–40. Pick one home; the generic module should hold only global defaults.
5. **Topic content hardcoded in generic modules** — `SCENE_NAME`/`SCENES`/output names in satellite_render.py:18–20, 73–75; the `build_satellite_story` import in satellite_voice.py:10; NASA_SOURCES/SCIENTIFIC_NOTES (satellite_storyboard.py:260–288) and narration prose — these belong in a per-topic package, injected via config/CLI.
6. **Dead code** — `prod = input if False else None` (satellite_qa.py:113); the whole legacy pilot line (`pilot.py`, `render.py`, `qa.py`, `storyboard.py`, `derivative_tangent.py`, `test_pilot.py`, plus old `DerivativeTangentScene_*.mp4` outputs) — keep only the QA techniques (blackdetect/ffprobe) and the ValueTracker limiting pattern.
7. **Manim-workaround specifics** — the phase-offset `ParametricFunction` lap paths (satellite_scene.py:210–217, 300–306) exist because `MoveAlongPath` re-wraps to t=0 (teleport); the *concept* (never teleport an actor) is a lesson, the exact closure/`s`/`TAU` arithmetic is per-scene.
8. **Deliberate-hold exception** — Beat 8's `wait(2.0)` "hold final frame (simpler than the middle)" (satellite_scene.py:529) is a conscious trade-off against the G2 no-frozen-tail rule (3 s limit); do not copy long tail holds as a default.
9. **Environment artifacts** — `.venv/`, `media/` partial movies, `output/frames_v03/` (superseded by frames_v04) are not source.
10. **Enforced render flags as a copy-paste** — the exact `-r 1920,1080 --fps 30` invocation is a correct *fix* for the `-qh` preset bug; v0.3 should expose resolution/fps as parameters, not hardcode them in a second renderer (cf. the divergence between render.py:29–63 and satellite_render.py:23–84).

---

## 8. Bottom line for v0.3

- **Reusable core already exists and is clean:** `script_lab.py`, `viral_config.py`, `viral_gates.py`, `missing_voice.py`, `captions.py`, plus the frame-QA machinery (`satellite_qa.py:43–120`) and render hygiene (`satellite_render.py:40–75`).
- **The main architectural debt:** everything topic-specific lives *inside* `satellite_scene.py` (one 500-line file), and topic identity (scene name, output name, beat windows, QA topic string) is hardcoded in otherwise-generic modules. v0.3 should split **topic package** (scene + storyboard + story + palette) from **generic core** (script lab, config, gates, voice, captions, QA, render), with a small manifest object (`topic = {scene_name, scene_file, beats, beat_windows, story_builder, colors}`) as the only topic↔core interface.
- **QA gaps for v0.3:** ebur128 loudness, dHash (frozen-tail/scene-change), and automated text-overlap detection are missing; the v0.2 cycle proved vision-model review of contact sheets + settled-state frames is the highest-value perceptual check, so keep it as an explicit pipeline stage, not a manual artifact.

*Report generated from a read-only audit; no project files were modified.*
