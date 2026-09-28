# RESEARCH.md: Phase 2 research and benchmarks

Branch `shorts-v3`. Author: Claude Code (Opus), 2026-09-27/28. Server: Oracle ARM aarch64, 4 vCPU, 24 GB RAM, no GPU.

Scope:
- The original Phase 2 brief, as modified by the owner's decisions on AUDIT.md (Fish stays primary, NIM is not approved for production, GLM leaves the required LLM path, run one fresh timed e2e).
- AUDIT.md findings are taken as ground truth and are not re-derived here.
- **No pipeline code was modified.** All scripts written for this phase live in `research/phase2/` and write their outputs to `~/phase2_out/`, outside the repo. Models downloaded for benchmarking are in `~/models/`.

Evidence labels (same as AUDIT.md):
- **[M]** measured on this server during this phase.
- **[V]** verified from a primary source (live API response, vendored licence text, official docs page), quoted where it matters.
- **[S]** secondary source (vendor or marketing blog). Treat these as directional only.
- **[U]** unverified or inferred; needs a check before anyone relies on it.

---

## 0. TL;DR: one recommendation per component

| Component | Recommendation | Key evidence |
|---|---|---|
| **Voice (primary)** | Keep **Fish Audio `s2.1-pro-free`**. Switch to its **`/v1/tts/stream/with-timestamp`** endpoint, which returns word timestamps on the free model. | Live call OK, RTF 0.53–0.60 [M]. Word timestamps are within a median 60 ms of whisper [M]. **Commercial use is NOT clearly permitted on the free tier** (§3.2). This needs an owner decision. |
| **Voice (fallback)** | **Kokoro-82M v1.0, fp32 ONNX, voice `am_michael`**, run locally (Apache-2.0). Switch the whole video, never mid-video. | RTF 0.65, 0.7 GB RSS, WER 0.0 on the round-trip test [M]. Chatterbox is 8–23x slower (RTF 5.2 / 15.2), uses 6–7 GB RSS and has misreads [M]. Not recommended for V15. |
| **Word alignment / captions** | **Fish-native timestamps** first. **faster-whisper `base.en` int8** as the universal aligner (fallback voices) and as a narration round-trip QA check. | V15's silence-based timing is off by p50 0.15–0.20 s and p90 ~0.45 s (max 1.1 s) against whisper [M]. base.en runs at RTF 0.27 and 0.4 GB, WER 0.0 on Fish narration [M]. |
| **2D animation / motion graphics** | Stay on **Remotion** (licence OK for ≤3-employee companies). Add **`@remotion/lottie`** plus a kinetic-typography component set. **Render one composition per video** instead of one render per scene. | Lottie and spring-animated type render correctly on aarch64 [M]. A 10 s composition costs 36 s against a 24.5 s floor for a 1 s one [M]. V15 pays that floor 17 times per video: 431 s of render for 56 s of output [M]. |
| **Illustration source** | **Hybrid built on one model, FLUX.2-klein-4B (Apache-2.0):** (1) **Cloudflare Workers AI** klein as the fast primary, using the free 10k neurons/day **[U: needs an owner account and a benchmark]**. (2) **Local klein via stable-diffusion.cpp** as the owned emergency floor and idle-time plate-library builder. (3) **CC0/PD archives**, plate reuse and motion-graphics scenes to cut plate demand. Pollinations is a watermark-checked last resort only. | Local klein matches NIM quality but takes **1,237 s per image vs NIM's 3.3 s**, with 8.5 GB RSS [M], so it is not a per-video source on this CPU. SD-Turbo takes 205–258 s and is off-prompt [M]. SiliconFlow 401, HF 410 Gone and Gemini-image 429 are **dead today** [M]. Pollinations watermarks every anonymous image [M]. |
| **Music** | A curated **YouTube Audio Library** set (monetisation-safe per YouTube, not claimed by Content ID [V]), tagged by mood, plus an in-house procedural **signature sting**. | Pixabay tracks can be Content-ID-claimed [S]. MusicGen weights are CC-BY-NC, so excluded [S]. Stable Audio Open Small is not benchmarked [U]. |
| **SFX** | **Kenney CC0 packs** plus the **Sonniss GDC bundles** (royalty-free, monetised YouTube explicitly allowed [V]) and the Freesound CC0 filter. Record each file in the licence manifest. | §7 |
| **LUT grading** | A brand `.cube` **generated in code** (`research/phase2/make_lut.py`), applied **to plates at ingest** rather than to the whole frame, so brand typography hexes stay exact. The ffmpeg `lut3d` final pass is the alternative. | `lut3d` costs +29 s filter time (+69 s in a full re-encode) per 56 s video [M]. A whole-frame LUT also shifts caption and accent colours [M, visual]. |
| **Automated quality scoring** | **PySceneDetect** for cut cadence and holds, **faster-whisper** round-trip WER, ffmpeg `ebur128`, and a **vision-LLM judge through the adapter**. Exclude pyiqa (PolyForm Noncommercial). | PySceneDetect found exactly the 17 real shots in 15.9 s [M]. Claude's plate QA caught a **Pollinations watermark and garbled text** that shipped in a PASS video [M]. |
| **LLM adapter (Phase 3 input)** | Claude CLI as default. It is format-compliant on both real V15 calls. GLM also passes. Gemini free tier is **20 req/day/model** and was exhausted by a single e2e run plus this comparison [V]. | §9 |

**Top findings that change priorities:**
1. **The V15 plate fallback chain is 3/5 dead.** SiliconFlow returns 401, HF `hf-inference` returns **410 Gone**, and Gemini-image returns 429. Only NIM and Pollinations produced images [M].
2. **Plate QA silently skipped in the fresh e2e run, and the video still PASSED** with a watermarked plate and a garbled-text plate in the timeline. The garbled text is visible **behind the hook headline at t=1 s** [M]. See §2.3.
3. **The OAuth token for YouTube upload is dead** (`invalid_grant`). Uploads would fail today, and the owner must re-authorise interactively [M].
4. **The channel's current V15-style Shorts get a median of 56 views**, against 1,043 for the May-2025 dinosaur series and 372 for the Jan-2026 batch [M]. §10.

---

## 1. Security notes (read first)

- **Gemini API key partially exposed in this session's log.** During the channel research I tried the Gemini key against the YouTube Data API as an API-key fallback. The Google client library put `key=…` in the request URL, and the 401 error message echoed that URL into this session's tool output.
  - The script now redacts it (`research/phase2/yt_channel.py`).
  - **Recommend rotating `GEMINI_API_KEY`** because the session log (`~/.claude/projects/...`) now contains it. This is not a repo file.
  - `client_secret.json` and `token.json` were never read or printed. They were only loaded programmatically.
- **YouTube OAuth refresh token is invalid** (`RefreshError: invalid_grant`). I did not attempt a new consent flow, as instructed. Phase 5's upload path needs the owner to re-run the consent step.
  - The token was upload-scope only anyway. Phase 3's analytics feedback loop needs `yt-analytics.readonly` added in the same re-consent.
  - If the Google Cloud OAuth app is in "Testing" status, refresh tokens expire after 7 days. Publishing the app, or re-consenting regularly, avoids that **[U: app status not checked]**.

---

## 2. Fresh timed end-to-end V15 run

### 2.1 Setup

- **Story:** `blackhole_clocks`, 7 beats, 126 words. It was chosen because it is on-niche (space) and V15 had never built it: no plan cache, no plates, no scene renders.
- It was copied to `~/phase2_out/stories/blackhole_clocks` **without** its legacy audio, so every stage ran cold. That includes fresh Fish TTS for all 7 beats.
- **Command:**
  ```
  /usr/bin/time -v python3 research/phase2/timed_e2e.py <story> ~/phase2_out/e2e_blackhole
  ```
  The script wraps `tts_beat` and `beat_timing` from outside to time them. No pipeline code was changed.
- Started 2026-09-27 18:54, finished 19:11. Exit 0.

### 2.2 Results **[M]**

| Stage | Wall-clock | Notes |
|---|---|---|
| TTS (Fish, 7 calls) | **26.9 s** | 50.4 s of narration → RTF 0.53 (network-bound) |
| Timing (silence segmentation) | **0.6 s** | |
| Plan (BVP) | **86.6 s** | 2 LLM calls: attempt 0 failed validation, source `llm_retry`. Standalone calls take 10–25 s (§9), so ~60 s is backoff or retry. The provider is not logged **[U]**. |
| Plates + QA | **271.1 s** | 14 images. 13 NIM plates finished in ~33 s. **1 straggler cost ~190 s:** NIM read timeout → SiliconFlow 401 → HF 410 → Pollinations (9 s). The plate-QA call (~30 s) returned nothing usable, and saliency analysis took ~17 s. |
| Shot compile | ~0 s | |
| Render (Remotion, 17 scenes) | **431.5 s** | 18.2–36.8 s per scene (mean 25.4 s) → **7.65 s wall per output second** |
| Assembly (captions + mix + mux) | **169.5 s** | Single pass, libx264 crf 18 |
| Gate + judge | **47.0 s** | 1 judge call, verdict **PASS** |
| **Total** | **1032.8 s = 17 min 13 s** | Peak RSS 1.6 GB, 144% average CPU |

- **Output:** 56.4 s, 1080x1920 at 30 fps, −14.2 LUFS, 230 MB (32.7 Mb/s).
- **Calls:** 2 LLM, 14 image, 2 vision.

Comparisons:
- AUDIT §5.2 estimated 12–14 min cold. The real run was **17.2 min**.
- The excess is the dead fallback links (+~3 min) and the plan retries.
- Render plus assembly (601 s, 58%) is the structural cost. About 17 × ~20 s of it is Remotion per-invocation overhead (§4.2).

### 2.3 Defects the run exposed **[M]**

1. **Plate QA silently skipped.** `plate_qa: {checked: false, reason: "judge unavailable or unparseable"}`.
   - Root cause, reproduced: Gemini returned **HTTP 429**. The quota is `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: "20"`, for `gemini-2.5-flash` [V].
   - `_vision_gemini` retried with 12 s and 24 s sleeps, set a 1 h cooldown and returned `None`. The GLM fallback then also produced no usable answer **[U why; in the standalone test GLM answered fine]**.
   - The gate does not require plate QA, so the video passed.
2. **A watermarked plate is in the PASS video.**
   - Plate `c0e3b646…` (Pollinations) has a visible `pollinations.ai` watermark in the bottom-right corner and a clearly different, non-sepia style (contact sheet cell #14).
   - It is used in shot B7_S1 at 48.2–51.9 s. In the frames I sampled, the camera crop happens to hide the watermark. That is luck, not a guarantee.
3. **Garbled pseudo-text is visible in the hook frame.**
   - Plate #2 has a fake printed "document header", and it shows behind the headline "WHY DOES TIME SLOW HERE?" at t = 1 s.
   - The final judge still returned `hook_stops_scroll: true` with no flagged frames.
   - There is also a faint, low-contrast ghost label ("THE CLOCK") in the same frame.
4. **Gate verdict vs. content.** Max visual hold was 4.26 s and 29 visual changes passed. That is consistent with AUDIT §2.2.

The Claude plate-QA pass on the same contact sheet (§9) flagged exactly defects 2 and 3, plus 2 more dial-lettering plates.

---

## 3. Voice

### 3.1 Fish Audio: account and API **[M]**

- **Live synthesis works.** One 12-word line took 3.06 s wall for 5.07 s of audio (RTF 0.60), using the repo provider pinned to `s2.1-pro-free` and voice `0327fdb5…` ("Narrator").
- **Account state** (`GET /wallet/self/api-credit` and `/wallet/self/package`):
  - `credit: "0.000000"`, `cumulative_top_up: "0"`.
  - Package `type: "free"`, `total: 8000`, `balance: 8000`, `billing_period: "month"`.
  - The balance did not decrease after the calls, so `s2.1-pro-free` does **not** consume the 8,000 monthly credits **[M, by observation]**.
- **Word timestamps on the free model.** `POST /v1/tts/stream/with-timestamp` with header `model: s2.1-pro-free` returned SSE events with `alignment.segments[{text, start, end}]` plus `chunk_audio_offset_sec`.
  - Test: 12 words, 3.2 s wall.
  - Against faster-whisper `small.en` on the same audio, the absolute start difference was a **median of 0.06 s and a max of 0.16 s**. Fish's grid is 80 ms.
  - Script: `research/phase2/fish_timestamps.py`.

### 3.2 Fish Audio: commercial terms (quoted, not guessed) **[V]**

- **Terms of Use** (fish.audio/terms, "Last Updated: August 18, 2024"):
  - > "You will only use the Services for your own internal, personal, non-commercial use, and not on behalf of or for the benefit of any third party."
  - > "if you are a user of Paid Services, you are licensed to use the Services for commercial uses and otherwise to the fullest extent possible under applicable law."
- **Plan page** (fish.audio/plan): lists "Commercial use" among Free-tier features. However, its FAQ states:
  > "Free plan users can only use generated content for personal, non-commercial projects."

  The page is internally contradictory.
- **S2.1 Pro Free API blog** (fish.audio/blog/s2-1-pro-free-api, published 2026-06-23 and updated since):
  - > "Free access is available through November 30, 2026" … "we'll communicate any changes with advance notice."
  - > "Products generating more than $1M ARR should contact us before using S2.1 Pro Free."
  - The free tier may have "restrictions on certain commercial scenarios", while paid plans offer "full licensing".
  - > "Requests may be used to improve model quality."
- **Developers page:** paid S2.1 Pro is "$15 / 1M UTF-8 bytes".

**Reading:** the free API window is extended to **2026-11-30**, not 2026-08-31 as AUDIT recorded. Monetised YouTube use on the free tier is **not clearly permitted**: the binding ToS says non-commercial, and the plan FAQ agrees. Only the blog hints at a sub-$1M-ARR tolerance.

**Owner options:**
- (a) Get written confirmation from Fish (support email).
- (b) Pay for S2.1 Pro. A 130-word script is ~750 bytes, about **$0.011 per video**, but this breaks the zero-cost rule.
- (c) Promote the local fallback (§3.3) to primary for monetised uploads.

Separately, "Narrator by Max N" is a **community voice model**. Fish's terms on commercial use of third-party public voices were not found **[U]**.

### 3.3 Local fallbacks benchmarked on this server **[M]**

- **Material:** blackhole_clocks B1–B5 (5 lines, 36 s of speech), including "Einstein's" and "38 microseconds".
- **Scripts:**
  - `research/phase2/tts_bench.py`: wall time, RTF and max RSS via `/usr/bin/time`.
  - `research/phase2/tts_measure.py`: round-trip WER through faster-whisper `small.en`, words/min, pauses, peak, and a crude autocorrelation F0 spread.
- Chatterbox ran with its **default built-in voice**. I deliberately did not clone the Fish narrator, because cloning a third party's voice is a rights problem.

| Candidate | Licence | Load | **RTF** | Max RSS | WER | wpm | Pitch IQR (semitones) | Peak | Observed issues |
|---|---|---|---|---|---|---|---|---|---|
| Fish s2.1-pro-free (reference) | see §3.2 | — | 0.53 (network) | — | **0.000** | 145 | 2.9 | 0.61 | Deep male (F0 ~79 Hz), measured delivery, 10 pauses >250 ms in 5 lines |
| **Kokoro v1.0 fp32 `am_michael`** | Apache-2.0 (weights and kokoro-onnx) | 1.5 s | **0.65** | **0.70 GB** | **0.000** | 145 | 5.4 | 0.68 | None found. Mid-low male (F0 ~121 Hz), more pitch movement than Fish |
| Kokoro v1.0 fp32 `bm_george` | Apache-2.0 | 1.5 s | 0.57 | 0.70 GB | 0.011 | 147 | 3.8 | 0.55 | "clocks" transcribed as "Clark's" (British vowel) |
| Kokoro v1.0 fp32 `am_puck` | Apache-2.0 | 1.5 s | 0.56 | 0.69 GB | 0.011 | 157 | 6.0 | **1.02 (clips)** | "tick" → "take". Needs a limiter |
| Kokoro v1.0 **int8** `am_michael` | Apache-2.0 | 1.4 s | **1.75** | 0.46 GB | 0.000 | 145 | 4.9 | 0.68 | int8 is **2.7x slower** on this ARM CPU (no fast int8 kernels). Don't use it |
| Chatterbox **Turbo** (default voice) | MIT | 82 s | **5.19** | **6.3 GB** | 0.034 | 156 | 4.3 | 0.63 | Default voice is **female** (F0 ~225 Hz). "feel this" → "field us", "tick" → "took" |
| Chatterbox base 0.1.7 (default voice) | MIT | 81 s | **15.15** | **6.8 GB** | 0.023 | **189** | 8.5 | **1.01 (clips)** | Rushed at 189 wpm. "feel this" → "build this". The pitch spread may partly be tracker octave errors **[U]** |

Notes:
- "Quality" here means objective proxies only. **I could not listen to the audio.**
  - WER measures intelligibility and pronunciation of the hard tokens.
  - Pitch IQR is a rough expressiveness proxy.
  - Peak greater than 1.0 means sample clipping.
  - A human listening pass is still needed before promoting any fallback **[U]**.
- The Chatterbox line-5 timing was partly contended by another job, so base RTF is 12–20 per line. AUDIT's brief says 12–14x, consistent with this.
- The prior `illustrated_engine/V11_TTS_BENCH.md` found Chatterbox Turbo at ~45 s per line and Kokoro at 4.6 s per line on older builds. That agrees in direction.

### 3.4 Recommended fallback chain (research only; needs S's approval per AGENTS.md)

```
Fish s2.1-pro-free /with-timestamp  ──fail/timeout/402──►  Kokoro v1.0 fp32 am_michael (local)
   (word timestamps native)                                   (+ faster-whisper base.en alignment)
```

- **Granularity:** switch the **whole video**, never mid-video. The voice lock stays per video, and the fallback voice is recorded in the licence manifest and report.
- **Why Kokoro and not Chatterbox:**
  - Kokoro is 8x faster than Chatterbox Turbo and uses a tenth of the RAM.
  - It had zero round-trip errors.
  - It is Apache-2.0 with no reference-voice rights question.
  - Chatterbox's only advantage is voice cloning, and cloning needs a rights-cleared reference that does not exist today. The current `ref_thomas.wav` "kurzgesagt_like" reference is a risk (AUDIT §3.1 #19).
- **Brand consequence:** a Kokoro fallback **sounds different** from Fish (F0 ~121 Hz vs ~79 Hz). If commercial clearance for Fish fails (§3.2), the cleanest brand move is to make **Kokoro `am_michael` the channel's signature voice everywhere**. It is then the primary, and Fish is not used for monetised videos. This is an owner decision.
- **Edge TTS** stays excluded. It uses an unofficial endpoint with no commercial terms (AUDIT #18).
- Kokoro raw output can exceed 1.0 (`am_puck`), so the chain must peak-limit before loudnorm.

---

## 4. Captions, alignment and motion graphics

### 4.1 Word-level alignment **[M]**

- **Method:** faster-whisper 1.2.1 (MIT; CTranslate2 aarch64 wheel) with `word_timestamps=True` and int8, on the 7 fresh Fish beat WAVs (50.4 s).
- Its word starts were compared with V15's `silence_v1` timing for the same beats (`research/phase2/align_bench.py`).

| Model | Load | Wall (50 s audio) | RTF | RSS | WER vs script | V15 vs whisper word-start \|Δ\| p50 / p90 / max |
|---|---|---|---|---|---|---|
| tiny.en | 17.5 s (first download) | 9.0 s | 0.18 | 0.29 GB | 0.032 | 0.15 / 0.49 / 1.13 s |
| **base.en** | 8.1 s | 13.4 s | **0.27** | **0.40 GB** | **0.000** | 0.20 / 0.45 / 1.17 s |
| small.en | 23.4 s | 36.3 s | 0.72 | 0.83 GB | 0.000 | 0.15 / 0.43 / 1.11 s |

- All three models agree with each other. **V15's `silence_v1` word times drift by up to ~1.1 s**, with a p90 of ~0.45 s. That is much worse than the "±0.1 s at anchors" self-description, and it is what makes captions phrase-accurate rather than word-exact (AUDIT §2.4).
- Example from B1: V15 places "beside" at 0.868–1.252 s, across the measured pause at 0.95–1.08 s.
- **Recommendation:**
  - Use Fish-native timestamps (§3.1) when Fish is the voice.
  - Otherwise use **faster-whisper base.en**, which costs about 7% extra wall on top of TTS.
  - Keep `silence_v1` only as the offline last resort. This is a fallback, so keep it per AGENTS.md.
- **Not benchmarked:**
  - whisper.cpp (MIT, would need a build).
  - WhisperX (BSD-2, needs a torch/wav2vec2 aligner, heavier).
  - **MMS-based `ctc-forced-aligner`: the MMS weights are CC-BY-NC, so excluded.**
  - Montreal Forced Aligner (MIT, heavy conda stack).

  faster-whisper already meets the need, so none of these is justified.
- The Remotion project already vendors **`@remotion/captions`** (in `engine/remotion_project/node_modules/@remotion/`). Its token/page helpers may replace custom caption paging **[U: API fit not checked]**.

### 4.2 2D animation / motion graphics **[M]**

Scratch project `~/phase2_out/remotion_bench` (Remotion 4.0.529 plus `@remotion/lottie`, the same version as the pipeline). The composition was 1080x1920 at 30 fps and contained:
- a V15 plate with a Ken Burns move,
- a hand-built Lottie layer (pulsing ring plus orbiting dot),
- spring-animated kinetic words with accent-colour emphasis.

| Render | Wall | RSS |
|---|---|---|
| 1 s composition (30 frames), concurrency 2 | 24.5 s | 1.0 GB |
| 10 s composition (300 frames), concurrency 2 | 36.1 s | 0.63 GB |
| 10 s composition, concurrency 4 | 32.6 s | 0.63 GB |

- **Interpretation:** there is a ~23 s fixed cost per `remotion render` (bundle, browser launch, compositor), then ~1.2 s per output second for this layer mix.
- V15 invokes Remotion once per scene: 17 invocations, 431 s for 56 s of output. At least ~17 × 20 s ≈ 340 s of that is fixed overhead.
- Rendering **one composition per video** (a Remotion `<Series>` of the scene components), or reusing a pre-bundled server via `@remotion/renderer`'s `bundle()` + `renderMedia()`, would plausibly cut render from ~7 min to **~1.5–2.5 min** **[U: V15 scenes are heavier than this bench composition; to be confirmed in Phase 4]**.
- Lottie renders correctly headless on aarch64 [M, frame checked].
- **Asset licence:** LottieFiles free animations use the **Lottie Simple License**: "commercial use … no attribution" required, with no redistribution as a competing library [S: LottieFiles help centre; the licence page returned 403 to the fetcher].
- **Alternatives considered, not benchmarked:**
  - Motion Canvas / Revideo (MIT; headless via Puppeteer).
  - Manim CE (MIT; already used in `~/mathmotion-lab`, good for diagrams but slow per scene).
  - Raw SVG + Skia.

  None removes a need that Remotion does not already meet, so switching is not justified (AGENTS.md: prefer libraries already in the project).
- **Remotion licence** (vendored `node_modules/remotion/LICENSE.md`) [V]:
  > "You are eligible to use Remotion for free if you are: an individual; a for-profit organization with up to 3 employees; a non-profit…" … "use the software non-commercially or commercially for the purpose of creating videos"

  The file also notes that "In Remotion 5.0, the license will slightly change." **Pin to 4.x or re-check the terms on upgrade.**

---

## 5. Illustration / plate sources

### 5.1 Cloud providers **[M]**

- **Method:** the same 4 house-style prompts (from this e2e run) sent through the **repo's own provider classes** at V15's `REQ_W×REQ_H` = 720x1280 (`research/phase2/img_bench.py`).
- Runs used a fresh output directory and wrote nothing to the pipeline cache.

| Provider | Status today | Speed per image | Output | Style consistency | Output licence | True cost at batch scale |
|---|---|---|---|---|---|---|
| NVIDIA NIM FLUX.2-klein-4B (baseline) | ✅ | **3.1–3.3 s** | 752x1392 | Good. Coherent sepia/navy house look across all 4 | Model Apache-2.0. **Hosted-API terms are the NIM trial/evaluation terms, not approved by the owner** | Trial credits **[U cap]** |
| Pollinations (anonymous) | ✅ but degraded | 4.5 s, then **~29 s** (throttled) | 576x1024 | **Poor.** It ignored the subject in 2 of 4 prompts (no satellites), the look is flatter, and it drifts from the house palette | **Every image carries a `pollinations.ai` watermark** [M]. The new API (`gen.pollinations.ai`) requires keys, and legacy anonymous access is limited to "1 pollen per IP per hour" [V: APIDOCS.md] | Free, but slow and watermarked. Unusable as a primary |
| SiliconFlow FLUX.1-schnell | ❌ **HTTP 401** | — | — | — | — | Dead key |
| HF `hf-inference` FLUX.1-schnell | ❌ **HTTP 410 Gone** | — | — | — | — | Endpoint retired; the provider code is stale |
| Gemini `gemini-2.5-flash-image` | ❌ **HTTP 429** (free quota exhausted) | — | — | — | SynthID watermark (invisible) | Free tier effectively ~0 for this project today |
| **Cloudflare Workers AI** | **Not tested: no account in `.env`** | **[U]** | FLUX.1-schnell, **FLUX.2-klein-4B**, FLUX.2-dev and others | Same klein model as NIM, so style continuity is expected **[U]** | klein-4B and schnell are Apache-2.0 | **"10,000 Neurons per day at no charge"** [V: official pricing page]. klein-4B lists "5.37 neurons per input tile". A 720x1280 image is ~4–8 tiles, so **roughly 200–400 images/day free [U: the per-output-tile basis is unclear]**. That is about 15–25 videos/day at ~15 plates each. Needs a free Cloudflare account (owner action) |
| AI Horde (crowd-sourced, anonymous) | Not tested | Minutes per image for anonymous users **[U]** | SD-family | Varies by worker | Model-dependent | Free but unpredictable. Not recommended |

### 5.2 Public-domain / CC0 archives (no generation) **[V: licences well established; per-item checks still required]**

These fit the channel's existing vintage-engraving house look: real engravings and plates, zero AI disclosure burden, and zero cost.

- **NASA Images** (generally not copyrighted; NASA media guidelines apply, no endorsement implied).
- **Smithsonian Open Access** (CC0).
- **The Met Open Access** (CC0).
- **Library of Congress** (many PD items; check rights statements per item).
- **Biodiversity Heritage Library** (many PD scientific plates).
- **Wikimedia Commons** (filter to PD/CC0; CC-BY-SA needs attribution and share-alike, so avoid).

The legacy `src/` stack already has NASA, Wikimedia and Internet Archive fetchers (AUDIT #22–23).

### 5.3 Self-hosted diffusion on this CPU

- **Tool:** stable-diffusion.cpp (MIT, built from source at `3f8527a`), running **FLUX.2-klein-4B** GGUF (Apache-2.0).
- **Supporting files:** Qwen3-4B Q4_K_M text encoder (Apache-2.0) and the klein VAE (Apache-2.0). All are ungated on Hugging Face.
- 4 steps, cfg 1.0, the same house prompt, `-t 4`.

| Model (local, CPU) | Size | Load | Generate (4 vCPU) | Total wall | Max RSS | Quality vs NIM (same prompt, visual check) | Licence |
|---|---|---|---|---|---|---|---|
| **FLUX.2-klein-4B Q4_0**, 4 steps, 576x1024 | 2.5 GB + 2.5 GB TE + 0.17 GB VAE | 47 s | **1,236 s** (~250–305 s per step, VAE decode 97 s) | **1,237 s ≈ 20.6 min per image** | **8.5 GB** | **Equivalent.** Clean engraving/sepia look and correct subject (pocket watch on rock before a black disc). No stray text, no watermark | Apache-2.0 (model, TE, VAE) |
| SD-Turbo (fp32 safetensors), 1 step, 512x896 | 5.2 GB | ~67 s | 138 s | 205 s | 6.8 GB | Not tested visually at 1 step | Stability AI Community License ("For commercial use, please refer to stability.ai/license") [V: model card]. Free under a revenue threshold [S] |
| SD-Turbo, 4 steps, 512x896 | 5.2 GB | ~53 s | 205 s | 258 s | 6.8 GB | **Worse.** Stylish vintage plate, but it ignored the subject (abstract clock rings instead of a watch on rock). Low resolution | as above |

- Build: 272 s. Build and run used `~/phase2_venv`'s pip `cmake`; no system packages were installed.
- The Q8_0 and 720x1280 runs were **cancelled**: at ~20 min per image, three more runs would have taken ~1.5–2 h without changing the conclusion.
- Comparison sheet: `~/phase2_out/img/compare_local.jpg`.

**Conclusion [M]:**
- Local FLUX.2-klein matches the NIM house style but is **~375x slower** (1,237 s vs 3.3 s).
- A 15-plate video would take **~5 h of plates**, and running 24/7 would give ≈70 plates/day while competing with Remotion for the same 4 cores.
- **It is not CPU-feasible as the per-video source.** It is only usable as a slow, owned emergency floor or an idle-time plate-library builder.
- Q8_0 (sometimes faster than Q4_0 on ARM, because it avoids nibble dequantisation), lower step counts and thread tuning were not measured **[U]**. None of them is likely to close a 375x gap.

### 5.4 Recommendation

There is **no verified zero-cost, commercially clear, fast replacement for NIM today.** The recommendation is a hybrid built around the *same model* (FLUX.2-klein-4B, Apache-2.0), so the channel look survives whichever host serves it.

1. **Primary (fast cloud, free quota): Cloudflare Workers AI `flux-2-klein-4b`.**
   - It is the same model as NIM's primary, so the look carries over, and Cloudflare publishes a permanent daily free allocation.
   - **[U] It is the one unverified link:** the owner must create a free Cloudflare account and add `CLOUDFLARE_ACCOUNT_ID`/`CLOUDFLARE_API_TOKEN`. Then benchmark speed, the real neuron cost per 720x1280 image and output consistency before adopting.
2. **Owned floor (always available, slow): local FLUX.2-klein-4B via stable-diffusion.cpp.**
   - Measured quality matches NIM, but ~20 min per image (§5.3).
   - Use it only to (a) finish the 1–3 plates of a video when every cloud tier is down, instead of dropping to the procedural tier, and (b) grow a reusable, content-addressed plate library during idle hours.
3. **Reduce plate demand** (lowers the cost of every tier):
   - Archive tier: CC0/PD museum and NASA images for "real artefact" shots, graded with the brand LUT so they sit in the house look.
   - Plate reuse through crops and zooms of one plate across adjacent shots (V15's `ZOOM_THROUGH` and punch-ins already do this).
   - Motion-graphics scenes (§4.2) that need no plate at all.
4. **Last resort:** Pollinations, **only with a watermark detector or crop**, and it must be flagged in the manifest.
5. **Remove from the chain, or repair:** SiliconFlow (dead key) and HF `hf-inference` (410). Per AGENTS.md this narrows a fallback chain, so **it needs S's explicit approval**. I recommend replacing them with tiers 1 and 2 rather than simply deleting them.
6. NIM stays usable for benchmarking only, per the owner's decision.

---

## 6. LUT grading **[M]**

- `research/phase2/make_lut.py` generates a 33³ `.cube` in code: a gentle S-curve, −8% saturation, cool-navy shadows and warm highlights.
  - This matches the de facto house palette (AUDIT §2.3), so no third-party LUT pack with unclear licensing is needed.
  - The LUT is versionable and reviewable as code.
- **ffmpeg `lut3d` (tetrahedral) cost on the 56.4 s final:**
  - Decode only: 11.5 s. Decode plus `lut3d`: 40.4 s, so the **filter itself costs ~29 s**.
  - Full re-encode (crf 18, medium): 147 s plain vs 216 s with `lut3d`.
- **Visual check:** a whole-frame LUT also shifts burned-in caption, label and accent colours away from brand hex codes (visible in `~/phase2_out/rb_lut.jpg`).
- **Recommendation:** apply the brand LUT **to plates and archive images at ingest**. It is a per-image numpy lookup, and a still costs well under 1 s [U: not timed separately]. Typography, captions and brand UI then render in exact palette hexes afterwards. A whole-frame `lut3d` inside the existing single-pass assembly is the fallback if footage is added later.

---

## 7. Music and SFX

| Source | Licence / terms | Fit | Verdict |
|---|---|---|---|
| **YouTube Audio Library** | "If you're in the YouTube Partner Program, you can monetize videos with music and sound effects from the Audio Library." Audio Library tracks "won't be claimed by a rights holder through the Content ID system". Some tracks need a description credit (CC) [V: support.google.com/youtube/answer/3376882] | No API: the owner downloads a curated set once, filtered to "Attribution not required" | **Recommended music source** |
| Pixabay Music | Pixabay Content License. Contributors may still register tracks with Content ID, so claims happen and must be disputed with the Pixabay certificate [S: Pixabay blog] | API available | Secondary only. Store the certificate per track in the manifest |
| Kenney audio packs (Impact, Sci-fi, Interface, UI, Jingles, …) | CC0 **[U: verify the licence file inside each zip at ingest]** | Short UI/impact SFX and jingles | **Recommended SFX base** |
| Sonniss GDC Game Audio Bundles | "completely royalty-free for any commercial work … YouTube videos you monetize"; "Attribution … never required"; no redistribution as standalone files; "AI/ML training is strictly prohibited" [V: sonniss.com/gameaudiogdc] | Large cinematic SFX library (whooshes, risers, impacts) | **Recommended** for richer transitions |
| Freesound | Mixed licences; use the CC0 filter only | Long tail | Optional, manifest per file |
| Procedural (existing `procedural_audio.py`) | Self-made | **Signature sting and logo motif** | Keep for the sonic identity: one fixed motif across all videos |
| MusicGen (Meta) | **Weights CC-BY-NC 4.0** [S] | — | **Excluded** |
| Stable Audio Open Small (341M) | Stability AI Community License: commercial use free below the revenue threshold [S]. Arm-optimised | Stingers/loops | Plausible later experiment. **Not benchmarked [U]** |
| ACE-Step | Apache-2.0 [S] | Full songs | 3.5B parameters, impractical on this CPU **[U]** |

**Recommendation:**
- Build a small mood-tagged library of ~30–50 Audio Library tracks: wonder, tension, mystery, triumph, calm.
- Select a track per video from the story's emotional arc.
- Keep a fixed procedural sting as the sonic logo.
- Take SFX from Kenney and Sonniss.
- Log every file in the per-video licence manifest.

This addresses AUDIT §2.6 (same A-minor bed on every video).

---

## 8. Automated quality scoring

| Tool | Licence | Measured | Use |
|---|---|---|---|
| **PySceneDetect 0.7.1** (`detect-adaptive`) | BSD-3 | 56 s final analysed in **15.9 s**, 0.16 GB. It found **17 scenes, exactly V15's 17 shots**, average shot 3.3 s [M] | Pacing gate: max shot length, cut cadence, "nothing static > N s" |
| **faster-whisper base.en** round-trip | MIT | RTF 0.27 [M] | Narration WER vs script (catches TTS misreads such as "Clark's" and "field us"), caption-identity check, and word-exact captions |
| ffmpeg `ebur128`/`astats`/`silencedetect` | LGPL/GPL (ffmpeg) | already in V15 | Loudness, peaks, dead air |
| **Vision-LLM judge via the adapter** | — | Claude found the watermark and 3 text plates that the pipeline missed (§9) [M] | Plate QA, final judge, clickbait/claim checks. It must be **required**, never silently skippable |
| OpenCLIP (+ LAION aesthetic head) | MIT | not benchmarked **[U]** | Cross-video similarity (anti "mass-produced"), plate-to-prompt fit, aesthetic floor |
| Tesseract OCR | Apache-2.0 | not benchmarked **[U]** | Detect stray or garbled text and watermarks in plates *before* render (cheap pre-filter for the LLM QA) |
| pyiqa / IQA-PyTorch | **PolyForm Noncommercial 1.0.0** [V: repo] | — | **Excluded** (licence) |
| VMAF | BSD+patent | — | Needs a reference video; not useful for generative output |

---

## 9. LLM comparison: Claude CLI vs Gemini vs GLM on real V15 calls **[M]**

- **Script:** `research/phase2/llm_compare.py`.
- **Inputs:** identical prompts built by V15's own `build_prompt` and `QA_QUESTION`, on the blackhole_clocks story and the e2e contact sheet.
- **Scoring:** V15's own `validate_plan` (after `_repair`), and JSON parse plus schema checks for QA.
- **Claude:** `claude -p --output-format json --strict-mcp-config`, with only the Read tool allowed (for the image).

| Call | Gemini 2.5-flash | GLM-5.3-flash (OpenRouter) | Claude CLI (default model → `claude-opus-5-5`) |
|---|---|---|---|
| **BVP plan** | 10.2 s. Parsed. **1 validation error:** asks the image for a "giant number '38'" (a rule violation) | 11.5 s. Parsed. **0 errors**, 14 shots | 24.5 s. Parsed. **0 errors**, 14 shots. Wrote plain JSON with no code fence |
| **Plate QA** (14-plate sheet) | **None** (HTTP 429, daily quota of 20) | 5.8 s. Parsed. Flagged 2 (`text` on #2 and #14) | 13.8 s (2 turns incl. image Read). Parsed. Flagged 4: #2 garbled header, #11 and #12 dial lettering, **#14 "pollinations.ai watermark"** |

Qualitative:
- Claude's plan prompts proactively specified "a lone brass pocket clock **with a blank face**". That pre-empts the dial-numeral `text` failures that later hit NIM plates #11 and #12.
- GLM's plan was also clean.
- Gemini violated the no-numbers-in-image rule.

Cost and quota (for the Phase 3 design):
- The CLI reported a list-price equivalent of **$0.11 per plan call and $0.09 per QA call** on the default model. On the Pro plan these count against the shared usage quota, not billing.
- About 3–4 calls per video on Opus would use quota quickly at batch scale.
- The adapter should make the model **per-stage configurable**, e.g. `--model sonnet` for plan/QA, reserving Opus for creative stages. This was not measured here **[U]**.

Implications for Phase 3:
- GLM is not needed on the required path. Claude alone met the format contract on both calls.
- **Gemini's free tier cannot be relied on.** Its 20 requests/day per model were exhausted by one e2e run plus this comparison [V].
- The QA-must-not-silently-skip issue (§2.3) belongs in the adapter/gate design.

---

## 10. Channel brand research: @most.amazing.wonders

### 10.1 Data access: what worked and what didn't **[M]**

| Route | Result |
|---|---|
| YouTube Data API v3 via the existing OAuth token (built like `tools/youtube_upload.py`) | ❌ `RefreshError: invalid_grant`. The token is dead (§1) |
| YouTube Data API with a Google API key | ❌ 401: "API keys are not supported by this API" (the only Google key present is a Gemini/AI-Studio key) |
| yt-dlp flat playlist (public) | ✅ All 82 uploads with ids, titles and view counts (long-form counts are rounded, e.g. "90K") |
| yt-dlp full per-video extraction / downloads | ❌ "Sign in to confirm you're not a bot" from this Oracle IP |
| Public watch/shorts page HTML (`research/phase2/yt_scrape.py`) | ✅ Partial: exact views, publish date, length, tags and description for Shorts. Likes for 26 of 82. **Comment counts are not in the page** (loaded asynchronously) |
| **YouTube Analytics (retention, audience, traffic sources)** | ❌ **Unreachable.** It needs `yt-analytics.readonly` plus an owner re-consent. **Limitation:** everything below is public-counter data only, with no retention curves |

Raw per-video data: `research/phase2/channel_videos.csv`.

### 10.2 What the channel looks like **[M]**

- **Title "Most Amazing"**, **1,040 subscribers**.
- **59 Shorts** (12,946 total views; median **44**, mean 219) and **23 long-form** videos (~115k total, dominated by one 90K outlier).
- **Upload history is bursty and topically mixed:**

| Batch | Shorts | Median views | Max | Content |
|---|---|---|---|---|
| 2023-06 | 30 | 31 | 543 | Emoji place quizzes (4–8 views each), JWST clips |
| 2023-08/09 | 3 | 537 | 641 | "Universe in 1 Second", "Close Encounter with Aliens" |
| **2025-05** | 5 | **1,043** | **1,360** | **Dinosaur / deep-time series** ("Dinosaurs Were Thriving", "The Reset Button for Life", "Dinosaurs' Legacy in Modern Birds"): 3 of 5 over 1k |
| 2026-01 | 6 | 372 | 1,253 | "Physics.exe has stopped working 🤯" (satisfying physics glitches, 3 variants, best 1,086), 2 untitled "10 January 2026" clips (1,253 / 482), ASMR |
| **2026-06/07** (current V14/V15-era explainers) | 15 | **56 / 23** | 1,093 | "How Scientists Created a Time Crystal" (1,093) is the only breakout. Others 6–172, e.g. "Why Time Moves Slower Near Black Holes" 172, "Blood Falls" 136. Two run **112–113 s** |

- **Long-form:** "Scientists Shocked by Warp Drive Potential – Faster Than Light Travel" at **90K** (≈78% of all long-form views), then "Supercomputer Simulation … Galaxy Creation" at 10K and "5 Discoveries from JWST" at 4.4K.
- **Likes per view** (Shorts with ≥30 views and exact likes): "Why The Speed of Light is Actually Slow" 11.1%, "Bioluminescent bays…" 7.1%, "Alien travel" 5.7%, "Universe in 1 Second" 4.8% (26 likes, 537 views).
  - The samples are small (tens of views), so these ratios are **not statistically meaningful**.
  - Comments were unavailable.
- **Tag hygiene:** the most frequent tags across the channel are **quiz/trivia/pub quiz (18 videos)**, above the science tags (15–16). The channel's historic topical signal is diluted by quiz, Bitcoin, AI-policy and ASMR uploads.
- **Titles** (Shorts): median 5 words; 8% start with How/Why/What; 15% end in "?"; 20% have an emoji; **42% put hashtags in the title**.

### 10.3 External benchmark channels (public flat metadata, latest ~120 Shorts each) **[M]**

| Channel (subs) | Median Short views | Title words | How/Why/What (all → top-20) | "?" | Emoji | #tags in title |
|---|---|---|---|---|---|---|
| Zack D. Films (28.6M) | 4.9M | 7 | 45% → **55%** | 0% | **100%** | 0% |
| Veritasium (21.3M) | 5.2M | 6 | 36% → 25% | 30% | 0% | 2% |
| Kurzgesagt (25.6M) | 2.45M | **5** | 31% → **45%** | 33% | 0% | 0% |
| MrBallen (11.3M; mysteries) | 432K | 7 | 18% → 35% | 2% | 30% | 2% |
| Astrum (2.9M; space) | 360K | 6.5 | 26% → 10% | 21% | 3% | 0% |
| SciShow (8.4M) | 277K | 6 | 23% → 35% | 1% | 0% | **94%** |
| The Infographics Show (15.5M) | 181K | 8 | 55% → **70%** | 8% | 0% | 18% |

Top examples in-niche:
- Kurzgesagt: "The Deadly Power of a Coin-Sized Black Hole" (20M), "Something in Your Kitchen Emits Antimatter" (14M).
- Astrum: "The Gravity Illusion" (9.1M).
- SciShow: "We solved Roman concrete" (22M).
- Veritasium: "Can you swim in shade balls?" (64M).

**Limitation:** downloads are bot-walled from this IP, so I could not measure cut rate, caption placement or hook timing on these videos directly. The format claims below come from secondary sources.

**Format patterns from secondary sources** [S; vendor blogs, no disclosed methodology; directional only]:
- 50–60% of drop-offs happen in the first 3 s.
- Aim for a visual change every ~1.5–4 s.
- Burned-in, large, middle-third captions.
- Front-load the payoff.
- Design the last frame to loop into the first.

**Platform facts [V-ish]:**
- Since 2025-03-31, a Shorts "view" counts **every start or replay**, so loops directly inflate views (reported by TechCrunch/Musically; YouTube help).
- Monetisation uses "engaged views".

Zack D. Films' micro-documentary format is 20–45 s and 3D-animated, with a single "How X works" premise [S].

### 10.4 Tailored content and topic strategy (for Phase 3)

Grounded in this channel's own numbers. The sample sizes are small, so treat these as priors to test, not conclusions.

1. **Lead with deep-time / "Earth's history" series and single-spectacle physics.**
   - The channel's only consistently >1k Shorts are the **dinosaur/extinction series** (a multi-part arc from one big story) and bold single-concept items: time crystal, "Universe in 1 Second", "Physics.exe".
   - The topic engine should score for (a) a concrete, visual, counter-intuitive single idea, and (b) **series potential** (Part 1/2/3 of one big story, which builds returning viewers).
2. **The long-form warp-drive outlier (90K) marks demand for FTL / exotic-space-travel / "scientists found" topics.**
   - Mine that cluster: warp drives, wormholes, FTL, alien-world discoveries.
   - Use honest framings. Brief constraint 4c forbids misleading clickbait, and "Scientists Shocked" titles are a risk there.
3. **Drop off-niche formats.** Emoji quizzes (4–8 views), Bitcoin, AI policy and ASMR all underperformed and muddy the channel's topical identity. Stop adding quiz/trivia tags.
4. **Titles:**
   - Move toward the benchmark pattern: **5–7 words, a concrete noun plus a twist** ("The Deadly Power of a Coin-Sized Black Hole").
   - Use How/Why/What for ~30–50% of titles.
   - **No hashtags in the title.** 42% of our titles have them; Kurzgesagt, Veritasium, Zack and Astrum have ~0%. Put hashtags in the description instead.
   - Emoji in titles is a Zack-specific style, not a niche norm. Optional.
5. **Length:** the channel's breakout Shorts were 30–62 s, and the 112–113 s uploads did poorly (16 and 136 views). Enforce the brief's 30–60 s budget. AUDIT §2.1 found none in V15.
6. **Hook and loop:** the current V15 Shorts open with a soft question over a calm plate, and their median is 56 views. With a 1k-subscriber channel, almost all distribution comes from cold swipe-feed tests, so the first 1–2 s and replay loops are the levers. This matches AUDIT weaknesses #1–#2. The owner should check "viewed vs swiped away" in YouTube Studio for the 2026-06 batch, because that is the one retention signal I could not reach.

---

## 11. Owner decisions / open items raised by this phase

1. **Fish commercial clearance** (§3.2): get written OK from Fish, pay (~$0.011/video), or promote Kokoro `am_michael` to the channel voice.
2. **Approve the TTS fallback addition** (Fish → Kokoro, whole-video switch) (§3.4). This adds a fallback and does not remove one.
3. **Approve replacing the dead plate-fallback links** (SiliconFlow 401, HF 410) with local klein and Cloudflare. This narrows a chain, so **explicit approval is required** per AGENTS.md (§5.4).
4. **Create a free Cloudflare account** (Workers AI) if tier 2 is wanted, then benchmark it.
5. **Re-consent YouTube OAuth** with `youtube.upload` + `yt-analytics.readonly` (+ `youtube.readonly`). This unlocks retention data for the Phase 3 feedback loop, and uploads are currently broken anyway.
6. **Rotate `GEMINI_API_KEY`** (§1).
7. **Download a curated YouTube Audio Library set.** This is a manual step with no API.

---

## 12. Reproducibility

| Artifact | Path |
|---|---|
| Timed e2e wrapper / results | `research/phase2/timed_e2e.py` → `~/phase2_out/e2e_blackhole/{phase2_timings.json,pipeline_report.json,final.mp4}` |
| Fish check / timestamps | `research/phase2/fish_check.py`, `research/phase2/fish_timestamps.py` |
| TTS bench / measures | `research/phase2/tts_bench.py`, `research/phase2/tts_measure.py` → `~/phase2_out/tts/` |
| Alignment bench | `research/phase2/align_bench.py` → `~/phase2_out/align_*.json` |
| Image bench | `research/phase2/img_bench.py`, `research/phase2/qa_prompts.json` → `~/phase2_out/img/` |
| LLM comparison | `research/phase2/llm_compare.py` → `~/phase2_out/llm_compare/` |
| LUT generator | `research/phase2/make_lut.py` |
| Channel data | `research/phase2/yt_channel.py` (API attempt), `research/phase2/yt_scrape.py`, `research/phase2/channel_videos.csv` |
| Remotion/Lottie bench | `~/phase2_out/remotion_bench/` |
| Scratch venv (faster-whisper, PySceneDetect, cmake) | `~/phase2_venv` (project venvs untouched) |
| Models | `~/models/kokoro/` (v1.0 onnx), `~/models/flux2klein/`, `~/models/sdcpp/` |

Sources: [Fish ToU](https://fish.audio/terms) · [Fish plans](https://fish.audio/plan/) · [Fish S2.1 Pro Free blog](https://fish.audio/blog/s2-1-pro-free-api/) · [Fish developers](https://fish.audio/developers/) · [Fish TTS with timestamps](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech-stream-with-timestamps) · [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) · [Pollinations APIDOCS](https://raw.githubusercontent.com/pollinations/pollinations/master/APIDOCS.md) · [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) · [sd.cpp FLUX.2 doc](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/flux2.md) · [IQA-PyTorch](https://github.com/chaofengc/IQA-PyTorch) · [YouTube Audio Library help](https://support.google.com/youtube/answer/3376882) · [Sonniss GDC](https://sonniss.com/gameaudiogdc) · [Pixabay Content ID blog](https://pixabay.com/blog/posts/how-to-clear-a-youtube-content-id-claim-with-a-pix-190/) · [LottieFiles commercial use](https://help.lottiefiles.com/hc/en-us/articles/45243303062681-Commercial-Use-Attribution) · [Stable Audio Open Small](https://stability.ai/news-updates/stability-ai-and-arm-release-stable-audio-open-small-enabling-real-world-deployment-for-on-device-audio-control) · [MusicGen weights licence issue](https://github.com/facebookresearch/audiocraft/issues/198) · [ACE-Step](https://github.com/ace-step/ACE-Step) · [TechCrunch: Shorts view counting](https://techcrunch.com/2025/03/26/youtube-is-changing-how-youtube-shorts-views-are-counted) · [OpusClip Shorts length/retention (S)](https://www.opus.pro/blog/ideal-youtube-shorts-length-format-retention) · [Zack D. Films analysis (S)](https://ivideonow.com/blog/why-zack-d-films-dominates-youtube-shorts-with-unsettling-3d-animation-content-en)
