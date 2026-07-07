"""Data isolation tests for Pydantic model pipeline.

Proves:
1. visual prompts can never reach TTS
2. narration can never reach asset search
3. editing instructions can never reach narration
4. metadata cannot leak anywhere
5. TTS ONLY receives SceneNarration.spoken_narration
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.models.schemas import (
    Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan,
    AssetPlan, AudioPlan, RenderPlan, PipelineState,
    ProviderType, CameraMotion, TransitionType,
)


class TestNarrationIsolation:
    """Prove narration NEVER reaches TTS or asset search."""

    def test_tts_only_receives_spoken_narration(self):
        """Scene.to_tts_dict() must ONLY contain spoken_narration text."""
        scene = Scene(
            scene_id=0,
            title="Test",
            narration=SceneNarration(spoken_narration="Only this text reaches TTS"),
            visual_plan=VisualPlan(
                visual_description="A majestic landscape with mountains",
                camera_motion=CameraMotion.PAN_LEFT,
            ),
            search_plan=SearchPlan(
                asset_search_queries=["mountain landscape", "valley"],
                negative_search_queries=["city", "people"],
            ),
            editing_plan=EditingPlan(
                editing_instructions="Slow reveal with crossfade",
                camera_motion=CameraMotion.ZOOM_IN,
                transition_in=TransitionType.FADE,
            ),
            metadata={"source": "test", "version": "1.0"},
        )

        tts_result = scene.to_tts_dict()
        assert tts_result == {"text": "Only this text reaches TTS"}, (
            f"TTS dict contains wrong data: {tts_result}"
        )

        # Verify visual description did NOT leak
        assert "landscape" not in tts_result["text"], (
            "Visual description leaked into TTS output!"
        )

        # Verify search queries did NOT leak
        assert "mountain" not in tts_result["text"], (
            "Search query leaked into TTS output!"
        )

        # Verify editing instructions did NOT leak
        assert "Slow reveal" not in tts_result["text"], (
            "Editing instructions leaked into TTS output!"
        )

        # Verify metadata did NOT leak
        assert "test" not in tts_result["text"].lower() or \
               tts_result["text"].lower() == "only this text reaches tts", (
            "Metadata leaked into TTS output!"
        )

    def test_tts_input_direct_call(self):
        """Narration.to_tts_input() must return ONLY spoken text."""
        narration = SceneNarration(spoken_narration="Pure narration text")
        result = narration.to_tts_input()
        assert result == "Pure narration text"
        assert isinstance(result, str)
        assert len(result) < 100  # Ensures no extra data appended

    def test_search_plan_has_no_narration_field(self):
        """SearchPlan must NOT have a narration field."""
        plan = SearchPlan(
            asset_search_queries=["test query"],
        )
        assert not hasattr(plan, "narration")
        assert not hasattr(plan, "spoken_narration")
        assert not hasattr(plan, "visual_description")

    def test_search_plan_rejects_narration_leak(self):
        """SearchPlan must reject queries that are narration text."""
        # Query must be >100 chars (the SearchPlan validation limit)
        with pytest.raises(Exception):
            SearchPlan(
                asset_search_queries=[
                    "This is a very long query that should be rejected by "
                    "the search plan validation because it exceeds the maximum "
                    "length of 100 characters for any single search query"
                ],
            )

    def test_search_plan_rejects_high_overlap_with_narration(self):
        """Scene validator must catch >50% word overlap between narration and queries."""
        with pytest.raises(Exception):
            Scene(
                scene_id=0,
                narration=SceneNarration(
                    spoken_narration="The universe is vast and mysterious"
                ),
                search_plan=SearchPlan(
                    asset_search_queries=[
                        "universe is vast and mysterious cosmos"
                    ],
                ),
            )

    def test_visual_plan_has_no_narration_field(self):
        """VisualPlan must NOT have a narration field."""
        plan = VisualPlan()
        assert not hasattr(plan, "spoken_narration")
        assert not hasattr(plan, "narration")

    def test_editing_plan_has_no_narration_field(self):
        """EditingPlan must NOT have a narration field."""
        plan = EditingPlan()
        assert not hasattr(plan, "spoken_narration")
        assert not hasattr(plan, "narration")


class TestVisualPromptIsolation:
    """Prove visual prompts can never reach TTS."""

    def test_visual_description_isolated_from_tts(self):
        """VisualPlan.visual_description must NOT appear in TTS input."""
        scene = Scene(
            scene_id=0,
            narration=SceneNarration(spoken_narration="Count to three"),
            visual_plan=VisualPlan(
                visual_description="Cinematic shot showing three distinct objects",
            ),
            search_plan=SearchPlan(asset_search_queries=["test"]),
        )
        tts_text = scene.to_tts_dict()["text"]
        assert "Cinematic" not in tts_text
        assert "three" in tts_text

    def test_camera_motion_isolated_from_tts(self):
        """Camera motion must not appear in TTS input."""
        scene = Scene(
            scene_id=0,
            narration=SceneNarration(spoken_narration="Hello world"),
            visual_plan=VisualPlan(camera_motion=CameraMotion.KEN_BURNS),
            search_plan=SearchPlan(asset_search_queries=["test"]),
        )
        tts_text = scene.to_tts_dict()["text"]
        assert "ken" not in tts_text.lower()
        assert "burn" not in tts_text.lower()


class TestEditingInstructionIsolation:
    """Prove editing instructions cannot reach narration."""

    def test_editing_instruction_rejected_in_narration(self):
        """SceneNarration validator must reject metadata-like prefixes."""
        with pytest.raises(Exception):
            SceneNarration(
                spoken_narration="transition: fade this scene into the next"
            )

        with pytest.raises(Exception):
            SceneNarration(
                spoken_narration="camera: zoom in on the subject"
            )

    def test_editing_instructions_not_in_tts(self):
        """EditingPlan contents must not appear in TTS output."""
        scene = Scene(
            scene_id=0,
            narration=SceneNarration(spoken_narration="The story continues"),
            visual_plan=VisualPlan(camera_motion=CameraMotion.STATIC),
            search_plan=SearchPlan(asset_search_queries=["test"]),
            editing_plan=EditingPlan(
                editing_instructions="Fast-paced cuts with dramatic transitions",
                transition_in=TransitionType.WIPE_LEFT,
                camera_motion=CameraMotion.TRUCK_IN,
            ),
        )
        tts_text = scene.to_tts_dict()["text"]
        assert "fast" not in tts_text.lower()
        assert "cuts" not in tts_text.lower()
        assert "wipe" not in tts_text.lower()
        assert "truck" not in tts_text.lower()


class TestMetadataIsolation:
    """Prove metadata cannot leak anywhere."""

    def test_metadata_not_in_tts(self):
        """Metadata must not appear in TTS output."""
        scene = Scene(
            scene_id=0,
            narration=SceneNarration(spoken_narration="Hello world"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
            metadata={"api_key": "sk-12345", "secret": "abc"},
        )
        tts_text = scene.to_tts_dict()["text"]
        assert "sk-12345" not in tts_text
        assert "abc" not in tts_text

    def test_metadata_not_searchable(self):
        """Metadata must not be accessible via SearchPlan."""
        scene = Scene(
            scene_id=0,
            narration=SceneNarration(spoken_narration="Hello"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
            metadata={"internal_note": "classified"},
        )
        assert "internal_note" not in scene.search_plan.model_dump()
        assert "metadata" not in scene.search_plan.model_dump()

    def test_metadata_not_visual(self):
        """Metadata must not be accessible via VisualPlan."""
        scene = Scene(
            scene_id=0,
            narration=SceneNarration(spoken_narration="Hello"),
            search_plan=SearchPlan(asset_search_queries=["test"]),
            visual_plan=VisualPlan(visual_description="A scene"),
            metadata={"render_cost": "$5.00"},
        )
        vis_dump = scene.visual_plan.model_dump()
        assert "render_cost" not in str(vis_dump)
        assert "metadata" not in vis_dump


class TestSceneModelValidation:
    """Prove Scene model enforces strict typing."""

    def test_extra_fields_forbidden(self):
        """Scene must reject extra fields."""
        with pytest.raises(Exception):
            Scene(
                scene_id=0,
                narration=SceneNarration(spoken_narration="test"),
                search_plan=SearchPlan(asset_search_queries=["test"]),
                illegal_field="should not be accepted",
            )

    def test_scene_id_required(self):
        """scene_id must be provided."""
        with pytest.raises(Exception):
            Scene(
                narration=SceneNarration(spoken_narration="test"),
                search_plan=SearchPlan(asset_search_queries=["test"]),
            )

    def test_expected_duration_positive(self):
        """expected_duration must be positive."""
        with pytest.raises(Exception):
            Scene(
                scene_id=0,
                narration=SceneNarration(spoken_narration="test"),
                search_plan=SearchPlan(asset_search_queries=["test"]),
                expected_duration=-1,
            )

    def test_pipeline_state_scene_ids_continuous(self):
        """PipelineState must validate continuous scene IDs."""
        with pytest.raises(Exception):
            PipelineState(
                topic="test",
                scenes=[
                    Scene(scene_id=0, narration=SceneNarration(spoken_narration="A"),
                          search_plan=SearchPlan(asset_search_queries=["a"])),
                    Scene(scene_id=2, narration=SceneNarration(spoken_narration="B"),
                          search_plan=SearchPlan(asset_search_queries=["b"])),
                ],
            )

    def test_pipeline_state_accepts_valid(self):
        """PipelineState must accept valid continuous scenes."""
        state = PipelineState(
            topic="test",
            scenes=[
                Scene(scene_id=0, narration=SceneNarration(spoken_narration="A"),
                      search_plan=SearchPlan(asset_search_queries=["a"])),
                Scene(scene_id=1, narration=SceneNarration(spoken_narration="B"),
                      search_plan=SearchPlan(asset_search_queries=["b"])),
            ],
        )
        assert len(state.scenes) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
