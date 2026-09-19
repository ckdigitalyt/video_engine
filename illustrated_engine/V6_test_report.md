# V6 Test Report — 3 Fresh Videos (v2, post-fix)

Engine: V6 (subpixel Bézier camera + 2x stage + single downsample; 3-layer audio: narration / continuous bed / SFX with sidechain ducking).
All three rendered through plan5 -> render5 --force -> qa5full. Topics deliberately unrelated to test grammar generalization.

## v2 Fix Pass (2026-09-05)

First-cycle renders for `aircraft_wing_lift` and `mitochondria_dna` were byte-identical (sha256 match on all sampled frames at t=3/20/40) because all stories share `build/shots3/` with the same S01–S09 IDs, and `render_shot_v5` silently reuses existing mp4s when `--force` is not passed. Blackhole escaped only because its re-render had been force-flushed.

**Engine fix (composev5):** story isolation guard stamps `build/shots3/.story` with the story id and wipes stale shots on story change.
**Editorial fix (visual_plan patches):** concrete claim → concrete visual:
- aircraft S01: NUMBER_POP `400 T` over the wing hero (satisfies the "400 tonnes" number requirement that flagged generic_risk)
- mitochondria S04: NUMBER_POP `37 GENES` over the DNA-ring macro
- mitochondria S06: role promoted to DIAGRAM + NUMBER_POP `1.5 BYA` (DIAGRAM satisfies number + timeline reqs; the engulfment card is genuinely a schematic)

**Frame-distinctness proof:** sha256 of 9 sampled frames (3 stories × t=3/20/40) yields 9 unique hashes (v1: 3 unique — 6 duplicates).

## Per-video results (v2)

### AIRCRAFT — How a 747 Wing Actually Lifts

- Story: `aircraft_wing_lift` | Duration: 52.8s | Grammar: blueprint / structural diagram / cutaway grammar

| Metric | Result |
| --- | --- |
| Technical | 100.0 |
| Visual | 94.81 |
| Editorial | 95.91 |
| Factual | 100.0 (4 verified claims; uncovered=0) |
| Motion smoothness | jitter 100.0/100, reversals 100.0/100, bad shots: none |
| Audio continuity | continuous=True, score 100.0/100, 0 restarts |
| Information velocity | 100.0 |
| Narration/visual alignment | 100.0 |
| Information density | 92.7 |
| Phone QA | 100.0 |
| CAN_PUBLISH | **True** |

TOP 3 HUMAN-EDITOR CONCERNS:
- [VISUAL] style_continuity = 48 — mean=0.4815 min=0.4714 max=0.494
- [EDITORIAL] hook_strength = 55 — retention_ok=True opening=True first_dur=7.518

### BIOLOGY — Why Mitochondria Have Their Own DNA

- Story: `mitochondria_dna` | Duration: 54.4s | Grammar: cellular diagram / transformation grammar

| Metric | Result |
| --- | --- |
| Technical | 100.0 |
| Visual | 94.81 |
| Editorial | 100.0 |
| Factual | 100.0 (4 verified claims; uncovered=0) |
| Motion smoothness | jitter 100.0/100, reversals 100.0/100, bad shots: none |
| Audio continuity | continuous=True, score 100.0/100, 0 restarts |
| Information velocity | 93.3 |
| Narration/visual alignment | 88.9 |
| Information density | 92.7 |
| Phone QA | 100.0 |
| CAN_PUBLISH | **True** |

TOP 3 HUMAN-EDITOR CONCERNS:
- shot S09: failed 4/8 human-editor questions
- narration/visual gap in shots ['S09'] — concrete claims on generic imagery

### PHYSICS — Why Clocks Run Slower Near a Black Hole

- Story: `blackhole_clocks` | Duration: 51.7s | Grammar: scale / transformation grammar

| Metric | Result |
| --- | --- |
| Technical | 100.0 |
| Visual | 93.69 |
| Editorial | 100.0 |
| Factual | 100.0 (4 verified claims; uncovered=0) |
| Motion smoothness | jitter 100.0/100, reversals 100.0/100, bad shots: none |
| Audio continuity | continuous=True, score 100.0/100, 0 restarts |
| Information velocity | 100.0 |
| Narration/visual alignment | 100.0 |
| Information density | 92.7 |
| Phone QA | 100.0 |
| CAN_PUBLISH | **True** |

TOP 3 HUMAN-EDITOR CONCERNS:
- [VISUAL] style_continuity = 48 — mean=0.4803 min=0.4611 max=0.4942
- [VISUAL] role_threshold_audit = 89 — B1_bh_hero(HERO) 0.57<0.6

## Verdict (v2)

- V6 P0 motion + audio gates: **PASS on all three videos** (zero tremble, zero direction reversals, continuous ambience through every cut, narration dominant).
- All three videos now **CAN_PUBLISH = True**. Aircraft S01 and mitochondria S04/S06 issues are resolved (alignment 100 / 88.9). Mitochondria S09 still flagged at 4/8 editor questions but no longer a hard veto.
- style_continuity ~48 across all three: free-model plate variation; per brief P2 this is explicitly NOT to be chased at the cost of subject correctness.

## Engine changes exercised

- motion_v6: EASE_IO/EASE_OUT Bézier-zoompan at 2x stage, lanczos downsample, auto-HOLD for static shots
- motion_qa: 240-sample displacement/velocity/reversal analysis per shot
- audio_mix: single continuous bed (600ms crossfade on change), sidechain duck (thr -18dB, 6:1, att 20ms, rel 800ms), loudnorm -14 LUFS
- visual_grammar: subject detection per story (aircraft/biology/physics) drove mode selection
- qa5full: full V6 gate assembly incl. per-story snapshot
- composev5 v2: story-isolation guard (build/shots3/.story stamp + wipe on change)

---

# V6.2 Algorithmic Update — verification report (2026-09-05, post plate-fix)

All five directives implemented in the engine pipeline (composev5, planv5, visual_grammar, qa5). Zero manual plan/shot patches anywhere in the verification loop — every overlay decision is made by the compiler, every artifact by CAS. Chain: plan5 → render5 → qa5full × 3 stories.

## Directive verification

| Directive | Result |
|---|---|
| §1 Timeline & audio sync guard | PASS — final_duration = ceil(audio + 0.8s tail); `-shortest` removed; tpad clone-extension; qa5 `audio_completion` gate hard-fails CAN_PUBLISH on narration truncation |
| §2 Overlay anti-collision compiler | PASS — 0 violations on all stories; card-space standardization + header/footer exclusion zones; NUMBER_POPs duplicating plate text (HIGH/LOW, LIFT, 37 GENES, 2 MEMBRANES, DEEPER = SLOWER, 38) converted to kinetic pulses on the existing element; same-shot duplicate stamps suppressed |
| §3 Layout & canvas refactor | PASS — ambient blurred-card background (25px Gaussian + gradient) replaces the flat void; 100% of captions inside the y=1350–1520 safe band |
| §4 Kinetic vector primitives | PASS — blackhole S02 two-clocks (ω_near = 0.2·ω_far, REV counters); aircraft S05+S06 animated dash-offset streamlines (faster over the suction side); 15 fps procedural frames at 2× stage, HOLD camera |
| §5 Content-addressable storage | PASS — artifacts `<id>_<sha256(story+prompt+motion+kinetic+audio)[:16]>.mp4`; stale-artifact GC replaces the `.story` wipe hack (v2's isolation guard is retired); cross-story reuse structurally impossible |

## V6.2 per-story results (fresh renders, 2026-09-05)

### AIRCRAFT — How a 747 Wing Actually Lifts (56.9s)
- CAN_PUBLISH **True** — Technical 100.0 / Visual 95.0 / Editorial 95.91
- V6.2 gates: narration completes at 52.52s with **4.41s** margin before video EOF (stem tail −180 dBFS); overlay events=6, plate-pulses=3, dedup-suppressed=3, **violations=0**; captions **20/20** in band
- Subject gate: S01 PASS, remaining rows UNVERIFIED (vision model unavailable during QA) — **zero FAIL rows**
- Plate fix this cycle: after the 07:34 run FAILed S04/S06, both plates were made contract-true in `stories/aircraft_wing_lift/make_cards.py` — S04: 5 long suction arrows + 11 short push arrows thickened/lengthened, LOW/HIGH numerals moved clear of the arrow bands (they previously sat on top of the arrows); S06: engraved cambered airfoil section added beneath the streamline bundle (+18k dark-ink px in that region; no text labels added — forbidden by contract). Cards re-rendered (continuity gates pass: 0.680 / 0.643), stale CAS artifacts evicted, shots re-rendered, composite re-run.

### PHYSICS — Why Clocks Run Slower Near a Black Hole (56.0s)
- CAN_PUBLISH **True** — Technical 100.0 / Visual 93.9 / Editorial 100.0, alignment 100
- V6.2 gates: margin **4.49s**; violations=0; captions **23/23** in band

### BIOLOGY — Why Mitochondria Have Their Own DNA (58.0s)
- CAN_PUBLISH **True** — Technical 100.0 / Visual 94.85 / Editorial 100.0
- V6.2 gates: margin **3.79s**; violations=0 (2 plate-pulses, 2 suppressed); captions **19/19** in band

## Brief criteria — verified on rendered output
- **Zero text collisions:** `overlay_compliance` violations = 0 on all three stories.
- **Zero audio cutoffs:** `audio_completion` gate green on all three (margins 4.41 / 4.49 / 3.79 s; stem tails far below −45 dBFS).
- **Verified safe-zone compliance:** 20/20, 23/23, 19/19 captions inside the 1350–1520 band.
- **Frame distinctness:** 9/9 unique sha256 across the three outputs at t = 3/20/40 (re-verified on the final renders).

## Subject-gate health caveat (honest limitation)
The subject-correctness gate depends on vision-model availability, which is intermittent. In most QA windows the model was unavailable → rows UNVERIFIED (non-gating by design). In the one window it responded (07:07 UTC) it flagged 2 aircraft plates; both plates were then made contract-true and re-verified (pixel-level) — but a full 9/9 vision-PASS run has not been obtained. QA remains honest in both directions: FAILs gate, UNVERIFIED never silently passes as PASS.

## Verdict (V6.2)
- All three stories **CAN_PUBLISH = True** under the V6.2 gate set (strictly stronger than v2: audio-completion, overlay-compliance, caption-safe-zone and subject-recheck are all live P0 checks).
- The brief's three acceptance criteria (zero collisions, zero cutoffs, safe-zone compliance) are verified on rendered output.
