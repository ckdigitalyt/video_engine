# V8 Plan — Visual Storytelling Engine (algorithm-level)

**Date:** 2026-09-06 · **Brief:** `Jade_todo.txt` (V8) · **Prior:** `V7_REPORT.md`, `V7_PLAN.md`
**Prime directive (brief §17):** the goal is not CAN_PUBLISH=true. The goal is: *would a human viewer mistake this for a deliberately produced YouTube documentary rather than an automated slideshow?*

---

## 1. Architecture: extend vs unchanged

| Module | Verdict | What changes |
|---|---|---|
| `engine/planv7.py` | **EXTEND → `engine/planv8.py`** | Visual state machine, escalation curve, curiosity ladder, TTS performance plan, hero anchors, duration policy |
| `engine/editorial7.py` | **EXTEND → `engine/editorial8.py`** | Visual information gain, semantic payoff, filler/duration policy, human-viewer simulation; keeps coverage/ITS/continuity/anti-template |
| `engine/composev5.py` | **EXTEND (in place)** | Mid-shot state transitions, living-diagram events, full-bleed composition profile, event-synced SFX cues |
| `engine/audio_mix.py` | **EXTEND (in place)** | Continuous drone bed OFF by default; narration > event SFX > sparse ambience; loudness/tonal metrics |
| `engine/visualclass.py` | **EXTEND (in place)** | Hero recognizability, narration-card budget ≤5–10%, parchment-share audit |
| `engine/story_grammar.py` | **NEW** | Subject-specific visual grammar packs (science/history/geography/engineering) |
| `cli.py` | **EXTEND** | `plan8`, `qa8full` commands; per-story plan guard (kept) |
| Renderer primitives (`_v6_cardlib`, `_camera_filter`, parallax/flags), `antitemplate.py`, `semantic_qa.py`, caption system, facts/CAS | **UNCHANGED** | Per brief: no new rendering stack, no AI video, no Manim. Anti-template keeps measuring; variation now emerges from grammar |

## 2. Core design decisions

### 2.1 Visual state machine (brief §1) — `planv8.py`
`narration beat → visual intent → visual state sequence → choreography`.
- Every shot gets a declared `intent` and a `states: [ESTABLISH → FOCUS → TRANSFORM → CONSEQUENCE → PAYOFF]` subsequence chosen by the planner (not all states everywhere).
- Each state transition is rendered as a **mid-shot plate evolution**: `state_plates: [{t, kind}]` in the shot schema; composev5 crossfades/mutates the plate at those times. States are **derived algorithmically from the existing plate manifest** (element geometry from `make_cards.py`): progressive reveal of annotated layers, flow along declared connectors, region emphasis, element group dim/isolate. Where a state genuinely needs new art the planner emits an honest `needs_state_plate` flag instead of faking it.
- Phone example (brief): charger plate → current flow → resistance → heat → thermal protection becomes five declared states on the existing chain/split/limit plates, animated by reveal+flow+fill events — not five static cards.

### 2.2 Living diagrams (brief §3) — composev5 events
New event kinds beside number_pop/highlight/pulse: `reveal` (progressive element visibility), `flow` (animated particles/dashes along a path between two manifest elements), `fill_state` (area fill change on a declared region), `isolate` (dim everything except a group), `consequence` (state change with SFX cue). Implemented as pre-rendered overlay frame sequences — same rendering stack, zero new dependencies. **Camera movement alone registers as zero information gain (enforced in the metric, §2.4).**

### 2.3 Subject-specific grammar (brief §4) + anti-template (§16) — `grammar.py`
Per story_type packs declaring expected visual classes, state-transition patterns, and vocabulary requirements: science → cutaways/particles/energy flows/scale; history → maps/timelines/event chains/documents; geography → recognizable silhouettes/regional overlays/terrain; engineering → cross-sections/exploded views/forces. Planner selects and validates against the pack; anti-template keeps fingerprinting — variation must emerge from grammar, never random.

### 2.4 Visual information gain (brief §7) — `editorial8.py`
Timeline split into 2–4s windows; each window counts only declared NEW semantic content: new relationship / cause-effect / scale / location / comparison / process state / consequence / evidence. Zoom, pan, number pops, decorative animation count zero. Gate: no window sequence may coast on camera motion.

### 2.5 Escalation curve (§8) + curiosity ladder (§9) — `planv8.py`
Per-beat `intensity` profile must trace hook → orientation → discovery → escalation → reveal → payoff (penalized for flat lines). Each beat declares `opens` / `resolves` question IDs; ≥1 open question must be alive at all times; the final beat resolves the central question.

### 2.6 Payoff, redefined (§13) — `editorial8.py`
Lexical overlap demoted. Payoff = semantic resolution: declared hook curiosity → explanation chain → final visual resolution (concept/entity match between hook question and payoff state, plus the payoff shot's declared state sequence ending in PAYOFF class). Reported honestly as partially declarative until an LLM checker is live again (DeepSeek key currently 401).

### 2.7 TTS performance plan (§10) — `planv8.py` + TTS step
Every beat emits `performance: {pace, energy, emphasis[], pause_locations[], arc, intensity}` → maps to TTS parameters (rate, pauses as silence insertion, emphasis via pacing) and drives audio timing.

### 2.8 Audio (§11) — `audio_mix.py`
Continuous tonal/drone bed **off by default**. Hierarchy: narration > event-synced SFX (at declared visual event times) > sparse ambience only where the plan declares it. New `audio_metrics`: integrated LUFS, true peak, speech-to-bed ratio, noise floor, low-frequency tonal energy, dynamic range — measured, reported, gated on tonal-noise.

### 2.9 Narration-card budget (§2) + full-bleed (§6) + hero recognizability (§5) — `visualclass.py` + composition profile
Generic blurred narration cards target ≤5–10% of narration duration (was ≤10% gate, now planner-enforced preference for evidence/diagram/map/cutaway classes). Full-bleed 9:16 composition profile: evidence occupies the field, parchment margins shrink, chrome gone after the opening. Hero recognizability: first hero frame must declare ≥1 recognizable subject anchor (silhouette for geography, named structure for science/history) — abstract-shape-only heroes fail.

### 2.10 Duration (§14) + human viewer simulation (§15) — `editorial8.py`
No hard fail >60s; instead filler/redundant-beat/weak-pacing detection (repeated beat functions, zero-info-gain windows, redundant visual states). Viewer simulation checks at 0.5s/2s/5s/15s/30s/final computed from plan + measured render data.

### 2.11 TTS A/B (§12) — separate harness
Same 30–45s narration via current Chatterbox Turbo vs Kokoro v1.0 vs Qwen3-TTS 0.6B, blind-scored (naturalness 25 / authority 20 / prosody 20 / range 15 / clarity 10 / names+numbers 10). No switch on benchmark claims alone. Runs as its own task; not on the render critical path.

## 3. Implementation order (global, then validated on the 3 existing stories — no per-video re-authoring)

1. `story_grammar.py` + `planv8.py` (state machine, escalation, curiosity, performance plan) → `plan8` CLI
2. `editorial8.py` (info gain, semantic payoff, duration, viewer sim) → `qa8full` CLI
3. composev5: state transitions + living events + full-bleed profile + event SFX
4. audio_mix: bed off, SFX-at-events, audio metrics
5. visualclass: hero/narration-card/parchment audits
6. Validate on phone_heating / titanic_mistake / sahara_greening as-is; report with before/after V7 numbers and the documentary-vs-slideshow verdict
7. TTS A/B harness in parallel

**Honest constraints:** states that require genuinely new art are flagged (`needs_state_plate`), not faked; DeepSeek R4 remains down (401) so semantic checks are deterministic/declared until the key is refreshed.
