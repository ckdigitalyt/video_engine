"""Regressions for the 2026-10-11 fail-rate pass (5/5 fresh renders FAILed):
narration-as-image-subject via the fallback plan, fantasy-register house
style, clipped final consonants, and ASR-only voice-QA mismatches."""
import numpy as np

from engine import v15_plan as P
from engine.v15_style import HOUSE_DECK, FRAMING_GUIDANCE, image_prompt
from engine.voice import _trim
from engine.voice.text import norm_tokens, restore_d_elision, flat_tokens

AUTO_STORY = {  # v16_autostory shape: claim == narration, no visual fields
    "story_id": "t_rains_rock", "title": "The Planet That Rains Rock",
    "beats": [
        {"beat_id": "B1", "function": "HOOK",
         "narration": "On some planets, the ground boils into the sky.",
         "claim": "On some planets, the ground boils into the sky."},
        {"beat_id": "B2", "function": "NORMAL",
         "narration": "Not meters per second. Kilometers per second.",
         "claim": "Not meters per second. Kilometers per second."}]}
IDENT = {"name": "the lava planet",
         "description": "Scorched rocky sphere, one glowing molten hemisphere"}


def _subjects(plan):
    return [s["subject"] for b in plan["beats"] for s in b["shots"]]


def test_fallback_never_uses_narration_as_subject_when_identity_known():
    plan = P.fallback_plan(AUTO_STORY, IDENT)
    assert P.validate_plan(plan, AUTO_STORY) == []
    for s in _subjects(plan):
        assert "meters per second" not in s.lower()
        assert "lava planet" in s


def test_fallback_without_identity_still_valid():
    assert P.validate_plan(P.fallback_plan(AUTO_STORY), AUTO_STORY) == []


def test_view_name_as_kind_is_repaired_to_plate():
    plan = {"beats": [{"beat_id": "B1", "shots": [{
        "kind": "comparison", "start_word": 0, "headline": "ROCK RAIN",
        "subject": "glowing molten rock droplets falling onto dark stone",
        "view": "comparison", "composition": "centered"}]},
        {"beat_id": "B2", "shots": [{
            "kind": "plate", "start_word": 0, "camera": "push_in",
            "subject": "glowing vapor winds streaking across a lava plain",
            "view": "close"}]}]}
    out = P._repair(plan, AUTO_STORY)
    assert out["beats"][0]["shots"][0]["kind"] == "plate"
    assert P.validate_plan(out, AUTO_STORY) == []


def test_salvage_drops_figureless_number_instead_of_falling_back():
    plan = {"beats": [{"beat_id": "B1", "shots": [{
        "kind": "plate", "start_word": 0, "camera": "push_in",
        "headline": "ROCK RAIN", "view": "medium",
        "subject": "molten crust boiling up into streaming vapor"}]},
        {"beat_id": "B2", "shots": [{
            "kind": "plate", "start_word": 0, "camera": "push_in",
            "view": "close", "number": {"text": "KM/S", "word": 4},
            "subject": "glowing vapor winds streaking across a lava plain"}]}]}
    assert P.validate_plan(plan, AUTO_STORY)  # invalid as written
    sal, dropped = P.salvage(plan, AUTO_STORY, IDENT)
    assert P.validate_plan(sal, AUTO_STORY) == []
    assert "streaking" in sal["beats"][1]["shots"][0]["subject"]
    assert any("number" in d for d in dropped)


def test_planner_prompt_forbids_narration_subject_and_view_kinds():
    p = P.build_prompt(AUTO_STORY, {"illustration_style": "x"})
    assert "NEVER copy or paraphrase the narration" in p
    assert "Kilometers per second" in p and "VIEWS, never kinds" in p


def test_house_style_has_no_fantasy_key_art_register():
    st = HOUSE_DECK["illustration_style"].lower()
    import re
    for w in ("hero", "epic", "awe-inspiring", "one bold focal"):
        assert not re.search(rf"\b{w}\b", st), w
    for w in ("teal", "orange", "rim light", "deep shadow"):
        assert w in st
    assert "figure" not in FRAMING_GUIDANCE.lower()


def test_two_thing_subject_keeps_both_in_frame():
    b = {"illustration_style": "s", "prompt_fragments": {"prefix": "s"}}
    p = image_prompt(b, "the Moon beside Earth", "subject_low", view="medium")
    assert "every named thing fully visible together" in p
    assert "single clear focal subject" not in p
    p = image_prompt(b, "a lava plain", "centered", view="close")
    assert "single clear focal subject" in p


def test_trim_keeps_final_consonant_release():
    sr = 24000
    loud = np.ones(sr // 2, dtype=np.float32) * 0.5
    burst = np.ones(int(0.1 * sr), dtype=np.float32) * 0.005  # < 2% of peak
    a = np.concatenate([np.zeros(sr // 10), loud, burst,
                        np.zeros(sr // 2)]).astype(np.float32)
    out, _ = _trim(a, sr)
    assert len(out) >= len(loud) + len(burst)


def test_d_elision_before_consonant_only():
    ref, _ = flat_tokens("You'd think so".split())
    assert restore_d_elision(ref, ["you", "think", "so"]) == ref
    ref, _ = flat_tokens("You'd always know".split())
    assert restore_d_elision(ref, ["you", "always", "know"]) != ref
    ref, _ = flat_tokens("Snakes shed skin".split())
    assert restore_d_elision(ref, ["snakes", "she", "skin"]) != ref


def test_homophones_and_roman_numerals_normalise():
    assert norm_tokens("hours") == norm_tokens("ours")
    assert norm_tokens("II") == norm_tokens("Two")
