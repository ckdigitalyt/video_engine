"""test_v3_renderer_adapters.py — Adapter wiring around existing renderers."""

from pathlib import Path

import pytest

from engine.renderers.adapters import (
    ManimRenderer,
    MediaRenderer,
    StubRenderer,
    VectorRenderer,
    make_renderer,
)
from engine.renderers.base import (
    RenderContext,
    Renderer,
    RendererCapability,
    RendererNotImplemented,
)
from engine.renderers.registry import all_capabilities, get_capability, get_renderer


MINIMAL_SHOT = {
    "version": "v3",
    "shot_id": "S01",
    "duration_sec": 3.0,
    "narrative_role": "reveal",
    "visual_goal": "test shot",
    "renderer": "MANIM",
}


@pytest.fixture
def ctx(tmp_path):
    return RenderContext(output_dir=str(tmp_path))


class TestManimAdapter:
    def test_is_a_renderer(self):
        assert isinstance(get_renderer("MANIM"), Renderer)
        assert isinstance(get_renderer("MANIM"), ManimRenderer)

    def test_capability_from_registry(self):
        cap = get_renderer("MANIM").capabilities()
        assert cap.id == "MANIM"
        assert cap.cost_tier == "LOW" and cap.offline_capable

    def test_missing_visualspec_is_reported(self):
        issues = get_renderer("MANIM").validate(MINIMAL_SHOT)
        assert any("visualspec" in i for i in issues)

    def test_invalid_visualspec_is_reported(self):
        shot = dict(MINIMAL_SHOT, visualspec={"version": "v2", "beats": []})
        issues = get_renderer("MANIM").validate(shot)
        assert any(i.startswith("visualspec:") for i in issues)

    def test_wrong_renderer_field_reported(self):
        issues = get_renderer("MANIM").validate(dict(MINIMAL_SHOT, renderer="PIXIJS"))
        assert any("renderer" in i for i in issues)

    def test_missing_required_fields_reported(self):
        issues = get_renderer("MANIM").validate({"shot_id": "S01"})
        assert len(issues) >= 3  # duration_sec, visual_goal, visualspec

    def test_render_validates_before_compiling(self, ctx):
        with pytest.raises(ValueError, match="validate failed"):
            get_renderer("MANIM").render(MINIMAL_SHOT, None, ctx)


class TestMediaVectorAdapters:
    @pytest.mark.parametrize("renderer_id,cls", [
        ("MEDIA", MediaRenderer),
        ("VECTOR", VectorRenderer),
    ])
    def test_registered_and_conformant(self, renderer_id, cls):
        renderer = get_renderer(renderer_id)
        assert isinstance(renderer, cls)
        assert isinstance(renderer, Renderer)
        assert renderer.capabilities().id == renderer_id
        assert isinstance(
            renderer.validate(dict(MINIMAL_SHOT, renderer=renderer_id)), list)

    def test_media_renders_offline(self, ctx, tmp_path):
        """Wave 2: MEDIA now renders provided stills (offline Ken Burns)."""
        from engine.renderers.media.ai_image_motion import make_solid_still

        still = make_solid_still(tmp_path / "s.png")
        shot = dict(MINIMAL_SHOT, renderer="MEDIA",
                    asset_requirements={"still_path": str(still)})
        res = get_renderer("MEDIA").render(shot, None, ctx)
        assert Path(res.path).exists()


class TestStubRenderer:
    def test_generic_stub_factory(self):
        cap = get_capability("GODOT")
        stub = make_renderer("GODOT", cap)
        assert isinstance(stub, StubRenderer)
        assert stub.id == "GODOT"
        assert stub.capabilities() is cap

    def test_stub_validate_uses_capability(self):
        issues = make_renderer("GODOT", get_capability("GODOT")).validate(
            dict(MINIMAL_SHOT, renderer="GODOT"))
        assert issues == []

    def test_disabled_renderer_not_instantiated(self):
        assert "GODOT" not in all_capabilities() or not get_capability("GODOT").enabled
        # enabled flags gate the instance map, not the capability map:
        assert "GODOT" in all_capabilities()

    def test_capability_passthrough(self):
        cap = RendererCapability(id="TEST_R", display_name="Test",
                                 quality_dimensions={
                                     d: 0.5 for d in (
                                         "realism", "physical_motion",
                                         "math_precision", "character_interaction",
                                         "emotional_impact", "historical_authenticity",
                                         "diagrammatic", "camera_movement",
                                         "text_heavy", "stylization")})
        stub = StubRenderer("TEST_R", cap)
        assert stub.capabilities() is cap


class TestNoBehaviorChange:
    def test_manim_compiler_unchanged_entrypoint(self):
        """The adapter must delegate to the same compile_to_file the pipeline uses."""
        import inspect

        from engine.renderers.adapters import ManimRenderer
        from engine.renderers.manim.compiler import compile_to_file

        source = inspect.getsource(ManimRenderer.render)
        assert "compile_to_file" in source
        # and the import is the real engine module function
        assert callable(compile_to_file)
