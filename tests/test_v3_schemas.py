"""test_v3_schemas.py — v3 Wave-1 schemas validate their canonical examples."""

import pytest

from engine.validation.schema import validate

SHOT_EXAMPLE = {
    "version": "v3",
    "shot_id": "S07",
    "duration_sec": 3.8,
    "narration_start": 18.2,
    "narration_end": 22.0,
    "narrative_role": "reveal",
    "visual_goal": "show the asteroid impact with escalating scale",
    "renderer": "AI_VIDEO",
    "fallback_renderer": "AI_IMAGE",
    "style": "cinematic_documentary",
    "subject": "asteroid entering atmosphere",
    "background": "clear dawn sky over ocean",
    "camera": "slow push-in",
    "motion": "fireball trailing smoke",
    "composition": "center-weighted, subject upper third",
    "text_overlay": None,
    "sfx": ["impact", "rumble"],
    "music_state": "build",
    "duck_music_db": -12.0,
    "asset_requirements": [{"kind": "video", "query": "asteroid impact"}],
    "generation_priority": "hero",
    "qa_requirements": ["no_distorted_anatomy", "subject_present"],
    "visual_budget_ref": "hero_ai_video_shots",
    "requirements": {"realism": True, "physical_motion": True,
                     "emotional_impact": True},
}

STYLE_EXAMPLE = {
    "version": "v2",
    "style_name": "cinematic_documentary",
    "palette": {"primary": "#0B1D3A", "accent": "#FF6B35", "mood": "dramatic"},
    "typography": {"title_font": "Inter Black", "body_font": "Inter"},
    "camera_language": "slow push-ins, occasional whip-pan pattern interrupts",
    "lighting": "golden hour, high contrast",
    "texture": "subtle film grain",
    "motion_language": "ease-out, unhurried",
    "transition_language": "match cuts, light leaks on reveals",
    "character_style": "none",
    "caption_style": {"position": "lower_third", "kinetic": False},
}

BUDGET_EXAMPLE = {
    "version": "v1",
    "topic": "why_dinosaurs_died",
    "target_duration_sec": 180.0,
    "budget": {
        "hero_ai_video_shots": 3,
        "ai_image_motion_shots": 5,
        "stock_or_archival_shots": 7,
        "motion_canvas_shots": 7,
        "pixijs_shots": 3,
        "manim_shots": 2,
        "pattern_interrupts": 8,
    },
    "max_hero_cost_share": 0.25,
    "notes": "example mix from directive §16",
}

CAPABILITY_EXAMPLE = {
    "id": "MANIM",
    "display_name": "Manim math/science visualization",
    "strengths": ["equations", "geometry"],
    "input_kinds": ["visualspec"],
    "output": "scene_file",
    "cost_tier": "LOW",
    "availability": {"enabled": True, "offline_capable": True,
                     "requires_network": False, "requires_remote_gpu": False},
    "quality_dimensions": {
        "realism": 0.05, "physical_motion": 0.3, "math_precision": 1.0,
        "character_interaction": 0.1, "emotional_impact": 0.15,
        "historical_authenticity": 0.05, "diagrammatic": 0.9,
        "camera_movement": 0.4, "text_heavy": 0.8, "stylization": 0.6,
    },
    "max_duration_sec": 30,
    "notes": "specialist renderer",
}

PROVIDER_REGISTRY_EXAMPLE = {
    "version": "v1",
    "providers": [
        {"id": "minimax_h3", "kind": "video", "models": ["MiniMax-H3"],
         "env_keys": ["MINIMAX_API_KEY"], "enabled": False, "priority": 0},
        {"id": "pexels", "kind": "stock", "env_keys": ["PEXELS_API_KEY"],
         "enabled": True, "priority": 5},
    ],
    "failover_policy": {"retry_transient": True, "max_retries": 2,
                        "failover_on_error": True, "cache_first": True},
}


class TestShotV3:
    def test_directive_example_validates(self):
        assert validate(SHOT_EXAMPLE, "shot_v3") == []

    def test_missing_renderer_rejected(self):
        bad = {k: v for k, v in SHOT_EXAMPLE.items() if k != "renderer"}
        assert validate(bad, "shot_v3")

    def test_bad_renderer_enum_rejected(self):
        bad = dict(SHOT_EXAMPLE, renderer="UNREAL_ENGINE")
        assert validate(bad, "shot_v3")

    def test_bad_shot_id_rejected(self):
        bad = dict(SHOT_EXAMPLE, shot_id="shot7")
        assert validate(bad, "shot_v3")

    def test_zero_duration_rejected(self):
        bad = dict(SHOT_EXAMPLE, duration_sec=0)
        assert validate(bad, "shot_v3")

    def test_unknown_field_rejected(self):
        bad = dict(SHOT_EXAMPLE, mystery_field=1)
        assert validate(bad, "shot_v3")

    def test_requirements_flags_only_known_dims(self):
        bad = dict(SHOT_EXAMPLE, requirements={"telepathy": True})
        assert validate(bad, "shot_v3")


class TestStyleSpecV2:
    def test_example_validates(self):
        assert validate(STYLE_EXAMPLE, "style_spec_v2") == []

    def test_style_name_required(self):
        bad = {k: v for k, v in STYLE_EXAMPLE.items() if k != "style_name"}
        assert validate(bad, "style_spec_v2")

    def test_wrong_version_rejected(self):
        assert validate(dict(STYLE_EXAMPLE, version="v1"), "style_spec_v2")


class TestVisualBudgetV1:
    def test_directive_example_validates(self):
        assert validate(BUDGET_EXAMPLE, "visual_budget_v1") == []

    def test_missing_budget_key_rejected(self):
        bad = {**BUDGET_EXAMPLE,
               "budget": {k: v for k, v in BUDGET_EXAMPLE["budget"].items()
                          if k != "pattern_interrupts"}}
        assert validate(bad, "visual_budget_v1")

    def test_negative_count_rejected(self):
        bad = {**BUDGET_EXAMPLE,
               "budget": dict(BUDGET_EXAMPLE["budget"], manim_shots=-1)}
        assert validate(bad, "visual_budget_v1")


class TestRendererCapabilityV1:
    def test_example_validates(self):
        assert validate(CAPABILITY_EXAMPLE, "renderer_capability_v1") == []

    def test_bad_cost_tier_rejected(self):
        bad = dict(CAPABILITY_EXAMPLE, cost_tier="EXPENSIVE")
        assert validate(bad, "renderer_capability_v1")

    def test_quality_dimension_out_of_range_rejected(self):
        qd = dict(CAPABILITY_EXAMPLE["quality_dimensions"], realism=1.5)
        bad = dict(CAPABILITY_EXAMPLE, quality_dimensions=qd)
        assert validate(bad, "renderer_capability_v1")

    def test_configs_renderers_yaml_matches_schema(self):
        """Every record in configs/renderers.yaml validates against the schema."""
        import yaml
        from pathlib import Path

        cfg = yaml.safe_load(
            (Path(__file__).resolve().parent.parent / "configs" / "renderers.yaml")
            .read_text()
        )
        for rid, record in cfg.items():
            if rid == "fallback_chain":
                continue
            errs = validate({"id": rid, **record}, "renderer_capability_v1")
            assert errs == [], f"{rid}: {errs}"


class TestProviderRegistryV1:
    def test_example_validates(self):
        assert validate(PROVIDER_REGISTRY_EXAMPLE, "provider_registry_v1") == []

    def test_bad_kind_rejected(self):
        bad = {**PROVIDER_REGISTRY_EXAMPLE,
               "providers": [dict(PROVIDER_REGISTRY_EXAMPLE["providers"][0],
                                  kind="quantum")]}
        assert validate(bad, "provider_registry_v1")

    def test_empty_providers_rejected(self):
        assert validate({"version": "v1", "providers": []}, "provider_registry_v1")
