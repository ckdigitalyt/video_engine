"""stock_video.py — STOCK_VIDEO + ARCHIVAL renderer bodies (directive §13).

Broker-backed search + download with license metadata sidecars, deterministic
cache (same query+filters never re-download), then ffmpeg conform: scale/crop
to target aspect, trim to duration_sec, 30fps H.264 silent.

§13 GATE: assets whose license cannot be established are never downloaded —
the candidate is skipped and, when no candidate survives, the renderer raises
so the router's fallback chain takes over.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engine.renderers.base import (
    RenderContext,
    Renderer,
    RendererCapability,
    ShotRenderResult,
)

logger = logging.getLogger(__name__)


class _FootageRendererBase(Renderer):
    """Shared search→download→conform flow; subclasses pick the broker kind."""

    _broker_kind = "stock"      # broker search kind ("stock" | "archival")
    _download_method = "download_stock"

    def __init__(self, capability: RendererCapability | None = None,
                 broker: Any | None = None) -> None:
        self._capability = capability
        self._broker = broker

    def capabilities(self) -> RendererCapability:
        from engine.renderers.registry import get_capability

        return self._capability or get_capability(self.id)

    def _basic_issues(self, shot: dict) -> list[str]:
        issues: list[str] = []
        if not isinstance(shot, dict):
            return ["shot must be a dict"]
        if shot.get("renderer") not in (None, self.id):
            issues.append(f"shot.renderer is {shot.get('renderer')!r}, not {self.id!r}")
        if not shot.get("duration_sec"):
            issues.append("missing required shot field: duration_sec")
        if not (shot.get("subject") or shot.get("visual_goal")):
            issues.append(f"{self.id} needs subject or visual_goal as search query")
        return issues

    def _broker_instance(self) -> Any:
        if self._broker is not None:
            return self._broker
        from engine.broker.broker import MediaBroker

        self._broker = MediaBroker()
        return self._broker

    def _search_download(self, query: str, per_page: int = 4) -> Path | None:
        """Search, then download the first candidate that passes the §13
        license gate. Deterministic cache prevents re-downloads."""
        broker = self._broker_instance()
        method_name = ("download_archival" if self._broker_kind == "archival"
                       else "download_stock")
        method = getattr(broker, method_name, None)
        if self._broker_kind == "archival":
            candidates = broker.search_archival(query, per_page=per_page)
        else:
            candidates = broker.search_stock(query, per_page=per_page)
        if method is None:
            return None
        for asset in candidates:
            try:
                result = method(asset)
                logger.info("%s: using %s asset %s (%s)", self.id,
                            result.metadata.get("source"),
                            result.metadata.get("asset_id", ""),
                            result.metadata.get("license", ""))
                return Path(result.path)
            except Exception as exc:  # license gate or network — try next
                logger.warning("%s: skipping candidate (%s)", self.id, exc)
                continue
        return None

    def render(self, shot: dict, style: dict | None,
               ctx: RenderContext) -> ShotRenderResult:
        issues = self._basic_issues(shot)
        if issues:
            raise ValueError(f"{self.id} validate failed: {'; '.join(issues)}")

        from engine.renderers.media.conform import conform_clip, conform_image

        out_dir = Path(ctx.output_dir)
        shot_id = shot.get("shot_id", "shot")
        duration = float(shot.get("duration_sec", 4.0))
        query = shot.get("subject") or shot.get("visual_goal") or ""

        # Explicit local asset wins (offline path / pre-fetched by planner).
        req = shot.get("asset_requirements")
        local: Path | None = None
        if isinstance(req, dict) and req.get("footage_path"):
            local = Path(req["footage_path"])
        elif isinstance(req, list):
            for p in req:
                if isinstance(p, (str, Path)) and Path(p).exists():
                    local = Path(p)
                    break
        if local is None:
            local = self._search_download(query)

        if local is None:
            raise RuntimeError(
                f"{self.id}: no licensable asset found for {query!r} — "
                "falling back down the chain (§24)")

        out_path = out_dir / f"{shot_id}_{self.id.lower()}.mp4"
        is_image = local.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        if is_image:
            conform_image(local, out_path, duration=duration,
                          aspect=ctx.aspect, fps=ctx.fps)
        else:
            conform_clip(local, out_path, duration=duration,
                         aspect=ctx.aspect, fps=ctx.fps)
        return ShotRenderResult(
            path=str(out_path),
            metadata={
                "renderer": self.id,
                "asset": str(local),
                "query": query,
                "duration_sec": duration,
            },
            qa_frames=[],
        )


class StockVideoRenderer(_FootageRendererBase):
    """Pexels/Pixabay stock footage (broker-backed)."""

    id = "STOCK_VIDEO"
    _broker_kind = "stock"
    _download_method = "download_stock"

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        return self._basic_issues(shot)


class ArchivalRenderer(_FootageRendererBase):
    """NASA / Wikimedia Commons / Internet Archive (public-domain gate)."""

    id = "ARCHIVAL"
    _broker_kind = "archival"
    _download_method = "download_archival"

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        return self._basic_issues(shot)
