"""Decision #18 item 3: per-shot view variety (planner, prompts, punch-in)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import v15_plan  # noqa: E402
from engine.v15_style import image_prompt, load_style  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STORY = json.loads((ROOT / "stories/ice_slippery/story.json").read_text())
BIBLE = load_style(ROOT / "stories/ice_slippery", STORY)


def _plan(views):
    """One plate shot per beat with the given views (cycled)."""
    beats = []
    for i, b in enumerate(STORY["beats"]):
        sh = {"kind": "plate", "start_word": 0,
              "subject": "a steel skate blade gliding over clear ice",
              "composition": "centered", "camera": "push_in",
              "view": views[i % len(views)]}
        if i == 0:
            sh["headline"] = "WHY IS ICE SLIPPERY"
        beats.append({"beat_id": b["beat_id"], "shots": [sh]})
    return {"beats": beats}


def test_variety_errors_flags_repeats_and_low_spread():
    errs = v15_plan.variety_errors(_plan(["wide"]))
    assert any("same view" in e for e in errs), errs
    n = len(STORY["beats"])
    if n >= 6:
        assert any("max 40%" in e for e in errs), errs


def test_variety_errors_clean_on_varied_plan():
    assert v15_plan.variety_errors(
        _plan(["wide", "close", "surface", "cutaway", "medium"])) == []


def test_variety_errors_requires_a_view():
    p = _plan(["wide", "close", "surface", "cutaway"])
    p["beats"][1]["shots"][0].pop("view")
    assert any("needs a view" in e for e in v15_plan.variety_errors(p))


def test_unknown_view_is_repaired_away_and_rejected_when_kept():
    p = _plan(["wide", "close"])
    p["beats"][0]["shots"][0]["view"] = "Bird's Eye"
    v15_plan._repair(p, STORY)
    assert "view" not in p["beats"][0]["shots"][0]
    p["beats"][0]["shots"][0]["view"] = "birdseye"
    assert any("view must be one of" in e
               for e in v15_plan.validate_plan(p, STORY))


def test_make_plan_retries_for_variety_then_accepts_with_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(v15_plan, "CACHE_DIR", tmp_path)
    same = json.dumps(_plan(["wide"]))
    prompts = []

    def ask(p, temp, mx):
        prompts.append(p)
        return same

    r = v15_plan.make_plan(STORY, BIBLE, ask=ask, force=True)
    assert len(prompts) == 2 and "same view" in prompts[1]
    assert r["source"] == "llm_retry" and r["variety_warnings"]


def test_make_plan_varied_first_try(monkeypatch, tmp_path):
    monkeypatch.setattr(v15_plan, "CACHE_DIR", tmp_path)
    good = json.dumps(_plan(["wide", "close", "surface", "cutaway", "medium"]))
    r = v15_plan.make_plan(STORY, BIBLE, ask=lambda p, t, m: good, force=True)
    assert r["source"] == "llm" and r["variety_warnings"] == []


def test_identity_block_in_prompt_and_cache_key():
    subj = {"name": "the icy dwarf planet", "description": "grey cratered ice"}
    p = v15_plan.build_prompt(STORY, BIBLE, subj)
    assert "RECURRING SUBJECT: the icy dwarf planet" in p
    assert v15_plan.plan_key(STORY, BIBLE, subj) != v15_plan.plan_key(STORY, BIBLE)


def test_view_is_prepended_and_prompt_stays_clean():
    p = image_prompt(BIBLE, "a skate blade on ice", "subject_low", view="close")
    assert "Extreme close-up of surface detail" in p
    assert p.index("Extreme close-up") < p.index("skate blade")
    for bad in ("diagram", "text", "label", "open background"):
        assert bad not in p.lower(), (bad, p)


def test_hook_reframes_generic_views_to_scroll_stopping_framing():
    """live_20261011_055858 (ice age): the hook plate was "Wide establishing
    view: Earth ... floating alone in space" -> judge hook_stops_scroll=false."""
    from engine.v15_style import (FRAMING_GUIDANCE, HOOK_FRAMING,
                                  HOOK_FRAMING_GUIDANCE, VIEW_PHRASES)
    subj = "Earth as a half-frozen globe floating alone in space"
    for view in (None, "wide", "medium"):
        p = image_prompt(BIBLE, subj, "subject_low", view=view, hook=True)
        assert HOOK_FRAMING in p and p.index(HOOK_FRAMING) < p.index("Earth"), p
        assert VIEW_PHRASES["wide"] not in p and "establishing" not in p, p
        assert HOOK_FRAMING_GUIDANCE in p and FRAMING_GUIDANCE not in p
        assert "main subject large" in p          # headline room kept
    # non-hook shots are unchanged
    assert image_prompt(BIBLE, subj, "subject_low", view="wide") == \
        image_prompt(BIBLE, subj, "subject_low", view="wide", hook=False)
    assert HOOK_FRAMING not in image_prompt(BIBLE, subj, view="wide")
    # a specific hook view (e.g. a comparison: the contradiction IS the hook)
    # keeps its own framing
    p = image_prompt(BIBLE, "two beavers side by side", view="comparison", hook=True)
    assert VIEW_PHRASES["comparison"] in p and HOOK_FRAMING not in p


def test_hook_framing_survives_plate_regen_steering():
    from engine.v15_pipeline import _prompt_parts, _prompts_for, steer_prompt
    from engine.v15_style import HOOK_FRAMING
    shot = {"kind": "plate", "subject": "a small icy world in space",
            "view": "wide", "composition": "subject_low", "camera": "push_in"}
    assert HOOK_FRAMING in _prompts_for(shot, BIBLE, None, hook=True)[0]
    assert HOOK_FRAMING not in _prompts_for(shot, BIBLE, None)[0]
    parts = _prompt_parts(shot, None, hook=True)[0]
    for reason in ("empty", "wrong_subject", "text", None):
        assert HOOK_FRAMING in steer_prompt(BIBLE, parts, reason, 1), reason
    assert HOOK_FRAMING not in steer_prompt(
        BIBLE, _prompt_parts(shot, None)[0], "empty", 1)


def test_planner_prompt_hook_rule_and_example():
    p = v15_plan.build_prompt(STORY, BIBLE)
    assert "never the recurring subject shown whole" in p
    assert '"start_word":0,"subject":"...","view":"wide"' not in p


def test_derived_punch_in_takes_a_different_view():
    from engine.v15_pipeline import _split_one
    words = [0.3 * i for i in range(30)]
    bt = [0.18 + t - 0.12 for t in words]
    s = {"shot": {"kind": "plate", "subject": "a small icy world in space",
                  "view": "wide", "composition": "subject_low",
                  "camera": "pull_out", "start_word": 0},
         "t0": 0.0, "t1": 9.0}
    first, second = _split_one(s, words, bt, 3.0, 1.0)
    assert second["shot"]["view"] == "close"
    assert second["shot"]["subject"] == "a small icy world in space"
    s["shot"]["view"] = "close"
    assert _split_one(s, words, bt, 3.0, 1.0)[1]["shot"]["view"] == "wide"


# ------------------------------- decision #18 item 6: planner robustness --

def test_spelled_out_numbers_count_as_spoken():
    d = v15_plan._spoken_digits("It's only about four hundred thirty to five "
                                "hundred ten kilometres across, over 20 m.")
    assert {"430", "510", "20"} <= d


def test_number_overlay_of_spelled_figure_validates():
    story = {"story_id": "t", "title": "T", "beats": [
        {"beat_id": "B1", "function": "HOOK",
         "narration": "It vanishes within one hundred to one thousand years."}]}
    plan = {"beats": [{"beat_id": "B1", "shots": [
        {"kind": "plate", "start_word": 0, "view": "wide",
         "subject": "a small icy world losing its haze", "camera": "push_in",
         "composition": "centered", "headline": "GONE SOON",
         "number": {"text": "100-1,000 YEARS", "word": 3}}]}]}
    assert v15_plan.validate_plan(plan, story) == []
    plan["beats"][0]["shots"][0]["number"]["text"] = "5,000 YEARS"
    assert any("not spoken" in e for e in v15_plan.validate_plan(plan, story))


def test_repair_fills_first_shot_start_word():
    p = _plan(["wide", "close"])
    p["beats"][2]["shots"][0].pop("start_word")
    v15_plan._repair(p, STORY)
    assert p["beats"][2]["shots"][0]["start_word"] == 0


# ------------------------ decision #18 item 7: zoom_through on short beats --

def test_zoom_through_on_a_short_beat_compiles_valid_scene_ir():
    """Dry run 6 crashed: 3 dive levels on a ~2 s beat -> decreasing
    keyframe times -> invalid Scene IR. Middle levels are now dropped."""
    from engine.scene_ir import validate_scene_spec
    from engine.v15_shots import _fit_zoom_levels, compile_shot
    levels = [{"subject": "a beaver on a riverbank", "label": "THE BEAVER", "word": 0},
              {"subject": "a glowing cell", "label": "CELL", "word": 2},
              {"subject": "chromosome strands", "label": "CHROMOSOMES", "word": 3}]
    for dur in (1.6, 2.1, 3.3, 6.0):
        sc = {"scene_id": f"z{dur}", "duration": dur,
              "shot": {"kind": "zoom_through", "levels": levels,
                       "start_word": 0, "camera": "push_in"},
              "plates": [None, None, None],
              "t_of": lambda w, _d=dur: min(0.15 + 0.4 * w, _d - 0.35),
              "first": False}
        res = compile_shot(sc, BIBLE)
        ok, errs = validate_scene_spec(res["spec"])
        assert ok, (dur, errs[:3])
    kept, pl = _fit_zoom_levels(levels, ["p0", "p1", "p2"], 2.1)
    assert [k["label"] for k in kept] == ["THE BEAVER", "CHROMOSOMES"]
    assert pl == ["p0", "p2"]
    assert _fit_zoom_levels(levels, [1, 2, 3], 6.0)[0] == levels
