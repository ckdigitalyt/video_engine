"""2026-10-24 analytics review, item 5: titles may lead with a literal,
searchable label, then a curiosity hook ("Acoustic Levitation: Sound That
Holds Objects Up"). The one plain, searchable title earned 12% of its views
from YouTube search, against 2-3% for curiosity-gap titles. A bare label
and the "(It's Real)" parenthetical stay banned. No network.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_metadata as M  # noqa: E402
from engine import v16_script as S  # noqa: E402
from llm.prompts import render  # noqa: E402

STORY = {"story_id": "s", "title": "Sound That Lifts Things",
         "beats": [{"beat_id": "B1", "function": "HOOK", "narration": "Sound can lift a bead.",
                    "claim": "a b c", "fact_ids": ["f"]}]}


def test_hybrid_label_plus_hook_titles_pass_both_title_paths():
    for t in ("Acoustic Levitation: Sound That Holds Objects Up",
              "Diamagnetism: Why This Frog Can Float",
              "G-Force Blackouts: Pilots Train To Pass Out"):
        assert S.check_title(t) == [], t
        assert M.check_title_rules(t) == [], t


def test_pure_curiosity_gap_titles_still_pass():
    assert M.check_title_rules("What Can Invisible Sound Hold Up?") == []
    assert S.check_title("Why Pilots Train To Black Out On Purpose") == []


def test_label_with_a_generic_or_missing_hook_is_rejected():
    for t in ("Acoustic Levitation Facts: The Real Truth",
              "Acoustic Levitation: Explained Simply",
              "Acoustic Levitation: Full Science Explanation"):
        errs = S.check_title(t)
        assert any("curiosity hook" in e for e in errs), (t, errs)
    long_label = "Why Sound Waves Can Hold Things: In Midair Forever"
    assert any("lead-in" in e for e in S.check_title(long_label))
    assert any("more than one colon" in e for e in S.check_title("A: Sound Lifts: Beads Up"))


def test_meta_3_0_bans_are_kept():
    assert M.check_title_rules("Sound Waves That Levitate Objects (It's Real)")   # parenthetical
    assert M.check_title_rules("Levitation")                                      # < 4 words
    assert M.check_title_rules("Acoustic Levitation: You Won't Believe This")     # trope


def test_prompts_offer_the_hybrid_shape():
    p = M.build_prompt(STORY)
    assert M.PROMPT_VERSION == "meta/3.1"
    assert "searchable label + hook" in p and "Acoustic Levitation: Sound That" in p
    assert "not label the topic" in p and "curiosity gap" in p
    assert "12%" in p
    p2, ver = render("metadata_pack", script="1. x", facts="f | c", series_note="")
    assert ver == "3" and "searchable" in p2 and "never a bare topic label" in p2
