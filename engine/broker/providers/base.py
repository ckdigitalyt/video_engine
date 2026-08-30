"""base.py — MediaProvider ABC for the AI Media Broker.

A provider hides one external service behind a small, uniform surface.
Generation ops a service doesn't support raise ProviderError — the broker
fails over to the next provider of that kind (ordered failover, §11).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    """A provider failed (transient or permanent) — broker may fail over."""


@dataclass
class BrokerResult:
    """Uniform result for every broker operation."""

    path: Path
    provider: str
    kind: str  # image | video | stock | vision
    cached: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderDescriptor:
    """What get_capabilities() reports for one provider."""

    id: str
    kind: str
    models: list[str] = field(default_factory=list)
    enabled: bool = True
    priority: int = 100
    notes: str = ""


class MediaProvider(ABC):
    """Base class for all broker clients."""

    id: str = ""
    kind: str = ""  # image | video | image_to_video | stock | vision

    @abstractmethod
    def capabilities(self) -> ProviderDescriptor: ...

    @abstractmethod
    def health_check(self) -> bool:
        """Cheap liveness probe. Must never raise — return False on failure."""

    def quota(self) -> dict[str, Any] | None:
        """Remaining quota if the provider exposes it, else None."""
        return None

    # ── Generation ops (default: unsupported) ────────────────────────────

    def generate_image(self, prompt: str, **kw: Any) -> BrokerResult:
        raise ProviderError(f"{self.id}: image generation not supported")

    def generate_video(self, prompt: str, **kw: Any) -> BrokerResult:
        raise ProviderError(f"{self.id}: video generation not supported")

    def image_to_video(self, image: str | Path, prompt: str, **kw: Any) -> BrokerResult:
        raise ProviderError(f"{self.id}: image-to-video not supported")

    def edit_image(self, image: str | Path, instruction: str, **kw: Any) -> BrokerResult:
        raise ProviderError(f"{self.id}: image editing not supported")
