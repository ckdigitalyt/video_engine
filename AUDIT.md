# AUDIT.md: Phase 1 gap analysis of the V15 baseline

Branch `shorts-v3` @ `b20406f` (V15 WIP checkpoint `6df5bc0`). Auditor: Claude Code (Opus), 2026-09-27.
Scope: V15 is the baseline, and this is a gap analysis against `~/UPGRADE_BRIEF.md`. It does not redesign V15.
No pipeline code was modified. No fresh render was triggered. Timing comes from the existing reports and the file mtimes.

Evidence labels: **[V]** verified in code or artifacts during this audit. **[M]** measured by me on existing artifacts.
**[U]** unverified or inferred, and needs a check before anyone relies on it.

---

## 0. TL;DR

- V15 is a solid **render and QA core** for vertical Shorts. It already outputs native 1080x1920 at 30 fps and 50–55 s long.
  - Each shot gets an AI illustration plate, with Remotion shot grammars on top.
  - Captions are phrase-timed with an active-word highlight.
  - Audio is loudness-normalised to about −14 LUFS, with no clipping and no dead air.
  - A deterministic gate plus a vision judge decides the verdict.
  - The brief's "known gap" (horizontal, 4K, ~120 s, static) is **out of date for V15**. It still describes the legacy `mission_run.py` path.
- The biggest gaps are **upstream of rendering**:
  - V15 has **no story engine**. Topic sourcing, script writing, hook engineering, loop endings and fact verification are all missing. It renders a hand-authored corpus of 27 `story.json` files.
  - There is **no channel brand bible** in code. Each story has its own look, and brand names like SURFACE, ABOVE THE CLOUDS and EVENT HORIZON vary by story.
  - Pacing is slow for the niche. The gate allows a 4.5 s hold against a 1.5 s bar.
  - Captions are small and sit inside the Shorts bottom-UI zone.
  - There is one fixed procedural music bed for every video.
  - The voice depends on a free cloud tier whose free window is documented as ending 2026-08-31, and V15 deliberately gives it **no fallback**.
- Constraints:
  - **LLM layer is not provider-agnostic.** V15 hard-codes Gemini → GLM (OpenRouter) via raw `urllib` in `engine/director.py`. There is no Claude CLI provider.
  - **No per-video license manifest** and **no AI-disclosure flag** exist.
  - Several services are **credit- or trial-limited**: see §3.2.
- V15's own validation milestone (M8) is **incomplete**. The Tunguska generalisation run stopped after plates, and `V15_REPORT.md` was never written.

---

## 1. What V15 already covers well (do not rebuild)

| Capability | Where | Notes |
|---|---|---|
| One-command story → gated MP4 | `illustrated_engine/engine/v15_pipeline.py` | Runs TTS → timing → plan → plates → shots → render → assembly → gate. Exit code 0 = PASS, 1 = HOLD. **[V]** |
| Batch runner | `engine/v15_batch.py` → `build/v15/batch_report.json` | Runs sequentially, shares the plate and plan caches, and reports cost counters. **[V]** |
| Native vertical output | assembly `fps=30`, 1080x1920; ffprobe on `ice_slippery/final.mp4` = h264 1080x1920 30/1 + AAC **[M]** | The legacy 4K horizontal gap does not apply to V15. |
| Beat Visual Plan (semantic shot planning) | `engine/v15_plan.py` (prompt `bvp/1.4`) | One LLM call per story, cached by input hash. It uses closed enums (3 shot kinds, 6 cameras, 3 compositions) and word-index anchors. On-screen copy is capped at 5 or 4 words. **Factual guard:** every digit shown on screen must appear verbatim in the narration. Retries once, then falls back to a deterministic plan. **[V]** |
| AI plate layer with fallback chain | `engine/v15_plates.py` → `src/providers/image_gen.py` | NIM FLUX.2-klein → SiliconFlow → HF → Pollinations → Gemini image, then the V14 procedural tier (recorded as `asset_tier`). Global content-addressed cache with a provenance sidecar (provider, model, seed, prompt). Saliency subject mask and bbox. **[V]** |
| Plate QA with model-diverse regeneration | `plate_qa()` + `_next_chain()` in `v15_pipeline.py` | One vision call per story on a contact sheet. Failing plates regenerate on the *next* provider. Cell run: 2 failures (text, wrong_subject) were caught and fixed. **[V]** |
| Shot grammars | `engine/v15_shots.py` | `PLATE_SHOT` (camera toward the subject bbox, 2.5D subject band, leader label, giant number), `ZOOM_THROUGH` (multi-plate scale dive) and `PROCESS_OVER_PLATE` (causal steps revealed on their words). Adds a finish layer (grain and vignette) and fits text to real font metrics. **[V]** |
| Anti-hold splitting | `split_long_holds()` (MAX_HOLD_S 4.4) | Punch-in cut at the word nearest the middle of a long gap. **[V]** |
| Word/phrase timing without ASR | `engine/v15_timing.py` | Silence segmentation anchored to punctuation, syllable-weighted between anchors. About ±0.1 s at anchors, with drift mid-phrase (self-declared). **[V]** |
| Kinetic captions | `caption_cues()` in `v15_pipeline.py` + `engine/captions.py` | Phrases of up to 4 words that never strand a function word or split a number from its unit. Active-word highlight in the lightened bible accent. Burned in *after* composition. **[V]** |
| Art direction plumbing | `engine/v15_style.py`, `engine/bible.py` | Bible palette → renderer palette. Fonts are staged into Remotion. Adaptive ink colour from plate luminance. Prompt hygiene for FLUX (banned "page/diagram/text" vocabulary). **[V]** *(but see §2.3: this is per-story, not a channel bible)* |
| Audio mix | `engine/v14_assembly.py`, `engine/procedural_audio.py` | Narration + underscore + SFX on cuts and reveals, voice-keyed ducking, `loudnorm=I=-14:TP=-1.5:LRA=11`. **Measured:** ice −14.3 LUFS / −1.4 dBTP / LRA 2.6; cell −14.1 LUFS / −1.5 dBTP / LRA 2.5; no silence ≥0.6 s below −45 dB. **[M]** |
| Render caching | `engine/v14_cache.py` (§24/§25) | Scene keys include the renderer source hash, so only changed scenes re-render. **[V]** |
| Honest publish gate | `engine/v15_gate.py` | Checks caption identity against the narration, text bounds, information floor, max visual hold, asset tier (procedural HOOK/PAYOFF = fail), LUFS window, voice-stem presence, A/V duration and codecs. Adds 1 vision-judge call (hook stops scroll / ending resolves / template feel / per-frame issues). An unavailable judge gives HOLD, not PASS. The V14 finals FAIL this gate (`build/v15/evidence/v14_artifacts_vs_v15_gate.json`). **[V]** |
| Fact sheet per story | `stories/<id>/facts.json` | Claims have sources, DOI or URL, and verified flags (for example Tunguska). The input quality is good, but it is authored by hand. **[V]** |
| Tests | `illustrated_engine/tests/test_v15.py` | 11 passed in 0.56 s during this audit. **[M]** |
| Leak scan | `engine/leak_scan.py` | Blocks model and tool names (FLUX, Kokoro, …) from appearing on screen. **[V]** |

The legacy `src/` stack has reusable parts that V15 does not use:
- `src/providers/llm_provider.py` + `factory.py`: an LLM provider ABC with a config-driven role → provider map and `ChainLLMProvider`. This is the closest thing to the required adapter.
- `src/research/research_agent.py`: web research via DuckDuckGo, Brave or Google CSE.
- `mission_run.py` stages: `stage_research`, `stage_fact_verification`, `stage_script`, `stage_script_review`.

---

## 2. Gap analysis vs. the brief

Legend: ✅ meets the bar · 🟡 partial · ❌ missing.
Scores are my judgement (0–10 vs. the top 1% of the niche). They are based on the two V15 finals (`ice_slippery`, `cell_scale_dive`), their judge sheets, and frames I extracted at t=0.5 s and t=12.3 s.

### 2.1 Story: 🟡/❌ (score 4/10)

- ❌ **No topic engine or script generation in V15.** V15 consumes pre-written `stories/<id>/story.json` + `facts.json`. Commit history shows these were authored by earlier agent sessions (a fixed corpus of 27). "Many videos" is therefore capped by hand-authoring. **[V]**
- ❌ **No hook engineering.** The hooks are textbook questions:
  - "…Why is ice slippery?"
  - "Think your world is small?"
  - Headlines like "WHY IS ICE SLIPPERY?" and "HOW SMALL IS SMALL?"
  - The first spoken word lands at ~0.3–0.6 s (first caption cue at 0.59 s). There is no pattern-breaking visual or claim in the first second.
  - The only hook check is one judge boolean on the first frame (`hook_stops_scroll`). **[V][M]**
- ❌ **No loop-back ending.** "loop" appears nowhere in the V15 code. Payoffs resolve but do not wrap back to frame 1 (for example "So ice is slippery — the leading explanation…"). **[V]**
- 🟡 **Structure:** beat functions are HOOK / CURIOSITY / REVEAL / EXPLANATION / ESCALATION / PAYOFF, and the story JSON has a `contradiction` field. The curiosity-gap and escalation scaffolding exists as data but is not scored or enforced in V15. **[V]**
- 🟡 **Writing quality:** the scripts are accurate but explanatory in register, and hedged ("the leading explanation", "is thought to have"). They are human-sounding but not emotionally charged. **[judgement]**
- ❌ **No length budget in V15.** Tunguska is 199 words (~75–80 s at the current pace), beyond the 30–60 s target. Nothing in V15 rejects it. **[M]**
- ❌ **No dedupe, virality scoring or topic history** in V15. The legacy `topic_history.json` exists at the repo root, but V15 does not use it. **[V]**

### 2.2 Visuals: 🟡 (score 6/10)

- ✅ The plates are rich, story-specific and attractive (engraving/watercolour looks). Judge verdicts: `template_feel:false`, `hook_stops_scroll:true` on both finals. **[V]**
- 🟡 **Motion density is below the bar.**
  - The bar is "nothing static for more than ~1.5 s". The gate allows `MAX_HOLD_S = 4.5` and the measured max hold is 3.86 s (ice) and 3.78 s (cell).
  - Average *shot* length is about 4.6 s (11 shots / 50.4 s) and 3.6 s (15 / 54.5 s).
  - Between cuts, the motion is a slow camera move on a still plus label or number reveals. **[M]**
- 🟡 **Visual vocabulary is 3 shot kinds** (plate, zoom_through, process). The brief's mix is still missing:
  - maps and diagrams (V14 grammars exist only as the procedural floor tier)
  - kinetic typography as a scene type (only headline and giant number overlays exist)
  - a mascot or character animation
  - parallax beyond the single subject band
  - licensed footage
  - charts **[V]**
- 🟡 **Overlay quality defects still pass the gate.**
  - Ice frame 4 shows "WATER SQUEEZED OUT" as a half-faded box overlapping the caption area. The judge flagged `text_garbled`, but the gate only fails on 2 or more critical frames.
  - Cell frames 4 and 12 were flagged `no_change` and still passed (under the 25% threshold). **[V][M]**
- ❌ **No AI-video or animated layer**, by design: the V15 non-goals list excludes AI video. Everything moving is camera and overlay animation on stills. **[V]**

### 2.3 Channel look / brand bible: ❌ (score 3/10)

- ❌ **There is no channel-level brand bible, and nothing enforces one in code.**
  - `load_style()` uses the story's own `visual_bible.json`, or derives one of **5 different decks** (vintage_ink, nocturne_gouache, blueprint, archival_etching, watercolor_atlas).
  - Across the 27 bibles the brand name varies: SURFACE (in story.json) vs. "ABOVE THE CLOUDS" (in the bible) for the same ice story, then EVENT HORIZON, ABYSS, SIGNAL, …
  - The accent colour varies (#9C522C, #C25B33, #E0A33C, #2E7E8C, …).
  - The style prompts contain copy-paste errors: phone_heating, sahara_greening and titanic_mistake all say "aeronautical engineering illustration". **[M]**
- 🟡 The de facto house look is vintage ink/sepia with Bebas Neue + Inter and a rust accent. It is consistent *by accident*, not by rule. **[M]**
- ❌ **No grading LUT.** There are no `lut3d`, `.cube` or haldclut references in V15. The legacy `stage_cinematic_grade` uses `eq`/`curves` and only covers the horizontal path. **[V]**
- ❌ **No intro sting, no outro format, no cover frame or thumbnail generator, no mascot, no logo or watermark.** The code grep found no implementation; "sting" and "cover" only match unrelated words like "fit: cover". **[V]**

### 2.4 Voice: 🟡/❌ (score 5/10, high risk)

- 🟡 There is one fixed narrator: Fish Audio `s2.1-pro-free`, voice `0327fdb5…` ("Narrator by Max N"), pinned in `engine/tts.py` and `configs/voices.yaml`. The voice is consistent. **[V]**
- ❌ **No fallback in V15.**
  - `tts.py` says: "If the Fish API fails … we STOP — never switch provider or tier."
  - The legacy chain in `src/providers/tts_provider.py` (Chatterbox, Edge, Kokoro, ElevenLabs) is **not wired into V15**.
  - This is a single point of failure for any new story. The existing stories only work because their WAVs are cached under `stories/<id>/audio/`. **[V]**
  - Per AGENTS.md, adding a fallback is allowed, while removing one needs approval.
- ⚠️ **Free window:** `tts_provider.py` records "Free window currently ends 2026-08-31". Today is 2026-09-27. Fish availability and pricing now are **[U]**, and I did not call it.
- ⚠️ **Commercial terms are unresolved:** the code comment says the product pages allow commercial use for <$1M ARR, but the Aug-2024 ToS says free = non-commercial. **[V] (as documented), [U] (current terms)**
- 🟡 **Expressiveness:** the style tags are deliberately restrained (`[calm]` / `[measured]` everywhere) and speed is 0.95. That is a documentary delivery, with lower energy than top Shorts narrators. **[V]** Audio quality and artifacts were not assessed by listening. **[U]**
- ❌ **No pronunciation lexicon or IPA overrides** in the V15 path. **[V]**
- 🟡 **No word timestamps from TTS**, so timing is recovered from silence (see §1). Captions are phrase-accurate, not word-exact. **[V]**

### 2.5 Captions: 🟡 (score 5/10)

- ✅ Burned in, phrase-timed, active-word highlight in the accent colour, identity-checked against the narration by the gate. **[V]**
- ❌ **Size and placement.**
  - Each caption is a 1080x192 strip with ink at rows 43–135 (about 50 px letter height inside a ~92 px pill). It is overlaid at band top ≈ y 1464, so the text sits at y ≈ 1507–1599, which is **78–83% of frame height**. **[M]**
  - That is inside the Shorts bottom overlay (title, channel and sound row). The usual guidance keeps key content out of roughly the bottom 20–25%. **[U: exact YouTube UI inset]**
  - Top channels use larger (≈90–130 px) bold centred captions around 55–70% height. **[judgement]**
- 🟡 **Keyword emphasis** exists only as the "active word" highlight. There is no semantic emphasis (numbers or key nouns bigger or coloured), no pop or scale animation per word, and no emoji or icon accents. **[V]**
- ❌ **Safe-zone checks do not cover captions or the right-side action rail.** The gate's `SAFE = (40, 60, 1040)` checks only the x-range and the top of scene text boxes. It does not check the bottom UI band or the right-edge button column. **[V]**

### 2.6 Music and SFX: 🟡 (score 4/10)

- ✅ The technical mix is good: voice ducking, SFX on cuts and reveals, −14 LUFS, true peak ≤ −1.4 dBTP, no dead air. **[M]**
- ❌ **Not mood-matched.** `procedural_audio.underscore()` is the *same* A-minor pad plus a 68 BPM pulse for every video (fixed seed). Only its gain follows beat intensity. There is no genre or mood selection and no licensed or CC0 music library. **[V]**
- ❌ **No sonic identity.** There is no sting and no signature motif or logo sound. **[V]**
- 🟡 **SFX are procedural** (whoosh and similar via `procedural_audio.sfx`). They are consistent but thin compared with library SFX. **[V]**
- ❌ **Cuts are not aligned to music beats.** Cuts follow narration words only. **[V]**

### 2.7 Pacing: 🟡 (score 5/10)

- ✅ Cuts land on narration words (`CUT_EARLY_S = 0.12` before the word). Reveals are word-anchored. **[V]**
- ❌ **No pattern-interrupt policy.** There is no rule like "every N seconds, a zoom-punch, a colour flash, a sound hit or a scene-type change". The judge's `no_change` flags on cell frames 4 and 12 confirm stretches of near-identical imagery. **[V]**
- 🟡 **Shot cadence:** the planner targets a new picture every 2.5–4 s. The niche bar is about 1–2 s. **[V]**

### 2.8 Format: ✅/🟡

- ✅ 1080x1920, 30 fps, 50.4 s and 54.5 s. **[M]**
- 🟡 Length is not enforced (Tunguska at ~75 s+). There is no justification field for long videos. **[V]**
- 🟡 The delivered file is about 39 Mb/s (crf 18, 250 MB per 50 s). That is acceptable for upload but heavy for Discord posting, which Phase 5 needs. **[M]**

### 2.9 Constraints

| Constraint | Status | Detail |
|---|---|---|
| 1. Zero additional cost | 🟡 | Nothing paid is *enabled* in V15. However, the V15 LLM fallback is `z-ai/glm-5.3-flash` on OpenRouter; the model id has no `:free` suffix, so it probably draws OpenRouter credits **[U]**. The NVIDIA NIM "free" key is a trial/evaluation tier **[U: production-use ToS and credit cap]**. Fish is a free tier past its documented window **[U]**. See §3.2. |
| 2. CPU-only ARM | ✅ | Remotion (Chromium headless), ffmpeg, numpy and Pillow all run here. Measured cold Remotion cost is ~7–8 s of wall time per output second at concurrency 2 (§5). All image, LLM and TTS generation is **remote**, so nothing heavy runs locally except rendering. |
| 3. Provider-agnostic LLM adapter | ❌ | V15 calls go through `engine/director.py` `text_ask` / `vision_ask`, which hard-codes Gemini 2.5-flash then GLM-5.3-flash via raw `urllib`. That is a **second** LLM layer, parallel to `src/providers/llm_provider.py` (the role-configured `ProviderFactory` used by `mission_run.py`). There is no single adapter, no per-stage config for V15 and **no Claude CLI provider**. The prompts are fairly model-agnostic (explicit rules and a JSON shape) but have **no JSON Schema validation at the adapter level and no few-shot examples**. `vision_ask` salvages malformed JSON with a regex and repair ladder. |
| 4a. Licensed assets + per-video manifest | ❌ | There is no license manifest. Plate provenance sidecars exist (`build/cache/v15_plates/<key>.json`: provider, model, seed, prompt), which is a good start, but they are not aggregated per video. The model licences are unverified **[U]**: FLUX.2-klein-4B (believed Apache-2.0), FLUX.1-dev (non-commercial model licence; output terms need checking), FLUX.1-schnell (Apache-2.0), Pollinations and Gemini-image output terms. Music and SFX are procedural and self-generated, so there is no licensing issue. Fonts: Bebas Neue, Inter and Archivo Black are OFL. |
| 4b. Distinct, non-mass-produced | 🟡 | Plates are per-story and the judge's `template_feel` check exists. However, the shared structure (3 shot kinds, the same beat functions and the same bed) is a mass-production signal at batch scale **[judgement]**. There is no cross-video similarity gate in V15; V11's `template_signature.py` and `editorial_signatures/` exist but are not wired into V15 **[V]**. |
| 4c. Facts verified, AI disclosure, no misleading clickbait | 🟡/❌ | `facts.json` is verified by hand and the plan's digit guard stops invented numbers. However, V15 has **no automated claim verification** of narration against sources (the legacy `stage_fact_verification` exists). There is **no AI-disclosure flag**, even though the plates are AI-generated and some depict realistic historical scenes. There is no clickbait check on titles. |
| 5. Don't break what works | ✅ | V15 is additive; v14_pipeline and mission_run remain. |

### 2.10 V15's own validation status

- M8 is **not finished**.
  - `batch_report.json` has only ice and cell, and both were **warm-cache reruns** (llm_calls 0, image_calls 0, render 0.3 s for ice).
  - `build/v15/tunguska_1908/` has a plan and plates but **no scenes, no final and no report**.
  - `V15_REPORT.md` does not exist.
  - Generalisation to an unseen story is therefore **unproven**. **[V]**
- Only 2 finished videos exist, both on stories that V15 was iterated against, so there is a risk of overfitting. **[judgement]**

---

## 3. External service / API inventory

### 3.1 Full inventory

"Stage" = the pipeline that calls the service. **V15** = `illustrated_engine/engine/v15_*`. **Legacy** = `mission_run.py`, `mission_stills.py` and `src/`.
Keys present in `.env` (names only): DEEPSEEK, ELEVENLABS, FISH, GEMINI, GROQ, HF_TOKEN(+ALT), MISTRAL, NASA, NVIDIA, OPENROUTER(+ALT), PEXELS, PIXABAY, SILICONFLOW, SLACK_APP/BOT, XAI, ZAI.

| # | Service | Purpose | Called by (stage) | Cost model | Known limits (from code, config or docs) | DeepSeek / GLM? |
|---|---|---|---|---|---|---|
| 1 | **Google Gemini API** `gemini-2.5-flash` | Text judge (BVP plan), vision judge (plate QA, final judge) | **V15** `director._text_gemini` / `_vision_gemini` (primary); Legacy `GeminiProvider` (planner/critic roles) | Free tier | `configs/pipeline.yaml`: "Gemini 2.5-flash free quota is only **20 req/day**". The code waits ≥4 s between calls and backs off for **1 h on a 429**. At ~3–4 calls per video, that is about **5 videos/day** before everything falls to GLM. **[V comment, U current]** | No |
| 2 | **OpenRouter → `z-ai/glm-5.3-flash`** | Fallback text and vision judge | **V15** `director._text_glm` / `_vision_glm` | **Credit-based [U]** (no `:free` suffix) | Reasoning model; needs `reasoning.effort=low` or it can return empty output (documented bug fix) | **GLM: yes** |
| 3 | **Z.AI API** `glm-5.3-flash` (`api.z.ai`) | Chain last resort; **final claim-verification gate** (`get_final_gate_llm`) | Legacy only (`ZaiProvider`, `ChainLLMProvider`) | **Paid** ("paid last resort", "paid high-confidence gate" in `factory.py`); pricing recorded as $0 "not yet tracked" | none recorded | **GLM: yes** |
| 4 | Gemini `gemini-3.7-flash` | Legacy default text role (`pipeline.roles.default: gemini37`) | Legacy | Free tier | "intermittent 503 high-demand" | No |
| 5 | Groq `llama-3.3-70b-versatile` | Legacy cost-chain member | Legacy | Free tier **[U limits]** | — | No |
| 6 | OpenRouter `google/gemma-4-26b-a4b-it:free` | Legacy cost-chain member | Legacy | Free (`:free`) | OpenRouter free-model RPD caps **[U]** | No |
| 7 | Mistral `mistral-small-latest` | Legacy (retired from roles, class remains) | Legacy | Free tier **[U]** | — | No |
| 8 | xAI Grok `grok-3` | Legacy chain (if key present) | Legacy | **Paid / credit [U]** | — | No |
| 9 | NVIDIA NIM (integrate.api.nvidia.com) `nemotron-3-super-120b` | Legacy LLM routing experiment | Legacy (`LLM_ROUTING_EXPERIMENT`) | Trial credits **[U]** | — | No |
| 10 | **DeepSeek** | Formerly scripts and review | **None active.** Retired 2026-08-30 ("Don't use deepseek at all anywhere", `pipeline.yaml`). Key still in `.env`; old `review_deepseek.json` artifacts remain. | Paid (no credits left per brief) | — | **DeepSeek: retired**. The brief's "Scripts: DeepSeek" is stale. |
| 11 | **NVIDIA NIM image** FLUX.2-klein-4b → FLUX.1-dev → FLUX.1-schnell (`ai.api.nvidia.com`) | Plate generation (primary; 87 of 89 cached plates) and FLUX Kontext edit | **V15** `v15_plates` via `image_gen.NvidiaNimProvider`; Legacy `stage_ai_imagery` | "Free API key" = **NVIDIA API-catalog trial [U: credit cap and production-use ToS]** | Median 5.7 s, max 32 s per plate **[M]**; max dimension 2048 | No |
| 12 | SiliconFlow FLUX.1-schnell (`api.siliconflow.cn`) | Plate fallback 2 | V15 chain | Free credits **[U]** | — | No |
| 13 | Hugging Face router `hf-inference` FLUX.1-schnell | Plate fallback 3 | V15 chain | HF **monthly included credits** (402 when depleted) | Monthly | No |
| 14 | Pollinations (`image.pollinations.ai`) | Plate fallback 4 (keyless); 2 of 89 cached plates | V15 chain, Legacy | Free, keyless | Rate limits **[U]**; output terms **[U]** | No |
| 15 | Gemini image `gemini-2.5-flash-image` | Plate fallback 5 | V15 chain | Free tier **[U quota]**; SynthID watermark | — | No |
| 16 | **Fish Audio** `s2.1-pro-free` (`api.fish.audio`) | **The only V15 narrator** | **V15** `engine/tts.py` (no fallback) | Free tier | "fair-use, no hard char cap, 5 concurrent, no SLA; **free window ends 2026-08-31**"; MP3 128 kbps cap; commercial terms conflict | No |
| 17 | ElevenLabs | Legacy narrator option | Legacy `ElevenLabsProvider` | Freemium / **paid** (free plans can't use library voices) | Monthly char quota **[U]** | No |
| 18 | Microsoft Edge TTS (edge-tts) | Legacy TTS fallback | Legacy | Free, unofficial endpoint | No SLA; ToS grey area for commercial use **[U]** | No |
| 19 | Chatterbox TTS (local) | Legacy primary TTS | Legacy (`venv-cb`) | Free, local (MIT) | CPU RTF ~12–14x (per brief). The reference voice `cache/voices/ref_thomas.wav` ("kurzgesagt_like") is a **voice-clone rights risk [U]** | No |
| 20 | Kokoro ONNX `kokoro-v0_19.onnx` (local) | Legacy TTS last fallback | Legacy | Free, local (Apache-2.0) | — | No |
| 21 | Pexels, Pixabay video APIs | Legacy stock footage | Legacy `asset_provider` | Free with key | Pexels 200 req/h, 20k/mo; Pixabay 100 req/60 s **[U, public docs]** | No |
| 22 | NASA Images API / api.nasa.gov | Legacy stills | Legacy | Free (key) | api.nasa.gov 1,000 req/h **[U]** | No |
| 23 | Wikimedia Commons, Internet Archive | Legacy stills and footage | Legacy | Free; **per-file licences vary** (CC-BY-SA needs attribution/share-alike) | — | No |
| 24 | Kaggle Datasets API | Legacy research bonus | Legacy `stage_kaggle_research` | Free | Needs `~/.kaggle/kaggle.json` | No |
| 25 | DuckDuckGo lite / Brave Search / Google CSE | Legacy web research | Legacy `research_agent` | Free / free tier (Brave ~2k/mo, CSE 100/day) **[U]** | — | No |
| 26 | HF ZeroGPU Spaces (LTX, Wan2.2) | AI video (broker) | Legacy / broker only; not V15 | Free daily quota (~5 GPU-min/day) | Daily | No |
| 27 | HF router → fal-ai Wan2.2 T2V/I2V | AI video | Legacy broker | **HF monthly credits** | Monthly | No |
| 28 | MiniMax H3 | AI video | Disabled (`enabled:false`) | **Paid per second** | — | No |
| 29 | Slack (bot/app tokens) | Notifications (legacy) | Legacy | Free | — | No |
| 30 | Remotion 4.0.529 (local npm) | Scene rendering | **V15** | Free for individuals and companies ≤3 people; a **company licence is required above that [U: verify current Remotion licence]** | Local CPU | No |
| 31 | ffmpeg, Pillow, numpy, Chromium (local) | Assembly, analysis, render | V15 | Free / OSS | — | No |

### 3.2 ⚠️ Paid, credit-limited or trial-limited dependencies

| Service | Why flagged | V15 impact |
|---|---|---|
| **Fish Audio s2.1-pro-free** | Documented free window ended 2026-08-31 (now **[U]**). No SLA. Commercial-use terms conflict. **No fallback in V15.** | **Blocks every new story** if it is unavailable. **Highest risk.** |
| **Gemini 2.5-flash free tier** | ~20 req/day (per config comment) | Caps V15 at about 5 videos/day on the primary judge. After that everything runs on GLM. |
| **OpenRouter `z-ai/glm-5.3-flash`** | Probably draws credits (no `:free`) **[U]**. **GLM dependency.** | This is V15's *only* fallback for plan, plate QA and judge. |
| **Z.AI GLM (direct)** | Explicitly paid ("paid last resort" / "final gate"). **GLM dependency.** | Legacy only. |
| **NVIDIA NIM** (image + Nemotron) | Trial/evaluation credits; production-use terms **[U]** | 98% of V15 plates come from NIM. |
| **HF router** (image + video) | Monthly included credits, 402 when depleted | Plate fallback 3 |
| **SiliconFlow** | Free credits **[U]** | Plate fallback 2 |
| **xAI Grok, ElevenLabs, MiniMax** | Paid or freemium | Legacy only; MiniMax disabled |
| **DeepSeek** | Paid, no credits left | **Not used anywhere active.** Key should be removed from `.env` once confirmed. |

**DeepSeek dependency:** none in V15 or the active legacy chains.
**GLM dependency:** V15's LLM fallback (OpenRouter GLM) and the legacy last resort and final claim gate (Z.AI GLM).

### 3.3 V15 LLM call map (all to be routed through the new adapter)

| Stage | Function | Kind | Calls/video | Prompt location | Output contract |
|---|---|---|---|---|---|
| Beat Visual Plan | `v15_plan.make_plan` → `director.text_ask` | text | 1 (+1 retry) | `v15_plan.build_prompt` | JSON shape in the prompt; validated in code (`_check_copy`, enums, word indices, digit guard) |
| Plate QA | `v15_plates.plate_qa` → `director.vision_ask` | vision | 1 (+1 after regeneration) | `v15_plates.QA_QUESTION` | closed fail enum |
| Final judge | `v15_gate.run_judge` → `director.vision_ask` | vision | 1 | `v15_gate.JUDGE_Q` | per-frame issue enum + 3 booleans |
| (not in V15) script, research, fact verification, script review, titles/descriptions | — | — | 0 | Legacy `mission_run.stage_*` | — |

The legacy `engine/` modules `human_editor.py`, `semantic_qa.py` and `template_signature.py` also call `director.*`, but the V15 path does not import them.

---

## 4. Weaknesses ranked by impact on retention and virality

1. **No automated story engine or hook craft (critical).** Topic → research → script → hook → loop is entirely manual. The hooks are soft questions, there is no curiosity-gap check, no loop ending and no length enforcement. Story drives retention more than anything else in the niche, and without an engine batch production depends on hand-authoring. *(§2.1)*
2. **The first 1–2 seconds are under-engineered.** The first frame is a calm plate plus a question headline and the voice starts at ~0.3–0.6 s. There is no scroll-stopping visual event, sting, sound hit or bold claim. The only guard is a single judge boolean. *(§2.1, §2.7)*
3. **Pacing and motion density are below the niche bar.** Shots last 3.6–4.6 s on average, the gate allows holds up to 4.5 s, and motion is mostly slow camera moves on stills. There are no pattern interrupts, and the judge flags `no_change` stretches that still pass. *(§2.2, §2.7)*
4. **Captions are small and sit in the Shorts UI dead zone.** Text is at about 78–83% of frame height, with ~50 px letters and only an active-word highlight. Many viewers watch muted, so this directly costs retention. *(§2.5)*
5. **No enforced channel brand.** Brand names vary per story, the 5 art decks drift, and there is no LUT, sting, outro, cover frame or mascot. This hurts recognisability, returning viewers, subscribe conversion and thumbnail/cover consistency. *(§2.3)*
6. **Voice single point of failure plus low energy.** Fish is free-tier only, possibly expired, with no V15 fallback and unclear commercial terms. The `[calm]/[measured]` delivery is flat for Shorts. *(§2.4)*
7. **Generic, non-mood-matched music and a thin SFX palette.** Every video has the same A-minor pad, there is no sonic signature, and cuts ignore music beats. *(§2.6)*
8. **Limited visual vocabulary.** Only 3 shot kinds. There are no maps, charts, kinetic-type scenes, character/mascot animation, parallax scenes or footage. At batch scale this risks the look of "the same template with a different noun" (a YouTube inauthentic-content risk). *(§2.2, §2.9-4b)*
9. **The gate is too lenient on visible defects.** One garbled or overlapping label passes, as do `no_change` stretches under 25%. The judge sees stills at 3.5 s spacing only (no audio, no motion). There is no retention-oriented scorecard, no caption safe-zone check and no cross-video similarity check. *(§2.2, §2.5, §2.9)*
10. **Compliance gaps.** There is no per-video license manifest, no AI-disclosure flag, no automated claim verification and no title/clickbait check. These are policy risks that can demonetise or suppress a channel rather than retention issues. *(§2.9)*
11. **The LLM layer is not provider-agnostic, and the free quotas are tiny.** Gemini at ~20 RPD means about 5 videos/day, then the GLM fallback, which probably spends credits. There is no Claude CLI provider for the benchmark. *(§2.9-3, §3)*
12. **Unproven generalisation.** V15 finished only 2 videos, both on stories it was tuned against. The unseen Tunguska run stopped after plates, and the V15 report was never written. *(§2.10)*

---

## 5. Stage timings (from existing reports; no new render)

### 5.1 Warm-cache reruns (`build/v15/batch_report.json`, 2026-09-27) **[V]**

| Story | Out len | plan | plates (+QA) | render | assembly | gate (+judge) | **total** | LLM / image / vision calls |
|---|---|---|---|---|---|---|---|---|
| ice_slippery | 50.4 s | 0.0 (cache) | 46.0 | 0.3 (all 11 scenes reused) | 164.4 | 44.7 | **255.9 s** | 0 / 0 / 2 |
| cell_scale_dive | 54.5 s | 0.0 (cache) | 18.0 | 79.7 (1 of 15 scenes re-rendered) | 190.6 | 56.8 | **345.5 s** | 0 / 0 / 3 |
| batch wall | | | | | | | **601.4 s** | 0 / 0 / 5 |

TTS time is not recorded because the beat WAVs are cached per story, and the reports do not time TTS.

### 5.2 Cold-render estimate **[M]**

This comes from the mtimes of the scene `props.json` → `mp4` files in `build/v15/<story>/scenes/`, which record the last real render of each scene.

| Story | Scenes | Remotion render (sum) | Output seconds | **Render cost** |
|---|---|---|---|---|
| ice_slippery | 11 | ~369 s | 50.3 s | **~7.3 s wall per output second** |
| cell_scale_dive | 15 | ~438 s | 54.6 s | **~8.0 s wall per output second** |

Each scene costs about 17–23 s even for ~2 s shots; the 10.5 s zoom_through took 79 s. This matches the ~6.5 s fixed Remotion overhead in V15_PLAN.

The cold plate cache has 89 plates: median **5.7 s**, max 32 s per plate. Plates run 3 at a time, so 12–16 plates take roughly 30–90 s, plus 1–2 QA calls.

**Estimated cold total per ~50 s video (excluding TTS):** plan ~10–30 s [U] + plates and QA ~1–2 min + render ~6–7.5 min + assembly ~3 min + gate ~1 min ≈ **12–14 min**.

- For comparison, UPGRADE_LOG records a V14 end-to-end run of 9 m 38 s.
- A 5-video batch is about **1–1.2 h** of wall time on this 4-vCPU box.
- The main costs are Remotion's per-scene overhead and the ~3 min single-pass assembly (Python-streamed caption overlay, libx264 crf 18 medium).

### 5.3 Why no fresh run

- The brief asks for a run "with the Claude provider if feasible". It is not feasible yet: no Claude provider or adapter exists.
- A fresh story would also need Fish TTS, which may no longer be free, and it would spend the ~20 RPD Gemini quota.
- Per the task instructions, I used the existing reports instead.

---

## 6. Scorecard vs. the quality bar (auditor judgement, 0–10 vs. top 1%)

| Dimension | Score | One-line reason |
|---|---|---|
| Story | 4 | Accurate, structured beats, but written by hand, soft question hooks, no loop, no length budget |
| Visuals | 6 | Rich story-specific plates and word-anchored reveals, but slow cadence and a narrow vocabulary |
| Channel look | 3 | No channel bible, LUT, sting, outro, cover or mascot; the look drifts per story |
| Voice | 5 | Consistent single narrator, but restrained delivery, no fallback, free-tier and licensing risk |
| Captions | 5 | Timing and highlight mechanics are good; too small and too low for Shorts |
| Music/SFX | 4 | Technically clean mix; one generic procedural bed with no identity |
| Pacing | 5 | Cuts on words; holds up to ~3.9 s; no interrupts, no beat sync |
| Format | 8 | 1080x1920 at 30 fps, 50–55 s; length not enforced |
| **Constraints** | — | Adapter ❌ · license manifest ❌ · AI disclosure ❌ · zero-cost 🟡 (quota/trial risk) · ARM ✅ |

---

## 7. Open questions for the owner (before Phase 2)

1. **Fish Audio:** is the free tier still active after 2026-08-31, and are we cleared for commercial use? If not, the voice must move to a local model (Kokoro or Chatterbox, both of which exist in the legacy code). This touches a fallback chain, so it needs S's confirmation per AGENTS.md.
2. **Brand:** should the channel standardise on the existing vintage ink/sepia + Bebas + rust house look (lowest-risk path), or does Phase 3 design a new one?
3. **NVIDIA NIM trial:** is it acceptable as the production image source, or must Phase 2 benchmark a local or commercially clear alternative?
4. **OpenRouter GLM:** does it bill credits on this account? If yes, it conflicts with zero cost as the only V15 fallback.
5. Is it OK to remove the dead `DEEPSEEK_API_KEY` and the DeepSeek review artefacts? That is not a fallback chain; it has been retired since 2026-08-30.
