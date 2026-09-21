# V13 IMPLEMENTATION PLAN — RICH VISUAL ASSET ENGINE

Owner directive: `docs/directives/JADE_V13_RICH_VISUAL_DIRECTIVE.md` (2026-09-20).
Gap analysis: `docs/v13/GAP_ANALYSIS_2026-09-20.md` (0 implemented / 10 partial / 9 missing).
Baseline: V12 @ 711af23. Pipeline: plan9 -> TTS(Fish) -> plan7 -> plan8 -> render5(4K) -> qa8full --v6.

Non-goals (binding): no AI video, no compositor switch, no Manim, no audio redesign, no new paid
providers, no new QA-metric zoo beyond the named ones, Jev stays CLOSED (inert stub, zero API calls).

## Contract 1 — Plate sidecar schema (M1 writes, M2/M3 consume)

`build/plates/<story>/<beat>/<asset>.sidecar.json`, schema id `v13-plate-sidecar@1`:

```json
{
  "schema": "v13-plate-sidecar@1",
  "plate": "build/plates/<story>/<beat>/<asset>.png",
  "asset_class": "RICH_VISUAL_PLATE",
  "generation": {"composition": {"provider": "...", "model": "...", "seed": 0},
                  "detail": {"...": "..."}, "semantic_edit": {"...": "..."}, "depth": {"...": "..."}},
  "layers": [
    {"name": "BACKGROUND|MIDGROUND|SUBJECT|FOREGROUND|ATMOSPHERE|EFFECTS|ANNOTATION",
     "mask": "<path>.png|null", "bbox_px": [x0, y0, x1, y1], "parallax_weight": 0.0}
  ],
  "subject_bbox_px": [x0, y0, x1, y1],
  "annotation_rects_px": [{"id": "label-1", "kind": "label|number|arrowhead|annotation|diagram",
                            "bbox": [x0, y0, x1, y1]}],
  "depth_map": "<path>.png|null",
  "zoom_safe": {"max_scale": 1.6},
  "safe_margin_px": 40,
  "texture_tags": ["..."], "lighting": "..."
}
```

Rules: all rects in source-plate pixel space (plates generated 2160x3840); `annotation_rects_px` is the
input to safe-area QA; a plate without sidecar is treated as legacy deterministic art (QA falls back to
declared rects from planv8 `key_number_rect`).

## Contract 2 — Provider op extension (in-place, abstraction intact)

`src/providers/image_gen.py` + `engine/broker/providers/*` gain, with NotImplemented-safe fallbacks to
existing single-pass text→img:

- `edit_image(prompt: str, image: str | list[str], aspect: str, seed: int | None) -> Path`
- `generate_multi_ref(prompt: str, refs: list[str], aspect: str, seed: int | None) -> Path`

Candidate implementations behind the SAME interface, using already-wired keys only:
Gemini image editing (GEMINI_API_KEY, already used for judging), NVIDIA NIM img2img if the endpoint
supports it, Pollinations as single-pass fallback. A capability probe (`tools/image_capability_audit.py`)
emits `docs/v13/PROVIDER_CAPABILITIES.md` (edit / multi-ref / depth-edge conditioning / max-res matrix).
Broker cache keys extend with (op, ref-hashes). Never log or commit key values; load from `.env`.

## Milestones

| M | Deliverable | Acceptance | Global? | Blocks 6-video |
|---|-------------|-----------|---------|----------------|
| M1a | Provider ops + capability audit doc **(landed @ 79edeb3 — code complete, live edit UNVERIFIED)** | ops wired both stacks w/ fallback; live probes: Gemini edit 429 quota, NIM 422 payload, SiliconFlow 401 (key scoped to generations?). Follow-ups: retry Gemini edit after 1h quota cooldown (pilot run), fix NIM img2img payload shape, re-probe SiliconFlow edit endpoint | G | YES |
| M1b | Plate pipeline `engine/plates.py`: 4 stages (composition → detail/material → semantic edit → depth/edge) writing plate + sidecar | pilot plate sidecar validates against schema; stage failures degrade gracefully to single-pass with sidecar flag | G+S | YES |
| M2 | Final-transform safe-area QA `engine/safe_area_qa.py` + publish_gate component `safe_area_final` | synthetic test: bbox pushed off-canvas by zoompan → CAN_PUBLISH=FALSE; passes on in-spec plate; runs on sampled final frames post-transform | G | YES (P0 defect) |
| M3 | Depth-aware 2.5D **(landed @ 4668dca)**: depth_layers.py — saliency_v1 masks (BACKGROUND/MIDGROUND/SUBJECT, edge-feathered, coverage-weighted, ~1.3s/plate arm64; rembg route present but not installed — see DEPTH_BENCH.md); composev5.plate_parallax_filters — _damped_v6 both-endpoint damping + fg-occlusion compose contract (focus shift/push-through ride the same rates), flag-gated V13_DEPTH default-ON; plate_pipeline stage 4 calls derive_masks (status="derived") + stamps layer masks; validator accepts derived; self-test: fg 88px vs bg 46px motion (1.91×), rollback proven. Beat-render hookup → integration milestone | pilot plate renders parallax from real masks; occupancy/depth QA updated | G+S | art-direct verdict |
| M4 | Mode→representation mapping **(landed @ 6f30716)** | 29-mode MODE_REPRESENTATION (unknown→PLATE); rich-preference in recommend_mode + detailed {mode, representation, justification}; planv9 stamps representation/mode_justification/representation_mix per beat (planv8 unchanged); antitemplate +asset_class_mix/composition_architecture/background_architecture | G+S | YES |
| M5 | Hook/payoff/SCALE_DIVE **(planner-side landed @ 9f9a1c9)**: planv9 hook fields (phenomenon/tension/hook_source authored|synthesized, deterministic templates, no invented facts) + payoff fields (causal_chain assembled from beat claims, payoff_source); visual_grammar SCALE_DIVE mode → PLATE with nested-scale subject routing (≤1 mid-story beat); diagnostic-only, no gate changes; legacy plans valid. **Remaining (integration milestone):** 0.5s/2s gate timing + compositor SCALE_DIVE zoom primitive across depth layers + pilot calibration of SCALE_DIVE subject routing (current grammar routes some scale-y subjects to diagram-class with justification) | planv9 gates tightened; payoff renders as synthesis, not generic end card; SCALE_DIVE demonstrable on pilot | G | YES |
| M6 | Diagnostics **M6a landed @ 5f748c5**: visual_sophistication.py — 9 sub-scores (depth/material/lighting/texture/context/scale/semantic_layers/subject_specificity/hierarchy; declared 50/50 frame-verified region stats inside declared layers only, never global entropy; clutter penalty ≤0.5 on composite) + rich_asset_coverage (plate/total, per-beat); cli.py res8 additive non-gating (calibration on pilot). Antitemplate dims done in M4. **M6b landed @ 5ce4e60:** new engine/svg_evidence.py — SVG evidence emit path per directive P1 (linearGradients parchment-neutral + ink→muted accent, mask soft fade-ins, clipPath containment to declared rects, feGaussianBlur glow on emphasis marks only — never text); flag V13_SVG default-ON, byte-identical legacy rollback; text rules untouched. | metrics present in qa8 report without adding >3 gate components | G | verdict gates |
| M7 | Jev shadow stub **(landed @ b28da8b)**: jev_stub.py — JevShadowStub.evaluate → None unless V13_JEV=1 opt-in (inverse convention, docstring records owner-closed 2026-09-19 provenance: 60/100 + 12 unsafe FP; live Jev requires owner re-approval); opt-in returns deterministic sorted summary of precomputed local metrics only; zero network imports verified (self-test: no requests/urllib/httpx/socket, no sys.modules delta); PROVIDER_CAPABILITIES.md done in M1a | grep proves no network path; flag documented | G | no |
| M8 | Six fresh stories end-to-end + muted review | science mechanism / biology / geography / history / engineering / everyday counterintuitive; per-story mode plan + art direction; QA loops; muted review verdict | S | — |

Sequencing: M1a ∥ M2 (disjoint files; both pinned by this contract) → M1b → M3 ∥ M4 → M5 → M6/M7 →
pilot story (M1–M5 proven on ONE biology/scale story first) → M8 slate → muted review.

Integration milestone (pilot prep, after M3/M4): render5 consumes plate sidecars (plate beats →
RICH_VISUAL_PLATE layer compositing via real masks), cli.py passes safe_area= into publish_gate.run,
planv9 emits plate specs using M4 representations. All proven on the pilot story before M8.
**(landed @ cf60352)** — planv9 plate_spec for PLATE-class beats (legacy-tolerant); cli _v13_plates_stamp
discovers build/plates/<story>/<beat> assets into the render path; safe_area_qa wired into the
publish-gate path; svg_evidence public wrapper exposed. Pilot story proves the chain.

## QA gate changes (only these)

- `safe_area_final` (M2, landed @ f997f3c): project `annotation_rects_px` + `subject_bbox_px` through the final camera
  window per sampled frame; any semantic clipping or margin violation → component FAIL → CAN_PUBLISH=FALSE.
  Integration TODO (folded into the pilot-prep integration milestone, after M3/M4): call
  `safe_area_qa.evaluate` from cli.py and pass `safe_area=` into `publish_gate.run` once plate sidecars
  flow through render5; address M2 coupling notes — densify samples or port `resolve_camera` eased
  curves (current projection is linear-at-t, may miss brief eased-window clips).
- `viewer_simulation` / `hero_recognizable` unchanged; hook timing folded into existing planv9 gates (M5).
- No other gate components added.

## M8 slate (owner may veto topics before render)

1. Science mechanism — candidate: "Why ice is slippery" or per planner selection
2. Biology — scale-dive pilot (cell/immune), reuses seawater-style depth kit
3. Geography — candidate: Atacama-adjacent fog/desert reconstruction (new story, not a re-render)
4. History — candidate: Tunguska-class reconstruction (new event)
5. Engineering — candidate: crumple-zone successor (new mechanism)
6. Everyday counterintuitive — candidate: microwave/dielectric successor

Renderer/planner changes are global; the five V12 videos are NOT patched (per directive).

## Pilot status (2026-09-21): cell_scale_dive CAN_PUBLISH=True
- qa8full: all 10 publish-gate components true, p0 none; subjects 6/6 PASS on real frames; TECH 100; continuity 0.6953; soph composite 0.566
- Plate mix: 3 live AI plates (B2 eye, B3 rings — wait, final mix: B1/B3/B4/B5/B6 deterministic contract-faithful cards, B2 graded AI eye) — free-provider subject-adherence ceiling documented; Gemini-image swap on quota reset = open upgrade
- Engine fixes landed on the way (M6-class): render_shot_v2 input-staleness invalidation (3 renders were cache hits), vision_ask parse hardening + subject_check max_tokens 1600, S02 contract realignment (was hair-edge text on the eye asset)
