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
| M3 | Depth-aware 2.5D: masks from generation stage (M1b) or CPU seg benchmark (rembg/BiRefNet-class, seconds/plate — adopt only if CPU-cheap); composev5 true fg/mg/bg parallax, focus shift, push-through; ambient blur no longer counts as depth credit | pilot plate renders parallax from real masks; occupancy/depth QA updated | G+S | art-direct verdict |
| M4 | Mode→representation mapping: add RICH_PLATE, MATERIAL_DEFORMATION, VECTOR_DIAGRAM, DATA_GRAPHIC, PROCESS_LOOP, CAUSAL_CHAIN as representations; mode declares representation (PLATE / PLATE+OVERLAY / DIAGRAM / HYBRID); DIAGRAM-default requires justification field | planner output shows non-default modes per story; antitemplate fingerprint still distinct | G+S | YES |
| M5 | Hook 0.5s phenomenon + 2s visual contradiction gates; causal-chain-collapse payoff primitive; SCALE_DIVE first-class camera primitive across depth layers | planv9 gates tightened; payoff renders as synthesis, not generic end card; SCALE_DIVE demonstrable on pilot | G | YES |
| M6 | Diagnostics: VISUAL_SOPHISTICATION (9 sub-scores: depth/material/lighting/texture/context/scale/semantic-layers/subject-specificity/hierarchy; declared+frame hybrid, never raw entropy); RICH_ASSET_COVERAGE (plate-duration/total); antitemplate dims + asset_class/composition/background; SVG evidence-layer upgrade (gradients/masking/clip/glow) | metrics present in qa8 report without adding >3 gate components | G | verdict gates |
| M7 | Jev shadow stub (inert registry + decision shape, enabled=False, zero imports of any client, zero network); PROVIDER_CAPABILITIES.md finalized (if not in M1a) | grep proves no network path; flag documented | G | no |
| M8 | Six fresh stories end-to-end + muted review | science mechanism / biology / geography / history / engineering / everyday counterintuitive; per-story mode plan + art direction; QA loops; muted review verdict | S | — |

Sequencing: M1a ∥ M2 (disjoint files; both pinned by this contract) → M1b → M3 ∥ M4 → M5 → M6/M7 →
pilot story (M1–M5 proven on ONE biology/scale story first) → M8 slate → muted review.

## QA gate changes (only these)

- `safe_area_final` (M2, landed @ f997f3c): project `annotation_rects_px` + `subject_bbox_px` through the final camera
  window per sampled frame; any semantic clipping or margin violation → component FAIL → CAN_PUBLISH=FALSE.
  Integration TODO (folded into M1b): call `safe_area_qa.evaluate` from cli.py and pass `safe_area=` into
  `publish_gate.run` once plate sidecars exist; address M2 coupling notes — densify samples or port
  `resolve_camera` eased curves (current projection is linear-at-t, may miss brief eased-window clips).
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
