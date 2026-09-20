# V13 GAP ANALYSIS — JADE RICH VISUAL DIRECTIVE vs V12 ENGINE

Date: 2026-09-20 · Repo `/home/ubuntu/video_engine` @ branch `illustrated-engine` (HEAD 711af23).
Method: read-only audit of directive items vs code + V12 stage reports. No code changed.
Directive: `docs/directives/JADE_V13_RICH_VISUAL_DIRECTIVE.md`.

## 1. Executive status table

| # | Directive item | Status | Primary evidence |
|---|----------------|--------|------------------|
| 1 | P0 Final-transform safe-area QA | **PARTIAL** | caption_qa.py:158 safe_zone; occupancy_qa.py:109,129; phone_qa.py:13 — no bbox-edge-clipping check after zoompan |
| 2 | P0 RICH_VISUAL_PLATE asset class | **MISSING** | All V12 plates deterministic PIL: `_v12_kitlib.py`, `_v6_cardlib.py`; AI plates only in legacy stories (fetch_plates.py) |
| 3 | P0 Hybrid visualization model | **PARTIAL** | composev5.py:208–269 full_bleed canvas + card overlays; plate = procedural background, no rich subject imagery |
| 4 | P0 Multi-stage image generation | **MISSING** | Single-pass text→img only: `src/providers/image_gen.py`, `engine/broker/providers/imageapi.py` |
| 5 | P0 Asset layer extraction (7 layers) | **MISSING** | Plates are flat PNGs; only renderer layers are card/ambient/captions (composev5) |
| 6 | P0 Depth-aware 2.5D | **PARTIAL** | depth.py = planner metadata + QA; motion_v6.py:341 parallax = damped blurred ambient, explicitly not content depth |
| 7 | P0 Story-specific visual modes (14) | **PARTIAL** | visual_grammar.py:99 22 modes ≈ diagram types; 7/14 directive modes map; modes select diagrams, not representations |
| 8 | P0 VISUAL_SOPHISTICATION | **MISSING** | No metric; nearest: occupancy edge-density, editorial7 ratios, value_density.py |
| 9 | P0 Full-canvas cinematic composition | **PARTIAL** | V12 full_bleed + 10 kits (canvas_grammar.py:81), panel_usage/chrome_density already kit-declared; composition varies by kit, not per-story art direction |
| 10 | P0 Hook (0.5s phenomenon / 2s contradiction) | **PARTIAL** | planv9.py:82–91 subject_visible_s default 1.0s; editorial8 viewer_simulation checks fade/0.5s; no phenomenon-first/contradiction-visual requirement |
| 11 | P0 Payoff causal-chain synthesis | **PARTIAL** | editorial8.py:62 payoff_semantic + PAYOFF state; declared payoff image (planv9); no chain-collapse rendering primitive |
| 12 | P1 Advanced SVG/procedural | **PARTIAL** | Cards are PIL-drawn (vgrad/mottle/grain, _v6_cardlib.py:59–212); no SVG emission in diagrams_v4 (grep "svg" = 0 hits in engine/) |
| 13 | P1 SCALE_DIVE primitive | **MISSING** | Token only: canvas_grammar.py:118 transition_vocab; no camera primitive (motion_v6.py:82) |
| 14 | P1 Visual contradiction via plates | **PARTIAL** | contradiction.py declares/verifies reveal editorially; reveal is diagram-class, not plate+transformation |
| 15 | P1 Cross-video template test | **PARTIAL** | antitemplate.py SEQ/RATIO fields + planv9 fingerprint loop (15/15 distinct); missing asset_class/composition/background dimensions |
| 16 | P1 RICH_ASSET_COVERAGE | **MISSING** | No metric; nearest: antitemplate blur_ratio/diagram_ratio |
| 17 | P1 Label/caption final-frame QA | **PARTIAL** | Same gap as #1: caption_qa band containment is pre-render-declared; no final-frame transformed bbox probe |
| 18 | P1 Provider capability audit | **PARTIAL** | scripts/benchmark_image_gen.py; zai.py:65 notes no gen endpoint; no capability matrix doc |
| 19 | P1 Jev shadow stub | **MISSING (by design)** | Zero jev refs in *.py (verified); owner rule 2026-09-19: Jev closed, stub must make zero API calls |

## 2. Investigation findings (the 7 mandated questions)

### 2.1 Where visual assets come from today + provider capabilities

- **Production path (V12): 100% deterministic.** Per-story `make_cards.py` paints plates with PIL: kit backgrounds (`_v12_kitlib.py:30–182`: dark/era/terrain/split/depth fields) + card primitives (`_v6_cardlib.py`: label:134, arrow:154, big_number:167, vgrad:59). `seawater_drop/`, `fever_thermostat/` etc. have **no assets/ dir** — everything is painted at build time.
- **Legacy AI path (not in automated pipeline):** `stories/{round_window,green_sahara,honey_never}/fetch_plates.py` — per-story scripts curl Pollinations FLUX → Gemini vision subject check → finish acceptance. Ad hoc, hand-run, single-pass.
- **Provider abstractions (two parallel stacks):**
  - `src/providers/image_gen.py` — factory: nvidia_nim (FLUX.2, dim-pair table, long axis ≤1568, :126), pollinations, siliconflow, hf_serverless (HF_TOKEN).
  - `engine/broker/providers/imageapi.py` — SiliconFlow FLUX.1-schnell (:51), NvidiaNim FLUX.2-klein (:118); `generate_image(prompt, aspect, seed)` only.
- **Capabilities: text→image with seed ONLY.** No multi-reference, no image editing, no depth/edge conditioning anywhere in either stack. `imageapi.py` descriptor has no edit op; broker cache keys on (prompt, model, seed, aspect).
- **Env keys present in `.env` (names verified, values not read):** NVIDIA_API_KEY, SILICONFLOW_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, ZAI_API_KEY, HF_TOKEN, ELEVENLABS_API_KEY, FISH_API_KEY. Z.AI is vision-only ("no generation endpoint", zai.py:65); Gemini/OpenRouter are wired as **judges** (director.py:91/141), not image sources.
- **Implication:** the directive's "exploit already-available capabilities" resolves to: Pollinations (keyless, flux), NVIDIA NIM (img2img-capable models exist on NIM but not implemented), SiliconFlow. **No wired provider today exposes edit/multi-ref ops in code** — M1 must add ops to the existing abstraction (no new provider needed; NIM/Gemini image-edit endpoints are candidate implementations behind `ImageGenProvider`).

### 2.2 Camera transforms in render5 + post-transform QA

- Transforms live in `composev5.py`: `layout.smart_crop` (bias_y crop, :112/:219/:261), `_camera_filter` (:120) emitting zoompan/push/pull/crop_reveal/focus_reveal/DIAGONAL/CUSTOM_BEZIER (motion_v6.py:82), plus `_ambient_base` cover-crop (:193). All transforms are **single-layer affine camera on a flat plate**; foreground occlusion impossible by construction (only card layer + ambient + captions).
- **Existing post-render QA is frame-sampled but not bbox-aware:** caption_qa (state machine, safe_zone vs overlay-report band containment :158, stale-caption boundary probe :241), occupancy_qa (top/bottom band edge-density, continuation verification :129), phone_qa (360×640 legibility), publish_gate 8 components (publish_gate.py:31).
- **The mandated check does not exist:** no module projects label/number/arrowhead/annotation bboxes through the final camera window and tests canvas-edge crossing, overlap-by-bars, or occlusion at final frames. V12 stage-3 P0s (card-bottom seam frames, labels near panel edges) are exactly this blind spot. `key_number_rect` (planv8/caption_place) is a declared rect for QA exclusion — declared pre-render, never verified post-transform.

### 2.3 Beat visual modes today vs directive mode set

- Modes are chosen in `visual_grammar.py:recommend_mode` (:137): subject grammar → EXPLANATORY_MODES tuple; planv9 wraps planv8 + canvas_grammar kit classification. `motion_class` (C/B/A) is motion, not representation. `antitemplate` fingerprints mode sequences.
- 22 EXPLANATORY_MODES (visual_grammar.py:99) ≈ **diagram types**. Mapping to the directive's 14: CUTAWAY✓, MAP✓, TIMELINE✓, COMPARISON✓, FORCE_DIAGRAM≈FORCE/FLOW_FIELD, CELLULAR/MOLECULAR/MACRO_DETAIL≈MICROSCOPIC, SCALE≈SCALE_TRANSITION, CLIMATE_RECON/GEOGRAPHIC≈ENVIRONMENTAL_RECONSTRUCTION (partial), PROCESS≈PROCESS_LOOP (partial), CAUSE_EFFECT≈CAUSAL_CHAIN (partial), QUANTITATIVE≈DATA_GRAPHIC (implicit).
- **Missing as modes/representations: RICH_PLATE, MATERIAL_DEFORMATION, VECTOR_DIAGRAM (explicit), and "mode = representation" semantics.** Today a mode only selects a diagrams_v4 painter; there is no mode whose representation is a rich plate with overlaid evidence. `DIAGRAM` remains the generic fallback — exactly the directive's "do not default to VECTOR_DIAGRAM" risk.

### 2.4 depth.py — real or blur?

**Metadata, not pixels.** depth.py (200 lines) is a planner grammar: LAYERS (:24), MODE_LAYERS (:28), INTENTS (:81), per-shot stamping + revealing/decorative transition classification, blurred-only depth FAIL. The only rendered depth effect is `motion.ambient_parallax_filter` (motion_v6.py:341): the **Gaussian-blurred ambient field's** camera window moves at damp× rate behind the card — docstring itself says "no factual content can distort." No segmentation, no subject masks, no true parallax, no focus shift, no push-through. Directive: blurred extension "does NOT count" — current 2.5D is declaration+QA honest but renders no real depth.

### 2.5 Hook / payoff structure

- Hook: planv9 `_hook_plan` (:82) targets subject_visible_s default **1.0s** (directive: 0.5s), curiosity 2s, question 5s; editorial8 `viewer_simulation` (:115) verifies fade/black at 0.5s. No requirement that 0.5s shows the *phenomenon* or that 2s shows a *visual* contradiction (contradiction.py checks the reveal is visual, but timing/position of the contradiction is not the hook's 2s gate).
- Payoff: editorial8 `payoff_semantic` (:62) verifies declared hook curiosity → final semantic resolution + PAYOFF beat state; planv9 declares a payoff image. What's missing is the **causal-chain collapse primitive**: a renderer construct that draws the accumulated chain into one synthesized final image (today payoff is a diagram like any other, hero-enlarge banned).

### 2.6 Existing metrics vs VISUAL_SOPHISTICATION / RICH_ASSET_COVERAGE

- Nothing measures depth/material/lighting/texture/semantic-layers/subject-specificity. Adjacent metrics: occupancy edge-density (occupancy_qa), info_gain (editorial8, 2–4s semantic windows), editorial7 diagram/cinematic/blur ratios + antitemplate fingerprint ratios, value_density, motion_class C/B/A, visualclass ≥80% evidence+cinematic gate (declared, not pixel-measured).
- Both new diagnostics must be **declared-plan-driven + frame-verified hybrid**, not entropy — directive explicitly bans clutter-optimization.

### 2.7 Live Jev references

- **Zero** in `illustrated_engine/**/*.py`, `tools/`, `cli.py`, `engine/` (grep verified, venv excluded). Only historical mentions in AGENTS.md/workspace memory (closed 2026-09-19) and the directive's owner note. The V13 stub must be an inert interface (registry + decision-shape, `enabled=False`, no imports of any Jev client, no network).

## 3. Recommended milestone build order

Legend: **G** = renderer/planner-global (fix once, all stories inherit — directive: "fix the renderer/planner globally"); **S** = per-story authoring; "Blocks 6-video" = hard prerequisite for the final 6-video muted-review milestone.

| M | Scope | Items delivered | G/S | Blocks 6-video? |
|---|-------|-----------------|-----|-----------------|
| **M1** | RICH_VISUAL_PLATE asset class + multi-stage generation | extend `ImageGenProvider`/broker with `edit_image` + multi-ref ops (NIM/Gemini-edit behind existing abstraction); 4-stage pipeline (composition→detail→semantic-edit→optional depth/edge); per-plate sidecar: layer map (BACKGROUND..ANNOTATION), bbox registry, depth map, texture/lighting tags; new ASSET_CLASS in visual_plan schema; at least 1 rich plate per major beat for high-value beats | G (pipeline) + S (per-plate art direction) | **YES — core** |
| **M2** | Final-transform safe-area QA | project plate bbox registry through `_camera_filter` math per frame-sampled t; post-render edge-crossing probe on final frames (labels/numbers/arrowheads/diagrams); wire into publish_gate as new named component; fail → CAN_PUBLISH=FALSE | G | **YES — P0 defect** |
| **M3** | Depth-aware 2.5D | derive layer masks at generation stage (prompt-conditioned) or benchmark CPU seg/depth (rembg/BiRefNet-class, seconds/plate) — adopt only if CPU-cheap, else provider structural controls; renderer: true fg/mg/bg parallax + focus shift + push-through in composev5; retire ambient-only as "depth" credit | G (renderer) + S (masks per plate) | YES (art-directed verdict) |
| **M4** | Mode set + mode→representation mapping | add RICH_PLATE/MATERIAL_DEFORMATION/VECTOR_DIAGRAM/etc.; every mode declares its representation (plate / plate+overlay / pure diagram); planner picks non-default modes per beat; ban DIAGRAM-default without justification field | G + S (per-story mode plans) | **YES** |
| **M5** | Hook 0.5s + payoff synthesis + SCALE_DIVE | tighten hook gate (phenomenon visible ≤0.5s, visual contradiction ≤2s); causal-chain collapse payoff primitive; SCALE_DIVE first-class camera/transition primitive (layered descent across depth layers) | G | YES (hook/payoff are P0) |
| **M6** | Diagnostics + template extension | VISUAL_SOPHISTICATION (declared+frame hybrid); RICH_ASSET_COVERAGE (plate-duration/total); antitemplate gains asset_class/composition/background-architecture dims; SVG upgrade: gradients/masking/clip/glow for the evidence layer | G | Partially — needed for acceptance gates, not first render |
| **M7** | Jev stub + provider audit doc | inert disabled shadow interface (zero API calls); PROVIDER_CAPABILITIES.md matrix (edit/multi-ref/depth/res) from audit; benchmark refresh | G | No |
| **M8** | 6 fresh stories end-to-end | per-story: mode plan + art direction + plate generation + QA loops (mechanism / biology / geography / history / engineering / everyday counterintuitive), muted review | S | — (the deliverable) |

**Sequencing:** M1+M2 first (M2's bbox registry needs M1's sidecar; both are P0). M3 and M4 parallelize after M1 lands. M5 rides on M3 (SCALE_DIVE needs layers). M6 gates the milestone verdict. M8 only starts after M1–M5 are proven on one pilot story (recommend pilot = one biology/scale-descent story, reusing seawater-style kit).

**Critical constraint honored:** no AI video, compositor unchanged, provider abstraction intact, no paid additions beyond existing keys, Jev stays at zero calls.
