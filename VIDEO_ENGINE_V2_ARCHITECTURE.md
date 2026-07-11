# Video Engine V2 — Complete Architecture

> **Author:** Jade
> **Date:** 2026-07-10
> **Scope:** Intelligence-first pipeline architecture for autonomous YouTube documentary production
> **Target:** Oracle Cloud ARM (4 CPU, 24 GB RAM), DeepSeek V4 Flash, OpenClaw, open-source only
> **Status:** Design document — no code changes

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [System Overview](#2-system-overview)
3. [Pipeline Stage 1: Research Intelligence](#3-pipeline-stage-1-research-intelligence)
4. [Pipeline Stage 2: Knowledge Graph](#4-pipeline-stage-2-knowledge-graph)
5. [Pipeline Stage 3: Story Planning](#5-pipeline-stage-3-story-planning)
6. [Pipeline Stage 4: Scene Planning](#6-pipeline-stage-4-scene-planning)
7. [Pipeline Stage 5: Visual Planning & timeline_v2.json](#7-pipeline-stage-5-visual-planning)
8. [timeline_v2.json — Full Schema](#8-timeline_v2json-full-schema)
9. [Pipeline Stage 6: Asset Acquisition](#9-pipeline-stage-6-asset-acquisition)
10. [Pipeline Stage 7: Animation Planning & Rendering](#10-pipeline-stage-7-animation-planning)
11. [Pipeline Stage 8: Rendering Engine](#11-pipeline-stage-8-rendering-engine)
12. [Pipeline Stage 9: Multi-Stage Video Critic](#12-pipeline-stage-9-multi-stage-video-critic)
13. [Pipeline Stage 10: Self-Improvement Loop](#13-pipeline-stage-10-self-improvement-loop)
14. [Hardware Optimization Guide](#14-hardware-optimization-guide)
15. [Implementation Roadmap](#15-implementation-roadmap)

---

## 1. Design Philosophy

### Intelligence-First ≠ Script-First

The current V1 pipeline is **script-first**: the LLM writes a narration script, then we hunt for visuals to match. This is backward.

V2 is **intelligence-first**: we research and understand the topic first, build a knowledge graph of facts and relationships, then design a narrative that communicates that knowledge most effectively, and *finally* plan the visuals to serve the narrative.

### Core Principles

| Principle | Rationale |
|-----------|-----------|
| **Research before writing** | Facts constrain the narrative, not the other way around |
| **Knowledge drives visuals** | The visual plan is derived from what needs to be explained |
| **Parallelize everything** | 4 ARM cores should never be idle — render segments in parallel |
| **Cache aggressively** | Reuse research, scripts, assets, and animations across videos |
| **Fail gracefully** | Every stage has a degradation path — never produce blank video |
| **Self-improving** | Every video's review scores improve the next one |
| **Offline-first** | Only LLM calls hit the network; everything else runs local |

### Architecture Overview

```
                        INTELLIGENCE LAYER
  ┌─────────────────────────────────────────────────────────────┐
  │  ResearchAgent → FactVerifier → KnowledgeGraph             │
  │  (DeepSeek + web) (DeepSeek cross-ref) (local SQLite)      │
  └─────────────────────────────────────────────────────────────┘
                            │
                          story_context
                            ▼
                       NARRATIVE LAYER
  ┌─────────────────────────────────────────────────────────────┐
  │  StoryPlanner → ScenePlanner → VisualPlanner               │
  │  (DeepSeek)      (DeepSeek)      (DeepSeek + rules)        │
  └─────────────────────────────────────────────────────────────┘
                            │
                     timeline_v2.json
                            ▼
                      PRODUCTION LAYER
  ┌─────────────────────────────────────────────────────────────┐
  │  AssetAcquisition → AnimationEngine → SegmentRenderer      │
  │  (parallel HTTP)    (Manim pool)     (4× parallel ffmpeg)  │
  └─────────────────────────────────────────────────────────────┘
                            │
                       rendered_segments/
                            ▼
                      POLISH LAYER
  ┌─────────────────────────────────────────────────────────────┐
  │  Concat → AudioMix → Subtitles → MultiCritic → Improve     │
  └─────────────────────────────────────────────────────────────┘
                            │
                     FINAL_VIDEO.mp4
```

---

## 2. System Overview

### 2.1 Data Flow (End to End)

```
topic_string
  │
  ▼
[ResearchAgent]
  │ research_document (dict: sources[], facts[], timelines[], controversies[])
  ▼
[FactVerifier]
  │ verified_facts (list[Fact], each with source citations)
  ▼
[KnowledgeGraph]
  │ knowledge_graph (JSON: nodes=concepts, edges=relationships)
  │ story_context (narrative-ready excerpt of KG)
  ▼
[StoryPlanner]
  │ narrative_arc (list[NarrativeBeat] with purpose, hook, tension, release)
  ▼
[ScenePlanner]
  │ scenes (list[SceneV2] with narration, duration, emotion, transition)
  ▼
[VisualPlanner]
  │ visual_plan (shot-by-shot: type, query, animation params, duration)
  │ timeline_v2.json (complete multi-track production spec)
  ▼
[AssetAcquisition] ──parallel──▶ [AnimationEngine] ──parallel──▶ [SegmentRenderer]
  │ downloaded/rendered clips
  ▼
[MultiCritic ── feedback loop ──▶ re-render if needed]
  │
  ▼
[Concat + AudioMix + SubtitleBurn] → FINAL_VIDEO.mp4
```

### 2.2 Module Architecture (Python Package Layout)

```
video_engine/
├── __init__.py
├── run_pipeline.py              # Entry point (OpenClaw orchestrator)
├── configs/
│   ├── pipeline.yaml            # Top-level pipeline config
│   ├── models.yaml              # LLM model definitions
│   ├── providers.yaml           # Asset provider config
│   ├── render.yaml              # Render settings (codec, preset, etc.)
│   ├── research.yaml            # Research agent settings
│   ├── animation.yaml           # Manim/animation settings
│   └── critic.yaml              # Critic thresholds and settings
│
├── src/
│   ├── models/                  # ===== DATA MODELS =====
│   │   ├── __init__.py
│   │   ├── v2_types.py          # ALL V2 Pydantic models (see §2.3)
│   │   └── enums.py             # Shared enums (ShotType, Emotion, TransitionType, etc.)
│   │
│   ├── research/                # ===== STAGE 1-2: INTELLIGENCE =====
│   │   ├── __init__.py
│   │   ├── research_agent.py    # ResearchAgent — web search + extraction
│   │   ├── fact_verifier.py     # FactVerifier — cross-reference + source tracking
│   │   └── knowledge_graph.py   # KnowledgeGraph — concept network builder
│   │
│   ├── planner/                 # ===== STAGE 3-5: NARRATIVE =====
│   │   ├── __init__.py
│   │   ├── story_planner.py     # StoryPlanner — narrative arc from KG
│   │   ├── scene_planner.py     # ScenePlanner — scene breakdown
│   │   └── visual_planner.py    # VisualPlanner — shot-by-shot visual plan + timeline_v2
│   │
│   ├── assets/                  # ===== STAGE 6: ASSET ACQUISITION =====
│   │   ├── __init__.py
│   │   ├── orchestrator.py      # AssetOrchestrator — coordinates asset pipeline
│   │   ├── stock_search.py      # StockSearcher — multi-provider search
│   │   ├── image_provider.py    # ImageProvider — still image -> Ken Burns video
│   │   ├── cache_manager.py     # AssetCache — SQLite + disk cache
│   │   └── providers/           # Provider adapters (port from V1)
│   │       ├── pexels.py
│   │       ├── pixabay.py
│   │       ├── nasa.py
│   │       └── wikimedia.py
│   │
│   ├── animation/               # ===== STAGE 7: ANIMATION =====
│   │   ├── __init__.py
│   │   ├── manim_runner.py      # ManimRunner — wraps manim CLI calls
│   │   ├── template_library.py  # TemplateLibrary — registered animation templates
│   │   ├── manim_templates/     # Manim .py scene templates
│   │   │   ├── comparison_bars.py
│   │   │   ├── timeline_chart.py
│   │   │   ├── zoom_diagram.py
│   │   │   ├── particle_system.py
│   │   │   ├── text_reveal.py
│   │   │   └── map_animation.py
│   │   └── data_viz.py          # DataViz — matplotlib -> ffmpeg charts
│   │
│   ├── audio/                   # ===== AUDIO PIPELINE =====
│   │   ├── __init__.py
│   │   ├── tts_engine.py        # TTS — Kokoro wrapper (port from V1)
│   │   ├── music_library.py     # MusicLibrary — emotion-tagged CC music
│   │   └── mixer.py             # AudioMixer — multi-track mixing
│   │
│   ├── render/                  # ===== STAGE 8: RENDERING =====
│   │   ├── __init__.py
│   │   ├── segment_renderer.py  # SegmentRenderer — ffmpeg segment assembly
│   │   ├── final_renderer.py    # FinalRenderer — concat + polish
│   │   ├── subtitle_burner.py   # SubtitleBurner — SRT/VTT/embedded
│   │   └── thumbnail_gen.py     # ThumbnailGen — frame extract + overlay
│   │
│   ├── critic/                  # ===== STAGE 9: CRITIC =====
│   │   ├── __init__.py
│   │   ├── visual_critic.py     # VisualCritic — Gemini multi-frame QA
│   │   ├── audio_critic.py      # AudioCritic — loudness + silence + sync
│   │   ├── pacing_critic.py     # PacingCritic — shot length analysis
│   │   └── critic_result.py     # CriticResult model
│   │
│   ├── improvement/             # ===== STAGE 10: SELF-IMPROVEMENT =====
│   │   ├── __init__.py
│   │   ├── feedback_loop.py     # FeedbackLoop — aggregate + decide
│   │   ├── autofixer.py         # Autofixer — known failure patterns
│   │   └── cross_video_memory.py # CrossVideoMemory — learn across videos
│   │
│   ├── memory/                  # ===== PERSISTENT MEMORY =====
│   │   ├── __init__.py
│   │   ├── memory_manager.py    # MemoryManager (port from V1, extend)
│   │   └── graph_store.py       # GraphStore — knowledge graph SQLite
│   │
│   └── utils/                   # ===== SHARED UTILITIES =====
│       ├── __init__.py
│       ├── config.py            # Config loader (port from V1)
│       ├── parallel.py          # ThreadPool + ProcessPool helpers
│       ├── timing.py            # Timing + progress tracking
│       └── logging.py           # Structured logging
```

### 2.3 Data Models (v2_types.py)

```python
"""
v2_types.py — All V2 Pydantic models for the intelligence-first pipeline.

Every stage communicates through typed models. No ad-hoc dicts across
module boundaries.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field
from enum import StrEnum
from datetime import datetime
import uuid


# ── Enums ────────────────────────────────────────────────────────────────

class TopicCategory(StrEnum):
    SPACE = "space"
    SCIENCE = "science"
    HISTORY = "history"
    NATURE = "nature"
    TECHNOLOGY = "technology"
    FINANCE = "finance"
    GENERAL = "general"

class EmotionalTone(StrEnum):
    WONDER = "wonder"
    TENSION = "tension"
    DRAMATIC = "dramatic"
    SOLEMN = "solemn"
    ENERGETIC = "energetic"
    MYSTERIOUS = "mysterious"
    NOSTALGIC = "nostalgic"
    CONTEMPLATIVE = "contemplative"
    URGENT = "urgent"
    TRIUMPHANT = "triumphant"
    HOPEFUL = "hopeful"
    NEUTRAL = "neutral"

class NarrativeRole(StrEnum):
    HOOK = "hook"
    CONTEXT = "context"
    EXPLORATION = "exploration"
    CLIMAX = "climax"
    RESOLUTION = "resolution"
    CONCLUSION = "conclusion"

class ShotType(StrEnum):
    PRIMARY = "primary"
    CUTAWAY = "cutaway"
    BACKUP = "backup"
    ANIMATION = "animation"
    DATA_VIZ = "data_viz"
    MAP = "map"
    TEXT_OVERLAY = "text_overlay"
    MOTION_GRAPHICS = "motion_graphics"
    AI_GENERATED = "ai_generated"

class CameraMotion(StrEnum):
    STATIC = "static"
    KEN_BURNS_IN = "ken_burns_in"
    KEN_BURNS_OUT = "ken_burns_out"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    FOLLOW = "follow"
    TRUCK_IN = "truck_in"
    TRUCK_OUT = "truck_out"
    PARALLAX = "parallax"
    DRIFT = "drift"

class TransitionType(StrEnum):
    CUT = "cut"
    CROSSFADE = "crossfade"
    FADE = "fade"
    DIP_TO_BLACK = "dip_to_black"
    DIP_TO_WHITE = "dip_to_white"
    WIPE_LEFT = "wipe_left"
    WIPE_RIGHT = "wipe_right"
    SLIDE = "slide"
    ZOOM = "zoom"

class AssetProvider(StrEnum):
    PEXELS = "pexels"
    PIXABAY = "pixabay"
    NASA = "nasa"
    WIKIMEDIA = "wikimedia"
    ANIMATION = "animation"
    DATA_VIZ = "data_viz"
    AI_GENERATED = "ai_generated"
    REUSE = "reuse"
    FALLBACK = "fallback"
    EMERGENCY = "emergency"

class CriticSeverity(StrEnum):
    CRITICAL = "critical"   # Must fix before release
    MAJOR = "major"          # Should fix, can release if urgent
    MINOR = "minor"          # Nice to fix
    INFO = "info"            # Log only


# ── Stage 1-2: Research Intelligence ─────────────────────────────────────

class Source(BaseModel):
    url: str = ""
    title: str = ""
    domain: str = ""
    snippet: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)

class Fact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    claim: str
    sources: list[Source]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    category: str = "general"
    verified: bool = False
    verification_notes: str = ""

class ResearchDocument(BaseModel):
    topic: str
    sources: list[Source] = []
    key_facts: list[Fact] = []
    key_statistics: list[str] = []
    key_dates: list[dict] = []
    key_people: list[str] = []
    controversies: list[str] = []
    timelines: list[dict] = []
    unanswered_questions: list[str] = []

class KnowledgeNode(BaseModel):
    id: str
    label: str
    type: str  # "concept", "person", "event", "place", "date", "stat"
    description: str = ""

class KnowledgeEdge(BaseModel):
    source_id: str
    target_id: str
    relationship: str  # "causes", "contradicts", "supports", "precedes", etc.

class KnowledgeGraph(BaseModel):
    nodes: list[KnowledgeNode] = []
    edges: list[KnowledgeEdge] = []
    topic: str = ""


# ── Stage 3: Story Planning ─────────────────────────────────────────────

class NarrativeBeat(BaseModel):
    index: int
    role: NarrativeRole
    hook_sentence: str = ""
    core_message: str = ""
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    knowledge_node_ids: list[str] = []
    target_duration_range: tuple[float, float] = (45.0, 120.0)  # seconds
    cliffhanger: str = ""  # What makes the viewer want to keep watching

class NarrativeArc(BaseModel):
    topic: str
    title: str = ""
    subtitle: str = ""
    logline: str = ""
    beats: list[NarrativeBeat] = []
    total_target_duration: float = 480.0  # 8 minutes
    narrative_framework: str = "mystery_reveal"  # or "chronological", "problem_solution", etc.


# ── Stage 4: Scene Planning ─────────────────────────────────────────────

class SceneDialogue(BaseModel):
    speaker: str = "narrator"
    text: str
    emphasis_words: list[str] = []

class SceneV2(BaseModel):
    scene_id: int
    title: str
    narration_segments: list[SceneDialogue]  # Spoken text
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    target_duration: float  # seconds
    scene_purpose: str = ""
    transition_in: TransitionType = TransitionType.CROSSFADE
    transition_out: TransitionType = TransitionType.CROSSFADE
    knowledge_ids: list[str] = []  # References into KnowledgeGraph
    music_emotion: str = "ambient"  # For music_library lookup


# ── Stage 5: Visual Planning ────────────────────────────────────────────

class VisualQuery(BaseModel):
    query: str
    query_variants: list[str] = []
    provider_priority: list[str] = []

class CameraDirection(BaseModel):
    motion: CameraMotion = CameraMotion.STATIC
    zoom_start: float = 1.0
    zoom_end: float = 1.0
    pan_x: int = 0
    pan_y: int = 0

class ShotV2(BaseModel):
    shot_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    scene_id: int
    beat_index: int = 0
    shot_index: int = 0
    shot_type: ShotType
    start_ms: float
    end_ms: float
    narration_indices: list[int] = []  # Which narration segments align with this shot
    visual_query: Optional[VisualQuery] = None
    camera: CameraDirection = CameraDirection()
    transition_in: TransitionType = TransitionType.CROSSFADE
    transition_out: TransitionType = TransitionType.CROSSFADE

    # Animation-specific (if shot_type == ANIMATION or DATA_VIZ)
    animation_template: str = ""
    animation_params: dict = {}

class ColorGrade(BaseModel):
    saturation: float = 1.0
    contrast: float = 1.0
    brightness: float = 0.0
    temperature: float = 5600.0

class SubtitleLine(BaseModel):
    start_ms: float
    end_ms: float
    text: str
    words: list[dict] = []  # [{text, start_ms, end_ms}]

class SceneAudioPlan(BaseModel):
    narration_path: str = ""
    music_path: str = ""
    music_volume_db: float = -18.0
    ducking_enabled: bool = True
    ducking_reduction_db: float = 10.0
    ducking_attack_ms: int = 200
    ducking_release_ms: int = 500
    sound_effects: list[dict] = []  # [{path, start_ms, volume_db}]

class VisualPlan(BaseModel):
    scenes: list[SceneV2] = []
    shots: list[ShotV2] = []
    subtitles: list[SubtitleLine] = []
    global_color_grade: ColorGrade = ColorGrade()
    timeline_version: str = "2.0"
    render_settings: dict = {"resolution": [1920, 1080], "fps": 30}
    video_id: str = ""


# ── Stage 6-7: Asset Models ─────────────────────────────────────────────

class AssetRecord(BaseModel):
    shot_id: str
    provider: AssetProvider
    source_url: str = ""
    local_path: str = ""
    duration: float = 0.0
    width: int = 1920
    height: int = 1080
    semantic_score: float = 0.0
    technical_score: float = 0.0
    motion: CameraDirection = CameraDirection()
    color_grade: ColorGrade = ColorGrade()

class AnimationJob(BaseModel):
    job_id: str
    template_name: str
    params: dict
    output_path: str
    estimated_runtime_s: float = 30.0
    priority: int = 5  # 1-10, higher = more urgent

class SegmentRenderJob(BaseModel):
    segment_id: str
    start_ms: float
    end_ms: float
    shots: list[AssetRecord]
    narration_path: str
    music_path: str
    sfx: list[dict] = []
    subtitles: list[SubtitleLine] = []
    output_path: str
    codec: str = "libx264"
    crf: int = 18
    preset: str = "slow"


# ── Stage 9: Critic Models ──────────────────────────────────────────────

class CriticIssue(BaseModel):
    severity: CriticSeverity
    category: str  # "frame_quality", "audio_clipping", "subtitle_sync", "pacing", etc.
    description: str
    location: dict = {}  # e.g. {"frame_ms": 15000, "segment": "seg-03"}
    suggestion: str = ""

class VisualCriticResult(BaseModel):
    frames_checked: int = 10
    frames_passed: int = 0
    frames_failed: int = 0
    pass_rate: float = 0.0
    issues: list[CriticIssue] = []

class AudioCriticResult(BaseModel):
    integrated_lufs: float = 0.0
    true_peak_db: float = 0.0
    silence_gaps: list[dict] = []
    clipping_events: list[dict] = []
    issues: list[CriticIssue] = []

class PacingCriticResult(BaseModel):
    avg_shot_duration: float = 0.0
    shot_duration_variance: float = 0.0
    transition_diversity: int = 0
    predicted_retention_score: float = 0.0
    issues: list[CriticIssue] = []

class VideoCriticReport(BaseModel):
    video_id: str
    visual: VisualCriticResult
    audio: AudioCriticResult
    pacing: PacingCriticResult
    overall_score: float = 0.0
    recommended_action: str = "approve"  # approve, autofix, rebuild


# ── Stage 10: Improvement Models ────────────────────────────────────────

class ImprovementAction(BaseModel):
    action_type: str  # "rerender_segment", "replace_asset", "adjust_audio", "rebuild_script"
    target: str  # e.g. "segment_seg-03", "shot_abc123"
    params: dict = {}
    priority: int = 5
    estimated_time_s: float = 30.0


# ── Pipeline State ──────────────────────────────────────────────────────

class PipelineStateV2(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str
    category: TopicCategory = TopicCategory.GENERAL
    status: str = "initialized"  # initialized → researching → verified → planning → acquiring → rendering → critiquing → improving → complete

    # Stage results
    research_document: Optional[ResearchDocument] = None
    knowledge_graph: Optional[KnowledgeGraph] = None
    narrative_arc: Optional[NarrativeArc] = None
    scenes: list[SceneV2] = []
    visual_plan: Optional[VisualPlan] = None
    acquired_assets: list[AssetRecord] = []
    animation_jobs: list[AnimationJob] = []
    segment_jobs: list[SegmentRenderJob] = []
    rendered_segments: list[str] = []

    # Critic results
    critic_report: Optional[VideoCriticReport] = None
    improvement_actions: list[ImprovementAction] = []

    # Timing
    started_at: float = 0.0
    stages_elapsed: dict[str, float] = {}

    # Iteration control
    iteration: int = 0
    max_iterations: int = 3
```

---

## 3. Pipeline Stage 1: Research Intelligence

### Purpose

Replace single-shot LLM script generation with a structured research phase. Instead of asking the LLM to "write a script about X," we first gather real sources, extract facts, and build an evidence base.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `topic` | `str` | User or queue |
| `max_sources` | `int` | `configs/research.yaml` (default: 15) |
| `recency_days` | `int` | `configs/research.yaml` (default: 365) |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `ResearchDocument` | Pydantic model | ~5-20 KB |
| Output file (cache) | `cache/research/{topic_hash}.json` | ~5-20 KB |

### Python Module

**`src/research/research_agent.py`** — `ResearchAgent` class.

### Algorithm

```
1. Classify topic (TopicClassifier — port from V1, expand categories)
2. Generate 5-8 search queries from topic (DeepSeek)
3. For each query (parallel, max 4 concurrent):
   a. web_search(query, count=3)
   b. web_fetch(result.url) for top results
   c. DeepSeek: extract facts, stats, dates, people from content
   d. Append to ResearchDocument
4. DeepSeek: cross-consolidation pass (merge duplicates, rank by relevance)
5. Cache to disk
```

### Prompt Strategy

**Search Query Generation:**
```
You are a research query planner for a documentary video about "{topic}".
Generate {n} search queries that will find authoritative, factual,
up-to-date information. Cover:
- Core facts and definitions
- Key controversies or debates
- Statistical data
- Historical timeline
- Expert perspectives

Return ONLY a JSON list of strings. Each query 3-8 words.
```

**Fact Extraction (per source):**
```
Extract factual information from the following text about "{topic}".

SOURCE: {url}
TITLE: {title}
TEXT: {content_snippet}

Return JSON:
{
  "facts": [{"claim": "...", "confidence": 0.0-1.0}],
  "statistics": ["..."],
  "key_dates": [{"date": "...", "event": "..."}],
  "key_people": ["..."],
  "controversies": ["..."],
  "unresolved_questions": ["..."]
}
```

**Consolidation:**
```
You have {n} research extracts about "{topic}". Consolidate them into a
coherent research document. Merge duplicate facts, resolve contradictions,
rank by confidence. Remove speculative content.

Current extracts:
{research_json}

Return a ResearchDocument JSON structure.
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| All web searches fail | Use LLM's training data as fallback (set confidence=0.3) |
| Partial source failures | Continue with successful results |
| LLM parse error | Retry once with simpler prompt |
| Timeout (>60s total) | Return whatever has been collected |

### Caching

- **Cache key:** `sha256(topic + max_sources + recency_days)`
- **Cache store:** `cache/research/{key}.json`
- **TTL:** 7 days (research degrades; recency matters)
- **Hit strategy:** Check cache before any network call

### Estimated Runtime

| Component | Time | Notes |
|-----------|------|-------|
| Topic classification | 200ms | Deterministic rule-based fallback |
| Search query gen | 2-5s | One LLM call |
| Web searches (8×) | 4-12s | Parallel, network-bound |
| Web fetches (8-16×) | 4-16s | Parallel, network-bound |
| Fact extraction (8-16×) | 16-40s | Parallel LLM calls |
| Consolidation | 3-8s | One LLM call |
| **Total** | **~30-80s** | Largely network-bound |

### Memory Usage

| Item | Estimate |
|------|----------|
| Research doc JSON | ~50 KB |
| Source texts (during extraction) | ~2-5 MB |
| LLM response buffers | ~5 MB |
| **Peak** | **~10 MB** |

### Oracle ARM Optimization

- `ThreadPoolExecutor(max_workers=4)` for parallel web operations
- `asyncio` web fetching for IO-bound parallelism
- Web fetches are the bottleneck — max 4 concurrent to avoid rate limiting
- Store research doc to disk before proceeding (crash recovery)

### Parallelization

| Parallelism | Count | Strategy |
|-------------|-------|----------|
| Search queries | 4 concurrent | ThreadPool per query group |
| Web fetches | 4 concurrent | ThreadPool per URL |
| LLM extractions | 4 concurrent | ThreadPool, batched |

---

## 4. Pipeline Stage 2: Knowledge Graph

### Purpose

Transform flat research facts into a structured knowledge graph. Facts, concepts, people, events, and dates become nodes. Relationships (causes, contradicts, supports, precedes) become edges. This graph drives narrative structure and ensures every scene is grounded in verified information.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `ResearchDocument` | `ResearchDocument` | Stage 1 output |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `KnowledgeGraph` | Pydantic model | ~2-10 KB |
| Graph DB | SQLite | `cache/knowledge/{topic_hash}.db` |

### Python Module

**`src/research/knowledge_graph.py`** — `KnowledgeGraphBuilder` class.

### Algorithm

```
1. LLM: Extract entities from ResearchDocument (DeepSeek)
   → nodes: concepts, people, events, dates
2. LLM: Identify relationships between entities
   → edges: "Einstein → developed → Theory_of_Relativity"
3. LLM: Build narrative structure from graph
   → Which nodes are foundational? Which are conclusions?
   → Returns a ranked "story path" through the graph
4. Store in SQLite for cross-video reference
5. Generate story_context: a distilled narrative-ready excerpt
```

### Prompt Strategy

**Entity Extraction:**
```
From this research document about "{topic}", extract all named entities
(concepts, people, events, dates, places, statistics).

Research: {research_json}

Return JSON:
{
  "concepts": [{"id": "c1", "label": "Great Filter", "description": "..."}],
  "people": [{"id": "p1", "label": "Enrico Fermi", "description": "..."}],
  "events": [{"id": "e1", "label": "Drake Equation (1961)", "description": "..."}],
  "dates": [{"id": "d1", "label": "1961", "description": "..."}],
  "statistics": [{"id": "s1", "label": "100 billion stars", "description": "..."}]
}
```

**Relationship Extraction:**
```
Identify relationships between these entities about {topic}:

Entities: {entities_json}

Return JSON:
{
  "edges": [
    {"source_id": "c1", "target_id": "c2", "relationship": "contradicts"},
    {"source_id": "p1", "target_id": "e1", "relationship": "proposed"}
  ]
}
Relationships: "proposed", "contradicts", "supports", "causes", "precedes",
"example_of", "predicts", "questions", "solves"
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| LLM fails entity extraction | Generate flat list from research doc keywords |
| LLM fails relationship extraction | Default: star graph (all connected to topic) |
| No entities found | Create single node (topic) and continue |

### Caching

- **Cache key:** `sha256(topic + research_doc_json)`
- **Cache store:** `cache/knowledge/{key}.json`
- **TTL:** 30 days (knowledge is relatively stable)

### Estimated Runtime

| Component | Time | Notes |
|-----------|------|-------|
| Entity extraction | 4-10s | One LLM call |
| Relationship extraction | 4-10s | One LLM call |
| Graph construction | 200ms | Deterministic |
| Narrative path extraction | 4-8s | One LLM call |
| **Total** | **~12-28s** | 2-3 LLM calls |

### Memory Usage

| Item | Estimate |
|------|----------|
| KnowledgeGraph JSON | ~10 KB |
| SQLite connection | ~1 MB |
| LLM buffers | ~2 MB |
| **Peak** | **~5 MB** |

### Oracle ARM Optimization

- Graph operations are deterministic and negligible cost
- SQLite WAL mode for concurrent reads during cross-video queries
- Store as both JSON (fast load) and SQLite (queryable)

### Parallelization

This stage is inherently sequential (entities → relationships). No significant parallelization opportunity.

---

## 5. Pipeline Stage 3: Story Planning

### Purpose

Design the narrative arc. Instead of writing a script from scratch, we select a narrative framework (mystery-reveal, chronological, problem-solution), place knowledge graph entities into narrative beats, and produce a structured arc with hooks, tension curves, and conclusions.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `KnowledgeGraph` | `KnowledgeGraph` | Stage 2 |
| `target_duration` | `float` | `configs/pipeline.yaml` (default: 480s) |
| `narrative_template` | `str` | `configs/planner.yaml` (default: "documentary") |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `NarrativeArc` | Pydantic | ~5-15 KB |

### Python Module

**`src/planner/story_planner.py`** — `StoryPlannerV2` class.

### Algorithm

```
1. DeepSeek: Analyze knowledge graph + select narrative framework
   → mystery-reveal, chronological, problem-solution, etc.
2. DeepSeek: Design 5-8 narrative beats
   → Each beat: hook, core message, emotional tone, KG references
3. DeepSeek: Generate logline + title
4. Self-critic: Score narrative for engagement
   → If hook_score < 0.7: rewrite hooks
5. Cache narrative arc
```

### Prompt Strategy

**Framework Selection:**
```
You are a documentary story architect. Analyze this knowledge graph
and research document about "{topic}":

Knowledge Graph: {kg_json}
Research Document: {research_json}

Which narrative framework would best present this topic?
Options: "mystery_reveal", "chronological", "problem_solution",
         "comparison", "listicle", "character_driven"

Return JSON:
{
  "framework": "mystery_reveal",
  "reasoning": "The Fermi Paradox is fundamentally a mystery — we have
                a question but no answer. A mystery-reveal structure
                builds tension by presenting the question first, exploring
                possible answers, and ending with the unresolved nature
                of the question itself.",
  "expected_tension_curve": "gradual_rise_plateau"
}
```

**Beat Design:**
```
Design the narrative beats for a {framework} documentary about {topic}.

Target duration: {target_duration}s
Knowledge graph: {kg_json}

Each beat should:
1. Have a clear hook sentence (what makes the viewer want to see the next beat)
2. Reference specific knowledge graph entities
3. Have an emotional tone
4. Include a cliffhanger or transition hook

Return JSON:
{
  "title": "The Great Silence",
  "subtitle": "Why the Universe Isn't Talking Back",
  "logline": "A journey through the most profound question in science.",
  "beats": [
    {
      "index": 0,
      "role": "hook",
      "hook_sentence": "The universe is 13.8 billion years old, contains more stars
                         than grains of sand on Earth, and is completely silent.",
      "core_message": "The Fermi Paradox is the tension between high probability
                       of alien life and complete absence of evidence.",
      "emotional_tone": "wonder",
      "knowledge_node_ids": ["fermi_paradox", "drake_equation"],
      "target_duration_range": [60, 90],
      "cliffhanger": "But there are several possible explanations — and some of them
                       are terrifying."
    }
    // ... more beats
  ]
}
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| LLM returns bad framework | Default to "documentary" template from V1 |
| Beat generation fails | Use V1-style scene generation as fallback |
| Hook score below threshold | Retry hook generation once |

### Caching

- **Cache key:** `sha256(topic + narrative_template + target_duration)`
- **Cache store:** `cache/narrative/{key}.json`
- **TTL:** 14 days
- **Note:** Research may update but narrative structure is reusable

### Estimated Runtime

| Component | Time | Notes |
|-----------|------|-------|
| Framework selection | 3-8s | One LLM call |
| Beat generation (5-8 beats) | 8-20s | One LLM call |
| Hook self-critic | 3-8s | One LLM call |
| **Total** | **~14-36s** | 2-3 LLM calls |

### Memory Usage

| Item | Estimate |
|------|----------|
| NarrativeArc JSON | ~15 KB |
| LLM buffers | ~3 MB |
| **Peak** | **~5 MB** |

### Oracle ARM Optimization

- Single-threaded LLM calls — this stage is LLM-bound, not CPU-bound
- Cache aggressively to avoid unnecessary calls
- Store beat data as structured JSON, not prose

### Parallelization

Beats are generated in one LLM call (sequential dependencies within the arc). No parallelization.

---

## 6. Pipeline Stage 4: Scene Planning

### Purpose

Expand each narrative beat into concrete scenes with timed narration, emotional arcs, and scene-level transitions. Each scene contains narration text as a `SceneDialogue` list, which preserves word-level structure for subtitle timing and for beat-level shot planning.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `NarrativeArc` | `NarrativeArc` | Stage 3 |
| `KnowledgeGraph` | `KnowledgeGraph` | Stage 2 |
| `words_per_second` | `float` | Config (default: 3.0) |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `list[SceneV2]` | Pydantic list | ~10-30 KB |

### Python Module

**`src/planner/scene_planner.py`** — `ScenePlannerV2` class.

### Algorithm

```
For each NarrativeBeat:
  1. LLM: Expand beat into 2-3 scenes
     → Each scene: narration text, duration, emotional tone
  2. Apply target_duration_range constraint
  3. Calculate word counts from narration (words_per_second budgeting)
  4. Assign transition types between scenes
     → emotion change → crossfade
     → new narrative section → dip_to_black
  5. Auto-assign music_emotion from scene emotional_tone
```

### Prompt Strategy

```
You are a documentary scene writer. Expand this narrative beat into
2-3 concrete scenes.

Narrative Beat:
  Index: {index}
  Role: {role}
  Hook: {hook_sentence}
  Core Message: {core_message}
  Tone: {emotional_tone}
  Target Range: {duration_range}
  Knowledge References: {knowledge_refs}

Knowledge Graph Context:
{kg_relevant_nodes}

Each scene should be a coherent 30-90 second segment with clear
spoken narration (3 words/second speaking rate).

Return JSON:
{
  "scenes": [
    {
      "title": "The Scale of the Cosmos",
      "emotional_tone": "wonder",
      "target_duration": 45.0,
      "scene_purpose": "Establish the incomprehensible scale of the universe",
      "narration_segments": [
        {"speaker": "narrator", "text": "When you look up at the night sky...",
         "emphasis_words": ["incomprehensibly vast"]}
      ],
      "knowledge_ids": ["milky_way", "observable_universe", "stellar_count"],
      "transition_in": "fade",
      "transition_out": "crossfade",
      "music_emotion": "wonder_ambient"
    }
  ]
}
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| LLM fails scene expansion | Split beat with V1-style planner heuristics |
| Scene duration too long/short | Trim/extend narration to fit budget |
| Narration segmentation fails | Create single-segment scene |

### Caching

- **Cache key:** `sha256(narrative_arc_json + kg_hash)`
- **TTL:** 14 days

### Estimated Runtime

| Component | Time | Notes |
|-----------|------|-------|
| Scene expansion (5-8 beats) | 15-40s | One LLM call per beat (parallelizable) |
| **Total** | **~15-40s** | |

### Memory Usage

| Item | Estimate |
|------|----------|
| Scene list | ~30 KB |
| **Peak** | **~5 MB** |

### Parallelization

Beat expansion is embarrassingly parallel: each beat → scenes independently.

- `ThreadPoolExecutor(max_workers=4)` for beat expansion
- 6 beats at 8s each = 12s vs 48s sequential

---

## 7. Pipeline Stage 5: Visual Planning

### Purpose

For every scene, generate a shot-by-shot visual plan. This is where we decide: does this narration segment need stock footage? An animation? A chart? A map? A text overlay? An AI-generated image?

The output is `timeline_v2.json` — the complete production specification.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `list[SceneV2]` | Pydantic list | Stage 4 |
| `KnowledgeGraph` | `KnowledgeGraph` | Stage 2 |
| `providers.yaml` | Config | Asset provider config |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `VisualPlan` (containing `timeline_v2.json`) | Pydantic | ~50-200 KB |
| JSON file | `timeline_v2.json` | ~50-200 KB |

### Python Module

**`src/planner/visual_planner.py`** — `VisualPlannerV2` class.

### Algorithm

```
For each SceneV2:
  1. Parse narration into 3-12 second segments (V1 beat splitting logic)
  2. For each segment, classify required visual:
     a. Is this an abstract concept (emotion, math, system)?
        → assign animation template
     b. Is this a statistical fact?
        → assign data_viz template
     c. Is this a known location or historical event?
        → assign map or stock search
     d. Is this a concrete visual?
        → assign stock video query
     e. Is this a key point needing emphasis?
        → add text overlay or motion graphics
  3. For stock shots: generate search queries (KnowledgeGraph-aware)
  4. Assign camera motion based on emotional tone
  5. Assign transitions based on emotion changes
  6. Build subtitle word-timing placeholders
  7. Assign music per scene emotion
  8. Assign sound effect triggers at transitions
```

### Prompt Strategy

**Shot Classification:**
```
Classify each narration segment into the best visual type.

Narration: "{narration_text}"
Topic: {topic}
Knowledge Graph: {kg_nodes}

Options: "stock_video", "animation", "data_viz", "map", "text_overlay",
         "motion_graphics", "ai_image"

For each segment, return JSON:
{
  "classification": "animation",
  "confidence": 0.92,
  "reasoning": "This segment explains how the Great Filter works — an abstract
                concept that stock footage cannot adequately represent.",
  "suggested_animation_template": "particle_system_evolution",
  "search_query_override": ""  // Only for stock_video
}
```

**Query Generation (KnowledgeGraph-augmented):**
```
You need to find stock footage for this narration segment about {topic}.

Narration: "{narration_text}"
Relevant KG Concepts: {kg_concepts}

Generate 5 diverse, visually concrete search queries optimized for stock
video libraries. Each query should describe something filmable.

Rules:
- 2-6 words each
- Concrete visual elements (not abstract)
- Vary: wide/close/aerial/detail
- Include KG concept keywords

Return: JSON list of strings.
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| LLM shot classification fails | Default to `stock_video` for all shots |
| Animation template unknown | Use generic `text_reveal` template |
| All stock queries poorly scored | Regenerate with broader terms |
| Scene has no shots | Create one text_overlay shot per scene |

### Caching

- **Cache key:** `sha256(scenes_json + kg_hash)`
- **TTL:** 7 days
- **Note:** Visual plan is the most expensive to regenerate

### Estimated Runtime

| Component | Time | Notes |
|-----------|------|-------|
| Shot classification (per scene, parallel) | 8-20s | 1 LLM call per scene |
| Query generation (per scene, parallel) | 4-10s | 1 LLM call per scene |
| Transition assignment | 200ms | Rule-based |
| Timeline assembly | 500ms | Deterministic |
| **Total** | **~12-30s** | Parallelized across scenes |

### Memory Usage

| Item | Estimate |
|------|----------|
| VisualPlan (timeline JSON) | ~200 KB |
| Shot classification results | ~100 KB |
| **Peak** | **~10 MB** |

### Oracle ARM Optimization

- Parallelize scene processing with `ThreadPoolExecutor(max_workers=4)`
- Visual plan is the largest data structure — store and load as JSON
- Deterministic rules (transitions, camera motion) are instant

### Parallelization

| Parallelism | Count | Strategy |
|-------------|-------|----------|
| Scene processing | 4 concurrent | ThreadPool per scene |
| Shot classification + queries | Same scene sequential | Each scene is independent |

---

## 8. timeline_v2.json — Full Schema

This is the authoritative document that defines the complete multi-track production specification. Every downstream stage (asset acquisition, animation, rendering, mixing, subtitling) reads from this single file.

### Top-Level Structure

```json
{
  "version": "2.0",
  "meta": {
    "video_id": "fp-20260710",
    "topic": "The Fermi Paradox",
    "category": "space",
    "created_at": "2026-07-10T19:00:00Z",
    "pipeline_version": "2.0",
    "total_duration_ms": 480000,
    "total_beats": 6,
    "total_scenes": 14,
    "total_shots": 84,
    "total_animations": 3,
    "total_segments": 12
  },
  "render": {
    "resolution": [1920, 1080],
    "fps": 30,
    "pixel_format": "yuv420p",
    "video_codec": "libx264",
    "video_bitrate": "16M",
    "crf": 18,
    "preset": "slow",
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "sample_rate": 48000,
    "segment_duration_s": 60
  },
  "narration": {
    "tracks": [
      {
        "track_id": "narrator_main",
        "voice": "bm_george",
        "speed": 1.0,
        "language": "en-gb",
        "segments": [
          {
            "segment_id": "nar-001",
            "scene_id": 0,
            "text": "When you look up at the night sky, you see stars. Billions of them.",
            "start_ms": 0,
            "end_ms": 6000,
            "emphasis_ranges": [
              {"start_ms": 3000, "end_ms": 5000, "type": "slow_down"}
            ]
          }
        ]
      }
    ],
    "audio_path": "cache/audio/narration_track.wav"
  },
  "visuals": {
    "shots": [
      {
        "shot_id": "shot-001",
        "scene_id": 0,
        "beat_index": 0,
        "shot_index": 0,
        "type": "stock_video",
        "layer": 1,
        "start_ms": 0,
        "end_ms": 4000,
        "narration_refs": ["nar-001"],
        "source": {
          "provider": "pexels",
          "intent": "stock_footage",
          "queries": [
            {"query": "milky way night sky timelapse", "weight": 0.8},
            {"query": "starfield cinematic wide shot", "weight": 0.5},
            {"query": "observatory telescope stars", "weight": 0.3}
          ],
          "selected_url": "",
          "selected_filepath": "",
          "original_duration_ms": 10000,
          "loop": false,
          "speed": 1.0
        },
        "camera": {
          "motion": "zoom_in",
          "zoom_start": 1.0,
          "zoom_end": 1.08,
          "pan_x": 0,
          "pan_y": -20
        },
        "color_grade": {
          "saturation": 1.2,
          "contrast": 1.1,
          "brightness": -0.05,
          "temperature": 5800,
          "shadows": {"color": "#000033", "amount": 0.1},
          "highlights": {"color": "#FFD700", "amount": 0.05}
        },
        "transition_in": {
          "type": "fade",
          "duration_ms": 500,
          "easing": "ease_in"
        },
        "transition_out": {
          "type": "crossfade",
          "duration_ms": 400,
          "easing": "ease_out"
        },
        "overlays": []
      }
    ]
  },
  "animations": [
    {
      "animation_id": "anim-001",
      "scene_id": 2,
      "type": "diagram_explainer",
      "engine": "manim",
      "template_name": "comparison_bars",
      "params": {
        "datasets": [
          {"label": "Earth", "value": 1.0, "color": "#00BFFF"},
          {"label": "Proxima b", "value": 1.3, "color": "#FF6B35"},
          {"label": "TRAPPIST-1e", "value": 0.8, "color": "#7B68EE"}
        ],
        "title": "Relative sizes of potentially habitable worlds",
        "x_label": "Planet",
        "y_label": "Radius (Earth = 1)",
        "color_scheme": "cosmic",
        "transition_duration_s": 0.5,
        "total_duration_s": 10.0
      },
      "start_ms": 45000,
      "end_ms": 55000,
      "output_path": "cache/animation/anim_001.mp4",
      "resolution": [1920, 1080],
      "fps": 30,
      "expected_render_time_s": 45.0
    }
  ],
  "subtitles": {
    "enabled": true,
    "burn_in": false,
    "main_language": "en",
    "lines": [
      {
        "line_index": 1,
        "start_ms": 500,
        "end_ms": 3500,
        "text": "When you look up at the night sky, you see stars.",
        "words": [
          {"text": "When", "start_ms": 500, "end_ms": 700},
          {"text": "you", "start_ms": 700, "end_ms": 900},
          {"text": "look", "start_ms": 900, "end_ms": 1100},
          {"text": "up", "start_ms": 1100, "end_ms": 1300},
          {"text": "at", "start_ms": 1300, "end_ms": 1500},
          {"text": "the", "start_ms": 1500, "end_ms": 1700},
          {"text": "night", "start_ms": 1700, "end_ms": 2000},
          {"text": "sky,", "start_ms": 2000, "end_ms": 2400},
          {"text": "you", "start_ms": 2400, "end_ms": 2600},
          {"text": "see", "start_ms": 2600, "end_ms": 2900},
          {"text": "stars.", "start_ms": 2900, "end_ms": 3500}
        ],
        "style": {
          "font": "Arial",
          "font_size": 36,
          "color": "#FFFFFF",
          "outline_color": "#000000",
          "outline_width": 2,
          "shadow_color": "#000000",
          "shadow_offset": [2, 2],
          "position": "bottom_center",
          "bottom_margin_px": 80,
          "animation": {
            "type": "karaoke",
            "active_word_color": "#FFD700",
            "active_word_scale": 1.1,
            "fade_in_ms": 100,
            "fade_out_ms": 100
          }
        }
      }
    ]
  },
  "transitions": [
    {
      "from": "shot-001",
      "to": "shot-002",
      "type": "crossfade",
      "duration_ms": 500,
      "easing": "ease_in_out",
      "params": {
        "overlap_frames": 15
      }
    },
    {
      "from_scene": 1,
      "to_scene": 2,
      "type": "dip_to_black",
      "duration_ms": 800,
      "easing": "ease_out"
    }
  ],
  "sound_effects": [
    {
      "sfx_id": "sfx-001",
      "trigger": "transition",
      "transition_ref": {"from": "shot-001", "to": "shot-002"},
      "filepath": "assets/sfx/whoosh_soft_01.wav",
      "start_ms": 3950,
      "duration_ms": 600,
      "volume_db": -8,
      "pan": 0,
      "fade_in_ms": 50,
      "fade_out_ms": 100
    },
    {
      "sfx_id": "sfx-002",
      "trigger": "emphasis",
      "narration_ref": "nar-001",
      "emphasis_word": "billions",
      "start_ms": 4500,
      "filepath": "assets/sfx/soft_stinger.wav",
      "duration_ms": 1500,
      "volume_db": -10
    }
  ],
  "music": {
    "enabled": true,
    "global_mix": {
      "master_volume_db": -1.0,
      "ducking_enabled": true,
      "ducking_reduction_db": 10,
      "ducking_attack_ms": 200,
      "ducking_release_ms": 500
    },
    "tracks": [
      {
        "track_id": "music-001",
        "emotion": "wonder",
        "filepath": "assets/music/wonder_ambient.wav",
        "start_ms": 0,
        "end_ms": 90000,
        "volume_db": -18,
        "fade_in_ms": 3000,
        "fade_out_ms": 3000,
        "scene_ids": [0, 1]
      },
      {
        "track_id": "music-002",
        "emotion": "tension",
        "filepath": "assets/music/tension_build.wav",
        "start_ms": 90000,
        "end_ms": 180000,
        "volume_db": -20,
        "fade_in_ms": 1000,
        "fade_out_ms": 1000,
        "scene_ids": [2, 3]
      }
    ]
  },
  "overlays": [
    {
      "overlay_id": "overlay-001",
      "type": "text_callout",
      "shot_ref": "shot-003",
      "start_ms": 15000,
      "end_ms": 18000,
      "content": {
        "text": "100 billion stars",
        "font_size": 48,
        "color": "#FFD700",
        "font": "Arial Bold",
        "position": "center",
        "animation": {
          "type": "typewriter",
          "characters_per_second": 8,
          "cursor_enabled": true
        }
      }
    }
  ],
  "segments": [
    {
      "segment_id": "seg-001",
      "start_ms": 0,
      "end_ms": 60000,
      "shots": ["shot-001", "shot-002", "shot-003", "shot-004"],
      "music_tracks": ["music-001"],
      "sfx": ["sfx-001"],
      "subtitles_start_index": 0,
      "subtitles_end_index": 15,
      "output_path": "cache/segments/seg_001.mp4",
      "render_status": "pending"
    }
  ]
}
```

### Schema Key Changes from V1

| V1 (current) | V2 (proposed) | Why |
|-------------|---------------|-----|
| Flat audio/video timeline | `narration`, `visuals`, `animations`, `subtitles`, `transitions`, `sfx`, `music`, `overlays` | Separate concerns; each track has its own data model |
| Video clips only | Shots + animations + data viz + maps | Unified timeline for all visual types |
| Auto-generated motion | Per-shot camera directive | Explicit artistic control |
| No per-shot color grade | Per-shot color grade | Enables mood variation between shots |
| No sound effects | Sound effects with triggers | Professional audio texture |
| Single music file | Multi-track emotional music bed | Emotional arc through music changes |
| Flat subtitle text | Word-level timing | Karaoke-style highlighting |
| No overlays | Text callouts, graphics | Visual emphasis without full animation |
| Render in one shot | Segment-based | Enables parallel rendering |

---

## 9. Pipeline Stage 6: Asset Acquisition

### Purpose

Fulfill every `stock_video` shot in the timeline by searching providers, validating quality, and downloading. Runs in parallel with Stage 7 (animation).

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `VisualPlan.shots` (filtered to stock_video type) | `list[ShotV2]` | Stage 5 |
| `visual_queries` (per shot) | `list[VisualQuery]` | Stage 5 |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `list[AssetRecord]` | Pydantic list | Variable |
| Downloaded assets | MP4/WEBM files | ~10-200 MB each |

### Python Module

**`src/assets/orchestrator.py`** — `AssetOrchestrator` class.
**`src/assets/stock_search.py`** — `StockSearcher` class.

### Algorithm

```
For each stock_video ShotV2 (parallel, 4 concurrent):
  1. Check cache first (SQLite by query hash)
  2. Try queries in priority order:
     a. Provider chain: pexels → pixabay → wikimedia → nasa
     b. Semantic validation (DeepSeek: "does this match the narration?")
     c. Quality gate checks (resolution, duration match, no watermark)
     d. If all providers fail: classify as "needs_fallback"
  3. Download best match → AssetRecord
  4. Record in cache database
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| All providers fail | Reclassify shot to fallback: NASA image → Ken Burns → animate(gradient) |
| Downloaded file is corrupt | Delete and retry next result |
| Duration < shot duration | Loop the clip with crossfade |
| Resolution < 1080p | Accept with quality penalty; upscale with ffmpeg |

### Caching

- **Cache store:** `cache/assets/` (SQLite catalog + disk files)
- **Cache key:** `sha256(query + provider + target_duration)`
- **TTL:** 30 days (stock footage URLs are stable)
- **Size limit:** 500 MB (LRU eviction)

### Estimated Runtime

| Component | Time per Shot | Notes |
|-----------|---------------|-------|
| Search (all providers) | 2-8s | Sequential provider chain |
| Semantic validation | 3-6s | One LLM call |
| Download | 3-20s | Network-bound, file size dependent |
| **Total per shot** | **~5-35s** | |
| **Total for 60 shots** | **~30-210s** | Parallel, 4 workers |

### Memory Usage

| Item | Estimate |
|------|----------|
| Asset metadata | ~100 KB |
| Downloaded clip (in flight) | ~50 MB |
| **Peak** | **~200 MB** (4 concurrent downloads) |

### Oracle ARM Optimization

- 4 concurrent downloads via `ThreadPoolExecutor(max_workers=4)`
- Download directly to disk (never buffer entire file in RAM)
- Use `requests` streaming downloads with 10 MB chunk buffer
- SQLite cache queries are instant

### Parallelization

| Parallelism | Count | Strategy |
|-------------|-------|----------|
| Shot acquisition | 4 concurrent | ThreadPool per shot |

---

## 10. Pipeline Stage 7: Animation Planning & Rendering

### Purpose

Generate all non-stock visuals: Manim animations, data visualizations, maps. These run in parallel with Stage 6 (asset acquisition) since they are independent.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `VisualPlan.shots` (animation and data_viz types) | `list[ShotV2]` | Stage 5 |
| `VisualPlan.animations` | `list` from timeline | Stage 5 |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `list[AnimationJob]` | Pydantic list | ~5 KB |
| Rendered animation MP4s | MP4 files | ~5-50 MB each |

### Python Module

**`src/animation/manim_runner.py`** — `ManimRunner` class.
**`src/animation/template_library.py`** — `TemplateLibrary` class.
**`src/animation/data_viz.py`** — `DataVizRenderer` class.

### Algorithm

```
For each animation shot (parallel, 2 concurrent):
  1. Look up template in TemplateLibrary
  2. Substitute params into template
  3. Generate Manim Python script
  4. Call `manim -pql script.py` (low quality preview)
  5. Validate output (non-empty, correct duration)
  6. Re-render at production quality: `manim -pqh script.py`
  7. Record rendered path in AnimationJob
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| Manim render fails | Regenerate Manim script with simpler params; retry once |
| Duration mismatch | Pad/cut with ffmpeg |
| Template not found | Use `text_reveal` as universal fallback |
| Manim not installed | Generate matplotlib animation instead |

### Caching

- **Cache key:** `sha256(template_name + json(params))`
- **TTL:** No limit (identically parameterized animations are reusable)
- **Store:** `cache/animations/{key}.mp4`

### Estimated Runtime

| Animation Type | Time (ARM CPU) | Notes |
|---------------|----------------|-------|
| Text reveal | 5-10s | Simple |
| Bar chart comparison | 15-30s | Moderate complexity |
| Timeline animation | 20-40s | Moderate |
| Particle system | 30-90s | High complexity |
| Map animation | 60-180s | Very high |

### Memory Usage

| Item | Estimate |
|------|----------|
| Manim script | ~2 KB |
| Celsius animation (in memory) | ~100-500 MB |
| Final MP4 (on disk) | ~5-50 MB |
| **Peak** | **~600 MB** (Manim may spike RAM) |

### Oracle ARM Optimization

- Max 2 concurrent Manim processes (RAM-limited)
- Use `manim -pql` for preview, `-pqh` for final
- Set `MANIM_FORCE_CPU=1` (no GPU detection)
- Keep Manim scene scripts reusable (cache compiled scenes)
- Fall back to matplotlib (lighter) when Manim takes too long

### Parallelization

| Parallelism | Count | Strategy |
|-------------|-------|----------|
| Animation renders | 2 concurrent | ProcessPool (Manim is CPU-intensive) |

---

## 11. Pipeline Stage 8: Rendering Engine

### Purpose

The core performance improvement over V1. Instead of rendering the entire video with MoviePy (single-threaded, all clips in RAM), we split the video into 30-90 second segments, render each with a separate ffmpeg command (parallel across 4 cores), and concatenate losslessly.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `VisualPlan` | Pydantic | Stage 5 |
| `AssetRecord[]` | Pydantic list | Stage 6 |
| Animation MP4 paths | `string[]` | Stage 7 |
| Narration audio WAV | file | TTS engine |
| Music + SFX files | files | Audio library |
| timeline_v2.json | JSON file | Stage 5 |

### Outputs

| Output | Type | Size |
|--------|------|------|
| Segment MP4s (4×) | MP4 files | ~50-200 MB each |
| Final concatenated MP4 | MP4 file | ~200-800 MB |

### Python Module

**`src/render/segment_renderer.py`** — `SegmentRenderer` class.
**`src/render/final_renderer.py`** — `FinalRenderer` class.
**`src/render/subtitle_burner.py`** — `SubtitleBurner` class.

### Algorithm

**Phase A: Segment Assembly**
```
For each segment in timeline_v2.json (sequential prep):
  1. Collect all shots, animations, overlays for the segment
  2. Build ffmpeg filter complex:
     a. Input each video/animation file
     b. Apply crops, zooms, color grading per shot
     c. Stack in layer order with setpts for timing
     d. Overlay text callouts with drawtext
     e. Overlay subtitles with subtitles filter
     f. Mix audio: narration + music + SFX with volume/pan
     g. Output to temp file
  3. Write ffmpeg command to segment_ffmpeg.sh
```

**Phase B: Parallel Render** (the key optimization)
```
For each segment (ProcessPool with 4 workers):
  > subprocess.run(["ffmpeg", "-y", ...segment command...])
  Blocks until segment is rendered
  Pipeline: 4 segments rendered simultaneously
```

**Phase C: Concatenation**
```
1. Build ffmpeg concat demuxer file (list all segment files)
2. ffmpeg -f concat -i concat_list.txt -c copy final_output.mp4
   (lossless — no re-encoding)
3. Validate: check output file exists, correct duration
```

### ffmpeg Filter Complex (Example Per Segment)

```
# ── Video inputs ──
ffmpeg -y \
  -i shot_001.mp4 -i shot_002.mp4 -i seg_anim_001.mp4 \
  -i narration.wav -i music.wav -i sfx.wav \
  -filter_complex "\
    # Ken Burns zoom on shot_001
    [0:v]zoompan=z='min(1.08,1+0.005*on)':d=120:s=1920x1080[v0];\
    \
    # Static + color grade on shot_002
    [1:v]eq=saturation=1.2:contrast=1.1:brightness=-0.05,scale=1920:1080[v1];\
    \
    # Stack all video layers
    [v0][v1]concat=n=2:v=1:a=0,format=yuv420p[vid_base];\
    \
    # Overlay animation on top with transparency
    [vid_base][2:v]overlay=0:0:enable='between(t,4,14)'[vid_anim];\
    \
    # Mix audio tracks
    [3:a]volume=1.0[anar];\
    [4:a]volume=0.25,adelay=0|0,apad[amus];\
    [5:a]volume=0.4[asfx];\
    [anar][amus][asfx]amix=inputs=3:duration=first[amix];\
  " \
  -map '[vid_anim]' -map '[amix]' \
  -c:v libx264 -preset slow -crf 18 \
  -c:a aac -b:a 192k \
  -pix_fmt yuv420p -r 30 \
  seg_001.mp4
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| Segment render fails (ffmpeg error) | Reduce preset to `ultrafast`, retry once |
| Concat fails (codec mismatch) | Re-encode all segments to consistent params |
| Single corrupt shot | Replace with fallback clip, re-render segment |
| Out of memory during render | Reduce segment duration, increase segment count |

### Caching

- Segment caching: if timeline unchanged, rendered segments are reusable
- Cache key for segments: `sha256(segment_json)`
- TTL: Until timeline changes

### Estimated Runtime

| Component | Time (4 cores) | Notes |
|-----------|----------------|-------|
| Segment assembly (prep) | ~5s | Deterministic, negligible |
| Parallel render (4 segments) | ~120-480s | 4 concurrent ffmpeg processes |
| Concatenation | ~5-15s | Lossless, very fast |
| **Total** | **~130-500s** | **2-8 min for 8 min video** |

**Comparison to V1:** V1 takes 30-60 min for 10 min video. V2 target: 3-8 min. **~4-10× speedup.**

### Memory Usage

| Item | Estimate |
|------|----------|
| ffmpeg process per segment | ~50-200 MB |
| 4 concurrent ffmpeg processes | ~200-800 MB |
| Segment MP4 (in flight) | ~100 MB |
| **Peak** | **~1 GB** |

### Oracle ARM Optimization

- **4 `ffmpeg` processes** simultaneously = full core utilization
- `-preset slow -crf 18` for quality; fallback to `ultrafast` if memory constrained
- `-threads 1` per ffmpeg process (one per core)
- Write segments to separate disk locations to avoid IO contention
- Use `/dev/shm` (tmpfs) for intermediate segment files if RAM permits
- `nice -n 10` ffmpeg to avoid starving the orchestrator process

### Parallelization

| Parallelism | Count | Strategy |
|-------------|-------|----------|
| Segment renders | 4 concurrent | ProcessPool (CPU-bound) |
| Concat | 1 | Sequential post-processing |

---

## 12. Pipeline Stage 9: Multi-Stage Video Critic

### Purpose

Replace the V1 single-frame Gemini critic with a comprehensive multi-stage review that checks visuals, audio, pacing, and subtitles.

### Critic Architecture

```
  RENDERED VIDEO
       │
       ▼
  ┌────────────────────────────────────────────┐
  │  1. VISUAL CRITIC (Gemini Multimodal)      │
  │     Extract 10 frames at key positions     │
  │     Check: black frames, watermarks,       │
  │     compression artifacts, letterboxing,   │
  │     resolution, composition                │
  └────────────────────────────────────────────┘
       │
       ▼
  ┌────────────────────────────────────────────┐
  │  2. AUDIO CRITIC (rule-based + DeepSeek)   │
  │     Check: LUFS loudness, true peak,       │
  │     clipping, silence gaps, narration      │
  │     volume consistency, pronunciation      │
  └────────────────────────────────────────────┘
       │
       ▼
  ┌────────────────────────────────────────────┐
  │  3. PACING CRITIC (DeepSeek + heuristics)  │
  │     Shot length histogram, transition      │
  │     diversity, emotion arc coherence,      │
  │     predicted retention curve              │
  └────────────────────────────────────────────┘
       │
       ▼
  ┌────────────────────────────────────────────┐
  │  4. AGGREGATION                           │
  │     Weighted scoring → overall_score       │
  │     Decision: approve / autofix / rebuild   │
  └────────────────────────────────────────────┘
```

### Inputs

| Field | Type | Source |
|-------|------|--------|
| Rendered video | MP4 file | Stage 8 |
| timeline_v2.json | JSON | Stage 5 |
| Critic thresholds | Config | `configs/critic.yaml` |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `VideoCriticReport` | Pydantic | ~5-20 KB |

### Python Module

**`src/critic/visual_critic.py`** — `VisualCritic` class.
**`src/critic/audio_critic.py`** — `AudioCritic` class.
**`src/critic/pacing_critic.py`** — `PacingCritic` class.

### Sub-Stage Details

#### 12.1 Visual Critic

```
1. Extract 10 frames at {5%, 15%, 25%, ..., 95%} of total duration
2. For each frame:
   a. ffmpeg blackdetect: black frame?
   b. ffprobe: detect letterboxing bars
   c. Gemini: "Describe any visual issues"
3. Aggregate: pass if >= 9/10 frames pass all checks
```

**Prompt Strategy (Gemini):**
```
You are a video quality inspector. Analyze this frame from a documentary video.
Report any issues you see. Be specific.

Check for:
- Black or nearly-black frames
- Letterboxing (black bars on any edge)
- Watermarks or logos
- Compression artifacts (blocky areas)
- Blurry or out-of-focus content
- Bad color (over/under exposed)

Frame timestamp: {time_position}s
Topic: {topic}
Expected content type: {scene_description}

Return JSON:
{
  "is_acceptable": true/false,
  "issues": ["..."],
  "issue_type": "black_frame" | "letterbox" | "watermark" | "artifact" | "blurry" | "color" | "none",
  "suggestion": "How to fix"
}
```

#### 12.2 Audio Critic

```
1. ffmpeg loudnorm: measure integrated LUFS, true peak
2. Detect silence gaps with pydub
3. Detect clipping (samples at max amplitude)
4. Compare measured values to thresholds:
   - LUFS: -14 to -18 (YouTube standard)
   - True peak: < -1 dBTP
   - Silence gaps: < 2 seconds
   - Clipping events: 0
5. Report any violations
```

#### 12.3 Pacing Critic

```
1. Parse timeline for shot durations
2. Compute: avg, median, std_dev, min, max
3. Count unique transition types
4. Track emotion changes across the video
5. Estimate retention: heuristic model based on:
   - Shot duration variance (more variety = better retention)
   - Transition diversity (more types = better)
   - Emotional arc completeness (start/end different emotions)
   - Scene length consistency
```

### Critic Scoring Rubric

| Dimension | Weight | Measure | Pass Threshold |
|-----------|--------|---------|---------------|
| Visual: frame quality | 25% | % frames passing | >= 90% |
| Visual: no black frames | 10% | blackdetect results | 0 black segments > 0.5s |
| Audio: loudness | 15% | Integrated LUFS | -14 to -18 |
| Audio: true peak | 5% | True peak dBTP | <= -1 |
| Audio: no clipping | 10% | Clipping events | 0 |
| Pacing: shot variety | 15% | Shot duration coefficient of variation | >= 0.3 |
| Pacing: transition diversity | 10% | Unique transition types | >= 3 |
| Pacing: emotional arc | 10% | Emotion change count | >= 3 |

**Overall score = weighted sum (0.0 - 1.0)**
- `>= 0.85`: approve
- `>= 0.70`: autofix (run improvement actions, recheck)
- `< 0.70`: rebuild (re-plan script or scenes)

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| Gemini API fails | Skip visual critic, use heuristic-only check |
| ffmpeg frame extraction fails | Retry with different timestamp |
| Audio file missing | Skip audio critic |

### Estimated Runtime

| Component | Time | Notes |
|-----------|------|-------|
| Frame extraction (10 frames) | ~2s | ffmpeg seek per frame |
| Gemini multi-frame review | ~15-30s | 10 frames sequentially |
| Audio analysis | ~3-8s | ffmpeg + pydub |
| Pacing analysis | ~1s | Heuristic |
| **Total** | **~20-40s** | |

### Memory Usage

| Item | Estimate |
|------|----------|
| 10 frame images | ~5 MB |
| Audio analysis buffer | ~50 MB |
| **Peak** | **~60 MB** |

### Oracle ARM Optimization

- Frame extraction uses ffmpeg fast seek (`-ss` before `-i`)
- Audio analysis is lightweight
- No parallelization needed (sequential stage)

---

## 13. Pipeline Stage 10: Self-Improvement Loop

### Purpose

When the critic finds issues, the system must fix them automatically. And across videos, the system must learn which strategies work and which don't.

### Inputs

| Field | Type | Source |
|-------|------|--------|
| `VideoCriticReport` | Pydantic | Stage 9 |
| `PipelineStateV2` | Pydantic | Current run |
| `timeline_v2.json` | JSON | Stage 5 |

### Outputs

| Output | Type | Size |
|--------|------|------|
| `list[ImprovementAction]` | Pydantic list | ~2 KB |
| Modified `timeline_v2.json` | JSON (updated) | Same size |

### Python Module

**`src/improvement/feedback_loop.py`** — `FeedbackLoop` class.
**`src/improvement/autofixer.py`** — `Autofixer` class.
**`src/improvement/cross_video_memory.py`** — `CrossVideoMemory` class.

### Algorithm

**Autofix (per-video loop):**

```
1. Parse critic issues
2. For each issue, check if autofixable:

   ISSUE: black frame at segment X
     ACTION: Replace segment X's first/second shot with fallback
     → re-render segment X with 2 concurrency
     → concat again
     → re-run visual critic (segment X only)

   ISSUE: audio too quiet (LUFS < -18)
     ACTION: Normalize audio track with ffmpeg loudnorm
     → Remux video with new audio
     → Re-run audio critic

   ISSUE: subtitles misaligned (>200ms drift)
     ACTION: Adjust subtitle timestamps by average drift
     → Re-run subtitle critic

   ISSUE: bad transition at scene boundary
     ACTION: Change transition type in timeline_v2.json
     → Re-render affected segments
     → Re-run visual critic

   ISSUE: pacing too slow
     ACTION: Reduce shot durations by 15%, increase transition frequency
     → Re-render affected segments
     → Re-run pacing critic

3. Max 2 autofix iterations per video
4. If still failing after autofix: mark as "needs human review"
```

**Cross-Video Learning:**
```
After each video:
1. Store in SQLite (cross_video_memory):
   - Research sources that provided the most facts
   - Provider success rates (which topics → which provider)
   - Script structures with high critic scores
   - Animation templates with fastest rendering
   - Music → emotion pairings that scored well
   - Shot duration ranges with best pacing scores
2. Update config defaults based on running averages
3. Flag topic categories needing research improvement
```

### Failure Recovery

| Failure Mode | Recovery |
|-------------|----------|
| Autofix makes things worse | Revert to pre-fix timeline, mark "needs human review" |
| Cross-video memory write fails | Log and continue (non-critical) |
| DB is corrupted | Reset cross-video memory |

### Estimated Runtime

| Component | Time | Notes |
|-----------|------|-------|
| Issue parsing | ~100ms | Deterministic |
| Autofix: segment re-render | ~60-120s | Per affected segment |
| Autofix: audio normalization | ~5-15s | Full audio re-encode |
| Cross-video memory write | ~200ms | SQLite insert |
| **Total** | **~5-120s** | Depends on fix count |

### Memory Usage

| Item | Estimate |
|------|----------|
| Memory store buffers | ~2 MB |
| **Peak** | **~10 MB** |

### Oracle ARM Optimization

- Re-renders are the expensive part — minimize with targeted segment re-renders
- Cross-video memory uses SQLite writes (disk, minimal CPU)

### Parallelization

Segments needing re-render can run in parallel (up to 4).

---

## 14. Hardware Optimization Guide

### 14.1 Memory Budget (24 GB Total)

| Layer | Min | Max | Notes |
|-------|-----|-----|-------|
| OS + system services | 256 MB | 512 MB | Oracle Cloud overhead |
| OpenClaw + Python interpreter | 64 MB | 128 MB | |
| Research stage (LLM responses) | 10 MB | 50 MB | Transient text data |
| Knowledge Graph + Scene data | 10 MB | 50 MB | Structured JSON |
| **Asset downloads (4 concurrent)** | 200 MB | 800 MB | Streaming, not full RAM |
| **Manim animation (1 process)** | 100 MB | 500 MB | Peak during render |
| **ffmpeg segment renders (4 concurrent)** | 200 MB | 800 MB | 50-200 MB per process |
| **Final concat + mixing** | 100 MB | 300 MB | |
| **Contingency / OS cache** | 5 GB | 20 GB | Free for disk cache |
| **TOTAL BUDGET** | **~6 GB** | **~20 GB** | Comfortable headroom |

**Key decisions:**
- Max 2 Manim processes (or 1 + 3 ffmpegs)
- Stream downloads to disk, never buffer entire file
- `/dev/shm` for temp files during rendering (up to 4 GB)
- Remove cache files after run to free space

### 14.2 CPU Budget (4 ARM Cores)

| Process | Cores | Priority | Notes |
|---------|-------|----------|-------|
| Download pool (4 threads) | 0 (IO) | Low | Threads, not processes |
| LLM API calls | 0 (IO) | Medium | Network-bound |
| Manim render | 1-2 | Medium | CPU-bound |
| Segment render (ffmpeg × 4) | 4 | High | CPU-bound |
| Final concat | 1 | Medium | IO-bound |
| Gemini critic | 0 (IO) | Low | Network-bound |

**Scheduling:**
- Asset download + Manim render can overlap (IO vs CPU)
- Segment render uses all 4 cores
- No process should use >4 threads

### 14.3 Disk Budget (~100 GB Available)

| Path | Max Size | Purpose |
|------|----------|---------|
| `cache/research/` | 1 GB | Research documents |
| `cache/knowledge/` | 500 MB | Knowledge graphs |
| `cache/narrative/` | 500 MB | Narrative arcs |
| `cache/assets/` | 10 GB | Downloaded video clips |
| `cache/animations/` | 5 GB | Rendered Manim scenes |
| `cache/segments/` | 20 GB | Render segment output |
| `cache/audio/` | 2 GB | TTS, music, SFX cache |
| `cache/memory.db` | 1 GB | SQLite memory store |
| `/dev/shm/` (tmpfs) | 4 GB | Temp render files |

**Total: ~44 GB**, leaving ~56 GB for OS + workspace + headroom.

### 14.4 Bottleneck Analysis

| Bottleneck | Severity | Mitigation |
|------------|----------|------------|
| **Manim rendering on ARM** | High | 4 cores × no GPU = slow animations. Limit 1-2 concurrent. Pre-render templates. Use `-pql` for draft. |
| **ffmpeg encoding** | Medium | 4× parallel with `-preset slow -crf 18` is acceptable. Fall back to `-preset fast -crf 23` if timing out. |
| **LLM API latency** | Medium | Each call 3-15s. Reduce call count via caching. Parallelize where possible. |
| **Asset download bandwidth** | Low | 4 concurrent downloads saturate most internet connections. |
| **RAM (24 GB)** | Low | Well within budget with streaming approach. |

---

## 15. Implementation Roadmap

### Design Principles for the Roadmap

1. **Every phase must produce a working system** that generates a video (even if not perfect).
2. **Every phase is independently commit-able** with passing tests.
3. **Earlier phases ship the biggest quality improvements** at lowest effort.
4. **No phase depends on a later phase** — each is a complete, testable unit.
5. **Breaking changes are minimized** — V1 code ported rather than rewritten.

### Phase 0: Port V1 Pipeline to V2 Package Layout (3-5 days)

**Goal:** The V1 pipeline runs under the V2 directory structure. No behavioral changes.

**Changes:**
- Create `src/models/v2_types.py` with all V2 models (backward-compat aliases for V1 models)
- Reorganize files into V2 package layout
- Port existing code with thin wrappers
- Ensure all existing tests pass

**Deliverable:** `run_pipeline.py` works identically to V1 but lives in V2 structure.

**Working system:** YES — same V1 output, new structure.

**Test gates:** All V1 tests pass.

---

### Phase 1: Parallel Segment Rendering (5-7 days)

**Goal:** Replace sequential MoviePy rendering with parallel ffmpeg segment rendering. This is the highest-ROI performance improvement.

**Changes:**
- Implement `SegmentRenderer` — parses `timeline_v1.json`, builds per-segment ffmpeg commands
- Implement `FinalRenderer` — ffmpeg concat of segments
- Implement `ProcessPool` parallel executor (4 workers)
- Create `src/render/` module
- Keep `MoviePyRenderer` as fallback for simple cases
- Add `timeline_v2.json` backward compat (convert V1 timeline to V2)

**Deliverable:** A 10-minute video renders in 3-8 min (vs 30-60 min in V1).

**Working system:** YES — V1 pipeline emits timeline, V2 renderer processes it.

**Test gates:**
- Segment ffmpeg commands are valid (run `ffmpeg -version` on generated command)
- Concatenated output is playable and correct duration
- Render time < 10 min for 10 min video

**Dependencies:** Phase 0 (package layout).

---

### Phase 2: Research Intelligence (5-7 days)

**Goal:** Replace single-shot LLM script generation with web-researched facts.

**Changes:**
- Implement `ResearchAgent` — web search → fact extraction
- Implement `FactVerifier` — cross-reference claims
- Implement `ResearchDocument` model
- Create `src/research/` module
- Integrate into pipeline as optional pre-processing step
- Cache layer: `cache/research/`

**Deliverable:** Scripts are generated from real sources with cited facts.

**Working system:** YES — pipeline works with or without research enabled.

**Test gates:**
- Research document contains at least 5 sources for known topics
- Fact extraction correctly identifies claims from content
- Cache hit/miss works correctly

**Dependencies:** Phase 0 (package layout).

---

### Phase 3: Knowledge Graph + Story Planner (5-7 days)

**Goal:** Design narrative structure from knowledge, not from scratch.

**Changes:**
- Implement `KnowledgeGraph` builder
- Implement `StoryPlannerV2` — narrative arc from KG
- Implement `NarrativeArc` + `NarrativeBeat` models
- Create `src/planner/` module (port V1 planner features)
- Integrate research → KG → story → scenes pipeline

**Deliverable:** The pipeline produces structured story arcs with hooks, tension curves, and logical scene ordering.

**Working system:** YES — falls back to V1 planner if KG/Narrative not available.

**Test gates:**
- Knowledge graph correctly extracts entities and relationships
- Story planner produces valid NarrativeArc with beats
- Fallback to V1 planner works when KG is empty

**Dependencies:** Phase 2 (research).

---

### Phase 4: timeline_v2.json + Visual Planner (5-7 days)

**Goal:** Complete the intelligence-to-production bridge. Visual plan is derived from knowledge and narrative, not from script text.

**Changes:**
- Implement `VisualPlannerV2` — shot classification + query generation
- Implement full `timeline_v2.json` schema
- Implement shot classification (stock vs animation vs text vs map)
- Implement `VisualPlan` model
- Create `src/planner/visual_planner.py`
- Write `timeline_v2.json` schema validator

**Deliverable:** `timeline_v2.json` is the single source of truth for all downstream stages.

**Working system:** YES — converts V1 scenes to timeline_v2 if V2 data missing.

**Test gates:**
- timeline_v2.json validates against schema
- Shot classification correctly identifies animation-needing segments
- All V1 scene types are convertible to timeline_v2 format

**Dependencies:** Phase 3 (KG + story).

---

### Phase 5: Asset Acquisition Engine (5-7 days)

**Goal:** Robust, cached, parallel asset acquisition that fulfills timeline_v2 stock video shots.

**Changes:**
- Implement `AssetOrchestrator` — coordinates the full asset pipeline
- Implement `StockSearcher` — multi-provider search (port V1 router)
- Implement `AssetCache` — SQLite + disk cache
- Port: Pexels, Pixabay, NASA, Wikimedia providers from V1
- Parallel download management

**Deliverable:** Assets are acquired in parallel with caching, ~3-4× faster than V1.

**Working system:** YES — falls back to V1 asset router if V2 cache missing.

**Test gates:**
- Provider chain produces results for known queries
- Cache hit returns without network call
- 4 concurrent downloads complete without errors
- Fallback chain produces non-black result

**Dependencies:** Phase 4 (timeline_v2).

---

### Phase 6: Manim Animation Engine (initial — 2-3 weeks)

**Goal:** Add procedural 2D animation capability for abstract concepts.

**Changes:**
- Install/configure Manim Community Edition
- Implement `ManimRunner` — wraps manim CLI
- Implement `TemplateLibrary` — 5 initial templates (text_reveal, comparison_bars, zoom_diagram, timeline_chart, simple_particles)
- Implement `DataVizRender` — matplotlib + ffmpeg
- Create `src/animation/` module
- Integrate animation jobs into asset pipeline
- Max 2 concurrent Manim processes

**Deliverable:** Narrations about abstract concepts get animated visuals instead of irrelevant stock footage.

**Working system:** YES — falls back to text overlay if animation not available.

**Test gates:**
- Each template produces valid MP4
- Manim output integrates into ffmpeg overlay pipeline
- Fall back to text_overlay on Manim failure

**Dependencies:** Phase 0 (package layout), Phase 4 (timeline_v2 enables animation assignment).

---

### Phase 7: Audio Engine Upgrade (3-5 days)

**Goal:** Multi-track audio with per-scene music selection + sound effects.

**Changes:**
- Implement `MusicLibrary` — emotion-tagged CC music collection
- Implement `AudioMixer` — multi-track mixing with dynamic ducking
- Implement SFX trigger system (transition whooshes, emphasis stings)
- Port TTS from V1 (already good)
- Create `src/audio/` module

**Deliverable:** Professional-quality audio with emotional variety.

**Working system:** YES — falls back to V1 simple mixing if library empty.

**Test gates:**
- Music selected per emotion from library
- Ducking reduces during narration
- SFX triggered at transitions

**Dependencies:** Phase 0, Phase 4 (timeline_v2 audio segments).

---

### Phase 8: Multi-Stage Video Critic (5-7 days)

**Goal:** Replace single-frame critic with comprehensive multi-stage review.

**Changes:**
- Implement `VisualCritic` — Gemini multi-frame QA
- Implement `AudioCritic` — ffmpeg loudness + silence analysis
- Implement `PacingCritic` — shot length analysis
- Implement `VideoCriticReport` aggregation
- Port V1 critic node functionality
- Create `src/critic/` module

**Deliverable:** Post-render review catches black frames, audio issues, pacing problems.

**Working system:** YES — falls back to V1 simple critic if Gemini unavailable.

**Test gates:**
- Visual critic correctly identifies black frames (test with known-bad video)
- Audio critic correctly measures LUFS ± 1 dB
- Pacing critic produces consistent scores for same input

**Dependencies:** Phase 1 (segment render produces playable video).

---

### Phase 9: Self-Improvement Loop (5-7 days)

**Goal:** Auto-fix common issues and learn across videos.

**Changes:**
- Implement `Autofixer` — segment re-render, audio normalize, subtitle adjust
- Implement `CrossVideoMemory` — SQLite store for cross-video learning
- Implement `FeedbackLoop` — aggregate issues → decide actions → execute
- Create `src/improvement/` module

**Deliverable:** Pipeline automatically fixes ~80% of common issues without human intervention.

**Working system:** YES — issues are just logged if autofix disabled.

**Test gates:**
- Autofix correctly replaces a black frame segment
- Cross-video memory stores and retrieves topic → provider mapping
- Max 2 fix iterations enforced

**Dependencies:** Phase 8 (critic), Phase 1 (segment re-render).

---

### Phase 10: Production Polish + Templates (ongoing, 2-4 weeks)

**Goal:** Polish everything for production use.

**Changes:**
- Thumbnail generation (imagemagick overlay)
- YouTube metadata generation (title, description, tags, timestamps)
- YouTube upload integration (Data API v3)
- Expand Manim template library (10+ templates)
- Performance tuning: benchmark each stage
- Error handling: comprehensive coverage
- Logging: structured, OpenClaw-friendly
- Memory profiling: ensure 24 GB is never exceeded
- cron job integration for automatic daily batch processing

**Deliverable:** Production-ready autonomous YouTube documentary engine.

**Working system:** YES — full pipeline end to end.

**Test gates:**
- End-to-end pipeline produces watchable 8-10 min video
- Thumbnail is visually appealing
- Metadata is valid YouTube format
- Pipeline can run unattended

**Dependencies:** Phases 1-9.

---

### Implementation Timeline (Realistic)

```
PHASE 0: Port to V2 layout            ████████░░░░  3-5 days
PHASE 1: Parallel rendering            ████████████  5-7 days
PHASE 2: Research intelligence         ████████████  5-7 days
PHASE 3: Knowledge graph + story       ████████████  5-7 days
PHASE 4: timeline_v2 + visual plan     ████████████  5-7 days
PHASE 5: Asset acquisition engine      ████████████  5-7 days
PHASE 6: Manim animation engine        ██████████████████████  2-3 weeks
PHASE 7: Audio engine upgrade          ████████░░░  3-5 days
PHASE 8: Multi-stage critic            ████████████  5-7 days
PHASE 9: Self-improvement loop         ████████████  5-7 days
PHASE 10: Production polish            ██████████████████████████  2-4 weeks
                                      ─────────────────────────────────
                                    TOTAL: ~10-14 weeks
```

**After Phase 1:** Pipeline is 4-10× faster. This is the highest-priority improvement.
**After Phase 3:** Scripts have real research backing. This is the biggest quality jump.
**After Phase 6:** Abstract concepts get real visuals. This is the biggest capability jump.
**After Phase 9:** Pipeline runs autonomously with self-healing. This is the maturity milestone.
**After Phase 10:** Production-ready for unattended daily operation.

---

### Quick Start: Minimum Viable V2

For a team that wants a *working V2 in 3 weeks*, implement these phases:

1. **Phase 0** (3 days) — new layout, V1 still runs
2. **Phase 1** (5 days) — parallel rendering (4-10× speedup)
3. **Phase 2** (5 days) — research (better scripts)
4. **Phase 4** (5 days) — timeline_v2 (foundation for everything)

**After 3 weeks:** Faster rendering with research-backed scripts and the V2 timeline. This is a solid foundation. Phases 3, 5-10 add improvements on top without breaking anything.
