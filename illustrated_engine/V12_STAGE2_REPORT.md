# V12 Stage 2 — P1 upgrades (report)

Branch `illustrated-engine`, base `bc578db` (Stage 1). Directive: `Jade_todo_v12.txt`
§P1 (7 items). No new 4K renders; QA suite re-run on existing artifacts
(three V11 stress stories + ice_slippery smoke render). Judge transport in
`engine/director.py` untouched; thresholds/keys unchanged.

## Modules + commits (in order)
1. `d237622` **engine/planv9.py** — claim confidence wired into the beat model.
   Every beat carries `claim_confidence` + `claim_ids` (facts.json
   `nuance.classification`; conservative lexicon fallback when unauthored).
   A beat narrating several claims takes the MOST contested class. Contested
   claims (SUPPORTED_BUT_COMPLEX..UNCERTAIN) can never use a definitive
   mechanism transform (`cause_to_consequence` / `mechanism_visible` /
   `object_transforms`) — downgraded to `hypothesis_branches`, recorded as
   `confidence_override` (never silent). VERIFIED: ice B1 ("ice is slippery
   because…", SUPPORTED_BUT_COMPLEX) object_transforms → hypothesis_branches;
   ice B4 (quasi-liquid layer, STRONG_CONSENSUS) keeps mechanism_visible.
2. `5edf0d1` **engine/motion_class.py** — INFO_GAIN_CADENCE: every 4 s window
   must contain a meaningful new relationship from the directive vocabulary
   (cause/consequence/scale/location/mechanism/comparison/process/
   uncertainty/evidence), derived from planv9 beat `state_transformation`
   (counted once per beat) + v8 events at authored times. Camera-only
   (A-class, no events) shots never count as gain. Negative control: 9s/7s
   camera-only shots → verdict `sparse`, 8 s gap flagged. All four story
   plans: coverage 1.0, verdict ok.
3. `(depth commit)` **engine/depth.py** — informational depth intents.
   Vocabulary: camera_entering_object / layer_separation /
   internal_layer_reveal / scale_transition / spatial_reconstruction /
   parallax_geometry. Authored `depth.intent` wins; deterministic
   mode→intent map otherwise; multi-plane fallback classified by events.
   Blurred-background-only depth (background plane, no foreground, no info
   event) FAILS QA (`informational_pass=False`). ice/baikal replanned plans:
   pass, no blurred-only shots; synthetic map-with-camera-only plan fails.
4. `(caption commit)` **engine/caption_place.py** — caption hierarchy:
   A narration captions / B semantic labels / C decorative text (title, tag,
   end-card; title_overlay inventoried but flagged as a disabled render
   path). Checks: narration cues max 2 lines (mirrors captions._cue_lines),
   competing text layers (B label inside an active A cue window; C chrome
   while narration on screen), per-kit caption zone respected
   (edge_band→below_card, top_band→top_band, in_scene→below_card).
   HONEST FINDING: all four plans carry C chrome on 7/7 shots (C_share=1.0,
   verdict `c_heavy`, 6 findings each) — the V11 per-shot tag chip is
   exactly the "text chrome" the directive wants minimized (Stage 3).
5. `(value commit)` **engine/value_density.py** — two fixes: the decorative
   penalty used class C (explanatory!) — corrected to A per planv5's
   `_motion_class` convention; added the missing generic_transition penalty
   (cut into a shot with same visual mode, no living event, camera-only).
   Directive penalty list now complete. Synthetic check fires both; the four
   real plans stay clean (mean 4.67–5.18, gate True) — no score changes.
6. `5a2b61a` **engine/nuance.py + engine/semantic_qa.py** — the big one.
   `evidence_support(story, facts, plan)`: from "is the statement true?" to
   "does visual+narration imply MORE than the evidence supports?" Ten
   deterministic checks per claim-carrier sentence: object, number,
   timeframe, geography (uniformity / global-mean without "on average"),
   population/scope quantifier strengthening, causal strength (unqualified
   causal verbs on contested claims = FAIL), certainty adverbs on contested
   claims (FAIL), perspective fused into causal assertions, comparison
   denominator (fraction noun-phrase must keep the claim's own denominator
   words), superlative qualification (ranged evidence, bare narration
   superlative). Plus `process_conflation` (directive autumn fixture:
   extraction verb + nutrient object in a contested claim's sentence →
   WARN "related but DISTINCT processes"). Plan-aware: contested claim
   drawn as definitive mechanism in the plan snapshot → FAIL
   (planv9 downgrades this; legacy plans would flag it).
   `verify()` reports the `evidence_support` gate (FAIL-severity blocks);
   WARN findings are advisory with suggested wording. SEMANTIC_PASS
   previously-False stories (baikal/tambora/autumn nuance_qualification)
   are unchanged — pre-existing V11 gate state, no regression.
7. `(audio commit)` **engine/audio_qa.py** — LOW_FREQ_TONALITY discrimination.
   The 0.02 narration-silence rule is BYTE-UNCHANGED (30–80 Hz quiet-window
   scan). New stem-level FFT classification (building on the V11 P1b-fix
   approach): narration_harmonics (window overlaps narration span or peak
   matches the narration stem's spectral peaks) / intentional_tonal_bed
   (peak matches a declared bed stem's peaks ±2 Hz) / electrical_hum
   (50/60 Hz harmonic series ±1.5 Hz) / repetitive_synthetic_tone (stable
   peak matching nothing). Finding details now name the class. Added
   `silence_usage` (sub-floor share + longest span; informational). Synthetic
   3-tone master discriminates all classes; ice master classifies
   narration_harmonics (peaks 138–165 Hz ≈ voice fundamentals).
8. `(scroll commit)` **engine/scroll_stop.py** — directive checkpoint mapping
   verified EXACT (docstring): 0.5→t0.5_what_am_i_seeing, 2→t2_why_continue,
   5→t5_question_open, 10→t10_learned_concrete, 20→t20_escalated,
   30→t30_model_changed, final→final_payoff. No gaps, no duplicates; the
   V12-P0 t1_subject_visible checkpoint strengthens without duplicating.

## Semantic-QA fixture demo (before → after)
- BAIKAL: raw "One lake holds 20% of Earth's freshwater." →
  `denominator_or_object_unqualified` WARN, suggested wording
  "about … of Earth's fresh/surface/unfrozen/water" (= directive's
  "about 20% of Earth's unfrozen/surface freshwater"). Current narration
  ("roughly one fifth of all the unfrozen fresh surface water") passes.
- AUTUMN: conflated "The anthocyanin strips out nitrogen as the leaf dies."
  → `process_conflation` WARN (distinct-processes wording). Current B5
  ("red works as a sunscreen while the tree strips out nitrogen") also
  flags WARN — honest: the single-breath juxtaposition still invites the
  conflation reading the directive forbids.
- TAMBORA: "The world cooled by roughly half a degree." →
  `geographic_uniformity` WARN, suggested "on average, …" (global mean ≠
  uniform field). The exaggerated "…half a degree everywhere." also flags.
- ice_slippery: 0 findings (the qualified "The current picture: … because"
  frame keeps its causal verb honest).

## Audio numbers from existing masters
| story | 30–80 Hz max share (thr 0.02) | dominant class | speech/bed | silence share / longest | LRA |
|---|---|---|---|---|---|
| ice (smoke render, planv9) | 0.0022 | narration_harmonics | bed-free (null) | 0.009 / 0.5 s | null* |
| baikal (4K render audio) | 0.0183 | narration_harmonics | n/a** | — | — |
| tambora (4K render audio) | 0.0030 | narration_harmonics | n/a** | — | — |
| autumn (4K render audio) | 0.0016 | intentional_tonal_bed | n/a** | — | — |

\* ffmpeg loudnorm LRA parse returned None on the smoke master (pre-existing).
\** per-story bed plans/sfx timings are not persisted for the old renders
(gap, below); classification ran with each story's persisted bed asset as
reference (autumn's 82/123/164 Hz bed fundamentals match 3 quiet windows;
6 stable unmatched tones reported honestly as synthetic_tone rows, all
sub-threshold). qa8full on ice: all audio hierarchy checks PASS.

## Verification runs on existing artifacts
- Battery (plan + story + facts on disk): motion C-share 1.0 / cadence ok on
  all four; depth informational_pass all four; captions c_heavy 7/7 shots
  (finding); value gate True; scroll-stop pass (with real payoff verdict)
  except tambora `final_payoff` (pre-existing payoff "partial" on the legacy
  plan).
- qa8full --story ice_slippery end-to-end: V8 editorial PASS, semantic
  (incl. new evidence_support gate) PASS, CROSS_VIDEO_TEMPLATE PASS,
  motion C-share 1.00; CAN_PUBLISH=False on pre-existing render-level
  defects (motion_tremble, audio_continuity, caption render-QA findings).
- Stage-1 negative control REPRODUCED exactly: pre-V12 planv8 plans
  autumn/tambora d=0.127, ice/baikal d=0.096, ice/tambora d=0.137 —
  same_video on all pairs; replanned ice(scale_descent) vs baikal(map_first)
  d=0.494 distinct. No regression from Stage 2.

## No new render
Stage 2 changed plan-time annotation (planv9 confidence), QA logic, and
reports — no render-path code. plan9 regeneration proven end-to-end
(ice/baikal/autumn snapshots rewritten with the v12s2 beat model);
qa8full re-run on the existing ice smoke render proves the QA suite wiring.
The conditional low-res render (directive allowance) is therefore not spent.

## Gaps / deferred
- Caption findings (C chrome on every shot, tag+narration competition) are
  authoring/compose work for Stage 3 — the QA now names them; scores not
  optimized away.
- `caption_hierarchy` and `INFO_GAIN_CADENCE` are reported in module reports
  (motion_class_*.json contains the cadence; caption hierarchy callable);
  folding them into publish_gate components is a Stage-3 gate decision once
  narrations/plans are re-authored.
- Per-story bed plans + SFX timings for the old 4K renders are not persisted
  (only build/audio_bed_plan.json of the last render) — full speech/bed and
  SFX-mask re-runs on old stories need that provenance; classification and
  silence metrics ran on the extracted master audio regardless.
- title_overlay is a disabled render path; inventoried as declared chrome,
  excluded from competing-layer findings.
- Semantic judge (R4 exact-wording) skipped honestly: no judge key in this
  environment; deterministic implication checks are key-free.
