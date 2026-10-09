"""Decision #18 item 1: caption clause-break fixes (dry run 5's real cues)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.v15_gate import check_caption_clause_breaks  # noqa: E402
from engine.v15_pipeline import caption_cues  # noqa: E402
from engine.voice.text import numeralize_cue_words  # noqa: E402


def _timing(text: str, pauses: dict | None = None) -> dict:
    """Evenly spaced words (0.3 s each), optional extra pause AFTER word i."""
    words, t = [], 0.0
    for i, w in enumerate(text.split()):
        words.append({"w": w, "t0": round(t, 3), "t1": round(t + 0.25, 3)})
        t += 0.3 + (pauses or {}).get(i, 0.0)
    return {"words": words}


def _texts(text, pauses=None):
    return [c["text"] for c in caption_cues(_timing(text, pauses), 0.18)]


def _nums(text):
    return [w["w"] for w in numeralize_cue_words(
        [{"w": x, "t0": 0, "t1": 0} for x in text.split()])]


def test_no_lone_function_word_cue_dry_run5_b6():
    cues = _texts("It faded gradually, over up to one and a half seconds.",
                  pauses={3: 0.3})
    assert "to" not in cues and "up" not in cues, cues
    assert check_caption_clause_breaks(
        [{"text": c, "t0": i} for i, c in enumerate(cues)])["ok"], cues


def test_up_to_stays_with_its_figure_dry_run5_b4():
    cues = _texts("Astronomers saw it pass in front of a star, dimming it "
                  "for up to twenty seconds.", pauses={4: 0.3})
    assert not any(c.split()[-1].lower() in ("up", "to", "for") for c in cues), cues
    assert any("up to 20" in c for c in cues), cues


def test_sentence_end_is_a_hard_boundary_and_words_preserved():
    text = "This tiny world has an atmosphere. It shouldn't still exist."
    cues = _texts(text)
    assert any(c.endswith("atmosphere.") for c in cues), cues
    assert " ".join(cues).split() == text.split()


def test_cue_length_bounded():
    cues = _texts("one two three four five six seven eight nine ten eleven "
                  "twelve thirteen fourteen fifteen sixteen.")
    assert all(len(c.split()) <= 7 and len(c) <= 36 for c in cues), cues


def test_gate_accepts_punctuation_terminated_cue():
    r = check_caption_clause_breaks([{"text": "that breaks it:", "t0": 0},
                                     {"text": "dimming it for", "t0": 1}])
    assert r["fails"] == ["cue 'dimming it for' ends on a function word "
                          "(mid-clause break)"], r


def test_numeral_range_across_scales_is_not_a_subtraction():
    assert _nums("within one hundred to one thousand years.") == \
        ["within", "100-1,000", "years."]
    # a shared scale still shares it
    assert _nums("fifty to sixty thousand") == ["50,000-60,000"]
    assert _nums("one hundred fifty-five to one hundred forty-five million "
                 "years") == ["155-145 million", "years"]
    assert _nums("five hundred to one million") == ["500 to 1 million"]


def test_numeral_small_forms():
    assert _nums("one and a half seconds.") == ["1.5", "seconds."]
    assert _nums("up to a hundred times") == ["up", "to", "100", "times"]
    assert _nums("a thousand years") == ["1,000", "years"]
    assert _nums("one two three") == ["1", "2", "3"]
