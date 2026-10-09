"""Decision #13 item 3: subject-consistency bible."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.subject_bible import (build_subject_bible, inject_subject,  # noqa: E402
                                  main_concept)


def _story(concepts):
    return {"story_id": "t_demo", "title": "Demo", "subject": "demo",
           "beats": [{"beat_id": "B1", "narration": "a skater spins"},
                     {"beat_id": "B2", "narration": "arms pull in"}],
           "concepts": concepts}


def test_main_concept_picks_busiest():
    story = _story([{"id": "arms", "beats": ["B2"]},
                    {"id": "skater", "beats": ["B1", "B2"]}])
    assert main_concept(story)["id"] == "skater"


def test_main_concept_none_without_concepts():
    assert main_concept(_story([])) is None


def test_build_subject_bible_empty_without_concepts_and_no_llm(monkeypatch, tmp_path):
    # decision #18 item 2: with an LLM, a no-concepts story now derives an
    # identity (tests below); with no LLM and no cache there is nothing.
    from engine import subject_bible as sb
    monkeypatch.setattr(sb, "CACHE_DIR", tmp_path)
    assert build_subject_bible(_story([]), use_llm=False) == {}


_IDENTITY = {"name": "the icy dwarf planet",
             "aliases": ["tiny world", "small icy world", "dwarf planet"],
             "description": "a small grey-white cratered ball of nitrogen ice "
                            "with pale rust-tinted patches",
             "not_like": "Earth with blue oceans and green continents"}


def test_identity_path_for_story_without_concepts(monkeypatch, tmp_path):
    from engine import subject_bible as sb
    monkeypatch.setattr(sb, "CACHE_DIR", tmp_path)
    calls = []

    def fake_ask(prompt):
        calls.append(prompt)
        return "here: " + json.dumps(_IDENTITY)

    r = build_subject_bible(_story([]), use_llm=True, ask=fake_ask)
    assert r["source"] == "llm" and r["name"] == "the icy dwarf planet"
    assert "icy dwarf planet" in r["aliases"]       # core name added
    assert r["not_like"].startswith("Earth")
    assert "a skater spins" in calls[0]             # narration in the prompt
    r2 = build_subject_bible(_story([]), use_llm=True, ask=fake_ask)
    assert r2["source"] == "cache" and len(calls) == 1


def test_identity_path_no_recurring_subject(monkeypatch, tmp_path):
    from engine import subject_bible as sb
    monkeypatch.setattr(sb, "CACHE_DIR", tmp_path)
    r = build_subject_bible(_story([]), use_llm=True,
                            ask=lambda p: '{"name": null}')
    assert not r.get("description")
    assert inject_subject("a tiny world", r) == "a tiny world"


def test_inject_subject_by_alias_whole_word_once():
    bible = dict(_IDENTITY, concept_id="icy_dwarf_planet")
    out = inject_subject("A small icy world hangs in starlit space", bible)
    assert out.endswith(_IDENTITY["description"])
    assert inject_subject(out, bible) == out          # never twice
    # whole words only: "worldly" is not "world"
    assert inject_subject("a worldly tinyness", {"aliases": ["world"],
                          "description": "X"}) == "a worldly tinyness"


def test_build_subject_bible_uses_llm_and_caches(monkeypatch, tmp_path):
    from engine import subject_bible as sb
    monkeypatch.setattr(sb, "CACHE_DIR", tmp_path)
    story = _story([{"id": "skater", "beats": ["B1", "B2"]}])
    calls = []

    def fake_ask(prompt):
        calls.append(prompt)
        return json.dumps({"description": "a young woman in a red leotard"})

    r1 = build_subject_bible(story, use_llm=True, ask=fake_ask)
    assert r1["source"] == "llm" and r1["concept_id"] == "skater"
    assert "red leotard" in r1["description"]
    assert len(calls) == 1
    r2 = build_subject_bible(story, use_llm=True, ask=fake_ask)
    assert r2["source"] == "cache" and len(calls) == 1  # no second call


def test_build_subject_bible_fallback_when_llm_unavailable():
    story = _story([{"id": "skater", "beats": ["B1", "B2"]}])
    r = build_subject_bible(story, use_llm=True, ask=lambda p: None)
    assert r["source"] == "fallback" and r["concept_id"] == "skater"


def test_inject_subject_matches_concept_id():
    bible = {"concept_id": "skater", "description": "red leotard, braided hair"}
    out = inject_subject("a figure skater spinning on ice", bible)
    assert "red leotard" in out


def test_inject_subject_no_match_passthrough():
    bible = {"concept_id": "skater", "description": "red leotard, braided hair"}
    out = inject_subject("a clock on a wall", bible)
    assert out == "a clock on a wall"


def test_inject_subject_empty_bible_passthrough():
    assert inject_subject("anything", {}) == "anything"
