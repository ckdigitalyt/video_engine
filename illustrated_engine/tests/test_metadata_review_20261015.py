"""2026-10-15 review, priority 6: curiosity-gap titles held to the script
stage's title rules, no-spoiler description instruction, real sources
instead of "Source/fact-check" boilerplate.

Run: python3 -m pytest -q tests/test_metadata_review_20261015.py   (no network)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_metadata as M  # noqa: E402

STORY = {"story_id": "s", "title": "Sound That Lifts Things",
         "sources": ["https://en.wikipedia.org/wiki/Acoustic_levitation"],
         "beats": [{"beat_id": "B1", "function": "HOOK", "narration": "a b c",
                    "claim": "a b c", "fact_ids": ["f"]}]}
TAGS = [f"tag {i}" for i in range(20)]
DESC = ("Sound you can't hear can hold a coin in mid-air.\n\nMore setup.\n\n"
        "Follow for more.\n\nSource/fact-check: based on peer-reviewed research.\n\n"
        "#shorts #physics #sound")


def test_prompt_asks_for_curiosity_gap_and_no_spoilers():
    p = M.build_prompt(STORY)
    assert "curiosity gap" in p and "not label the topic" in p
    assert "DO NOT give away the" in p
    assert '"Source/fact-check:"' not in p


def test_title_rules_shared_with_script_stage():
    assert M.check_title_rules("Sound Waves That Levitate Objects (It's Real)")
    assert M.check_title_rules("SHOCKED by levitating sound")
    assert M.check_title_rules("Levitation")                    # < 4 words
    assert M.check_title_rules("What Can Invisible Sound Hold Up?") == []


def test_real_sources_replace_boilerplate():
    out = M.with_sources(DESC, STORY["sources"])
    assert "Source/fact-check" not in out
    assert "Sources:\n- https://en.wikipedia.org/wiki/Acoustic_levitation" in out
    assert out.rstrip().endswith("#shorts #physics #sound")
    assert "Source/fact-check" not in M.with_sources(DESC, [])


def test_build_metadata_retries_a_label_title_then_uses_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "CACHE_DIR", tmp_path)
    answers = [{"title": "Sound Waves That Levitate Objects (It's Real)",
                "description": DESC, "tags": TAGS},
               {"title": "What Can Invisible Sound Hold Up?",
                "description": DESC, "tags": TAGS}]
    calls = []

    def ask(p, t, m):
        calls.append(p)
        return json.dumps(answers[len(calls) - 1])
    meta = M.build_metadata(STORY, ask=ask)
    assert len(calls) == 2 and "parenthetical" in calls[1]
    assert meta["source"] == "llm" and meta["title"] == "What Can Invisible Sound Hold Up?"
    assert "acoustic_levitation" in meta["description"].lower()
    assert "Source/fact-check" not in meta["description"]


def test_autostory_threads_source_urls():
    from engine.v16_autostory import script_to_story
    eng = {"script": {"sentences": [{"text": "x y z.", "role": "hook", "fact_ids": ["f"]}]},
           "metadata": {"title": "A Title Here Now"}}
    facts = {"claims": [{"id": "f", "claim": "c", "source_url": "https://e.org/a"}]}
    assert script_to_story({"title": "t"}, eng, facts)["sources"] == ["https://e.org/a"]
