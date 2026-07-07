"""
models — Typed domain models for the video_engine pipeline.

All inter-stage communication uses strict Pydantic models defined in
schemas.py.  Backward-compatible dataclasses are retained but deprecated.
"""

# ── Strict Pydantic models (current) ──────────────────────────────
from .schemas import (
    # Enums
    CameraMotion,
    TransitionType,
    ProviderType,
    MusicStyle,
    # Narration
    SceneNarration,
    # Plans
    VisualPlan,
    SearchPlan,
    EditingPlan,
    AssetPlan,
    AudioPlan,
    RenderPlan,
    # Composite
    Scene,
    PipelineState,
    # Helpers
    scene_to_flat_dict,
)

# ── Backward-compatible dataclasses (deprecated) ───────────────────
from .legacy_dataclasses import (
    Scene as LegacyScene,
    SceneAsset,
    Narration,
    RenderSettings,
    TimelineTrack,
    Timeline,
    VideoMetadata,
    VideoProject,
    AssetMetadata,
    ProviderResult,
    RenderResult,
    CriticResult,
    ExecutionResult,
    ChannelProfile,
    UploadJob,
    OutlineScene,
    StoryOutline,
)

__all__ = [
    # Pydantic models
    "CameraMotion",
    "TransitionType",
    "ProviderType",
    "MusicStyle",
    "SceneNarration",
    "VisualPlan",
    "SearchPlan",
    "EditingPlan",
    "AssetPlan",
    "AudioPlan",
    "RenderPlan",
    "Scene",
    "PipelineState",
    "scene_to_flat_dict",
    # Legacy dataclasses
    "LegacyScene",
    "SceneAsset",
    "Narration",
    "RenderSettings",
    "TimelineTrack",
    "Timeline",
    "VideoMetadata",
    "VideoProject",
    "AssetMetadata",
    "ProviderResult",
    "RenderResult",
    "CriticResult",
    "ExecutionResult",
    "ChannelProfile",
    "UploadJob",
    "OutlineScene",
    "StoryOutline",
]
