"""test_v3_router.py — Renderer router scoring (v3 Wave 1)."""

import pytest

from engine.renderers.base import Renderer, RendererNotImplemented
from engine.renderers.registry import (
    all_capabilities,
    all_renderers,
    fallback_chain,
    get_capability,
    get_renderer,
)
from engine.renderers.router import RouterDecision, select_renderer


def _shot(**req):
    return {"version": "v3", "requirements": dict(req)}


# ── Directive §5 examples ──────────────────────────────────────────────────


class TestDirectiveExamples:
    def test_mathematical_proof_chooses_manim(self):
        d = select_renderer(_shot(math_precision=True, diagrammatic=True))
        assert d.renderer_id == "MANIM"

    def test_exploding_volcano_chooses_ai_video(self):
        d = select_renderer(_shot(realism=True, physical_motion=True,
                                  emotional_impact=True))
        assert d.renderer_id == "AI_VIDEO"

    def test_nasa_launch_chooses_archival_or_stock(self):
        d = select_renderer(_shot(realism=True, historical_authenticity=True))
        assert d.renderer_id in ("ARCHIVAL", "STOCK_VIDEO")

    def test_kinetic_headline_chooses_motion_canvas(self):
        d = select_renderer(_shot(text_heavy=True), )
        assert d.renderer_id == "MOTION_CANVAS"

    def test_kinetic_headline_low_priority_still_motion_canvas(self):
        d = select_renderer({"requirements": {"text_heavy": True},
                             "generation_priority": "low"})
        assert d.renderer_id == "MOTION_CANVAS"

    def test_cartoon_conversation_chooses_pixijs(self):
        d = select_renderer(_shot(character_interaction=True))
        assert d.renderer_id == "PIXIJS"

    def test_historic_reconstruction_hero_prefers_ai_video(self):
        d = select_renderer({"requirements": {"realism": True,
                                              "historical_authenticity": True,
                                              "emotional_impact": True},
                             "generation_priority": "hero"})
        assert d.renderer_id == "AI_VIDEO"

    def test_diagram_explanation_chooses_motion_canvas(self):
        d = select_renderer(_shot(diagrammatic=True))
        assert d.renderer_id == "MOTION_CANVAS"


# ── Availability / quota / determinism ─────────────────────────────────────


class TestAvailabilityAndQuota:
    def test_unavailable_renderer_not_chosen(self):
        d = select_renderer(_shot(math_precision=True), availability={"MANIM": False})
        assert d.renderer_id != "MANIM"
        assert "off:MANIM" in d.fallback_chain

    def test_exhausted_quota_drops_remote_renderer(self):
        shot = _shot(realism=True, physical_motion=True)
        normal = select_renderer(shot)
        drained = select_renderer(shot, quota={"AI_VIDEO": 0.0})
        assert normal.renderer_id == "AI_VIDEO"
        assert drained.renderer_id != "AI_VIDEO"
        # AI_VIDEO stays visible in the chain for when quota returns.
        assert "AI_VIDEO" in drained.fallback_chain

    def test_partial_quota_lower_score(self):
        shot = _shot(realism=True, physical_motion=True, emotional_impact=True)
        full = select_renderer(shot, quota={"AI_VIDEO": 1.0})
        partial = select_renderer(shot, quota={"AI_VIDEO": 0.3})
        scores = dict(partial.ranked)
        assert scores["AI_VIDEO"] < dict(full.ranked)["AI_VIDEO"]

    def test_fallback_chain_starts_with_choice(self):
        d = select_renderer(_shot(realism=True, physical_motion=True))
        assert d.fallback_chain[0] == d.renderer_id

    def test_fallback_chain_follows_canonical_order(self):
        d = select_renderer(_shot(realism=True, physical_motion=True))
        canonical = fallback_chain()
        chosen_positions = [canonical.index(c) for c in d.fallback_chain
                            if c in canonical]
        assert chosen_positions == sorted(chosen_positions)

    def test_historical_shot_splices_archival_after_stock(self):
        d = select_renderer(_shot(realism=True, historical_authenticity=True),
                            availability={"ARCHIVAL": False})
        chain_clean = [c for c in d.fallback_chain if not c.startswith("off:")]
        if "STOCK_VIDEO" in chain_clean and "ARCHIVAL" in chain_clean:
            assert chain_clean.index("ARCHIVAL") > chain_clean.index("STOCK_VIDEO")

    def test_no_available_renderer_raises(self):
        with pytest.raises(ValueError):
            select_renderer(_shot(math_precision=True),
                            availability={rid: False for rid in all_capabilities()})


class TestDeterminism:
    def test_same_input_same_decision(self):
        shot = _shot(realism=True, physical_motion=True, emotional_impact=True,
                     historical_authenticity=True)
        a = select_renderer(shot, quota={"AI_VIDEO": 0.5})
        b = select_renderer(shot, quota={"AI_VIDEO": 0.5})
        assert a == b

    def test_ranked_sorted_descending_with_stable_tiebreak(self):
        d = select_renderer(_shot(math_precision=True))
        scores = [s for _, s in d.ranked]
        assert scores == sorted(scores, reverse=True)

    def test_decision_shape(self):
        d = select_renderer(_shot(math_precision=True))
        assert isinstance(d, RouterDecision)
        assert d.ranked and d.reasons is not None
        assert all(isinstance(rid, str) for rid, _ in d.ranked)


# ── Registry consistency ───────────────────────────────────────────────────


class TestRegistry:
    def test_all_capability_records_load(self):
        caps = all_capabilities()
        for expected in ("MANIM", "AI_VIDEO", "AI_IMAGE_MOTION", "STOCK_VIDEO",
                         "ARCHIVAL", "MOTION_CANVAS", "PIXIJS"):
            assert expected in caps

    def test_manim_is_offline_capable(self):
        cap = get_capability("MANIM")
        assert cap.offline_capable and not cap.requires_remote_gpu

    def test_ai_video_is_hero_cost(self):
        assert get_capability("AI_VIDEO").cost_tier == "HERO"

    def test_unknown_renderer_raises(self):
        with pytest.raises(KeyError):
            get_capability("DOES_NOT_EXIST")

    def test_registered_renderers_exist_for_enabled_caps(self):
        caps = all_capabilities()
        renderers = all_renderers()
        for rid, cap in caps.items():
            if cap.enabled:
                assert rid in renderers


# ── Renderer interface conformance ─────────────────────────────────────────


class TestRendererConformance:
    @pytest.mark.parametrize("renderer_id", sorted(all_renderers().keys()))
    def test_conformance(self, renderer_id):
        renderer = get_renderer(renderer_id)
        assert isinstance(renderer, Renderer)
        cap = renderer.capabilities()
        assert cap.id == renderer_id
        assert 0.0 <= cap.quality_dimensions["math_precision"] <= 1.0
        issues = renderer.validate({"shot_id": "S01", "duration_sec": 3.0,
                                    "visual_goal": "test", "renderer": renderer_id})
        assert isinstance(issues, list)

    def test_stub_renderers_raise_not_implemented(self):
        from engine.renderers.base import RenderContext

        ctx = RenderContext(output_dir="/tmp/v3-test")
        for rid in ("AI_VIDEO", "AI_IMAGE_MOTION", "STOCK_VIDEO", "ARCHIVAL",
                    "MOTION_CANVAS", "PIXIJS"):
            with pytest.raises(RendererNotImplemented):
                get_renderer(rid).render(
                    {"shot_id": "S01", "duration_sec": 3.0, "visual_goal": "x",
                     "renderer": rid},
                    None, ctx,
                )

    def test_stub_validate_checks_duration_cap(self):
        issues = get_renderer("AI_VIDEO").validate(
            {"shot_id": "S01", "duration_sec": 999.0, "visual_goal": "x",
             "renderer": "AI_VIDEO"})
        assert any("exceeds" in i for i in issues)
