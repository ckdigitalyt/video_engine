"""Owner review 2026-10-14 ("feels AI generated", item 3 — other formulaic
patterns): framing. 151/191 planned plate shots across the 11 batch
renders of 2026-10-13/14 were "subject_low" (calm dark top third, subject
at the bottom) — 99 of them with no headline/number to use that room."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import v15_plan  # noqa: E402
from engine.v15_style import image_prompt, load_style  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STORY = json.loads((ROOT / "stories/ice_slippery/story.json").read_text())
BIBLE = load_style(ROOT / "stories/ice_slippery", STORY)


def _plan(n=12, comp="subject_low", copy_at=(0,)):
    beats = []
    for i in range(n):
        sh = {"kind": "plate", "start_word": 0, "subject": "a skate blade on ice",
              "view": "medium", "composition": comp, "camera": "push_in"}
        if i in copy_at:
            sh["headline"] = "WHY IS ICE SLIPPERY"
        beats.append({"beat_id": f"B{i + 1}", "shots": [sh]})
    return {"beats": beats}


def _comps(plan):
    return [s["composition"] for b in plan["beats"] for s in b["shots"]]


def test_copy_free_shots_stop_reusing_the_headline_room_layout():
    p = _plan()
    r = v15_plan.vary_compositions(p, "t_ice")
    comps = _comps(p)
    assert comps[0] == "subject_low"                 # hook headline keeps room
    assert "subject_low" not in comps[1:], comps
    assert all(a != b for a, b in zip(comps, comps[1:])), comps
    assert len(set(comps)) >= 4, comps
    assert r["changed"] == len(comps) - 1


def test_copy_shots_keep_a_copy_safe_composition():
    p = _plan(copy_at=(0, 3, 4))
    p["beats"][3]["shots"][0]["composition"] = "subject_left"
    v15_plan.vary_compositions(p, "t_ice")
    comps = _comps(p)
    for i in (0, 3, 4):
        assert comps[i] in v15_plan.COPY_COMPOSITIONS, comps


def test_planner_choices_that_already_vary_are_kept():
    p = _plan(comp="centered", copy_at=())
    for i, c in enumerate(("centered", "subject_left", "subject_high",
                           "subject_right")):
        p["beats"][i]["shots"][0]["composition"] = c
    before = _comps(p)[:4]
    v15_plan.vary_compositions(p, "t_ice")
    assert _comps(p)[:4] == before


def test_vary_compositions_is_deterministic_and_valid():
    a, b = _plan(), _plan()
    v15_plan.vary_compositions(a, "t_x")
    v15_plan.vary_compositions(b, "t_x")
    assert a == b
    story = {"story_id": "t", "title": "T", "beats": [
        {"beat_id": f"B{i + 1}", "function": "HOOK" if i == 0 else "NORMAL",
         "narration": "Ice is slippery because a thin film of water forms on it."}
        for i in range(12)]}
    assert [e for e in v15_plan.validate_plan(a, story)
            if "composition" in e] == []


def test_new_framings_reach_the_image_prompt_and_stay_clean():
    for comp, side in (("subject_left", "left third"),
                       ("subject_right", "right third")):
        p = image_prompt(BIBLE, "a skate blade on ice", comp, view="medium")
        assert side in p
        for bad in ("diagram", "text", "label", "open background"):
            assert bad not in p.lower(), (bad, p)


def test_planner_prompt_reserves_subject_low_for_copy():
    p = v15_plan.build_prompt(STORY, BIBLE)
    assert "ONLY for a shot with a headline or" in p
    assert "subject_left" in p and "subject_right" in p
