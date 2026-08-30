"""registry.py — Renderer capability registry (v3 Wave 1).

Loads renderer capability records from configs/renderers.yaml, instantiates
every enabled renderer (live adapters where a body exists, registered stubs
otherwise) and exposes lookups used by the router and the pipeline.

YAML is the source of truth for capabilities; the schema
schemas/renderer_capability_v1.schema.json documents the record shape.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from engine.renderers.base import (
    COST_TIERS,
    QUALITY_DIMENSIONS,
    Renderer,
    RendererCapability,
)
from engine.renderers.adapters import make_renderer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RENDERERS_YAML = PROJECT_ROOT / "configs" / "renderers.yaml"


class RegistryError(ValueError):
    """Raised when the renderer registry is misconfigured."""


def _load_yaml() -> dict[str, Any]:
    with open(RENDERERS_YAML, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "fallback_chain" not in data:
        raise RegistryError("configs/renderers.yaml missing fallback_chain")
    return data


def _capability_from_record(renderer_id: str, record: dict[str, Any]) -> RendererCapability:
    avail = record.get("availability", {}) or {}
    qdims = record.get("quality_dimensions", {}) or {}
    missing = [d for d in QUALITY_DIMENSIONS if d not in qdims]
    if missing:
        raise RegistryError(f"renderer {renderer_id} missing quality dimensions: {missing}")
    cost_tier = record.get("cost_tier", "LOW")
    if cost_tier not in COST_TIERS:
        raise RegistryError(f"renderer {renderer_id} bad cost_tier {cost_tier!r}")
    return RendererCapability(
        id=renderer_id,
        display_name=record.get("display_name", renderer_id),
        strengths=list(record.get("strengths", [])),
        input_kinds=list(record.get("input_kinds", [])),
        output=record.get("output", "video"),
        cost_tier=cost_tier,
        enabled=bool(avail.get("enabled", True)),
        offline_capable=bool(avail.get("offline_capable", True)),
        requires_network=bool(avail.get("requires_network", False)),
        requires_remote_gpu=bool(avail.get("requires_remote_gpu", False)),
        quality_dimensions={d: float(qdims[d]) for d in QUALITY_DIMENSIONS},
        max_duration_sec=record.get("max_duration_sec"),
        notes=record.get("notes", ""),
    )


@functools.lru_cache(maxsize=1)
def _capabilities() -> dict[str, RendererCapability]:
    data = _load_yaml()
    out: dict[str, RendererCapability] = {}
    for renderer_id, record in data.items():
        if renderer_id == "fallback_chain":
            continue
        out[renderer_id] = _capability_from_record(renderer_id, record)
    return out


@functools.lru_cache(maxsize=1)
def _renderers() -> dict[str, Renderer]:
    return {
        renderer_id: make_renderer(renderer_id, cap)
        for renderer_id, cap in _capabilities().items()
        if cap.enabled
    }


def get_capability(renderer_id: str) -> RendererCapability:
    try:
        return _capabilities()[renderer_id]
    except KeyError:
        raise KeyError(f"unknown renderer id: {renderer_id!r}") from None


def get_renderer(renderer_id: str) -> Renderer:
    """Return the registered renderer instance (adapters + enabled stubs)."""
    try:
        return _renderers()[renderer_id]
    except KeyError:
        if renderer_id in _capabilities():
            raise RendererLookupUnavailable(renderer_id) from None
        raise KeyError(f"unknown renderer id: {renderer_id!r}") from None


class RendererLookupUnavailable(RuntimeError):
    """Renderer exists in the registry but is disabled (enabled: false)."""


def all_renderers() -> dict[str, Renderer]:
    """All *enabled* renderer instances."""
    return dict(_renderers())


def all_capabilities() -> dict[str, RendererCapability]:
    """All capability records, including disabled renderers."""
    return dict(_capabilities())


def fallback_chain() -> list[str]:
    """Canonical offline degradation chain (§24) from configs/renderers.yaml."""
    data = _load_yaml()
    return list(data["fallback_chain"])


def reset_registry_cache() -> None:
    """Test hook: drop cached capabilities/renderers (e.g. after config edit)."""
    _capabilities.cache_clear()
    _renderers.cache_clear()
