# V13 M3 — CPU Depth Bench (2026-09-20, arm64)

Directive: `docs/directives/JADE_V13_RICH_VISUAL_DIRECTIVE.md` — depth must become
real masks/parallax; blurred ambient extension does not count as depth.

## Approaches

| Approach | Status | Seconds/plate | Notes |
|---|---|---|---|
| Saliency v1 (luminance+saturation subject mask, edge-weighted feathering, 3-band split) | **ADOPTED (default)** | ~1.1–1.4 @ 2160×3840 (measured) | Deterministic, numpy/PIL only; masks BACKGROUND/MIDGROUND/SUBJECT; coverage-weighted (empty layer ⇒ parallax_weight 0) |
| rembg (u2net) | Implemented, not installed | not measured | `depth_layers._rembg_masks` ready; module absent on this box; onnx model download + CPU runtime unverified vs the 30s/plate budget |
| Monocular depth net | Rejected for M3 | — | Out of CPU budget; directive requires masks/parallax, not a heatmap; sidecar `depth_map` stays null |

## Decision
Saliency v1 ships as the default derivation (deterministic, offline, ~1.3s/plate).
rembg stays an optional route — revisit only if integration shows saliency masks too
coarse for parallax artifacts.

## Parallax proof (self-test, real ffmpeg frames)
- Synthetic 2160×3840 plate, PAN_RIGHT (w=0.7, cx 0.35→0.5), damp=0.35, masks from saliency v1
- fg (SUBJECT mask) moved 88px vs bg (BACKGROUND mask) 46px at 540-wide output —
  ratio 1.91× (analytic 2.86×; integer-step SAD tracking + feathered mask edges
  account for the delta)
- Validator accepts `generation.depth.status="derived"`; legacy `deferred_to_M3` still valid
- Rollback: `V13_DEPTH=0` → primitive returns None, single-plate path preserved

## Compositor contract
`composev5.plate_parallax_filters(shot, sidecar, dur, fps, damp=0.35)` →
`(bg_filter, fg_filter, meta)`: BACKGROUND rides the `_damped_v6` window pair
(both endpoints interpolated toward identity — damping only `to` collapses pure
pans), SUBJECT rides the authored camera; `[bg][fg]overlay` = fg occlusion.
Focus shift / push-through ride the same two rates. Beat-render hookup lands with
the integration milestone (sidecars flow through render5).
