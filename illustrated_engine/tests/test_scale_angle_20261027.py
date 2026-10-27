"""2026-10-27 competitor study (18 channels, 756 Shorts): topics framed
around scale or a direct comparison (size, depth, distance, "X vs Y") beat
their channel's own baseline x1.63 on views (p=0.009, n=51, 14 channels;
5 of 7 closest space/science analogs). Title wording had no effect.

Implemented as an angle that cuts across clusters: a deterministic
title+claim detector, a +5 score bonus (the evergreen bonus size), a
topic_history tag, and topic_ideate v3 / topic_score v4 prompt guidance.
The taxonomy, priors, target shares and still-image floor are unchanged.

Fake `ask` only -- no network, no LLM, no render.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_topics as T  # noqa: E402
from llm.prompts import render  # noqa: E402

ROW = {"counter_intuitive": 3, "visualisability": 3, "hook_strength": 3,
       "series_potential": 3, "evidence_strength": 3, "still_image_fit": 3}

# The competitor study's own examples plus real topic_history titles.
SCALE = [
    "We Are So TINY",
    "How Deep Does The Ocean Really Go",
    "Great Pyramid vs Olympus Mons",
    "If the Sun were the size of a basketball",
    "Astronomers Found a Planet With Rings 200 Times Wider Than Saturn's",
    "The First Horses Were Smaller Than a Modern Dog",
    "Giant Dragonflies Once Grew as Big as Hawks",
    "The Mariana Trench Is Deeper Than Everest Is Tall",
    "Every planet fits between Earth and the Moon",
]
# Real topic_history titles that must NOT read as scale framing.
NOT_SCALE = [
    "The Frog That Breaks Magnet Physics",
    "Sound Waves That Levitate Objects",
    "G-Force Can Pull the Skin on a Pilot's Face Back",
    "A Black Hole Was Found Too Massive to Exist",           # "so/too massive" != scale
    "A Ball Bouncing on a Trampoline Floor Can Rise Higher Than Its Drop",
    "White dwarf stars collapse into diamonds",
    "Why Pilots Train To Black Out On Purpose",
]


@pytest.mark.parametrize("title", SCALE)
def test_detector_recognises_scale_and_comparison_framing(title):
    assert T.is_scale_comparison({"title": title, "claim": ""})


@pytest.mark.parametrize("title", NOT_SCALE)
def test_detector_ignores_non_scale_titles(title):
    assert not T.is_scale_comparison({"title": title, "claim": ""})


def test_detector_reads_the_claim_but_not_the_hooks():
    c = {"title": "Saturn's Rings Hide a Secret", "claim": "The rings are thinner than paper "
         "to scale, wider than 20 Earths compared to their depth.", "hooks": []}
    assert T.is_scale_comparison(c)
    c2 = {"title": "A Frog Floats", "claim": "A magnet lifts a live frog.",
          "hooks": ["A frog bigger than your palm floats."]}
    assert not T.is_scale_comparison(c2)


def test_bonus_is_additive_within_any_cluster_and_never_breaks_100():
    for cluster in ("spectacle_physics", "deep_time", "space_discovery"):
        plain, b0 = T.score_candidate({"cluster": cluster, "title": "A Frog Floats"}, ROW)
        scale, b1 = T.score_candidate({"cluster": cluster, "title": "Great Pyramid vs Olympus Mons"},
                                      ROW)
        assert b0["scale_comparison"] == 0.0 and b1["scale_comparison"] == T.SCALE_COMPARISON_BONUS
        assert sum(b1.values()) - sum(b0.values()) == pytest.approx(5.0)
        assert abs((scale - plain) - 5) <= 1          # total is round(sum)
    top = dict.fromkeys(ROW, 5)
    s, _ = T.score_candidate({"cluster": "spectacle_physics", "evergreen": True,
                              "title": "We Are So TINY"}, top)
    assert s == 100


def test_bonus_does_not_override_cluster_priors_or_the_still_image_floor():
    # it is smaller than one prior step (spectacle 25 pts vs deep_time 20)
    sp, _ = T.score_candidate({"cluster": "spectacle_physics", "title": "A Frog Floats"}, ROW)
    gx, _ = T.score_candidate({"cluster": "general_explainer",
                               "title": "Great Pyramid vs Olympus Mons"}, ROW)
    assert sp > gx
    s, b = T.score_candidate({"cluster": "deep_time", "title": "Great Pyramid vs Olympus Mons"},
                             {**ROW, "still_image_fit": 1})
    assert s == 0 and b["excluded_still_unfriendly"] and b["scale_comparison"] == 0.0
    s, b = T.score_candidate({"cluster": "quiz", "title": "Great Pyramid vs Olympus Mons"}, ROW)
    assert s == 0 and b["scale_comparison"] == 0.0
    assert set(T.CLUSTER_PRIORS) == {"spectacle_physics", "deep_time", "exotic_space_travel",
                                     "space_discovery", "general_explainer"}


def test_real_rejected_scale_topics_now_clear_min_score():
    """Real topic_history rows: rejected at 64 (MIN_SCORE 65) with a scale
    framing. The +5 bonus queues them."""
    real = [  # (score, title, claim) verbatim from data/topic_history.jsonl
        (64, "A Comet's Tail Stretched Longer Than the Distance to the Moon",
         "Comet Hyakutake's tail was measured stretching farther than the distance from "
         "Earth to the Moon."),
        (64, "Astronomers Detected a Black Hole Small Enough to Fit in a City",
         "Astronomers found a black hole with an event horizon small enough to fit inside a "
         "single city."),
    ]
    for score, title, claim in real:
        assert score < T.MIN_SCORE
        assert T.is_scale_comparison({"title": title, "claim": claim})
        assert score + T.SCALE_COMPARISON_BONUS >= T.MIN_SCORE


def test_prompts_ask_for_the_scale_angle():
    prompt, ver = render("topic_ideate", clusters=T.clusters_prompt_block(), n=10,
                         avoid_titles="(none)")
    assert ver == "3"
    assert "SCALE or a direct COMPARISON" in prompt and "Great Pyramid vs Olympus Mons" in prompt
    assert "not a cluster" in prompt and "Never invent a" in prompt
    prompt, ver = render("topic_score", candidates="id: t_1\ntitle: x")
    assert ver == "4" and "side-by-side SCALE COMPARISON" in prompt


def test_build_queue_ranks_the_scale_topic_first_within_its_cluster_and_tags_history(tmp_path):
    raw = [
        {"title": "Wood Turns Entirely To Stone Underground", "cluster": "deep_time",
         "claim": "Minerals replace every cell of a buried log."},
        {"title": "The First Horses Were Smaller Than a Modern Dog", "cluster": "deep_time",
         "claim": "Eohippus stood about as tall as a fox."},
    ]
    raw = [{**c, "entities": {"subject": c["title"], "place": "", "era": "", "phenomenon": ""},
            "hooks": ["h1", "h2", "h3"], "templates": ["SCALE_COMPARE"],
            "series_id": None, "series_part": None, "evergreen": True} for c in raw]
    ids = [T.slugify(c["title"]) for c in raw]
    q = {"topic_ideate": [{"candidates": raw}],
         "topic_score": [{"scores": [{"id": i, **dict.fromkeys(ROW, 4), "best_hook": "h"}
                                     for i in ids]}]}

    def ask(stage, prompt, **kw):
        return SimpleNamespace(data=q[stage].pop(0), model="fake", cached=False,
                               attempts=1, usage={})
    res = T.build_queue(n=2, history_path=tmp_path / "h.jsonl", ask=ask, persist=True)
    queue = res["queue"]
    assert [e["title"] for e in queue][0] == "The First Horses Were Smaller Than a Modern Dog"
    assert queue[0]["score"] - queue[1]["score"] == 5
    rows = {r["title"]: r for r in map(json.loads, (tmp_path / "h.jsonl").read_text().splitlines())}
    assert rows["The First Horses Were Smaller Than a Modern Dog"]["scale_comparison"] is True
    assert rows["Wood Turns Entirely To Stone Underground"]["scale_comparison"] is False
