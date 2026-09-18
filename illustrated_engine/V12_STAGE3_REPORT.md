# V12 STAGE 3 REPORT — Stress Stories 4–6 + Combined 6-Story Acceptance Test

_Stage 3b, 2026-09-18. Branch `illustrated-engine`. Corpus: 3 Stage-3a stories (microwave_dielectric / tunguska_1908 / atacama_fog_oases) + 3 Stage-3b stories authored and rendered this pass (fever_thermostat / crumple_zones / seawater_drop). HEAD after 3b: see `git log --oneline -6`._

## 0. Order-of-work item: the systematic frame_text_outside_zones leak (fixed BEFORE story 4)

**Root cause (scanner logic, not render, not content):** `engine/leak_scan.py::_text_zones()` declared only the *default* caption band (`captions.band_rect()` = below-card 1464..1656). But `composev5` has placed captions per-shot via `caption_place.choose_zone` since V11 P1 §5 — candidates `below_card` (1464..1656), `below_card_low` retreat (1704..1896) and `top_band` (12..204). Every video with a non-default caption zone had its **own engine-drawn captions** flagged as "glyph-like pixels outside declared text zones". Evidence: microwave_dielectric S06 leak clusters sat at y1774..1818 — exactly the `below_card_low` carrier text rows; S05 used `top_band`; atacama's hits dropped to zero once all candidate zones were declared.

**Fix (commit e2d5d36):** leak_scan now declares **every** `caption_place` candidate zone. Detection itself (median-diff glyph mask, row clustering, dev-token source scan, severity) unchanged — no threshold touched. Post-fix: microwave 2→0 hits, atacama 2→0, crumple 0.

**Content-driven residue (documented, NOT silenced):** tunguska_1908 retains 2 frame hits, fever_thermostat 1, seawater_drop 3 — all the same signature: a static (frame-identical at multiple timestamps) 2-row spike at exactly y=1440..1455 — the card-bottom continuation-band seam of the V11 full-bleed canvas, plus faint plate texture. It is not text and not metadata; the scan honestly reports the seam as glyph-like. This is a scanner-vs-fullbleed-art false positive and stays a finding for the owner. No re-renders of stories 1–3 were made.

**Second authoring fix found in QA:** `key_number_rect` authored at y=0.16 sat inside the card header exclusion zone (HEADER_Y=0.18) → `overlay_compliance` P0 on fever. Fixed to y=0.20 in all three 3b stories before their renders; fever re-rendered and overlay_compliance = 100 (0 violations). Crumple/seawater never inherited it.

## 1. The six stress stories

| # | story | grammar (kit background) | brand | duration | facts posture |
|---|-------|--------------------------|-------|----------|---------------|
| 1 | microwave_dielectric | mechanism_flow (edge_to_edge_dark) | FIELD LINES | 83.0 s | 7 claims: 6 ESTABLISHED, 1 hedged range |
| 2 | tunguska_1908 | timeline_band (era_field) | (3a) | 80.1 s | established + hedged |
| 3 | atacama_fog_oases | map_first (terrain_field) | (3a) | 82.0 s | established + hedged |
| 4 | fever_thermostat | cutaway_reveal (blood-warm dark field) | INNER CLIMATE | 76.1 s | 7 claims: 6 ESTABLISHED, 1 ACTIVE_DEBATE (fever benefit) |
| 5 | crumple_zones | before_after (split_field hinge) | CRASH PHYSICS | 77.7 s | 7 claims: all ESTABLISHED |
| 6 | seawater_drop | scale_descent (depth_gradient) | ONE DROP | 84.8 s | 6 claims: 4 ESTABLISHED, 2 SUPPORTED_BUT_COMPLEX (viral shunt, diatom share) |

New kit painters added to `stories/_v12_kitlib.py`: `split_field` (before_after hinge) and `depth_gradient` (scale_descent surface-to-abyss). No grid paper, no parchment, no baked chrome anywhere.

## 2. Per-story gate verdicts + headline metrics

| metric | microwave | tunguska | atacama | fever | crumple | seawater |
|---|---|---|---|---|---|---|
| TECHNICAL | F(overlay→fixed at authoring; pre-fix render) | F | F | F(overlaid→**PASS** after re-render) | F | F |
| FACTUAL | P | F | P | **P** | **P** | F (1 R3 wording) |
| CAPTION | P | P | P | **P** | **P** | F (S07 state machine) |
| DEBUG_FREE (leak) | P (post-fix) | F (2 seam) | P (post-fix) | F (1 seam) | **P (0)** | F (3 seam) |
| VISUAL_EVIDENCE | F (judge outage) | F (judge outage) | F (judge outage) | F (judge outage) | F (judge outage) | F (judge outage) |
| VIEWER_SIMULATION | F (5/6) | F | F | F (5/6) | **P (6/6)** | **P (6/6)** |
| ANTI_TEMPLATE | P | P | P | P | P | P |
| CROSS_VIDEO_TEMPLATE | P | P | P | P | P | P |
| AUDIO | P | P | P | P | P | P |
| occupancy meaningful(major) | 0.819 | 0.819 | 0.819 | 0.819 | 0.819 | 0.819 |
| occupancy continuation | ok | ok | ok | ok | **bottom band 0.0036 < 0.004 floor** | ok |
| info-gain share (3 s windows) | 0.67 | 0.77 | 0.74 | 0.76 | 0.80 | 0.68 |
| motion C-share | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| value density (mean/window, gate) | pass | pass | pass | 3.77 pass | 3.95 pass | 3.72 pass |
| scroll-stop | pass | pass | pass | pass | pass | pass |
| hook (editorial7, /100) | — | — | — | 100 | 70 | 100 |
| payoff semantic | pass | pass | pass | pass | pass | pass |
| **CAN_PUBLISH** | **False** | **False** | **False** | **False** | **False** | **False** |

Notes:
- Fever TECHNICAL: the only technical P0 was `overlay_compliance` (key_number_rect in header exclusion), fixed at authoring and proven gone after the single re-render; everything else technical passed.
- Crumple is the only story with **DEBUG_FREE fully PASS** and **VIEWER_SIMULATION 6/6** post-leak-fix — evidence the scan fix works on a clean plate set.
- Seawater factual failure is a single deterministic R3 finding: B3 narration "the drop's architects **appear**" uses an observation verb needing a perspective qualifier. Honest wording gate; one-line narration fix + re-TTS would clear it — left as a finding per the one-QA-pass directive.
- Seawater caption failure: S07 (payoff ladder, 5 label chips) triggered `foreign_band_text` + `stale_caption` ×5 — the caption state machine colliding with the densest plate of the set. Authoring-level density finding, reported not tuned.
- Crumple occupancy: mean 0.819 (target 0.75) but continuation-verification bottom-edge density 0.0036 vs 0.004 floor — the split_field hinge leaves the bottom band marginally too quiet. Content finding.

## 3. Cross-video fingerprint matrix (v12 weighted structural distance)

All 15 pairs **distinct** (same-video threshold 0.30; clone threshold 0.45):

| d | MW | TUN | ATA | FEVER | CRUMPLE | SEA |
|---|---|---|---|---|---|---|
| MW | — | 0.537 | 0.577 | 0.427 | 0.549 | 0.558 |
| TUN | | — | 0.512 | 0.572 | 0.521 | 0.519 |
| ATA | | | — | 0.556 | 0.602 | 0.577 |
| FEVER | | | | — | 0.360 | 0.430 |
| CRUMPLE | | | | | — | 0.385 |
| SEA | | | | | | — |

Mean distance vs the other five: MW 0.530, TUN 0.532, ATA 0.576, FEVER 0.488, CRUMPLE 0.514, SEA 0.522. Closest pair in the corpus (fever↔crumple 0.360) is still well inside `distinct`; the three 3b grammars separate from every 3a grammar. Answer to the mute test: with narration off and nouns swapped, no pair reads as the same video — different background families (charcoal / sepia / terrain / blood-warm / hinge-split / depth-gradient), different composition verbs (flow / timeline / map / cutaway-dial / hinge-flip / descent-ladder), different label architectures.

## 4. The listed dimensions, covered

- **Technical QA** — per-story verdicts in §2. One systematic authoring defect (header-exclusion key_number) found and fixed pre-render for stories 5–6.
- **Factual QA** — FACTUAL pass on fever/crumple; microwave/atacama pass; tunguska F (3a, unaddressed by directive); seawater F (single R3 wording). All claims carry authored nuance classes (`facts.json`): contested claims (fever benefit, viral shunt) are hedged in narration and forced planv9 to non-definitive transforms (`hypothesis_branches` overrides on B5/B4).
- **Caption QA** — PASS everywhere except seawater S07 (state-machine collision with dense payoff plate). Caption architecture per grammar; adaptive placement (`below_card` / `below_card_low` / `top_band`) exercised on every story.
- **Debug leakage** — source layer: 0 hits in all six. Frame layer: 0 after the zone-declaration fix except the documented card-bottom seam false positive (tunguska 2, fever 1, seawater 3 — same y≈1440 signature; content-driven, stays a finding).
- **Canvas occupancy** — uniform 0.819 meaningful-major (target 0.75). Crumple continuation-verification flags a quiet bottom band; all others verified.
- **Visual information gain** — gain_share 0.67–0.80 (3 s windows).
- **Explanatory motion ratio** — C-share 1.00 everywhere (eased camera on explanatory diagrams), A=B=0.
- **Visual contradiction** — every story carries one authored contradiction with a reveal beat: MW shell-vs-core (B3), fever chills-vs-setpoint (B3), crumple rigid-vs-folded (B3), seawater empty-drop-vs-city (B3); planv9 reports `contradiction: honored` per story.
- **Visual surprise / hook quality** — hook scores 100/70/100 (fever/crumple/seawater); hook_plan first-subject ≤1 s, question by ~5 s, no black fade at 0.5 s.
- **Viewer value density** — mean 3.72–3.95 value/window, gate PASS on all six.
- **Payoff quality** — payoff_semantic PASS on all six; each closes on the opening question's image (dial-back frame, resolved hinge, full scale ladder).
- **Anti-template fingerprint** — verdict `diverse` on all six (editorial7) and per-pair `distinct` (§3).
- **Cross-video structural similarity** — no pair ≤0.36; closest pairs are the two new dark-field grammars vs microwave, as expected; still distinct.
- **Audio QA** — AUDIO component PASS on all six (speech/bed ratio, continuous bed, hierarchy); per-story SFX packs (whoosh/tick/pulse) synthesized deterministically.
- **TTS benchmark** — **no rerun** (per directive): see `V11_TTS_BENCH.md`. Headline: Chatterbox-turbo best pauses (554 ms mean longest) and narrator-cloning F0 79–83 Hz; nano 2× cheaper at equal quality; Kokoro fastest/cleanest but a voice change (out of mandate); Qwen3-TTS untested (gated). Production stays Fish `s2.1-pro-free` narrator per `configs/voices.yaml` (untouched). 3b narration totals: fever 73.3 s, crumple 74.9 s, seawater 82.0 s.
- **Human editor test** — §5.
- **CAN_PUBLISH** — all six **False** (§6).

## 5. HUMAN EDITOR TEST — 10 questions × 6 stories (owner scores from timecodes)

Directive: **fails on #1, #2, #3, #4, #8 or #9 block publish.** Score each Y/N per video.

| # | question | microwave | tunguska | atacama | fever | crumple | seawater |
|---|----------|-----------|----------|---------|-------|---------|----------|
| 1 | Documentary, not presentation? | 0:00–0:16 block interior | 0:00–0:12 forest aerial plates | 0:00–0:12 desert ridgeline | 0:00–0:10 body cutaway, shiver arcs | 0:00–0:10 hinge split nose | 0:00–0:12 droplet on sea surface |
| 2 | Recognizable generator with narration muted? | | | | | | |
| 3 | First 2 s stop you? | 0:00 wave arcs + cold core | 0:00 blast horizon | 0:00 fog ribbons | 0:00 core glow vs shiver marks | 0:00 intact-vs-crumpled hinge | 0:00 crowded droplet specks |
| 4 | The visual itself creates curiosity? | 0:10 dark core disc | 0:12 no-crater horizon | 0:14 green ribbons on brown | 0:10 lit hypothalamus dot | 0:12 hatched crush zone | 0:14 composition bar's living sliver |
| 5 | Something meaningful changes every few seconds? | C-motion + reveals; verify on 0:33 / 0:52 | | | reveals/pulses: 0:31 / 0:41 / 0:52 | fold stages 0:43 / staging 0:54 | burst 0:32 / ladder 1:02 |
| 6 | Visual explains narration? | 0:27 penetration fade | | | 0:22 cytokine flow → dial 39 | 0:33 two stop traces | 0:34 virus swarm + burst |
| 7 | Subject in its natural grammar? | field-flow ✓ | archival timeline ✓ | map ✓ | cutaway + dial ✓ | before/after hinge ✓ | scale descent ✓ |
| 8 | Story escalates? | 0:16→0:41→0:53 | | | 0:31→0:41→0:52 | 0:42→0:54 | 0:31→0:41→0:51 |
| 9 | Final visual resolves the opening? | 0:73 even warm gradient | 0:72 aftermath | 0:74 resolved map | 1:02 baseline dial + climb/descent arrows | 1:02 crumple beside intact cage | 1:01 full scale ladder |
| 10 | Human-directed, not template? | | | | | | |

_(empty cells = owner's judgment; timecodes are the payoff/reveal anchors to check against each question)._

## 6. Honest CAN_PUBLISH summary

| story | CAN_PUBLISH | blocking P0s |
|-------|-------------|--------------|
| microwave_dielectric | **FALSE** | subject UNVERIFIED (judge outage), viewer_simulation (5/6), leak fix post-dates its QA record (2 seam hits then; would be 0 now) |
| tunguska_1908 | **FALSE** | factual, subject UNVERIFIED ×3, viewer_simulation, 2 content-driven seam frame hits |
| atacama_fog_oases | **FALSE** | subject 7/7 UNVERIFIED, viewer_simulation, occupancy empty-row anomaly; (seam hits would be 0 post-fix) |
| fever_thermostat | **FALSE** | subject 7/7 UNVERIFIED (judge outage), viewer_simulation (5/6), 1 content-driven seam frame hit |
| crumple_zones | **FALSE** | subject 7/7 UNVERIFIED (judge outage), occupancy continuation bottom-band 0.0036<0.004 |
| seawater_drop | **FALSE** | subject 7/7 UNVERIFIED, factual R3 ("appear" needs hedge), caption S07 state-machine ×5, 3 content-driven seam frame hits |

**Cross-cutting findings for the owner (not tuned away):**

1. **Vision-judge outage (systematic, environmental):** every subject-evidence row on every story this pass recorded `UNVERIFIED` because the vision judge was unavailable at QA time. The gate records this honestly instead of hand-waving (`subject:no verified subject rows (7/7 UNVERIFIED — vision judge unavailable at QA time; gate not hand-waved)`). Until a judge run completes, VISUAL_EVIDENCE cannot pass on any story — that is the honest state, not a defect in the six videos.
2. **viewer_simulation (cross-story):** 5/6 on microwave/fever (and tunguska/atacama 3a), 6/6 on crumple/seawater. The marginal window differs per story; worth a single focused pass when the owner resumes.
3. **Card-bottom seam false positive:** the leak scan's glyph heuristic fires on the V11 full-bleed continuation seam at y≈1440..1455 on plates with content near the card bottom (tunguska, fever, seawater). Scanner-vs-art question, explicitly left open.
4. **editorial7 `evidence_cinematic_80` / `generic_blur_10` divergence:** the three 3b stories score 25–57% evidence windows vs 100% on 3a — the quiet kit backgrounds of the new grammars classify as breathing/blur windows. Reported, not tuned; may justify a grammar-aware breathing allowance later.

**Bottom line:** all six videos render, validate and are mutually distinct under the mute test; all six honestly fail CAN_PUBLISH, dominated by the environmental judge outage plus a short list of named, fixable content defects (one wording hedge, one dense payoff plate, one quiet bottom band, one seam false-positive question). No scores were tuned; every failure above is a finding with its evidence attached.
