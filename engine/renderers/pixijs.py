"""pixijs.py — PIXIJS renderer body (directive §7).

Maps Shot v3 → the §7 scene JSON (background, characters with position +
action, camera move, particles/atmosphere flags), writes the scene file,
invokes the headless node scene renderer (pixi/render.mjs) and verifies the
mp4. Scene framework: parallax layers, particles, cutout characters with
bob/run actions, camera push_in/pan/pull_out/shake, fly-in props.

IMPLEMENTATION NOTE (2026-08-30, Wave 2): pixi.js-legacy v7 cannot run under
node-canvas ("document is not defined" — DOM required; the @pixi/node shim
targets the unmaintained v6 line). The scene framework therefore runs
directly on node-canvas with the same scene JSON contract, so a later
migration to true PixiJS (e.g. puppeteer frame capture) keeps the Python
adapter and scene format unchanged. See design doc §7.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from engine.renderers.base import (
    RenderContext,
    Renderer,
    RendererCapability,
    ShotRenderResult,
)

logger = logging.getLogger(__name__)

PIXI_DIR = Path(__file__).resolve().parent.parent.parent / "pixi"
RENDER_SCRIPT = PIXI_DIR / "render.mjs"

_CAMERAS = {"static", "push_in", "pull_out", "pan_left", "pan_right", "shake"}
_ACTIONS = {"idle", "bob", "run", "none"}
_PARTICLES = {"dust", "embers", "stars", "asteroid_field", None}
_ATMOSPHERES = {"fog", "darkness", "flash", None}


class PixiRendererError(RuntimeError):
    """Scene render failed."""


def scene_json_from_shot(
    shot: dict,
    style: dict | None = None,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> dict:
    """Derive pixi-scene-v1 JSON from a Shot v3 payload.

    The shot may carry a full ``motion.scene`` block (§7 example). Otherwise
    a scene is built deterministically from subject/background/camera fields.
    """
    motion_cfg = shot.get("motion") or {}
    scene = dict(motion_cfg.get("scene") or {})

    if "background" not in scene:
        bg = shot.get("background") or "jungle"
        scene["background"] = (
            {"asset": bg, "depth": 0.5, "scale": 1.15}
            if not str(bg).startswith("#") else bg
        )
    if "characters" not in scene:
        chars = []
        subject = shot.get("subject") or ""
        # A subject mentioning a known character type places it automatically.
        for known in ("t_rex", "dino_herd", "dinosaur"):
            if known in subject.lower():
                role = shot.get("narrative_role", "")
                chars.append({
                    "type": known,
                    "position": [0.62 if role in ("hook", "reveal") else 0.4, 0.9],
                    "action": "run" if role in ("action", "hook") else "idle",
                    "scale": 0.9,
                    **({"path": [0.35]} if role in ("action", "hook") else {}),
                })
                break
        scene["characters"] = chars
    if "camera" not in scene:
        camera = shot.get("camera")
        if isinstance(camera, dict) and camera.get("move"):
            scene["camera"] = {"move": camera["move"],
                               "duration": float(camera.get("duration", 2.0))}
        elif isinstance(camera, str) and camera in _CAMERAS:
            scene["camera"] = {"move": camera, "duration": 2.0}
        else:
            role = shot.get("narrative_role", "context")
            scene["camera"] = {
                "move": "push_in" if role in ("hook", "reveal", "action")
                else "static",
                "duration": 2.0,
            }
    if "particles" not in scene:
        scene["particles"] = motion_cfg.get("particles")
    if "atmosphere" not in scene:
        scene["atmosphere"] = motion_cfg.get("atmosphere")

    scene.update({
        "version": "pixi-scene-v1",
        "duration_sec": float(shot.get("duration_sec", 3.0)),
        "width": width,
        "height": height,
        "fps": fps,
    })
    if style and isinstance(style.get("palette"), dict):
        bgc = style["palette"].get("background")
        if isinstance(bgc, str) and bgc.startswith("#") and not scene.get("background_asset"):
            pass  # colored backgrounds only when no asset backdrop
    return scene


class PixiJsRenderer(Renderer):
    """2D/cartoon scene renderer (JSON-described scenes, §7)."""

    id = "PIXIJS"

    def __init__(self, capability: RendererCapability | None = None,
                 pixi_dir: Path | None = None) -> None:
        self._capability = capability
        self._pixi_dir = Path(pixi_dir) if pixi_dir else PIXI_DIR

    def capabilities(self) -> RendererCapability:
        from engine.renderers.registry import get_capability

        return self._capability or get_capability(self.id)

    def validate(self, shot: dict, style: dict | None = None) -> list[str]:
        issues: list[str] = []
        if not isinstance(shot, dict):
            return ["shot must be a dict"]
        if shot.get("renderer") not in (None, self.id):
            issues.append(f"shot.renderer is {shot.get('renderer')!r}, not {self.id!r}")
        if not shot.get("duration_sec"):
            issues.append("missing required shot field: duration_sec")
        if not self._pixi_dir.exists() or not (self._pixi_dir / "render.mjs").exists():
            issues.append(f"pixi project missing: {self._pixi_dir}")
        elif not (self._pixi_dir / "node_modules").exists():
            issues.append("pixi node_modules missing (run: npm --prefix pixi install)")
        camera = (shot.get("motion") or {}).get("scene", {}).get("camera", {})
        move = camera.get("move") if isinstance(camera, dict) else None
        if move and move not in _CAMERAS:
            issues.append(f"unknown camera move: {move!r}")
        return issues

    def render(self, shot: dict, style: dict | None,
               ctx: RenderContext) -> ShotRenderResult:
        issues = self.validate(shot, style)
        if issues:
            raise ValueError(f"PIXIJS validate failed: {'; '.join(issues)}")

        out_dir = Path(ctx.output_dir)
        shot_id = shot.get("shot_id", "shot")
        scale = min(1.0, 1920 / ctx.resolution[0], 1080 / ctx.resolution[1])
        scene = scene_json_from_shot(
            shot, style or ctx.style,
            width=_even(ctx.resolution[0] * scale),
            height=_even(ctx.resolution[1] * scale),
            fps=ctx.fps,
        )

        scene_path = out_dir / f"{shot_id}_pixi_scene.json"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")

        out_path = out_dir / f"{shot_id}_pixijs.mp4"
        node = shutil.which("node")
        if not node:
            raise PixiRendererError("node not found on PATH")
        proc = subprocess.run(
            [node, str(self._pixi_dir / "render.mjs"),
             str(scene_path), str(out_path)],
            capture_output=True, text=True, timeout=900,
        )
        if proc.returncode != 0:
            raise PixiRendererError(
                f"pixi scene render failed ({proc.returncode}): "
                f"{(proc.stderr or proc.stdout)[-1200:]}")
        if not out_path.exists() or out_path.stat().st_size < 1000:
            raise PixiRendererError("pixi scene render produced no usable output")

        return ShotRenderResult(
            path=str(out_path),
            metadata={
                "renderer": self.id,
                "camera": scene["camera"]["move"],
                "characters": [c.get("type") for c in scene.get("characters", [])],
                "particles": scene.get("particles"),
                "atmosphere": scene.get("atmosphere"),
                "scene_json": str(scene_path),
                "duration_sec": scene["duration_sec"],
            },
            qa_frames=[],
        )


def _even(n: float) -> int:
    n = int(n)
    return n - n % 2
