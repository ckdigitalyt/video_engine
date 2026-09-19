# V6 — Motion + Audio Professionalism Pass

**Status:** shipped (engine modules + CLI). Test renders follow.

## Scope (per brief)

P0 — PROFESSIONAL MOTION + AUDIO CONTINUITY. No architecture rebuild, no Manim,
no AI video, no image-model search.

## Files added

| Module | Responsibility |
| --- | --- |
| `engine/motion_v6.py` | Subpixel Bézier/cubic camera trajectories; HOLD primitive; 2× stage with single downsample; per-shot ease resolver. Camera stage is rendered at 2× (`STAGE_W x STAGE_H`) and downsampled once with `lanczos` to the panel — never chains transforms. |
| `engine/motion_qa.py` | Per-shot jitter + direction-reversal scores; returns PASS/FAIL gate. |
| `engine/audio_mix.py` | 3-layer audio mix: continuous bed (crossfaded on change), narration (dominant), shot-specific SFX. Sidechain ducking of the bed under narration (threshold −18 dB, ratio 6:1, attack 20 ms, release 800 ms). Loudness target unchanged (−14 LUFS). |
| `engine/visual_grammar.py` | Subject detection + grammar resolver (AIRCRAFT/BIOLOGY/GEOLOGY/SPACE/HISTORY/PHYSICS/OCEAN/CLIMATE/ENGINEERING/TECHNOLOGY → preferred modes). Suggestion of transformation priority (comparison / scale / timeline / map / cutaway / animation). |
| `engine/planv5.py` | Wraps `planv4`; annotates each shot with `visual_grammar.subject` + `visual_grammar.recommended_mode`; writes default `audio_bed_plan.json` if absent. |
| `engine/composev5.py` | V4 renderer + `motion_v6` camera + `audio_mix` 3-layer mix. |
| `engine/qa5.py` | V4 results + `motion_smoothness` + `audio_continuity` + 9-question human-editor test. CAN_PUBLISH vetoes on any obvious motion tremble OR any obvious audio restart. |

## CLI

```
python cli.py plan5  --story <id>     # v4 + grammar
python cli.py render5 --story <id>    # Bezier motion + 3-layer audio
python cli.py qa5    --story <id>     # V6 QA + editor test
```

## How the P0 fixes land

**Smooth motion (P0).** `motion_v6.camera_filter` writes a single zoompan
filter whose `z` / `x` / `y` are closed-form expressions in the linear
progress `p = clip(on/(N-1), 0, 1)`, eased by a cubic / smoothstep / cubic
Bézier basis. Frame `n` is computed by the ffmpeg expression evaluator;
coordinates stay floating point until rasterization. The camera stage is
`STAGE_W x STAGE_H` (2× of the panel); the single downsample to
`PANEL_W x PANEL_H` uses `lanczos`. The source plate PNG is the only input —
no chained transforms.

**Never transform a transformed frame (P0).** Filter graph:

```
[0:v] scale=CONTENT_W:CONTENT_H:flags=lanczos
     pad=CANVAS_W:CANVAS_H:0:CANVAS_PAD_Y:color=black
     zoompan=z='…':x='…':y='…':d=N:s=STAGE_WxSTAGE_H:fps=30
     scale=PANEL_W:PANEL_H:flags=lanczos
     setsar=1
```

**Motion smoothness QA (P0).** `motion_qa.motion_smoothness` samples the
trajectory at 240 evenly-spaced progress values, computes velocity /
acceleration / direction reversals, and emits per-shot
`motion_jitter_score` and `motion_direction_reversal_score`. A shot with
`motion_jitter_score < 60` OR `reversals >= 3` fails the V6 gate.

**Static shots may remain static (P0).** The `HOLD` primitive returns the
camera at the `from` position for the entire shot. `motion_qa` treats
HOLD as zero-motion (structural note in the row).

**3-layer audio (P0).** `audio_mix.mix` accepts narration beats, per-shot
bed file list, SFX list, shot durations, and the total length. It produces:

1. ONE continuous bed (acrossfade on planned changes; silence pad on
   unplanned gaps; brief spec 300–1000 ms, default 600 ms).
2. SFX laid onto a full-duration silence track at `at` seconds.
3. Narration concatenated with a small (0.2 s) pad between beats.
4. The three layers mixed with **sidechain ducking** of the bed under
   narration. Final loudnorm `I=-14:TP=-1.5:LRA=11` matches V4.

**Audio continuity (P0).** `audio_mix.audio_continuity` reports per-shot
bed transitions, gaps (bed stops where it shouldn't) and restarts (bed
file changes). Any gap fails the V6 gate; planned changes pass.

**V6 QA (brief).** Keeps the V4 groups + metrics. Adds exactly two
checks: `motion_smoothness` and `audio_continuity`. No new QA framework.

**9-question human editor test (brief).** Q1–Q2 from motion measurements;
Q4–Q5 from audio continuity. Q3/Q6/Q7/Q8/Q9 are already covered by
raster / loudnorm / style / alignment / density / phone QA — surfaced
as `human_editor_v6.note`.

## CAN_PUBLISH

```
V6: V5 gates
   AND motion_smoothness (mean_jitter >= 80, no obvious tremble)
   AND audio_continuity (no bed restart, no gaps)
   AND 9-question human-editor test
```

## Test plan (brief §NEXT TEST)

1. Pick 3 unrelated science/technology topics (45–60 s each).
2. Run `plan5` → `render5` → `qa5` on each.
3. Report per video: Technical, Visual, Editorial, Factual, Motion
   smoothness, Audio continuity, Narration/visual alignment, Phone QA,
   CAN_PUBLISH.
4. List TOP 3 HUMAN-EDITOR CONCERNS per video.
5. Hold publish if any test exposes a concrete limitation.
