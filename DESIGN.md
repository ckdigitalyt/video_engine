# DESIGN.md: Phase 3 design for the shorts-v3 quality upgrade

Branch `shorts-v3`. Author: Claude Code (Opus), 2026-09-28. Inputs: `~/UPGRADE_BRIEF.md`, `AUDIT.md` (Phase 1), `RESEARCH.md` (Phase 2) and the owner's Phase 3 decisions.
No pipeline code was modified in this phase. Scripts: `research/phase3/`. Media: `~/phase3_out/`.

Evidence labels follow AUDIT/RESEARCH: **[M]** measured, **[V]** verified from code or a primary source, **[U]** unverified and must be checked in Phase 4 before anyone relies on it.
The working name of the new pipeline is **V16**. It is built *on* V15 (`illustrated_engine/engine/v15_*`), not beside it.

---

## 0. Summary

**The problem.** V15 already has a good render and QA core: native 9:16, AI plates, Remotion shot grammars, word-anchored reveals, −14 LUFS and an honest gate (AUDIT §1). What it lacks is upstream:
- a story engine
- a channel brand
- pacing
- fail-closed QA
- a provider-agnostic LLM layer

The channel's own data says the rest: **story and topic are the levers**. Deep-time series and single-spectacle physics Shorts got a median of ~1,043 views, against ~56 for V15-style explainers (RESEARCH §10).

**What V16 changes:**
1. **One LLM adapter** (`llm/`), with Claude CLI as the default provider and a provider and model configured per stage in `configs/llm.yaml`. Every call is validated against a JSON Schema. Required judges **fail closed**.
2. **A story engine.** It covers topic sourcing and scoring from channel data, series planning, a source-grounded fact sheet, and a script with an enforced hook, a 30–60 s budget and a loop-back ending. A fact-check gate and an honest-title pack follow.
3. **A voice layer** behind one interface: Fish (paid/cleared plan only) or Kokoro `am_michael` (local), chosen **once per video**. It adds word timestamps, a whisper round-trip QA and a pronunciation lexicon.
4. **An image chain rebuilt around FLUX.2-klein:** Cloudflare Workers AI first, local stable-diffusion.cpp as the floor, plus CC0/PD archives and plate reuse. The brand LUT is applied at plate ingest.
5. **A brand bible as code** (`brand/<id>/brand.yaml`). Every stage and the gate read it: palette tokens, LUT, fonts, caption style, safe zones, sting, outro and cover.
6. **A scene-template library** of about 15 typed Remotion templates, chosen by rules from beat content rather than at random. **One Remotion composition per video.**
7. **A scorecard with hard REJECT gates.** Plate QA, the judge, fact-check and the license manifest are all required.
8. **Batch, benchmark and analytics:** a resumable batch runner, a re-runnable quality benchmark with frozen topics, and an analytics loop with a degraded mode that works without OAuth.

**Deliverables B and C** (§17, §18):
- Brand options: `~/phase3_out/brand/` (3 options × 4 frames, a contact sheet each, and `comparison.jpg`).
- Voice samples: `~/phase3_out/voice/fish.wav` and `kokoro.wav`, both at −14.2 LUFS.

**Owner decisions still open** (details in §16):
- brand pick
- Fish-paid vs Kokoro
- Cloudflare credentials
- OAuth re-consent
- music download
- the AGENTS.md-flagged chain changes listed in §15.3

---

## 1. Architecture

### 1.1 Layout (new or changed parts only)

```
llm/                          NEW  the ONE LLM adapter (repo root, so V16 and legacy src/ can both import it)
  client.py                   ask(stage, ...) -> LLMResult; retries, cache, quota state, schema validation
  providers/claude_cli.py     default provider
  providers/{gemini,openrouter}.py   ported from engine/director.py; disabled in config (see §15.3)
  schemas/*.json              one JSON Schema per stage output
  prompts/<stage>.md          versioned, model-agnostic prompt templates + few-shot files
configs/llm.yaml              NEW  provider/model/effort per stage
configs/voice.yaml            NEW  channel voice + fallback + clearance flags
configs/images.yaml           NEW  plate chain order + per-tier budgets
brand/<brand_id>/             NEW  brand.yaml, fonts/, grade.cube, sting.wav, logo.svg, (mascot.json), lexicon.yaml
illustrated_engine/engine/
  v16_topics.py               NEW  topic engine (sourcing, dedupe, scoring, series planning)
  v16_research.py             NEW  source fetch -> facts.json (reuses src/research/research_agent.py)
  v16_script.py               NEW  script write -> critic -> rewrite -> fact_check -> title pack
  voice/{__init__,fish,kokoro,align}.py   NEW  voice layer (replaces engine/tts.py's Fish-only path)
  v16_plan.py                 CHANGED from v15_plan.py: template library + pacing rules
  v16_plates.py               CHANGED from v15_plates.py: new chain, LUT at ingest, fail-closed QA
  brand.py                    NEW  loads + validates brand bible; replaces per-story look (v15_style/bible)
  v16_audio.py                NEW  music selection, SFX library, sting; reuses v14_assembly mix/loudnorm
  v16_gate.py                 CHANGED from v15_gate.py: scorecard + hard gates
  v16_manifest.py             NEW  license manifest + AI disclosure
  v16_pipeline.py, v16_batch.py   CHANGED from v15_*: stage graph, resume, quota pause
  remotion_project/src/       CHANGED: Short.tsx (one <Series> composition), templates/*, Captions.tsx, Sting.tsx
bench/quality/                NEW  frozen benchmark topics, runner, reports
tools/analytics_pull.py       NEW  YouTube Analytics (full) + public-counter (degraded) collector
```

- V15 modules stay importable until V16 reaches parity. Then the dead V15-only paths are deleted, per AGENTS.md: dead code goes, fallbacks stay.
- `mission_run.py` is untouched and must stay runnable (AGENTS.md).

### 1.2 Stage graph and artifacts

Every stage writes one JSON artifact to `build/v16/<video_id>/NN_<stage>.json`, plus a `.done` marker holding the input hash.
- A re-run skips any stage whose input hash is unchanged. This is V15's cache idea (`v14_cache.py`) generalised to every stage.
- The same mechanism makes batches resumable after a quota pause.

```
[batch] S0 topics ─► per video: S1 research ─► S2 script ─► S3 fact-check gate ─► S4 metadata pack
        ─► S5 voice (+timestamps, whisper QA) ─► S6 visual plan ─► S7 assets (plates/archive, LUT, plate QA)
        ─► S8 compose (ONE Remotion render: sting+scenes+captions+outro) ─► S9 audio mix ─► S10 mux/encode
        ─► S11 scorecard + gates ─► S12 package (cover, manifest, disclosure, report) ─► [S13 publish, flag OFF]
[async] S14 analytics pull ─► priors update (topic weights, hook/title stats)
```

A stage either returns its artifact or raises `StageFailed(reason, retryable)`. The pipeline never converts a failure into a PASS. That is the core fix for RESEARCH §2.3.

---

## 2. LLM adapter

### 2.1 Interface

```python
# llm/client.py
@dataclass
class LLMResult:
    data: dict | None          # parsed + schema-validated JSON (None only for schema=None text calls)
    text: str                  # raw model text
    stage: str; provider: str; model: str
    attempts: int; latency_s: float; cached: bool
    usage: dict                # tokens + list-price-equivalent cost when the provider reports it

class LLMUnavailable(Exception):   # every configured provider for this stage is in quota/auth/outage state
    kind: str                      # "quota" | "auth" | "outage"
    retry_at: datetime | None

class LLMSchemaError(Exception): ...  # still invalid after the repair round on every provider

def ask(stage: str, prompt: str, *, schema: str | None = None, images: list[Path] = (),
        vars: dict = {}, cache: bool = True) -> LLMResult
```

- `stage` is the only routing key. Callers never name a provider or model.
- `schema` is the name of a file in `llm/schemas/`. `prompt` is rendered from `llm/prompts/<stage>.md` with `vars`, and the template includes its few-shots.
- Providers implement one method, `complete(req) -> RawResponse`:
  - `req` = system, prompt, images, JSON schema, model, effort, timeout.
  - `RawResponse` = text, usage, a provider-native error kind.
- The existing `engine/director.text_ask/vision_ask` become **thin shims** over `ask()`. The legacy engine modules that import them keep working, and there is exactly one code path.

### 2.2 Config schema (`configs/llm.yaml`)

```yaml
version: 1
defaults: {provider: claude_cli, model: sonnet, effort: medium, timeout_s: 240, max_attempts: 2}
providers:
  claude_cli: {type: claude_cli, bin: claude, fallback_model: haiku}
  gemini:     {type: gemini, key_env: GEMINI_API_KEY, enabled: false}      # free tier 20 RPD [V RESEARCH §9]
  openrouter: {type: openrouter, key_env: OPENROUTER_API_KEY, enabled: false}
stages:                      # model per stage; Opus only where writing quality matters
  topic_ideate:  {model: sonnet}
  topic_score:   {model: sonnet}
  research_extract: {model: sonnet}
  script_write:  {model: opus, effort: high}
  script_critic: {model: opus}
  fact_check:    {model: sonnet}
  metadata_pack: {model: sonnet}
  visual_plan:   {model: sonnet}
  plate_qa:      {model: sonnet, vision: true, required: true}
  final_judge:   {model: sonnet, vision: true, required: true}
  bench_judge:   {model: opus, pinned: true}          # benchmark judge never follows defaults
chains:                      # optional ordered fallbacks per stage; empty = provider default only
  plate_qa: [claude_cli:sonnet, claude_cli:haiku]
```

- A config loader validates this file with a JSON Schema and fails at startup on unknown stages or providers.
- **Switching providers is a config change only.** That is a brief acceptance criterion.

### 2.3 Claude CLI provider

The flags below were verified against `claude --help`, version 2.1.283 **[V]**:

```
claude -p --output-format json --model <model> --effort <effort> \
  --json-schema '<schema json>' --no-session-persistence --strict-mcp-config \
  --tools "Read"            # only when images are passed; otherwise --tools ""
  --add-dir <run_tmp>       # images copied here; the prompt tells the model to Read them
  --disallowedTools "<the PROGRESS.md lockdown list>" \
  --fallback-model haiku --system-prompt-file <run_tmp>/system.md
```

- The prompt goes on stdin. **cwd is a fresh temp dir**, so the repo's AGENTS.md and CLAUDE.md are not loaded into every call. That would waste quota and leak pipeline instructions into creative stages.
- The output envelope is parsed for `result`, `is_error`, `usage` and `total_cost_usd`.
  - With `--json-schema`, the structured payload's field name is **[U]**; WP1 pins it with a recorded fixture.
  - The adapter **always re-validates** with `jsonschema` (4.26 is in `venv` [M]). It never trusts the provider's validation alone.
- Vision uses the Read-tool route that Phase 2 proved (13.8 s, 2 turns, RESEARCH §9).

### 2.4 Errors, retries, quota

| Kind | Detection | Action |
|---|---|---|
| transport / timeout | non-zero exit with no envelope, or timeout | Retry the same provider ×2 with backoff (5 s, 20 s) |
| schema | JSON parse or `jsonschema` failure, empty or refusal text | **One repair round**: re-ask with the validator errors appended ("Your previous output failed: …; return only corrected JSON"). Then move to the next chain member |
| quota | Claude envelope/stderr "usage limit"/"rate limit" (reset time parsed if present); HTTP 429 for API providers | Put the provider on cooldown until `retry_at` (default 1 h), persisted in `build/llm_state.json`, and move to the next chain member |
| auth | 401/403, or "not logged in" | No retry. Raise immediately with the provider name. Never print keys |
| all members exhausted | — | `LLMUnavailable`. **Required stages fail closed** (video HOLD). The batch runner pauses and resumes at `retry_at` (§13) |

- **Cache:** `build/cache/llm/<sha256(stage, prompt_version, provider, model, prompt, image hashes, schema hash)>.json`. Benchmark mode disables it.
- **Usage ledger:** every call appends to `build/llm_ledger.jsonl` (stage, provider, model, latency, tokens, cost equivalent, cached). The batch report sums it.

### 2.5 Prompts and calls per video

- **Model-agnostic prompt template:**
  - a role line
  - explicit numbered rules
  - the output schema (also sent natively where the provider supports it)
  - 2–3 few-shots taken from real channel winners and losers (§9.3)
  - "Return only JSON."
- Each prompt file carries a `prompt_version`. The version is part of the cache key and of every artifact.
- **Budget:** about 9 calls per video (research_extract 1, script_write 1, critic 1, rewrite ≤1, fact_check 1, metadata 1, visual_plan 1, plate_qa 1–2, judge 1), plus about 2 per batch for topics.
  - Opus is used only for write and critic.
  - At the Phase 2 list-price equivalents (~$0.1 per Opus call, RESEARCH §9), that is roughly $0.5–0.8 equivalent of Pro quota per video **[U: Sonnet per-call cost not measured]**.

---

## 3. Stage by stage: what to KEEP from V15, what changes

| Stage | KEEP (evidence) | CHANGE (why) |
|---|---|---|
| S0 Topics | — (none in V15, AUDIT §2.1) | New topic engine (§9) |
| S1 Research | `facts.json` claim schema with source/DOI/URL/verified (AUDIT §1); legacy `research_agent` fetchers | Built automatically from **fetched source text**. Every claim carries a verbatim supporting quote, and code checks that the quote exists in the fetched text |
| S2 Script | `story.json` beat schema: `function`, `narration`, `claim`, `contradiction`, `visual_question/answer`, `fact_ids` (tunguska [V]) | Generated. Hook rules, word budget 75–140, loop-back last line, critic rubric (§9.4). Hedging is allowed only where the source hedges |
| S3 Fact-check | V15 digit guard (every on-screen digit must appear in the narration) | Extended to narration vs `facts.json`: every sentence must be entailed. Title honesty check. Fail → 1 rewrite → HOLD |
| S4 Metadata | — | Title (5–7 words, no hashtags), description (sources, AI note, 3–5 hashtags), series tag, pinned-comment question |
| S5 Voice | Per-video voice lock; loudness chain | Provider-agnostic layer (§5): Fish `with-timestamp` or Kokoro + faster-whisper; lexicon; whisper round-trip QA; `silence_v1` kept as the offline last resort |
| S6 Plan | BVP concept: one call, closed enums, word-index anchors, copy caps, digit guard, deterministic fallback plan (AUDIT §1) | Enums become the **template library** (§8). Pacing: visual change ≤1.5 s target (1.8 s hard) instead of 4.4–4.5 s (AUDIT §2.2); pattern interrupts; hook frame 0 and a loop-bridge last shot |
| S7 Assets | Content-addressed plate cache + provenance sidecar; saliency mask/bbox; model-diverse regeneration on QA failure; FLUX prompt hygiene | New chain (§6); **LUT at ingest** (RESEARCH §6); archive tier; plate reuse; **plate QA fail-closed**: `checked:false` → HOLD, never PASS (RESEARCH §2.3); OCR pre-filter |
| S8 Compose | Shot grammars PLATE_SHOT / ZOOM_THROUGH / PROCESS_OVER_PLATE; font-metric fitting; adaptive ink; leak scan | **One Remotion composition per video** (`<Series>`). 17 × ~23 s fixed overhead today, 431 s → est. 1.5–2.5 min **[U]** (RESEARCH §4.2). Captions, sting and outro move *into* the composition |
| S9 Audio | Voice ducking, SFX on cuts, `loudnorm I=-14:TP=-1.5`, dead-air check (AUDIT §1, measured) | Mood-matched music from a curated library, library SFX, procedural **signature sting**, cuts snapped to music beats where a word boundary is within ±80 ms |
| S10 Encode | 1080×1920, 30 fps, h264/AAC | Captions are no longer a Python overlay pass (170 s today, RESEARCH §2.2), so this is mux + audio only. crf 20 master + a ~8 Mb/s Discord proxy (AUDIT §2.8) |
| S11 Gate | V15 gate checks (caption identity, bounds, info floor, tier, LUFS, A/V); judge unavailable → HOLD | Full scorecard (§10). Any critical judge frame fails, not ≥2. Judge frames every 1 s for the first 3 s, then every 2 s. Plate QA, fact-check and manifest are required. Safe zones cover captions + right rail |
| S12 Package | `pipeline_report.json` | Cover PNG, metadata txt, `manifest.json` (§11), scorecard |

---

## 4. Hook, loop, length (cross-cutting rules)

**Hook** (first 1–2 s):
- The first sentence is ≤12 words and states a concrete, surprising claim. A bare question is not allowed ("Why is ice slippery?" is out; "That pigeon is a dinosaur." is in).
- The voice starts ≤0.25 s: leading silence is trimmed.
- **Frame 0** already shows the hook headline (2–5 words) over the strongest plate. There is no fade from black.
- The intro sting is an **overlay** (logo ping plus a 0.4 s sonic motif under the first words), **not a pre-roll**.

**Loop:**
- The last line is written to flow syntactically into the first line. For example, "…remember what it is." → "That pigeon is a dinosaur."
- The last shot is a `LOOP_BRIDGE` that returns to the hook plate and camera, so the last frame matches frame 0.
- There is **no static end screen**: it would kill the replay.
- The outro is a brand stamp plus a "Part 2" badge on the final 1.5 s of moving footage.

**Length:**
- Script 75–140 words, at the measured ~145 wpm for both voices (RESEARCH §3.3).
- Hard gate after TTS: **30–60 s**. More than 60 s needs a `length_justification` field and an owner flag; otherwise REJECT.

---

## 5. Voice layer

### 5.1 Interface and config

```python
# engine/voice/__init__.py
@dataclass
class VoiceResult: wav: Path; words: list[Word]; provider: str; voice_id: str; model: str
                   commercial_ok: bool; license_ref: str; rtf: float
def synthesize(script: Script, cfg: VoiceConfig) -> VoiceResult   # whole video, one voice
```

```yaml
# configs/voice.yaml
channel_voice: kokoro_michael          # OWNER DECIDES after the §18 samples; fish_narrator allowed only if cleared
voices:
  fish_narrator:  {provider: fish, model: s2.1-pro, reference_id: 0327fdb5…, requires_plan: paid,
                   commercial_ok: false, speed: 1.0}   # flips to true only when FISH_PLAN=paid is set AND voice rights confirmed
  kokoro_michael: {provider: kokoro, model: ~/models/kokoro/kokoro-v1.0.onnx, voice: am_michael,
                   precision: fp32, speed: 1.0, commercial_ok: true, license_ref: Apache-2.0}
fallback: [kokoro_michael]             # whole-video switch only
publish_requires_commercial_ok: true
```

### 5.2 Rules

- **Fish never uses the free tier for monetised output.** `s2.1-pro-free` is not a configurable production model: its ToS is non-commercial (RESEARCH §3.2).
  - The Fish provider refuses to run for a publishable video unless `FISH_PLAN=paid` is set and `commercial_ok: true`.
  - A video rendered with a non-cleared voice gets `publishable: false` in its manifest, and the publish step refuses it.
- **The voice is chosen once per video**, before the first synthesis.
  - If the chosen provider fails partway, the partial audio is discarded and the **whole** script is re-synthesised with the fallback. Voices are never mixed.
  - The switch is recorded in the manifest and the report.
- **Kokoro is the always-available fallback:** local, 0.7 GB, RTF 0.56–0.65 [M]. Use fp32, not int8, which is 2.7× slower on this CPU (RESEARCH §3.3).
- **Synthesis is per sentence**, then joined with designed gaps (hook 80 ms, normal 150 ms, before the payoff 300 ms). This gives pacing control.
  - Speed is modulated per beat function within 0.95–1.08.
  - A peak limiter runs before loudnorm, because Kokoro can exceed 1.0 (RESEARCH §3.4).
- **Timing:** Fish word timestamps when Fish is the voice (median 60 ms vs whisper [M]). Otherwise **faster-whisper base.en** word timestamps (RTF 0.27 [M]).
  - Whisper tokens are aligned to *script* words by sequence alignment. The script is the source of truth for spelling.
  - `silence_v1` is kept as the offline last resort (a load-bearing fallback, AGENTS.md).

### 5.3 Pronunciation lexicon and QA

- `brand/<id>/lexicon.yaml` maps a word to a respelling, and an optional phoneme string for Kokoro **[U: kokoro-onnx phoneme input API]**.
- Round-trip QA runs whisper base.en on the final voice track.
  - Normalised WER must be ≤0.03, and every **hard token** (names, numbers, lexicon entries) must match.
  - On a mismatch, that sentence is re-synthesised once with its respelling, then the video goes to HOLD.
- Evidence from the §18 samples: Kokoro's "Tyrannosaurus" came back as "tirenosaurus". That is exactly the case the lexicon exists for.

---

## 6. Image-source chain

### 6.1 Chain (config `configs/images.yaml`)

```
plate request {prompt, style_variant, seed, size, role: hero|support}
 0. cache hit (key includes model id + style_variant + brand LUT hash)
 1. plate library match (idle-built library; tag + prompt-embedding-free text match on subject tags)   [later WP]
 2. archive tier — only for shot.kind == "artefact/real object/place" (NASA, Smithsonian OA, Met OA, LoC, BHL; PD/CC0 only)
 3. Cloudflare Workers AI  FLUX.2-klein-4B       ← fast primary; skipped cleanly if CLOUDFLARE_ACCOUNT_ID/_API_TOKEN absent
 4. Gemini image (existing V15 link, kept; 429 today; SynthID; flagged in manifest)
 5. local FLUX.2-klein-4B via stable-diffusion.cpp  ← owned floor: ≤3 plates per video (~20 min each [M]),
                                                      otherwise the video waits in state "needs_plates"
 6. Pollinations (existing, kept as last resort): watermark detector + crop, flagged, never for hero shots
 7. V14 procedural tier: support shots only; the gate fails procedural HOOK/PAYOFF (existing rule)
```

**Changes vs V15.** The owner authorised these in the Phase 3 decisions. They are still listed in the PR, per AGENTS.md:
- SiliconFlow (401) and HF `hf-inference` (410) are removed and replaced by tiers 3 and 5.
- NIM leaves the production chain. It stays as a `benchmark_only: true` provider.
- Gemini-image and Pollinations are **kept**. Removing them was not decided, so they stay.

### 6.2 Graceful degradation and demand reduction

**When the Cloudflare credentials are absent:**
- `available()` returns `(False, "CLOUDFLARE_ACCOUNT_ID/API_TOKEN not set")`. It is logged once per batch, and the key value is never logged.
- The batch preflight reports the expected plate throughput.
- The plan switches to **low-plate mode**: ≤6 generated hero plates per video, and everything else from reuse, archive and plate-free templates.

**Cloudflare details:**
- The endpoint is `POST /client/v4/accounts/{id}/ai/run/@cf/black-forest-labs/flux-2-klein-4b` **[U: exact model id, input format (multipart vs JSON) and neuron cost per 720×1280 image]**. WP8 starts with a 4-prompt benchmark using the Phase 2 house prompts.
- The Cloudflare token must be scoped to Workers AI only. Keys are used only for the service they were issued for.

**Plate demand target:** ≤8 generated plates per 45 s video (V15 used 14–15). Each plate yields 2–3 shots through:
- punch-in crops
- camera moves toward different saliency regions
- 2.5D parallax from the saliency mask; `~/models/dav2-small` exists **[U: licence and speed not checked]**
- template scenes that need no plate: kinetic claim, big number, map, timeline

**The local floor also builds a plate library.** A `tools/plate_library.py` cron job runs only when no render is active (`nice 19`, one job). It generates brand-style plates for the topic queue's upcoming subjects, about 70 per day max (RESEARCH §5.3).

### 6.3 LUT at ingest and plate QA (fail closed)

**LUT at ingest:**
- Every plate or archive image passes through `brand.grade(img)`: the brand `.cube` is applied, and the graded copy is stored under a key of (source hash, LUT hash).
- Typography is rendered afterwards in exact brand hexes (RESEARCH §6). This is demonstrated for real in §17: the frames use ffmpeg `lut3d` on cached plates.

**Plate QA, fail closed:**
- A cheap tesseract OCR pre-filter runs first (`/usr/bin/tesseract` is installed [M]). It flags text and watermark candidates.
- Then one vision call on the contact sheet, returning a closed enum: `text, watermark, wrong_subject, off_style, anatomy, realistic_person`.
- Failing plates regenerate on the next tier, at most 2 rounds.
- **If `plate_qa` cannot run, the video is HOLD.** The gate requires `plate_qa.checked == true` and a pass on every plate used. The same watermark/garbled-text plates that shipped in the Phase 2 PASS would now block (RESEARCH §2.3).

---

## 7. Brand bible, enforced in code

### 7.1 Mechanism

`brand/<brand_id>/brand.yaml` is the single source of truth. `engine/brand.py` loads it, validates it with a schema and exposes typed tokens.

```yaml
brand_id: ink_ember            # example = option A
version: 1
channel_name: "Most Amazing"
palette: {paper: "#EDE0C4", ink: "#15202B", navy: "#1F3A56", accent: "#C4502A", gold: "#E3A83B", white: "#FFF7E8"}
roles:   {caption_fill: white, caption_stroke: ink, caption_active: gold, caption_key: accent,
          headline: white, headline_2: accent, label: gold, scrim: ink}
fonts:   {headline: {file: BebasNeue-Regular.ttf, license: OFL-1.1},
          caption:  {file: ArchivoBlack-Regular.ttf, license: OFL-1.1},
          eyebrow:  {file: Fraunces-Italic[...].ttf, instance: "Bold Italic", license: OFL-1.1}}
grade:   {cube: grade.cube, sha256: …, generator: research/phase3/brand_frames.py:make_cube, params: {...}}
plate_style: {prompt_prefix: "...", variants: {ink_day: "...", ink_night: "..."}, banned_terms: [...]}
captions: {size_px: 100, min_px: 84, max_words: 4, max_lines: 2, center_y: 1180, max_width: 780,
           active: underline_gold, keyword: scale_1.18_accent, anim: spring_pop_120ms}
safe_zones: {top: 220, bottom: 1440, right_rail: {x: 930, y0: 760}}   # [U: exact YouTube insets vary]
sting:   {audio: sting.wav, visual: ink_bloom, dur_s: 0.4, overlay: true}
outro:   {visual: seal_stamp, badge: series_part, dur_s: 1.5, loop_bridge: true}
cover:   {template: title_lower_third, title_font: headline, badge: series_part, logo: seal}
mascot:  null
```

### 7.2 How the code enforces it

- **Stories cannot define a look.** `visual_bible.json` and the per-story brand names (SURFACE, EVENT HORIZON…) are removed from the V16 path (AUDIT §2.3). A story may only pick a sanctioned `plate_style.variant`.
- **The Remotion side** receives `brand.json`, staged into `public/`, and only **role names**. The shot compiler rejects any literal colour or font in scene props (a unit test plus a runtime assert).
- **Every plate is graded with the brand cube.** The manifest records the LUT hash for each plate, and the gate checks it.
- **Gate checks:**
  - `brand_version` present
  - all fonts ∈ brand, each with its licence file present
  - sting and outro present in the timeline
  - caption and headline boxes inside the safe zones, including the right rail (AUDIT §2.5); caption size ≥84 px
  - the existing leak scan still runs
- **Units** are always rendered in the caption or eyebrow font. Bebas is caps-only, and "KM²" is visible in the §17 mock.

### 7.3 Brand options

The three options are in §17. **My recommendation is A ("Ink & Ember")**, with an optional `ink_night` plate variant for space topics:
- It keeps continuity with all 100 cached plates and the V15 prompt hygiene.
- It is distinct from the niche leaders (Zack D 3D, Kurzgesagt flat vector).
- It suits the deep-time and history topics that perform on this channel.
- It is the lowest implementation risk.

**B** needs new plate prompts to really look like itself. **C**'s mascot adds cost (§17.3). The owner decides.

---

## 8. Scene-template library (variety from composition)

### 8.1 How templates are defined and chosen

Each template is a typed Remotion component, `templates/<Name>.tsx`, with a Python-side spec:
- slots (plate, text, number, geo, series)
- duration bounds
- a **motion signature**, which guarantees a visible change at least every 1.0 s
- allowed beat functions
- the pattern-interrupt type it provides

The planner (LLM, schema-constrained) proposes templates. **Deterministic rules** then validate and repair the proposal:
- Content signals map to templates:
  - number → BIG_NUMBER
  - place → MAP_PIN
  - time span → TIMELINE
  - two sizes → SCALE_COMPARE
  - process → PROCESS/DIAGRAM
- No template may appear twice in a row.
- Each video uses ≥5 distinct templates.
- No single template takes more than 35% of screen time.
- Frame 0 is HOOK_PLATE or KINETIC_CLAIM, and the last shot is LOOP_BRIDGE.
- Ties are broken by hashing `story_id`, never by a random choice at render time.

### 8.2 The library

| # | Template | Source | Use | Interrupt type |
|---|---|---|---|---|
| 1 | HOOK_PLATE | new | frame-0 plate + 2–5 word claim, fast push-in | — |
| 2 | PLATE_PUSH | V15 PLATE_SHOT | camera to subject bbox, leader label | camera change |
| 3 | ZOOM_THROUGH | V15 | scale dives | scale jump |
| 4 | PROCESS_OVER_PLATE | V15 | causal steps on their words | overlay build |
| 5 | PARALLAX_25D | new (saliency/depth split) | depth drift on hero plates | depth move |
| 6 | KINETIC_CLAIM | new (RESEARCH §4.2 bench) | full-frame kinetic type on a graded texture | type slam |
| 7 | BIG_NUMBER | new | count-up + unit + comparison bar | number pop |
| 8 | SCALE_COMPARE | new | silhouettes to scale (bird vs T. rex) | split |
| 9 | MAP_PIN | new (Natural Earth PD vectors) | place, route, blast radius | map zoom |
| 10 | TIMELINE_DEEPTIME | new | geological scroll with "you are here": the **deep-time series signature** | scroll |
| 11 | DIAGRAM_ARROWS | new (SVG/Lottie) | cross-sections, forces | draw-on |
| 12 | BEFORE_AFTER | new | wipe between two states | wipe |
| 13 | ARCHIVE_DOC | new | PD engraving or photo, pan & scan, source tag | texture change |
| 14 | RANK_CARD | new | top-N countdown badge transition | rank slam |
| 15 | LOOP_BRIDGE | new | return to hook plate and camera | — |
| (16) | MASCOT_REACT | only if option C | ≤1 per video, never in the hook | character |

**Pacing targets:**
- median shot 1.2–2.0 s
- a pattern interrupt at least every 5 s
- the gate hard-fails any hold over 1.8 s without a visual change (§10)

Template choice alone buys a high cut rate: one plate can drive three templates (PLATE_PUSH → PARALLAX → DIAGRAM_ARROWS over the same plate) without generating new images.

---

## 9. Topic engine

### 9.1 Sourcing

1. **Clusters seeded from channel data** (RESEARCH §10.4, `channel_videos.csv`):

| Cluster | Prior (relative) | Evidence |
|---|---|---|
| `deep_time` (extinctions, dinosaurs → birds, early Earth) | 1.00 | 2025-05 series: median 1,043; "Dinosaurs Were Thriving" 1,360, "Dinosaurs' Legacy in Modern Birds" 1,271 |
| `spectacle_physics` (one counter-intuitive visual phenomenon) | 0.85 | "How Scientists Created a Time Crystal" 1,093; "Physics.exe" 1,086 |
| `exotic_space_travel` (warp, wormholes, FTL; honest framing) | 0.70 | long-form warp-drive 90K outlier |
| `space_discovery` | 0.50 | "Universe in 1 Second" 537 |
| `general_explainer` (V15 style) | 0.20 | 2026-06 batch: median 56 |
| quiz / crypto / AI-policy / ASMR | **excluded** | 4–8 views; dilutes the channel's topical signal |

2. **Candidate generation:**
   - LLM ideation (`topic_ideate`), constrained to the clusters and to a "one concrete, visual, counter-intuitive idea" schema.
   - Free evergreen sources through the existing `research_agent`: Wikipedia (featured and "Did you know" archives), NASA APOD archive, EurekAlert/press-release RSS.
   - Facts are not copyrightable. Sources are used for facts, never for copied text.

### 9.2 Dedupe

- Each topic gets a fingerprint: its key-entity set (subject, place, era, phenomenon) plus a normalised claim.
- Candidates are compared against `data/topic_history.jsonl`, which holds every published, queued and rejected topic, seeded from `channel_videos.csv` and the 27 V15 stories.
- Entity Jaccard ≥0.5 or claim token-overlap ≥0.6 counts as a duplicate, unless the candidate is a planned part of the same series.
- This uses the stdlib only. No embedding dependency is justified yet.

### 9.3 Virality score (0–100)

| Component | Weight | How |
|---|---|---|
| Cluster prior | 25 | table above; updated by analytics (§12) |
| Counter-intuitive single idea | 20 | LLM rubric 0–5 |
| Visualisability with our templates | 15 | LLM: name 3 striking frames + templates |
| Hook strength | 15 | LLM writes 3 hooks, rubric-scored (≤12 words, concrete claim, no bare question) |
| Series potential | 10 | can split into 2–3 standalone parts, each with its own payoff |
| Evidence strength | 10 | ≥2 reputable sources, low contention (also a hard gate in S3) |
| Evergreen / freshness | 5 | — |

The rubric's few-shots are anchored on real channel outcomes:
- winners: "Dinosaurs Were Thriving" 1,360; "How Scientists Created a Time Crystal" 1,093
- losers: "Underwater rivers flowing across the ocean floor" 6; "Blood Falls" 136

Candidates must score ≥65 to enter the queue.

### 9.4 Series planning, script rules, fact verification, titles

**Series:**
- A series is 2–3 parts. **Each part stands alone** with its own hook, payoff and loop.
- The last line may tease the next part only if it still loops. For example, the final shot's badge reads "Part 2: why the trees were still standing".
- Series metadata goes into the manifest and the title: "The Blast With No Crater (Part 1)".

**Script critic rubric** (0–5 each, scored by the LLM, JSON):
- hook strength
- curiosity gap
- escalation
- payoff clarity
- loop coherence
- human voice (no "Did you know", no filler)
- emotional charge
- one idea only

The critic's average must be ≥4.0, with nothing below 3. Otherwise one rewrite with the critique, then HOLD.

**Fact verification (S1 → S3):**
- Claims come only from fetched sources. Each claim has a verbatim quote, and code checks that the quote exists in the source text.
- The script must cite a `fact_id` for every sentence.
- `fact_check` (LLM, JSON) labels each sentence `supported | unsupported | contradicted` against its claim quotes.
- Code re-checks every number: narration digits must appear in `facts.json`, and on-screen digits must appear in the narration (the V15 guard).
- Any unsupported or contradicted sentence gets 1 rewrite, then HOLD.
- Example of why this matters: the §17 mock uses "2,150 km²", while `tunguska_1908/facts.json` says "roughly 2,000". The gate would catch exactly that mismatch.

**Title rules** (enforced by code plus an LLM honesty check):
- 4–8 words (target 5–7), a concrete noun plus a twist.
- How/Why/What in ≤50% of a batch.
- **No hashtags in the title.** No emoji by default. No ALL-CAPS words except acronyms.
- A ban list of misleading tropes ("shocked", "you won't believe", "scientists baffled"), unless the claim is literally sourced.
- The title's claim must be entailed by `facts.json`.
- The description carries 3–5 hashtags, the sources and the AI note (§11).

---

## 10. Quality scorecard and REJECT gates

### 10.1 Hard gates (any failure = REJECT/HOLD; never PASS)

| Area | Check | Tool | Threshold |
|---|---|---|---|
| Format | resolution/fps/codecs, duration | ffprobe | 1080×1920, 30 fps, h264/AAC; **30–60 s** |
| Audio | integrated loudness, true peak, dead air, voice stem | ffmpeg ebur128/silencedetect (existing) | −14 ±1 LUFS; ≤ −1.0 dBTP; no silence ≥0.6 s below −45 dB |
| Narration | round-trip WER, hard tokens | faster-whisper base.en | WER ≤0.03 normalised; all hard tokens exact |
| Captions | identity vs narration (existing); timing; size; safe zone | layout log + word times | p90 caption-onset error ≤0.12 s; ≥84 px; boxes inside safe zones incl. right rail |
| Hook | first word time; frame-0 headline; judge `hook_stops_scroll` | voice words, plan, judge | ≤0.25 s; headline present at frame 0; judge true |
| Pacing | max hold without visual change; interrupt spacing | PySceneDetect (cuts) + frame-difference energy every 0.25 s (motion) + plan log | hold ≤1.8 s; interrupt gap ≤5 s |
| Loop | last shot is LOOP_BRIDGE; last/first frame similarity; judge `loop_coherent` | plan, SSIM on 270×480 | SSIM ≥0.6 **[U: calibrate in WP7]**; judge true |
| Plates | QA ran; every plate used passes; OCR clean | plate_qa, tesseract | `checked == true`; 0 fails |
| Facts | every sentence supported; digit guards; title honesty | fact_check + code | 0 unsupported |
| Brand | version, fonts, LUT hash on all plates, sting + outro present | manifest + plan | all true |
| License | every asset has licence, source and `commercial_ok`; voice cleared if publishable | manifest | complete |
| Distinctness | template-sequence signature and plate dHash vs last 30 videos | stdlib/PIL | not a near-duplicate (signature distance ≥0.3, no plate dHash ≤6 reused across videos except library plates) |
| Judges | plate QA and final judge available | adapter | unavailable = HOLD |

Changes vs V15 leniency (AUDIT §2.2 and §4 #9):
- **One** critical judge frame (`text_garbled`, `watermark`, `overlap`) fails the video. V15 needed 2.
- `no_change` frames count against pacing.

### 10.2 Weighted score (0–100)

The score is computed only when every hard gate passes:

| Dimension | Weight |
|---|---|
| Hook | 20 (judge + rules) |
| Story | 20 (critic rubric) |
| Visuals | 15 (judge per-frame) |
| Pacing | 15 (measured cadence vs target) |
| Captions | 10 |
| Audio | 10 (mix metrics + music-mood fit) |
| Brand | 10 |

Verdicts: **≥80 PASS**, 70–79 HOLD for owner review, <70 REJECT. The scorecard is saved as `scorecard.json` with per-check evidence (frame paths, values), so a rejection is explainable.

---

## 11. License manifest and AI disclosure

`build/v16/<vid>/manifest.json` is assembled from the provenance that each stage emits:

```json
{"video_id": "...", "pipeline_sha": "...", "brand": {"id": "ink_ember", "version": 1, "lut_sha256": "..."},
 "publishable": true,
 "voice": {"provider": "kokoro", "model": "kokoro-v1.0 fp32", "voice": "am_michael", "license": "Apache-2.0", "commercial_ok": true},
 "assets": [{"kind": "plate", "sha256": "...", "provider": "cloudflare_workers_ai", "model": "flux-2-klein-4b",
             "model_license": "Apache-2.0", "service_terms_ref": "...", "prompt": "...", "seed": 1,
             "ai_generated": true, "realistic": false, "lut_applied": "..."},
            {"kind": "music", "source": "YouTube Audio Library", "title": "...", "artist": "...",
             "license": "YTAL (attribution not required)", "commercial_ok": true},
            {"kind": "sfx", "source": "Kenney Impact Sounds", "license": "CC0-1.0", "file": "..."},
            {"kind": "font", "file": "BebasNeue-Regular.ttf", "license": "OFL-1.1"}],
 "llm_calls": {"count": 9, "by_stage": {...}},
 "disclosure": {"ai_generated_imagery": true, "realistic_synthetic": false, "synthetic_voice": true,
                "youtube_altered_content": false, "description_note": "Illustrations are AI-generated in our house style; narration uses a synthetic voice."},
 "attribution_block": ""}
```

**Completeness:** every file used in the render must have an entry. The gate compares the render asset log with the manifest.

**Disclosure rule** (conservative):
- `plate_qa` also asks, per plate: "could a viewer mistake this for a real photo or footage of a real event or person?" That sets `realistic`.
- If any plate or clip is realistic, or a voice clone of a real person is used, then `youtube_altered_content = true`. That maps to the Data API `status.containsSyntheticMedia` field **[U: verify the field at WP12]**.
- The description note is always added, for transparency.
- The stylised ink look is the brand's own protection here: it keeps most plates non-realistic.

---

## 12. YouTube Analytics feedback loop

**Full mode** (needs owner re-consent with `youtube.upload`, `youtube.readonly` and `yt-analytics.readonly`, RESEARCH §1):
- `tools/analytics_pull.py` runs nightly. It pulls per-video views, average view duration and percentage, subscribers gained, likes and shares, and the **retention curve** (`audienceWatchRatio` by `elapsedVideoTimeRatio`).
- The data is stored in SQLite (`data/analytics.db`, alongside the legacy postmortem DB). "Viewed vs swiped away" is not in the API **[U]**.
- Each row is joined with the video's features from its manifest and plan: cluster, hook type, template sequence, voice, length, title pattern, brand version, series part.

**Learning:**
- Cluster priors, hook-type and title-pattern stats are updated by shrinkage toward the channel median (n_min = 5 per cell). No weight moves more than 20% per week.
- Changes go to `data/priors.json` with a changelog.
- Retention dips are mapped to the shot or template on screen at that moment and reported in a weekly postmortem.
- **Gates are never auto-changed.** Only topic/title priors move.

**Degraded mode** (the default until re-consent):
- Public counters from `research/phase2/yt_scrape.py` (exact Shorts views, likes where present) at +48 h and +7 d update the cluster priors on views only.
- A manual `tools/import_studio_csv.py` path ingests YouTube Studio exports, including "viewed vs swiped away", if the owner downloads them.

---

## 13. Batch support

```
python -m engine.v16_batch --n 5 [--series tunguska] [--topics topics.txt] [--brand ink_ember] [--resume BATCH_ID]
```

1. **Preflight.** It checks and reports each of these, with no secrets printed:
   - Claude CLI login and quota state
   - voice availability and clearance
   - image tiers available (Cloudflare present?)
   - music and SFX libraries
   - disk space
2. **Topic selection.** The topic engine picks N distinct topics: ≤2 per cluster unless `--series`.
3. **Overlap.** Two lanes: the network/LLM stages (S1–S7) of video k+1 run while video k holds the **render lock** (S8–S10). That keeps the 4 vCPUs busy without CPU contention.
4. **Quota handling.** `LLMUnavailable(quota)` makes the batch checkpoint and exit with code 75, printing `retry_at`. `--resume` continues from the stage markers.
5. **Distinctness.** A cross-video distinctness gate compares each video with the rest of the batch and with history.
6. **Output.** `build/v16/batches/<id>/report.json`, plus a per-video package: `final.mp4`, `proxy.mp4`, `cover.png`, `metadata.txt`, `manifest.json`, `scorecard.json`. That is what Phase 5 posts to Discord. Upload stays behind a config flag, default OFF.

**Estimated cold time per video after WP5:** ~8–10 min. The main costs are plates, ~2 min render, ~1 min encode and the gate **[U]**.

---

## 14. Re-runnable QUALITY BENCHMARK

**Fixed topics** (`bench/quality/topics/`). Each topic has a **frozen research pack**: `facts.json` plus source excerpts, committed, so web variance is removed.

1. Birds are living dinosaurs (deep_time)
2. Tunguska, the blast with no crater (history spectacle)
3. Time crystals (spectacle physics)
4. The Alcubierre warp drive (exotic space; **honesty test**: must not imply FTL is possible now)
5. Snowball Earth (deep time)
6. "5 things older than trees" (top-N format; RANK_CARD)
7. The Wow! signal (mystery; **honesty test**: must say "unexplained", not "aliens")

**Modes:**
- `text`: the LLM stages only (topic_score, script_write, critic, fact_check, metadata, visual_plan). This is cheap and is what compares runtime LLMs.
- `full`: an end-to-end render with a fixed voice (Kokoro, deterministic) and a **frozen plate set per topic**, so image variance does not confound LLM comparisons.

**Scoring** is automatic:
1. Hard-rule pass rates: schema validity first time, retries, length, hook rules, loop, digit guard, fact support, title rules, template rules.
2. Rubric scores from a **pinned judge** (`bench_judge`: fixed provider, model and prompt version).
3. **Pairwise A/B** against the stored Claude baseline outputs, with position swapping to cancel order bias.
4. Latency and cost.

**Report:** `bench/reports/<date>_<provider>_<model>.{json,md}`, with the same columns every time and prompt, judge and topic versions stamped in. Two reports are comparable only when those versions match, and the runner refuses to diff them otherwise.

**Known bias:** when Claude is judged by Claude, self-preference is possible. The report states this, and the pairwise human spot-check column is left for the owner.

`--topics 3` gives a quota-light run of about 20 calls.

---

## 15. Phase 4 implementation plan

### 15.1 Rules for every work package

- Sized for one Sonnet session.
- Small tested commits, with a CHANGELOG.md entry per package.
- `mission_run.py` and `v15_pipeline.py` stay runnable at every commit.
- **A/B checkpoint** means rendering 3 videos (benchmark topics 1–3) with the new build against the V15 baseline, scoring them with the scorecard (or the gate subset that exists so far), and writing `bench/ab/<wp>.md`.

### 15.2 Ordered work packages (by retention impact, respecting dependencies)

| WP | Scope | Files | Tests | Acceptance / A-B |
|---|---|---|---|---|
| **WP0** Baseline + harness skeleton | Freeze V15 baseline scores for ice, cell and blackhole; create `bench/` with the frozen topic packs 1–3 | `bench/quality/*`, `bench/ab/baseline.md` | runner smoke test | Baseline report exists; no pipeline change |
| **WP1** LLM adapter + Claude CLI | §2 in full. `director.text_ask/vision_ask` become shims; Gemini/GLM ported as disabled providers; DeepSeek entries removed from tracked config (queued owner task) | `llm/**`, `configs/llm.yaml`, `engine/director.py`, `configs/pipeline.yaml` | fake-provider tests: retry, repair, quota cooldown, cache key, schema reject; 1 recorded live CLI fixture | V15 plan + plate QA + judge run through the adapter on blackhole; ledger written. **Flag to owner:** default chain changes from Gemini→GLM to Claude (§15.3) |
| **WP2** Fail-closed QA | plate QA required; 1 critical frame = fail; caption safe-zone + right-rail check; OCR pre-filter | `v15_gate.py` → `v16_gate.py`, `v16_plates.py` | unit: `checked:false` → HOLD; fixture with the Phase 2 watermark plate → FAIL | The Phase 2 blackhole final now **fails** (it should) |
| **WP3** Voice layer | §5: interface, Kokoro provider, Fish with-timestamp (paid-gated), whisper aligner, lexicon, round-trip QA, whole-video switch | `engine/voice/*`, `configs/voice.yaml`, `brand/*/lexicon.yaml`; install `faster-whisper` into `venv` | forced Fish failure → whole-video Kokoro; lexicon fixes "Tyrannosaurus"; WER gate | Voice for benchmark topic 1 ≤ WER 0.03; captions p90 ≤0.12 s |
| **WP4** Story engine (script) | S1–S4: research pack → facts with quote check → script (hook/length/loop schemas) → critic → rewrite → fact_check → metadata | `v16_research.py`, `v16_script.py`, `llm/prompts/*`, `llm/schemas/*` | quote-exists check, digit guard, title rules, length rules (pure-code unit tests) | **A/B #1:** new scripts + Kokoro + V15 visuals vs baseline on topics 1–3; hook ≤0.25 s; 30–60 s |
| **WP5** One-composition render | `Short.tsx` `<Series>`; captions, sting and outro inside Remotion (`@remotion/captions`); a pre-bundled render via `@remotion/renderer` | `remotion_project/src/*`, `v16_pipeline.py` | frame-exact parity test vs the per-scene render on ice (SSIM ≥0.98 on 20 frames) | Render time ≤40% of V15 on ice [target]; the Python caption pass is retired only after parity (it is not an external-service fallback) |
| **WP6** Brand bible | `brand/<chosen>/`, `engine/brand.py`, LUT at ingest, roles-only props, brand caption style, sting + outro + cover | `brand/**`, `brand.py`, `v16_plates.py`, `templates/*` | props lint (no literal hex), LUT-hash test, font licence files present | **A/B #2:** on-brand frames; safe zones pass; owner eyeball |
| **WP7** Templates + pacing | the §8 library (at least KINETIC_CLAIM, BIG_NUMBER, MAP_PIN, TIMELINE, SCALE_COMPARE, PARALLAX, LOOP_BRIDGE); planner v2 rules; 1.8 s hold gate | `v16_plan.py`, `templates/*.tsx`, `v16_gate.py`; `npm i @remotion/lottie@4.0.529`; `scenedetect` | rule tests (no repeats, ≥5 templates, frame0/last); one Remotion still per template | **A/B #3:** median shot ≤2.0 s, max hold ≤1.8 s, loop SSIM calibrated |
| **WP8** Image chain | Cloudflare provider (absent-creds path), sd.cpp provider, archive tier, chain reorder, low-plate mode, plate library cron | `src/providers/image_gen.py`, `configs/images.yaml`, `tools/plate_library.py` | absent creds → clean skip + report line; mock HTTP; watermark crop test | 4-prompt Cloudflare bench (when creds exist); a video completes with Cloudflare absent (low-plate mode). **Flag to owner:** chain narrowing list |
| **WP9** Music + SFX + sting | mood-tagged library loader, selection from the arc, library SFX, sting, beat-snapped cuts | `v16_audio.py`, `assets/music/*`, `assets/sfx/*` | licence-row present per file; mix metrics unchanged | **A/B #4:** music-mood fit judged; LUFS/TP gates hold |
| **WP10** Scorecard + manifest | §10 full, §11 manifest + disclosure, distinctness gate | `v16_gate.py`, `v16_manifest.py` | manifest completeness vs render log; distinctness fixture | Every A/B video has a complete manifest; scores explainable |
| **WP11** Topic engine | §9: clusters, ideation, dedupe, scoring, series planner, `topic_history.jsonl` | `v16_topics.py`, `data/*` | dedupe fixtures from the channel CSV; score reproducibility | 20 candidates → ranked queue; no duplicate of existing uploads |
| **WP12** Batch + package | §13: preflight, lanes, quota pause/resume, package, proxy, cover | `v16_batch.py` | resume after a simulated quota at S6 | **Acceptance batch:** 5 videos from one command, all gates, score ≥80, manifests complete, distinct |
| **WP13** Benchmark full | §14: all 7 topics, both modes, pairwise, report | `bench/quality/*` | report schema; version-mismatch refusal | Claude baseline report committed |
| **WP14** Analytics | §12, degraded mode first; full mode after re-consent | `tools/analytics_pull.py`, `tools/import_studio_csv.py` | shrinkage math; bounded step | Priors file updated from public counters |

WP1 must come before WP4, because the story engine needs the adapter. WP3 must come before WP4's A/B, because new scripts need a publishable voice for internal renders.

### 15.3 AGENTS.md items that need S's explicit confirmation in the PRs

1. **LLM:** the V15 default chain changes from Gemini→GLM to Claude CLI. Gemini and OpenRouter stay implemented, but `enabled:false` (owner decision 3 puts GLM out of the required path).
2. **Images:**
   - SiliconFlow and HF are removed (dead: 401/410).
   - NIM becomes benchmark-only (owner decision).
   - Gemini-image and Pollinations are kept.
3. **Voice:** Fish's V15 "no fallback, STOP" policy becomes Fish (paid only) → Kokoro whole-video. This *adds* a fallback, but it changes a documented policy.
4. **Internal paths retired after parity:** the Python caption overlay and per-scene Remotion renders. These are internal paths, not external-service fallbacks, so they are listed for transparency only.

---

## 16. Owner setup checklist

- [ ] **Voice decision:** listen to `~/phase3_out/voice/fish.wav` vs `kokoro.wav` (§18). If Fish is chosen:
  - buy a paid plan and set `FISH_PLAN=paid` in `.env`
  - **confirm commercial rights for the community voice "Narrator by Max N"**, or pick or create a cleared voice (RESEARCH §3.2)
- [ ] **Brand pick:** A, B or C (`~/phase3_out/brand/comparison.jpg`), and mascot yes/no.
- [ ] **Cloudflare:** create a free account and a Workers-AI-scoped API token. Add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` to `/home/ubuntu/video_engine/.env`. The design runs without them, in low-plate mode.
- [ ] **YouTube OAuth re-consent** with `youtube.upload`, `youtube.readonly` and `yt-analytics.readonly`. Check whether the OAuth app is in "Testing" status, where refresh tokens expire after 7 days (RESEARCH §1).
- [ ] **Music:** download 30–50 YouTube Audio Library tracks, filtered to "attribution not required", into `assets/music/ytal/<mood>/` (wonder, tension, mystery, triumph, calm). Add a CSV of title, artist and mood.
- [ ] **SFX:** download the Kenney audio packs (Impact, Sci-fi, Interface) and selected Sonniss GDC bundle files into `assets/sfx/`. Keep the licence files.
- [ ] **Rotate `GEMINI_API_KEY`** (RESEARCH §1).
- [ ] **Approve the §15.3 items** when their PRs arrive.
- [ ] **Remotion licence:** confirm the operation is ≤3 employees, and stay on Remotion 4.x (RESEARCH §4.2).
- [ ] **Quota:** accept roughly 9 Claude calls per video on the shared Pro quota, with Opus used only for script write and critic.
- Phase 4 installs these itself (no owner action): `faster-whisper` and `scenedetect` into `venv`; `@remotion/lottie@4.0.529`; Natural Earth (PD) vectors; the sd.cpp build already in `~/models/sdcpp`.

---

## 17. Deliverable B: brand options for @most.amazing.wonders

**Audience** (RESEARCH §10): cold swipe-feed viewers of space, deep-time and spectacle-physics Shorts, on a 1k-subscriber channel. Recognition has to come from type, colour and sound within 1 s, and without a face.

**Frames:** `~/phase3_out/brand/<option>/{hook,mid,cover,mid_safezones}.png` (1080×1920), `contact_sheet.jpg` per option, `comparison.jpg`, and the generated `<option>.cube`. Script: `research/phase3/brand_frames.py`. The same 3 cached Tunguska plates are used for every option, so the comparison is fair. No image API was called.

| | **A. Ink & Ember** (refined vintage ink) | **B. Deep Signal** (night-sky modern) | **C. Wonder Almanac** (bold pop + mascot) |
|---|---|---|---|
| Idea | The V15 accidental house look, made deliberate: museum engraving with an ember accent | Dark, cinematic, high-contrast "transmission from deep space" | Playful field-guide energy for broad and young audiences |
| Palette | paper `#EDE0C4` · ink `#15202B` · navy `#1F3A56` · ember `#C4502A` · brass `#E3A83B` · bone `#FFF7E8` | void `#070B16` · midnight `#122440` · signal cyan `#3FE0FF` · solar amber `#FFB23F` · starlight `#F2F5FA` | cream `#FFF1D0` · charcoal `#1C1C1E` · sunflower `#FFC83D` · coral `#FF6A4D` · teal `#17A398` · white |
| Fonts (all OFL-1.1) | Bebas Neue (headline) · Archivo Black (captions) · Fraunces Bold Italic (eyebrow/series) | Anton (headline) · Montserrat Black (captions) · Montserrat Bold tracked (eyebrow) | Lilita One (headline) · Nunito Black (captions/eyebrow) |
| Captions | 100 px bone with 9 px ink stroke; active word brass + underline; key word ember at 1.18×; no pill | 100 px white with soft shadow; active word inside a cyan pill; numbers amber | 104 px white with 12 px charcoal stroke and drop; active word sunflower; key word on a coral sticker; spring pop |
| Grade (LUT) | S-curve 0.12, sat 0.92, navy shadows / warm highlights (Phase 2 `brand_v0`) | gamma 1.9 crush, S 0.25, strong teal shadows, warm highlights | lift 0.04, sat 1.9, warm highlights, slight teal shadows |
| Sting (0.4 s overlay) | Ink bloom spreading from the seal + quill scratch + low procedural timpani | Cyan ring ping + scan sweep + two-note synth ping | Mascot pops in the corner + "boing" wood-block motif |
| Outro / loop | Seal stamps onto the final (moving) shot + "Part N" plate; cut back to the hook | Radar rings collapse to a dot on the last shot | Mascot points at the "Part 2" sticker |
| Cover | Plate top 60%, logo seal, 2-line Bebas title (white/ember) lower-middle, series badge | Same grid with cyan second line and pill badge | Mascot above the title, sticker badge |
| Mascot | **No.** An engraving look plus a cartoon clashes; the seal is the recurring mark | **No.** A mascot fights the cinematic tone | **Yes, "Tik" the trilobite explorer.** Deep-time tie-in and a series host, but it needs real character art (Lottie) and consistent posing, and risks a "kids' channel" read |
| Risk / cost | Lowest: matches all cached plates and prompts | Needs a new plate style prompt (`ink_night`) to look native. The LUT alone on sepia plates is only an approximation | Highest: character design + animation + stronger AI/brand consistency burden |

### 17.1 What is real vs mocked in the sample frames

- **Real:**
  - The brand LUTs are generated in code and applied to real cached plates with ffmpeg `lut3d`, which is the proposed ingest step.
  - The OFL font files, with their `OFL_*.txt` files in `~/phase3_out/fonts/`.
  - The exact palette hexes.
  - The safe-zone geometry and caption box.
- **Mocked:**
  - It is a PIL still compositor, not the Remotion renderer. There is no motion (spring pop, sting, parallax) and no grain animation.
  - B and C show **ink plates re-graded**, not plates generated with their own style prompt.
  - The option-C mascot is a placeholder vector sketch.
  - The on-screen figures ("80 million trees", "2,150 km²") are illustrative and were **not** run through the fact gate. `facts.json` says "roughly 2,000 km²", which the §9.4 gate would catch.

### 17.2 Observations from the frames

- Plates carry fake signatures in their corners. The 1.12× punch-in hides them here, but in production the OCR and QA must catch them anyway.
- The 100 px captions sit at y≈1180, clear of the bottom UI and right rail (`mid_safezones.png`). V15's sat at 78–83% of height (AUDIT §2.5).

### 17.3 Recommendation

**A**, with a sanctioned `ink_night` plate variant for space topics (option B's colour logic on dark-ground ink plates). C only if the owner wants a host character, and then as a later layer (WP after WP14) with commissioned or self-made character art.

---

## 18. Deliverable C: voice samples

**Script** (`~/phase3_out/voice/script.txt`, 73 words). The topic matches the channel's #2 Short, "Dinosaurs' Legacy in Modern Birds" (1,271 views). It is hook-first and loops back:

> That pigeon is a dinosaur. Not related to one. It is one. Sixty-six million years ago, a rock ten kilometres wide slammed into Mexico, and the age of giants ended. Tyrannosaurus, gone. Triceratops, gone. But a few small, feathered dinosaurs made it through. They were tiny, and they could live on seeds. Their descendants are outside your window right now. So the next time a pigeon stares at you... remember what it is.

**Results** (measured on this server; `research/phase3/voice_samples.py`, `~/phase3_out/voice/report.json`) **[M]**:

| | Fish `s2.1-pro-free` (comparison only, **not for publication**) | Kokoro v1.0 fp32 `am_michael` (local) |
|---|---|---|
| File | `fish.wav` (raw `fish_raw.mp3`, word timestamps `fish_timestamps.json`, 74 segments) | `kokoro.wav` (raw `kokoro_raw.wav`) |
| Duration | 28.63 s | 26.18 s |
| Wall / RTF | 13.8 s / **0.48** (network) | 14.5 s / **0.56** (+5.9 s model load) |
| Normalised | −14.2 LUFS, −1.6 dBTP (gain + limiter; linear loudnorm undershot to −14.7/−15.1) | −14.2 LUFS, −1.6 dBTP |
| Whisper base.en round-trip | 1 diff: "kilometres" → "kilometers" (spelling only) → effectively **0 errors** | "kilometres" spelling + **"Tyrannosaurus" → "tirenosaurus"** (a probable mispronunciation → lexicon entry) |

- Both use the same speed (1.0) and no emotion tags, for a fair comparison.
- **I cannot listen to audio.** Naturalness, expressiveness and artifacts are for the owner's ears. The objective differences are:
  - Fish is deeper (F0 ~79 Hz vs ~121 Hz, RESEARCH §3.3) and slightly slower here.
  - Kokoro has more pitch movement and needs a lexicon for hard names.

---

## 19. Risks and open questions

1. **Claude Pro quota** is shared with development. At ~9 calls per video, a 5-video batch plus the benchmark may hit limits. The pause/resume in §13 is mandatory, not optional.
2. **Cloudflare is still unbenchmarked [U].** If its free neurons cover fewer plates than estimated, low-plate mode plus the idle library is the plan, and visual richness then leans on templates.
3. **One-composition render speed** is extrapolated from a light bench composition **[U]**. WP5 measures it first.
4. **Retention truth is unavailable** until the OAuth re-consent. Until then, all "retention impact" ordering rests on AUDIT/RESEARCH judgement and public view counts.
5. **Fish community-voice rights are unknown** even on a paid plan **[U]**.
