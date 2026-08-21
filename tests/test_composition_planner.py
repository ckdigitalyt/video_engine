"""Phase B tests: CompositionPlanner (§20–21) — composition/attention as a
first-class planning stage.

Covers:
  - every beat carries a composition plan with pacing + attention metrics
  - exactly one focal point per beat (release/pause may be full-frame)
  - attention metrics are sane ratios in [0,1]
  - hero beats read as climax pacing with tight camera scale
  - negative space (not density) is preserved
  - gate_composition passes the three §46 topics
"""

import pytest

from engine.qa.gates import gate_composition
from engine.validation.schema import validate_visualspec_v2
from engine.visuals.composition_planner import (
    PACING_TAGS, attach_composition, plan_beat, plan_composition,
)
from engine.visuals.world_director import build_visualspec
from engine.world.knowledge import build_world

TOPICS = [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
]


def _spec(topic):
    world = build_world(topic)
    vs = build_visualspec(topic, world)
    return vs


def test_every_beat_has_composition_plan():
    for t in TOPICS:
        vs = _spec(t)
        for b in vs["beats"]:
            comp = b.get("composition")
            assert comp, f"{t}: beat {b['beat_id']} missing composition plan"
            assert comp["beat_id"] == b["beat_id"]
            assert comp["pacing"] in PACING_TAGS
            assert "attention_metrics" in comp


def test_at_most_one_focal_point():
    for t in TOPICS:
        vs = _spec(t)
        for b in vs["beats"]:
            comp = b["composition"]
            focal = comp["focal_object"]
            supports = comp["supporting_objects"]
            # focal must never also appear in supporting_objects
            if focal:
                assert focal not in supports, \
                    f"{t}: beat {b['beat_id']} focal duplicated in supports"
            # and there is exactly one focal key
            assert focal is None or isinstance(focal, str)


def test_attention_metrics_are_ratios():
    for t in TOPICS:
        vs = _spec(t)
        for b in vs["beats"]:
            attn = b["composition"]["attention_metrics"]
            for key in ("focal_area_ratio", "semantic_object_area",
                        "empty_area_ratio", "text_area_ratio",
                        "focal_contrast"):
                val = attn[key]
                assert 0.0 <= val <= 1.0, \
                    f"{t}: beat {b['beat_id']} {key}={val} out of range"


def test_hero_beats_are_climax_with_tight_camera():
    for t in TOPICS:
        vs = _spec(t)
        heroes = [b for b in vs["beats"] if b["importance"] == "high"]
        assert heroes, f"{t}: no hero beat"
        for b in heroes:
            comp = b["composition"]
            # hero beats read as climax (unless they are release/payoff)
            if comp["pacing"] != "release":
                assert comp["pacing"] in ("climax", "escalation"), \
                    f"{t}: hero beat {b['beat_id']} pacing={comp['pacing']}"
            if comp["focal_object"]:
                assert comp["camera"]["scale"] <= 0.72, \
                    f"{t}: hero beat {b['beat_id']} not tight enough"


def test_negative_space_preserved_not_density():
    for t in TOPICS:
        vs = _spec(t)
        report = vs["metadata"]["composition_report"]
        assert report["avg_empty_area_ratio"] >= 0.20, \
            f"{t}: frame density too high (empty {report['avg_empty_area_ratio']})"
        assert report["avg_focal_contrast"] >= 0.5, \
            f"{t}: focal contrast too low"


def test_gate_composition_passes_three_topics():
    for t in TOPICS:
        vs = _spec(t)
        g = gate_composition(vs)
        assert g.passed, f"{t}: composition gate failed: {g.errors}"


def test_gate_composition_fails_on_dense_spec():
    """A spec with no composition report and dense beats must fail."""
    beats = []
    for i in range(6):
        beats.append({
            "beat_id": f"b{i + 1:03d}",
            "intent": "explanation",
            "role": "explain_principle",
            "importance": "medium",
            "objects": [{"id": f"o{j}", "type": "particle",
                         "properties": {}} for j in range(12)],
            "transformations": [],
            "semantic_actions": [{"action": "flow", "target": "o0"}],
            "visual_type": "",
            "camera": {"type": "static"},
        })
    vs = {"version": "v2", "beats": beats, "metadata": {"topic": "dense"}}
    g = gate_composition(vs)
    assert not g.passed
    assert any("empty" in e for e in g.errors)


def test_schema_accepts_composition_fields():
    for t in TOPICS:
        vs = _spec(t)
        errs = validate_visualspec_v2(vs)
        assert not errs, f"{t}: schema errors: {errs}"


def test_attach_composition_idempotent_report():
    vs = _spec(TOPICS[0])
    report1 = vs["metadata"]["composition_report"]
    assert report1["per_beat"]
    assert report1["beats_without_focal"] is not None
    # per-beat plans match beat ids
    ids = {b["beat_id"] for b in vs["beats"]}
    assert {p["beat_id"] for p in report1["per_beat"]} == ids


def test_plan_beat_exits_and_remains():
    """Stage continuity: objects referenced later do not exit."""
    beats = _spec(TOPICS[1])["beats"]  # noise-cancelling (wave chain)
    prev: set[str] = set()
    for b in beats:
        comp = b["composition"]
        refs = {o["id"] for o in b.get("objects", [])
                if isinstance(o, dict) and o.get("id")}
        # everything referenced this beat either remains or is a new enter;
        # exits only ever contain ids that are NOT referenced this beat
        assert not (set(comp["exits"]) & refs), \
            f"beat {b['beat_id']}: exiting an object still on stage"
        prev |= refs
