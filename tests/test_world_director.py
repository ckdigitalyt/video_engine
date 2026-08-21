"""Phase A tests: three-topic grammar diversity (§46) + spec scoring."""

from engine.world.knowledge import build_world
from engine.visuals.world_director import build_visualspec

TOPICS = [
    "Why is the sky blue?",
    "How do noise-cancelling headphones work?",
    "Why does popcorn pop?",
]


def _spec(topic):
    world = build_world(topic)
    vs = build_visualspec(topic, world)
    return vs


def test_three_topics_all_produce_beats():
    for t in TOPICS:
        vs = _spec(t)
        assert len(vs["beats"]) >= 5, f"{t}: too few beats"
        for b in vs["beats"]:
            assert b["explanation_score"] >= 0


def test_three_topics_have_semantic_actions():
    for t in TOPICS:
        vs = _spec(t)
        for b in vs["beats"]:
            # every non-payoff beat should carry semantic actions or be
            # an intentional kinetic hook/payoff
            assert (b["semantic_actions"] or b["visual_type"]
                    in ("kinetic_title", "payoff")), \
                f"{t}: beat {b['beat_id']} has no semantic action"


def test_explanation_avg_ge_3_5():
    for t in TOPICS:
        vs = _spec(t)
        expl = vs["metadata"]["explanation_report"]
        assert expl["average_explanation_score"] >= 3.5, f"{t}: too low"


def test_text_dominance_lt_0_35():
    for t in TOPICS:
        vs = _spec(t)
        expl = vs["metadata"]["explanation_report"]
        assert expl["text_dominance_ratio"] < 0.35, f"{t}: text-dominant"


def test_three_distinct_grammars():
    """§46: the engine must choose different visual grammars per topic."""
    reps = [_spec(t)["metadata"]["representation"] for t in TOPICS]
    # sky = SIMULATION, noise = SIMULATION, popcorn = EXPERIMENT
    assert reps[2] == "EXPERIMENT"
    assert reps[0] == "SIMULATION"
    # the grammars must differ in *actions* even where the rep family
    # coincides (sky scatters, noise interferes)
    action_sets = []
    for t in TOPICS:
        vs = _spec(t)
        action_sets.append(frozenset(
            a["action"] for b in vs["beats"]
            for a in b.get("semantic_actions", [])))
    assert "scatter" in action_sets[0]
    assert {"interfere", "cancel"} <= action_sets[1]
    assert "burst" in action_sets[2]
    # noise vs sky: different mechanism actions
    assert action_sets[0] != action_sets[1]


def test_hero_beat_marked_high():
    for t in TOPICS:
        vs = _spec(t)
        heroes = [b for b in vs["beats"] if b["importance"] == "high"]
        assert heroes, f"{t}: no hero beat marked high"


def test_no_text_primary_explanatory_beats():
    for t in TOPICS:
        vs = _spec(t)
        for b in vs["beats"]:
            if b["visual_type"] not in ("kinetic_title", "payoff"):
                assert not b["text_primary"], \
                    f"{t}: beat {b['beat_id']} is text-primary"
