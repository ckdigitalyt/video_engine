# V11_REPORT.md — V11 P0 implementation + validation (2026-09-10)

Directive: `Jade_todo_v11.txt` (P0 sections only; P1/P2 out of scope). Story
under test: `ice_slippery` (the V10 validation story), re-rendered
end-to-end with story files untouched EXCEPT the end-card/brand compliance
fix (§3.2). Base: V10 (`72d052d`), all V10 flags and rollback paths intact.

## 1. P0 changes per item

### 1.1 Caption state machine (P0 — caption compositing regression)

**Root cause found (evidence, not guesswork):** the V10 kinetic caption band
(1344..1459) overlapped the card's bottom edge after the 9:16 cover-crop.
Every plate carries baked footer text (`footer_centered`, plate y=920) which
lands at frame y≈1312..1397 — inside the band. Result: the baked footer
showed through the caption scrim as a second, gray caption behind the active
one ("WHY SO SLIPPERY?" behind "A FROZEN LAKE,", "BORN AT THE SURFACE"
behind "BORN AT THE SURFACE," — frames extracted from the V10
`output/ice_slippery.mp4` at t=2.4/4.7/50). V10_REPORT §8.4 logged this as
"known cosmetic"; the reviewer correctly classified it as the P0 ghost
defect. Concat is hard-cut (`-c copy`), so there was no cross-shot crossfade
bleed — the ghost was this in-band collision.

Changes (`engine/captions.py`, `engine/composev5.py`):
- `captions.normalize_cues()` — the ACTIVE_CAPTION state machine: sort,
  clamp to the shot, drop degenerate states, enforce a 50 ms off-window
  between consecutive states (the previous state is fully removed before
  the next activates). Every normalization is recorded as a repair record.
- Band re-anchored BELOW the card (`captions.band_rect()` → card bottom
  + 24 = 1464..1656 under the V11 card geometry): plate-baked text can
  never enter the band, by construction. Rollback `V11_CAPTION=0` restores
  the V10 band byte-for-byte.
- `build_shot_captions()` asserts the exclusivity invariant at render time:
  two overlapping carrier windows raise instead of rendering stacked
  captions; returns the normalized cues + repairs for QA.
- Declared multi-line states: `cue["lines"]` (or embedded `\n`), max 2
  lines (`MAX_LINES`), one carrier window per state; the carrier renderer
  stacks up to 2 centered lines.
- Punctuation/emphasis: `text_emphasis` rules anchor to the ACTIVE cue and
  their hold is clipped to that cue's end — emphasis can never outlive its
  caption into the next state.
- Flag token `v11c` added to the CAS shot hash (artifacts never mix).

### 1.2 Caption QA gate (P0) — `engine/caption_qa.py` (new)

CONSTRUCTION layer (independent re-derivation from the plan): authored cue
overlaps, persistence past beat end, >2-line states, safe-zone containment
(overlay report), GLOBAL state uniqueness across the whole video timeline,
renderer repair records. PIXEL layer (ffmpeg frame samples, no OCR
dependency): off-state probe at every state boundary (the boundary frame
inside the gap must be text-empty — any glyph pixels mean a layer persisted
past its state = stale/ghost), foreign-text probe mid-cue (band pixels
outside the active carrier + emphasis margin), shot-end persistence probe.
ANY stale/overlapping caption = P0 → `CAPTION_PASS=false`. Probes are
anchored at `prev_t1 + 5 ms` because ffmpeg `-ss` snaps forward to the
frame at/after the requested time (run-1 false hit: a probe meant for the
gap landed on the new state's first frame).

### 1.3 DEBUG_LEAK_SCAN (P0) — `engine/leak_scan.py` (new)

- SOURCE layer (deterministic): every drawable string is collected from the
  plan/story/bible trees — captions (incl. chunk words), event pop texts,
  titles, tags, end cards, title overlays, story/bible brand — and scanned
  for DEBUG / TEST / SIGNAL / PLACEHOLDER / TODO / FIXME / DUMMY / LOREM /
  UNTITLED, model names, filename shapes, internal-id shapes. Word-boundary
  matching. NO story-level whitelisting (directive: the SIGNAL leak is
  fixed at content level, never exempted).
- FRAME layer: 12 sampled frames; glyph-like pixels outside all declared
  text zones (header band, card content, caption band) = P0. Catches baked
  plate text escaping the card after composition bugs.
- Any hit → `DEBUG_FREE=false` → CAN_PUBLISH=false.

### 1.4 True 9:16 composition (P0)

`engine/composev5._ambient_base()` V11_FULLBLEED path (default ON; `V11_
FULLBLEED=0` restores the V10 blurred backdrop): the card grows to
1080×1248 at y=192 (65% of the canvas; card bottom stays 1440 so the
caption band is identical), and the top/bottom bands are a CRAFTED
CONTINUATION — the outermost 64 card rows (card-aspect cover crop of the
same plate, so tones match the card edge) stretched (LANCZOS) to fill the
band, tone-graded toward the bible background toward the frame extremes.
No gaussian blur anywhere: `blurred_extension_area = 0` by construction.
The first implementation mirrored full card rows and duplicated baked plate
text ("WATER SKIN" legible upside-down in the bottom band) — replaced with
the stretch before validation; the stretch never duplicates glyphs.
Ambient parallax drift is skipped under full-bleed (the continuation is
seam-locked to the card edges; card camera motion is untouched).

`engine/occupancy_qa.py` (new) — CANVAS_OCCUPANCY, construction-truth per
shot: card rect + header text rect + caption carriers + plan evidence rects
rasterized on a 12 px grid → `content_frac`. The backdrop is pixel-verified
on rendered frames (edge-density floor 0.004): a "continuation" that is
actually flat fill is demoted to empty (anti-gaming). Calibration: the V10
blurred backdrop measures 0.000 edge density; the V11 continuation measures
0.052 (top) / 0.022 (bottom) — the floor separates craft from blur by an
order of magnitude. Gate: story mean over major explanatory shots ≥ 0.75
(target) with a 0.50 hard floor; deliberate exceptions must be declared in
the plan via `shot["occupancy_exception"]` (none declared — none needed).

### 1.5 EXPLANATORY_MOTION_RATIO (P0)

`engine/planv5._motion_class()` tags every shot A/B/C at plan time and
`engine/planv8.py` RE-TAGS after the v8 living-event stamping (the plan5
event set predates the state machine — without the re-tag every C-shot
misclassifies as A/B; authored `motion_class` overrides are respected via
`motion_class_authored`). C = explanatory living events (reveal / isolate /
flow / fill_state / consequence) or process/field kinetic types; B =
structural events (pops, highlights, restyle kinetic); A = camera-only or
static — camera movement does NOT count as information. `engine/motion_
class.py` (new) computes duration-weighted shares + the ratio. Gate (hard):
A > C fails (decoration must never outweigh explanation). The strict
C > B > A ordering is an advisory so stories genuinely lacking B-motion are
not punished into faking structural events. No events were added to satisfy
the metric — tagging and measurement only.

### 1.6 CAN_PUBLISH rework (P0) — `engine/publish_gate.py` (new)

CAN_PUBLISH = AND of eight named components; numeric scores cannot override
a false component. Mapping (additive; nothing duplicated):

| Component | Sources |
|---|---|
| TECHNICAL | qa5 TECHNICAL group ≥ 95 + no p0 checks + motion smoothness + audio continuity + v6.2 completion checks |
| FACTUAL | semantic_qa SEMANTIC_PASS (deterministic + exact-wording) |
| CAPTION | caption_qa (NEW) |
| DEBUG_FREE | leak_scan (NEW) |
| VISUAL_EVIDENCE | editorial7 evidence_cinematic_80 + qa5 subject acceptance + CANVAS_OCCUPANCY + EXPLANATORY_MOTION_RATIO (A>C) |
| VIEWER_SIMULATION | editorial8 viewer_simulation + escalation_curve + curiosity_ladder + info_gain_60 |
| ANTI_TEMPLATE | editorial7 antitemplate verdict (structural fingerprint) |
| AUDIO | bed continuity + audio completion (loudness normalized at mix: −14 LUFS / −1.5 dBTP) |

editorial7's human-editor test (incl. payoff_70) is a REPORTED diagnostic —
it also surfaces through qa5's EDITORIAL group and the top-concerns list
(rationale in §3.1). Integrated into `qa8full` (`cli.py`): prints the 8
components + P0 defects, writes `build/qa/publish_gate_<story>.json` plus
caption_qa/leak_scan/occupancy/motion_class artifacts. `V11_GATES=0` rolls
back to the pre-V11 qa8full behavior exactly.

## 2. Validation matrix — ice_slippery V11 vs V10 (V10_REPORT §8)

Re-render: `plan5 → plan7 → plan8 → render5 --force → qa8full --v6`, flags
`…-v10v-v10k-v10d-v10p-v11c-v11f` confirmed on plan and render. Story files
changed ONLY: `story.json` + `visual_bible.json` brand `SIGNAL → SURFACE`,
`visual_plan.json` end_card `SIGNAL → ALREADY WET` (§3.2). Engine applies
globally — no per-video patch.

| Metric | V11 (this run) | V10 (§8.1) | Δ / note |
|---|---|---|---|
| Duration | 54.00s | 54.00s | = |
| TECHNICAL | 100.0 | 100.0 | = (run-1 false 91.67: overlay_compliance read the stale 1350..1520 constant — root-caused, fixed, see §3.3) |
| VISUAL | 95.03 | 95.30 | −0.27 (style_continuity 50.3 vs 53, advisory; continuation bands feed the palette match) |
| EDITORIAL | 95.91 | 95.91 | = |
| IV (gate 80) | 100.0 | 100.0 | = |
| NVA (gate 80) | 100.0 | 100.0 | = |
| ID (gate 75) | 86.8 | 86.8 | = |
| Motion smoothness | jitter 100.0 / reversals 100.0, 0 bad | same | = |
| Audio continuity | 100.0, 0 gaps, 0 restarts | same | = |
| Continuity | 7/7 (0.563–0.638), video 0.6091 | 7/7, 0.609 | = |
| Phone QA | readable=True, pop_px=32, diag_px=48 | readable=True, pop_px=31, diag_px=48 | = |
| LUFS | −14.17 (TP −1.44) | −14.17 (TP −1.44) | = |
| Editorial gates | 8/8 PASS, documentary, semantic True | same | = |
| CAPTION (new) | **PASS** — construction 0 overlaps / 0 past-end / 0 line-cap / 0 safe-zone; pixels 35 probes, 0 off-state / 0 foreign / 0 shot-end; 14 gap-shift repairs (authoring contiguity absorbed ≤50 ms per boundary, logged) | n/a (defect class invisible) | new gate |
| DEBUG_FREE (new) | **PASS** — 0 source hits, 0/12 frame hits | "SIGNAL" rendered top-center every payoff frame + top-left brand marker | fixed at content level |
| CANVAS_OCCUPANCY (new) | **0.819** meaningful (target 0.75), continuation verified (edge 0.052/0.022 vs floor 0.004; V10 blur = 0.000) | no metric; ~60% card + 40% blurred backdrop (blur not meaningful) | up, honestly measured |
| EXPLANATORY_MOTION_RATIO (new) | C=1.00 A=0.00 B=0.00 — gate pass (C>A); strict C>B>A advisory NOT met (no B-only shots: every shot carries living explanatory events) | no metric | reported, not faked |
| CAN_PUBLISH | **True** — 8/8 components (+ diagnostics: human_editor_gates False via payoff_70 65.8<70, surfaced) | True (qa5+editorial only) | stricter structure, same verdict |

Advisories unchanged from V10: style_continuity ~50, payoff_strength 55
(memorable=False), planv7 payoff_check 65.8<70 — all surfaced, non-gating
under the documented mapping (§3.1).

### 2.1 Frame checks (extracted from `output/ice_slippery.mp4`)

Frames inspected: t=2.4 (hook), t=4.7 (hook, V10-defect comparison frame),
t=23.45 (caption boundary), t=31.0 (escalation living overlay), t=50.0
(payoff), t=53.4 (final).

- **Ghost captions: GONE.** The V10 frames show baked footer text behind
  the active caption in every shot; the V11 frames show exactly one caption
  state, in the band below the card, with the plate footer fully readable
  inside the card ("WHY SO SLIPPERY?", "BORN AT THE SURFACE" are now
  ordinary plate content, no collision). Caption-band text-mask probes at
  every state boundary: 0 hits in 35 probes.
- **SIGNAL: GONE.** End card reads "ALREADY WET" (payoff phrase), brand
  marker reads "SURFACE". Source scan: 0 hits across all drawable strings.
- **Canvas ownership: UP.** Card 192..1440 (65% of canvas height, labels
  intact — plates author content inside the central 57.6% visible band),
  continuation bands are tone-matched art extension (texture-verified),
  zero blur panels. Honest note: the stretched bottom continuation of
  B7's wide orange circle reads as a soft orange block in the lower-right
  (t=50/53.4) — cosmetic, no text duplication.
- **Captions: clean** at hook, escalation, payoff, final; accent underline
  on the active word; no stacked states anywhere.

## 3. Deviations / decisions / gaps

1. **ANTI_TEMPLATE mapping.** Component = editorial7 antitemplate verdict
   (structural fingerprint) only. The human-editor test (9 questions incl.
   payoff_70) is a reported diagnostic, not a component: its payoff miss
   (65.8<70, "memorable=False") was reviewed in V10_REPORT §8.5 as
   advisory-class while editorial8's semantic payoff gate passes the same
   property — double-gating one property with a conservative numeric would
   let a threshold veto what the semantic measure approves. The diagnostic
   remains visible in publish_gate.json, the qa8 report, and qa5's
   top-concerns list. No thresholds were changed.
2. **Story fix went one token beyond the end card.** The directive scopes
   the story edit to `end_card: "SIGNAL" → semantic word`, but the SAME
   string also renders as the brand marker (top-left, every shot) from
   `story.json`/`visual_bible.json`. Since the scan must not whitelist the
   token, the brand was changed to "SURFACE" (semantic, surface-layer is
   the story's core mechanism) and the end card to "ALREADY WET" (payoff
   phrase). Three story files touched; nothing else.
3. **Two false-P0s were root-caused and fixed, not suppressed:** (a)
   overlay_compliance's violation check still used the hardcoded
   1350..1520 safe-band constants → 21 false violations at the new band
   (fixed: active band via `_caption_band()`); (b) caption_qa's boundary
   probe snapped forward a frame onto the new state's first frame (fixed:
   anchor at `prev_t1 + 5 ms`). A third probe (post-boundary "old-box"
   stale check) was removed as false-positive-by-construction — adjacent
   states share the band rows, so old-vs-new text is not spatially
   separable without OCR; stale detection is carried by the off-state
   boundary frame + construction uniqueness.
4. **Caption timing shift ≤ 50 ms at cue boundaries** (state-machine
   off-gap). Narration audio untouched; word-timing estimation unchanged;
   sync feel preserved (word windows are length-weighted estimates, per
   V10 §6).
5. **Strict C > B > A not met on this story** (B = 0: planv8 attaches
   living explanatory events to every shot). Reported as a finding, not
   fixed by injecting structural events (do-not-fake rule).
6. **Occupancy is uniform per shot (0.8187).** The metric measures canvas
   ownership (card + header + caption zones); evidence rects sit inside the
   card and do not extend the union. In-card composition density is
   editorial7's coverage family, not this metric.
7. **Known gaps:** (a) no OCR dependency — in-card baked plate text is
   content by policy; the source scan covers all plan-drawn strings and the
   frame scan covers text outside declared zones, but glyphs inside the
   card are not read; (b) pre-existing quirk, untouched: an opening shot
   with `title: ""` swallows the brand-title fallback (empty string beats
   the default), so S01 draws no title; (c) the end-card "ALREADY WET"
   duplicates the in-card plate label on payoff frames — content-level
   echo, noted for the author; (d) QA pixel layers sample frames (35
   caption probes / 12 leak frames / 6 occupancy frames), not every frame —
   the construction layer is exhaustive, the pixel layer is statistical.

Rollback: `V11_CAPTION=0`, `V11_FULLBLEED=0`, `V11_GATES=0` (each
independent; V10 flags unchanged).

## 4a. V11 P1a — planner/visual grammar (2026-09-12)

Resumed a partial run (prior worker died on a provider billing error
~10 min in). Scope: Jade_todo_v11 P1 items 1, 2, 3, 4, 11 + P2. No
re-render (the follow-up QA run owns render validation).

### Per-item changes

**1. Visual contradiction engine — `engine/contradiction.py` (new,
reused as-authored) + `engine/planv8.py` hook.**
Story-level primitive declared on a beat:
`"contradiction": {viewer_thinks, actually, reveal_beat}`. `run(plan,
story)` checks the declaration is VISUALLY honored: the viewer-thinks
state must be shown on the declaring beat's shot (content-token overlap
≥1) and the actual state must be revealed on the reveal beat's shot
(overlap ≥2 AND a living explanatory event — reveal/isolate/flow/
fill_state/consequence; narration alone is not a reveal). Stamps
`s["v8"]["contradiction"]` on hook/reveal shots; report at
`v8["contradictions"]` with verdicts honored / declared_only /
missing_show / unresolved; malformed declarations surface as errors,
never silently dropped. ice_slippery: B1 "you are skating on solid ice"
→ B4 quasi-liquid reveal → **pass (honored)**.

**2. Visual surprise — `engine/surprise.py` (new, reused as-authored)
+ planv8 hook.**
Valid classes: MICROSCOPIC_ZOOM, HIDDEN_CROSS_SECTION,
IMPOSSIBLE_SCALE_TRANSITION, SPATIAL_REVEAL, BEFORE_AFTER,
CAUSAL_CHAIN_REVEAL, UNEXPECTED_TRANSFORMATION. Invalid (never count):
zoom, pan, number pop, decorative particle, generic transition.
Authored shot-level `"surprise": {class, evidence}` wins; undeclared
shots get one conservative inference (visual_mode map, then living
event + text lexicon) marked `inferred: true`. Report
`v8["surprise"]`: surprise_present (≥1 authored valid) / weak (only
inferred) / none. ice_slippery: authored MICROSCOPIC_ZOOM on S04 →
**surprise_present**.

**3. Brand ≠ visual vocabulary — `engine/visual_grammar.py` (extended)
+ `engine/planv5.py` topic_grammar path.**
`grammar_for(subject, beat_function, topic_grammar=...)`: a story
bible's declared `"topic_grammar"` list overrides the inferred
SUBJECT_GRAMMAR and is reported as
`visual_grammar_plan.topic_grammar_declared`. Added geography +
astronomy entries to SUBJECT_GRAMMAR/SUBJECT_HINTS per the directive
vocabulary table. Cross-topic motif reuse (P2, below) makes the
orange-circle/navy-strip/cream-panel recurrence visible. ice_slippery
bible declares `["CUTAWAY","MACRO_DETAIL","MOLECULAR_PROCESS","SCALE"]`
→ **declared and flowed to plan5**.

**4. Real 2.5D depth — `engine/depth.py` (new) + planv5 planner
tagging + planv8 hook.**
Every shot gets `depth_layers` (foreground/midground/background):
authored visual_plan `"depth": {layers}` wins, else a deterministic
mode→layers grammar (no randomization). planv8 classifies consecutive
shot-pair transitions: `revealing` (layer-set change + incoming shot
has a living explanatory event and is not decorative camera-only) vs
`decorative`. Blurred/stretched extension earns no credit — it is
already excluded by occupancy_qa at render QA, and A-class shots earn
no transition credit here. Stamps `s["v8"]["depth"]`; report
`v8["depth"]` verdict layered/flat. ice_slippery: authored microscopic
stack on S04, **layered, 5 revealing / 0 decorative transitions**.

**5. Story escalation (P1 §11) — `engine/planv8.py` escalation block
extended.**
Visual intensity ramp (existing V8 curve, verdict pass) is now joined
by an information-density ramp: living events per shot; density at the
reveal phase must be ≥ the pre-reveal mean (`density_verdict: ramps`).
PHASE_MAP unchanged (no TWIST phase exists; ice_slippery signals the
ramp with ESCALATION beats — 0.78). ice_slippery: density [2,2,3,4,4,3,4],
pre-reveal mean 2.0 → reveal 3 → **ramps**.

**6. P2 anti-template / cross-topic motif reuse —
`engine/antitemplate.py` (motif section added in-window) wired through
`engine/planv7.py` + `engine/editorial7.py`.**
Motif fingerprint = primitive-family × palette-role counts from plate
authoring (AST scan of make_cards.py: ellipse/rectangle/
rounded_rectangle/polygon + fill colour role) and plan-drawn primitives
(overlay/living event kinds → families). `compare_motifs` skips
same-subject signatures; a close motif mix (cosine ≥ 0.65) on a
DIFFERENT subject is `motif_recurrence` unless the story declares a
semantic `motif_justification`. No layout randomization — variation
comes from story/subject/mechanism/grammar/information structure.
ice_slippery: `no_comparable_history` (recent signatures predate motif
data).

### §4a-notes — reused vs rewritten vs fixed

- **Reused as-authored:** `contradiction.py`, `surprise.py`,
  `visual_grammar.py` topic_grammar changes, planv5/planv8 hooks from
  the partial run — verified by import + unit run + full pipeline, then
  kept.
- **Fixed (broken partial work):** `engine/planv7.py`
  `_anti_template_adapt` referenced an undefined `story` after the
  in-window motif wiring — NameError killed plan7/plan8. Fixed by
  loading story.json inside the guard.
- **Rewritten/added this session:** planv5 authored `surprise`/`depth`
  passthrough (planv4 rebuilds shots with a field whitelist and was
  silently dropping the authored surprise dict); depth.run moved after
  planv8's motion re-tag (provisional A-tags misclassified C-shot
  transitions as decorative); escalation density ramp (item 5 was not
  started); ice_slippery example fields; this report section.
- planv7.py and editorial7.py carry the motif wiring but remain
  untracked like the rest of the V7-era stack (planv8 already imported
  untracked planv7 at HEAD); `antitemplate.py` IS committed as the P2
  deliverable. Commit scope: contradiction/surprise/depth/
  visual_grammar/antitemplate + planv5/planv8 + ice_slippery example +
  this report.
- Verification: plan5 → plan7 → plan8 run clean on ice_slippery; all 61
  engine modules import (incl. caption_qa, leak_scan, occupancy_qa,
  motion_class, publish_gate). Pipeline verification only — no re-render
  (follow-up QA run owns render validation).

## 4b. V11 P1b — editorial gates + audio hierarchy (2026-09-12)

Scope: Jade_todo_v11 P1 items 5-10 (TTS benchmark excluded — separate
stage). Built on the P1a modules (contradiction/surprise/visual_grammar/
depth/antitemplate, HEAD 1f54eb2). planv7.py stays untracked-as-was.

### Per-item changes

**5. Adaptive caption placement — `engine/caption_place.py` (new) +
`captions.py`/`composev5.py`/`caption_qa.py`/`qa5.py`.**
Per-shot detection: evidence/label/arrow rects (events, v8 states,
key_number), header chrome (brand block/tag/title overlay/end-card at
frame y 64..184), evidence-mass thirds + dominant focal rect. Candidate
zones (9:16): `below_card` (default, faces the card's bottom edge),
`below_card_low` (retreat slot), `top_band` (faces the card's top edge).
Deterministic scoring: evidence mass in the zone's facing third, focal
proximity (<44px), chrome occupancy, default bias; an authored
`shot["caption_zone"]` wins outright. Both caption paths (kinetic +
legacy) anchor on the chosen zone; cap_state.json + overlay report
record the per-shot zone; caption_qa carrier boxes AND pixel probes
follow the shot's own band; new P0 rule `evidence_collision` (caption
box ∩ evidence rect). qa5's `_caption_safe_zone` reads the per-shot
bands. **Found + fixed a latent P0-era divergence:** the global report
band was 1464..1634 while the carrier rendered 1464..1656 —
`_caption_band()` now spans KIN_CAP_H exactly. ice_slippery result:
all 7 shots resolve to `below_card` — the detector ran per shot
(S01: below_card 0.45 vs low 0.55 vs top 6.35), but every shot carries
header chrome (tag/title/end-card) blocking the top band and no
bottom-edge evidence mass, so the default is genuinely the cleanest
zone everywhere (`placement_varies: false` — honest outcome, not a
stub: synthetic bottom-heavy geometry flips to below_card_low, authored
overrides flip to top_band). Frame checks: labels legible, captions
never touch card content.

**6. Scientific nuance QA — `engine/nuance.py` (new) + semantic_qa
wiring.** Six classes (ESTABLISHED..UNCERTAIN); authored facts.json
`nuance.classification` wins, conservative lexicon fallback; contested
classes (SUPPORTED_BUT_COMPLEX / ACTIVE_DEBATE / MODEL_DEPENDENT /
UNCERTAIN) narrated WITHOUT a wording qualifier are a FAIL carrying a
deterministic suggested wording. Source existence is explicitly
insufficient. `SEMANTIC_PASS` now includes `nuance_qualification` (P0
semantics via the FACTUAL component). Report: `build/qa/nuance_<story>.json`.
ice_slippery reference updates (documented): facts.json nuance —
pressure myth ESTABLISHED, quasi-liquid + friction heat STRONG_CONSENSUS,
slippery-principle + film-vs-temperature SUPPORTED_BUT_COMPLEX; story
narration hedges — B6 "tends to thin", B7 "The current picture: …".
**Known gap:** beat_B6/B7 wavs still carry the OLD wording (TTS stage
owns regeneration) — on-screen captions show the qualified wording.

**7. Viewer value density — `engine/value_density.py` (new).** ~5s
intervals; value = 2×counted semantic event (placed in the window where
it fires) + opens/resolves + narration novelty (new content tokens vs
everything seen); penalties for decorative motion (C-class, no events),
generic hero plates, repeated diagrams/assets, redundant labels, filler
narration, repeated information (novelty <1/3). A shot spanning several
windows contributes to every one it occupies. Gate: mean ≥0.6 AND weak
share ≤25%. ice_slippery: mean 4.79, 0 weak intervals, 11/11 ok/strong.

**8. Scroll-stop test — `engine/scroll_stop.py` (new).** The directive's
exact checkpoints 0.5/2/5/10/20/30/final-3s. Severity: MAJOR = {0.5
subject, 2.0 reason-to-continue, 10s concrete learning, final payoff}
(promise-breaking → publication-blocking), MINOR = {5s question open,
20s escalation, 30s mental-model} (pacing quality). Wired into
editorial8 gates + publish_gate VIEWER_SIMULATION; MAJOR failures are
named P0 defects (`scroll_stop:<checkpoint>`). ice_slippery: 7/7 pass.

**9. Audio hierarchy — planv5 + audio_mix + composev5 +
`engine/audio_qa.py` (new).** Plan default is now DELIBERATE SILENCE:
the auto `bed*.wav` pickup is gone — a bed exists only when story.json
declares `audio.bed` (authored per-story bed plans still win, flagged
`authored`). Mix enforces NARRATION > intentional SFX: the SFX stem
sidechain-ducks under narration (gentle 2:1 @ -30dB; new bed-free
narration+sfx graph branch + V9 path). V10_PUNCT risers now fit only
the narration pad gap — ice_slippery's 0.4s pad < 0.45s minimum, so all
risers drop (silence stays silent); sub-drop kept (transient, ducked).
V9 procedural underscore becomes an ACCENT (gain zeroed outside
escalation/reveal/payoff; ambience omitted unless a bed is declared).
QA: speech-to-bed ratio, 30-80Hz tonal noise in the quietest windows,
continuous-bed coverage (>70% fails unless authored), unnecessary
ambience (bed-only spans), SFX/narration masking (transients tolerated;
sustained overlaps fail unless the mix ducks SFX), dynamic range (LRA
2..18). Wired into qa8full + publish_gate AUDIO (P0 on the
continuous-bed default). voices.yaml / src/providers / TTS code
untouched. Master: -14.16 LUFS / -1.46 dBTP (target -14/-1.5).

**10. Performance plan — `engine/planv8.py`.** SURPRISE phase added to
PHASE_MAP (0.85); DELIVERY_BY_PHASE: hook immediate/curious,
orientation steady, discovery controlled, escalation building/tense,
surprise pause+emphasis (longer holds, 5 emphasis words), reveal
slower/weighty, payoff confident/resolved. Every beat carries
pace/energy/emphasis/pause/arc/delivery/tone; plan-level
`v8.performance_plan` report + variation check (distinct
(pace,energy,delivery,arc) signatures). Gate in editorial8
(`performance_plan` = complete AND varied). ice_slippery: 7 beats,
6 distinct signatures, varied+complete. TTS wiring stays at the TTS
stage (constraint honored).

## 5. Validation — full re-render + QA (delta vs P0/P1a)

Chain: plan5 → (TTS stub; existing beat wavs) → plan7 → plan8 →
render5 (force, two passes after fixes) → qa8full --v6. Flags
`…-v10v-v10k-v10d-v10p-v11c-v11f` confirmed. Duration 54.00s.

| Metric | P1b run | P0 run (§2) | Δ / note |
|---|---|---|---|
| TECHNICAL | PASS (first pass failed 91.67: caption_safe_zone saw the stale 1464..1634 band — root-caused, unified to KIN_CAP_H, re-ran) | 100.0 | fixed in-run |
| Caption safe zone | per-shot zones in overlay report; 23/23 captions in their shot's band; evidence_collisions=0 | global band | adaptive |
| FACTUAL (incl. nuance) | PASS — deterministic + nuance_qualification (5 claims classified: 1 EST, 2 SC, 2 SBC; contested 2/2 qualified) | PASS (no nuance) | stricter |
| CAPTION | PASS — 0 construction defects, pixels clean | PASS | = |
| DEBUG_FREE | PASS | PASS | = |
| Occupancy | 0.819 meaningful (target 0.75) | 0.819 | = |
| Motion ratio | C=1.00 A=0.00 (C>A pass) | same | = |
| VIEWER_SIMULATION | PASS — incl. NEW value_density (mean 4.79, weak 0/11) + scroll_stop (7/7, 0 MAJOR) | PASS (5 checks) | stricter |
| ANTI_TEMPLATE | PASS | PASS | = |
| AUDIO | FAIL — audio_continuity + completion PASS, hierarchy QA FAILS on low-frequency tonal noise: 0.0641 max bin share (30-80Hz) in the quiet windows = the accent underscore's 55Hz pulse + payoff sub-drop landing in narration pauses (windows t=5/8/46/49/51s) | PASS (no hierarchy QA) | V11 rejects what V10 passed — honest finding |
| VISUAL_EVIDENCE | FAIL — subject recheck S02 votes UNVERIFIED×3: the external vision judge returned raw=None (API degraded during this run; an earlier same-day run FAIL-voted different shots S06/S07 — judge instability, not content). Manual frame inspection (subjframe_S06/S07 + f_8/25/50) confirms the contracts are depicted. NOT overridden. | PASS | infrastructure, reported |
| Editorial gates | 11/11 PASS (8 V8 + value_density + scroll_stop + performance_plan) — documentary | 8/8 | stricter |
| CAN_PUBLISH | **False** — AUDIO (tonal noise finding) + VISUAL_EVIDENCE (vision judge UNVERIFIED) | True | see above |

Frame checks (build/qa/frames_p1b/, t=2.4/8/17/25/33/40/50): exactly one
caption state per instant, always in the below-card band; plate labels
(PRESSURE/ICE/MELTWATER, QUASI-LIQUID LAYER/ICE LATTICE/BELOW FREEZING),
plate footers (THE CLASSIC ANSWER / THE SKIN OF WATER / BORN AT THE
SURFACE) and the end card (ALREADY WET) fully legible and never covered —
these are the coordinates the fixed V10 band collided with. No ghost
text. B7 caption carries the nuance hedge on-screen ("The current
picture: …").

Honest deltas: (1) AUDIO fails its new hierarchy QA — the accent
underscore's sub-bass pulse rings in narration pauses (0.0641 > 0.02);
fixing it means dropping the pulse or gating the accent lower — an
authoring/sound-design decision, surfaced not forced. (2) The vision
subject judge was unreachable at QA time (UNVERIFIED) — can_publish
stays False until a healthy judge run confirms; no threshold was moved.
(3) B6/B7 narration hedges await TTS regeneration (separate stage).
