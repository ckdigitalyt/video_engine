"""Phase G tests (§24–25): daily topic scouting + diversity.

- score_topic() produces all 10 §24 factors, total is a weighted mean
- is_visualizable() rejects topics that can't be visualized
- record_topic()/select_daily_topic() implement §25 diversity:
  repeated categories are penalized, rotation is preferred
"""

from __future__ import annotations

import pytest

from engine.scout.topic_scout import (
    CATEGORY_ROTATION,
    SCORE_FACTORS,
    is_visualizable,
    load_history,
    record_topic,
    score_topic,
    select_daily_topic,
)


def test_score_topic_all_factors_present():
    c = score_topic("Why is the sky blue?", category="science")
    assert set(c.scores) == set(SCORE_FACTORS)
    for v in c.scores.values():
        assert 0.0 <= v <= 1.0


def test_score_topic_weighted_total():
    c = score_topic("Why is the sky blue?", category="science")
    assert 0.0 <= c.total <= 1.0
    # a visual keyword topic out-scores a non-visual one
    visual = score_topic("How do waves cancel out?", category="science")
    plain = score_topic("What is the history of chairs?",
                        category="history")
    assert visual.total > plain.total


def test_override_scores():
    c = score_topic("Why is the sky blue?", category="science",
                    scores={"visual_potential": 1.0,
                            "production_feasibility": 0.1})
    assert c.scores["visual_potential"] == 1.0
    assert c.scores["production_feasibility"] == 0.1


def test_is_visualizable_rejects_hard_topics():
    assert is_visualizable("How does wave interference work?")
    assert not is_visualizable("Abstract philosophy of tax law")


def test_record_topic_updates_history(tmp_path):
    hist = record_topic("Why is the sky blue?", "science", base=tmp_path)
    assert hist["recent"] == ["Why is the sky blue?"]
    assert hist["category_counts"]["science"] == 1
    hist2 = record_topic("How do noise-cancelling headphones work?",
                         "technology", base=tmp_path)
    assert len(hist2["recent"]) == 2
    assert hist2["category_counts"]["technology"] == 1


def test_history_persists(tmp_path):
    record_topic("Why does popcorn pop?", "everyday_phenomenon",
                 base=tmp_path)
    loaded = load_history(tmp_path)
    assert "Why does popcorn pop?" in loaded["recent"]


def test_select_daily_topic_prefers_fresh_category(tmp_path):
    # produce 2 science topics recently, then offer science vs technology
    record_topic("Why is the sky blue?", "science", base=tmp_path)
    record_topic("Why does popcorn pop?", "science", base=tmp_path)
    science = score_topic("Why is the ocean salty?", "science")
    tech = score_topic("How do noise-cancelling headphones work?",
                       "technology")
    # give science a higher raw total so only the §25 penalty can flip it
    science.scores = {k: 0.9 for k in SCORE_FACTORS}
    tech.scores = {k: 0.8 for k in SCORE_FACTORS}
    chosen = select_daily_topic([science, tech], base=tmp_path)
    assert chosen.category == "technology"


def test_select_daily_topic_returns_highest_when_no_history(tmp_path):
    a = score_topic("Why is the sky blue?", "science")
    a.scores = {k: 0.5 for k in SCORE_FACTORS}
    b = score_topic("Why does popcorn pop?", "everyday_phenomenon")
    b.scores = {k: 0.9 for k in SCORE_FACTORS}
    chosen = select_daily_topic([a, b], base=tmp_path)
    assert chosen.topic == b.topic


def test_rotation_order_defined():
    assert len(CATEGORY_ROTATION) == 9
    assert len(set(CATEGORY_ROTATION)) == 9
