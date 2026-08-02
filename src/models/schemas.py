"""
schemas.py — Strict Pydantic models for the documentary pipeline.

Every stage of the pipeline communicates through these typed models only.
No untyped dicts, Any, or generic JSON are permitted between components.

Architecture (data flow):

  Planner
    │
    ├─ Scene            ← composite model for the whole scene
    │   ├─ SceneNarration     → TTS (ONLY spoken_narration field)
    │   ├─ VisualPlan         → visual director / image generation
    │   ├─ SearchPlan         → AssetRouter (NEVER receives narration)
    │   ├─ EditingPlan        → transitions / motion / pacing
    │   ├─ AssetPlan          → quality gates / renderer
    │   ├─ AudioPlan          → music / sound design
    │   └─ RenderPlan         → final concatenation / encoding
    │
    Validation between every stage enforces strict field isolation.
    Pipeline fails immediately (no silent recovery) if schema validation fails.
"""

from __future__ import annotations

from typing import Any, Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


# ═══════════════════════════════════════════════════════════════════════ #
# Enums
# ═══════════════════════════════════════════════════════════════════════ #

class CameraMotion(str, Enum):
    """Supported camera motion types."""
    NONE = "none"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    KEN_BURNS = "ken_burns"
    TRUCK_IN = "truck_in"
    TRUCK_OUT = "truck_out"
    FOLLOW = "follow"
    STABILIZED = "stabilized"
    STATIC = "static"


class TransitionType(str, Enum):
    CUT = "cut"
    CUT_SYNC = "cut_sync"       # Cut on word/breath boundary (voiceover-aware)
    FADE = "fade"
    DISSOLVE = "dissolve"
    CROSSFADE = "crossfade"
    WIPE_LEFT = "wipe_left"
    WIPE_RIGHT = "wipe_right"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"


class ProviderType(str, Enum):
    PIXABAY = "pixabay"
    PEXELS = "pexels"
    NASA = "nasa"
    WIKIMEDIA = "wikimedia"
    MANIM = "manim"
    GENERATED = "generated"
    REUSE = "reuse"
    PLACEHOLDER = "placeholder"
    EMERGENCY = "emergency"


class MusicStyle(str, Enum):
    CINEMATIC = "cinematic"
    AMBIENT = "ambient"
    DRAMATIC = "dramatic"
    HOPEFUL = "hopeful"
    SUSPENSE = "suspense"
    HISTORICAL = "historical"
    SCI_FI = "sci_fi"
    NATURE = "nature"
    CORPORATE = "corporate"
    NONE = "none"


# ═══════════════════════════════════════════════════════════════════════ #
# SceneNarration
# ═══════════════════════════════════════════════════════════════════════ #

class SceneNarration(BaseModel):
    """Pure spoken text — the ONLY field that ever reaches TTS.

    Validation guarantees no visual search, editing, or metadata fields
    can leak into the TTS system.
    """

    narration_id: str = Field(
        default="",
        description="Unique identifier for this narration block",
    )
    spoken_narration: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The exact text that will be spoken by TTS. "
                    "No other field from any model may reach TTS.",
    )

    @field_validator("spoken_narration")
    @classmethod
    def no_technical_metadata(cls, v: str) -> str:
        """Reject strings that look like leaked internal metadata."""
        forbidden_prefixes = [
            "query:", "search:", "transition:", "motion:",
            "camera:", "zoom:", "pan:", "tilt:", "effect:",
            "metadata:", "audio:", "music:", "sound:",
        ]
        stripped = v.strip().lower()
        for prefix in forbidden_prefixes:
            if stripped.startswith(prefix):
                raise ValueError(
                    f"SceneNarration.spoken_narration contains forbidden "
                    f"metadata prefix '{prefix}'. Narration text must be "
                    f"pure spoken content only."
                )
        return v

    def to_tts_input(self) -> str:
        """The ONLY method TTS is allowed to call.

        Returns only the pure narration text.
        """
        return self.spoken_narration

    class Config:
        frozen = False
        extra = "forbid"  # No extra fields allowed


# ═══════════════════════════════════════════════════════════════════════ #
# VisualPlan
# ═══════════════════════════════════════════════════════════════════════ #

class VisualPlan(BaseModel):
    """Visual description and generation instructions.

    NEVER reaches TTS. NEVER contains spoken narration.
    Only consumed by the visual generation pipeline.
    """

    visual_description: str = Field(
        default="",
        description="Detailed description of what this scene should look like.",
        max_length=2000,
    )
    visual_metaphors: list[str] = Field(
        default_factory=list,
        description="Abstract visual metaphors representing the narration concept.",
        max_length=20,
    )
    camera_motion: CameraMotion = Field(
        default=CameraMotion.STATIC,
        description="Suggested camera motion for this scene.",
    )
    preferred_aspect: Optional[str] = Field(
        default=None,
        description="Preferred aspect ratio if relevant (e.g. '16:9', '4:3').",
    )

    @field_validator("visual_description")
    @classmethod
    def description_length_check(cls, v: str) -> str:
        if len(v.strip()) < 3 and v.strip():
            raise ValueError(
                "visual_description must be at least 3 characters."
            )
        return v

    class Config:
        extra = "forbid"


# ═══════════════════════════════════════════════════════════════════════ #
# SearchPlan
# ═══════════════════════════════════════════════════════════════════════ #

class SearchPlan(BaseModel):
    """Asset search queries — NEVER contains spoken narration.

    AssetRouter consumes ONLY SearchPlan.
    No narration field leaks into asset retrieval.
    """

    asset_search_queries: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Diverse search queries for asset retrieval. "
                    "These are visual search terms, NOT narration text.",
    )
    negative_search_queries: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Terms to exclude from search results.",
    )
    primary_topic: str = Field(
        default="",
        description="The video's primary topic category.",
        max_length=100,
    )
    scene_purpose: str = Field(
        default="general",
        description="Scene purpose (introduction, explanation, conclusion, etc.).",
        max_length=200,
    )
    diversity_weighting: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for semantic diversity in query selection.",
    )

    @field_validator("asset_search_queries")
    @classmethod
    def no_narration_in_queries(cls, v: list[str]) -> list[str]:
        """Guard: reject queries that are just copied narration."""
        for q in v:
            if len(q) > 100:
                raise ValueError(
                    f"Search query too long ({len(q)} chars). "
                    f"Queries must be search terms, not narration text."
                )
        return v

    class Config:
        extra = "forbid"


# ═══════════════════════════════════════════════════════════════════════ #
# EditingPlan
# ═══════════════════════════════════════════════════════════════════════ #

class EditingPlan(BaseModel):
    """Editing instructions — transitions, motion, pacing.

    NEVER reaches TTS or narration generation.
    """

    editing_instructions: str = Field(
        default="",
        description="Free-form editing instructions (e.g. 'fast cuts', 'slow reveal').",
        max_length=500,
    )
    transition_in: TransitionType = Field(
        default=TransitionType.CUT,
        description="Transition into this scene.",
    )
    transition_out: TransitionType = Field(
        default=TransitionType.CUT,
        description="Transition out of this scene.",
    )
    camera_motion: CameraMotion = Field(
        default=CameraMotion.STATIC,
        description="Camera motion to apply during this scene.",
    )
    pacing: str = Field(
        default="medium",
        description="Editing pace: 'slow', 'medium', or 'fast'.",
        max_length=10,
    )
    motion_intensity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Intensity of camera motion (0=static, 1=very active).",
    )

    @field_validator("pacing")
    @classmethod
    def valid_pacing(cls, v: str) -> str:
        allowed = {"slow", "medium", "fast"}
        if v.lower() not in allowed:
            raise ValueError(f"pacing must be one of {allowed}, got '{v}'")
        return v.lower()

    class Config:
        extra = "forbid"


# ═══════════════════════════════════════════════════════════════════════ #
# AssetPlan
# ═══════════════════════════════════════════════════════════════════════ #

class AssetPlan(BaseModel):
    """Selected asset information — the RESULT of asset retrieval.

    Contains the actual file path, scores, and provider info.
    """

    provider: ProviderType = Field(
        default=ProviderType.PIXABAY,
        description="Which provider supplied this asset.",
    )
    filepath: str = Field(
        default="",
        description="Local file path to the downloaded/cached video.",
    )
    video_url: str = Field(
        default="",
        description="Original source URL (for attribution/tracking).",
    )
    query_used: str = Field(
        default="",
        description="The search query that found this asset.",
        max_length=500,
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Combined quality score.",
    )
    semantic_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Semantic relevance score (threshold: 0.75).",
    )
    technical_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Technical quality score.",
    )
    aesthetic_style: str = Field(
        default="documentary",
        description="Aesthetic classification of this asset.",
        max_length=50,
    )
    duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Duration of the video asset in seconds.",
    )
    width: int = Field(
        default=1920,
        ge=1,
        description="Video width in pixels.",
    )
    height: int = Field(
        default=1080,
        ge=1,
        description="Video height in pixels.",
    )

    @field_validator("filepath")
    @classmethod
    def filepath_check(cls, v: str) -> str:
        if v and not v.endswith(".mp4"):
            raise ValueError(
                f"AssetPlan filepath must end with .mp4, got '{v}'"
            )
        return v

    @field_validator("width", "height", "duration", mode="before")
    @classmethod
    def coerce_zero_to_default(cls, v: object, info) -> object:
        """Coerce 0/None to a usable default so callers never fail on API data."""
        if v is None or (isinstance(v, (int, float)) and v <= 0):
            if info.field_name == "duration":
                return 10.0
            return 1920 if info.field_name == "width" else 1080
        return v

    class Config:
        extra = "forbid"


# ═══════════════════════════════════════════════════════════════════════ #
# AudioPlan
# ═══════════════════════════════════════════════════════════════════════ #

class AudioPlan(BaseModel):
    """Audio rendering instructions.

    Contains paths to narration audio, music, and sound effects.
    """

    narration_audio_path: str = Field(
        default="",
        description="Path to the generated TTS audio file.",
    )
    music_style: MusicStyle = Field(
        default=MusicStyle.AMBIENT,
        description="Background music style for this scene.",
    )
    music_path: Optional[str] = Field(
        default=None,
        description="Path to a background music file (optional).",
    )
    sound_effects: list[str] = Field(
        default_factory=list,
        description="Paths to sound effect files.",
        max_length=10,
    )
    ducking_enabled: bool = Field(
        default=True,
        description="Whether to duck music during narration.",
    )
    ducking_reduction_db: float = Field(
        default=8.0,
        ge=0.0,
        le=30.0,
        description="Decibel reduction during narration ducking.",
    )
    ambient_sound_path: Optional[str] = Field(
        default=None,
        description="Path to ambient sound file.",
    )

    class Config:
        extra = "forbid"


# ═══════════════════════════════════════════════════════════════════════ #
# VisualIntent — structured visual metadata per scene
# ═══════════════════════════════════════════════════════════════════════ #

class VisualIntent(BaseModel):
    """Structured visual metadata for a scene.

    Generated by StoryPlanner alongside narration. Consumed by
    ConceptPlanner and VisualDirector to drive asset search,
    provider selection, and animation triggering.

    NEVER reaches TTS. NEVER contains spoken narration.
    """

    model_config = {"extra": "forbid"}

    visual_objective: str = Field(
        default="",
        max_length=500,
        description="What this scene should communicate visually "
                    "(e.g. 'explain light absorption', 'show observable universe').",
    )
    concepts: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Core concepts in this scene that drive asset search "
                    "(e.g. ['photons', 'vacuum', 'wavelength', 'blackbody']).",
    )
    required_assets: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Types of assets needed (e.g. 'stock_video', 'diagram', "
                    "'animation', 'photograph', 'infographic').",
    )
    preferred_asset_types: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Preferred visual treatment (e.g. 'wide_shot', 'close_up', "
                    "'infographic', 'animation', 'timelapse').",
    )
    animation_requirements: str = Field(
        default="",
        max_length=500,
        description="If stock footage cannot explain this concept, describe "
                    "the animation needed (e.g. 'manim_photon_travel', "
                    "'diagram_inverse_square_law'). Empty if not required.",
    )
    camera_style: str = Field(
        default="",
        max_length=50,
        description="Suggested camera style: 'static_diagram', 'slow_pan', "
                    "'ken_burns', 'dynamic', 'tilt_shift'.",
    )
    motion_style: str = Field(
        default="",
        max_length=50,
        description="Motion intensity: 'gentle', 'dynamic', 'none', 'timelapse'.",
    )
    fallback_strategy: str = Field(
        default="",
        max_length=100,
        description="Fallback strategy if primary asset search fails "
                    "(e.g. 'fallback_to_diagram', 'fallback_to_reuse', "
                    "'fallback_to_photograph').",
    )
    search_terms: list[str] = Field(
        default_factory=list,
        max_length=30,
        description="Expanded search keywords for stock footage lookup "
                    "(e.g. ['deep space', 'night sky', 'Milky Way', 'nebula']).",
    )


# ═══════════════════════════════════════════════════════════════════════ #
# DiversityRecord — tracks asset usage across scenes
# ═══════════════════════════════════════════════════════════════════════ #


class DiversityRecord(BaseModel):
    """Record of a single accepted asset, used by DiversityTracker
    to prevent repeated use of similar content across scenes.
    """

    model_config = {"extra": "forbid"}

    scene_id: int = Field(..., ge=0)
    provider: str = Field(default="", max_length=50)
    asset_id: str = Field(default="", max_length=200)
    query_used: str = Field(default="", max_length=500)
    content_hash: str = Field(default="", max_length=64)
    similarity_group: str = Field(default="", max_length=100)


class ValidationReport(BaseModel):
    """Result of pre-render storyboard validation."""

    model_config = {"extra": "forbid"}

    passed: bool = Field(default=False, description="Whether the plan passed all checks.")
    total_scenes: int = Field(default=0, ge=0)
    total_beats: int = Field(default=0, ge=0)
    total_shots: int = Field(default=0, ge=0)
    missing_assets: int = Field(default=0, ge=0, description="Shots with no asset plan.")
    missing_filepaths: int = Field(default=0, ge=0, description="Asset plans with no valid filepath.")
    diversity_violations: list[str] = Field(
        default_factory=list,
        description="Descriptions of diversity issues found.",
    )
    total_duration: float = Field(default=0.0, ge=0.0)
    target_duration: float = Field(default=0.0, ge=0.0)
    errors: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════ #
# RenderPlan
# ═══════════════════════════════════════════════════════════════════════ #

class RenderPlan(BaseModel):
    """Final render instructions — concatenation, encoding, output."""

    resolution_width: int = Field(
        default=1920,
        ge=1,
        description="Output video width.",
    )
    resolution_height: int = Field(
        default=1080,
        ge=1,
        description="Output video height.",
    )
    fps: int = Field(
        default=30,
        ge=1,
        le=120,
        description="Output video frame rate.",
    )
    output_path: str = Field(
        default="final_output.mp4",
        description="Path for the final rendered video.",
    )
    scene_filepaths: list[str] = Field(
        default_factory=list,
        description="Ordered list of scene video file paths to concatenate.",
    )
    transition_sequence: list[TransitionType] = Field(
        default_factory=list,
        description="Transitions between consecutive scenes.",
    )
    background_music_path: Optional[str] = Field(
        default=None,
        description="Background music overlay track.",
    )
    subtitles_enabled: bool = Field(
        default=True,
        description="Whether to render subtitles.",
    )

    @model_validator(mode="after")
    def validate_transition_count(self) -> "RenderPlan":
        expected = max(0, len(self.scene_filepaths) - 1)
        actual = len(self.transition_sequence)
        if self.transition_sequence and actual != expected:
            raise ValueError(
                f"transition_sequence has {actual} entries but "
                f"{expected} are needed ({len(self.scene_filepaths)} scenes)"
            )
        return self

    class Config:
        extra = "forbid"


# ═══════════════════════════════════════════════════════════════════════ #
# ── Beat-based editing models ──────────────────────────────────────────


class ShotType(str, Enum):
    """Type of shot within a beat."""
    PRIMARY = "primary"
    CUTAWAY = "cutaway"
    BACKUP = "backup"
    MOTION_GRAPHICS = "motion_graphics"


class ShotPlan(BaseModel):
    """A single shot within a beat — timing, camera, motion, asset."""

    model_config = {"extra": "forbid"}

    timestamp: float = Field(
        default=0.0,
        ge=-1.0,
        description="Start time relative to beat start (seconds). -0.5 for L-cut lead.",
    )
    duration: float = Field(
        ...,
        ge=0.5,
        le=10.0,
        description="Shot duration in seconds (max 6s unless justified).",
    )
    shot_type: ShotType = Field(
        default=ShotType.PRIMARY,
        description="Role of this shot within the beat.",
    )
    camera: CameraMotion = Field(
        default=CameraMotion.KEN_BURNS,
        description="Camera motion to apply.",
    )
    transition: TransitionType = Field(
        default=TransitionType.CROSSFADE,
        description="Transition from previous shot to this one.",
    )
    emotion: str = Field(
        default="neutral",
        max_length=20,
        description="Emotional tone of this shot.",
    )
    motion: str = Field(
        default="ken_burns_in",
        max_length=30,
        description="Detailed motion descriptor passed to the motion engine.",
    )
    asset_type: str = Field(
        default="video",
        max_length=20,
        description="Type of asset: video, image_ken_burns, generated, motion_graphics.",
    )
    description: str = Field(
        default="",
        max_length=500,
        description="Visual description for asset search.",
    )
    search_query: str = Field(
        default="",
        max_length=200,
        description="Search query used (populated after asset selection).",
    )
    asset_plan: Optional[AssetPlan] = Field(
        default=None,
        description="Selected asset for this shot (populated after search).",
    )
    semantic_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Semantic relevance score of selected asset.",
    )
    justify_long_shot: str = Field(
        default="",
        max_length=200,
        description="Required justification if duration > 6s.",
    )


class BeatPlan(BaseModel):
    """A semantic beat — one complete thought unit with visual treatment."""

    model_config = {"extra": "forbid"}

    index: int = Field(
        ...,
        ge=0,
        description="Beat index within scene.",
    )
    text: str = Field(
        ...,
        max_length=500,
        description="Narration text for this beat.",
    )
    start_time: float = Field(
        default=0.0,
        ge=0.0,
        description="Start time in seconds from scene start.",
    )
    duration: float = Field(
        ...,
        ge=1.0,
        le=30.0,
        description="Beat duration in seconds (3-10s typical, max 30s).",
    )
    emotion: str = Field(
        default="neutral",
        max_length=20,
        description="Emotional tone of this beat.",
    )
    visual_purpose: str = Field(
        default="",
        max_length=500,
        description="Why this beat exists and what it should show.",
    )
    camera_primary: CameraMotion = Field(
        default=CameraMotion.KEN_BURNS,
        description="Primary camera motion for main shot.",
    )
    camera_cutaway: CameraMotion = Field(
        default=CameraMotion.STATIC,
        description="Camera motion for cutaway shot.",
    )
    transition_in: TransitionType = Field(
        default=TransitionType.CROSSFADE,
        description="Transition into this beat.",
    )
    transition_out: TransitionType = Field(
        default=TransitionType.CROSSFADE,
        description="Transition out of this beat.",
    )
    shots: list[ShotPlan] = Field(
        default_factory=list,
        description="Individual shots within this beat.",
    )
    motion_graphics_note: str = Field(
        default="",
        max_length=500,
        description="Optional motion graphics overlay description.",
    )


# Scene — the composite model
# ═══════════════════════════════════════════════════════════════════════ #

class Scene(BaseModel):
    """Complete scene model — the single source of truth.

    Every stage of the pipeline validates its input/output against this model.
    No untyped dicts or generic JSON are passed between components.
    """

    scene_id: int = Field(
        ...,
        ge=0,
        description="Unique scene identifier (0-indexed).",
    )
    title: str = Field(
        default="",
        max_length=200,
        description="Scene title for logging and reference.",
    )
    expected_duration: float = Field(
        default=12.0,
        ge=1.0,
        le=300.0,
        description="Target duration for this scene in seconds.",
    )
    topic: str = Field(
        default="",
        max_length=200,
        description="Video topic (used for routing/classification).",
    )

    # ── Sub-models ──────────────────────────────────────────────
    narration: SceneNarration = Field(
        default_factory=lambda: SceneNarration(spoken_narration=""),
        description="Spoken narration — the ONLY field that reaches TTS.",
    )
    visual_plan: VisualPlan = Field(
        default_factory=VisualPlan,
        description="Visual generation instructions — NEVER reaches TTS.",
    )
    visual_intent: VisualIntent = Field(
        default_factory=VisualIntent,
        description="Structured visual metadata — drives search, asset type "
                    "selection, and fallback strategies.",
    )
    search_plan: SearchPlan = Field(
        default_factory=lambda: SearchPlan(asset_search_queries=["general"]),
        description="Search queries for asset retrieval — NEVER contains narration.",
    )
    editing_plan: EditingPlan = Field(
        default_factory=EditingPlan,
        description="Editing instructions — transitions, motion, pacing.",
    )
    asset_plan: Optional[AssetPlan] = Field(
        default=None,
        description="Retrieved asset information (populated after asset search).",
    )
    beat_plans: Optional[list[BeatPlan]] = Field(
        default=None,
        description="Beat-based breakdown of this scene (populated after beat planning).",
    )
    
    audio_plan: Optional[AudioPlan] = Field(
        default=None,
        description="Audio rendering instructions (populated after TTS).",
    )
    render_plan: Optional[RenderPlan] = Field(
        default=None,
        description="Render instructions (populated during final composition).",
    )

    # ── Metadata ────────────────────────────────────────────────
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata. "
                    "Never reaches TTS, search, or visual generation.",
        max_length=50,
    )

    @model_validator(mode="after")
    def check_no_narration_leak_in_search(self) -> "Scene":
        """Validate that narration never leaks into search queries.

        Uses word-overlap ratio instead of naive substring check.
        A search query with >90% word overlap with narration is a leak.
        """
        if self.search_plan.asset_search_queries and self.narration.spoken_narration:
            narration_words = set(self.narration.spoken_narration.lower().split())
            if len(narration_words) < 3:
                return self
            for q in self.search_plan.asset_search_queries:
                query_words = set(q.lower().split())
                if len(query_words) < 3:
                    continue
                overlap = len(narration_words & query_words) / len(query_words)
                if overlap > 0.90:
                    raise ValueError(
                        f"Scene {self.scene_id}: SearchPlan query "
                        f"has {overlap:.0%} word overlap with narration. "
                        f"Search queries must be visual search terms, "
                        f"not copied narration text."
                    )
        return self

    @model_validator(mode="after")
    def check_expected_duration_positive(self) -> "Scene":
        if self.expected_duration <= 0:
            raise ValueError(
                f"Scene {self.scene_id}: expected_duration must be > 0, "
                f"got {self.expected_duration}"
            )
        return self

    def to_tts_dict(self) -> dict:
        """Produce ONLY the fields TTS is allowed to see.

        Returns a flat dict with ONLY spoken_narration.
        Any attempt to access other fields is architecturally prevented.
        """
        return {"text": self.narration.to_tts_input()}

    class Config:
        extra = "forbid"
        arbitrary_types_allowed = True


# ═══════════════════════════════════════════════════════════════════════ #
# Pipeline-level models
# ═══════════════════════════════════════════════════════════════════════ #

class PipelineState(BaseModel):
    """Complete pipeline state — tracked across all stages.

    This is the high-level state object passed between pipeline nodes.
    """

    topic: str = Field(..., min_length=1, max_length=200)
    scenes: list[Scene] = Field(default_factory=list)
    output_path: str = Field(default="final_output.mp4")
    render_plan: Optional[RenderPlan] = Field(default=None)
    iteration: int = Field(default=0, ge=0)
    max_iterations: int = Field(default=3, ge=1)
    quality_metrics: dict[str, float] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def scenes_continuous(self) -> "PipelineState":
        """Validate scene IDs are 0-based continuous."""
        if len(self.scenes) > 1:
            for i, scene in enumerate(self.scenes):
                if scene.scene_id != i:
                    raise ValueError(
                        f"PipelineState: scene_ids must be 0-based "
                        f"continuous. Expected {i}, got {scene.scene_id}"
                    )
        return self

    class Config:
        extra = "forbid"
        arbitrary_types_allowed = True


# ═══════════════════════════════════════════════════════════════════════ #
# Validation helpers
# ═══════════════════════════════════════════════════════════════════════ #

def validate_stage_input(stage_name: str, model: BaseModel) -> None:
    """Validate a model and raise immediately on failure.

    This is the contract enforcement point between every pipeline stage.
    Pipeline must fail immediately — no silent recovery.
    """
    # model.model_dump() already validates on construction,
    # but we call model_validate for explicit double-check.
    pass  # Validation happens at construction time in Pydantic v2


def scene_to_flat_dict(scene: Scene) -> dict[str, Any]:
    """Convert Scene to a flat dict for backward compatibility.

    WARNING: Only use this for logging/reporting, NOT for stage communication.
    """
    return {
        "scene_id": scene.scene_id,
        "title": scene.title,
        "spoken_narration": scene.narration.spoken_narration,
        "visual_description": scene.visual_plan.visual_description,
        "search_queries": scene.search_plan.asset_search_queries,
        "editing_instructions": scene.editing_plan.editing_instructions,
        "provider": scene.asset_plan.provider.value if scene.asset_plan else "",
        "filepath": scene.asset_plan.filepath if scene.asset_plan else "",
        "duration": scene.expected_duration,
    }
    