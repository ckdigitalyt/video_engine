# V7 — Editorial Intelligence & Anti-Template (implementation plan)

Brief: `Jade_todo_v7.txt` (2026-09-06). V6.2 renderer is frozen infrastructure.
V7 = planner intelligence + editorial metrics + new QA gates. No renderer redesign,
no Manim, no AI video, no new packages. All V6.2 foundations (motion QA, audio bed,
overlay/caption QA, frame distinctness, CAS, subject correctness, factual, phone QA)
stay intact and keep gating.

## Existing vocabulary (planv5, reused and formalized)
- role: HERO/DIAGRAM/DETAIL/COMPARISON/PAYOFF
- visual_mode: CINEMATIC/DIAGRAM/SPLIT/DETAIL/TRANSFORMATION/PAYOFF
- evidence_type: DIRECT_EVIDENCE / EXPLANATORY_DIAGRAM / ANALOGY
- beat_function: HOOK/CURIOSITY/... (visual_grammar_plan.per_shot)

## Module map (all new files; composev5/motion_v6 untouched except additive hooks)

| Brief item | Module | Notes |
|---|---|---|
| P0-1 visual classes + gates | `engine/visualclass.py` | shot → EVIDENCE / CINEMATIC / BREATHING / GENERIC_BLUR from plan spec + card art signature; coverage over narration duration; gates 80/20/10 |
| P0-2 real hook | `engine/planv7.py` | plan field `hook{claim,visual,curiosity_gap,payoff}`; opening shot must show hook_visual within 2s; works muted |
| P0-3 title removal | `engine/composev7.py` hooks | title = overlay on opening shot only, fades out by ~2.5s; cards no longer bake persistent headers (make_cards change per story) |
| P1-4 continuity chains | `engine/planv7.py` | plan field `concepts{}`; shots declare concept refs + verb (move/zoom/split/transform/connect/compare/annotate/state_change); renderer reuses concept assets across shots |
| P1-5 Information Transformation | `engine/editorial7.py` | per-beat score from spec-level diff (concept state/evidence/diagram change); camera-only or number-pop-only = 0 |
| P1-6 Visual Redundancy | `engine/editorial7.py` | rolling 5s windows over shot fingerprint (asset, layout, camera state, blur-card); flags narration-change-without-visual-change |
| P1-7 story-driven grammar | `engine/planv7.py` | story JSON gains `story_type` (science_process/history/geography/...); beat templates per type; no fixed hero→card→diagram chain |
| P0-8 semantic factual QA | `engine/semantic_qa.py` | claim decomposition (number/unit/object/qualifier/observer/timeframe) + DeepSeek exact-wording verification; superlative gate (oldest/largest/first...) requires in-video definition |
| P0-9 ending payoff | `engine/planv7.py` + `editorial7.py` | final beat resolves hook.curiosity_gap; no new entities in last beat; payoff visual = strongest explanatory visual |
| P0-10 Anti-Template | `engine/antitemplate.py` | per-video structural signature JSON → `editorial_signatures/`; planner reads recent signatures, varies structure deliberately (never randomly); brand constants untouched |
| P0-11 Human Editor Test | `editorial7.py` | the 10 questions; #1,2,4,8,9 are CAN_PUBLISH gates |
| P1-12 V6.2 foundations | — | qa5full still runs unmodified before qa7full |

## CLI
- `plan7 --story X` → V7 plan (superset of v5 schema; render5 renders it unchanged)
- `render7 --story X` → thin alias of render5 for V7 plans
- `qa7full --story X` → qa5full gates + V7 metric suite + extended report (hook score,
  evidence/cinematic/breathing/blur coverage, ITS, redundancy, continuity,
  anti-template diversity, semantic factual, ending payoff, human editor, top-5 problems)

## Test stories (deliberately different grammars)
- `phone_heating` — science_process: cause → process → heat → consequence
- `titanic_mistake` — history: chronology → reconstruction → causal chain → consequence
- `sahara_greening` — geography: map → time → transformation → comparison
Each = story JSON + procedural make_cards.py. No shared shot template.

## Order of work
1. Metrics foundation (editorial7 + visualclass) → baseline on existing 3 videos
2. planv7 (hook/concepts/grammar/anti-template adaptation) + composev7 title-fade
3. semantic_qa upgrade
4. 3 new stories → full validation → V7 report (extended metrics + top-5 human problems)
