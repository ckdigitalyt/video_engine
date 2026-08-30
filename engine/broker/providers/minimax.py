"""minimax.py — MiniMax H3 video provider (directive §11).

STATUS (verified 2026-08-30): MiniMax's video API (Hailuo / platform.minimax.io)
is **paid-only** — per-second video generation billing, no free tier, no
ZeroGPU Space, no open weights for H3. Registered but ``enabled: false`` so
the broker registry documents the intended hero-shot provider; enable after
spend approval (directive §2C/§26: HERO shots only).

When enabled, implement ``generate_video`` against
``POST https://api.minimax.io/v1/video_generation`` (task-based: submit →
query → download; key: MINIMAX_API_KEY).
"""

from __future__ import annotations

import os

from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)


class MiniMaxH3Provider(MediaProvider):
    """MiniMax H3 cinematic video — DISABLED: paid-only API (no free tier)."""

    id = "minimax_h3"
    kind = "video"

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=["MiniMax-H3"],
            enabled=False, priority=10,
            notes=(
                "Paid-only (platform.minimax.io, per-second video billing, "
                "no free tier or open Space as of 2026-08-30). Set "
                "MINIMAX_API_KEY + cost approval to enable. Intended for "
                "HERO shots only (§26)."
            ),
        )

    def health_check(self) -> bool:
        return bool(os.environ.get("MINIMAX_API_KEY", "")) and False  # never live

    def generate_video(self, prompt: str, **kw) -> BrokerResult:
        raise ProviderError(
            "minimax_h3: paid-only provider, not enabled (§26 cost gate). "
            "The broker fails over to Wan 2.2 / LTX (free ZeroGPU Spaces).")
