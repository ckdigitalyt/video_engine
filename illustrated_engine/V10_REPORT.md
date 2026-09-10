# V10_REPORT.md — V10 engine upgrade, end-to-end validation (2026-09-10)

Story under test: `noise_cancel` (59.0s ANC documentary). Implementation commit
`5e5f0a5` (staged 1/2); this report is stage 2: one full render + QA + visual
checks + fixes.

## 1. Layers validated (from `git show 5e5f0a5`)

| Layer | Flag (default ON) | What it does | Verified by |
|---|---|---|---|
| V10_VERTICAL | `V10_VERTICAL` | Native 9:16 pass: card anchored at `planv5.CARD_Y0=288`, portrait 1080×1152 panel fills the Shorts focal band Y 0.15–0.75 | flags token `…v10v…`; frame inspection (§4) |
| V10_KINETIC | `V10_KINETIC` | 2–4 word caption chunks, active-word accent highlight, band y≈0.70–0.76, PNG band-strip carriers (`build/ov5/<shot>/kin_caps/`, regenerated on `--force`) | flags token; carriers on disk; accent+underline visible in frames |
| V10_DEPTH | `V10_DEPTH` | Bloom on kinetic shots; additive `_glow_frames` halo on flow particles | `build/ov5/S03/liv2_glow/` generated during render |
| V10_PUNCT | `V10_PUNCT` | Sub-bass risers (REVEAL/ESCALATION starts) + 40–80Hz sub-drops (PAYOFF starts), absolute-timeline `at`; 1–3kHz bed notch | `build/punct/subdrop.wav` written + mixed at S06 (see §6 gap) |

Rollback: set the env var to 0 (e.g. `V10_VERTICAL=0`) — restores the pre-V10
path per layer. `plan5 --story noise_cancel` smoke: 6 shots, 58.1s, token
`…v10v-v10k-v10d-v10p`.

## 2. Stage-2 fixes (this commit)

1. **living overlays rendered on the wrong canvas (render-blocker).**
   `composev5.py` called `living.render_frames(...)` without
   `canvas_w/canvas_h`, so living diagrams drew on the legacy 1536×1024 canvas
   while V10 geometry maps card rects up to y=1440 →
   `ValueError: y1 must be >= y0` in `_frame_isolate` on the first ISOLATE
   event. Fix: pass `canvas_w=CANVAS_W, canvas_h=CANVAS_H` (1080×1920);
   `_frame_isolate` additionally skips degenerate dim-strips instead of
   crashing. Unit-checked with the failing rect.
2. **Cross-story audio contamination (correctness).** `build/` holds the LAST
   story's `audio_bed_plan.json`; only `edit_plan.json` had a per-story guard.
   The first V10 render silently mixed the previous story's SFX timeline
   (panama_locks events at panama times) into `noise_cancel`. Fix:
   `render5` now restores the bed plan per story (snapshot
   `build/audio_bed_plan_<story>.json`, else the authored
   `stories/<story>/audio_bed_plan.json`), and `plan5` snapshots the injected
   plan so every future render self-heals. Verified: second render log shows
   `audio: restored … (per-story guard)`; master rebuilt with noise's own 12
   SFX events.
3. **Subject-QA judged the wrong artifact.** `qa5.py` re-checked FAILing
   subjects on a rendered video frame only for shots with a kinetic spec
   (`plan.shots[].kinetic` — none in this story), so the vision judge saw the
   static plate, never what the viewer sees. Under V10 the plate is always
   recomposed (vertical band, camera crop, captions). Fix: rendered-frame
   recheck extended to every FAILing shot (3-vote majority unchanged).

## 3. Metric matrix — V10 render vs published V9 baseline

Baseline: V8_REPORT.md §12 (V9 engine, same story, `qa8full --v6`).
Control A/B (flags off, same tree) skipped per stage brief: the V10 render
required engine fixes (§2) and the committed V9 baseline is the same tree with
all V10 flags off by construction (rollback = flags to 0).

| Metric | V10 (this run) | V9 baseline | Δ |
|---|---|---|---|
| Duration | 59.00s | 59.0s | = |
| TECHNICAL | 100.0 | 100.0 | = |
| VISUAL | 95.42 | 95.08 | +0.34 |
| EDITORIAL | 87.73 | 87.73 | = |
| IV (info velocity, gate 80) | 93.3 | 93.3 | = |
| NVA (narration-visual alignment, gate 80) | 100.0 | 100.0 | = |
| ID (info density, gate 75) | 83.5 | 83.5 | = |
| Motion smoothness | jitter 100.0 / reversals 100.0, 0 bad shots | n/a (§12) | pass |
| Audio continuity | 100.0, 0 gaps, 0 restarts | n/a (§12) | pass |
| Continuity | 6/6 (0.589–0.640), video 0.609 | 6/6 (0.589–0.640) | = |
| Phone QA | readable=True, pop_px=19, diag_px=96, caption_band_px=120 | readable (panama fix ref 17px) | = |
| LUFS | −14.33 (TP −1.42) | −14.32 | −0.01 (correct own-story SFX mix) |
| Editorial gates | 8/8 PASS, documentary, semantic True | 8/8 PASS, documentary, semantic True | = |
| CAN_PUBLISH | **True** | True | = |

Notes: VISUAL +0.34 comes from phone_readability/caption checks entering the
group at full score; the composition change did not regress any gate. Style
continuity 54.2 and hook advisories (hook_3_4s 50, hook_strength 55,
info_density check 60) are unchanged advisory-level items also present in the
V9 run. ID probes the shared `assets/` dir (includes other stories' plates) —
pre-existing metric quirk, identical value to baseline.

## 4. Visual frame checks (extracted from `output/noise_cancel.mp4`)

Frames inspected: hook t=2.0s, escalation t=24.0s, late t=44.0s, payoff
t≈53.7s (S06 mid). Extracted from the first V10 render; the audio-only fix
(§2.2) rebuilt the mix — the video stream is deterministic and unaffected, so
the frames represent the final render.

- **Letterbox:** none. The vertical card fills the Shorts band; above/below is
  the blurred-fill backdrop by design (dark, soft), not black bars. blackdetect
  confirms 0 black runs.
- **Kinetic captions:** visible in every frame at the band below the card with
  a scrim; active word carries the orange accent + underline ("NOT BLOCK
  **SOUND**.", "**CREST** MEETS TROUGH,", "SO **A** SECOND"). Chunks are 2–4
  words; word timings are length-weighted estimates within cue windows — sync
  feels aligned on hook/escalation; no drift visible at the payoff.
- **Key numbers:** "30 DB" (payoff) renders large and crisp; labels (DRIVER,
  OUTER MIC, ANTI-NOISE, SUM: SILENCE, RESIDUAL) readable at phone size.
  raster_text QA: 0 clipped, 0 contrast failures; caption_safe_zone 22/22 in
  band.
- **Depth:** glow halo present on flow overlays (S03 `liv2_glow`); living
  overlays now land in card-band coordinates (post-fix).

Findings (non-blocking):
- **Edge-label clipping at frame borders** (V10_VERTICAL tradeoff): landscape
  plates are cover-cropped into the portrait card, so chips at the plate's
  left/right edge can be cut ("EARC…" at t=2s, "…ERFERENCE" at t=24s,
  "…CTING" at t=44s). Center-weighted content (key numbers) is unaffected.
  Mitigation options: plate authoring keeps labels inside the central ~90%
  safe width, or V10 adds edge-aware label pull-in. Left as a documented gap.

## 5. Subject-QA episode (S06 B6_silence_payoff) — evidence trail

- QA run 1: vision judge (deepseek-v4-flash-vision-exp) FAILed S06 3/3 on the
  static plate with `forbidden_found: ["wave trains","new subjects",
  "photographic rendering"]` — while its own `depicted` sentence ("stylized
  earcup-like shape with a flat horizontal line passing through it") matches
  the contract (earcup at rest, flat silence line, calm palette) and supports
  none of the forbidden hits. Judged an echo false-positive on the wrong
  artifact (plate, not rendered frame).
- QA run 2 (after fix §2.3): no FAIL rows (gate True); S04–S06 UNVERIFIED —
  the vision API intermittently returned None (non-blocking by design).
- Direct inspection of the rendered S06 mid-frame (§4 payoff): earcup geometry
  as opening ✓, flat silence line ✓, calm dusk palette ✓, none of the
  forbidden attributes present ✓. Contract satisfied; gate stands.

- QA run 3 (final, corrected render): vision API returned None for all six
  subject checks → all UNVERIFIED (non-blocking by design; UNVERIFIED keeps
  the explicit human-inspection path). Gate stands; subject evidence for this
  run is the direct visual inspection above plus the run-1/run-2 analysis.

## 6. Remaining gaps / notes

- **V10_PUNCT risers under-fire on this story's vocabulary:** risers trigger
  on `shot_type == REVEAL` or `beat_function == ESCALATION`; noise_cancel's
  shots are HOOK/DIAGRAM/SPLIT/EXPLAIN/PAYOFF with no beat_function, so only
  the PAYOFF sub-drop fired (verified in the mix). Mapping the curiosity
  ladder's escalation beats to risers is a design decision left open.
- **Bed notch was a no-op here:** the story's bed plan declares 6×null bed
  files (no music bed by design), so `_notch_beds` had nothing to notch. The
  notch path is exercised on stories with beds only.
- **Caption word timings** are length-weighted estimates within cue windows —
  judge sync feel, not exactness (feels right; no measurable drift).
- **PUNCT risers overlap the previous shot's tail by design** (absolute-t
  `at`), so a riser ending at a shot start crosses the cut.
- **Kinetic carriers** are per-word PNG band strips (~10× cheaper than
  full-frame overlays); regenerated on `--force` (cached hits observed).
- Control A/B (flags-off re-render + QA) skipped per stage brief — the V9
  committed baseline serves as the flags-off control (stage 1 committed only
  flag-gated additive changes; rollback env restores prior paths).

## 7. Verdict

**CAN_PUBLISH: True** (qa8full `--v6`, final run on the fixed render).
V10 is validated end-to-end on `noise_cancel`: native 9:16 composition, kinetic
captions, depth glow, and audio punctuation all active; no gate regressed vs
the published V9 baseline; three integration bugs found and fixed (§2).
