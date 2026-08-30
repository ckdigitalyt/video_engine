"""engine.renderers — v3 multi-renderer layer (Wave 1).

Formal Renderer interface + adapters around the existing manim/media/vector
packages, registered stubs for Wave-2 renderers, capability registry and the
deterministic renderer router.  See docs/architecture/v3_multi_renderer_design.md.
"""

from engine.renderers.base import (
    RenderContext,
    Renderer,
    RendererCapability,
    RendererNotImplemented,
    RendererUnavailable,
    ShotRenderResult,
)

__all__ = [
    "RenderContext",
    "Renderer",
    "RendererCapability",
    "RendererNotImplemented",
    "RendererUnavailable",
    "ShotRenderResult",
]
