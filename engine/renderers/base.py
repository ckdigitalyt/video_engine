"""base.py — Formal Renderer interface for the v3 multi-renderer engine.

Every renderer (Manim, AI video, stock, Motion Canvas, PixiJS, ...) sits
behind this interface (directive §4 "renderer-agnostic and future-proof").
The router selects renderers; the pipeline only ever talks to Renderers.

Adapters wrap existing code paths WITHOUT behavior change; Wave-2 renderers
register as stubs that raise :class:`RendererNotImplemented` until filled in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


class RendererNotImplemented(NotImplementedError):
    """Raised by registered stub renderers whose bodies land in Wave 2."""


class RendererUnavailable(RuntimeError):
    """Raised when a renderer cannot run in the current environment."""


# Quality dimensions scored by the router (directive §5).
QUALITY_DIMENSIONS: tuple[str, ...] = (
    "realism",
    "physical_motion",
    "math_precision",
    "character_interaction",
    "emotional_impact",
    "historical_authenticity",
    "diagrammatic",
    "camera_movement",
    "text_heavy",
    "stylization",
)

COST_TIERS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "HERO")


@dataclass
class RendererCapability:
    """Mirrors schemas/renderer_capability_v1.schema.json."""

    id: str
    display_name: str
    strengths: list[str] = field(default_factory=list)
    input_kinds: list[str] = field(default_factory=list)
    output: str = "video"
    cost_tier: str = "LOW"
    enabled: bool = True
    offline_capable: bool = True
    requires_network: bool = False
    requires_remote_gpu: bool = False
    quality_dimensions: dict[str, float] = field(default_factory=dict)
    max_duration_sec: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "strengths": list(self.strengths),
            "input_kinds": list(self.input_kinds),
            "output": self.output,
            "cost_tier": self.cost_tier,
            "availability": {
                "enabled": self.enabled,
                "offline_capable": self.offline_capable,
                "requires_network": self.requires_network,
                "requires_remote_gpu": self.requires_remote_gpu,
            },
            "quality_dimensions": dict(self.quality_dimensions),
            "max_duration_sec": self.max_duration_sec,
            "notes": self.notes,
        }


@dataclass
class RenderContext:
    """Per-shot render context handed to every renderer."""

    output_dir: str
    fps: int = 30
    resolution: tuple[int, int] = (3840, 2160)
    aspect: str = "16:9"
    seed: int = 0
    style: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShotRenderResult:
    """Result of rendering a single shot."""

    path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    qa_frames: list[str] = field(default_factory=list)


class Renderer(ABC):
    """Formal interface every renderer implements.

    Implementations must be deterministic given (shot, style, ctx) — LLMs
    author the spec, renderers implement it (directive §4).
    """

    id: ClassVar[str] = ""

    @abstractmethod
    def capabilities(self) -> RendererCapability:
        """Capability record (loaded from configs/renderers.yaml)."""

    @abstractmethod
    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        """Static pre-flight checks. Returns a list of human-readable issues;
        an empty list means the shot is renderable by this renderer."""

    @abstractmethod
    def render(self, shot: dict, style: dict | None, ctx: RenderContext) -> ShotRenderResult:
        """Render one shot. May raise RendererNotImplemented (stub) or
        RendererUnavailable (environment)."""
