# video_engine v0.3 — Autonomous Visual Explanation Engine

Status: DRAFT (implementation blueprint)
Date: 2026-08-20
Sources: JADE_TO_DO v0.3 spec · `docs/audit/mm-lab-v02-audit.md` · `docs/audit/engine-current-map.md`

## 0. Mission

MathMotion Lab v0.2 proved the *visual language* can be produced procedurally
(satellite orbit: narrative progression, object lifecycle, physics, hero shot,
payoff). v0.3 makes the **production engine** (video_engine, branch `jade`)
discover and construct that visual language **autonomously from a bare topic**.

Success criterion: input `"Why is the sky blue?"` (no storyboard) →
output video whose visual logic belongs to the same family as SatelliteOrbit:
question → physical/visual experiment → transformation → evidence →
hero explanation → payoff — with local/free tooling, deterministic rendering,
audio, technical+visual QA, factual verification, autonomous E2E.

## 1. Architecture principles (from the spec)

1. **Do not destroy correctness work.** SceneState lifecycle, math_verify,
   schema gates, ffprobe/ebur128 QA, frame QA, debug artifacts, YAML config,
   deterministic seeds — all preserved and extended.
2. **Separate proven rendering from autonomous direction.** MathMotion Lab
   stays an isolated R&D lab. Its *concepts* are promoted into video_engine
   primitives; its satellite scene is NOT copied.
3. **World model first.** Every video is planned as semantic entities +
   relationships + forces + signals + paths + states + measurements + labels,
   with factual constraints attached. Manim is the renderer, not the planner.
4. **Simulation over illustration** where the subject is mathematical/physical.
5. **Kinetic text is a fallback**, not the default.
6. **QA is semantic**: visual explanation score (avg ≥ 3.5), mute test,
   no-text review, text-dominance ratio.

## 2. Module layout (new code in ~/video_engine)

```
engine/world/                 NEW — semantic planning layer (no Manim imports)
  world_model.py              WorldState, Entity, Relationship, Force, Signal,
                              Path, Measurement, Label, CameraFocus, Fact
  representations.py          RepType enum + RepresentationSelector (rules+LLM)
  actions.py                  Action vocabulary + ActionRegistry (action→primitive)
  story_templates.py          StoryTemplate library + StoryArchitect + hero_mechanism
  scoring.py                  visual explanation score (0-5), text-dominance ratio
engine/primitives/            EXTENDED — generic world primitives (Manim)
  world_primitives.py         NEW: physics/science/info primitives (see §5)
  manim_primitives.py         keep; refactor Kaprekar-specific bits out of
                              generic paths (canonical_id, _MANAGED_TEMP stay)
engine/renderers/manim/
  compiler.py                 EXTENDED: materialize arbitrary entity types from
                              world model; semantic actions resolve via registry
engine/visuals/
  scene_state.py              generalize zone_conflicts focal set (configurable)
  visual_director.py          EXTENDED: emits WorldState + rep_type + hero +
                              per-beat explanation scores; kinetic text last
engine/validation/
  math_verify.py              keep; ADD physics verifiers (orbital, scattering)
engine/qa/
  gates.py                    keep; ADD visual-explanation + text-dominance gates
  mute_test.py                NEW: no-text render variant + dHash motion check
  no_text_review.py           NEW: contact sheets of no-text variant
engine/audio/
  timeline.py                 keep; ensure kokoro (local) is first-choice TTS
engine/cli/run.py             EXTENDED: `topic` autonomous command
tests/                        NEW: per-primitive visual regression + unit tests
```

## 3. WorldState schema (spec §4, §18)

```json
{
  "topic": "why is the sky blue",
  "representation": "SIGNAL_FLOW",
  "entities": [
    {"id": "sun", "type": "light_source", "properties": {"spectrum": "white"}},
    {"id": "atmosphere", "type": "medium", "properties": {"height": 100}},
    {"id": "molecule", "type": "scatterer", "count": 200},
    {"id": "observer", "type": "eye", "properties": {"direction": "up"}}
  ],
  "relationships": [
    {"source": "sun", "target": "atmosphere", "type": "emits_into"},
    {"source": "atmosphere", "target": "molecule", "type": "scatters"},
    {"source": "molecule", "target": "observer", "type": "reaches"}
  ],
  "forces": [],
  "signals": [
    {"id": "sunlight", "kind": "light_wave", "from": "sun", "to": "atmosphere",
     "properties": {"wavelengths": [450, 550, 650]}}
  ],
  "paths": [],
  "states": [],
  "measurements": [],
  "labels": [],
  "camera": {"focus": "molecule", "choreography": ["zoom_into", "follow"]},
  "hero_mechanism": {
    "concept": "shorter wavelengths scatter more (Rayleigh 1/λ^4)",
    "visualization": "wavelength_dependent_scattering",
    "target_beat": "b004"
  },
  "facts": [
    {"formula": "I ∝ 1/λ^4", "units": "relative", "assumption": "particles ≪ λ",
     "source": "Rayleigh scattering, Lord Rayleigh 1871"}
  ]
}
```

Rules:
- Entity types come from a closed registry (light_source, medium, scatterer,
  eye, celestial_body, moving_body, wave, particle, field, node, flow, ...).
- Facts MUST accompany any quantitative claim; `assumptions` section lists
  simplifications (e.g. "idealized two-body circular orbit", "particles much
  smaller than wavelength").
- The world model is validated by a strict schema (Gate 1) before direction.

## 4. Representation selection (spec §8)

Closed enum: DIRECT_DIAGRAM, SIMULATION, PHYSICAL_MODEL,
MATHEMATICAL_TRANSFORMATION, CAUSE_EFFECT, SIGNAL_FLOW, COMPARISON, TIMELINE,
GRAPH, NETWORK, CHARACTER_ACTION, EXPERIMENT, METAPHOR, KINETIC_TEXT,
REAL_MEDIA, HYBRID.

Deterministic rule layer (first match wins), LLM only to break ties:
- orbital/mechanics → PHYSICAL_MODEL | SIMULATION
- perception/illusion (McGurk) → SIGNAL_FLOW + EXPERIMENT
- number theory (Kaprekar/Collatz) → MATHEMATICAL_TRANSFORMATION + GRAPH
- optics/atmosphere → SIMULATION + SIGNAL_FLOW
- historical → REAL_MEDIA + TIMELINE
- fallback (no better match) → CAUSE_EFFECT + DIRECT_DIAGRAM
- KINETIC_TEXT only when the topic has no demonstrable mechanism

The renderer is selected AFTER representation: PHYSICAL_MODEL/SIMULATION/
TRANSFORMATION/SIGNAL_FLOW/EXPERIMENT/CAUSE_EFFECT → Manim;
REAL_MEDIA → media renderer (later).

## 5. Primitive library (spec §6 — promoted from MathMotion Lab + new)

Physics (from mm-lab audit: `kepler_period`, `ballistic_arc`, updater trackers,
lap paths, ghost trails):
- `CelestialBody` (Earth: disc + limb glow), `OrbitPath` (parametric ellipse/
  circle lap), `MovingBody` (satellite/ball, phase-offset lap, no teleport),
  `Trajectory` (ballistic arc under constant g), `VelocityVector`, `ForceVector`
  (gravity → center), `GravityField` (radial arrows), `Projectile`,
  `ReferenceFrame` (axes grid)
Science:
- `Wave` (sine packet), `LightRay` (beam + wavelength coloring), `Signal`
  (pulse traveling), `Particle`, `Field`, `Scatterer` (molecule: ray hits,
  re-emits in all directions, blue scatters more), `ScatteringField`
  (hero primitive for sky-blue), `Atom`, `Molecule`, `Lens`
Information/psychology (schematic, not anthropomorphic):
- `Node`, `Connection`, `Flow`, `Pipeline`, `Decision`, `Timeline`,
  `CauseEffect` (A ↓ B ↓ C), `Comparison`, `Hierarchy`,
  `Brain`, `Eye`, `Ear` (simplified schematic glyphs)
Narrative:
- `Question`, `Experiment`, `Hypothesis`, `Observation`, `Reveal`,
  `Counterexample`, `Payoff`

Every primitive: deterministic, state-aware (SceneState enter/update/exit),
JSON-parameterized, no topic-specific constants.

## 6. Action grammar (spec §7)

Semantic actions: orbit, fall, accelerate, decelerate, collide, miss, curve,
follow, trace, branch, merge, converge, oscillate, flow, scatter, assemble,
disassemble, compare, measure, zoom_into, zoom_out_of, focus_on,
cross_section, reveal_inside.

Each maps through `ActionRegistry` to one or more primitives:
- `fall` → MovingBody + ForceVector (gravity) + Trajectory
- `orbit` → CelestialBody + OrbitPath + MovingBody (lap)
- `scatter` → ScatteringField (incoming ray → multi-direction re-emission,
  short λ dominant)
- `converge` → ConvergenceParticles / AttractorDiagram (existing)
- `flow` → Flow (pipeline of nodes)
- `zoom_into` / `focus_on` → camera frame scale/move (existing pattern)

The director emits semantic actions on entities; the compiler resolves
actions → primitives. A sentence like "the satellite keeps falling, but the
surface curves away" maps to `satellite.fall()` + `surface.curve_away()` +
`camera.follow(satellite)` — not to on-screen text.

## 7. Story templates + hero mechanism (spec §13–15)

Template library (StoryArchitect picks by topic+facts):
1. Mystery → Experiment → Reveal
2. Question → Demonstration → Explanation
3. Counterintuitive fact → Visual proof → Resolution
4. Prediction → Test → Surprise → Explanation
5. Simple case → Extreme case → General rule
6. Problem → Failure → Insight → Solution
7. EXPERIMENT-DRIVEN (default for science, from v0.2): QUESTION →
   SIMPLE EXPERIMENT → CHANGE ONE VARIABLE → OBSERVE → PUSH TO EXTREME →
   DISCOVER PRINCIPLE → EXPLAIN PRINCIPLE → PAYOFF

Every plan emits `hero_mechanism {concept, visualization, target_beat}` —
the one animation that proves the central mechanism (v0.2's Beat 4 orbit
generation; sky-blue's wavelength-dependent scattering).

## 8. Visual explanation scoring (spec §10, §28)

Per beat, before rendering:
- 0 narration only · 1 decorative · 2 loosely illustrative · 3 concept
  visualization · 4 direct demonstration · 5 highly informative transformation
Deterministic heuristics (visual_type + actions + world entities) + LLM
cross-check. Gate: average ≥ 3.5 → perceptual PASS; a video dominated by
0–2 beats fails and is re-directed.

Text-dominance ratio = Σ duration of beats whose primary visual is text /
total duration. Target: < 0.35 (hooks, terms, numbers, reveals only).

## 9. QA additions (spec §11, §12, §24, §27)

- **Mute test**: render/analyze the video with narration hidden; verify the
  central mechanism is visually readable (dHash frame diffs at beat
  boundaries + contact-sheet vision review).
- **No-text review mode**: env flag re-renders analysis variant with
  explanatory text hidden (subtitles preserved separately); contact sheets
  reviewed; feeds perceptual score.
- **Visual regression tests**: per primitive, input JSON → render reference
  frame → dHash compare (spec §24).
- Report format per topic (spec §27): topic, story template, hero mechanism,
  beat count, representation types, text-dominant ratio, avg explanation
  score, # procedural primitives, # simulation beats, audio duration,
  render time, QA scores, component provenance (MathMotion Lab vs engine).

## 10. Audio (spec §20)

Production engine already has narration + timeline + mastering. v0.3:
- **Local TTS first**: Kokoro (kokoro-onnx 0.5.0 + kokoro-v0_19.onnx,
  already in repo) as primary narrator; fish free tier as fallback; Edge/
  espeak as last resort. No network dependency for the core path.
- Narration is generated BEFORE visual timing; beats sized to measured
  narration duration (no frozen tail — existing pattern).
- SFX cues already exist per beat (audio_cues); keep; add music bed if
  available locally (check existing assets) — otherwise silence is acceptable
  only for R&D, not production.

## 11. Autonomous pipeline (spec §25–26, §31)

New CLI: `python -m engine.cli.run topic --topic "Why is the sky blue?"`

Stages (each writes deterministic artifacts to output/<topic>/):
1. research   — web research + facts (existing research module)
2. verify     — deterministic verifiers for any quantitative claim
3. story      — StoryArchitect: template + beats + hero_mechanism
4. script     — narration written to template beats (existing script path)
5. world      — WorldState build (entities/relationships/signals/facts)
6. direct     — VisualDirector: representation → per-beat visual spec +
                explanation scores
7. compile    — compiler: world+beats → Manim scene (semantic actions)
8. render     — 1080p preview first (QA loop), then 4K final
9. audio      — kokoro narration → timeline sync → SFX → master
10. compose   — ffmpeg: video + audio + captions
11. qa        — technical (ffprobe, ebur128, dHash, freeze) + visual (frames)
                + semantic (explanation score, text-dominance, mute, no-text)
12. report    — spec §27 comparison table

No topic-specific hardcoded scene selection anywhere.

## 12. Test set (spec §25)

Test A Kaprekar · Test B Collatz · Test C Satellite orbit · Test D McGurk ·
Test E Why is the sky blue — all through the SAME engine, topic-only input.
First required autonomous run: Test E (sky blue).

## 13. Constraints

- Local/free tooling only (kokoro/fish-free/edge; no paid TTS).
- DeepSeek V4 Flash via existing LLM path (deterministic fallbacks for every
  stage; LLM is never authority for math/physics).
- 4 CPU / 24 GB Oracle compatibility; deterministic seeds; YAML config;
  strict schemas; no global package installs (repo venv).
- MathMotion Lab stays isolated; promotion process (spec §23) is the only
  path from lab → engine.
