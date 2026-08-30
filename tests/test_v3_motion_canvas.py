"""Wave-2 tests: MOTION_CANVAS renderer (node-canvas template engine).

Requires node + motion/node_modules (npm --prefix motion install); skips
gracefully when the JS toolchain is absent so the suite stays network-free.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.renderers.base import RenderContext
from engine.renderers.motion_canvas import (
    MotionCanvasRenderer,
    template_json_from_shot,
)

NODE = shutil.which("node")
MOTION_DIR = Path(__file__).resolve().parent.parent / "motion"
NODE_MODULES = MOTION_DIR / "node_modules"

_requires_node = pytest.mark.skipif(
    NODE is None or not NODE_MODULES.exists(),
    reason="node or motion/node_modules not available",
)


class TestTemplateJsonMapping:
    def test_explicit_template_and_props(self):
        shot = {
            "shot_id": "S1", "duration_sec": 2.5,
            "motion": {"template": "timeline",
                       "props": {"events": [{"label": "a"}]}},
        }
        scene = template_json_from_shot(shot, None)
        assert scene["template"] == "timeline"
        assert scene["props"]["events"] == [{"label": "a"}]
        assert scene["duration_sec"] == 2.5

    def test_default_from_narrative_role(self):
        shot = {"shot_id": "S1", "duration_sec": 2.0,
                "narrative_role": "hook", "text_overlay": {"text": "Hook"}}
        scene = template_json_from_shot(shot, None)
        assert scene["template"] == "kinetic_title"
        assert scene["props"]["title"] == "Hook"

    def test_default_from_data_payload(self):
        shot = {"shot_id": "S1", "duration_sec": 2.0,
                "data": {"rows": [{"label": "x", "value": 5}]}}
        scene = template_json_from_shot(shot, None)
        assert scene["template"] == "infographic"

    def test_style_palette_carried(self):
        style = {"palette": {"accent": "#123456"}}
        scene = template_json_from_shot({"shot_id": "S", "duration_sec": 1.0},
                                        style)
        assert scene["style"]["palette"]["accent"] == "#123456"

    def test_deterministic(self):
        shot = {"shot_id": "S1", "duration_sec": 2.0, "narrative_role": "hook"}
        a = template_json_from_shot(shot, {"palette": {}})
        b = template_json_from_shot(shot, {"palette": {}})
        assert a == b


class TestMotionCanvasRenderer:
    def test_validate_missing_project(self, tmp_path):
        r = MotionCanvasRenderer(motion_dir=tmp_path / "nope")
        issues = r.validate({"shot_id": "S1", "duration_sec": 1.0})
        assert any("motion project missing" in i for i in issues)

    def test_validate_unknown_template(self):
        r = MotionCanvasRenderer()
        if not MOTION_DIR.exists():
            pytest.skip("motion project absent")
        issues = r.validate({"shot_id": "S1", "duration_sec": 1.0,
                             "motion": {"template": "nope"}})
        assert any("unknown motion template" in i for i in issues)

    @_requires_node
    def test_render_end_to_end(self, tmp_path):
        r = MotionCanvasRenderer()
        shot = {
            "shot_id": "T1", "duration_sec": 1.0,
            "narrative_role": "hook",
            "motion": {"template": "kinetic_title",
                       "props": {"title": "Hello", "subtitle": "world"}},
        }
        res = r.render(shot, {"palette": {"background": "#000000"}},
                       RenderContext(output_dir=str(tmp_path), fps=12,
                                     resolution=(640, 360), aspect="16:9"))
        assert Path(res.path).exists()
        assert res.metadata["template"] == "kinetic_title"
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", res.path],
            capture_output=True, text=True, timeout=60)
        stream = next(s for s in json.loads(out.stdout)["streams"]
                      if s["codec_type"] == "video")
        assert stream["codec_name"] == "h264"
        assert stream["width"] == 640

    @_requires_node
    def test_render_deterministic(self, tmp_path):
        r = MotionCanvasRenderer()
        shot = {"shot_id": "D1", "duration_sec": 0.8,
                "motion": {"template": "number_counter",
                           "props": {"from": 0, "to": 50}}}
        import hashlib

        paths = []
        for i in range(2):
            res = r.render(shot, None, RenderContext(
                output_dir=str(tmp_path / f"run{i}"), fps=12,
                resolution=(640, 360), aspect="16:9"))
            paths.append(hashlib.sha256(
                Path(res.path).read_bytes()).hexdigest())
        assert paths[0] == paths[1]
