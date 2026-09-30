# WP8 acceptance: image chain (DESIGN.md §6, §15.2 WP8)

Scope this run: WP8 only (re-sequenced ahead of WP5/WP11-14 — it blocks
*any* render from passing the License hard gate, not just robustness work).
No full pipeline render was run for this WP (the owner's 2-video render cap
is not spent here, per this run's instructions) — the chain is proven with
unit/fixture tests, a live Cloudflare benchmark, and a few individual real
plate generations through the actual production function
(`engine.v15_plates.generate_plate`).

## What changed (see CHANGELOG.md "WP8" for the full list)

- New providers in `src/providers/image_gen.py`: `CloudflareWorkersAIProvider`
  (DESIGN §6.1 tier 3), `SDCppLocalProvider` (tier 5, owned floor),
  `ArchiveProvider` (tier 2, PD/CC0 — NASA Images + Met Open Access).
- `nvidia_nim`/`siliconflow`/`hf_serverless` marked `benchmark_only = True`
  (new `ImageGenProvider` attribute) — excluded from
  `ImageGenFactory.production_available()`, still fully usable by name for
  `scripts/benchmark_image_gen.py`/`tools/image_capability_audit.py`.
- New `configs/images.yaml`: `image_gen.chain.production` = `[archive,
  cloudflare_workers_ai, gemini_image, sdcpp_local, pollinations]` (DESIGN
  §6.1 order — NIM is gone; a `commercial_ok:true` source now runs first).
- `illustrated_engine/engine/v15_plates.py`: `PROVIDER_ORDER` reads the
  config (hardcoded tuple is the fallback only); Pollinations watermark
  crop before normalize/OCR/QA; `providers_for_beat_function` drops
  Pollinations for HOOK/PAYOFF beats; `cloudflare_available`/
  `low_plate_mode`/`image_chain_report` for preflight visibility.
- `illustrated_engine/engine/v15_pipeline.py`: wires the hero-shot
  Pollinations exclusion and `report["image_chain"]`.
- `illustrated_engine/engine/v16_manifest.py`: licence rows for the 3 new
  providers (`cloudflare_workers_ai`/`sdcpp_local`/`archive`, all
  `commercial_ok: true`); fixed a pre-existing bug found while adding them
  (`ai_generated` was hardcoded `True` for every plate row, which would
  have mislabelled real archival photos — see below).
- New `illustrated_engine/tools/plate_library.py` (DESIGN §6.2 cron job).

## Absent-creds clean-skip test

```
$ source venv/bin/activate
$ python3 -m pytest -q tests/test_wp8_image_chain.py::TestCloudflareAbsentCreds
```

4 tests: `is_available()` is `False` with no/partial creds; `generate()`
raises a clean `RuntimeError` naming the missing env vars (never "Bearer",
i.e. never echoes anything key-shaped) instead of crashing or prompting for
a key; `is_available()` is `True` once both vars are set; a simulated chain
loop (archive → cloudflare_workers_ai → gemini_image) with no Cloudflare
creds correctly records `{"provider": "cloudflare_workers_ai", "error":
"unavailable"}` and moves on rather than raising out of the loop. All 4
PASS.

## Mock HTTP test

```
$ python3 -m pytest -q tests/test_wp8_image_chain.py::TestCloudflareMockHTTP tests/test_wp8_image_chain.py::TestArchiveProvider
```

Cloudflare: a mocked `_multipart_post` returning the real observed response
shape (`{"result": {"image": "<base64>"}}`) round-trips through
`generate()` into a written file; a mocked error-shaped response
(`{"success": false, "errors": [...]}`) raises `RuntimeError` rather than
writing a broken file. Archive: mocked `urllib.request.urlopen` responses
for both the NASA Images API and the Met Open Access API shapes (including
the Met `isPublicDomain: false` case, which must NOT match — proving the PD
gate is real, not decorative). All PASS (see full count below).

## Watermark-crop test

```
$ python3 -m pytest -q illustrated_engine/tests/test_wp8_plates_chain.py::TestWatermarkCrop
```

3 tests: `_crop_watermark` removes the configured bottom fraction (proven
on a synthetic image, exact pixel-dimension check); a synthetic "watermark"
stamped in the bottom strip (matching `v15_plates.OCR_STRIPS`' own bottom-7%
read region) is provably cropped away, not just resized past; a full
`generate_plate()` run through a fake `gemini_image` provider proves the
crop step is called ONLY when the winning provider is `pollinations`, never
for any other provider. All PASS.

## Live proof: does the reordered chain now produce `commercial_ok:true` plates?

**Yes**, both times tried. Two real shot prompts were built from the actual
`stories/tunguska_1908` brand bible (the same story WP10's FAIL render
used) and run through the real, unmodified `engine.v15_plates.generate_plate()`
— the exact function `v15_pipeline.run_pipeline` calls per shot, not a
standalone reimplementation:

```
$ cd illustrated_engine && source ../venv/bin/activate
$ python3 -c '... see CHANGELOG.md WP8 entry for the exact script ...'
PROVIDER_ORDER: ('archive', 'cloudflare_workers_ai', 'gemini_image', 'sdcpp_local', 'pollinations')
{
 "subject": "a 1908 Siberian taiga forest flattened radially outward, tre",
 "ok": true, "provider": "cloudflare_workers_ai", "commercial_ok": true,
 "attempts": [{"provider": "archive", "error": "archive: '...' has no concrete real-object/place keyword hint ..."}]
}
{
 "subject": "a fireball meteor streaking across the dawn sky over Siberia",
 "ok": true, "provider": "cloudflare_workers_ai", "commercial_ok": true,
 "attempts": [{"provider": "archive", "error": "archive: no PD/CC0 match for 'fireball meteor streaking across siberia'"}]
}
```

Both plates: `archive` correctly declined (no keyword hint on the first —
an abstract-ish composed scene, not a museum/NASA object; no search match
on the second) and fell through cleanly to `cloudflare_workers_ai`, which
produced a real, on-brand, watermark-free, correctly-graded (LUT applied,
`lut_sha256` present) plate — `illustrated_engine/build/cache/v15_plates/
18688edb0c24453c.png` is the flattened-forest plate; visually verified,
matches the tunguska_1908 sepia archival-engraving style exactly, correct
subject, no garbled text, no watermark. **WP10's real render (pre-WP8) got
0/18 `commercial_ok:true` plates (16 nvidia_nim + 2 pollinations, all
`false`); this run's 2/2 real generations both landed `commercial_ok:true`.**
This is not a full-video proof — it is the concrete mechanism WP10's FAIL
traced the License problem to, now shown working on the same story.

### 4-prompt Cloudflare benchmark (DESIGN §6.2: "WP8 starts with a 4-prompt benchmark using the Phase 2 house prompts")

Real Phase 2 house prompts (`research/phase2/qa_prompts.json`, the same 4
used for every other provider's Phase 2 benchmark in RESEARCH.md §5.1),
through `CloudflareWorkersAIProvider` directly, 720x1280, distinct seeds:

| # | ok | seconds | bytes |
|---|----|---------|-------|
| 1 | yes | 20.36 | 769,228 |
| 2 | yes | 19.71 | 447,886 |
| 3 | yes | 23.87 | 665,215 |
| 4 | yes | 12.53 | 635,864 |

4/4 succeeded. **12.5-23.9 s/image** — slower than NIM's ~3.1-3.3 s
(RESEARCH.md §5.1), but easily fast enough for live per-shot generation
(vs. the ~20 min/image local sd.cpp floor) and, unlike NIM, `commercial_ok:true`.
Output correctly sized (720x1280 confirmed via PIL on a separate check),
correct house sepia-engraving style, no watermark, no garbled text (sample
`~/phase4_out/wp8/cloudflare_bench/1.png` — a constellation-of-satellites-
over-Earth image that matches the requested subject precisely).

**Neuron cost per image**: still **[U]** — the Cloudflare dashboard's usage
page was not checked this run (would need the owner's account access
beyond the API token already in `.env`); RESEARCH.md §5.1's estimate
("roughly 200-400 images/day free") stands unverified, flagged, not
re-guessed.

## sd.cpp local provider — not live-exercised this run (flagged, deliberate)

RESEARCH.md §5.3 measured **~1,237 s (~20.6 min) per image** on this CPU at
576x1024 — a real generation here would cost ~20-40x more wall time than
everything else in this WP combined for one data point. `SDCppLocalProvider`
is implemented against the real, verified `sd-cli` CLI flags (checked live
via `sd-cli --help` and `docs/flux2.md`'s own worked example) and against
the real model files already on disk (`~/models/sdcpp/build/bin/sd-cli`,
`~/models/flux2klein/*.gguf`, confirmed present) — `is_available()` and the
constructed command line are unit-tested with a mocked `subprocess.run`
(`tests/test_wp8_image_chain.py::TestSDCppLocal`, 4 tests, all PASS,
< 1 s total). A real end-to-end sd.cpp generation is not part of this
run's acceptance; recommend running one manually (`venv/bin/python3 -c
"from src.providers.image_gen import SDCppLocalProvider as P;
P().generate('...', 'out.png', width=720, height=1280)"`, ~20 min) before
relying on it in a live low-plate-mode render.

## Low-plate mode — scope decision (flagged, not silent)

DESIGN §6.2: "The plan switches to low-plate mode: <=6 generated hero
plates per video, and everything else from reuse, archive and plate-free
templates." Implemented as a **pure budget/reporting layer**
(`v15_plates.cloudflare_available`/`low_plate_mode`/`image_chain_report`,
wired into `v15_pipeline.run_pipeline`'s report) — visible to an operator
or a future batch preflight exactly as DESIGN §6.2 asks. **Not implemented
this pass**: actually capping the number of *successful* generation calls a
render makes and routing the overflow to reuse/plate-free templates would
require plan-stage changes (which shots get a template that needs no
plate, which reuse a cached plate) that are `v16_plan.py`/scheduling
territory, not the image-provider-layer scope this WP's file list
(`src/providers/image_gen.py`, `configs/images.yaml`,
`tools/plate_library.py`) covers — and risk shipping a half-tested demand-
reduction behaviour under this WP's "no full render" constraint. Same
deferred-wiring precedent WP7 (planner v2) and WP9 (beat-snapped cuts) set
for their own scope boundaries.

**What this means for "a video completes with Cloudflare absent"**: since
Cloudflare being unavailable just means that chain tier's `is_available()`
returns `False` and the existing per-provider try/except loop moves on
(exactly like every other tier already does), a video **does** still
complete without Cloudflare today — the chain has 4 remaining tiers
(archive, gemini_image, sdcpp_local, pollinations) plus the existing V14
procedural floor. What is **not yet true** without Cloudflare: a
CPU-bound sd.cpp floor makes per-shot generation impractical at ~20
min/image, archive only covers real-object/place subjects, and Gemini/
Pollinations are both `commercial_ok: false` — so **for this channel's
typical topics (deep-time/physics spectacle), most shots without
Cloudflare would still land on a `commercial_ok:false` provider** and the
License gate would legitimately HOLD, same as WP10 found, just for a
narrower reason (Cloudflare down, not "wrong tier order"). This is the
DESIGN-sanctioned fallback: "or clearly report that no commercial_ok:true
path exists yet" for the no-Cloudflare case specifically.

## Test suite

```
$ source venv/bin/activate
$ python3 -m pytest -q tests/test_wp8_image_chain.py
24 passed in 2.6s

$ cd illustrated_engine && source ../venv/bin/activate
$ python3 -m pytest -q tests/test_wp8_plates_chain.py
21 passed in 3.7s

$ python3 -m pytest -q tests/                      # illustrated_engine/tests, full
190 passed in 74.4s   (169 before WP8 + 21 new, 0 regressions)
```

Root `tests/` (separate invocation, per the WP acceptance ritual): diffed
against a clean worktree of pre-WP8 HEAD (`98a3267`):

```
baseline (clean worktree, 98a3267): 58 failed, 1259 passed, 8 skipped, 5 errors (282.4s)
after   (this tree, WP8 applied):   58 failed, 1287 passed, 4 skipped, 5 errors (352.5s)
```

63 failing IDs (58 FAILED + 5 ERROR) both before and after — `diff` of the
sorted, sanitised ID lists is **empty**: identical set, zero new failures,
zero fixed. The passed/skipped delta (1287 vs 1259 passed, 4 vs 8 skipped)
is exactly `+28 passed / -4 skipped`: `+24` from this WP's own new test file
plus a `+4`/`-4` order/network-dependent skip swing in the pre-existing
suite — the same "order/network noise" pattern WP7's acceptance report
documented, not a WP8 effect (the failing-ID diff above is what actually
proves no regression).

## Secret scan / `.env`

`git diff` across every changed file, grepped for the standard key-prefix
patterns (`sk-or-v1-`, `AIzaSy`, `hf_...`, `nvapi-`, `gsk_`, `xai-`,
`sk-ant-`, `sk-proj-`) plus `CLOUDFLARE_API_TOKEN=`/`CLOUDFLARE_ACCOUNT_ID=`/
`NVIDIA_API_KEY=` literal-assignment shapes: **clean, zero hits**. `.env`
and every `.env.bak*` file: untouched (`git status`/`git diff --stat`
confirm no changes). The live Cloudflare/NASA/Met calls this run made read
credentials from the environment via `os.environ.get` exactly like every
existing provider; nothing was printed beyond masked length checks
(`len=N`) during investigation, never a value or a prefix.

## Housekeeping

`~/phase4_out/wp8/cloudflare_bench/` kept (4 small PNGs + result.json, a
few MB). `/tmp/wt_wp8_baseline` worktree removed after use. No large work
dirs created this run (no full render).

## Next

Per `scripts/phase4_driver.sh` re-sequencing: whichever WP comes after WP8
(WP5/WP11-14, owner's call) — this run's brief says STOP after WP8.
