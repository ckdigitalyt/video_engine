# Video Engine — Complete Technical Review

> **Author:** Jade (Automation Ops Engineer)
> **Date:** 2026-07-10
> **Scope:** Full architectural review of the ckdigitalyt YouTube documentary video pipeline
> **Constraint:** Design & critique only — no code changes

---

## Table of Contents

1. [Current Architecture](#1-current-architecture)
2. [Quality Assessment](#2-quality-assessment)
3. [Biggest Weaknesses](#3-biggest-weaknesses-ranked-by-impact)
4. [Comparison Against Professional Channels](#4-comparison-against-professional-channels)
5. [Ideal Architecture (Hardware-Bounded)](#5-ideal-architecture-hardware-bounded)
6. [Improved Pipeline Design](#6-improved-pipeline-design)
7. [Timeline Schema](#7-timeline-schema-recommendation)
8. [AI Review Agents](#8-ai-review-agents)
9. [Auto-Critique & Self-Improvement](#9-auto-critique-and-self-improvement)
10. [Implementation Roadmap](#10-prioritized-implementation-roadmap)

---

## 1. Current Architecture

### 1.1 End-to-End Pipeline

```
  TOPIC STRING
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. PLANNER NODE          (DeepSeek)                             │
│    Phase 1 → Narrative Outline (LLM)                            │
│    Phase 2 → Scene Generation (LLM)                             │
│    Generates VisualIntent per scene                             │
│    Returns list[Scene] with narration + search_plan             │
└─────────────────────────────────────────────────────────────────┘
      │  Plan: list[Scene] (Pydantic models)
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. EXECUTION NODE         (VisualDirector)                      │
│    ├─ ConceptPlanner         → expands queries from intent      │
│    ├─ AssetRouter            → multi-query search (providers)   │
│    ├─ SemanticValidator      → scores relevance                  │
│    ├─ AestheticAgent         → style consistency check           │
│    ├─ QualityGates           → hard gates (semantic, reuse,     │
│    │                            style, diversity)                │
│    ├─ FallbackDirector       → chain: NASA→Wikimedia→reuse→     │
│    │                            animated placeholder→emergency   │
│    ├─ DiversityTracker       → prevents asset similarity         │
│    ├─ StoryboardValidator    → post-hoc validation               │
│    │                                                             │
│    │  BEAT MODE (optional)                                       │
│    ├─ BeatDirector           → splits narration into beats      │
│    │  ├─ BeatPlanner         → sentence/clause splitting        │
│    │  ├─ ShotPlanner         → primary + cutaway + backup       │
│    │  └─ CinematicEditor     → L/J cuts, match cuts, pacing    │
│    │                                                             │
│    ├─ AssetRouter.download() → downloads selected clips         │
│    └─ generate_voice()       → Kokoro TTS                       │
└─────────────────────────────────────────────────────────────────┘
      │  Timeline: timeline.json + subtitle_timeline
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. RENDER NODE            (MoviePyRenderer)                     │
│    ├─ TimelineBuilder        → validates & writes timeline.json │
│    ├─ MotionEngine           → Ken Burns zoom/pan              │
│    ├─ TransitionEngine       → smart transitions (crossfade,    │
│    │                            fade, dissolve)                  │
│    ├─ SubtitleEngine         → pydub silence detection → SRT   │
│    ├─ CompositeVideoClip     → assemble all layers              │
│    └─ write_videofile()      → libx264 + aac                   │
└─────────────────────────────────────────────────────────────────┘
      │  final_output.mp4
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. CRITIC NODE             (Gemini Multimodal)                  │
│    Extracts 1 frame @ 2s → Gemini visual QA → Approve/Reject   │
│    If rejected → loops back to Planner (max 3 iterations)      │
└─────────────────────────────────────────────────────────────────┘
```

**Orchestration:** LangGraph `StateGraph` with 4 nodes connected linearly with a conditional loop from critic → planner (max 3 iterations).

### 1.2 Data Flow

```
Topic (str) 
  → Plan (list[Scene] via model_dump JSON serialization through LangGraph state)
  → Per-scene: VisualIntent → ConceptPlanner queries → AssetRouter.search()
  → AssetPlan (filepath, scores, metadata) attached to Scene
  → AudioPlan (TTS file) attached to Scene
  → Scene JSON re-serialized → TimelineBuilder produces timeline.json
  → Render reads timeline.json, MoviePy composites clips
  → SubtitleEngine reads audio, pydub silence detection → word-timing clips
  → Subtitle clips added to CompositeVideoClip
  → write_videofile() renders final MP4
```

### 1.3 Agent Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Planner  │ ──▶ │Execution │ ──▶ │ Render   │ ──▶ │ Critic   │
│(DeepSeek)│     │(DeepSeek)│     │(CPU only)│     │(Gemini)  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                     │                                │
                     │                          ┌─────┴──────┐
                     │                          │ Approved?  │
                     │                          │ YES → END  │
                     │                          │ NO  ───────┤
                     │                          │ Max iter?  │
                     │                          │ YES → END  │
                     │                          └─────┬──────┘
                     │                                │ NO
                     └────────────────────────────────┘
                          (loop back to Planner)
```

Current LangGraph runs on DeepSeek V4 Flash only. Gemini is used only for the multimodal critic node.

### 1.4 Module Dependencies

```
orchestrator.py (entry point)
  ├─ audio_engine.py
  │    └─ KokoroProvider (TTS)
  │
  ├─ src/renderer/ (Renderer interface)
  │    └─ moviepy_renderer.py (MoviePyRenderer)
  │         ├─ src/effects/motion.py (MotionEngine)
  │         ├─ src/effects/transitions.py (TransitionEngine)
  │         ├─ src/renderer/timeline_builder.py (TimelineBuilder)
  │         └─ src/models/schemas.py (Scene, BeatPlan, ShotPlan, etc.)
  │
  ├─ src/planner/planner.py (StoryPlanner)
  │    └─ src/providers/llm_provider.py (DeepSeekProvider)
  │
  ├─ src/director/director.py (VisualDirector)
  │    ├─ src/assets/asset_router.py (AssetRouter)
  │    │    ├─ src/providers/asset_provider.py (Pexels, Pixabay, NASA, Wikimedia)
  │    │    └─ src/assets/asset_library.py (cache layer)
  │    ├─ src/director/concept_planner.py
  │    ├─ src/director/quality_gate.py (QualityGates)
  │    ├─ src/director/aesthetic_agent.py
  │    ├─ src/director/diversity_tracker.py
  │    ├─ src/director/visual_style.py
  │    ├─ src/director/fallback_director.py
  │    ├─ src/cinematic/director_integration.py (BeatDirector)
  │    │    └─ src/cinematic/beat_planner.py (BeatPlanner, ShotPlanner, TimelineBuilder)
  │    └─ src/validation/semantic_validator.py
  │
  ├─ src/subtitles/engine.py (SubtitleEngine)
  │
  └─ src/providers/llm_provider.py (GeminiProvider — critic only)
```

---

## 2. Quality Assessment

Each scored /10 based on current implementation quality, robustness, and output.

### 2.1 Research Quality — **3/10**

- No research phase exists. The planner generates scripts purely from LLM training data.
- No sources, citations, fact-checking, or up-to-date information gathering.
- The `planner.py` has "Phase 1" (outline) and "Phase 2" (scenes), but these are purely narrative structure prompts, not research.
- No web search, no paper retrieval, no data ingestion.
- **Consequence:** Scripts contain plausible-sounding but potentially inaccurate information. Cannot trust factual claims without manual review.

### 2.2 Script Quality — **5/10**

- Scripts are generated via single-shot DeepSeek prompts — no revision, no structural analysis.
- Narration style is configurable but not optimized for the topic.
- No hook analysis, no retention curve modeling, no audience engagement scoring.
- Dialogue is monologue-only (expected for documentary) but lacks narrative devices: no rhetorical questions, no thought experiments, no analogies.
- **Consequence:** Competent but generic. Reads like a Wikipedia article, not a YouTube script.

### 2.3 Storytelling — **4/10**

- Beat-based editing adds pacing structure, but the emotion assignment is purely heuristic (keyword → emotion map).
- No narrative arc analysis. No tension curve. No climax/complication structuring.
- The outline phase exists but the LLM generates it without any storytelling framework (Hero's Journey, Three-Act, Problem-Solution, etc.).
- Templates exist (`templates.py`) but are simple role lists, not narrative blueprints.
- **Consequence:** Videos are linearly expository, not narratively compelling. No hook-hold-payoff structure.

### 2.4 Visual Planning — **5/10**

- VisualIntent is generated per scene, with conceptual queries and asset type preferences.
- Beat-based planning breaks each scene into semantic beats with shot-level visual plans.
- However, VisualIntent quality depends entirely on the LLM's understanding of visual metaphors.
- The rule-based fallback (concept map) is topic-limited (only "Space" has a full concept map).
- No storyboarding (no shot-by-shot visual sketch, no framing direction).
- **Consequence:** Visual concepts are reasonable but lack cinematographic intentionality.

### 2.5 Scene Generation — **4/10**

- Generated entirely from stock footage providers — no AI image/video generation.
- Asset selection is provider-scored (resolution × duration × HD flag), not actually visually evaluated.
- "Semantic validation" is an LLM call that scores relevance — useful but slow.
- The quality gate system is well-designed (semantic, reuse, style, diversity) but relies on the semantic validator being accurate.
- **Consequence:** Visuals are generic stock footage. Cannot create specific or novel imagery.

### 2.6 Animation — **2/10**

- Ken Burns zoom/pan on static images (FallbackDirector).
- Subtle camera motion on video clips (MotionEngine).
- NO procedural animation, NO motion graphics, NO data visualization.
- NO Manim, NO Blender, NO programmatic 2D/3D animation.
- The `animation_requirements` field in VisualIntent is never fulfilled — it's aspirational metadata.
- Subtitle animation is basic fade-in.
- **Consequence:** Cannot visually explain abstract concepts (physics, math, systems). Entire classes of Kurzgesagt-style content are impossible.

### 2.7 Asset Selection — **5/10**

- Multi-query search is genuinely good — diverse queries, early exit on threshold, provider fallback chain.
- Quality gates (semantic, reuse, style, diversity) are well-architected.
- FallbackDirector has a respectable degradation chain.
- However, all assets come from free stock footage providers (Pexels, Pixabay, NASA, Wikimedia).
- No paid/premium stock. No AI generation. No custom creation.
- Query planning sometimes still generates narration-copied queries (despite sanitization).
- **Consequence:** Visual quality ceiling is "free stock footage." Cannot achieve premium visual identity.

### 2.8 Audio — **6/10**

- Kokoro TTS produces reasonable quality for a local, free TTS engine.
- Ducking logic is functional (reduce music during narration).
- Background music can be mixed per-scene.
- However:
  - No multi-voice narration (single voice throughout).
  - No sound design — no sound effects, no ambient audio.
  - Music selection is hardcoded to one file (`cinematic.mp3`).
  - No audio pacing (fast/slow segments).
  - Ducking is a simple constant -12dB, not dynamic.
- **Consequence:** Listenable but monotonous. No audio depth or texture.

### 2.9 Rendering — **6/10**

- MoviePy is a reasonable choice for compositing — it works.
- Subtitle overlay is functional.
- Transition support (crossfade, fade, dissolve) is present.
- Duration matching between audio and video clips is enforced.
- However:
  - Software rendering only — no GPU acceleration.
  - MoviePy is single-threaded for most operations (Python GIL).
  - ffmpeg is called externally for frame extraction and fallback generation but not for primary rendering.
  - No hardware-accelerated encoding (libx264 software, no h264_vaapi/nvenc).
  - No segment-based parallel rendering.
  - `write_videofile` is very slow (2-5× realtime on ARM).
- **Consequence:** Extremely slow rendering. A 10-minute video may take 30-60 minutes to render.

### 2.10 Performance — **3/10**

- **Rendering is the bottleneck:** Single-threaded MoviePy on 4 ARM cores.
- **LLM calls:** Each video makes 15-25 DeepSeek calls + 1 Gemini call. Each call takes 3-15 seconds.
- **Asset downloading:** Sequential per-shot, no parallel downloads.
- **Audio generation:** Sequential per-scene Kokoro TTS (CPU-bound).
- **No caching reuse:** MemoryManager exists but is only partially wired into the pipeline.
- **Memory pressure:** All clips loaded into RAM simultaneously during compositing. 24 GB will be tight for long videos with many high-res clips.
- **Consequence:** Pipeline throughput is ~1 video per hour for a 10-minute documentary.

### 2.11 Maintainability — **6/10**

- **Strong:** Pydantic models with strict validation. No untyped dicts between components. Clear separation of concerns.
- **Strong:** Config-driven (YAML). Environment variables for secrets.
- **Strong:** Good docstrings and module documentation.
- **Weak:** Some very large files (`planner.py`, `director.py`, `beat_planner.py`) should be split.
- **Weak:** Inconsistent error handling — some places raise, some print and continue.
- **Weak:** No formal API boundaries between pipeline stages (they pass serialized JSON through LangGraph state).
- **Weak:** Test coverage is incomplete — many modules have tests but integration test coverage is thin.
- **Weak:** No CI/CD pipeline (GitHub Actions workflow exists but is minimal).

---

## 3. Biggest Weaknesses (Ranked by Impact)

| Rank | Weakness | Impact | Effort to Fix |
|------|----------|--------|---------------|
| **1** | **No procedural animation / motion graphics** | Cannot explain abstract concepts. Videos are stock footage slideshows. | High |
| **2** | **No research phase** | Scripts may contain factual errors. No authority or credibility. | Medium |
| **3** | **Rendering is painfully slow** | 1 video/hour throughput. Cannot scale. | High |
| **4** | **Music/sound is a single hardcoded track** | Zero audio variety. No emotional pacing. | Low |
| **5** | **Script quality is single-shot LLM** | No revision, no hook analysis, no audience optimization. | Medium |
| **6** | **Stock footage quality ceiling** | Cannot create specific visuals. Videos look generic. | High |
| **7** | **No multi-voice narration** | Monotone delivery for entire video. | Low |
| **8** | **Fact-checking / source attribution** | No citations, no references, no source links. | Low |
| **9** | **Critic only checks one frame** | Misses audio glitches, subtitle errors, pacing issues. | Low |
| **10** | **No thumbnail generation** | Every YouTube video needs a compelling thumbnail. | Low |

---

## 4. Comparison Against Professional Channels

### 4.1 Kurzgesagt (Blue Bird)

| Capability | Kurzgesagt | Our Engine | Gap |
|------------|-----------|------------|-----|
| Custom 2D animation | Manim-style procedural vector animation | None | **Critical** |
| Music composition | Original scores per video | Single track | Significant |
| Voiceover | Professional narrator + multiple voices | Single TTS voice | Significant |
| Visual metaphors | Hand-crafted illustrations | Stock footage | **Critical** |
| Script depth | 6+ months research per video | Single LLM call | **Critical** |
| Fact-checking | Expert review + sources | None | **Critical** |
| Visual identity | Distinctive, recognizable art style | Generic stock | Significant |
| Pacing | Masterful editing | Linear beat splitting | Significant |

**Verdict:** Our engine is not competitive with Kurzgesagt. Their core value — *custom animation explaining abstract concepts* — is entirely missing from our pipeline.

### 4.2 Veritasium

| Capability | Veritasium | Our Engine | Gap |
|------------|-----------|------------|-----|
| Narrative hooks | Compelling personal stories | Generic exposition | Significant |
| On-camera presence | Host appears in video | None (no host) | Architectural |
| Experimental footage | Filmed experiments | None | **Critical** |
| Graphics overlays | Custom motion graphics | None | **Critical** |
| Sound design | Original score + foley | Single music track | Significant |
| Script structure | Mystery → reveal → implication | Linear | Significant |

**Verdict:** Veritasium's on-camera experiments and motion graphics are out of reach for now. But their narrative hook structure is learnable and adaptable.

### 4.3 Astrum

| Capability | Astrum | Our Engine | Gap |
|------------|--------|------------|-----|
| Space visuals | NASA imagery + Space Engine renders | NASA images + stock | Medium |
| 3D space scenes | Space Engine / Universe Sandbox | None | Significant |
| Commentary style | Calm, authoritative narration | TTS (improving) | Medium |
| Script accuracy | Well-researched astronomical content | LLM-generated | Significant |
| Visual consistency | Coherent visual language | Mixed stock sources | Medium |

**Verdict:** Astrum is the closest to what our engine *could* produce for space topics. The gap is narrower but still significant — particularly in custom 3D renders.

### 4.4 Johnny Harris

| Capability | Johnny Harris | Our Engine | Gap |
|------------|-------------|------------|-----|
| Map animations | Custom map animations | None | **Critical** |
| Visual essay style | B-roll + graphics + maps | Stock footage only | Significant |
| Personal narration | Host's distinctive voice | TTS | Architectural |
| Tight editing | Fast-paced, rhythm-driven | Beat-based (good start) | Medium |
| Music scoring | Original tracks | Hardcoded | Significant |

**Verdict:** Johnny Harris's signature map-based visual style is entirely absent. However, the beat-based editing is a good foundation for the fast-paced editing style.

### 4.5 Feature Gap Summary

| Missing Capability | Channels That Have It | Priority |
|-------------------|---------------------|----------|
| Procedural 2D/3D animation | Kurzgesagt, Astrum, Veritasium | 🔴 Critical |
| Fact-checking / research | All professional channels | 🔴 Critical |
| Custom audio composition | Kurzgesagt, Johnny Harris | 🟡 High |
| Motion graphics overlays | Veritasium, Johnny Harris | 🟡 High |
| Map/data animation | Johnny Harris | 🟡 High |
| On-camera presence | Veritasium, Johnny Harris | 🔵 Architectural |
| Visual identity (brand) | Kurzgesagt, Johnny Harris | 🟡 High |
| Multi-voice narration | Most doc channels | 🟢 Medium |
| Sound design / foley | Veritasium, Kurzgesagt | 🟢 Medium |
| Thumbnail generation | All | 🟢 Medium |

---

## 5. Ideal Architecture (Hardware-Bounded)

### Constraints

- **CPU:** 4 ARM cores (Oracle Cloud Ampere)
- **RAM:** 24 GB
- **LLM:** DeepSeek V4 Flash (via API)
- **Storage:** Probably ~100-200 GB boot volume
- **No GPU** — no CUDA, no ROCm, no accelerated rendering or inference
- **Open-source only** — no paid APIs beyond LLM

### Design Principles

1. **Parallelize everything** — 4 cores must be fully utilized
2. **Disk streaming over RAM** — don't load all clips at once
3. **Degrade gracefully** — never produce black frames or blank video
4. **Incremental quality** — improve one dimension per iteration
5. **Cache aggressively** — avoid redundant LLM calls and downloads

### Proposed Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR LAYER                         │
│  OpenClaw scheduling + pipeline state machine                   │
│  Node: Python subprocess (isolated, restartable)               │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RESEARCH & PLANNING LAYER                    │
│                                                                 │
│  ResearchAgent     ─── Web search + source extraction           │
│  ScriptWriter      ─── Narrative construction + hook design     │
│  FactChecker       ─── Cross-reference + source validation      │
│  StoryboardPlanner ─── Shot-by-shot visual plan                 │
│  (All use DeepSeek V4 Flash)                                   │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ASSET LAYER                                │
│                                                                 │
│  AssetPlanner      ─── What visuals are needed per shot        │
│  StockRouter       ─── Multi-provider stock footage search     │
│  ImageGenerator    ─── Stable Diffusion (CPU-only, slow)       │
│  AnimationEngine   ─── Programmatic 2D animation (Manim)       │
│  MapGenerator      ─── Map animations (folium + ffmpeg)        │
│  AudioComposer     ─── Music + sound effects per segment       │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      COMPOSITION LAYER                          │
│                                                                 │
│  TimelineAssembler ─── Merges all assets into segment clips    │
│  PreRenderer       ─── Renders segments in parallel (ffmpeg)   │
│  AudioMixer        ─── Multi-track audio (voice + music + SFX) │
│  SubtitleRenderer  ─── Word-level animated subtitles           │
│  SegmentRenderPool ─── 4 parallel ffmpeg processes             │
│  FinalConcatenator ─── ffmpeg concat of rendered segments      │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      REVIEW & POLISH LAYER                      │
│                                                                 │
│  VisualCritic      ─── Multi-frame visual QA                   │
│  AudioCritic       ─── Audio quality + sync check              │
│  PacingCritic      ─── Retention curve analysis                │
│  ThumbnailGen      ─── Automatic thumbnail creation            │
│  MetadataWriter    ─── Description, tags, timestamps           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Improved Pipeline Design

### Stage 1: Topic Selection & Research

**Input:** Topic keyword + optional brief

**Sub-stages:**
1. **ResearchAgent** (DeepSeek V4 Flash):
   - Web search the topic (via `web_search` / `web_fetch`)
   - Extract key facts, statistics, timelines, controversies
   - Identify 5-10 authoritative sources
   - Generate a "research document" with structured facts
2. **AngleSelector** (DeepSeek V4 Flash):
   - Analyze research doc for compelling narratives
   - Propose 3 possible angles (e.g., "mystery", "explanation", "debate")
   - Select best angle based on YouTube engagement criteria
3. **OutlineGenerator**:
   - Produce narrative structure with hooks, rising action, climax, conclusion
   - Assign estimated timestamps to each segment

### Stage 2: Script Writing

**Input:** Research document + narrative outline

**Sub-stages:**
1. **ScriptWriter** (DeepSeek V4 Flash):
   - Write full script section by section
   - Include hook (first 30s), clear explanations, analogies, conclusion
   - Target specific word counts per section
2. **SelfCritic** (DeepSeek V4 Flash):
   - Review script for clarity, accuracy, pacing
   - Flag unfounded claims, confusing passages, weak hooks
3. **ScriptRevision**:
   - Revise based on SelfCritic feedback
   - Repeat until score threshold met (max 3 iterations)
4. **FactChecker** (DeepSeek + web sources):
   - Validate each factual claim against research sources
   - Flag unverifiable claims for removal or caveating

### Stage 3: Visual Planning

**Input:** Script + research doc

**Sub-stages:**
1. **ShotBreakdown**:
   - Parse script into 5-15 second segments
   - For each segment: identify what visual is needed
   - Classify visual type: `stock_video`, `chart`, `diagram`, `map`, `infographic`, `animated_explanation`, `text_overlay`
2. **StoryboardAssetPlan**:
   - For `stock_video`: generate diverse search queries
   - For `chart`/`diagram`: specify data and visualization type
   - For `map`: specify location data and animation style
   - For `animated_explanation`: specify concept and animation approach
   - For `text_overlay`: specify text and style
3. **AssetClassification**:
   - Rank each visual need by how well stock footage can fulfill it
   - If stock won't work: route to animation or AI generation

### Stage 4: Asset Generation

**Parallel execution across 4 cores:**

1. **StockFootageSearch** (parallel):
   - Route queries through priority provider chains
   - Quality gates: semantic relevance >= 0.75, no recent reuse
2. **ProgrammaticAnimation** (CPU-bound, queue-based):
   - **Manim** (Manim Community) for physics/math abstractions
   - Use `manimgl` or `manimce` with pre-built templates
   - Templates: timeline charts, comparisons, particle systems, zoom-in diagrams
   - Each animation renders as a short MP4 segment
3. **DataVisualization**:
   - matplotlib → ffmpeg for animated charts
   - folium → ffmpeg for map animations
4. **ImageGeneration** (optional, low priority):
   - Stable Diffusion (CPU onnxruntime) for custom imagery
   - Only for specific scenes where stock fails and animation is inappropriate
   - Very slow (2-5 min per image on ARM), use sparingly

### Stage 5: Audio Production

1. **TTS Generation** (Kokoro, parallel per scene):
   - Generate narration audio
   - Voice selection per segment (primary narrator vs. quoted speaker)
2. **BackgroundMusicSelection**:
   - Categorize scenes by emotion (wonder, tension, triumph, calm)
   - Select from a growing library of CC-licensed music
   - Change music track per scene based on emotional arc
3. **SoundEffects**:
   - Curated library of CC sound effects
   - Auto-trigger based on shot type: transitions, emphasis, atmosphere
4. **AudioMixing**:
   - Multi-track: voice (center, -3dB), music (stereo, variable ducking), SFX (per scene)
   - Dynamic ducking: music volume varies with narration density
   - Crossfades between music tracks at scene boundaries

### Stage 6: Segment Rendering (Parallel)

**Key insight:** Render segments independently, then concatenate. This is the single biggest performance improvement available.

1. **SegmentAssembly**:
   - Group shots by scene (or scene group)
   - Each segment = 30-90 seconds of final video
   - Each segment gets its own ffmpeg command with all overlays
2. **ParallelRenderPool** (4 processes):
   - ffmpeg with `-preset ultrafast -crf 23` for draft, `slow -crf 18` for final
   - Each process renders one segment at a time
   - Pipeline saturation: ~4× speedup over sequential

### Stage 7: Final Concatenation & Polish

1. **ffmpeg concat demuxer**:
   - Concatenate rendered segments losslessly
   - Add a single global audio normalization pass
2. **SubtitleBurnIn** (optional):
   - Burn subtitles into final video
   - Or output separate SRT/WebVTT for YouTube upload
3. **ThumbnailGeneration**:
   - Extract best frame from video
   - Overlay title text with imagemagick
   - Export 1280×720 thumbnail

### Stage 8: Review & Release

1. **MultiFrameVisualCritic**:
   - Extract frames at 10%, 50%, 90% positions
   - Gemini multimodal review for visual issues (black frames, letterboxing, quality)
2. **AudioCritic**:
   - Check for clipping, silence gaps, volume consistency
3. **PacingCritic**:
   - Analyze retention curve based on shot length diversity
4. **MetadataGeneration**:
   - Generate YouTube title, description, tags, timestamps
5. **Upload** (future):
   - YouTube Data API v3 upload with metadata

### Pipeline Flow Diagram

```
TOPIC
  │
  ▼
┌────────────────  RESEARCH  ────────────────┐
│  web_search() → ResearchAgent → Sources Doc│
└────────────────────────────────────────────┘
  │
  ▼
┌────────────────  SCRIPT  ──────────────────┐
│  ScriptWriter → SelfCritic → Revision →    │
│  FactChecker → Approved Script             │
└────────────────────────────────────────────┘
  │
  ▼
┌────────────────  VISUAL PLAN  ─────────────┐
│  ShotBreakdown → StoryboardAssetPlan       │
│  AssetClassification → Per-shot plan       │
└────────────────────────────────────────────┘
  │
  ▼
┌────────────────  ASSET GEN  ───────────────┐
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ Stock    │ │ Manim    │ │ Data Viz   │ │
│  │ (fast)   │ │ (medium) │ │ (fast)     │ │
│  └──────────┘ └──────────┘ └────────────┘ │
│  ──── Parallel across 4 cores ──────────  │
└────────────────────────────────────────────┘
  │
  ▼
┌────────────────  AUDIO  ───────────────────┐
│  TTS (parallel) → Music Select → SFX →    │
│  Multi-track mix per segment              │
└────────────────────────────────────────────┘
  │
  ▼
┌──────────  SEGMENT RENDER (×4)  ──────────┐
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐│
│  │Seg 1   │ │Seg 2   │ │Seg 3   │ │Seg 4 ││
│  │ffmpeg  │ │ffmpeg  │ │ffmpeg  │ │ffmpeg││
│  └────────┘ └────────┘ └────────┘ └──────┘│
│  ──── Parallel across 4 ARM cores ─────  │
└────────────────────────────────────────────┘
  │
  ▼
┌──────────  CONCATENATION  ─────────────────┐
│  ffmpeg concat → final MP4                 │
└────────────────────────────────────────────┘
  │
  ▼
┌──────────  REVIEW  ────────────────────────┐
│  VisualCritic + AudioCritic + PacingCritic │
│  ThumbnailGen + MetadataGen                │
└────────────────────────────────────────────┘
  │
  ▼
  FINAL_VIDEO.mp4
```

---

## 7. Timeline Schema Recommendation

The current `timeline.json` is flat: `{render_settings, audio_timeline[], video_timeline[]}`. The beat-based data lives in Scene objects but is partially flattened into timeline. This needs to be a rich, multi-track timeline.

### Proposed `timeline_v2.json` Schema

```json
{
  "$schema": "timeline_v2.schema.json",
  "version": "2.0",
  "meta": {
    "topic": "The Fermi Paradox",
    "video_id": "fp-20260710",
    "created_at": "2026-07-10T19:00:00Z",
    "pipeline_version": "2.0",
    "total_duration": 480.0,
    "render_duration_ms": 254000
  },

  "render": {
    "resolution": [1920, 1080],
    "fps": 30,
    "pixel_format": "yuv420p",
    "codec": "libx264",
    "crf": 18,
    "preset": "slow",
    "audio_codec": "aac",
    "audio_bitrate": "192k"
  },

  "narration": {
    "segments": [
      {
        "id": "nar-001",
        "scene_id": 0,
        "text": "The Fermi Paradox is one of the most profound questions in science.",
        "start_ms": 0,
        "end_ms": 8000,
        "voice": "default",
        "speed": 1.0,
        "pitch": 1.0,
        "emphasis": ["Fermi Paradox", "profound questions"]
      }
    ]
  },

  "visuals": {
    "shots": [
      {
        "id": "shot-001",
        "scene_id": 0,
        "beat_index": 0,
        "shot_index": 0,
        "type": "stock_video",
        "start_ms": 0,
        "end_ms": 5000,
        "source": {
          "provider": "pexels",
          "url": "https://...",
          "filepath": "cache/video/scene_0.mp4",
          "original_duration": 15.0
        },
        "crop": {"x": 0, "y": 0, "w": 1920, "h": 1080},
        "motion": {
          "type": "ken_burns_in",
          "zoom_start": 1.0,
          "zoom_end": 1.08,
          "pan_x": 0,
          "pan_y": 0
        },
        "color_grade": {
          "saturation": 1.1,
          "contrast": 1.05,
          "brightness": 0.0,
          "temperature": 5600
        },
        "overlays": ["overlay-001"]
      }
    ]
  },

  "animations": [
    {
      "id": "anim-001",
      "scene_id": 2,
      "type": "diagram_explainer",
      "engine": "manim",
      "start_ms": 45000,
      "end_ms": 55000,
      "params": {
        "template": "comparison_bars",
        "data": {
          "labels": ["Earth", "Proxima b", "TRAPPIST-1e"],
          "values": [1.0, 1.3, 0.8]
        },
        "colors": ["#00BFFF", "#FF6B35", "#7B68EE"],
        "title": "Relative sizes of potentially habitable worlds"
      },
      "render_path": "cache/animation/anim_001.mp4"
    }
  ],

  "subtitles": [
    {
      "id": "sub-001",
      "start_ms": 500,
      "end_ms": 3500,
      "text": "The Fermi Paradox is one of the most profound questions",
      "words": [
        {"text": "The", "start_ms": 500, "end_ms": 700},
        {"text": "Fermi", "start_ms": 700, "end_ms": 1200},
        {"text": "Paradox", "start_ms": 1200, "end_ms": 1800},
        {"text": "is", "start_ms": 1800, "end_ms": 2000}
      ],
      "style": {
        "font": "Arial",
        "font_size": 36,
        "color": "#FFFFFF",
        "outline": "#000000",
        "outline_width": 2,
        "position": "bottom_center",
        "animation_in": "fade",
        "animation_out": "fade"
      }
    }
  ],

  "transitions": [
    {
      "from_shot": "shot-001",
      "to_shot": "shot-002",
      "type": "crossfade",
      "duration_ms": 500,
      "easing": "ease_in_out"
    },
    {
      "from_scene": 1,
      "to_scene": 2,
      "type": "dip_to_black",
      "duration_ms": 800
    }
  ],

  "sound_effects": [
    {
      "id": "sfx-001",
      "filepath": "assets/sfx/whoosh_01.wav",
      "start_ms": 5000,
      "duration_ms": 800,
      "volume_db": -6,
      "pan": 0,
      "trigger_event": "transition"
    }
  ],

  "music": [
    {
      "id": "music-seg-001",
      "filepath": "assets/music/wonder_ambient.wav",
      "start_ms": 0,
      "end_ms": 90000,
      "volume_db": -18,
      "ducking": {
        "enabled": true,
        "reduction_db": 10,
        "attack_ms": 200,
        "release_ms": 500
      },
      "fade_in_ms": 3000,
      "fade_out_ms": 3000
    }
  ]
}
```

### Key improvements over current timeline.json:

1. **Separate tracks for narration, visuals, animations, subtitles, transitions, SFX, music** — not a flat video_timeline.
2. **Word-level subtitle timing** — not just line-level. Enables karaoke-style highlighting.
3. **Per-shot metadata** — crop, motion, color grade, overlays. Currently these are auto-generated by MotionEngine; they should be prescriptive in the timeline.
4. **Animation tracks** — Manim renders as first-class timeline elements.
5. **Multi-track music** — different tracks per emotional segment.
6. **Sound effects** — triggerable by events (transitions, emphasis points).
7. **Transition schema** — explicit transitions between both shots and scenes.
8. **Render metadata** — codec, CRF, preset specified in timeline (allows per-segment override).

---

## 8. AI Review Agents

### Recommended Review Insertion Points

```
 RESEARCH PHASE:
   ╰─ ResearchQualityCheck (DeepSeek)
       After ResearchAgent: verify source count, diversity, recency

 SCRIPT PHASE:
   ╰─ ScriptHookReview (DeepSeek)
       After first draft: evaluate opening 30 seconds for engagement
   ╰─ ScriptClarityCheck (DeepSeek)
       After revision: flag confusing or ambiguous sentences
   ╰─ FactualAccuracyCheck (DeepSeek + web)
       Validate each factual claim before proceeding

 VISUAL PLAN PHASE:
   ╰─ VisualFeasibilityCheck (DeepSeek)
       Are the planned visuals achievable with available resources?
       Reclassify impossible plans to alternatives

 ASSET SELECTION PHASE:
   ╰─ AssetQualityCheck (Gemini multimodal)
       For each selected asset: is it high quality? No watermarks?
       No compression artifacts? Good composition?
   ╰─ SemanticRelevanceCheck (DeepSeek)
       Does the selected asset actually match the narration meaning?

 AUDIO PHASE:
   ╰─ TTSQualityCheck (DeepSeek)
       Listen to pronunciation of technical terms. Flag mispronunciations.
   ╰─ MusicMatchCheck (DeepSeek)
       Does the selected music match the scene's emotional tone?

 PRE-RENDER:
   ╰─ StoryboardValidation (rule-based) ← Already exists!
       Pre-flight check for missing assets, duration mismatches
   ╰─ TimelineIntegrityCheck (rule-based)
       Validate all file paths, no gaps/overlaps in timeline

 POST-RENDER:
   ╰─ MultiFrameVisualCritic (Gemini multimodal) ← Upgrade!
       Check 5+ frames at key positions, not just one
   ╰─ AudioMixingCheck (rule-based + DeepSeek)
       Check volume levels, clipping, silence gaps
   ╰─ SubtitleSyncCheck (rule-based)
       Do subtitle timings match actual speech timing?
   ╰─ PacingRetentionCheck (DeepSeek)
       Analyze shot length distribution. Predict retention.
   ╰─ ThumbnailAppealCheck (Gemini multimodal)
       Evaluate thumbnail for viewer appeal
```

### Review Agent Architecture

Each review agent follows a standard interface:

```python
class ReviewAgent(ABC):
    @abstractmethod
    def review(self, artifact: Any, context: dict) -> ReviewResult:
        """Returns ReviewResult with pass/fail, score, issues[]."""
        pass

    @abstractmethod
    def can_autofix(self, artifact: Any, issues: list[Issue]) -> bool:
        """Can this agent fix issues itself vs. requiring human review?"""
        pass

    @abstractmethod
    def autofix(self, artifact: Any, issues: list[Issue]) -> Any:
        """Attempt to fix fixable issues."""
        pass
```

**ReviewResult schema:**

```json
{
  "agent": "ScriptClarityCheck",
  "artifact_id": "script-draft-2",
  "passed": false,
  "score": 0.72,
  "threshold": 0.80,
  "issues": [
    {
      "severity": "major",
      "category": "clarity",
      "description": "Sentence 'The Great Filter could be anywhere' is ambiguous",
      "location": {"paragraph": 3, "sentence": 2},
      "suggestion": "Rephrase to: 'The Great Filter hypothesis suggests that somewhere between simple life and advanced civilization, a near-impossible barrier exists.'"
    }
  ],
  "can_autofix": true,
  "autofix_applied": true
}
```

---

## 9. Auto-Critique and Self-Improvement

### Current System

The critic node extracts a single frame at 2 seconds, sends it to Gemini, and asks YES/NO. This is woefully insufficient.

### Proposed Multi-Layer Critique System

#### Layer 1: Component-Level (Runs After Each Stage)

| Review | Timing | Tool | What It Checks |
|--------|--------|------|----------------|
| ResearchCompleteness | After research | DeepSeek | Are there enough sources? Are they diverse? |
| ScriptClarity | After script | DeepSeek | Clear sentences? Good hook? Strong conclusion? |
| FactualAccuracy | After script | DeepSeek + web | Cross-reference claims against sources |
| PlanRelevance | After visual plan | DeepSeek | Will the visual plan adequately support the narration? |
| AssetQuality | After asset selection | Gemini multimodal | Resolution, artifacts, watermark, composition |
| AudioQuality | After TTS | DeepSeek | Pronunciation, naturalness, pacing |

#### Layer 2: Pre-Render Validation (Rule-Based)

- Asset file existence check
- Duration mismatch detection (audio vs. video)
- Missing music/SFX detection
- Subtitle timing sanity check
- Transition sequence integrity check

#### Layer 3: Post-Render Critique

**Multi-frame visual QA (upgrade from current):**
- Extract 10 frames at regular intervals
- Gemini multimodal review each frame
- Report: % of frames with black borders, blur, compression artifacts, watermarks
- Pass threshold: >= 90% of frames pass

**Audio analysis (rule-based):**
- Loudness: Integrated LUFS between -14 and -18 (YouTube standard)
- True peak: no sample exceeds -1 dBTP
- Dynamic range: appropriate for content type
- Silence detection: no gaps > 2 seconds in narration

**Pacing analysis (DeepSeek):**
- Shot length histogram
- Scene transition density
- Predict viewer retention curve using heuristic model

**Subtitle sync check:**
- Do subtitle start/end times match the end of actual speech?
- Maximum allowed drift: 200ms

#### Layer 4: Automated Improvement Loop

```
  Post-render critique
      │
      ▼
  ┌─────────────────────────────────────────────────┐
  │  Can the issue be auto-fixed?                   │
  │                                                  │
  │  YES ──────────────────────────────────────────┐ │
  │  ├─ Black frame → re-render segment with       │ │
  │  │   ffmpeg replace filter → run concat again  │ │
  │  ├─ Audio too quiet → normalize → remux        │ │
  │  ├─ Subtitles misaligned → adjust timing →     │ │
  │  │   re-burn subtitles                          │ │
  │  ├─ Bad asset → replace with fallback →         │ │
  │  │   re-render segment                           │ │
  │  └─ Loop max 2 iterations                       │ │
  │                                                  │
  │  NO ───────────────────────────────────────────┐ │
  │  ├─ Script is confusing → re-plan with revised │ │
  │  │   narration (full pipeline re-run)          │ │
  │  ├─ Research is weak → re-research with        │ │
  │  │   different search queries                   │ │
  │  └─ Mark as "needs human review" + export      │ │
  │     diagnostic report                           │ │
  └─────────────────────────────────────────────────┘
```

#### Layer 5: Cross-Video Learning (Memory)

**What to store per video:**
- Research sources used (prevent repeated failed searches)
- Which providers succeeded for which topics
- Asset quality scores (build a quality model)
- Rejected assets (avoid re-selecting)
- Script structures that score well on retention
- Audio settings that worked well

**Feedback to pipeline:**
- Topic classification quality → adjust TopicClassifier
- Provider routing success rates → adjust route priorities
- Script template effectiveness → weight templates by performance
- Beat planning parameters → adjust duration defaults

---

## 10. Prioritized Implementation Roadmap

### 10.1 High Impact / Low Effort

| # | Improvement | Effort | Impact | Dependencies |
|---|------------|--------|--------|--------------|
| 1 | **Multi-frame visual critic** — check 5+ frames instead of 1 | 1-2 hours | High | None |
| 2 | **Music library** — curate CC music per emotion (wonder, tension, triumph, calm) | 3-4 hours | High | None |
| 3 | **Per-scene music selection** — pick music track based on scene emotion | 4-6 hours | High | Music library (#2) |
| 4 | **Sound effects on transitions** — add whoosh/drone on scene boundaries | 2-3 hours | Medium | None |
| 5 | **Thumbnail generation** — extract best frame + imagemagick title overlay | 3-4 hours | Medium | None |
| 6 | **YouTube metadata generation** — title, description, tags, timestamps | 2-3 hours | Medium | None |
| 7 | **Source attribution in description** — collect provider URLs | 1-2 hours | Low | None |
| 8 | **Script hook scoring** — LLM evaluates first 30s engagement | 2-3 hours | High | None |
| 9 | **Multi-voice TTS** — use different voices for narration vs. quotes | 4-5 hours | Medium | Kokoro multi-voice support |

**Total effort: ~22-28 hours | Cumulative impact: Significant**

### 10.2 High Impact / Medium Effort

| # | Improvement | Effort | Impact | Dependencies |
|---|------------|--------|--------|--------------|
| 10 | **Research phase** — web_search + fact extraction + source tracking | 2-3 days | Critical | None |
| 11 | **Script self-revision loop** — write, critique, rewrite (3 iterations max) | 1-2 days | High | Research phase |
| 12 | **Fact-checking agent** — cross-reference claims against sources | 2-3 days | Critical | Research phase (#10) |
| 13 | **Segment-based parallel rendering** — split video into 30-90s segments, render in parallel with ffmpeg | 3-4 days | Critical | None |
| 14 | **Audio ducking improvements** — dynamic ducking based on speech density | 1-2 days | Medium | None |
| 15 | **Asset quality gate with Gemini** — Gemini multimodal check per selected asset | 2-3 days | High | None |
| 16 | **Subtitle karaoke highlighting** — word-level highlight in subtitle animation | 2-3 days | Medium | None |
| 17 | **Pacing critic** — analyze shot length distribution, flag monotony | 1-2 days | Medium | None |
| 18 | **Video-level memory** — store per-video results, provider success rates, asset quality | 2-3 days | High | MemoryManager (exists) |

**Total effort: ~14-23 days | Cumulative impact: Transformational**

### 10.3 High Impact / High Effort

| # | Improvement | Effort | Impact | Dependencies |
|---|------------|--------|--------|--------------|
| 19 | **Manim integration** — programmatic 2D animation for abstract concepts | 1-2 months | **Critical** | None (Manim is standalone) |
| 20 | **Motion graphics engine** — animated text, overlays, callouts, graphs | 2-4 weeks | High | Manim integration (#19) |
| 21 | **Data visualization engine** — animated charts, timelines, maps | 2-4 weeks | High | None |
| 22 | **AI image generation** — Stable Diffusion (CPU) for custom imagery | 2-4 weeks | High | None |
| 23 | **Segment-based pre-render with color grading** — per-segment color correction | 1-2 weeks | Medium | Segment rendering (#13) |
| 24 | **Automated retention optimization** — A/B test script structures, measure outcomes | 1-2 months | High | Video release pipeline |
| 25 | **YouTube upload automation** — Data API v3 upload with metadata, thumbnail | 2-3 weeks | High | None |
| 26 | **Full Manim template library** — 20+ reusable animation templates | 1-2 months | **Critical** | Manim integration (#19) |

**Total effort: ~6-8 months | Cumulative impact: Professional-grade capability**

### Roadmap Visualization

```
WEEK 1-2     │░░░░░░░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│
High impact / low effort (items 1-9)

WEEK 3-6     │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░│
High impact / medium effort (items 10-18)

WEEK 7-16    │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
High impact / high effort (items 19-26)

Continued    │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
Maintenance + template building + refinement
```

---

## Key Takeaways for the Engineering Team

1. **You have a solid foundation.** The Pydantic model design, quality gates, beat-based editing, and fallback director are genuinely well-engineered.

2. **Your biggest gap is animation.** Without procedural animation (Manim, motion graphics), you cannot compete with Kurzgesagt or explain abstract concepts. This is a 1-2 month project.

3. **Your biggest bottleneck is rendering.** Segment-based parallel rendering with ffmpeg is the single highest-ROI engineering investment. 3-4 days for 4× speedup.

4. **Your biggest quality gap is research.** Adding a web research phase + fact-checking loop is 2-3 days and dramatically improves credibility.

5. **Small wins matter.** Music variety, multi-frame critic, thumbnail generation, and sound effects are each one afternoon of work and each measurably improve the final product.

6. **Don't chase on-camera presence.** On-camera video is an architectural decision that doesn't fit your current pipeline. Focus on what you *can* do well: narration-driven documentary with rich visuals.

7. **Your hardware limits are real but manageable.** 4 cores / 24 GB means sequential MoviePy compositing is the wrong approach. Parallel ffmpeg-based segment rendering is the correct path forward.
