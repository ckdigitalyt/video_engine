"""2026-11-11 review, item 2: voice QA homophone / spelling false positives.

The round-trip comparator matched the script and the ASR transcript by
spelling, so correctly read words written differently by faster-whisper
held whole renders: weight/"wait", sac/"sack", hertz/"hz",
nanometres/"nanometers", doughnut/"donut". max_wer is 0.03 per beat; one
such word on a 9-13 word beat scores 0.08-0.11. ~10 earlier commits added
one _SPELLING pair at a time. Now a non-hard word whose espeak-ng (Kokoro's
own phonemizer) phonemes match the heard word's counts as correct, and unit
abbreviations are expanded literally.

Replay of the 151 stored FAIL/HOLD beat transcripts (stories/*/audio/
beat_*.voice.json) against their story.json narration: 51 now pass, and
every newly accepted pair is a true homophone (waist/waste, flour/flower,
arc/ark, disc/disk, plain/plane, heir/air, piece/peace, halve/have...).

Run: python3 -m pytest -q tests/test_voice_phonetic_20261111.py   (no network)
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine.voice import phonetic, qa  # noqa: E402
from engine.voice.lexicon import Lexicon  # noqa: E402
from engine.voice.text import norm_tokens  # noqa: E402

espeak = pytest.mark.skipif(phonetic.phonemes("cat") is None,
                            reason="espeak-ng not loadable")


def _rt(script, heard, lex=None):
    asr = [{"w": w, "t0": 0.3 * i, "t1": 0.3 * i + 0.25} for i, w in enumerate(heard.split())]
    return qa.round_trip(script, asr, lex or Lexicon(), 0.03)


# ---- the live held beats, exact stored transcripts --------------------------

@espeak
@pytest.mark.parametrize("script,heard", [
    # t_spider_silk_light_enough_to_wrap_earth B3 (WER 0.0833 -> HOLD)
    ("Instead, weight for weight, it's about five times as strong as steel.",
     "instead wait for weight its about five times as strong as steel"),
    # t_pericardium_your_heart_s_hidden_body_arm B2 (0.1111)
    ("That armor is a protective sac called the pericardium.",
     "that armor is a protective sack called the pericardium"),
    # t_aerogel_99_98_air_yet_it_holds_firm B4 (0.1111)
    ("Its pores are just under a hundred nanometres across.",
     "its pores are just under a hundred nanometers across"),
    # t_air_vortex_cannons_toys_that_shoot_inv B6 (0.0714)
    ("Each shot is just a doughnut-shaped ring of air, an invisible smoke ring.",
     "each shot is just a donut shaped ring of air an invisible smoke ring"),
])
def test_held_homophone_beats_now_pass(script, heard):
    r = _rt(script, heard)
    assert r["verdict"] == "PASS" and r["wer"] == 0, r
    assert r["sound_alike"]


def test_infrasound_hz_abbreviation_passes():
    """t_infrasound_the_sound_that_made_them_sick B4 (0.0909): literal
    expansion, no phonemizer needed (espeak spells "hz" as letters)."""
    r = _rt("Human hearing bottoms out around twenty hertz, so this was infrasound.",
            "human hearing bottoms out around twenty hz so this was infrasound")
    assert r["verdict"] == "PASS" and r["wer"] == 0
    assert norm_tokens("Hz") == ["hertz"] and norm_tokens("mph") == ["miles", "per", "hour"]


def test_unit_abbreviation_accepts_the_plural():
    r = _rt("The probe flew past at ten kilometers a second.",
            "the probe flew past at 10 km a second")
    assert r["verdict"] == "PASS" and r["wer"] == 0


# ---- what must still fail ---------------------------------------------------

@espeak
def test_one_phoneme_apart_is_still_an_error():
    assert not phonetic.same_sound("cat", "bat")
    assert not phonetic.same_sound("bear", "pear")
    r = _rt("A cat can survive the fall.", "a bat can survive the fall")
    assert r["verdict"] == "FAIL" and r["bad_word_idx"] == [1]


@espeak
def test_names_and_numbers_stay_strict_even_when_homophones():
    # "Webb" mid-sentence is a name (hard word): no phoneme relaxation for it
    # beyond the existing _SPELLING entry; a homophone NAME not in that table
    # stays a hard miss.
    r = _rt("Then Wright flew the glider again.", "then right flew the glider again")
    assert r["verdict"] == "FAIL" and r["hard_missed"] == ["Wright"]
    # a number word heard as its homophone digit-word is a hard miss too
    r = _rt("They waited for eight long years.", "they waited for ate long years")
    assert r["verdict"] == "FAIL" and r["hard_missed"] == ["eight"]


@espeak
def test_phonemes_ignore_stress_and_length_marks():
    assert phonetic.same_sound("hours", "ours")       # ˈaʊɚz vs aʊɚz
    assert phonetic.same_sound("their", "there")
    assert phonetic.same_sound("weight", "wait")


def test_espeak_unavailable_falls_back_to_strict(monkeypatch):
    monkeypatch.setattr(phonetic, "_unavailable", True)
    phonetic.phonemes.cache_clear()
    try:
        assert phonetic.phonemes("weight") is None
        assert not phonetic.same_sound("weight", "wait")
        r = _rt("Instead, weight for weight, it's strong.", "instead wait for weight its strong")
        assert r["verdict"] == "FAIL"
    finally:
        phonetic.phonemes.cache_clear()
