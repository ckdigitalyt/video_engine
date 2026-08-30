"""Wave-2 tests: PIXIJS renderer (node-canvas scene framework)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.renderers.base import RenderContext
from engine.renderers.pixijs import PixiJsRenderer, scene_json_from_shot

NODE = shutil.which("node")
PIXI_DIR = Path(__file__).resolve().parent.parent / "pixi"
NODE_MODULES = PIXI_DIR / "node_modules"

_requires_node = pytest.mark.skipif(
    NODE is None or not NODE_MODULES.exists(),
    reason="node or pixi/node_modules not available",
)

SECTION7_SHOT = {
    "shot_id": "S7",
    "duration_sec": 2.0,
    "narrative_role": "action",
    "visual_goal": "t-rex running through the jungle",
    "background": "jungle",
    "subject": "a t_rex sprints through ferns",
    "camera": {"move": "push_in", "duration": 2.5},
}


class TestSceneJson:
    def test_section7_example_shape(self):
        scene = scene_json_from_shot(SECTION7_SHOT, None)
        assert scene["background"]["asset"] == "jungle"
        assert scene["camera"]["move"] == "push_in"
        assert any(c["type"] == "t_rex" for c in scene["characters"])
        assert scene["version"] == "pixi-scene-v1"

    def test_explicit_scene_block_wins(self):
        shot = dict(SECTION7_SHOT, motion={"scene": {
            "background": "#101020",
            "characters": [{"type": "earth", "position": [0.5, 0.5]}],
            "camera": {"move": "pan_right"},
        }})
        scene = scene_json_from_shot(shot, None)
        assert scene["background"] == "#101020"
        assert scene["characters"][0]["type"] == "earth"
        assert scene["camera"]["move"] == "pan_right"

    def test_deterministic(self):
        a = scene_json_from_shot(SECTION7_SHOT, {"palette": {}})
        b = scene_json_from_shot(SECTION7_SHOT, {"palette": {}})
        assert a == b


class TestPixiJsRenderer:
    def test_validate_missing_project(self, tmp_path):
        r = PixiJsRenderer(pixi_dir=tmp_path / "nope")
        assert any("pixi project missing" in i
                   for i in r.validate({"shot_id": "S", "duration_sec": 1.0}))

    @_requires_node
    def test_render_end_to_end(self, tmp_path):
        r = PixiJsRenderer()
        res = r.render(SECTION7_SHOT, None, RenderContext(
            output_dir=str(tmp_path), fps=12, resolution=(640, 360),
            aspect="16:9"))
        assert Path(res.path).exists()
        assert "t_rex" in res.metadata["characters"]
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", res.path],
            capture_output=True, text=True, timeout=60)
        stream = next(s for s in json.loads(out.stdout)["streams"]
                      if s["codec_type"] == "video")
        assert stream["codec_name"] == "h264"

    @_requires_node
    def test_render_deterministic(self, tmp_path):
        r = PixiJsRenderer()
        import hashlib

        hashes = []
        for i in range(2):
            res = r.render(SECTION7_SHOT, None, RenderContext(
                output_dir=str(tmp_path / f"run{i}"), fps=12,
                resolution=(640, 360), aspect="16:9"))
            hashes.append(hashlib.sha256(
                Path(res.path).read_bytes()).hexdigest())
        assert hashes[0] == hashes[1]

    def test_asset_library_present(self):
        root = PIXI_DIR.parent / "engine" / "assets" / "library"
        for rel in ("characters/t_rex.svg", "characters/dino_herd.svg",
                    "backdrops/jungle.svg", "props/asteroid.svg",
                    "props/earth.svg", "ATTRIBUTION.md"):
            assert (root / rel).exists(), rel
