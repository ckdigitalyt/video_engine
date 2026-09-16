# V11 Stage 3 — Fresh-Story Stress Test (FINAL, 2026-09-16)

Branch `illustrated-engine` @ 0162395 + stage-3 commits. Three fresh, unrelated stories authored
from scratch (schema per ice_slippery) and pushed through the full production pipeline:
author (story/facts/bible/visual_plan/make_cards, all plates Pillow-drawn offline) → plan5 → TTS
(Fish s2.1-pro-free free tier) → plan7 → plan8 → render5 (4K) → qa8full --v6 (V11 gates on).

| story | topic | brand/grammar | dur | verdict |
|---|---|---|---|---|
| autumn_red | science/process — why autumn leaves turn red | CANOPY (botanical atlas) | 76.0s (1st pass) / 58.4s (redo cut, staged) | CAN_PUBLISH False |
| tambora_1816 | history/event — 1815 Tambora, Year Without a Summer | EPOCH (copperplate engraving) | 63.0s | CAN_PUBLISH False |
| baikal_deep | geography — Lake Baikal rift/volume | ABYSS (bathymetric chart) | 56.0s | CAN_PUBLISH False |

## Gate components (V11 publish gate, 8)

| component | autumn_red (1st) | tambora_1816 | baikal_deep |
|---|---|---|---|
| TECHNICAL | FAIL (76s>window; novelty) | FAIL (63.0s vs 62 cap — 1s) | **PASS** (56s, novelty 0 gaps) |
| FACTUAL | FAIL (R3 "seem to" + judges) | FAIL (judge-unavailable → semantic skipped) | FAIL (judge-unavailable) |
| CAPTION | PASS | PASS | FAIL (stale_caption S06) |
| DEBUG_FREE | FAIL ("SIGNAL" token FP in B6 line) | FAIL (frame glyph heuristic ×5) | FAIL (frame glyph heuristic) |
| VISUAL_EVIDENCE | FAIL (S01 subject misread; S05–07 UNVERIFIED) | FAIL (7/7 UNVERIFIED) | FAIL (7/7 UNVERIFIED) |
| VIEWER_SIMULATION | FAIL (no state action — sparse plan events) | FAIL (t30 intensity at floor) | FAIL (t30 intensity 0.62 = floor) |
| ANTI_TEMPLATE | **PASS** | **PASS** | **PASS** |
| AUDIO | **PASS** | **PASS** | **PASS** |

## Headline metrics

| metric | autumn_red | tambora_1816 | baikal_deep |
|---|---|---|---|
| canvas occupancy (mean meaningful-major) | 0.819 PASS | 0.819 PASS | 0.819 PASS |
| explanatory-motion C-share | 0.165 FAIL (A=0.84) | 1.00 PASS (hard C>A) | 1.00 PASS (hard C>A) |
| value density (5s windows, mean) | 1.49 (six P0 windows) | 4.67 | 5.17 |
| info-gain (3s windows w/ gain) | 0.125 (3/24, thin) | PASS gate | 0.824 (14/17) |
| scroll-stop | 5/7 (t10, final_payoff fail) | 6/7 (final_payoff fail) | **7/7** |
| audio: LF tonal-peak share (≤0.02) | 0.0016 PASS | 0.003 PASS | 0.0183 PASS |

## Findings (honest, with root causes)

1. **Vision-judge capacity is the binding constraint on fresh-story acceptance.** A's run verified
   S01–S04 then went UNVERIFIED mid-run (Gemini 429 → cooldown; GLM fallback also returned
   nothing); B's and C's runs got 7/7 UNVERIFIED ("vision judge unavailable at QA time; gate not
   hand-waved"). Publish gate correctly refuses to accept UNVERIFIED as PASS, so VISUAL_EVIDENCE
   and FACTUAL (R4) fail on evidence-absence, not on detected defects. A one-story-per-cooldown-
   window budget (or GLM vision repair) is required before fresh stories can pass honestly.
2. **Authoring bug found & fixed during the stage: relative paths in authored audio_bed_plan**
   crashed render5 at audio mux ("Error opening input … sfx_reveal.wav"). All authored plans must
   carry absolute sfx paths. Fixed for all three.
3. **Choreography needs declared plate elements.** planv7 only staggers events for shots whose
   plates declare `label(...)` elements parseable in make_cards source; my `lab()` wrapper was
   invisible to `_plate_manifest` → zero events → novelty FAIL, viewer_sim "begins at Nones",
   C-share 0.165. Declaring all plates (not just diagrams) in write_manifest + parseable
   `label(d, …)` calls took tambora/baikal to novelty PASS, C-share 1.00, info-gain 0.824.
4. **Duration discipline:** the 45–62s window is dominated by narration length. autumn_red 1st
   pass (76s) failed; tambora trim landed 1s over (63.0 — pad math: ceil(audio+0.8 tail) eats the
   authored pad); baikal (54.0s plan) passed. Redo cuts must budget ~2s of tail.
5. **t30 intensity floor:** viewer_sim requires intensity >0.62 at 30s; two stories sat exactly at
   the floor — v8 escalation stamping needs an explicit intensity step mid-story.
6. **DEBUG_FREE frame heuristic** flags plate LABELS as "glyph-like pixels outside declared text
   zones" (tambora ×5, baikal) — label text is on-plate, not declared as a plan text zone. Either
   plates must stop carrying labels (they are the subject evidence) or the scan needs the plate
   manifest rects as declared zones. Left as found (engine-side decision).
7. **Lexicon FP:** leak_scan tokenizes the word "SIGNAL" in legitimate narration ("a warning
   signal that keeps pests away") as a dev token. Reworded in the autumn redo.
8. **Semantics:** deterministic semantic QA passed for tambora/baikal as authored; autumn 1st
   pass failed R3 (perspective "seem to" without observer) — fixed in redo.
9. **Antitemplate cross-topic (dim 11):** all three "acceptable" (seq distance ≥0.4 floor;
   autumn 0.428, tambora 0.467 mean). Motif check reports "no_comparable_history" — the motif
   store has no botany/geography/history neighbors for these topics, so the closest-neighbor test
   is vacuous for fresh topics; ice_slippery's signature did not produce a cross-hit.
10. **Concurrent render5 runs corrupt each other** (shared build/ workspace: shots3, ov5, audio
    masters). Renders must stay serialized; one Stage-3 render had to be restarted.

## Dim 13 — TTS: cite V11_TTS_BENCH.md (Stage 2c, not rerun)

Advisory benchmark verdict: **"Keep Chatterbox Turbo as the narrator. No production change is
proposed by this benchmark."** Production remained on Fish s2.1-pro-free (free tier) for all
three Stage-3 stories; per-beat synthesis 5.3–8.6s/beat, zero 429s at ≥4s spacing with ≤2 retries.

## Dim 16 — CAN_PUBLISH

No fresh story reaches CAN_PUBLISH **primarily because the vision judge could not verify subject
evidence at QA time** (P0, honestly reported by the gate) plus a small set of concrete authoring
findings (duration discipline, t30 intensity, stale_caption S06). The technical, caption, audio,
anti-template, occupancy, motion-class, info-gain and scroll-stop machinery all demonstrably pass
on fresh material (baikal_deep passes TECHNICAL outright and 7/7 scroll-stop).

## Final question

**Would a human viewer mistake this for a deliberately produced premium YouTube documentary, or
does it still feel like an automated presentation?** — Honest answer: **it still feels like an
automated presentation**. The parchment/chart plates, kinetic captions, audio hierarchy and
information motion are genuinely good (baikal reads closest to a real explainer channel), but
the Pillow-drawn plates are visibly vector-flat at 4K, label typography repeats the same three
positions, escalation between beats is uneven (slideshow_risk verdict), and the ambient bed is
too sparse to carry documentary weight between narrated spans.
