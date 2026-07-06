"""
test_effects.py — Tests for cinematic motion and transition engines.

Verifies:
- MotionEngine generates deterministic Ken Burns descriptors
- Motion types are valid (zoom_in, zoom_out, pan_*, none)
- TransitionEngine generates transitions between clips
- Transition types are valid
- Disabled mode returns static descriptors
- Renderer integration with effects
- Configuration parsing
- Deterministic output (same seed → same result)
- Edge cases (0 clips, 1 clip, disabled, custom config)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.effects import MotionEngine, TransitionEngine
from src.effects.motion import MOTION_TYPES
from src.effects.transitions import TRANSITION_TYPES


# ── MotionEngine ───────────────────────────────────────────────────────────


class TestMotionEngine:
    def test_generates_correct_count(self) -> None:
        me = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=42)
        assert len(me.generate(0)) == 0
        assert len(me.generate(1)) == 1
        assert len(me.generate(5)) == 5
        assert len(me.generate(14)) == 14

    def test_valid_motion_types(self) -> None:
        me = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=42)
        for desc in me.generate(20):
            assert desc["type"] in MOTION_TYPES

    def test_disabled_returns_none(self) -> None:
        me = MotionEngine(enabled=False, seed=42)
        for desc in me.generate(3):
            assert desc["type"] == "none"
            assert desc["zoom_start"] == 1.0
            assert desc["zoom_end"] == 1.0
            assert desc["pan_x"] == 0
            assert desc["pan_y"] == 0

    def test_zero_clips(self) -> None:
        me = MotionEngine(enabled=True, seed=42)
        assert me.generate(0) == []

    def test_deterministic_same_seed(self) -> None:
        me1 = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=42)
        me2 = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=42)
        assert me1.generate(5) == me2.generate(5)

    def test_different_seed_different(self) -> None:
        me1 = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=42)
        me2 = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=99)
        assert me1.generate(5) != me2.generate(5)

    def test_strength_affects_zoom(self) -> None:
        weak = MotionEngine(enabled=True, strength=0.05, probability=1.0, seed=42)
        strong = MotionEngine(enabled=True, strength=0.20, probability=1.0, seed=42)
        weak_motions = weak.generate(5)
        strong_motions = strong.generate(5)
        # A zoom_in with higher strength should have larger zoom_end
        for w, s in zip(weak_motions, strong_motions):
            if w["type"] == "zoom_in" and s["type"] == "zoom_in":
                assert s["zoom_end"] >= w["zoom_end"]

    def test_probability_zero(self) -> None:
        me = MotionEngine(enabled=True, strength=0.08, probability=0.0, seed=42)
        for desc in me.generate(10):
            assert desc["type"] == "none"

    def test_probability_one(self) -> None:
        me = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=42)
        nones = sum(1 for d in me.generate(20) if d["type"] == "none")
        assert nones == 0

    def test_descriptor_keys(self) -> None:
        me = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=42)
        desc = me.generate(1)[0]
        assert set(desc.keys()) == {"type", "zoom_start", "zoom_end", "pan_x", "pan_y"}

    def test_all_motion_types_appear(self) -> None:
        """Over many clips, all non-none motion types should appear."""
        me = MotionEngine(enabled=True, strength=0.08, probability=1.0, seed=7)
        types = set(d["type"] for d in me.generate(100))
        for mt in MOTION_TYPES:
            if mt == "none":
                continue
            assert mt in types

    def test_constructor_overrides_config(self, tmp_project: Path) -> None:
        """Constructor params override YAML config."""
        me = MotionEngine(enabled=False, strength=0.5)
        assert me._enabled is False
        assert me._strength == 0.5


# ── TransitionEngine ───────────────────────────────────────────────────────


class TestTransitionEngine:
    def test_generates_correct_count(self) -> None:
        te = TransitionEngine(enabled=True, default_transition="crossfade", duration=0.5, seed=42)
        assert len(te.generate(0)) == 0
        assert len(te.generate(1)) == 1
        assert len(te.generate(5)) == 5

    def test_first_transition_is_always_cut(self) -> None:
        te = TransitionEngine(enabled=True, duration=0.5, seed=42)
        for count in [1, 3, 10]:
            descs = te.generate(count)
            assert descs[0]["type"] == "cut"
            assert descs[0]["duration"] == 0.0
            assert descs[0]["index"] == 0

    def test_valid_transition_types(self) -> None:
        te = TransitionEngine(enabled=True, duration=0.5, seed=7)
        for desc in te.generate(20):
            assert desc["type"] in TRANSITION_TYPES

    def test_disabled_returns_all_cut(self) -> None:
        te = TransitionEngine(enabled=False, seed=42)
        for desc in te.generate(5):
            assert desc["type"] == "cut"
            assert desc["duration"] == 0.0

    def test_zero_clips(self) -> None:
        te = TransitionEngine(enabled=True, seed=42)
        assert te.generate(0) == []

    def test_single_clip(self) -> None:
        te = TransitionEngine(enabled=True, seed=42)
        descs = te.generate(1)
        assert len(descs) == 1
        assert descs[0]["type"] == "cut"

    def test_deterministic_same_seed(self) -> None:
        te1 = TransitionEngine(enabled=True, duration=0.5, seed=42)
        te2 = TransitionEngine(enabled=True, duration=0.5, seed=42)
        assert te1.generate(10) == te2.generate(10)

    def test_different_seed_different(self) -> None:
        te1 = TransitionEngine(enabled=True, duration=0.5, seed=42)
        te2 = TransitionEngine(enabled=True, duration=0.5, seed=99)
        assert te1.generate(10) != te2.generate(10)

    def test_non_cut_transitions_have_duration(self) -> None:
        te = TransitionEngine(enabled=True, duration=0.5, seed=7)
        for desc in te.generate(10):
            if desc["type"] != "cut":
                assert desc["duration"] == 0.5
            else:
                assert desc["duration"] == 0.0

    def test_descriptor_keys(self) -> None:
        te = TransitionEngine(enabled=True, duration=0.5, seed=42)
        desc = te.generate(1)[0]
        assert set(desc.keys()) == {"type", "duration", "index"}

    def test_constructor_overrides_config(self, tmp_project: Path) -> None:
        te = TransitionEngine(enabled=False, duration=1.0, default_transition="dissolve")
        assert te._enabled is False
        assert te._duration == 1.0
        assert te._default == "dissolve"


# ── Renderer integration ──────────────────────────────────────────────────


class TestRendererIntegration:
    def test_renderer_imports_motion_engine(self) -> None:
        from src.renderer.moviepy_renderer import _apply_motion
        assert callable(_apply_motion)

    def test_renderer_imports_transition_helpers(self) -> None:
        from src.renderer.moviepy_renderer import _apply_transition
        assert callable(_apply_transition)

    def test_effects_listed_in_config(self, tmp_project: Path) -> None:
        from src.utils.config import get_config
        assert get_config("effects.random_seed") == 42
        assert get_config("effects.motion.enabled") is True
        assert get_config("effects.motion.strength") == 0.08
        assert get_config("effects.motion.probability") == 0.85
        assert get_config("effects.transitions.enabled") is True
        assert get_config("effects.transitions.default_transition") == "crossfade"
        assert get_config("effects.transitions.transition_duration") == 0.5


# ── Edge cases ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_motion_zero_strength(self) -> None:
        """Strength 0 should produce zoom_start==zoom_end and pan_x/y==0."""
        me = MotionEngine(enabled=True, strength=0.0, probability=1.0, seed=42)
        for desc in me.generate(5):
            assert desc["zoom_start"] == desc["zoom_end"]
            assert desc["pan_x"] == 0
            assert desc["pan_y"] == 0

    def test_transition_zero_duration(self) -> None:
        """Zero transition duration should result in all cuts."""
        te = TransitionEngine(enabled=True, duration=0.0, seed=42)
        for desc in te.generate(10):
            assert desc["type"] == "cut"
            assert desc["duration"] == 0.0
