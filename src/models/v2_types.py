"""
v2_types.py — All V2 Pydantic models for the intelligence-first pipeline.

Every stage communicates through typed models. No ad-hoc dicts across
module boundaries.

This module is additive — it does not modify any existing V1 types.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


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
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


# ── Stage 1-2: Research Intelligence ─────────────────────────────────────


class Source(BaseModel):
    """A single source discovered during web research."""

    url: str = ""
    title: str = ""
    domain: str = ""
    snippet: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class Fact(BaseModel):
    """A factual claim extracted from one or more sources."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    claim: str
    sources: list[Source] = []
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    category: str = "general"
    verified: bool = False
    verification_notes: str = ""


class ResearchDocument(BaseModel):
    """Structured research output for a single topic.

    Produced by ResearchAgent and consumed by KnowledgeGraphBuilder.
    """

    topic: str
    sources: list[Source] = []
    key_facts: list[Fact] = []
    key_statistics: list[str] = []
    key_dates: list[dict] = Field(default_factory=list)
    key_people: list[str] = []
    controversies: list[str] = []
    timelines: list[dict] = Field(default_factory=list)
    unanswered_questions: list[str] = []


class KnowledgeNode(BaseModel):
    """A single node in the knowledge graph."""

    id: str
    label: str
    type: str  # "concept", "person", "event", "place", "date", "stat"
    description: str = ""


class KnowledgeEdge(BaseModel):
    """A directed relationship between two knowledge nodes."""

    source_id: str
    target_id: str
    relationship: str  # "causes", "contradicts", "supports", "precedes", etc.


class KnowledgeGraph(BaseModel):
    """Structured knowledge graph of concepts, people, events and their relationships."""

    nodes: list[KnowledgeNode] = []
    edges: list[KnowledgeEdge] = []
    topic: str = ""


# ── Stage 3: Story Planning ─────────────────────────────────────────────


class NarrativeBeat(BaseModel):
    """A single beat in the narrative arc."""

    index: int
    role: NarrativeRole
    hook_sentence: str = ""
    core_message: str = ""
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    knowledge_node_ids: list[str] = []
    target_duration_range: tuple[float, float] = (45.0, 120.0)
    cliffhanger: str = ""


class NarrativeArc(BaseModel):
    """Complete narrative arc for a video."""

    topic: str
    title: str = ""
    subtitle: str = ""
    logline: str = ""
    beats: list[NarrativeBeat] = []
    total_target_duration: float = 480.0
    narrative_framework: str = "mystery_reveal"


# ── Stage 4: Scene Planning ─────────────────────────────────────────────


class SceneDialogue(BaseModel):
    """A single segment of spoken narration within a scene."""

    speaker: str = "narrator"
    text: str
    emphasis_words: list[str] = []


class SceneV2(BaseModel):
    """A single scene in the V2 pipeline."""

    scene_id: int
    title: str
    narration_segments: list[SceneDialogue]
    emotional_tone: EmotionalTone = EmotionalTone.NEUTRAL
    target_duration: float
    scene_purpose: str = ""
    transition_in: TransitionType = TransitionType.CROSSFADE
    transition_out: TransitionType = TransitionType.CROSSFADE
    knowledge_ids: list[str] = []
    music_emotion: str = "ambient"


# ── Stage 5: Visual Planning ────────────────────────────────────────────


class VisualQuery(BaseModel):
    """Search query for a single shot."""

    query: str
    query_variants: list[str] = []
    provider_priority: list[str] = []


class CameraDirection(BaseModel):
    """Camera motion and zoom parameters for a shot."""

    motion: CameraMotion = CameraMotion.STATIC
    zoom_start: float = 1.0
    zoom_end: float = 1.0
    pan_x: int = 0
    pan_y: int = 0


class ShotV2(BaseModel):
    """A single shot in the V2 timeline."""

    shot_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    scene_id: int
    beat_index: int = 0
    shot_index: int = 0
    shot_type: ShotType
    start_ms: float
    end_ms: float
    narration_indices: list[int] = []
    visual_query: Optional[VisualQuery] = None
    camera: CameraDirection = CameraDirection()
    transition_in: TransitionType = TransitionType.CROSSFADE
    transition_out: TransitionType = TransitionType.CROSSFADE
    animation_template: str = ""
    animation_params: dict = {}


class ColorGrade(BaseModel):
    """Color grading parameters for a shot or global."""

    saturation: float = 1.0
    contrast: float = 1.0
    brightness: float = 0.0
    temperature: float = 5600.0


class SubtitleLine(BaseModel):
    """A single subtitle line with optional word-level timing."""

    start_ms: float
    end_ms: float
    text: str
    words: list[dict] = []


class SceneAudioPlan(BaseModel):
    """Audio mixing plan for a single scene."""

    narration_path: str = ""
    music_path: str = ""
    music_volume_db: float = -18.0
    ducking_enabled: bool = True
    ducking_reduction_db: float = 10.0
    ducking_attack_ms: int = 200
    ducking_release_ms: int = 500
    sound_effects: list[dict] = []


class VisualPlan(BaseModel):
    """Complete visual plan — the production spec."""

    scenes: list[SceneV2] = []
    shots: list[ShotV2] = []
    subtitles: list[SubtitleLine] = []
    global_color_grade: ColorGrade = ColorGrade()
    timeline_version: str = "2.0"
    render_settings: dict = {"resolution": [1920, 1080], "fps": 30}
    video_id: str = ""


# ── Stage 6-7: Asset & Animation Models ─────────────────────────────────


class AssetRecord(BaseModel):
    """A single acquired asset (stock footage or animation)."""

    shot_id: str
    provider: AssetProvider = AssetProvider.EMERGENCY
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
    """A single animation render job."""

    job_id: str
    template_name: str
    params: dict = {}
    output_path: str = ""
    estimated_runtime_s: float = 30.0
    priority: int = 5


class SegmentRenderJob(BaseModel):
    """A single segment render job (one ffmpeg invocation)."""

    segment_id: str
    start_ms: float
    end_ms: float
    shots: list[AssetRecord] = []
    narration_path: str = ""
    music_path: str = ""
    sfx: list[dict] = []
    subtitles: list[SubtitleLine] = []
    output_path: str = ""
    codec: str = "libx264"
    crf: int = 18
    preset: str = "slow"


# ── Stage 9: Critic Models ──────────────────────────────────────────────


class CriticIssue(BaseModel):
    """A single issue identified by a critic."""

    severity: CriticSeverity
    category: str
    description: str
    location: dict = {}
    suggestion: str = ""


class VisualCriticResult(BaseModel):
    """Result from the visual critic."""

    frames_checked: int = 10
    frames_passed: int = 0
    frames_failed: int = 0
    pass_rate: float = 0.0
    issues: list[CriticIssue] = []


class AudioCriticResult(BaseModel):
    """Result from the audio critic."""

    integrated_lufs: float = 0.0
    true_peak_db: float = 0.0
    silence_gaps: list[dict] = []
    clipping_events: list[dict] = []
    issues: list[CriticIssue] = []


class PacingCriticResult(BaseModel):
    """Result from the pacing critic."""

    avg_shot_duration: float = 0.0
    shot_duration_variance: float = 0.0
    transition_diversity: int = 0
    predicted_retention_score: float = 0.0
    issues: list[CriticIssue] = []


class VideoCriticReport(BaseModel):
    """Complete critic report for a video."""

    video_id: str
    visual: VisualCriticResult = VisualCriticResult()
    audio: AudioCriticResult = AudioCriticResult()
    pacing: PacingCriticResult = PacingCriticResult()
    overall_score: float = 0.0
    recommended_action: str = "approve"


# ── Stage 10: Improvement Models ────────────────────────────────────────


class ImprovementAction(BaseModel):
    """A single improvement action to fix a detected issue."""

    action_type: str  # "rerender_segment", "replace_asset", "adjust_audio", "rebuild_script"
    target: str = ""
    params: dict = {}
    priority: int = 5
    estimated_time_s: float = 30.0


# ── Pipeline State ──────────────────────────────────────────────────────


class PipelineStateV2(BaseModel):
    """Complete state of a V2 pipeline run."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str
    category: TopicCategory = TopicCategory.GENERAL
    status: str = "initialized"

    research_document: Optional[ResearchDocument] = None
    knowledge_graph: Optional[KnowledgeGraph] = None
    narrative_arc: Optional[NarrativeArc] = None
    scenes: list[SceneV2] = []
    visual_plan: Optional[VisualPlan] = None
    acquired_assets: list[AssetRecord] = []
    animation_jobs: list[AnimationJob] = []
    segment_jobs: list[SegmentRenderJob] = []
    rendered_segments: list[str] = []

    critic_report: Optional[VideoCriticReport] = None
    improvement_actions: list[ImprovementAction] = []

    started_at: float = 0.0
    stages_elapsed: dict[str, float] = {}

    iteration: int = 0
    max_iterations: int = 3
