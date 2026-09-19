# V7 Report — Editorial Intelligence & Anti-Template

**Date:** 2026-09-06 · **Brief:** `Jade_todo_v7.txt` · **Build plan:** `V7_PLAN.md` · **Prior:** `V6_cinematography_benchmark.md` §7–8 (bake-in)

---

## 1. Status

- V7 engine suite (visualclass, antitemplate, editorial7, planv7, semantic_qa + composev5 extensions) is **built and validated end-to-end** on three deliberately different stories: phone_heating (science_process), sahara_greening (geography), titanic_mistake (history).
- All three stories: **rendered and fully measured** (§2). The titanic render was invalidated mid-run by a build bug the QA numbers alone did not reveal — caught by the mandated actual-viewing pass, fixed at the root, re-rendered, and **verified genuine by frame inspection** (iceberg hook, six-compartment wound diagram, 2,200/705 count plate; 7 shots / 7 beats parity restored).
- Honest bottom line: **CAN_PUBLISH_V7 = False on every story.** That is the system working: the gates refuse to bless videos that still have real, viewer-visible problems (§3). The engine is done; the authoring needs a v2 pass (§6).

## 2. Results

| Gate / metric | phone_heating (science_process, 51.0s) | sahara_greening (geography, 60.7s) | titanic_mistake (history, 70.0s) |
|---|---|---|---|
| EVIDENCE | 100% | 100% | 100% |
| CINEMATIC | 0% | 0% | 0% |
| BREATHING | 0% (≤20 ✓) | 0% (≤20 ✓) | 0% (≤20 ✓) |
| Generic blur | 0% (≤10 ✓) | 0% (≤10 ✓) | 0% (≤10 ✓) |
| 2s hook | 100/100 | 100/100 | 100/100 |
| Information Transformation | 1.0 | 1.0 | 1.0 |
| Visual Redundancy | 49.4% (was 96.2%) | 41.2% | 60.0% |
| Conceptual Continuity | 1.0 | 1.0 | 1.0 |
| Ending Payoff | 65.4/100 | 57.3/100 | 52.3/100 |
| Anti-Template | acceptable | acceptable | acceptable |
| Semantic Factual QA | PASS | PASS | PASS |
| Key-number gate (P0) | FAIL (no figure shown) | FAIL (no figure shown) | **PASS** (2,200 / 705 on screen) |
| V6.2 TECHNICAL | 100.0 | 91.67 | 83.33 |
| V6.2 VISUAL | 83.43 | 81.28 | 91.2 |
| V6.2 EDITORIAL | 87.73 | 87.73 | 83.18 |
| V7 editorial verdict | FAIL: redundancy_25, payoff_70, human_editor | FAIL: same three | FAIL: same three (+ V6 duration 69.97s > 60s) |
| **CAN_PUBLISH_V7** | **False** | **False** | **False** |

Gate detail (all three): PASS `evidence_cinematic_80` (EVIDENCE 100%), `breathing_20`, `generic_blur_10`, `hook_70`, `its_share_50`, `continuity_50`, `anti_template`; FAIL `redundancy_25` (41–60% > 25%), `payoff_70`, `human_editor_gates` (S01 fails 4/8 editor questions — concrete claims on generic imagery). Titanic additionally fails V6 `duration_window` (69.97s vs 45–60s — the story is one beat too long) and `novelty` (4 gaps > 5s).

Baseline for comparison: the three V6 production videos measured **59–71% redundancy** at V7 build time (blackhole + mitochondria additionally flagged `template_clone`). phone_heating's own first-draft plan measured 96.2%; planv7 choreography events cut it to 49.4% (−46.8 pts) without touching the authoring.

## 3. Top 5 human-editor problems (from actual viewing — 27 frames across the three videos)

1. **Static diagram holds across consecutive narration beats.** phone: the power-split plate (THE LEAK) holds unchanged through *"a few percent of the charging"* → *"Fast charging pushes far more power through the same."* sahara: the drivers plate holds through *"Rains have come back to the Sahel…"* → *"so plants grow more with the same water."* It feels like slides exactly where the narration advances — the precise anti-pattern V7 targets. **Fix: state-variant cards** (arrows thicken, figures appear, heat circle grows between beats).
2. **The key number is spoken but never shown (phone, sahara).** "A few percent" never appears as an on-screen figure; sahara's 9.2M km² appears only as tiny label text. Titanic proves the fix works: its 2,200-vs-705 dot plate **passes** the P0 gate and is the most memorable frame in the three videos. Numbers are the stickiest element on a phone screen — every story needs its number plate. Related: the HERO plate B1 scored 0.57 < 0.60 on the role gate — the opening card is too generic for a hero.
3. **Abstract iconography where a recognizable shape is needed.** phone: heat is an orange blob engulfing the phone — a cold viewer may not parse it as heat. sahara: the map plate (white polygon + orange shapes) does not read as Africa. titanic: the opening represents the ship as an orange dome with floating hull icons — ambiguous at 1s glance. This costs instant comprehension at the hook, where it matters most.
4. **Labels clip / lose contrast.** sahara: "9.2 MILLION KM²" gets cut to "0.2 MILLION KM" at the frame edge during the pan. titanic: "2,200" and "705" sit over the dark-orange disk with weak contrast. Camera framing must respect label safe-zones, and key numbers need contrast treatment.
5. **Payoff under-callbacks the hook.** The final beat re-shows the opening visual nearly unchanged (sahara payoff ≈ opening map; the only difference is a "THE BRIGHTER FRINGE" chip) instead of transforming it with the resolved fact. Payoff scores 52–65 vs the 70 gate; hook_overlap 0.14–0.29. The receipt moment — the most memorable frame of the video — is currently the weakest.

## 4. What V7 proved

- **The gates catch real, visible-in-frames problems.** Every automated FAIL above maps to a concrete viewing observation in §3 — the QA measures viewer outcomes, not internal scores.
- **Redundancy is measurable and planner-reducible** (96.2% → 49.4% on phone via choreography events), but the remaining 41–60% is an **authoring ceiling**: only state-variant cards fix it. History (titanic, 60%) is the hardest case — its grammar is inherently sequential.
- **Story-driven grammar works:** three story_types produced three different shot grammars — science_process → cell interior / power split / thermal-limit chart chain; geography → map / timeline / rim-vs-core comparison; history → sinking cascade → wound diagram → casualty count.
- **Semantic Factual QA (deterministic rules): PASS** on all authored facts across all three stories. R4 exact-wording (LLM) skipped — DeepSeek key returns HTTP 401.
- **Hook construction** (2s opening proof + curiosity gap + declared payoff) hit **100/100 on all three**.
- **V6.2 foundations held:** audio bed, motion, caption-fit, plate-continuity gates all pass on every render.
- **The key-number gate is a real differentiator:** titanic passes it, phone/sahara fail it — and the passing frame is the strongest of the nine inspected. That is exactly the "optimize for real-viewer outcomes" behavior the brief asked for.

## 5. Build findings & fixes

- **CRITICAL — shared-plan clobber (found by the viewing pass, not by QA):** the first `titanic_mistake.mp4` contained **sahara content**. Root cause: every planner writes the shared `build/edit_plan.json`; `plan7` ran for titanic then sahara back-to-back before either rendered, sahara's plan clobbered titanic's, and `render5 --story titanic_mistake` rendered sahara's plan. Tells: identical 41.2% redundancy between the "titanic" and sahara QA, "6 shots vs 7 beats", sahara visuals under titanic's hook text. **Fix shipped 2026-09-06:** `plan7` now writes a per-story snapshot (`build/edit_plan_<story>.json`); `render5` and `qa5full` restore the story's own plan before running (guard line printed in logs). Re-render verified genuine by frame inspection + 7/7 shot-beat parity.
- **Title overlay:** the ffmpeg-side title-fade filter chain is rejected ("Error initializing complex filters: Invalid argument") — overlay disabled in composev5 for V7 stories (documented limitation; the opening card carries the hook).
- **DeepSeek 401:** R4 exact-wording check skipped; deterministic rules still gate. Key refresh needed.
- **V6 P0 `phone_readability` vs V7 qualitative authoring:** "a few percent" is honest wording, but the gate demands an on-screen key number. Titanic shows the two are compatible — treat it as an authoring requirement, not a gate bug.

## 6. Authoring recommendations (v2 path)

1. State-variant cards for every static hold ≥5s — kills the remaining redundancy.
2. Put the key number on hero/split cards with contrast treatment (titanic's count plate is the template).
3. Recognizable-shape revision: a legible heat cue on the phone; a real Africa outline for sahara; a ship silhouette, not a dome, for titanic.
4. Label safe-zones under camera framing.
5. Payoff receipt beat: transform the opening visual with the resolved fact, echoing the hook's wording.
6. Trim titanic by one beat (~10s) to fit the 45–60s window.
7. Refresh the DeepSeek key so R4 exact-wording runs.

## 7. Honesty statement

Per the brief: not optimizing internal scores. Each FAIL above maps to a defect visible in the frames (§3); the v2 authoring pass above is the path to CAN_PUBLISH_V7 = True. The test asked: *would a real person stop scrolling, understand, remember, and finish?* The current answers are "closer, but not yet" — and now they are measured, visible, and fixable.
