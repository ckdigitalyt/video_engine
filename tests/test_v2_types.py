"""
test_v2_types.py — Tests for V2 Pydantic models and enums.

Coverage plan:
  1. All enums have expected values
  2. All models construct with defaults
  3. All models serialize/deserialize (JSON round-trip)
  4. Field validation (min/max, length, etc.)
  5. Edge cases (empty lists, None optionals)
  6. Nested model construction
"""

import json

import pytest
from pydantic import ValidationError

from src.models.v2_types import (
    # Enums
    TopicCategory,
    EmotionalTone,
    NarrativeRole,
    ShotType,
    CameraMotion,
    TransitionType,
    AssetProvider,
    CriticSeverity,
    # Models
    Source,
    Fact,
    ResearchDocument,
    KnowledgeNode,
    KnowledgeEdge,
    KnowledgeGraph,
    NarrativeBeat,
    NarrativeArc,
    SceneDialogue,
    SceneV2,
    VisualQuery,
    CameraDirection,
    ShotV2,
    ColorGrade,
    SubtitleLine,
    SceneAudioPlan,
    VisualPlan,
    AssetRecord,
    AnimationJob,
    SegmentRenderJob,
    CriticIssue,
    VisualCriticResult,
    AudioCriticResult,
    PacingCriticResult,
    VideoCriticReport,
    ImprovementAction,
    PipelineStateV2,
)


# ── Enum tests ─────────────────────────────────────────────────────────────


class TestEnums:
    """V2 enums have expected values."""

    def test_topic_category_values(self):
        assert TopicCategory.SPACE == "space"
        assert TopicCategory.SCIENCE == "science"
        assert TopicCategory.HISTORY == "history"
        assert TopicCategory.NATURE == "nature"
        assert TopicCategory.TECHNOLOGY == "technology"
        assert TopicCategory.FINANCE == "finance"
        assert TopicCategory.GENERAL == "general"

    def test_topic_category_members(self):
        assert len(TopicCategory) == 7

    def test_emotional_tone_values(self):
        assert EmotionalTone.WONDER == "wonder"
        assert EmotionalTone.NEUTRAL == "neutral"
        assert EmotionalTone.TENSION == "tension"

    def test_shot_type_values(self):
        assert ShotType.PRIMARY == "primary"
        assert ShotType.ANIMATION == "animation"
        assert ShotType.DATA_VIZ == "data_viz"

    def test_camera_motion_values(self):
        assert CameraMotion.STATIC == "static"
        assert CameraMotion.KEN_BURNS_IN == "ken_burns_in"
        assert CameraMotion.PARALLAX == "parallax"

    def test_transition_type_values(self):
        assert TransitionType.CUT == "cut"
        assert TransitionType.DIP_TO_BLACK == "dip_to_black"

    def test_asset_provider_values(self):
        assert AssetProvider.PEXELS == "pexels"
        assert AssetProvider.PIXABAY == "pixabay"
        assert AssetProvider.EMERGENCY == "emergency"

    def test_critic_severity_values(self):
        assert CriticSeverity.CRITICAL == "critical"
        assert CriticSeverity.INFO == "info"


# ── Source tests ───────────────────────────────────────────────────────────


class TestSource:
    def test_default_construction(self):
        s = Source()
        assert s.url == ""
        assert s.title == ""
        assert s.domain == ""
        assert s.snippet == ""
        assert s.relevance_score == 0.0

    def test_full_construction(self):
        s = Source(url="https://example.com", title="Test", domain="example.com",
                    snippet="Example snippet", relevance_score=0.85)
        assert s.url == "https://example.com"
        assert s.relevance_score == 0.85

    def test_relevance_score_range(self):
        with pytest.raises(ValidationError):
            Source(relevance_score=1.5)
        with pytest.raises(ValidationError):
            Source(relevance_score=-0.1)

    def test_json_round_trip(self):
        s = Source(url="https://a.com", title="A", snippet="Some text", relevance_score=0.5)
        data = s.model_dump_json()
        restored = Source.model_validate_json(data)
        assert restored.url == s.url
        assert restored.relevance_score == s.relevance_score


# ── Fact tests ─────────────────────────────────────────────────────────────


class TestFact:
    def test_default_construction(self):
        f = Fact(claim="Test claim")
        assert f.claim == "Test claim"
        assert len(f.id) == 8  # UUID first 8 chars
        assert f.sources == []
        assert f.confidence == 0.0
        assert f.verified is False

    def test_with_sources(self):
        sources = [Source(url="https://a.com"), Source(url="https://b.com")]
        f = Fact(claim="Test", sources=sources, confidence=0.9)
        assert len(f.sources) == 2
        assert f.confidence == 0.9

    def test_confidence_range(self):
        with pytest.raises(ValidationError):
            Fact(claim="x", confidence=2.0)
        with pytest.raises(ValidationError):
            Fact(claim="x", confidence=-0.1)

    def test_unique_ids(self):
        f1 = Fact(claim="A")
        f2 = Fact(claim="B")
        assert f1.id != f2.id  # Practically guaranteed by UUID

    def test_json_round_trip(self):
        f = Fact(claim="Test claim", sources=[Source(url="https://a.com")],
                  confidence=0.75, verified=True)
        data = f.model_dump_json()
        restored = Fact.model_validate_json(data)
        assert restored.claim == f.claim
        assert len(restored.sources) == 1
        assert restored.verified is True


# ── ResearchDocument tests ─────────────────────────────────────────────────


class TestResearchDocument:
    def test_default_construction(self):
        doc = ResearchDocument(topic="Test Topic")
        assert doc.topic == "Test Topic"
        assert doc.sources == []
        assert doc.key_facts == []
        assert doc.key_statistics == []

    def test_with_full_data(self):
        sources = [Source(url="https://a.com")]
        facts = [Fact(claim="Fact 1", sources=sources)]
        doc = ResearchDocument(
            topic="Fermi Paradox",
            sources=sources,
            key_facts=facts,
            key_statistics=["100 billion stars"],
            key_dates=[{"date": "1950", "event": "Fermi asked the question"}],
            key_people=["Enrico Fermi"],
            controversies=["Great Filter hypothesis"],
            timelines=[{"year": 1950, "event": "Fermi Paradox"}],
            unanswered_questions=["Where is everybody?"],
        )
        assert len(doc.key_facts) == 1
        assert doc.key_facts[0].claim == "Fact 1"
        assert len(doc.key_people) == 1

    def test_json_round_trip(self):
        facts = [Fact(claim="C1", confidence=0.8)]
        doc = ResearchDocument(topic="T", key_facts=facts, key_people=["P1"])
        data = doc.model_dump_json()
        restored = ResearchDocument.model_validate_json(data)
        assert restored.topic == "T"
        assert len(restored.key_facts) == 1
        assert restored.key_facts[0].claim == "C1"

    def test_empty_optional_lists(self):
        doc = ResearchDocument(topic="T", key_facts=[], key_people=[],
                                 controversies=[], unanswered_questions=[])
        assert doc.key_statistics == []


# ── Knowledge Graph tests ──────────────────────────────────────────────────


class TestKnowledgeGraph:
    def test_minimal(self):
        kg = KnowledgeGraph(topic="Test")
        assert kg.nodes == []
        assert kg.edges == []

    def test_with_nodes_and_edges(self):
        n1 = KnowledgeNode(id="n1", label="Fermi Paradox", type="concept")
        n2 = KnowledgeNode(id="n2", label="Enrico Fermi", type="person")
        e = KnowledgeEdge(source_id="n1", target_id="n2", relationship="posed_by")
        kg = KnowledgeGraph(topic="Fermi", nodes=[n1, n2], edges=[e])
        assert len(kg.nodes) == 2
        assert len(kg.edges) == 1
        assert kg.edges[0].relationship == "posed_by"


# ── Narrative tests ────────────────────────────────────────────────────────


class TestNarrativeBeat:
    def test_minimal(self):
        beat = NarrativeBeat(index=0, role=NarrativeRole.HOOK)
        assert beat.index == 0
        assert beat.role == NarrativeRole.HOOK

    def test_default_tone(self):
        beat = NarrativeBeat(index=1, role=NarrativeRole.CLIMAX)
        assert beat.emotional_tone == EmotionalTone.NEUTRAL


class TestNarrativeArc:
    def test_defaults(self):
        arc = NarrativeArc(topic="Test")
        assert arc.total_target_duration == 480.0
        assert arc.beats == []

    def test_with_beats(self):
        beats = [NarrativeBeat(index=0, role=NarrativeRole.HOOK)]
        arc = NarrativeArc(topic="T", beats=beats)
        assert len(arc.beats) == 1


# ── Scene tests ────────────────────────────────────────────────────────────


class TestSceneV2:
    def test_construction(self):
        dialogues = [SceneDialogue(text="Hello")]
        scene = SceneV2(scene_id=0, title="Intro", narration_segments=dialogues,
                         target_duration=60.0)
        assert scene.target_duration == 60.0
        assert scene.transition_in == TransitionType.CROSSFADE

    def test_json_round_trip(self):
        d = SceneDialogue(text="Narration text", emphasis_words=["key"])
        scene = SceneV2(scene_id=1, title="Test", narration_segments=[d],
                         target_duration=45.0, scene_purpose="Explain concept")
        data = scene.model_dump_json()
        restored = SceneV2.model_validate_json(data)
        assert restored.scene_id == 1
        assert restored.target_duration == 45.0
        assert restored.narration_segments[0].text == "Narration text"


# ── Visual Plan tests ──────────────────────────────────────────────────────


class TestShotV2:
    def test_construction(self):
        shot = ShotV2(scene_id=0, shot_type=ShotType.PRIMARY, start_ms=0, end_ms=5000)
        assert shot.shot_type == ShotType.PRIMARY
        assert shot.transition_in == TransitionType.CROSSFADE

    def test_with_animation(self):
        shot = ShotV2(scene_id=0, shot_type=ShotType.ANIMATION, start_ms=0, end_ms=10000,
                       animation_template="comparison_bars", animation_params={"data": [1, 2]})
        assert shot.animation_template == "comparison_bars"

    def test_unique_shot_ids(self):
        s1 = ShotV2(scene_id=0, shot_type=ShotType.PRIMARY, start_ms=0, end_ms=1000)
        s2 = ShotV2(scene_id=0, shot_type=ShotType.PRIMARY, start_ms=0, end_ms=1000)
        assert s1.shot_id != s2.shot_id


class TestVisualPlan:
    def test_defaults(self):
        plan = VisualPlan()
        assert plan.timeline_version == "2.0"
        assert plan.render_settings == {"resolution": [1920, 1080], "fps": 30}
        assert plan.scenes == []

    def test_with_scenes_and_shots(self):
        s = SceneV2(scene_id=0, title="S1", narration_segments=[SceneDialogue(text="T")],
                     target_duration=30.0)
        sh = ShotV2(scene_id=0, shot_type=ShotType.PRIMARY, start_ms=0, end_ms=5000)
        plan = VisualPlan(scenes=[s], shots=[sh])
        assert len(plan.scenes) == 1
        assert len(plan.shots) == 1


# ── Asset & Render tests ───────────────────────────────────────────────────


class TestAssetRecord:
    def test_defaults(self):
        a = AssetRecord(shot_id="s1")
        assert a.provider == AssetProvider.EMERGENCY
        assert a.width == 1920
        assert a.height == 1080

    def test_full(self):
        a = AssetRecord(shot_id="s1", provider=AssetProvider.PEXELS,
                         source_url="https://example.com/v.mp4",
                         local_path="cache/video/s1.mp4", duration=15.0,
                         semantic_score=0.9, technical_score=0.8)
        assert a.semantic_score == 0.9


class TestAnimationJob:
    def test_defaults(self):
        j = AnimationJob(job_id="j1", template_name="bars")
        assert j.priority == 5
        assert j.estimated_runtime_s == 30.0


class TestSegmentRenderJob:
    def test_defaults(self):
        j = SegmentRenderJob(segment_id="seg-001", start_ms=0, end_ms=60000)
        assert j.codec == "libx264"
        assert j.crf == 18


# ── Critic tests ───────────────────────────────────────────────────────────


class TestCriticIssue:
    def test_construction(self):
        issue = CriticIssue(severity=CriticSeverity.MAJOR, category="audio",
                             description="Audio clipping detected")
        assert issue.severity == CriticSeverity.MAJOR


class TestVideoCriticReport:
    def test_defaults(self):
        report = VideoCriticReport(video_id="v1")
        assert report.overall_score == 0.0
        assert report.recommended_action == "approve"
        assert report.visual.frames_checked == 10

    def test_with_results(self):
        visual = VisualCriticResult(frames_checked=10, frames_passed=8,
                                     pass_rate=0.8)
        report = VideoCriticReport(video_id="v1", visual=visual,
                                    overall_score=0.75)
        assert report.visual.pass_rate == 0.8
        assert report.overall_score == 0.75


# ── Improvement tests ──────────────────────────────────────────────────────


class TestImprovementAction:
    def test_defaults(self):
        action = ImprovementAction(action_type="rerender_segment", target="seg-03")
        assert action.priority == 5
        assert action.estimated_time_s == 30.0


# ── Pipeline State tests ───────────────────────────────────────────────────


class TestPipelineStateV2:
    def test_defaults(self):
        state = PipelineStateV2(topic="Fermi Paradox")
        assert state.topic == "Fermi Paradox"
        assert state.status == "initialized"
        assert state.max_iterations == 3
        assert len(state.run_id) == 8

    def test_with_research(self):
        doc = ResearchDocument(topic="Fermi Paradox", key_facts=[Fact(claim="C1")])
        state = PipelineStateV2(topic="Fermi Paradox", status="researching",
                                 research_document=doc)
        assert state.research_document is not None
        assert len(state.research_document.key_facts) == 1

    def test_status_transitions(self):
        for status in ["initialized", "researching", "verified", "planning",
                       "acquiring", "rendering", "critiquing", "improving", "complete"]:
            state = PipelineStateV2(topic="T", status=status)
            assert state.status == status

    def test_stage_timing(self):
        state = PipelineStateV2(topic="T", stages_elapsed={"research": 45.2})
        assert state.stages_elapsed["research"] == 45.2


# ── Model import guard tests ───────────────────────────────────────────────


class TestModelImports:
    """All V2 types import correctly from the expected path."""

    def test_import_v2_types_module(self):
        import importlib
        mod = importlib.import_module("src.models.v2_types")
        assert hasattr(mod, "ResearchDocument")
        assert hasattr(mod, "Source")
        assert hasattr(mod, "Fact")
        assert hasattr(mod, "KnowledgeGraph")
        assert hasattr(mod, "NarrativeArc")
        assert hasattr(mod, "SceneV2")
        assert hasattr(mod, "VisualPlan")
        assert hasattr(mod, "ShotV2")
        assert hasattr(mod, "VideoCriticReport")
        assert hasattr(mod, "PipelineStateV2")
