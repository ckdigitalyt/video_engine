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

# v4.1 algorithmic hardening: bump when render-side behavior changes so
# drivers can detect and re-render stale records instead of reusing them.
RENDER_ENGINE_REV = "v4.1"
# A clip that badly undershoots its planned duration is a broken render
# (frozen/black tail), not a conformable one — rejected at render time.
DURATION_MIN_RATIO = 0.6


def probe_video_duration(path: str | Path) -> float:
    """Media duration (s) via ffprobe; -1.0 when unavailable."""
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001 — a probe must never break a render
        return -1.0


def record_is_stale(record: dict, shot: dict) -> str | None:
    """Reason a render record must not be reused, or None when fresh.

    Checks: missing artifact, engine-revision mismatch, and duration
    undershoot vs the shot's planned duration (broken-render signature —
    r5 shipped clips at 25% of plan).
    """
    path = record.get("path")
    if not record.get("ok") or not path or not Path(path).exists():
        return "no rendered artifact"
    rev = (record.get("metadata") or {}).get("engine_rev")
    if rev != RENDER_ENGINE_REV:
        return f"engine_rev {rev!r} != {RENDER_ENGINE_REV!r}"
    expected = float(shot.get("duration_sec") or 0)
    if expected > 0:
        actual = probe_video_duration(path)
        if 0 < actual < expected * DURATION_MIN_RATIO:
            return (f"clip {actual:.2f}s < "
                    f"{DURATION_MIN_RATIO:.0%} of planned {expected:.2f}s")
    return None


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
                # v4.1: a clip far shorter than planned is a broken render
                # (S17 shipped at 1.4s vs 5.7s planned) — reject the attempt
                # and keep walking the fallback chain.
                expected = float(shot.get("duration_sec") or 0)
                if expected > 0:
                    actual = probe_video_duration(path)
                    if 0 < actual < expected * DURATION_MIN_RATIO:
                        attempts.append({
                            "renderer": rid, "ok": False,
                            "error": f"broken render: clip {actual:.2f}s < "
                                     f"{DURATION_MIN_RATIO:.0%} of planned "
                                     f"{expected:.2f}s"})
                        continue
                metadata = dict(result.metadata or {})
                if extra_metadata:
                    metadata.update(extra_metadata)
                metadata["engine_rev"] = RENDER_ENGINE_REV
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
