# V12 Stage 1 — P0 Story-Driven Visual Grammar Engine (report)

Stage: plan-level engine + gate wiring + one smoke render (no full 4K QA renders — Stage 3).
Branch `illustrated-engine`, base `8725462`. Directive: `Jade_todo_v12.txt` §P0 (8 items).

## The problem (verified on frames)
Frames extracted from `output/{autumn_red,tambora_1816,baikal_deep}.mp4`
(`~/.openclaw/workspace/tmp_v12/*_t*.png`): three different story_types
(science_process / history_event / geography_place) render one shared
architecture — cream grid-paper background, central framed panel, black
annotation chips, header brand rail, lower title band, narration strip,
single orange accent. `story_type` packs varied evidence vocabulary but
never canvas architecture.

## Modules landed (commits in order)
1. `9fb08be` **engine/canvas_grammar.py** — grammar registry: 7 kits ×
   (composition, background, panel_usage, chrome_density,
   caption_architecture, transition_vocab, camera doctrine, per-beat
   composition variants, per-beat default transformation). Covers the six
   stress categories: mechanism_flow (science mechanism), scale_descent
   (biology / macro→micro), map_first (geography), timeline_band (history),
   cutaway_reveal (engineering), before_after (counterintuitive everyday),
   field_propagation (climate/earth). Also: VALID_TRANSFORMATIONS
   vocabulary (11 valid primary gains; zoom/pan/drift/particles/number_pop/
   highlight/sweep declared invalid) + `LEGACY_DEFAULT` (the universal
   presentation-panel architecture, documented for legacy-plan comparison).
   Story classification: declared `visual_grammars` wins; else scored
   story_type + subject/beat keywords (deterministic, never randomized).
2. `a355904` **engine/planv9.py** — visual experience planner wrapping the
   planv8 chain (engine extended, not rewritten): per-shot `canvas` dict,
   beat model (viewer question → visual intent → visual experience → state
   transformation → payoff), declared-contradiction localization (reveal
   shot must exist), hook-plan measurement (subject visible ≤1s, no
   black/fade at 0.5s, question by 5s), payoff-image localization (final
   3–5s window, hero-enlarge default rejected), and the bounded
   regeneration loop (≤2 regenerations with the next DIFFERENT valid
   grammar, honest final verdict). Persists v2 signatures at plan time
   (fixes the empty `no_comparable_history` motif store: signatures now
   exist before any render). Story schema additions (backward compatible):
   `visual_grammars`, `visual_contradiction{seems,actually,reveal,beat}`,
   `hook_plan{subject_visible_s,curiosity_s,question_s,no_black_fade_at_0_5}`,
   `payoff_image{image,beat}`. CLI: `python3 -m cli plan9 <story> [--grammar K]`.
   Same commit: **engine/antitemplate.py** v2 fingerprint — directive field
   list computed from PLANS (no renders): scene-role, grammar, composition,
   panel usage, background, caption architecture, transition types, state
   sequence, camera behavior sequences + diagram/cinematic ratios, shot
   duration profile, title behavior, chrome usage, accent usage. Weighted
   distances; `cross_video_compare` answers "mute narration + replace nouns
   → same video?" (same_video = low weighted mean AND dominated
   architecture fields).
3. `2080b21` **gate wiring** — editorial7 emits `cross_video_template`
   (v2 fields stored inside the one persisted signature; v1 verdict kept);
   publish_gate gains the 9th component `CROSS_VIDEO_TEMPLATE`
   (default True only for pre-V12 plans); scroll_stop checkpoints extended:
   `t1_subject_visible` (MAJOR), t0.5 now fails on fade/black openings,
   declared-but-unhonored contradiction fails `t30_model_changed`,
   payoff-image spec joins `final_payoff` (no generic end card / hero
   enlarge).
4. composev5 seams (`0-seam` + `dedupe` commits) — `canvas.panel_usage
   "none"` → full-bleed presentation (plate art cover-crops the whole
   canvas; no tone-mixed continuation bands); `canvas.chrome_density`
   none/minimal suppresses the universal brand rail (opening titles always
   render); full-bleed ambient crops the cardlib baked footer chrome so the
   title band is not duplicated.
5. Story schema additions committed for ice_slippery (scale_descent:
   solid ice → microscopic quasi-liquid interface) and baikal_deep
   (map_first: one lake → one fifth of Earth's fresh surface water).

## Negative control (honest — the detector works, so old plans FAIL)
v2 fingerprints of the pre-V12 plans (legacy architecture), pairwise
cross-video compare:

| pair | mean distance | architecture fields near-identical | verdict |
|---|---|---|---|
| autumn_red vs tambora_1816 (old) | 0.127 | 7/9 | **same_video** |
| ice_slippery vs baikal_deep (old) | 0.096 | 8/9 | **same_video** |
| ice_slippery vs tambora_1816 (old) | 0.137 | 7/9 | **same_video** |

Same numbers would make the publish gate return CAN_PUBLISH=False on the
V11 stress stories — proven by direct `publish_gate.run` check
(`cross_video_template:same_video(...)` named in p0_defects).

## Replan divergence (plan8 level, no render)
| pair | mean distance | verdict |
|---|---|---|
| ice(old) vs baikal(old) | 0.096 | same_video |
| ice(scale_descent) vs baikal(map_first) | **0.494** | distinct |
| ice(descent) vs ice(old) | **0.435** | distinct |
| baikal(map_first) vs baikal(old) | **0.491** | distinct |
| ice(descent) vs autumn_red(old) | 0.542 | distinct |
| baikal(map_first) vs autumn_red(old) | 0.617 | distinct |

Regeneration loop demo (forced-similar): `plan9 ice_slippery --grammar
map_first` → attempt 1 d=0.096 same_video (clashes with baikal's
map_first plan) → auto-regenerated with scale_descent → attempt 2 d=0.494
distinct. No randomization: both attempts are valid story-specific
grammars; the loop is bounded and the intermediate failure is recorded.

editorial7 driver on the new plans: `cross_video_template: True
(distinct, 0.494)` for both; v1 `anti_template` unaffected.

## Smoke render (lowest supported = native 1080×1920)
`render5 --story ice_slippery --force` with the planv9 plan (grammar
scale_descent, 7 shots, 56s, exit 0, no crashes, no debug leakage in
frames). Frames (`tmp_v12/NEW_ice_t*.png`) vs the V11 template:
- brand rail chrome gone; no matted presentation panel; art bleeds
  edge-to-edge (orange field, molecule cutaway band full-width);
- captions in the kit's edge band (authored caption_zone honored);
- fixed during verification: full-bleed ambient duplicated the cardlib
  baked footer strip → ambient now crops baked plate chrome (commit
  "dedupe title band"); one title band remains, at the card bottom.
Honest residual: the plates themselves still carry grid-paper backgrounds
and panel-authored art from the V4-era cardlib; the plan declares the kit
background (depth_gradient) and Stage 3 plate regeneration must honor it.
Architecture at the composition/chrome/panel level is story-dependent now;
plate-internal art is the next stage.

## Gaps / deferred to later stages
- Plate-art regeneration per kit (backgrounds: depth_gradient,
  era_field, terrain_field…) — Stage 3; composev5 already carries the
  per-shot `canvas.background` declaration.
- Diagram/cinematic plate coverage for every composition variant
  (descent/micro layers currently reuse existing cardlib plates).
- qa5full/qa5 vision judges not run in this stage (no full QA render).
- The 6-story stress test (Stage 3) will exercise kit coverage; the two
  replanned stories already cover science mechanism + geography.
- `_title_overlay_png` remains disabled (pre-existing V7 behavior, out of
  scope).
