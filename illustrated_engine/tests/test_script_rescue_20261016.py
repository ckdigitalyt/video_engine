"""2026-10-16 owner complaint ("what is the point of a quality gate if
everything fails?"): 4 batches / ~12 topics, zero publishable. Script-stage
losses that were NOT quality calls:

  - live_20261015_104500 Oldest Rock: numbers_in mis-parsed spelled figures
    ("four thousand two hundred eighty million" -> 280,004,000; "three point
    eight billion" -> 8e9), so sourced numbers failed check_digits.
  - same draft: "only three point seven billion years old" (a magnitude,
    not an exclusivity claim) failed check_absolute_claims.
  - live_20261015_202500 warp bubble: a code-clean draft above both critic
    floors was discarded because the optional critic rewrite broke a code
    rule.
  - live_20261015_093943 prism: the first draft's code fix spent the single
    shared rewrite budget, so a weak hook never got its critic rewrite.

The bar itself is unchanged: code checks and the 3/5 hook/payoff floors
still gate every draft (tests at the bottom).

Run: python3 -m pytest -q tests/test_script_rescue_20261016.py   (no network)
"""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_script as S  # noqa: E402
from engine.v16_research import numbers_in  # noqa: E402

WARP = json.loads((ROOT / "tests" / "fixtures" / "warp_bubble_20261015.json").read_text())
WARP_FACTS = {"claims": [{**c, "evidence": c["quote"], "quote_verified": True,
                          "verified": True, "curated": False} for c in WARP["claims"]]}
GOOD = dict.fromkeys(WARP["critic1"]["scores"], 4)
# The real warp draft-1 critic had escalation=2. Under the 2026-10-24
# escalation/emotional_charge >= 3 floor that draft now holds (see
# tests/test_critic_gate_20261024.py). The draft-keeping mechanics below are
# tested on the same scores with escalation lifted to the floor.
WARP_C1 = {**WARP["critic1"], "scores": dict(WARP["critic1"]["scores"], escalation=3)}


class Fake:
    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        item = self.q[stage].pop(0)
        return SimpleNamespace(data=copy.deepcopy(item), model="fake", cached=False,
                               attempts=1, usage={})


def _fc(script):
    return {"sentences": [{"n": i, "label": "supported"}
                          for i in range(1, len(script["sentences"]) + 1)]}


META = {"title": "A Ship That Never Speeds Up", "title_fact_ids": ["f_warp_contract_expand"],
        "description": "x", "hashtags": ["#space", "#physics", "#science"],
        "series_tag": "", "pinned_comment": "?"}


# ------------------------------------------------------------ numbers_in --

def test_spelled_decimal_is_one_number():
    assert numbers_in("about three point eight billion years old") == {3.8e9}
    assert numbers_in("four point two eight billion") == {4.28e9}
    assert numbers_in("zero point one") == {0.1}
    assert numbers_in("the point is that") == set()


def test_larger_scale_after_smaller_multiplies_the_total():
    assert numbers_in("four thousand two hundred eighty million years") == {4.28e9}
    assert numbers_in("one million two hundred thousand") == {1.2e6}   # unchanged
    assert numbers_in("sixty-six million") == {66e6}                    # unchanged


def test_digit_and_spelled_forms_compare_equal():
    # float("4.28") * 1e9 == 4280000000.0000005 used to differ from the spelled form
    assert numbers_in("4.28 billion") == numbers_in("four point two eight billion")


def test_oldest_rock_sentence_now_matches_its_cited_fact():
    facts = {"claims": [{"id": "f_n", "claim": "Microfossils may be 4.28 billion years old.",
                         "evidence": "may be as old as 4.28 billion years",
                         "quote": "may be as old as 4.28 billion years",
                         "quote_verified": True, "verified": True}]}
    script = {"sentences": [{"text": "And microfossils in Nuvvuagittuq vent rock may be four "
                                     "thousand two hundred eighty million years old.",
                             "fact_ids": ["f_n"]}]}
    assert S.check_digits(script, facts) == []


# ---------------------------------------------------- absolute-claim "only" --

def _abs(text):
    facts = {"claims": [{"id": "a", "claim": "x", "evidence": "x", "quote": "x"}]}
    return S.check_absolute_claims({"sentences": [{"text": text, "fact_ids": ["a"]}]}, facts)


def test_only_before_a_sourced_magnitude_is_not_an_exclusivity_claim():
    assert _abs("Greenland rocks only three point seven billion years old hold fossils.") == []


def test_only_as_exclusivity_or_count_is_still_flagged():
    for t in ("That has been done only once.", "Only two people have tried it.",
              "It was the only survivor.", "It took only ten seconds.",
              "It sits only sixty kilometres down, the first ever seen."):
        assert _abs(t), t


# ------------------------------------------- rank: keep the valid draft --

def test_warp_bubble_valid_draft_survives_a_rewrite_that_breaks_code_rules():
    d1, d2 = WARP["draft1"], WARP["draft2"]
    assert S.code_checks(d1, WARP_FACTS) == []           # the real draft 1 was clean
    assert S.code_checks(d2, WARP_FACTS)                 # the real rewrite was not
    assert not S.critic_floor_misses(WARP_C1["scores"])
    assert not S.critic_pass(WARP_C1["scores"])  # -> polish rewrite fires
    # rewrite (d2) breaks rules, its code-fix (d2 again) still breaks them
    f = Fake(script_write=[d1, d2, d2], script_critic=[WARP_C1],
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "PASS", res
    c = res["candidates"][0]
    assert c["status"] == "scored" and "kept the previous valid draft" in c["notes"][0]
    assert res["story"]["script"] == d1


def test_rewrite_that_breaks_rules_gets_its_own_code_fix():
    d1, d2 = WARP["draft1"], WARP["draft2"]
    better = {"scores": GOOD, "critique": ""}
    f = Fake(script_write=[d1, d2, d1], script_critic=[WARP["critic1"], better],
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "PASS"
    assert res["candidates"][0]["critic"]["scores"] == GOOD
    assert res["candidates"][0]["rewrites"] == 2


def test_lower_scoring_rewrite_does_not_replace_the_draft():
    d1 = WARP["draft1"]
    worse = dict(WARP_C1["scores"], hook_strength=2)
    f = Fake(script_write=[d1, d1], script_critic=[WARP_C1,
                                                   {"scores": worse, "critique": ""}],
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "PASS"
    assert res["candidates"][0]["critic"]["scores"]["hook_strength"] == 4


def test_code_fix_no_longer_spends_the_critic_rewrite():
    # prism shape: draft fails a code rule, the fix is clean but the hook is
    # weak -> the critic rewrite must still happen (it used to hold here).
    d1 = WARP["draft1"]
    broken = copy.deepcopy(d1)
    broken["sentences"][0]["text"] = "Why could a ship beat light?"
    weak = dict(GOOD, hook_strength=2)
    f = Fake(script_write=[broken, d1, d1],
             script_critic=[{"scores": weak, "critique": "weak hook"},
                            {"scores": GOOD, "critique": ""}],
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "PASS", res
    assert res["candidates"][0]["rewrites"] == 2


# --------------------------------------------------- the bar still holds --

def test_weak_hook_after_every_rewrite_still_holds():
    d1 = WARP["draft1"]
    weak = {"scores": dict(GOOD, hook_strength=2), "critique": "weak"}
    f = Fake(script_write=[d1, d1], script_critic=[weak, weak])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "HOLD"
    assert "hook_strength=2 < 3" in res["candidates"][0]["reason"]


def test_draft_that_never_clears_code_rules_still_holds():
    d2 = WARP["draft2"]
    f = Fake(script_write=[d2, d2])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "HOLD"
    assert "still failing" in res["candidates"][0]["reason"]
