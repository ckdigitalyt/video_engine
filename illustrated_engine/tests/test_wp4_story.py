"""WP4 - story engine S1-S4: quote-exists check, digit guard, title rules, length
and hook rules, critic/rewrite/fact-check orchestration.

Run: python3 tests/test_wp4_story.py   (exit 0 = all passed; fake `ask`, no network, no LLM)
"""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

from engine import v16_research as R  # noqa: E402
from engine import v16_script as S  # noqa: E402
from llm import client  # noqa: E402
from llm.prompts import render  # noqa: E402
from llm.types import LLMUnavailable  # noqa: E402

PACK = json.loads((ROOT.parent / "bench/quality/topics/02_tunguska/facts.json").read_text())
FACTS = R.from_curated(PACK)

TEXTS = [
    ("Something flattened a Siberian forest and left no crater.", "hook", ["f_kulik_1927"]),
    ("It was the morning of 30 June 1908.", "normal", ["f_flattened_forest"]),
    ("In minutes, roughly two thousand square kilometres of trees went down, about 80 million of them.",
     "normal", ["f_flattened_forest"]),
    ("Sixty-five kilometres away, people felt the heat and were thrown from their chairs.",
     "normal", ["f_eyewitness_vanavara"]),
    ("For nights afterward, skies glowed across Europe and Asia, and instruments far away "
     "felt the pressure wave.", "normal", ["f_global_signals"]),
    ("When the first expedition finally arrived in 1927, the trees were flattened in a fan, "
     "and the ones near the centre still stood, stripped bare.", "normal", ["f_kulik_1927"]),
    ("There was no hole in the ground at all.", "normal", ["f_kulik_1927"]),
    ("The leading explanation is an asteroid that burst in the air, five to ten kilometres up, "
     "and never reached the ground in one piece.", "payoff", ["f_airburst_model"]),
    ("So the sky did the damage, and that is why the forest fell and the ground stayed whole.",
     "payoff", ["f_airburst_model"]),
]


def good_script():
    return {"hook_headline": "The Blast With No Crater",
            "sentences": [{"text": t, "role": r, "fact_ids": list(f)} for t, r, f in TEXTS]}


def wc(script):
    return len(S.narration(script).split())


# ---------------------------------------------------------------- S1 -----

def test_numbers_in():
    assert R.numbers_in("Sixty-five kilometres, two thousand square kilometres") == {65.0, 2000.0}
    assert R.numbers_in("80 million trees on 30 June 1908, 2,000-2,150 km") == \
        {80e6, 30.0, 1908.0, 2000.0, 2150.0}
    assert R.numbers_in("eighty million") == {80e6}
    assert R.numbers_in("one hundred and five") == {105.0}
    assert R.numbers_in("seven five") == {7.0, 5.0}                     # two numbers
    assert R.numbers_in("It is one. In two ways") == {1.0, 2.0}
    assert R.numbers_in("It is one. In two ways", min_spelled=11) == set()
    assert R.numbers_in("about 2.5 billion") == {2.5e9}
    assert R.numbers_in("in 1908, the") == {1908.0}                     # no trailing comma glue


def test_quote_exists():
    src = "The  Tunguska event\nflattened—roughly 2,000 square kilometres of “forest” in 1908."
    assert R.quote_exists('flattened-roughly 2,000 square kilometres of "forest"', src)
    assert R.quote_exists("THE TUNGUSKA EVENT FLATTENED", src)
    assert not R.quote_exists("flattened roughly 2,100 square kilometres", src)      # changed number
    assert not R.quote_exists("the event destroyed roughly 2,000 square km", src)    # paraphrase
    assert not R.quote_exists("event", src)                                          # too short to prove anything


SRC = {"id": "s1", "url": "https://example.org/a",
       "text": "The Tunguska event of 1908 flattened about 80 million trees over roughly 2,000 "
               "square kilometres of Siberian forest. Eyewitnesses at Vanavara, 65 kilometres "
               "away, were thrown from their chairs. Kulik's 1927 expedition found no crater. "
               "Most researchers favour an airburst explanation for the blast."}


def _claims(*rows):
    return SimpleNamespace(data={"claims": [
        {"id": i, "claim": c, "quote": q, "source_id": s, "nuance": "ESTABLISHED"}
        for i, c, q, s in rows]}, model="sonnet", cached=False, attempts=1, usage={})


Q1 = "flattened about 80 million trees over roughly 2,000 square kilometres"
Q2 = "were thrown from their chairs"
Q3 = "Kulik's 1927 expedition found no crater"
Q4 = "Most researchers favour an airburst explanation"


def test_check_claim_rules():
    by = {"s1": SRC["text"]}
    ok = {"id": "f_a", "claim": "It flattened about 80 million trees.", "quote": Q1, "source_id": "s1"}
    assert R.check_claim(ok, by) is None
    assert "quote not found" in R.check_claim({**ok, "quote": "flattened about 90 million trees"}, by)
    assert "unknown source" in R.check_claim({**ok, "source_id": "zz"}, by)
    assert "numbers not in the quote" in R.check_claim({**ok, "claim": "It flattened 2,150 square km."}, by)


def test_build_facts_drops_bad_quotes():
    rows = [("f_a", "About 80 million trees fell.", Q1, "s1"),
            ("f_b", "People were thrown from chairs.", Q2, "s1"),
            ("f_c", "No crater was found in 1927.", Q3, "s1"),
            ("f_d", "It never happened.", "this sentence is not in the source at all", "s1")]
    got = R.build_facts("Tunguska", [SRC], ask=lambda *a, **k: _claims(*rows))
    assert [c["id"] for c in got["claims"]] == ["f_a", "f_b", "f_c"]
    assert got["dropped"][0]["id"] == "f_d"
    assert all(R.usable(c) and c["quote_verified"] and c["source_url"] for c in got["claims"])


def test_build_facts_holds_below_minimum():
    rows = [("f_a", "About 80 million trees fell.", Q1, "s1"),
            ("f_d", "Made up.", "this sentence is not in the source at all", "s1"),
            ("f_e", "Also made up.", "neither is this sentence in the source", "s1")]
    try:
        R.build_facts("Tunguska", [SRC], ask=lambda *a, **k: _claims(*rows))
    except R.ResearchHold as e:
        assert "only 1 claims" in str(e)
    else:
        raise AssertionError("expected ResearchHold")


def test_curated_unverified_is_not_usable():
    pack = {"title": "x", "claims": [
        {"id": "f_u", "claim": "c" * 20, "verified": False},
        {"id": "f_v", "claim": "d" * 20, "verified": True}]}
    got = R.from_curated(pack)
    assert [R.usable(c) for c in got["claims"]] == [False, True]
    assert all(not c["quote_verified"] for c in got["claims"])
    corrected = R.from_curated({"claims": [{"id": "f_c", "claim": "old wording here", "verified": True,
                                            "correction": "corrected wording here", "nuance": "DEBATED_DETAIL"}]})
    c = corrected["claims"][0]
    assert c["claim"] == "corrected wording here" and c["nuance"] == "CONTESTED"


# ---------------------------------------------------------------- S2 -----

def test_good_script_passes_every_code_check():
    sc = good_script()
    assert 75 <= wc(sc) <= 140, wc(sc)
    assert S.code_checks(sc, FACTS) == [], S.code_checks(sc, FACTS)


def test_length_rules():
    sc = good_script()
    sc["sentences"] = sc["sentences"][:4]
    sc["sentences"][-1]["role"] = "payoff"
    assert any(e.startswith("length") for e in S.check_script(sc))
    sc = good_script()
    sc["sentences"][2]["text"] += " " + "word " * 80
    assert any(e.startswith("length") for e in S.check_script(sc))


def test_hook_rules():
    sc = good_script()
    sc["sentences"][0]["text"] = "Why did something flatten a Siberian forest?"
    assert any("bare question" in e for e in S.check_script(sc))
    sc = good_script()
    sc["sentences"][0]["text"] = "Did you know something flattened a forest?"
    assert any("filler opener" in e for e in S.check_script(sc))
    sc = good_script()
    sc["sentences"][0]["text"] = "One cold morning in 1908 something flattened a Siberian forest and left no crater."
    assert any("hook: first sentence has" in e for e in S.check_script(sc))
    sc = good_script()
    sc["hook_headline"] = "The"
    assert any("hook_headline" in e for e in S.check_script(sc))


def test_narration_digits_are_voice_safe():
    sc = good_script()
    assert S.check_script(sc) == []                       # "30 June 1908" (a date/year) is fine
    sc["sentences"][2]["text"] = "Roughly 2,000 square kilometres of forest went flat."
    assert any(e.startswith("digits") for e in S.check_script(sc))
    sc["sentences"][2]["text"] = "About 80000000 trees fell."
    assert any(e.startswith("digits") for e in S.check_script(sc))
    sc["sentences"][2]["text"] = "It was 2.5 times bigger."
    assert any(e.startswith("digits") for e in S.check_script(sc))


def test_role_and_loop_rules():
    sc = good_script()
    sc["sentences"][3]["role"] = "hook"
    assert any("exactly one hook" in e for e in S.check_script(sc))
    sc = good_script()
    sc["sentences"][-1]["role"] = "normal"
    assert any("last sentence must have role payoff" in e for e in S.check_script(sc))
    sc = good_script()
    sc["sentences"][-1]["text"] = "Follow for part two, and thanks for watching."
    assert any("call to action" in e for e in S.check_script(sc))
    sc = good_script()
    sc["sentences"][-1]["text"] = "So who really knows what fell there?"
    assert any("must resolve" in e for e in S.check_script(sc))


def test_every_sentence_cites_a_usable_fact():
    sc = good_script()
    sc["sentences"][1]["fact_ids"] = ["f_does_not_exist"]
    sc["sentences"][2]["fact_ids"] = []
    errs = S.check_facts(sc, FACTS)
    assert len(errs) == 2 and "sentence 2" in errs[0]
    unverified = copy.deepcopy(FACTS)
    unverified["claims"][0]["verified"] = False
    assert any("sentence 2" in e for e in S.check_facts(good_script(), unverified))


def test_digit_guard_narration_vs_cited_facts():
    f = {"claims": [{"id": "f_x", "claim": "the blast flattened roughly 2,000 square kilometres",
                     "evidence": "roughly 2,000 square kilometres", "quote": None,
                     "curated": True, "verified": True}]}
    sc = {"hook_headline": "Two Thousand", "sentences": [
        {"text": "It flattened 2,000 square kilometres.", "role": "hook", "fact_ids": ["f_x"]}]}
    assert S.check_digits(sc, f) == []
    sc["sentences"][0]["text"] = "It flattened 2,150 square kilometres."      # DESIGN §9.4 example
    assert "2150" in S.check_digits(sc, f)[0].replace(".0", "").replace(",", "")
    sc["sentences"][0]["text"] = "It flattened two thousand one hundred fifty square kilometres."
    assert S.check_digits(sc, f)
    sc["sentences"][0]["text"] = "It flattened two thousand square kilometres."  # spelled == digits
    assert S.check_digits(sc, f) == []
    # a number that is in ANOTHER fact but not in the cited one is still a miss
    f["claims"].append({"id": "f_y", "claim": "80 million trees", "evidence": "80 million trees",
                        "curated": True, "verified": True})
    sc["sentences"][0]["text"] = "It felled 80 million trees."
    assert S.check_digits(sc, f)
    sc["sentences"][0]["fact_ids"] = ["f_y"]
    assert S.check_digits(sc, f) == []


def test_on_screen_digits_must_be_spoken():
    sc = good_script()
    sc["sentences"][3]["on_screen"] = ["65 km"]
    assert S.check_digits(sc, FACTS) == []
    sc["sentences"][3]["on_screen"] = ["650 km"]
    assert any("never spoken" in e for e in S.check_digits(sc, FACTS))


def test_duration_gate():
    assert S.check_duration(45.0) == []
    assert S.check_duration(29.9)
    assert S.check_duration(61.0)
    assert S.check_duration(61.0, {"length_justification": "two-part reveal"}) == []


# -------------------------------- decision #16 item 2: absolute-claim check --

# decision #15 step 3's real Everest script (build_reports/decision15/step3_full_scripts.json):
# "That's been done only once, by Tim Macartney-Snape's team in 1990." cites
# f_sea_level_climb. In reality Macartney-Snape's 1990 climb was solo/unsupported but
# NOT unique -- Reinhold Kropp (sic: the real other sea-to-summit climber) also made a
# full ascent from sea level in 1996 -- so a fact that only describes Macartney-Snape's
# climb, without itself asserting nobody else has done one, must NOT satisfy the
# absolute claim "only once". Facts.json fixture matches the research-stage shape from
# engine.v16_research.build_facts (id/claim/evidence/quote/source_id/nuance).
EVEREST_FACT_UNSUPPORTED = {
    "id": "f_sea_level_climb",
    "claim": "Tim Macartney-Snape's team climbed Everest from the Bay of Bengal to the "
             "summit without supplemental oxygen in 1990.",
    "evidence": "Macartney-Snape's 1990 sea-to-summit ascent is documented as unsupported "
               "and without bottled oxygen.",
    "quote": "Macartney-Snape walked from the Bay of Bengal to the summit of Everest",
    "source_id": "src1", "quote_verified": True, "curated": False, "verified": True,
    "nuance": "ESTABLISHED",
}
EVEREST_FACT_SUPPORTED = {
    **EVEREST_FACT_UNSUPPORTED,
    "claim": "Tim Macartney-Snape's team is the only climbing party ever documented "
             "making a full, unsupported sea-to-summit ascent of Everest.",
}
EVEREST_FACTS_UNSUPPORTED = {"claims": [EVEREST_FACT_UNSUPPORTED]}
EVEREST_FACTS_SUPPORTED = {"claims": [EVEREST_FACT_SUPPORTED]}
EVEREST_SENTENCE = "That's been done only once, by Tim Macartney-Snape's team in 1990."


def test_absolute_claim_everest_only_once_fails_without_exclusivity_support():
    sc = {"hook_headline": "The Solo Climb", "sentences": [
        {"text": EVEREST_SENTENCE, "role": "hook", "fact_ids": ["f_sea_level_climb"]}]}
    errs = S.check_absolute_claims(sc, EVEREST_FACTS_UNSUPPORTED)
    assert errs and "only" in errs[0].lower() and "sentence 1" in errs[0]


def test_absolute_claim_everest_only_once_passes_with_exclusivity_support():
    sc = {"hook_headline": "The Solo Climb", "sentences": [
        {"text": EVEREST_SENTENCE, "role": "hook", "fact_ids": ["f_sea_level_climb"]}]}
    assert S.check_absolute_claims(sc, EVEREST_FACTS_SUPPORTED) == []


def test_absolute_claim_softened_everest_sentence_has_no_claim_to_support():
    sc = {"hook_headline": "The Solo Climb", "sentences": [
        {"text": "That was done solo, by Tim Macartney-Snape's team in 1990, though "
                 "others have since made similar sea-to-summit climbs.",
         "role": "hook", "fact_ids": ["f_sea_level_climb"]}]}
    assert S.check_absolute_claims(sc, EVEREST_FACTS_UNSUPPORTED) == []


def test_absolute_claim_detector_catches_common_superlatives_and_never_always():
    base = {"id": "f_y", "claim": "x", "evidence": "x", "quote": None,
           "curated": True, "verified": True}
    facts = {"claims": [base]}
    for text in ("This is the biggest blast ever recorded.",
                "No one has ever seen anything like it.",
                "The forest never grew back the same way.",
                "Scientists always assumed it was an asteroid."):
        sc = {"hook_headline": "H", "sentences": [
            {"text": text, "role": "hook", "fact_ids": ["f_y"]}]}
        errs = S.check_absolute_claims(sc, facts)
        assert errs, text


def test_absolute_claim_check_feeds_into_code_checks():
    # f_eyewitness_vanavara's claim text (bench/quality/topics/02_tunguska/facts.json)
    # carries no absolute/superlative marker of its own, so citing it for an "only"
    # claim must still fail -- unlike f_kulik_1927, whose real claim text happens to
    # contain "the first" and would otherwise accidentally "support" any absolute claim.
    sc = good_script()
    sc["sentences"][0]["text"] = "Only one blast like this has ever been recorded."
    sc["sentences"][0]["fact_ids"] = ["f_eyewitness_vanavara"]
    errs = S.code_checks(sc, FACTS)
    assert any("absolute/superlative" in e or "only" in e.lower() for e in errs)


# ---------------------------------------------------------------- S4 -----

def test_title_rules():
    ok = "The Blast With No Crater"
    assert S.check_title(ok) == []
    assert S.check_title("Flat Forest") and S.check_title("A very long title that just keeps going on")
    assert any("hashtag" in e for e in S.check_title("The Blast With No #Crater"))
    assert any("emoji" in e for e in S.check_title("The Blast With No Crater \U0001F4A5"))
    assert any("ALL-CAPS" in e for e in S.check_title("THE BLAST WITH NO CRATER"))
    assert S.check_title("How NASA Tracks The Blast Now") == []           # acronym allowed
    assert any("trope" in e for e in S.check_title("Scientists baffled by the Siberian blast"))
    assert S.check_title("The 2,150 Square Kilometre Blast", fact_numbers={2000.0})
    assert S.check_title("The 2,000 Square Kilometre Blast", fact_numbers={2000.0}) == []


def test_title_batch_question_share():
    assert S.check_title_batch(["How Ice Works Today", "Why Birds Are Dinosaurs", "The Blast With No Crater"])
    assert S.check_title_batch(["How Ice Works Today", "The Blast With No Crater"]) == []
    assert S.check_title_batch([]) == []


META = {"title": "The Blast With No Crater", "title_fact_ids": ["f_kulik_1927"],
        "description": "A forest fell. Nothing hit the ground.", "hashtags": ["#science", "#history", "#space"],
        "series_tag": "standalone", "pinned_comment": "What do you think came down?"}


def test_metadata_checks_and_description():
    assert S.check_metadata(META, FACTS) == []
    bad = {**META, "title_fact_ids": ["f_nope"]}
    assert any("missing/unusable" in e for e in S.check_metadata(bad, FACTS))
    assert S.check_metadata({**META, "hashtags": ["#a", "#b"]}, FACTS)
    assert S.check_metadata({**META, "hashtags": ["a", "#b", "#c"]}, FACTS)
    assert S.check_metadata(META, FACTS, batch_titles=["How A", "Why B"])
    d = S.build_description(META, FACTS, ["f_kulik_1927", "f_flattened_forest"])
    assert "Sources:" in d and S.AI_NOTE in d and d.rstrip().endswith("#space")
    assert "https://doi.org" in d


def test_critic_bar():
    ok = dict.fromkeys(["a", "b", "c", "d", "e", "f", "g", "h"], 4)
    assert S.critic_pass(ok)
    assert not S.critic_pass({**ok, "a": 2})                    # a 2 fails even with a 4.0 mean
    assert not S.critic_pass({**ok, "a": 3})                    # mean 3.875
    assert S.critic_pass({**ok, "a": 3, "b": 5})                # mean 4.0, floor 3


# ------------------------------------------ decision #16 item 1: rank floor ----

RANK_DIMS = ["hook_strength", "curiosity_gap", "escalation", "payoff_clarity",
            "loop_coherence", "human_voice", "emotional_charge", "one_idea_only"]


def test_dim_floor_is_2_except_payoff_clarity_and_one_idea_only():
    assert S.dim_floor("hook_strength") == 2
    assert S.dim_floor("escalation") == 2
    assert S.dim_floor("emotional_charge") == 2
    assert S.dim_floor("payoff_clarity") == 3
    assert S.dim_floor("one_idea_only") == 3


def test_clears_rank_floor_mean_3_every_dim_2_except_payoff_and_one_idea():
    # mean exactly 3.0, every dim >= 2, payoff_clarity/one_idea_only at the stricter 3
    scores = {**dict.fromkeys(RANK_DIMS, 3), "escalation": 2, "emotional_charge": 4}
    assert sum(scores.values()) / len(scores) == 3.0
    assert S.clears_rank_floor(scores)
    # the owner's own accepted skater sample shape (decision #15 step 1): mean 2.75,
    # escalation/emotional_charge at 2 -- fails the new mean floor too (3.0 > 2.75)
    skater_shaped = {**dict.fromkeys(RANK_DIMS, 3), "curiosity_gap": 2, "emotional_charge": 2}
    assert sum(skater_shaped.values()) / len(skater_shaped) == 2.75
    assert not S.clears_rank_floor(skater_shaped)


def test_clears_rank_floor_fails_when_payoff_clarity_or_one_idea_only_below_3():
    # mean held well above 3.0 so only the per-dimension floor is under test
    scores_hi = dict.fromkeys(RANK_DIMS, 4)
    assert S.clears_rank_floor(scores_hi)
    assert not S.clears_rank_floor({**scores_hi, "payoff_clarity": 2})
    assert not S.clears_rank_floor({**scores_hi, "one_idea_only": 2})
    assert S.clears_rank_floor({**scores_hi, "escalation": 2})       # 2 is fine for a non-strict dim


def test_clears_rank_floor_fails_below_mean_3():
    scores = dict.fromkeys(RANK_DIMS, 2)
    scores["payoff_clarity"] = scores["one_idea_only"] = 3
    assert sum(scores.values()) / len(scores) < 3.0
    assert not S.clears_rank_floor(scores)


# ------------------------------------------------------ orchestration ----

GOOD_SCORES = dict.fromkeys(["hook_strength", "curiosity_gap", "escalation", "payoff_clarity",
                             "loop_coherence", "human_voice", "emotional_charge", "one_idea_only"], 4)
BAD_SCORES = {**GOOD_SCORES, "hook_strength": 2}


class Fake:
    """Queue of responses per stage; records prompts."""

    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}
        self.prompts = []

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        self.prompts.append((stage, prompt))
        item = self.q[stage].pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(data=item, model="fake", cached=False, attempts=1, usage={"cost_usd": 0.01})


def fc_ok(script):
    return {"sentences": [{"n": i, "label": "supported"} for i in range(1, len(script["sentences"]) + 1)]}


def fc_bad(script):
    d = fc_ok(script)
    d["sentences"][2] = {"n": 3, "label": "unsupported", "note": "adds a number"}
    return d


def stages(fake):
    return [s for s, _ in fake.prompts]


def test_happy_path_four_calls():
    sc = good_script()
    f = Fake(script_write=[sc], script_critic=[{"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_ok(sc)], metadata_pack=[dict(META)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "PASS" and st["holds"] == [], st["holds"]
    assert stages(f) == ["script_write", "script_critic", "fact_check", "metadata_pack"]
    assert st["llm_calls"] == 4 and "Sources:" in st["metadata"]["description_full"]


def test_code_error_costs_a_rewrite_not_a_critic_call():
    bad = good_script()
    bad["sentences"][0]["text"] = "Why did a forest fall?"
    sc = good_script()
    f = Fake(script_write=[bad, sc], script_critic=[{"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_ok(sc)], metadata_pack=[dict(META)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "PASS"
    assert stages(f) == ["script_write", "script_write", "script_critic", "fact_check", "metadata_pack"]
    assert "bare question" in f.prompts[1][1]                     # the errors reach the rewrite


def test_code_error_twice_holds_without_critic():
    bad = good_script()
    bad["sentences"][0]["text"] = "Why did a forest fall?"
    f = Fake(script_write=[bad, copy.deepcopy(bad)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "HOLD" and "still failing" in st["holds"][0]
    assert stages(f) == ["script_write", "script_write"]


def test_critic_fail_one_rewrite_then_pass():
    sc = good_script()
    f = Fake(script_write=[sc, sc], script_critic=[{"scores": BAD_SCORES, "critique": "sharpen the hook"},
                                                   {"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_ok(sc)], metadata_pack=[dict(META)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "PASS"
    assert stages(f) == ["script_write", "script_critic", "script_write", "script_critic",
                         "fact_check", "metadata_pack"]
    assert "sharpen the hook" in f.prompts[2][1] and "mean of 4.0" in f.prompts[2][1]
    assert len(st["drafts"]) == 2 and st["drafts"][0]["critic"]["scores"] == BAD_SCORES


def test_critic_fail_thrice_holds():
    sc = good_script()
    f = Fake(script_write=[sc, sc, sc], script_critic=[{"scores": BAD_SCORES, "critique": "x"}] * 3)
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "HOLD" and "critic below bar after 2 rewrite(s)" in st["holds"][0]
    assert stages(f).count("script_critic") == 3 and stages(f).count("script_write") == 3
    assert "fact_check" not in stages(f)


def test_critic_fail_twice_then_pass():
    sc = good_script()
    f = Fake(script_write=[sc, sc, sc],
             script_critic=[{"scores": BAD_SCORES, "critique": "x"},
                            {"scores": BAD_SCORES, "critique": "y"},
                            {"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_ok(sc)], metadata_pack=[dict(META)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "PASS"
    assert stages(f).count("script_critic") == 3 and stages(f).count("script_write") == 3


def test_fact_check_fail_one_rewrite_then_pass_and_then_hold():
    sc = good_script()
    f = Fake(script_write=[sc, sc], script_critic=[{"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_bad(sc), fc_ok(sc)], metadata_pack=[dict(META)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "PASS" and stages(f).count("fact_check") == 2
    assert "adds a number" in f.prompts[3][1]
    f = Fake(script_write=[sc, sc], script_critic=[{"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_bad(sc), fc_bad(sc)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "HOLD" and "fact_check still failing" in st["holds"][0]
    assert "metadata_pack" not in stages(f)


def test_fact_check_missing_sentence_is_not_a_pass():
    sc = good_script()
    partial = fc_ok(sc)
    partial["sentences"].pop()
    f = Fake(script_write=[sc, sc], script_critic=[{"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[partial, partial])
    assert S.write_story("Tunguska", FACTS, ask=f)["verdict"] == "HOLD"


def test_metadata_title_rule_failure_retries_once_then_holds():
    sc = good_script()
    bad = {**META, "title": "THE BLAST WITH NO CRATER"}
    f = Fake(script_write=[sc], script_critic=[{"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_ok(sc)], metadata_pack=[bad, dict(META)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "PASS" and stages(f)[-2:] == ["metadata_pack", "metadata_pack"]
    f = Fake(script_write=[sc], script_critic=[{"scores": GOOD_SCORES, "critique": ""}],
             fact_check=[fc_ok(sc)], metadata_pack=[bad, bad])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "HOLD" and "ALL-CAPS" in st["holds"][0]


def test_llm_unavailable_is_a_hold_with_retry_time():
    when = datetime(2026, 9, 28, 19, 30, tzinfo=timezone.utc)
    f = Fake(script_write=[good_script()], script_critic=[LLMUnavailable("quota", "quota", when)])
    st = S.write_story("Tunguska", FACTS, ask=f)
    assert st["verdict"] == "HOLD" and st["retry_at"] == when.isoformat()


# ------------------------------------------------------- prompts/schemas --

def test_prompts_render_and_schemas_are_valid():
    sc = good_script()
    pieces = {
        "research_extract": dict(topic="t", sources="s"),
        "script_write": dict(topic="t", facts="f", series_note="", min_words=75, max_words=140,
                             critique_note=""),
        "script_critic": dict(script="s"),
        "fact_check": dict(facts="f", sentences="s"),
        "metadata_pack": dict(script="s", facts="f", series_note=""),
    }
    for stage, vars_ in pieces.items():
        prompt, ver = render(stage, **vars_)
        assert ver and "{{" not in prompt, stage
        jsonschema.Draft202012Validator.check_schema(client.load_schema(stage))
    try:
        render("script_critic", script="s", extra="x")
    except ValueError:
        pass
    else:
        raise AssertionError("extra var accepted")
    jsonschema.validate(sc, client.load_schema("script_write"))
    jsonschema.validate(META, client.load_schema("metadata_pack"))


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {e!r}"[:400])
    print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)
