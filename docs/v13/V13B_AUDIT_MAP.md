# V13B AUDIT MAP — where the presentation-template language is generated
Audit 2026-09-24 ~01:35 UTC (read-only subagent, branch illustrated-engine). Companion to docs/directives/JADE_V13B_STORY_SPECIFIC_VISUAL_GRAMMAR.md.

## Code map (file:line anchors)
- Shared constants: `stories/_v6_cardlib.py:35-45` PARCH/PARCH_L/CREAM/NAVY/RUST palette (RUST=(194,91,51) = the orange), `:100 parchment()`, `:118 title_bar`, `:128 footer_band`, `:145 label()` rounded box, `:154 arrow(col=RUST)`, `:167 big_number(col=RUST)` — imported by every `stories/*/make_cards.py` (e.g. aircraft_wing_lift:13-17)
- Orange accent source: `stories/*/visual_bible.json` palette "accent": "#C25B33" → validated `engine/bible.py:18,66-77` (`rgb255(bible,"accent")`), consumed `composev5.py:407,417,434,491`, `diagrams.py:35`, `diagrams_v3.py:36`
- Parchment card default: `engine/diagrams.py:30-42 _card()` hardcodes paper (233,223,200)+mottle; same `diagrams_v3.py:36-42`; kitlib override exists `stories/_v12_kitlib.py:4-14,182 kit_background()`
- Template grammar registry: `engine/canvas_grammar.py:300-305` default kit `universal_presentation_panel` (composition=central_horizontal_panel, panel_usage=hero_island, chrome_density=rail, caption_architecture=edge_band); keyword→kit `_keywords_for:319`
- Planner: `engine/planv9.py:231 _beat_model` per-beat composition; `:289-292 visual_grammar.recommend_mode_detailed` stamps representation per beat; `:304-306` legacy no-plate_spec reads DIAGRAM; `:309-325` additive plate_spec (rich beats); `:442 apply_canvas` writes kit canvas onto EVERY shot — per-shot visual-grammar attach point
- Domain classification (exists, keyword-level): `engine/visual_grammar.py:56 SUBJECT_HINTS`, `:74 detect_subject()` (→"general" fallback), `:154 representation_for()`, `:159 representation_of()`, `:185 grammar_for()` — no true story-domain model
- Rich-asset path: `engine/plate_pipeline.py:293 generate_plate()` → `:124-150 _compose` (generate_multi_ref_with_fallback; failure → mode="placeholder" PIL gradient `:83-85,149`); detail edit `:155-169`; stamped `cli.py:310 _v13_plates_stamp`
- Diagram fallback: failed plates → placeholder (not diagram); legacy plans w/o plate_spec read DIAGRAM (planv9:304-305 via representation_of:159); painters `engine/diagrams_v3.py`/`diagrams_v4.py` from `cli.py:148-151,233-236`
- Caption layout: `engine/composev5.py:265-279 _caption_band()`, `:454 _layout_caption_v5` (SAFE_CAPTION_TOP), `:477-485 caption_png_v5`; `engine/captions.py:37 KIN_CAP_H=192`, `:47-68 band_rect()`; `engine/caption_place.py:48 DEFAULT_ZONE="below_card"`, `:58-75 zones()` (1350..1520), authored `shot["caption_zone"]` wins `:195-210`
- Chrome rails: `engine/composev5.py:371-390` — chrome_density=="rail" or shot.opening → layout.brand_block; end_card `:385-390`
- Hook/B1: `engine/planv9.py:82 _hook_plan`, `:164-199 _hook_fields`, stamped `:327-330`; title `engine/layout.py:89-107` + `engine/composev5.py:80-102 _title_overlay_png` (header band top-center)
- Boxes/annotations: `engine/composev5.py:392 _number_png_card`, `:411 _highlight_png_card` (accent rounded_rect), `:427 _pulse_png_card`, `:447 rule_png`; plate annotations `engine/plate_pipeline.py:247-264` (subject_bbox_px/annotation_rects_px → consumed `:403-419` depth layers); empty-container QA `engine/occupancy_qa.py:178-188`, `engine/depth_layers.py:271`

## Highest-leverage files
1. `engine/canvas_grammar.py` — kill universal_presentation_panel as default; make kit selection per-domain + per-beat
2. `engine/planv9.py` — attach per-shot visual_grammar at `_beat_model`/`apply_canvas` (domain-aware)
3. `stories/_v6_cardlib.py` — shared parchment/RUST/title-bar constants; per-domain palette + payload-required boxes

## Milestone plan (directive: engine-global fixes only, no story hacks)
- M2 story-grammar planner: STORY_DOMAINS (biology, physics_mechanism, geography_environment, history, engineering, everyday_science, general); detect_domain(story_meta, narration) weighted deterministic; per-domain ordered composition prefs + overlay vocab + accent guidance; canvas_grammar world kits; universal panel = justified-only; cardlib payload-required boxes; apply_canvas writes per-shot {domain, world, composition, overlays, accent}
- M3 rich-first fallback tiers: rich plate → rich procedural reconstruction → layered hybrid → subject-specific technical diagram → simple (only when concept requires); track asset tier in shot meta (no new scoring system); placeholder ≠ rich
- M4 full-canvas 9:16 + captions + hook: world-bleed compositions default for rich tiers; caption placed into measured negative space (use plate subject_bbox_px/annotation_rects_px sidecars) keeping caption QA intact; hook shows subject/scale/consequence from frame 1, title demoted to support
- M5 detection + gates: deterministic presentation-template signature check (parchment bg + panel + boxes + rail + generic diagram + edge caption together → flag → planner recomposes, not a pass-able score); visual-authorship mute test per 2-4s segment; human-editor 6-question gate before CAN_PUBLISH (Q1/2/3/4/6 fail → false)
- M6 six-story muted set: ice_slippery, cell_scale_dive, atacama_fog_oases, tunguska_1908, crumple_zones, microwave/dielectric (new story to author); judge TOGETHER → engine freeze

## Hard constraints (from directive)
Preserve: cache invalidation, forced rerender on asset/bible change, judge parser hardening, contract token-budget, semantic asset verification, caption safety, factual verification, technical QA, zero-debug-leak. NO AI video, NO Manim, NO FFmpeg redesign, NO audio redesign, NO metric zoo, NO random styles, NO make-every-shot-AI. Deterministic selection only.
