"""
models — Typed domain models for the video_engine pipeline.

All models are plain Python dataclasses with complete type hints.  They carry
no business logic, no provider dependencies, and no ORM machinery.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ── Core project model ─────────────────────────────────────────────────────

@dataclass
class Scene:
    """A single scene in a video project."""

    scene_id: int
    search_query: str
    narration: str


@dataclass
class SceneAsset:
    """Resolved file paths for a scene's media assets."""

    scene_id: int
    video_path: str
    audio_path: str


@dataclass
class Narration:
    """Text-to-speech narration parameters."""

    text: str
    voice: str = "bm_george"
    speed: float = 1.0
    language: str = "en-gb"
    output_path: str = ""


# ── Timeline models ────────────────────────────────────────────────────────

@dataclass
class RenderSettings:
    """Video output rendering parameters."""

    resolution: list[int] = field(default_factory=lambda: [1920, 1080])
    fps: int = 30

    def to_tuple(self) -> tuple[int, int]:
        return (self.resolution[0], self.resolution[1])


@dataclass
class TimelineTrack:
    """A single track entry in the audio or video timeline."""

    file: str
    start_time: float = 0.0
    end_time: float = 0.0
    track: str = "voice"
    layer: int = 1
    transition_out: str = "none"


@dataclass
class Timeline:
    """Complete timeline document consumed by the renderer."""

    render_settings: RenderSettings
    audio_timeline: list[TimelineTrack] = field(default_factory=list)
    video_timeline: list[TimelineTrack] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "render_settings": {
                "resolution": self.render_settings.resolution,
                "fps": self.render_settings.fps,
            },
            "audio_timeline": [
                {
                    "track": t.track,
                    "file": t.file,
                    "start_time": t.start_time,
                    "end_time": t.end_time,
                }
                for t in self.audio_timeline
            ],
            "video_timeline": [
                {
                    "layer": t.layer,
                    "file": t.file,
                    "start_time": t.start_time,
                    "end_time": t.end_time,
                    "transition_out": t.transition_out,
                }
                for t in self.video_timeline
            ],
        }

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)


# ── Video project ──────────────────────────────────────────────────────────

@dataclass
class VideoMetadata:
    """Metadata about a produced video."""

    topic: str
    duration_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    output_path: Optional[str] = None
    approved: Optional[bool] = None
    iterations: int = 0
    status: str = "pending"


@dataclass
class VideoProject:
    """Top-level project representing a video to produce."""

    topic: str
    scenes: list[Scene] = field(default_factory=list)
    metadata: Optional[VideoMetadata] = None
    timeline: Optional[Timeline] = None
    iteration: int = 0


# ── Provider result models ─────────────────────────────────────────────────

@dataclass
class AssetMetadata:
    """Metadata about a downloaded media asset."""

    provider: str = ""
    search_query: str = ""
    asset_url: str = ""
    local_path: Optional[str] = None
    file_size_bytes: Optional[int] = None


@dataclass
class ProviderResult:
    """Result from an asset provider search."""

    items: list[AssetMetadata] = field(default_factory=list)
    error: Optional[str] = None


# ── Pipeline result models ─────────────────────────────────────────────────

@dataclass
class RenderResult:
    """Result of a video render operation."""

    output_path: str
    duration_seconds: float
    file_size_bytes: int
    success: bool = True
    error: Optional[str] = None


@dataclass
class CriticResult:
    """Result from the Gemini multimodal critic."""

    approved: bool = False
    decision: str = ""
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    """Complete result of a pipeline execution."""

    topic: str
    status: str = "running"
    plan_json: Optional[str] = None
    timeline_json: Optional[str] = None
    output_path: Optional[str] = None
    duration_seconds: Optional[float] = None
    iteration_count: int = 0
    critic_approved: Optional[bool] = None
    error_message: Optional[str] = None


# ── Upload / channel models ────────────────────────────────────────────────

@dataclass
class ChannelProfile:
    """YouTube channel profile (reserved for future use)."""

    channel_id: str = ""
    name: str = ""
    niche: str = ""
    target_audience: str = ""


@dataclass
class UploadJob:
    """YouTube upload job (reserved for future use)."""

    video_path: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    privacy_status: str = "public"
    channel_id: str = ""
    status: str = "pending"
