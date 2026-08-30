"""runner.py — Per-shot render orchestration (Wave 3).

Renders each planned shot through its assigned renderer, walking the §24
fallback chain on failure. Renderer-agnostic: the pipeline only ever talks
to the Renderer interface (engine/renderers/base.py). Every attempt is
recorded so QA/repair can route intelligently.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

from engine.renderers.base import RenderContext, ShotRenderResult
from engine.renderers.budget import FALLBACK_CHAIN
from engine.renderers.registry import get_renderer

logger = logging.getLogger(__name__)

# Offline-only availability (§24 / --dev mode): every network renderer off.
OFFLINE_AVAILABILITY: dict[str, bool] = {
    "AI_VIDEO": False,
    "AI_IMAGE_MOTION": False,
    "STOCK_VIDEO": False,
    "ARCHIVAL": False,
    "GODOT": False,
}

DEV_MODE = "dev"
FULL_MODE = "full"


def full_chain(shot: dict) -> list[str]:
    """§24 walk order for a shot: assigned renderer → fallback_renderer →
    canonical chain. Deduplicated, order-preserving."""
    chain: list[str] = []
    for rid in (shot.get("renderer"), shot.get("fallback_renderer"),
                *FALLBACK_CHAIN):
        if rid and rid not in chain:
            chain.append(rid)
    return chain


def shot_seed(shot: dict, attempt: int = 0) -> int:
    """Deterministic per-shot seed that varies across regen attempts."""
    basis = f"{shot.get('shot_id')}:{shot.get('visual_goal','')}:{attempt}"
    return int(hashlib.sha256(basis.encode("utf-8")).hexdigest()[:8], 16)


def render_shot(shot: dict, style: dict, out_dir: str | Path, *,
                fps: int = 30, resolution: tuple[int, int] = (1920, 1080),
                aspect: str = "16:9", attempt: int = 0,
                renderer_override: str | None = None,
                available: Callable[[str], bool] | None = None,
                extra_metadata: dict | None = None) -> dict:
    """Render one shot, walking the fallback chain until one renderer
    succeeds. Returns a render record:

        {"shot_id", "ok", "path", "renderer_used", "attempts":
         [{"renderer", "ok", "error"}...], "seed", "metadata", "qa_frames"}
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    attempts: list[dict] = []
    seed = shot_seed(shot, attempt)

    chain = full_chain(shot)
    if renderer_override:
        chain = [renderer_override] + [c for c in chain
                                       if c != renderer_override]

    for rid in chain:
        if available is not None and not available(rid):
            attempts.append({"renderer": rid, "ok": False,
                             "error": "unavailable (mode policy)"})
            continue
        try:
            renderer = get_renderer(rid)
        except Exception as exc:  # unregistered renderer id
            attempts.append({"renderer": rid, "ok": False,
                             "error": f"registry: {exc}"})
            continue
        # Renderers validate shot.renderer against their own id — walk the
        # chain with the attempt renderer recorded on the shot.
        attempt_shot = dict(shot)
        attempt_shot["renderer"] = rid
        try:
            issues = renderer.validate(attempt_shot, style)
            if issues:
                attempts.append({"renderer": rid, "ok": False,
                                 "error": f"validate: {'; '.join(issues[:3])}"})
                continue
            ctx = RenderContext(
                output_dir=str(out_dir), fps=fps, resolution=resolution,
                aspect=aspect, seed=seed, style=style)
            result: ShotRenderResult = renderer.render(attempt_shot, style, ctx)
            path = Path(result.path)
            # Scene-file artifacts (MANIM) are not mp4s — recorded but the
            # chain continues to a renderer that produces video.
            if path.exists() and path.suffix.lower() == ".mp4" \
                    and path.stat().st_size > 0:
                metadata = dict(result.metadata or {})
                if extra_metadata:
                    metadata.update(extra_metadata)
                return {
                    "shot_id": shot.get("shot_id", "?"), "ok": True,
                    "path": str(path), "renderer_used": rid,
                    "attempts": attempts, "seed": seed,
                    "metadata": metadata,
                    "qa_frames": list(result.qa_frames or []),
                }
            attempts.append({"renderer": rid, "ok": False,
                             "error": f"no mp4 artifact ({path.name}, "
                                      f"meta={result.metadata.get('artifact')})"})
        except Exception as exc:  # noqa: BLE001 — one renderer never kills the run
            attempts.append({"renderer": rid, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}"[:300]})

    return {"shot_id": shot.get("shot_id", "?"), "ok": False, "path": None,
            "renderer_used": None, "attempts": attempts, "seed": seed,
            "metadata": extra_metadata or {}, "qa_frames": []}


def mode_availability(mode: str, *,
                      offline_renderers: list[str] | None = None,
                      extra_off: list[str] | None = None) -> dict[str, bool]:
    """Availability policy per run mode.

    - dev: everything network-dependent off (§24 — pipeline stays local).
    - full: registry defaults, minus explicit offline_renderers overrides
      (used by the smoke run to keep the mix procedural + at most one AI
      shot) and extra_off.
    """
    if mode == DEV_MODE:
        return dict(OFFLINE_AVAILABILITY)
    avail: dict[str, bool] = {}
    for rid in (offline_renderers or []):
        avail[rid] = False
    for rid in (extra_off or []):
        avail[rid] = False
    return avail
