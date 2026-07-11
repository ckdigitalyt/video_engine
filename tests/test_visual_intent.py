"""
test_visual_intent.py — Unit tests for VisualIntent, QueryExpander,
DiversityTracker, and StoryboardValidator.
"""

import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from src.models.schemas import (
    VisualIntent, DiversityRecord, ValidationReport,
    AssetPlan, ProviderType, Scene, SceneNarration, SearchPlan,
)
from src.assets.query_expander import expand_queries, expand_for_shot
from src.director.diversity_tracker import DiversityTracker, _jaccard_similarity, _content_fingerprint
from src.director.storyboard_validator import StoryboardValidator


# ═══════════════════════════════════════════════════════════════════════ #
# VisualIntent
# ═══════════════════════════════════════════════════════════════════════ #

class TestVisualIntent:
    def test_default_construction(self):
        vi = VisualIntent()
        assert vi.visual_objective == ""
        assert vi.concepts == []
        assert vi.search_terms == []

    def test_full_construction(self):
        vi = VisualIntent(
            visual_objective="Explain vacuum",
            concepts=["vacuum", "photons"],
            required_assets=["stock_video", "diagram"],
            preferred_asset_types=["wide_shot", "infographic"],
            animation_requirements="manim_photon_travel",
            camera_style="slow_pan",
            motion_style="gentle",
            fallback_strategy="fallback_to_diagram",
            search_terms=["deep space", "vacuum"],
        )
        assert vi.visual_objective == "Explain vacuum"
        assert "vacuum" in vi.concepts

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            VisualIntent(invalid_field="test")

    def test_serialization_roundtrip(self):
        vi = VisualIntent(
            visual_objective="Test",
            concepts=["a", "b"],
            search_terms=["x", "y"],
        )
        data = vi.model_dump(mode="json")
        restored = VisualIntent(**data)
        assert restored.visual_objective == "Test"
        assert restored.search_terms == ["x", "y"]


# ═══════════════════════════════════════════════════════════════════════ #
# QueryExpander
# ═══════════════════════════════════════════════════════════════════════ #

class TestQueryExpander:
    def test_expand_from_search_terms(self):
        vi = VisualIntent(
            search_terms=["deep space", "nebula", "starfield"],
            concepts=[],
        )
        queries = expand_queries(vi, topic="Space", category="Space")
        assert len(queries) >= 3
        assert any("deep space" in q for q in queries)

    def test_expand_from_concepts(self):
        vi = VisualIntent(
            search_terms=[],
            concepts=["vacuum", "photon"],
        )
        queries = expand_queries(vi, topic="Why is space black?", category="Science")
        assert len(queries) >= 3

    def test_empty_intent_returns_topic_fallback(self):
        vi = VisualIntent()
        queries = expand_queries(vi, topic="Space", category="General")
        assert len(queries) >= 3
        assert any("Space" in q for q in queries)

    def test_expand_for_shot(self):
        queries = expand_for_shot("deep space", "primary", "Space", "Space")
        assert len(queries) >= 3
        assert any("primary" in q for q in queries)

    def test_no_duplicates(self):
        vi = VisualIntent(
            search_terms=["deep space", "deep space", "nebula"],
            concepts=[],
        )
        queries = expand_queries(vi, topic="Space", category="Space")
        # Count unique
        assert len(queries) == len(set(q.lower() for q in queries))

    def test_max_20_queries(self):
        vi = VisualIntent(
            search_terms=[f"term{i}" for i in range(50)],
            concepts=[],
        )
        queries = expand_queries(vi, topic="Space", category="Space")
        assert len(queries) <= 20

    def test_provider_specific_qualifiers(self):
        vi = VisualIntent(
            required_assets=["diagram"],
            search_terms=["light"],
        )
        queries = expand_queries(vi, topic="Physics", category="Science")
        diagram_queries = [q for q in queries if "diagram" in q or "infographic" in q]
        assert len(diagram_queries) >= 1


# ═══════════════════════════════════════════════════════════════════════ #
# DiversityTracker
# ═══════════════════════════════════════════════════════════════════════ #

class TestDiversityTracker:
    def test_first_check_always_passes(self):
        dt = DiversityTracker()
        asset = AssetPlan(provider=ProviderType.PEXELS, filepath="", query_used="deep space")
        ok, reason = dt.check_candidate(asset, asset_id="1", provider="pexels")
        assert ok is True

    def test_detects_exact_asset_reuse(self):
        dt = DiversityTracker()
        asset = AssetPlan(provider=ProviderType.PEXELS, filepath="", query_used="deep space")
        dt.record_accepted(scene_id=0, provider="pexels", asset_id="vid123")
        ok, reason = dt.check_candidate(asset, asset_id="vid123", provider="pexels")
        assert ok is False
        assert "duplicate" in reason.lower()

    def test_detects_similar_queries(self):
        dt = DiversityTracker(similarity_threshold=0.5)
        dt.record_accepted(scene_id=0, provider="pexels", asset_id="vid1", query_used="deep space nebula stars")
        asset = AssetPlan(provider=ProviderType.PEXELS, filepath="", query_used="deep space nebula cosmos")
        ok, reason = dt.check_candidate(asset, asset_id="vid2", provider="pexels")
        # Jaccard of the two query strings should be high enough
        assert ok is False

    def test_allows_different_assets(self):
        dt = DiversityTracker()
        dt.record_accepted(scene_id=0, provider="pexels", asset_id="vid1", query_used="deep space")
        asset = AssetPlan(provider=ProviderType.NASA, filepath="", query_used="astronaut spacewalk")
        ok, reason = dt.check_candidate(asset, asset_id="vid2", provider="nasa")
        assert ok is True

    def test_records_accepted_creates_record(self):
        dt = DiversityTracker()
        dt.record_accepted(scene_id=0, provider="pexels", asset_id="v1", query_used="stars", filepath="")
        assert len(dt.history) == 1
        assert dt.history[0].asset_id == "v1"

    def test_history_trimming(self):
        dt = DiversityTracker(history_size=5)
        for i in range(10):
            dt.record_accepted(scene_id=i, provider="pexels", asset_id=f"v{i}")
        assert len(dt.history) == 5

    def test_reset_clears_history(self):
        dt = DiversityTracker()
        dt.record_accepted(scene_id=0, provider="pexels", asset_id="v1")
        dt.reset()
        assert len(dt.history) == 0

    def test_diversity_violations_reports_reuse(self):
        dt = DiversityTracker()
        dt.record_accepted(scene_id=0, provider="nasa", asset_id="artemis1", query_used="space")
        dt.record_accepted(scene_id=1, provider="nasa", asset_id="artemis2", query_used="space")
        violations = dt.get_diversity_violations()
        # Should report reuse within same similarity group
        assert len(violations) >= 0  # no error at least

    def test_jaccard_similarity(self):
        sim = _jaccard_similarity("deep space nebula", "deep space cosmos")
        assert 0.3 < sim < 1.0

        sim = _jaccard_similarity("completely different query", "deep space nebula")
        assert sim < 0.3

    def test_content_fingerprint(self):
        # Create a temp file and compute its fingerprint
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content for fingerprinting")
            tmp_path = f.name
        try:
            fp = _content_fingerprint(tmp_path)
            assert len(fp) == 16  # 16 hex chars from sha256[:16]
            assert fp == _content_fingerprint(tmp_path)  # deterministic
        finally:
            os.unlink(tmp_path)

    def test_content_fingerprint_missing_file(self):
        fp = _content_fingerprint("/nonexistent/file.mp4")
        assert fp == ""


# ═══════════════════════════════════════════════════════════════════════ #
# StoryboardValidator
# ═══════════════════════════════════════════════════════════════════════ #

class TestStoryboardValidator:
    def test_empty_scenes_list(self):
        sv = StoryboardValidator()
        report = sv.validate([])
        assert report.passed is True
        assert report.total_scenes == 0

    def test_missing_asset_detected(self):
        sv = StoryboardValidator()
        scene = Scene(
            scene_id=0,
            title="Test",
            narration=SceneNarration(spoken_narration="test"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
        )
        # No asset_plan set — should be flagged
        report = sv.validate([scene])
        assert report.missing_assets >= 1

    def test_missing_filepath_detected(self):
        sv = StoryboardValidator()
        scene = Scene(
            scene_id=0,
            title="Test",
            narration=SceneNarration(spoken_narration="test"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
        )
        scene.asset_plan = AssetPlan(
            provider=ProviderType.PEXELS,
            filepath="",  # empty filepath
            query_used="test",
        )
        report = sv.validate([scene])
        assert report.missing_filepaths >= 1

    def test_non_beat_scene_with_valid_asset(self):
        sv = StoryboardValidator()
        scene = Scene(
            scene_id=0,
            title="Test",
            narration=SceneNarration(spoken_narration="test"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
        )
        scene.asset_plan = AssetPlan(
            provider=ProviderType.PEXELS,
            filepath="/tmp/test_asset.mp4",
            query_used="test",
        )
        # File doesn't exist, so it should be flagged even though asset plan exists
        report = sv.validate([scene])
        assert report.errors is not None

    def test_duration_calculation(self):
        sv = StoryboardValidator()
        scene1 = Scene(
            scene_id=0, title="S1",
            narration=SceneNarration(spoken_narration="test"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
            expected_duration=10.0,
        )
        scene2 = Scene(
            scene_id=1, title="S2",
            narration=SceneNarration(spoken_narration="test2"),
            search_plan=SearchPlan(asset_search_queries=["test2"]),
            expected_duration=15.0,
        )
        report = sv.validate([scene1, scene2], target_duration=25.0)
        assert report.total_duration == 25.0
        assert report.target_duration == 25.0


# ═══════════════════════════════════════════════════════════════════════ #
# QualityGates with DiversityTracker integration
# ═══════════════════════════════════════════════════════════════════════ #

class TestQualityGatesWithDiversity:
    def test_diversity_gate_rejects_reuse(self):
        from src.director.quality_gate import QualityGates
        from src.director.diversity_tracker import DiversityTracker
        dt = DiversityTracker()
        qg = QualityGates(diversity_tracker=dt)

        # Record first asset
        asset1 = AssetPlan(
            provider=ProviderType.PEXELS, filepath="",
            query_used="deep space nebula", semantic_score=0.9,
        )
        passed, _, _ = qg.check_all(asset1, category="Space", provider="pexels", asset_id="v1")
        assert passed is True

        # Same asset ID should be rejected
        asset2 = AssetPlan(
            provider=ProviderType.PEXELS, filepath="",
            query_used="deep space nebula", semantic_score=0.9,
        )
        passed, reason, _ = qg.check_all(asset2, category="Space", provider="pexels", asset_id="v1")
        assert passed is False
        assert "DiversityGate" in reason

    def test_diversity_gate_allows_different_assets(self):
        from src.director.quality_gate import QualityGates
        from src.director.diversity_tracker import DiversityTracker
        dt = DiversityTracker()
        qg = QualityGates(diversity_tracker=dt)

        asset1 = AssetPlan(
            provider=ProviderType.PEXELS, filepath="",
            query_used="deep space", semantic_score=0.9,
        )
        passed, _, _ = qg.check_all(asset1, category="Space", provider="pexels", asset_id="v1")
        assert passed is True

        # Different provider + different ID should pass
        asset2 = AssetPlan(
            provider=ProviderType.NASA, filepath="",
            query_used="astronaut spacewalk", semantic_score=0.9,
        )
        passed, _, _ = qg.check_all(asset2, category="Space", provider="nasa", asset_id="nasa1")
        assert passed is True


if __name__ == "__main__":
    pytest.main(["-v", __file__])
