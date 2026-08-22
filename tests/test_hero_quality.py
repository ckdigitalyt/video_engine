"""Phase C tests (§9–10, §12): hero mechanism first-class + QC gate.

- hero_for emits the full spec shape {concept, representation, objects,
  actions, why_this_visual} for the three §46 dev topics
- gate_hero_quality passes for plans built by the autonomous director
- gate_hero_quality FAILs closed on: missing hero, empty objects/actions,
  missing why_this_visual, hero beat not importance=high, weak hero beat
"""

from __future__ import annotations

import pytest

from engine.qa.gates import gate_hero_quality
from engine.visuals.world_director import build_visualspec
from engine.world.story_templates import hero_for, select_template
from engine.world.world_model import WorldState


def _world_for(topic: str) -> WorldState:
    from engine.world.knowledge import build_world
    return build_world(topic)


def _visualspec(topic: str) -> dict:
    world = _world_for(topic)
    return build_visualspec(topic, world)


@pytest.mark.parametrize("topic", [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
])
def test_hero_for_full_spec_shape(topic):
    plan = select_template(topic)
    world = _world_for(topic)
    from engine.world.representations import select_representation
    rep = select_representation(topic)
    hero = hero_for(topic, plan, rep.primary)
    assert hero.concept
    assert hero.visualization
    assert hero.representation
    assert hero.objects, "hero objects must be populated (§9)"
    assert hero.actions, "hero actions must be populated (§9)"
    assert hero.why_this_visual, "hero needs why_this_visual (§12)"
    # objects/actions must resolve to known vocabulary
    from engine.world.actions import ACTION_REGISTRY
    from engine.world.world_model import EntityType
    known_types = {v for v in vars(EntityType).values()
                   if isinstance(v, str)}
    for o in hero.objects:
        assert o in known_types, f"hero object {o} not an EntityType"
    for a in hero.actions:
        assert a in ACTION_REGISTRY, f"hero action {a} not in vocabulary"


@pytest.mark.parametrize("topic", [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
])
def test_gate_hero_quality_passes_on_director_plans(topic):
    vs = _visualspec(topic)
    g = gate_hero_quality(vs)
    assert g.passed, f"{topic}: {g.errors}"


def test_gate_fails_missing_hero():
    vs = _visualspec("Why is the sky blue?")
    del vs["metadata"]["hero_mechanism"]
    g = gate_hero_quality(vs)
    assert not g.passed
    assert any("no hero_mechanism" in e for e in g.errors)


def test_gate_fails_empty_objects_actions():
    vs = _visualspec("Why does popcorn pop?")
    hero = vs["metadata"]["hero_mechanism"]
    hero["objects"] = []
    hero["actions"] = []
    g = gate_hero_quality(vs)
    assert not g.passed
    assert any("objects empty" in e for e in g.errors)
    assert any("actions empty" in e for e in g.errors)


def test_gate_fails_missing_why_this_visual():
    vs = _visualspec("Why is the sky blue?")
    vs["metadata"]["hero_mechanism"]["why_this_visual"] = ""
    g = gate_hero_quality(vs)
    assert not g.passed
    assert any("why_this_visual" in e for e in g.errors)


def test_gate_fails_hero_beat_not_high_importance():
    vs = _visualspec("Why is the sky blue?")
    tb = vs["metadata"]["hero_mechanism"]["target_beat"]
    for b in vs["beats"]:
        if b["beat_id"] == tb:
            b["importance"] = "medium"
    g = gate_hero_quality(vs)
    assert not g.passed
    assert any("not importance=high" in e for e in g.errors)


def test_gate_fails_weak_hero_beat():
    vs = _visualspec("Why is the sky blue?")
    tb = vs["metadata"]["hero_mechanism"]["target_beat"]
    for b in vs["beats"]:
        if b["beat_id"] == tb:
            b["explanation_score"] = 2
    g = gate_hero_quality(vs)
    assert not g.passed
    assert any("explanation_score" in e for e in g.errors)


def test_gate_fails_missing_hero_beat():
    vs = _visualspec("Why is the sky blue?")
    vs["metadata"]["hero_mechanism"]["target_beat"] = "b999"
    g = gate_hero_quality(vs)
    assert not g.passed
    assert any("not found" in e for e in g.errors)
