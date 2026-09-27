# JADE V15 — Upgrade Plan (Claude, 2026-09-27)

Base: `illustrated-engine` @ `2be2e66` (V14 Stage 11). Input: my V14 review
(`build/v14/claude_review_2026-09-27.md`), treated as evidence, not as a spec.

## 0. What the research changed vs. the review

| Finding (verified this session) | Consequence for the plan |
|---|---|
| **NIM FLUX.2-klein returns an on-bible, recognizable, richly textured illustration in ~3 s** (probe: "vintage 1950s ink-and-sepia… skate blade gliding over a frozen lake" → a publishable-looking engraving plate). The free provider chain (NIM → SiliconFlow → HF → Pollinations → Gemini image) is all keyed and available. | The richness gap is closed fastest by making **AI stills the world layer of every shot** (directive §11: "AI image = one layer", with vector/typography/camera on top). The review's 30–50-subject SVG illustration kit (#7, "L effort") is **deferred**: it would take weeks to approach what one plate gives today. V14's procedural grammars remain as the **floor tier** when every image provider fails. |
| The existing per-story plates under `build/plates/` and `assets/IS_*`, `SD_*` are mostly **hand-authored deterministic "cardlib" drawings** (per-story `make_cards.py`), not generated. | They cannot scale to "many videos". V15 does not depend on them; it generates plates per shot from the visual plan and caches them globally. |
| Remotion: ~6.5 s fixed overhead per render + ~2.2 s per rendered second (concurrency 2). | One Scene IR scene **per shot** (2–3 shots per beat) is affordable (~3–4 min per 50 s video) and gives each shot its own camera move and its own §25 cache entry. No bundler rewrite needed. |
| Remotion has no system fonts (Inter/Bebas render as DejaVu fallback). Text is `#E8EEF4` on everything. | Stage fonts into `public/fonts` + `@font-face`; take palette from the bible; adaptive ink (dark ink on light plates, light ink + shadow on dark plates) decided deterministically from plate luminance. |
| Judge chain `director.text_ask / vision_ask` (Gemini 2.5-flash → GLM-5.3-flash) is live (1.4 s round-trip). | One cached planning call per story + one plate-QA vision call per story + one final judge call per video. |
| No ASR installed; TTS is Fish (pinned free tier), no timestamps. | Word timing from **silence segmentation** of the cached beat WAVs (numpy only), anchored to punctuation; syllable-weighted inside phrases. |
| Camera easing parity bug: Remotion `evalCam` eases a segment with the *start* keyframe's easing, FallbackRenderer with the *end* keyframe's. Layer `scale` animations in `SceneComposition` scale around the SVG origin (0,0), not the layer anchor. | Fix both (needed for zoom-through shots). |
| Confirmed P0 defects: caption PNG overwrite (all scenes show last beat's captions), empty scale dive (`local_scale=1` at 24×), title overflow, renderer version constant `"1"` in cache key, bed ~−54 dBFS, gate blind to content. | Milestone 1. The old V14 artifacts must FAIL the new gate. |

## 1. Target architecture (V15 data flow)

```
story.json (+facts.json, visual_bible.json | derived deck)
  │
  ├─ TTS per beat (existing, cached) ──► v15_timing: word/phrase times per beat
  │
  ├─ v15_plan (Beat Visual Plan): 1 cached LLM call/story, schema-validated,
  │     numbers must be verbatim narration tokens (fact-checked text),
  │     word anchors must exist; retry once with errors; else DETERMINISTIC
  │     fallback plan (recorded, degraded)
  │
  ├─ v15_plates: 1 still per shot via the image fallback chain
  │     (NIM FLUX.2 → SiliconFlow → HF → Pollinations → Gemini) with the
  │     bible prompt prefix/suffix; global content-addressed cache;
  │     normalized 1080x1920; saliency subject mask + bbox (depth_layers);
  │     1 vision QA call per story on a plate contact sheet → failing plates
  │     regenerated once with a new seed; all providers down → V14 procedural
  │     grammar tier (asset_tier recorded, gate knows)
  │
  ├─ v15_shots: shot grammars → Scene IR (one scene per shot)
  │     PLATE_SHOT     plate world + 2.5D subject band + purposeful camera
  │                    toward the subject bbox + ≤1 leader label anchored to
  │                    the subject + optional headline / giant number
  │     ZOOM_THROUGH   scale descent across 2–4 plates (outer zooms past
  │                    camera while inner grows from its centre), scale label
  │                    per level keyed to its word  (replaces the empty dive)
  │     PROCESS_OVER_PLATE  dimmed plate + 2–4 causal step nodes revealed on
  │                    their words (LLM-written step text, not clause-chopping)
  │     finish layer (grain + vignette from bible) on every shot
  │     text fitted with the real font metrics; bbox pre-flight
  │
  ├─ render (existing select_backend + §24/§25 cache; renderer version =
  │     source hash)
  │
  ├─ assembly (existing v14_assembly, fixed): per-scene caption namespaces,
  │     phrase cues on real word times, SFX on shot cuts/reveals, bed at a
  │     real level, loudnorm to −14 LUFS
  │
  └─ v15_gate: deterministic hard checks (caption identity, text bounds,
        information floor on sampled frames, shot hold ≤ 4.5 s, plate tier,
        audio levels) + 1 vision-judge call on a labelled contact sheet
        (§28/§29 questions, closed enum) → PASS / HOLD(reasons)
```

Batch: `engine/v15_batch.py` runs N stories sequentially, sharing plate/plan
caches, one report with cost counters.

## 2. Milestones (each ends runnable end-to-end; v14_pipeline keeps working)

1. **M1 — correctness + honest gate foundations.** Caption namespace +
   content-addressed PNG names; caption identity check; renderer version =
   sha16 of renderer sources; `local_scale` authoring in SCALE_DIVE; subject
   keyword order; text-fit helper (PIL metrics) used by title emitters; bed
   level; loudnorm. Easing parity + centre-anchored layer scale animations.
2. **M2 — art direction in the renderer.** Bible palette → props.palette;
   fonts via `@font-face`; text styles (weight/stroke/shadow/ink choice);
   finish layer (feTurbulence grain + vignette); derived deck for
   bible-less stories.
3. **M3 — timing.** `v15_timing.py` silence alignment → per-word times,
   cached next to the WAV.
4. **M4 — Beat Visual Plan.** `v15_plan.py` (prompt, schema validation,
   retry, deterministic fallback, cache).
5. **M5 — plates.** `v15_plates.py` (provider chain, cache, normalization,
   mask/bbox, sidecar provenance, plate-QA vision call + one regeneration).
6. **M6 — shot grammars + pipeline.** `v15_shots.py`, `v15_pipeline.py`
   (render, assemble with phrase captions + SFX, report).
7. **M7 — gate + judge.** `v15_gate.py`; old V14 finals must FAIL it.
8. **M8 — validation + batch.** Both fixture stories into `build/v15/`,
   before/after sheets, one unseen story (generalization), `v15_batch.py`,
   `V15_REPORT.md`.

## 3. Budgets (per story)

LLM: 1 plan call (+1 retry max) + 1 plate-QA vision call + 1 judge call ≈
3–4 calls, all cached by input hash. Image: 1 per shot (~12–18) + ≤ 30 %
regenerations. Render: ~3–5 min CPU per 50 s video. No unbounded loops.

## 4. Explicit non-goals / keep-outs

No AI video, no Manim, no FFmpeg redesign (only additive loudnorm/SFX), no
metric zoo (a handful of hard checks + one judge call), no new pip/npm
dependencies, no removal or narrowing of any fallback chain (V15 only *adds*
tiers above V14's procedural path), no hand-fixing of the fixture videos —
every change is algorithmic and applies to all stories.

## 5. Risks

- AI plates can contain garbled text or wrong subjects → bible suffix "no
  readable text", plate-QA vision call, one regeneration, judge on final.
- Provider quota exhaustion mid-batch → chain descent, then procedural tier
  with `asset_tier` recorded; gate HOLDs a video whose HOOK/PAYOFF is not
  plate-tier.
- Silence alignment drift (±100 ms) → acceptable for phrase captions and
  shot cuts; word-exact timing is a later layer (would need an ASR dep).
