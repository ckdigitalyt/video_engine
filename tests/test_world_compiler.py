"""Phase A tests: world compiler compile-only + physics guard (§46)."""

import pytest

from engine.renderers.manim.world_compiler import (
    WorldCompileError, _physics_guard, compile_world_to_file)
from engine.validation import physics_verify as PH
from engine.visuals.world_director import build_visualspec
from engine.world.knowledge import build_world

TOPICS = [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
]


def test_compile_only_writes_scene(tmp_path):
    for t in TOPICS:
        world = build_world(t)
        vs = build_visualspec(t, world)
        scene_file = tmp_path / f"{world.topic[:12]}.py".replace(" ", "_")
        compile_world_to_file(vs, scene_file, "WorldScene")
        assert scene_file.exists()
        assert "class WorldScene" in scene_file.read_text()


def test_physics_guard_accepts_interference():
    beat = {"beat_id": "b001",
            "semantic_actions": [{"action": "interfere", "target": "c",
                                  "params": {"frequency": 1.0,
                                             "phase_deg": 180.0}}]}
    # no exception for valid params
    _physics_guard(beat, None)


def test_physics_guard_rejects_bad_interference():
    beat = {"beat_id": "b001",
            "semantic_actions": [{"action": "cancel", "target": "c",
                                  "params": {"frequency": -1.0,
                                             "phase_deg": 180.0}}]}
    with pytest.raises(WorldCompileError):
        _physics_guard(beat, None)


def test_physics_guard_rejects_bad_burst():
    beat = {"beat_id": "b001",
            "semantic_actions": [{"action": "burst", "target": "k",
                                  "params": {"pressure_atm": -5.0,
                                             "temp_c": 180.0}}]}
    with pytest.raises(WorldCompileError):
        _physics_guard(beat, None)


def test_verifier_matches_guard():
    v = PH.verify_wave_interference(1.0, 1.0, 180.0)
    assert v.ok
