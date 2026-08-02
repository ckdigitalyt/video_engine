# Jade Studio — Architecture v1

**Mission:** Autonomous, self-improving documentary production studio.
**Date:** 2026-08-02
**Status:** Proposed → Implementing
**Repo branch:** `jade`

---

## 1. Executive Summary

Jade Studio is designed as a **modular, 16-stage documentary production
pipeline** where every stage is independently replaceable, benchmarkable, and
versioned. The system produces cinematic, fact-checked documentaries with
minimal human intervention, and — critically — **improves its own production
system over time** via structured postmortems, versioned prompts, and a
learning database.

The v1 architecture reuses and extends the existing `video_engine` codebase
(LangGraph orchestration, research agent, visual director, asset routing,
Kokoro TTS, MoviePy/FFmpeg rendering) and adds the mission-critical stages
that were missing:

| Missing stage (mission) | Status in existing engine | Action |
|---|---|---|
| Script Review (multi-reviewer) | ✗ absent | **New module** `src/review/script_review.py` |
| AI image generation provider abstraction | ✗ absent | **New module** `src/providers/image_gen/` + benchmark |
| Improvement passes (video-level) | △ partial (critic loop exists) | **New module** `src/review/improvement_pass.py` |
| Learning system / postmortem | △ memory_manager exists | **New module** `src/memory/postmortem.py` |
| Fact verification | ✓ `research_agent.py` (FactVerifier) | Wire + surface in reports |
| Manim first-class | △ `manim/planner.py` + provider exist; binary missing | Install manim, verify renders |
| Music & ducking | ✓ `audio_engine.py` | Extend with procedural ambience option |

---

## 2. Target Pipeline (16 stages)

```
 1. Research            → ResearchAgent (DeepSeek primary) + web search
 2. Fact Verification   → FactVerifier (cross-source confidence scoring)
 3. Story Development   → StoryPlannerV2 / EditorialPlanner
 4. Script Review       → 4 independent reviewer personas, ≤3 passes   [NEW]
 5. Storyboard          → BeatPlanner / StoryboardPlanner
 6. Visual Planning     → VisualDirector (aesthetic agent, motion grammar)
 7. Asset Routing       → AssetRouter (intent-based, cache-first)
 8. Asset Generation    → providers: stock / NASA / Wikimedia / Manim / AI-gen [NEW]
 9. Animation Planning  → MotionGrammar + ManimPlanner + ChartProvider
10. Narration           → Kokoro (bm_george), pronunciation normalization
11. Music & Sound       → bed selection + sidechain ducking
12. Rendering           → MoviePy → FFmpeg (libx264), subtitles
13. Video Review        → Gemini Pro end-to-end review of rendered MP4
14. Improvement Pass    → apply high-value recommendations, re-render ≤3 total
15. Final Output        → deliverables + report
16. Postmortem          → structured learnings → memory.db + docs [NEW]
```

Control rules:
- **No infinite loops.** Script review ≤ 3 passes; render+review ≤ 3 total iterations.
- **Human flag** if a recommendation would materially change the story or conflict.
- **Provider abstraction everywhere** — LLM, TTS, image gen, asset sources are all swappable via config (`configs/providers.yaml`, `configs/models.yaml`, new `configs/image_gen.yaml`).

---

## 3. Module Map (spec stage → implementation)

| Spec Stage | Module | Entry Point |
|---|---|---|
| Research | `src/research/research_agent.py`, `knowledge_graph.py` | `ResearchAgent.research(topic)` |
| Fact Verification | `src/research/research_agent.py` (FactVerifier) | `verify_all(facts, sources)` |
| Story Development | `src/planner/editorial_planner.py`, `story_planner_v2.py` | `StoryPlannerV2.generate()` |
| Script Review | **NEW** `src/review/script_review.py` | `ScriptReviewer.review(script)` |
| Storyboard | `src/director/storyboard_planner.py`, `src/cinematic/beat_planner.py` | `StoryboardPlanner.plan()` |
| Visual Planning | `src/director/director.py` (VisualDirector) | `director.run()` |
| Asset Routing | `src/assets/asset_router.py`, `search_planner.py`, `asset_cache.py` | `AssetRouter.route()` |
| Asset Generation | `src/providers/*` + **NEW** `image_gen/` | ProviderFactory |
| Animation Planning | `src/cinematic/motion_grammar.py`, `src/manim/planner.py`, `src/providers/chart_provider.py` | motion + manim + charts |
| Narration | `src/providers/tts_provider.py` (KokoroProvider), `audio_engine.py` | `generate_voice()` |
| Music & Sound | `audio_engine.py` + **NEW** `src/audio/ambience.py` | `mix_audio()` w/ ducking |
| Rendering | `src/renderer/moviepy_renderer.py`, `timeline_builder.py` | `Renderer.render()` |
| Video Review | `review_video.py` (Gemini Pro, video-capable) | `review_video(path)` |
| Improvement Pass | **NEW** `src/review/improvement_pass.py` | `improve(render, review)` |
| Learning | **NEW** `src/memory/postmortem.py` + `memory_manager.py` | `record_postmortem()` |

---

## 4. Provider Strategy (v1 defaults, benchmark-driven)

**LLM roles** (`configs/pipeline.yaml`):
- Research / planning / script / review (text) → **DeepSeek** (`deepseek-chat`) — primary reasoning engine per mission.
- End-to-end video review → **Gemini Pro** (`gemini-2.5-pro` via google-genai, video input).
- Fallback: the other provider; role-level override via `pipeline.roles.*`.

**TTS:** Kokoro ONNX (`kokoro-v0_19.onnx` + `voices.bin`), voice **bm_george** (default, en-gb). Pronunciation normalization via `src/subtitles` + `tts_provider` text pre-processing.

**Assets (chain order, cache-first):**
1. Asset intent router decides *type*: real footage / still photo / Manim animation / chart / AI illustration / procedural.
2. Real video: Pexels → Pixabay → Internet Archive.
3. Still/public-domain: NASA → Wikimedia Commons.
4. Explanation needs animation: Manim (first-class) → ChartProvider (matplotlib).
5. Concept has no real footage: **AI image generation** (new abstraction; candidates: SiliconFlow FLUX, NVIDIA NIM, HF inference). Benchmarked for realism, prompt adherence, speed, cost → winner becomes default.

**Image generation (NEW)** — `src/providers/image_gen/`:
- Interface: `ImageGenProvider.generate(prompt, size, style) -> Path`
- v1 candidates: NVIDIA NIM (FLUX.1-schnell), SiliconFlow (if key), HF serverless.
- `benchmark_image_gen.py` script records metrics into `cache/benchmarks/image_gen.json`.
- Generated images enter the same asset cache + Ken Burns/parallax motion pipeline.

---

## 5. Script Review Design (NEW — mission-critical)

`src/review/script_review.py` runs **four independent reviewer personas** in
parallel against the draft script, each with a distinct objective:

1. **Fact Reviewer** — checks every claim against the research facts + sources; flags unsupported or overstated claims; returns confidence per claim.
2. **Documentary Editor** — evaluates structure, pacing, transitions, hook, conclusion, clarity; returns line-level edits.
3. **Audience Retention Reviewer** — scores hook strength, curiosity gaps, momentum; flags 15-second drop-off risks.
4. **Storytelling Reviewer** — emotional progression, narrative arc, memorable moments, "spoken vs written" phrasing; flags generic AI phrasing.

Flow:
```
draft → 4 parallel reviews → consolidate (weighted) → revise script → 
re-review (changed areas) → ≤3 passes → quality gate (thresholds) → approve
```

Output: `script.md` (final), `script_review_report.md` (per-pass scores,
resolved issues, confidence). All passes logged to memory.db for learning.

Quality gate thresholds (v1): hook ≥ 8/10, retention ≥ 7/10, fact accuracy
≥ 9/10, no unresolved factual flags.

---

## 6. Video Review + Improvement Pass Design (NEW)

**Review** (`review_video.py` — upgraded to Gemini Pro with video input):
Gemini receives the rendered MP4 + script + storyboard, returns structured JSON:
- strengths / weaknesses
- prioritized recommendations (each with: category, action, expected impact, feasibility)
- quality score (0-100), confidence level
- title + thumbnail recommendations

**Improvement** (`src/review/improvement_pass.py`):
- Parse review → filter to *automatically applicable* recommendations (e.g., pacing tweaks, transition fixes, music level, subtitle timing, shot swaps from cache, color grading, zoom direction).
- Skip + flag for human: story-changing edits, factual disputes, new scenes.
- Apply → re-render → re-review. **Max 3 total iterations** (initial + 2 passes).
- Every pass recorded: what changed, delta score.

---

## 7. Learning System (NEW)

`src/memory/postmortem.py` — after every project writes `postmortem-<topic>.md`:
- successful / failed techniques (with evidence)
- prompt improvements (versioned — old prompts retained)
- visual / narration / rendering optimizations
- review feedback + benchmark results
- recommendations for next project

Stored in: `cache/memory.db` (structured) + `docs/mission/postmortems/` (readable).
Prompt/template/config **versioning**: every prompt has a `version` in
`prompt_library`; configs are git-tracked; learnings reference exact versions
so improvements are measurable and reversible (`git revert`-able).

---

## 8. Benchmarking

- `scripts/benchmark_image_gen.py` — image providers.
- `scripts/benchmark_tts.py` — Kokoro voice/params.
- `scripts/benchmark_render.py` — renderer speed vs quality.
- Results → `cache/benchmarks/*.json` → fed into config defaults + postmortems.
- A/B style comparisons recorded in `results/ab_experiment/` (existing convention).

---

## 9. Demo Documentary Plan (first run)

**Topic:** *Voyager 1 — the farthest human-made object* (space; strong story,
rich public-domain NASA imagery, natural Manim segments for scale/timeline).

Target: ~60 s, 1080p30, Kokoro George narration, cinematic motion, Gemini
review + ≥1 improvement pass.

Stage-by-stage expectations:
- Research: DeepSeek + NASA/Wikipedia/ESA sources; fact-verified.
- Script: hook → journey → golden record → pale blue dot → open conclusion.
- Assets: NASA imagery (Jupiter/Saturn flybys, golden record, family portrait),
  Manim (distance-scale animation, timeline), AI illustration (interstellar
  space concept) if benchmark passes.
- Audio: Kokoro George + ambient bed, ducked.
- Review: Gemini Pro on final MP4 → improvement pass → re-render → final.

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Manim system deps (cairo/pango) | Installed via apt; fallback: ChartProvider + procedural ffmpeg motion |
| NASA rate limits (DEMO_KEY) | Cache-first + Wikimedia fallback |
| AI image provider cost/latency | Benchmark before defaulting; cache every generation |
| Review loop non-termination | Hard caps: ≤3 script passes, ≤3 render iterations |
| LLM provider outage | Role-level fallback (gemini↔deepseek) |
| Fact drift | Every claim tied to research fact id; Fact Reviewer gate |

---

## 11. Definition of Done (v1)

- [x] Architecture doc (this file)
- [ ] Script review module + report on demo script
- [ ] Image-gen abstraction + benchmark output
- [ ] Postmortem module + postmortem for demo
- [ ] Demo documentary rendered (Voyager 1, ~60 s)
- [ ] Gemini Pro review performed (report saved)
- [ ] ≥1 improvement pass applied with measured delta
- [ ] Final video + full run report delivered
