# BUILD_STATE — illustrated_engine (illustrated-engine branch)

Checkpoint log. Update as stages complete.

## 2026-09-01 (run 2 — engine core rewrite)

### Context
- Run 1 timed out; fonts survived (BebasNeue, Inter-Variable, ArchivoBlack
  90,988 B — verified loads as `Archivo Black`). Run 1's engine code was
  OFF-SPEC (full-frame 2160x3840 zoompan, no panel/band/caption layout) and
  was replaced wholesale. Only fonts + stories/ kept from run 1.
- Interface files read: stories/space_closer/{story.json,visual_plan.json,
  visual_bible.md}. Nothing else outside illustrated_engine/ touched.

### Done
- engine/{__init__,motion,text_ass,compose,plan,qa}.py + cli.py +
  templates/ass_style.json + README.md — full spec implementation:
  - Camera: 11 primitives -> closed-form zoompan expressions (linear
    from/to {w,cx,cy} interp over on; zoompan on 3060x2210 panel-aspect
    canvas, plate pre-scaled 3060x2040 + 85px letterbox pad; zoom=1/w).
  - Overlays: HIGHLIGHT (throb via scale eval=frame t-expr; probe-gated,
    probe OK on this ffmpeg 6.1.1), ARROW_DRAW (12-stage draw-on PNGs),
    CALLOUT (label+leader, fade + 8px slide), LIGHT_SWEEP (alpha 0.12
    diagonal strip slide), TITLE_BAND (cached build/overlays/title_band.png),
    NUMBER_POP via ASS. Transitions: CUT/CROSSFADE/FADE/IMAGE_WIPE_UP.
  - text_ass: Caption/NumberPop/EndCard + WordReveal (120ms stagger),
    Pillow-measured 2-line wrap at 972px, safe-area clamps, fontsdir.
  - compose: standalone render_shot + render_video (stale mtime checks,
    xfade/concat chain from probed shot durations, loudnorm I=-14 audio or
    silent track). Determinism: threads=1, bitexact, metadata stripped.
  - plan: validate (schema/primitives/kinds/assets/fonts/clamp warnings) +
    make_edit_plan (beat-split durations, word-proportional phrase captions,
    symbolic region/point/pos resolvers).
  - qa: ffprobe (res/fps/pix_fmt/faststart/A-V dur), blackdetect (edge
    exempt 0.6s), freezedetect 3s, loudnorm print, shot count, contact sheet.

### Design decisions
- Zoompan runs on a panel-aspect canvas (3060x2210 = 18:13) so uniform
  zoom crops map 1:1 to the 1080x780 panel with no distortion; letterbox
  pad absorbs w up to 1.0.
- Frame assembled with pad (panel into 1080x1920) instead of a separate
  color-source overlay — identical pixels, one less sync risk.
- FOCUS_REVEAL auto-injects a slate ring HIGHLIGHT when the shot has none.
- ARROW_DRAW quantized to 12 reveal stages (deterministic, no geq).
- edit_plan carries CONCRETE geometry (resolved from visual_plan symbols);
  visual_plan stays the creative source. Region rects are estimates until
  plates land — refine in engine/plan.py REGION_TARGETS.

### Verification
- [x] validate + edit_plan build (12 shots, ~56.5s est, assets-missing warnings)
- [x] smoke x2 sha256 identical (see build/smoke/smoke.sha256)
- [x] qa build/smoke/smoke.mp4 (streams pass; silent-audio loudnorm warn expected)
- [ ] render-video (blocked: plate assets not generated yet)

### Open / risks
- Inter variable TTF renders at default weight in libass (bible wants Inter
  Black for captions; Bold flag kept 0 so Pillow wrap widths match libass).
- Overlay scale is static vs camera zoom (approximate on long push-ins).
- Contact sheet may pad the last tile black if frame count rounds down.
- engine/tts.py is run-1 leftover, intentionally not imported (TTS is a
  later stage; cli tts is a stub).
