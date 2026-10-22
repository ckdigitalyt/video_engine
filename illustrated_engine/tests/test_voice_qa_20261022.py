"""2026-10-22 voice round-trip QA: comparator bugs on correctly-read beats.

Suspected first: a scripted year ("in 1933") compared literally while the
voice says it as a year. Not the cause. small.en writes a year as DIGITS
("1933,", "2003,"), and both sides normalise digits to the same cardinal
words. 0 of the 7 held beats with a year-like token missed on the year.
What really held correctly-read beats (stored wavs re-transcribed with
small.en, the QA model):
  - "Bücks" -> "bcks": norm_tokens deleted the ü (t_sound_can_make_gravity
    B4, WER 0.0435);
  - "70" + ",000." -> "seventy zero": whisper split one figure in two
    (t_this_rock_still_points B6, WER 0.125, hard miss "thousand.");
  - "501" / "100" -> "five hundred one" / "one hundred": digits can't carry
    the script's "and" / "a" (t_no_train_beat_this_maglev B4 0.0588,
    t_a_sail_made_of_nothing B2 0.0625, t_this_isn_t_floating B3 0.0714,
    t_this_ship_has_no_farmland B4 0.0667).
Replaying those 7 stored takes through round_trip: all FAIL before, 6 PASS
after (the 7th, Brunhes-Matuyama B3, was a genuine misreading -> lexicon
phonemes; re-synthesised it round-trips WER 0.0). max_wer and the
hard-token rule are unchanged; the bottom tests show wrong figures and wrong
years still fail.

Run: python3 -m pytest -q tests/test_voice_qa_20261022.py   (no network)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine.voice import qa  # noqa: E402
from engine.voice.lexicon import Lexicon, hard_words  # noqa: E402
from engine.voice.text import (join_split_numbers, norm_tokens,  # noqa: E402
                               restore_number_words)

BRAND_LEX = Lexicon.load(ROOT.parent / "brand" / "ink_ember" / "lexicon.yaml")


def _rt(script, heard_words, lex=None):
    asr = [{"w": w, "t0": 0.3 * i, "t1": 0.3 * i + 0.25}
           for i, w in enumerate(heard_words)]
    return qa.round_trip(script, asr, lex or Lexicon(), 0.03)


# ---- the held beats, with the exact small.en words of the stored takes --

def test_gravity_b4_bucks_diacritic_and_year_pass():
    r = _rt("Bücks and Muller pulled it off in 1933, floating alcohol "
            "droplets between a quartz crystal and a reflector.",
            ["Bux", "and", "Muller", "pulled", "it", "off", "in", "1933,",
             "floating", "alcohol", "droplets", "between", "a", "quartz",
             "crystal", "and", "a", "reflector."], BRAND_LEX)
    assert r["wer"] == 0 and r["verdict"] == "PASS"


def test_diacritics_fold_instead_of_vanishing():
    assert norm_tokens("Bücks") == ["bucks"]
    assert norm_tokens("naïve") == ["naive"] and norm_tokens("Gödel") == ["godel"]
    # a lexicon entry spelled with the diacritic is still a hard word
    assert hard_words("Then Bücks tried.", Lexicon({"bücks": {}})) == [1]


def test_maglev_b4_hundred_and_one_passes():
    r = _rt("And during a non-commercial test run in 2003, it hit five "
            "hundred and one.",
            ["and", "during", "a", "non", "-commercial", "test", "run", "in",
             "2003,", "it", "hit", "501."])
    assert r["wer"] == 0 and r["verdict"] == "PASS"


def test_a_hundred_heard_as_digits_passes():
    for script, heard in [
        ("Fifty to a hundred wires, each about twenty kilometres long, "
         "would fan out from the ship.",
         "50 to 100 wires, each about 20 kilometers long, would fan out "
         "from the ship."),
        ("Scale it to a world ship, over a hundred thousand people, all "
         "fed from inside.",
         "Scale it to a world ship, over 100,000 people, all fed from "
         "inside."),
    ]:
        r = _rt(script, heard.split())
        assert r["wer"] == 0 and r["verdict"] == "PASS", (script, r)


def test_rock_b6_split_thousands_group_rejoined():
    assert join_split_numbers(["as", "70", ",000."]) == ["as", "70,000."]
    assert join_split_numbers(["in", "2003,", "it"]) == ["in", "2003,", "it"]
    r = _rt("Some could stretch as long as seventy thousand.",
            ["Some", "could", "stretch", "as", "long", "as", "70", ",000."])
    assert r["wer"] == 0 and r["verdict"] == "PASS" and r["hard_missed"] == []


def test_rock_b3_brunhes_matuyama_lexicon():
    # re-synthesised with the new phonemes, small.en wrote "Broun Matuyama."
    r = _rt("That flip was the last full reversal, the Brunhes–Matuyama.",
            ["That", "flip", "was", "the", "last", "full", "reversal,",
             "the", "Broun", "Matuyama."], BRAND_LEX)
    assert r["verdict"] == "PASS"
    assert BRAND_LEX.entries["brunhes"]["phonemes"]
    assert BRAND_LEX.entries["matuyama"]["phonemes"]


# ---- still caught --------------------------------------------------------

def test_held_take_of_brunhes_still_fails():
    # the stored (misread) take: default phonemes said BRUN-hz ma-dye-AH-ma
    r = _rt("That flip was the last full reversal, the Brunhes–Matuyama.",
            ["That", "flip", "was", "the", "last", "full", "reversal.",
             "The", "Brunnies", "madayama."], BRAND_LEX)
    assert r["verdict"] == "FAIL" and r["hard_missed"]


def test_wrong_figure_still_fails():
    # "a hundred" read as two hundred; "five hundred and one" as 502
    assert _rt("Fifty to a hundred wires.",
               ["50", "to", "200", "wires."])["verdict"] == "FAIL"
    r = _rt("It hit five hundred and one.", ["It", "hit", "502."])
    assert r["verdict"] == "FAIL" and r["errors"] >= 1
    # an inserted "and" only where the script has that exact triple
    assert restore_number_words(["five", "hundred", "one"],
                                ["five", "hundred", "one"]) == \
        ["five", "hundred", "one"]
    # a "one" that is really "one" is not turned into "a"
    assert restore_number_words(["one", "hundred"], ["one", "hundred"]) == \
        ["one", "hundred"]


def test_wrong_year_and_non_year_numbers_still_compared():
    assert _rt("It flew in 1933, quietly.",
               ["It", "flew", "in", "1934,", "quietly."])["verdict"] == "FAIL"
    assert _rt("The track ran 1500 kilometres.",
               ["The", "track", "ran", "1,500", "kilometers."])["verdict"] == "PASS"
    assert _rt("The track ran 1500 kilometres.",
               ["The", "track", "ran", "1,600", "kilometers."])["verdict"] == "FAIL"


def test_split_group_never_glues_onto_a_word():
    assert join_split_numbers(["seventy", ",000"]) == ["seventy", ",000"]
