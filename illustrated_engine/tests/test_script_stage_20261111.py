"""2026-11-11 review item 4: script-stage fixes.

  - the fact-check rewrite gets its own code-fix pass (5 of 14 on-disk
    script holds were code rules broken BY that rewrite);
  - rank_write_story finalizes the next scored candidate when the top one's
    fact-check/metadata tail holds (it used to hold the slot);
  - hook_headline / on_screen are not gated: script_to_story drops them.

Run: python3 -m pytest -q tests/test_script_stage_20261111.py   (no network)
"""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_autostory as A  # noqa: E402
from engine import v16_script as S  # noqa: E402
from llm.client import LLMUnavailable  # noqa: E402

WARP = json.loads((ROOT / "tests" / "fixtures" / "warp_bubble_20261015.json").read_text())
FACTS = {"claims": [{**c, "evidence": c["quote"], "quote_verified": True,
                     "verified": True, "curated": False} for c in WARP["claims"]]}
D1, D2 = WARP["draft1"], WARP["draft2"]          # D1 code-clean, D2 breaks rules
GOOD = dict.fromkeys(WARP["critic1"]["scores"], 4)
TOP = dict(GOOD, payoff_clarity=5)               # ranks above GOOD; both clear every bar
META = {"title": "A Ship That Never Speeds Up", "title_fact_ids": ["f_warp_contract_expand"],
        "description": "x", "hashtags": ["#space", "#physics", "#science"],
        "series_tag": "", "pinned_comment": "?"}


class Fake:
    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}
        self.stages = []

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        self.stages.append(stage)
        item = self.q[stage].pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(data=copy.deepcopy(item), model="fake", cached=False,
                               attempts=1, usage={})


def _fc(script, bad=()):
    return {"sentences": [{"n": i, "label": "unsupported" if i in bad else "supported",
                           "note": "overstated"}
                          for i in range(1, len(script["sentences"]) + 1)]}


def _crit(scores):
    return {"scores": scores, "critique": ""}


def test_fixture_shapes():
    assert S.code_checks(D1, FACTS) == [] and S.code_checks(D2, FACTS)


def test_fact_check_rewrite_that_breaks_code_rules_gets_a_code_fix():
    f = Fake(script_write=[D1, D2, D1], script_critic=[_crit(GOOD)],
             fact_check=[_fc(D1, bad=(2,)), _fc(D1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", FACTS)], ask=f)
    assert res["verdict"] == "PASS", res
    assert res["story"]["fact_check_code_fixes"] == 1
    assert res["story"]["script"] == D1


def test_fact_check_rewrite_still_holds_if_the_code_fix_fails_too():
    f = Fake(script_write=[D1, D2, D2], script_critic=[_crit(GOOD)],
             fact_check=[_fc(D1, bad=(2,))])
    res = S.rank_write_story([("Warp", FACTS)], ask=f)
    assert res["verdict"] == "HOLD"
    assert "after the fact-check rewrite" in res["story"]["holds"][0]


def test_second_scored_candidate_is_finalized_when_the_first_holds():
    # A ranks first; its fact-check never clears -> B must be tried.
    f = Fake(script_write=[D1, D1, D1], script_critic=[_crit(TOP), _crit(GOOD)],
             fact_check=[_fc(D1, bad=(1,)), _fc(D1, bad=(1,)), _fc(D1)],
             metadata_pack=[META])
    res = S.rank_write_story([("A", FACTS), ("B", FACTS)], ask=f)
    assert res["verdict"] == "PASS", res
    assert res["picked_topic"] == "B"
    by = {c["topic"]: c for c in res["candidates"]}
    assert by["A"]["finalize"] == "HOLD" and by["A"]["finalize_holds"]
    assert by["B"]["finalize"] == "PASS"


def test_top_candidate_passing_never_finalizes_the_second():
    f = Fake(script_write=[D1, D1], script_critic=[_crit(TOP), _crit(GOOD)],
             fact_check=[_fc(D1)], metadata_pack=[META])
    res = S.rank_write_story([("A", FACTS), ("B", FACTS)], ask=f)
    assert res["picked_topic"] == "A"
    assert f.stages.count("fact_check") == 1
    assert "finalize" not in {c["topic"]: c for c in res["candidates"]}["B"]


def test_llm_outage_during_finalize_stops_the_walk():
    f = Fake(script_write=[D1, D1], script_critic=[_crit(TOP), _crit(GOOD)],
             fact_check=[LLMUnavailable("session limit", "quota")])
    res = S.rank_write_story([("A", FACTS), ("B", FACTS)], ask=f)
    assert res["verdict"] == "HOLD"
    assert res["picked_topic"] == "A"
    assert f.stages.count("fact_check") == 1


def test_all_finalize_holds_reported_per_candidate_by_autostory(monkeypatch):
    f = Fake(script_write=[D1, D1, D1, D1],
             script_critic=[_crit(TOP), _crit(GOOD)],
             fact_check=[_fc(D1, bad=(1,))] * 4)
    monkeypatch.setattr(A, "build_facts", lambda title, src, ask=None: FACTS)
    cands = [{"title": "A", "id": "a"}, {"title": "B", "id": "b"}]
    res = A.generate_story_ranked(cands, ask=f,
                                  fetch_sources=lambda q, n: ["u1", "u2"])
    assert res["status"] == "hold"
    assert "A: mean" in res["reason"] and "B: mean" in res["reason"]


def test_dropped_fields_do_not_gate_the_script():
    sc = copy.deepcopy(D1)
    sc["hook_headline"] = "x"
    sc["sentences"][1]["on_screen"] = ["999 km"]
    assert S.code_checks(sc, FACTS) == []
    story = A.script_to_story({"title": "T", "id": "t"},
                              {"script": sc, "metadata": META, "critic": None}, FACTS)
    assert "hook_headline" not in json.dumps(story)
    assert "on_screen" not in json.dumps(story)
