"""2026-10-27 re-check of the 2026-10-24 escalation/emotional_charge floors.

- n=20 uploads: escalation +0.59 -> +0.06, emotional_charge +0.55 -> -0.05
  vs real retention (the n=8 numbers that justified the >= 3 floor were
  noise). With >= 50 views only: +0.26 / +0.19, weakly positive.
- 0 of 9 human-scale-physics candidates in live_20261024_134200/_181000
  reached render. Five were held on escalation=2 alone after 2-5 rewrites:
  G-force pilot, boiling can, Tesla coil, water jet, lung pressure.

Policy: the escalation/emotional_charge floor goes 3 -> 2, so it rejects
only scripts that are actually flat. Their STORY_DIM_WEIGHTS drop below
hook/payoff/curiosity. The hook/payoff >= 3 floors are unchanged.

The critic score sequences below are the REAL script_critic responses for
those topics. They were recovered from build/cache/llm by mtime order
(write -> critic) and match each materialize_report mean exactly. The cache
stores unique responses only, so a sequence shorter than the 3 critic calls
_rank_one makes is padded with its last response.

Fake LLM only; no network, no render.
"""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_script as S  # noqa: E402

WARP = json.loads((ROOT / "tests" / "fixtures" / "warp_bubble_20261015.json").read_text())
WARP_FACTS = {"claims": [{**c, "evidence": c["quote"], "quote_verified": True,
                          "verified": True, "curated": False} for c in WARP["claims"]]}
DIMS = ["hook_strength", "curiosity_gap", "escalation", "payoff_clarity",
        "loop_coherence", "human_voice", "emotional_charge", "one_idea_only"]
OLD_FLOORS = {"hook_strength": 3, "payoff_clarity": 3, "escalation": 3, "emotional_charge": 3}


def _s(*v):
    return dict(zip(DIMS, v))


# (topic, batch, reported mean of the kept draft, real critic sequence)
#              hook cur esc pay loop voice emo one
ESCALATION_KILLED = [
    ("G-Force Can Pull the Skin on a Pilot's Face Back", "134200", 3.125,
     [_s(4, 3, 2, 3, 3, 3, 2, 3), _s(4, 3, 2, 4, 3, 3, 3, 3)]),
    ("A Boiling Can Collapses Instantly in Cold Water", "134200", 3.375,
     [_s(4, 3, 2, 3, 2, 4, 2, 3), _s(4, 2, 2, 4, 3, 4, 3, 5)]),
    ("A Human Lung Can Shrink Under Deep Ocean Pressure", "134200", 2.75,
     [_s(4, 2, 2, 3, 3, 3, 2, 3), _s(4, 3, 2, 2, 2, 3, 3, 3)]),
    ("A Tesla Coil's Lightning Can Curl Around a Person", "181000", 3.25,
     [_s(4, 3, 2, 4, 3, 3, 3, 4), _s(4, 4, 2, 3, 3, 3, 3, 5)]),
    ("A Jet of Water Can Slice Through Solid Steel", "181000", 3.375,
     [_s(5, 2, 2, 3, 3, 3, 2, 3), _s(4, 4, 3, 3, 3, 3, 2, 4), _s(4, 4, 2, 4, 3, 3, 3, 4)]),
]
# Same batches, held on the validated payoff_clarity >= 3 floor: must STILL hold.
PAYOFF_KILLED = [
    ("A Person Can Stand on a Bed of Nails Unharmed",
     [_s(4, 3, 2, 2, 3, 2, 2, 2), _s(4, 3, 3, 2, 4, 4, 3, 4), _s(4, 3, 2, 2, 4, 3, 3, 4)]),
    ("A Fossil Captured the Splash of an Ancient Raindrop",
     [_s(4, 3, 2, 2, 4, 3, 2, 4), _s(4, 3, 2, 2, 4, 3, 3, 4), _s(4, 4, 2, 2, 4, 3, 3, 4)]),
]


class Fake:
    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}
        self.prompts = []

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        self.prompts.append((stage, prompt))
        return SimpleNamespace(data=copy.deepcopy(self.q[stage].pop(0)), model="fake", cached=False,
                               attempts=1, usage={})


def _critics(seq):
    seq = list(seq) + [seq[-1]] * (1 + S.RANK_REWRITE_BUDGET - len(seq))
    return [{"scores": s, "critique": "real 2026-10-24 critic"} for s in seq]


def _fc(script):
    return {"sentences": [{"n": i, "label": "supported", "note": ""}
                          for i in range(1, len(script["sentences"]) + 1)]}


META = {"title": "A Ship That Never Speeds Up", "title_fact_ids": ["f_warp_contract_expand"],
        "description": "x", "hashtags": ["#space", "#physics", "#science"],
        "series_tag": "", "pinned_comment": "?"}


def _rank(seq):
    d1 = WARP["draft1"]
    n = 1 + S.RANK_REWRITE_BUDGET
    return S._rank_one("t", WARP_FACTS, "", Fake(script_write=[d1] * n,
                                                  script_critic=_critics(seq)))


# ------------------------------------------------------------ policy --

def test_floor_policy_hook_payoff_3_escalation_emotion_2():
    assert S.CRITIC_HARD_FLOORS == {"hook_strength": 3, "payoff_clarity": 3,
                                    "escalation": 2, "emotional_charge": 2}


def test_escalation_and_emotion_weigh_less_than_hook_payoff_curiosity():
    w = S.STORY_DIM_WEIGHTS
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert set(w) == set(DIMS)
    for weak in ("escalation", "emotional_charge"):
        for strong in ("hook_strength", "payoff_clarity", "curiosity_gap"):
            assert w[weak] < w[strong], (weak, strong)
        assert w[weak] > 0          # weak +0.26/+0.19 signal on >=50-view uploads: kept
    # both well below their 2026-10-24 weight of .20
    assert w["escalation"] <= 0.10 and w["emotional_charge"] <= 0.10


# ----------------------------------------- real 2026-10-24 failures --

@pytest.mark.parametrize("topic,batch,mean,seq", ESCALATION_KILLED,
                         ids=[t[0][:24] for t in ESCALATION_KILLED])
def test_real_escalation_killed_topics_held_under_old_floor(monkeypatch, topic, batch, mean, seq):
    """Reproduces the live failure: under the 2026-10-24 >= 3 floor each of
    these held with escalation=2 among its misses, and the kept draft's
    mean matches live_20261024_<batch>/materialize_report.json."""
    monkeypatch.setattr(S, "CRITIC_HARD_FLOORS", OLD_FLOORS)
    c = _rank(seq)
    assert c["status"] == "hold"
    assert "escalation=2 < 3" in c["reason"]
    assert c["mean"] == pytest.approx(mean)


@pytest.mark.parametrize("topic,batch,mean,seq", ESCALATION_KILLED,
                         ids=[t[0][:24] for t in ESCALATION_KILLED])
def test_real_escalation_killed_topics_now_survive(topic, batch, mean, seq):
    c = _rank(seq)
    assert c["status"] == "scored", c.get("reason")
    assert not S.critic_floor_misses(c["critic"]["scores"])
    assert c["weighted"] > 60


def test_lung_pressure_keeps_its_payoff_3_draft_over_the_payoff_2_rewrite():
    """Lung pressure held on payoff_clarity=2 AND escalation=2. Its FIRST
    draft had payoff 3 and escalation 2. The rewrite, chasing the old
    escalation floor, broke the payoff. Now the first draft clears every
    floor and _rank_key keeps it."""
    seq = ESCALATION_KILLED[2][3]
    c = _rank(seq)
    assert c["status"] == "scored"
    assert c["critic"]["scores"] == seq[0]
    assert any("scored lower" in n for n in c.get("notes", []))


@pytest.mark.parametrize("topic,seq", PAYOFF_KILLED, ids=[t[0][:24] for t in PAYOFF_KILLED])
def test_real_payoff_misses_still_hold(topic, seq):
    """The validated hook/payoff floors are untouched."""
    c = _rank(seq)
    assert c["status"] == "hold"
    assert "payoff_clarity=2 < 3" in c["reason"]
    assert S.critic_floor_misses(c["critic"]["scores"]) == ["payoff_clarity=2 < 3"]


def test_real_134200_human_scale_group_now_produces_a_story():
    """live_20261024_134200's first rank group (G-force, boiling can) was
    all hold on escalation=2. Replayed now, the group picks one and
    finalizes it."""
    groups = ESCALATION_KILLED[:2]
    d1 = WARP["draft1"]
    n = 1 + S.RANK_REWRITE_BUDGET
    crit = [c for _, _, _, seq in groups for c in _critics(seq)]
    f = Fake(script_write=[d1] * n * len(groups), script_critic=crit,
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([(t, WARP_FACTS) for t, _, _, _ in groups], ask=f)
    assert res["verdict"] == "PASS", res
    assert all(c["status"] == "scored" for c in res["candidates"])
    assert res["picked_topic"] in {t for t, _, _, _ in groups}


def test_flat_script_still_gets_targeted_escalation_advice():
    """escalation=1 (38 of 613 cached critic responses, which average 2.50
    on their other dimensions) is still a hard miss with its FLOOR_ADVICE."""
    seq = [_s(3, 3, 1, 3, 3, 3, 2, 3)]
    d1 = WARP["draft1"]
    n = 1 + S.RANK_REWRITE_BUDGET
    f = Fake(script_write=[d1] * n, script_critic=_critics(seq))
    c = S._rank_one("t", WARP_FACTS, "", f)
    assert c["status"] == "hold" and "escalation=1 < 2" in c["reason"]
    rewrite = [p for st_, p in f.prompts if st_ == "script_write"][1]
    assert "HARD REQUIREMENT" in rewrite and "raise the stakes" in rewrite
