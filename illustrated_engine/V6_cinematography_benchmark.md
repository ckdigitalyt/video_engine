# V6 Cinematography Benchmark — Decision Report

Date: 2026-09-05
Engine: `illustrated_engine` (PIL procedural + FFmpeg), ARM CPU-only, $0
Status: **All enhancements implemented behind flags; smallest-recommended set validated end-to-end and KEEP**; others kept as opt-in flags.

## 1. What was built

Three enhancements implemented engine-side, all default-off, all behind env flags with CAS tokenization so the baseline hash is byte-identical:

| Flag | Effect | Where it lives |
|---|---|---|
| `CAMERA_PROFILE=eased` | Re-evaluates every non-HOLD shot's camera progress with a C2 quintic smoothstep (zero velocity AND zero acceleration at the endpoints) instead of the authored per-shot curve. Baseline curves (EASE_IN / OUT / IO / BEZIER) remain reachable for explicit authoring. | `engine/flags.py` (profile) → `engine/motion_v6.py` `_profile_p_e` and `_pe_numeric` |
| `ENABLE_PARALLAX` | Card shots with a non-HOLD camera (and **not** an opening or end-card shot) get a damped-rate ambient background layer (`damp = 0.85` by default, `PARALLAX_DAMP` overridable). The card plate keeps the authored camera — text is provably untouched. | `engine/motion_v6.py` `ambient_parallax_filter` + `engine/composev5.py` card branch |
| `ENABLE_BLOOM` | Restrained multi-pass PIL bloom on luminous *kinetic* frames only. Bright-pass → 2-pass blur (radius 8) at **¼ resolution** → screen-DELTA composed back onto the full-resolution original so the base keeps full sharpness. Final mask confines the delta to bright neighbourhoods. | `engine/effects.py` `bloom` + `bloom_dir` + `engine/composev5.py` kinetic branch |

Title/end-card shots (whose baked-in display title and end mark live in the ambient layer) are explicitly excluded from parallax so the brand mark cannot drift relative to the card.

CAS safety: every flag combination is hashed into `_shot_hash` (`engine/composev5.py`). Baseline artifacts therefore keep the same hash, so turning flags off returns to byte-identical shots. Production stays baseline unless the operator opts in.

Constraints respected: no new rendering engine (PIL + FFmpeg only), no new dependencies, ARM CPU only, deterministic, $0 cost.

## 2. Benchmark design (brief §1–§2)

Three representative scene types, each from the production `build/edit_plan.json` so the source VisualSpecs are identical across all 8 variants. Run order: data → technical → space (sequential to keep CPU timings clean). Wall + CPU seconds + utilization per render; `ffprobe` for size/res/fps; `ffmpeg freezedetect` + `blackdetect` for QA; 5-frame `PIL ImageStat` (luma, RMS contrast, FIND_EDGES energy) for objective frame metrics; `motion_qa._score_shot` on the camera spec. Strips: 8 mid-frames per scene for visual review.

| Scene | Story | Shot | Camera | Type |
|---|---|---|---|---|
| space | blackhole_clocks | S02 (6.94 s) | kinetic clocks | kinetic / luminous |
| data | mitochondria_dna | S02 (7.62 s) | 1.20→1.35 zoom, 1 number pop | card |
| technical | aircraft_wing_lift | S09 (8.01 s) | 1.16→1.0 zoom-out, label-heavy | card |

8 variants: `baseline`, `cam`, `par`, `bloom`, `cam+par`, `cam+bloom`, `par+bloom`, `all`.

Bugs caught and fixed by the harness during the loop:
1. **Shot-ID collision** — two stories have an S02. The first pass put both at `bench_shots/S02__baseline.mp4` and the data/space strips cross-contaminated. Fixed: `bench/bench_v6.py` now prefixes with the story id.
2. **Bloom v1 was a no-op** — `threshold=190` never fired on the blackhole clock strokes; v1 cost 2.18× for a 0.02-luma delta. Retuned: `threshold=160`, `strength=0.28`, computed at ¼ resolution, screen-DELTA applied on the full-res original.

## 3. Results (final clean re-run, 24 renders + full-pipeline validation)

Numbers are `wall / baseline_wall` (cost ratio). B = baseline, C = cam, P = par, BL = bloom. QA: `black=False` everywhere, `freeze=baseline=True` and `freeze=par-variant=False` (parallax actually breaks the freezedetect on near-static card shots — it's adding real motion), `motion_qa.jitter=100.0` both profiles.

### space (S02 blackhole, kinetic — HOLD camera)
| var | cost | cpu% | dLuma | dCon% | dEdge% | notes |
|---|---|---|---|---|---|---|
| baseline | 1.00× (43.93 s) | 184 | 0 | 0 | 0 | — |
| cam | 0.94× | 194 | 0 | 0 | 0 | HOLD camera → quintic no-op (by design) |
| par | 0.94× | 195 | 0 | 0 | 0 | HOLD camera → parallax no-op (by design) |
| **bloom** | **1.55× (68.09 s)** | 158 | **+0.50** | **+1.7** | 0 | glow now fires; contrast up, edges unchanged → restrained |
| cam+par | 0.94× | 196 | 0 | 0 | 0 | no-op |
| cam+bloom | 1.55× | 158 | +0.50 | +1.7 | 0 | |
| par+bloom | 1.56× | 157 | +0.50 | +1.7 | 0 | |
| all | 1.55× | 158 | +0.50 | +1.7 | 0 | |

### data (S02 mitochondria, 1.20→1.35 zoom)
| var | cost | cpu% | dLuma | dCon% | dEdge% | notes |
|---|---|---|---|---|---|---|
| baseline | 1.00× (53.20 s) | 179 | 0 | 0 | 0 | freeze=True |
| cam | 1.03× | 176 | 0 | −0.1 | +14.8 | edges shift = different sampled framing |
| **par** | **1.08× (57.41 s)** | 163 | **−6.93** | **+1.8** | −1.9 | **freeze=False** — real motion breaks freezedetect |
| bloom | 1.01× | 178 | 0 | 0 | 0 | card shot → bloom is a no-op (by design) |
| cam+par | 1.09× | 162 | −6.93 | +1.8 | +9.3 | |
| cam+bloom | 1.04× | 174 | 0 | −0.1 | +14.8 | |
| par+bloom | 1.08× | 163 | −6.93 | +1.8 | −1.9 | |
| all | 1.11× | 160 | −6.93 | +1.8 | +9.3 | |

### technical (S09 aircraft, 1.16→1.0 zoom-out)
| var | cost | cpu% | dLuma | dCon% | dEdge% | notes |
|---|---|---|---|---|---|---|
| baseline | 1.00× (56.61 s) | 167 | 0 | 0 | 0 | |
| cam | 0.99× | 167 | −0.05 | 0 | +3.3 | |
| **par** | **1.09× (61.98 s)** | 150 | **−0.35** | **+0.4** | +0.3 | **freeze=False** |
| bloom | 1.01× | 165 | 0 | 0 | 0 | card shot → bloom no-op (by design) |
| cam+par | 1.08× | 150 | −0.42 | +0.3 | +3.0 | |
| cam+bloom | 1.00× | 166 | −0.05 | 0 | +3.3 | |
| par+bloom | 1.10× | 150 | −0.35 | +0.4 | +0.3 | |
| all | 1.07× | 152 | −0.42 | +0.3 | +3.0 | |

### Objective parallax proof (no-render pixel test on the data shot)
Pure-ambient strip (y 0..170 — above the card at y 176) frame diff t=0.5 vs t=6.5:
- baseline: **0.0000** (the ambient is bit-static in the base pipeline)
- par: **1.439** (the damped-rate ambient layer is measurably moving)

### Motion-QA (mito S02, raw values)
| | mean_speed | max_speed | high_freq_energy | reversals | jitter |
|---|---|---|---|---|---|
| baseline | 0.000387 | 0.000581 | 0.000207 | 0 | 100.0 |
| eased | 0.000387 | 0.000726 | 0.000300 | 0 | 100.0 |

Zero reversals, jitter 100 both, no regression. (The eased max/high_freq are slightly higher because the quintic has a steeper mid-section — same trajectory length, no settling snap, no motion defect.)

### Full-pipeline validation (brief §9)
Re-rendered **aircraft_wing_lift** end-to-end with `ENABLE_PARALLAX=1` (out_name `aircraft_wing_lift_parallax_test.mp4`, CAS hashes diverge so all 9 shots re-render), then ran `qa5full`:

| | result |
|---|---|
| CAN_PUBLISH | **True** |
| TECHNICAL | 100.0 |
| VISUAL | 95.0 |
| EDITORIAL | 95.91 |
| audio_completion | narration_end=52.52 s, video_margin=4.41 s, stem_tail=−180 dBFS |
| overlay_compliance | events=6, plate_pulses=3, dedup_suppressed=3, violations=0 |
| caption_safe_zone | captions=20, in_band=20, band=1350..1520 |

Top-3 human-editor concerns are unchanged from the baseline snapshot (style_continuity 50, hook_strength 55, …) — they are pre-existing narrative-style concerns, not introduced by the flag.

## 4. Decision (brief §11)

| Enhancement | Visual gain | Render cost | QA impact | Decision |
|---|---|---|---|---|
| Camera (quintic eased) | subtle in stills; smoother start/stop by construction (C2) | ~1.00× (free) | none (jitter 100, no reversals) | **KEEP** (free, no regression; recommend production default-on after spot check) |
| 2.5D Parallax | measurable depth (ambient strip diff 0 → 1.44); background tighter on card shots; **freeze-gate actually improves** | 1.08–1.09× on card shots; 0× on HOLD/kinetic/opening/end-card | none; freeze→False on near-static baselines | **KEEP** (within 15% budget; title/end-card guard installed after strip review) |
| Bloom (kinetic only) | restrained glow on luminous strokes (dLuma +0.50, dCon +1.7% UP — no wash) | 1.55× on the 1–2 kinetic shots per story ≈ +6–12% per full story; 1.01× no-op on card shots | none (contrast up, edges unchanged, no halo) | **KEEP but scoped** — opt-in for space-class stories; default OFF on data/technical where it’s a no-op |
| Camera + Parallax | additive depth + smoother | 1.08–1.09× | none | **KEEP** (recommended production set) |
| Parallax + Bloom | 1.08–1.55× per scene | — | — | KEEP only if story has kinetic luminous content |
| All combined | 1.07–1.55× | — | — | KEEP only for space/luminous stories |

Smallest set that produces a clear, repeatable improvement: **CAMERA_PROFILE=eased + ENABLE_PARALLAX** (≤ 1.09× worst case, zero QA regressions, full-pipeline aircraft render passes qa5full). Add `ENABLE_BLOOM=1` for stories with luminous kinetic shots.

## 5. Caveats and known limitations

- **Strip resolution.** The 8-tile comparison strips are 360×640 per tile — subtle framing/edge effects may not be obvious at that size. Objective metrics above carry the load.
- **Bloom verdict at 1.55×.** Per the brief's "reject if render time increases by >15% unless the visual improvement is clearly substantial" rule, the per-shot number is over budget. Scoping bloom to kinetic shots only brings the per-story impact to ~+6–12% (within budget). Documented as opt-in, not default.
- **Freezedetect interaction.** `freeze=True` on `baseline` for the data and technical shots is a property of the strict detector (`n=0.003`) on near-static subtle motion, not a regression; it flips to `False` on the parallax variants.
- **Production scratch files.** `build/edit_plan.json` and `build/qa/qa5_aircraft_wing_lift.json` were briefly replaced to drive the validation; both restored from `/tmp/qa5_aircraft_baseline_backup.json` and the mito bench plan afterwards. Production `output/<story>.mp4` files were never touched (the validation used a separate `out_name`).
- **Mito and blackhole full-pipeline parity.** The full qa5full run was on aircraft. The shot-level matrix covers the same mechanisms on all three stories (1.08–1.11× on the data + technical card scenes, no-op on the kinetic space scene with HOLD camera); the recommended production set is recommended across the board, but if a strict §9 reading is required for mito and blackhole, that's a ~25 min background run per story (we can run on request).
- **§6 (primitives).** `stories/_v6_cardlib.py` already exists and is shared across stories. The benchmarking did not surface any *rendering* duplication that warranted a new extraction pass; deferred per the brief.

## 6. Files

- Engine: `engine/flags.py`, `engine/effects.py`, `engine/motion_v6.py`, `engine/composev5.py`
- Bench: `bench/bench_v6.py`
- Plans (one per story, captured pre-matrix): `bench/plans/{blackhole_clocks,mitochondria_dna,aircraft_wing_lift}.json`
- Per-render metrics: `bench/results/<scene>__<variant>.json` (24 files)
- Matrix summary: `bench/results/matrix.json`
- Visual strips: `bench/results/strip_{space,data,technical}.png` (technical was captured in the first pass; the artifact-name fix in the second pass preserved the strip file)
- Full-pipeline validation output (kept for reference, not for production): `output/aircraft_wing_lift_parallax_test.mp4`

## 7. Production bake-in (2026-09-06, operator approved)

The §11 recommendation was accepted and executed. `engine/flags.py` defaults flipped:

- `CAMERA_PROFILE` default: `baseline` → **`eased`** (C2 quintic on all non-HOLD shots)
- `ENABLE_PARALLAX` default: off → **on** (damped 0.85 ambient layer on moving card shots; opening/end-card still excluded)
- `ENABLE_BLOOM`: **stays opt-in** per story (`ENABLE_BLOOM=1`) — scoped to space-class content per §4
- Production CAS token is now `cameased-par085` — every shot re-renders under the new token
- Rollback / AB preserved: `CAMERA_PROFILE=baseline ENABLE_PARALLAX=0` → token `""` → byte-identical pre-flag baseline artifacts (verified)
- Pre-bake backups: `/tmp/prod_baseline_20260906/` (3 production mp4s + qa5 QA snapshots)
- Sanity verified: `DEFAULT: eased+parallax (cameased-par085)`, `ROLLBACK: baseline (token "")`, `BLOOM opt-in: cameased-par085-bloom`

## 8. Bake-in re-validation (in progress)

All three stories re-rendered with baked defaults via plan5 → render5 → qa5full (sequential, ≤20-min watchdog-safe chunks). Results recorded here on completion.
