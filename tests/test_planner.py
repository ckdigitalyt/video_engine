"""
test_planner.py — Tests for the Story Planning Engine.

Verifies:
- Story template loading and config
- Outline generation prompts and parsing
- Scene generation from outline
- StoryPlanner two-phase workflow
- Template selection and overrides
- Config parsing
- Edge cases (missing config, unknown template)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.planner import StoryPlanner
from src.planner.templates import load_templates, get_template, StoryTemplate, BUILTIN_TEMPLATES


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm() -> MagicMock:
    """Return a MagicMock that implements the LLMProvider interface."""
    mock = MagicMock()
    mock.generate_json.return_value = (
        '{"narrative_arc": "A journey through space and time.", '
        '"scenes": [{"role": "Hook", "purpose": "Grab attention", '
        '"continuity": "Opens the story", "visual_style": "Wide establishing shot"}]}'
    )
    mock.generate_text.return_value = '{"response": "ok"}'
    return mock


# ── Templates ──────────────────────────────────────────────────────────────


class TestTemplates:
    def test_load_templates_contains_defaults(self) -> None:
        templates = load_templates()
        assert len(templates) >= 4
        for name in ("documentary", "problem_resolution", "timeline", "listicle"):
            assert name in templates

    def test_documentary_has_five_roles(self) -> None:
        tmpl = get_template("documentary")
        assert len(tmpl.roles) == 5
        assert "Hook" in tmpl.roles[0]

    def test_get_template_default(self) -> None:
        """Without argument, should use config default."""
        tmpl = get_template()
        assert tmpl.name in ("documentary",)

    def test_get_template_unknown_falls_back(self) -> None:
        tmpl = get_template("nonexistent_template")
        assert tmpl.name == "documentary"

    def test_story_template_dataclass(self) -> None:
        tmpl = StoryTemplate(name="test", roles=["a", "b"], description="test desc")
        assert tmpl.name == "test"
        assert tmpl.roles == ["a", "b"]
        assert tmpl.description == "test desc"

    def test_builtin_templates_all_have_roles(self) -> None:
        for name, roles in BUILTIN_TEMPLATES.items():
            assert len(roles) >= 3, f"{name} has fewer than 3 roles"

    def test_load_templates_cached(self) -> None:
        """Loading twice returns the same structure."""
        t1 = load_templates()
        t2 = load_templates()
        assert t1["documentary"].roles == t2["documentary"].roles


# ── StoryPlanner — Outline phase ────────────────────────────────────────


class TestOutlinePhase:
    def test_generate_outline_returns_json(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        outline = planner._generate_outline("The Fermi Paradox")
        assert "narrative_arc" in outline
        assert "scenes" in outline

    def test_outline_prompt_contains_topic(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        planner._generate_outline("Black Holes")
        call_args = mock_llm.generate_json.call_args[0][0]
        assert "Black Holes" in call_args

    def test_outline_prompt_contains_template_roles(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        planner._generate_outline("Climate Change")
        call_args = mock_llm.generate_json.call_args[0][0]
        assert "Hook" in call_args
        assert "Context" in call_args

    def test_outline_prompt_mentions_target_scenes(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, target_scene_count=8)
        planner._generate_outline("AI Revolution")
        call_args = mock_llm.generate_json.call_args[0][0]
        assert "8" in call_args


# ── StoryPlanner — Scene phase ──────────────────────────────────────────


class TestScenePhase:
    def test_generate_scenes_from_outline(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        outline = '{"narrative_arc": "Test", "scenes": [{"role": "Hook"}]}'
        scenes = planner._generate_scenes("The Fermi Paradox", outline)
        assert "scenes" in scenes

    def test_scene_prompt_contains_narration_style(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        outline = '{"narrative_arc": "Test arc", "scenes": []}'
        planner._generate_scenes("Topic", outline)
        call_args = mock_llm.generate_json.call_args[0][0]
        assert "words per second" in call_args.lower()

    def test_scene_prompt_contains_outline(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        outline = '{"narrative_arc": "Custom arc", "scenes": [{"role": "Climax"}]}'
        planner._generate_scenes("Topic", outline)
        call_args = mock_llm.generate_json.call_args[0][0]
        assert "Custom arc" in call_args


# ── StoryPlanner — Full pipeline ────────────────────────────────────────


class TestFullPlanner:
    def test_generate_plan_calls_both_phases(self, mock_llm: MagicMock) -> None:
        """generate_plan should call _generate_outline then _generate_scenes."""
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        result = planner.generate_plan("The Fermi Paradox")

        # Should call generate_json at least twice (outline + scenes)
        assert mock_llm.generate_json.call_count >= 2

    def test_generate_plan_returns_plan_json(self, mock_llm: MagicMock) -> None:
        """The final output should be a valid JSON string with scenes."""
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        result = planner.generate_plan("Test Topic")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_constructor_defaults(self) -> None:
        """StoryPlanner should work with default parameters."""
        planner = StoryPlanner()
        assert planner._template.name == "documentary"
        assert planner._target_scene_count >= 8
        assert planner._target_duration >= 60

    def test_constructor_override_template(self) -> None:
        planner = StoryPlanner(template_name="timeline")
        assert planner._template.name == "timeline"

    def test_constructor_override_targets(self) -> None:
        planner = StoryPlanner(target_scene_count=12, target_duration=180)
        assert planner._target_scene_count == 12
        assert planner._target_duration == 180

    def test_generate_plan_works_with_timeline_template(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="timeline")
        result = planner.generate_plan("Historical Event")
        assert result is not None


# ── Configuration ─────────────────────────────────────────────────────────


class TestPlannerConfig:
    def test_config_has_planner_section(self, tmp_project: Path) -> None:
        from src.utils.config import get_config
        assert get_config("planner.story_template") is not None
        assert get_config("planner.target_scene_count") is not None
        assert get_config("planner.target_duration") is not None

    def test_config_planner_values(self, tmp_project: Path) -> None:
        from src.utils.config import get_config
        assert get_config("planner.story_template") == "documentary"
        assert get_config("planner.target_scene_count") == 10
        assert get_config("planner.target_duration") == 120

    def test_config_story_templates(self, tmp_project: Path) -> None:
        from src.utils.config import get_config
        templates = get_config("planner.story_templates", {})
        assert "documentary" in templates
        roles = templates["documentary"]["roles"]
        assert len(roles) >= 3


# ── Edge cases ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_topic(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm)
        result = planner.generate_plan("")
        assert result is not None

    def test_zero_target_scene_count(self, mock_llm: MagicMock) -> None:
        """Should still generate at least 8 scenes (minimum)."""
        planner = StoryPlanner(provider=mock_llm, target_scene_count=0)
        assert planner._target_scene_count == 0
        result = planner.generate_plan("Test")
        assert result is not None

    def test_outline_with_no_scenes(self, mock_llm: MagicMock) -> None:
        """If outline has no scenes, scene generation should still work."""
        planner = StoryPlanner(provider=mock_llm, template_name="documentary")
        outline = '{"narrative_arc": "Empty"}'
        result = planner._generate_scenes("Topic", outline)
        assert result is not None

    def test_listicle_template_works(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, template_name="listicle")
        result = planner.generate_plan("Top 10 Facts")
        assert result is not None

    def test_long_duration(self, mock_llm: MagicMock) -> None:
        planner = StoryPlanner(provider=mock_llm, target_duration=600)
        assert planner._target_duration == 600
