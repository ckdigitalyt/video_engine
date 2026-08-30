"""Wave-3 tests: story layer offline determinism (§24 — no network).

Run: ./venv/bin/python -m pytest tests/test_v3_story_offline.py -q
"""

from __future__ import annotations

import pytest

from engine.v3.story import research as research_mod
from engine.v3.story import script as script_mod
from engine.v3.story import structure as structure_mod
from engine.v3.story.llm import LLMError, extract_json


def test_offline_research_shape(tmp_path):
    doc = research_mod.build_research("a test topic", tmp_path / "r.json",
                                      use_llm=False)
    assert doc["topic"] == "a test topic"
    assert len(doc["claims"]) >= 3
    assert doc["provenance"] == "offline_template"
    # Cached second call returns the same doc.
    again = research_mod.build_research("a test topic", tmp_path / "r.json",
                                        use_llm=True)
    assert again["provenance"] == "offline_template"


def test_offline_structure_enforces_section15():
    research = {"topic": "t", "claims": [
        {"text": f"claim {i}", "confidence": "medium", "source_ref": ""}
        for i in range(6)], "angles": ["angle one"], "sources": []}
    story = structure_mod.structure_story(research, use_llm=False)
    roles = [b["role"] for b in story["beats"]]
    assert roles[0] == "hook"
    assert "reveal" in roles and "payoff" in roles
    assert 3 <= roles.count("escalation") <= 5
    # No generic intro in the hook goal.
    assert "in this video" not in roles[0] + story["beats"][0]["goal"].lower()


def test_offline_script_targets_durations():
    research = {"topic": "t", "claims": [
        {"text": f"claim {i}", "confidence": "medium", "source_ref": ""}
        for i in range(6)], "angles": ["angle one"], "sources": []}
    story = structure_mod.structure_story(research, use_llm=False)
    script = script_mod.write_script(story, research, use_llm=False)
    for beat in script["beats"]:
        assert beat["narration"].strip()
        assert beat["target_sec"] >= 1.5
    assert script["est_total_sec"] >= len(script["beats"])


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": [1,2]} hope it helps') == \
        {"a": [1, 2]}
    assert extract_json('{"nested": {"b": "}"}}') == {"nested": {"b": "}"}}
    with pytest.raises(LLMError):
        extract_json("no json here at all")


def test_max_shots_folding():
    research = {"topic": "t", "claims": [
        {"text": f"claim {i}", "confidence": "medium", "source_ref": ""}
        for i in range(6)], "angles": ["angle one"], "sources": []}
    story = structure_mod.structure_story(research, use_llm=False)
    script = script_mod.write_script(story, research, use_llm=False,
                                     max_shots=3)
    assert len(script["beats"]) <= 3
