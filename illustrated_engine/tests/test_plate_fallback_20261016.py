"""2026-10-16 zero-publish day, plate QA: one plate out of 12-24 that is
still failing after the 3 steered rounds FAILs the whole video (8 of 21
batch renders since 2026-10-13). live_20261016_032600 storm B5_S1 was
planned as "a hypothetical deep towering column of swirling storm" over
narration saying it ISN'T a deep tower, and every steered round kept that
subject. Two last-resort steps (engine.v15_pipeline): a narration-led
RESUBJECT round, then drop_unfixable_shots. Both keep the bar: a failed
image never ships, and the gate still judges the result.

Run: python3 -m pytest -q tests/test_plate_fallback_20261016.py   (no network)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v15_gate as g  # noqa: E402
from engine import v15_pipeline as P  # noqa: E402

BIBLE = {"deck": "ink_ember", "illustration_style": "vivid cinematic digital painting"}
STORM_NARR = ("So this monster likely isn't a deep tower at all, but a thin "
              "spinning sheet.")
IDENTITY = {"name": "the Great Red Spot", "aliases": ["storm", "monster"],
            "description": "a massive oval swirling storm with red-orange bands"}


def _shot(bid, idx, t0, t1, prompt, view="medium", **shot):
    return {"beat": {"beat_id": bid}, "idx": idx, "t0": t0, "t1": t1,
            "prompts": [prompt], "hook": False,
            "shot": {"kind": "plate", "view": view, **shot}}


# -------------------------------------------------------------- resubject --

def test_resubject_builds_from_narration_not_the_planner_subject(monkeypatch):
    monkeypatch.setattr(P, "image_prompt",
                        lambda bible, subj, comp, view=None, hook=False: f"{view}|{subj}")
    prompt, subj = P.resubject_prompt(BIBLE, STORM_NARR, IDENTITY,
                                      avoid_views={"medium", "surface"})
    assert "thin spinning sheet" in subj
    assert "hypothetical" not in prompt and "towering column" not in prompt
    assert prompt.startswith("cutaway|")             # a view no sibling uses
    _, subj2 = P.resubject_prompt(BIBLE, "It held for three hundred years.", None)
    assert "three hundred" not in subj2              # numbers stripped, like steering
    p3, _ = P.resubject_prompt(BIBLE, STORM_NARR, None, avoid_views={"cutaway", "wide"})
    assert p3.startswith("medium|")
    # variants rotate through the views the beat doesn't use yet
    views = [P.resubject_prompt(BIBLE, STORM_NARR, None, avoid_views={"medium", "surface"},
                                variant=k)[0].split("|")[0]
             for k in range(P.RESUBJECT_VARIANTS)]
    assert views == ["cutaway", "wide"] and P.RESUBJECT_VARIANTS == 2


def test_resubject_reasons_are_content_reasons_only():
    assert set(P.RESUBJECT_REASONS) == {"narration_mismatch", "wrong_subject",
                                        "generic_subject", "empty"}
    # text / bad_anatomy / near_duplicate keep their own steering only
    assert "text" not in P.RESUBJECT_REASONS


# ---------------------------------------------------------------- drop --

def test_failing_shot_dropped_when_sibling_covers_beat_within_ceiling():
    # t_the_light_bearer_that_poisons B5 shape: S1 1.70 s failing, S2 1.52 s ok
    shots = [_shot("B4", 0, 0.0, 2.0, "p_b4"),
             _shot("B5", 0, 2.0, 3.7, "p_fail"), _shot("B5", 1, 3.7, 5.22, "p_ok"),
             _shot("B6", 0, 5.22, 7.0, "p_b6")]
    out, log = P.drop_unfixable_shots(shots, {"p_fail"}, {"B5": 3.6})
    assert [(s["beat"]["beat_id"], s["idx"], s["prompts"][0]) for s in out] == [
        ("B4", 0, "p_b4"), ("B5", 0, "p_ok"), ("B6", 0, "p_b6")]
    b5 = out[1]
    assert (b5["t0"], b5["t1"]) == (2.0, 5.22)        # timeline stays contiguous
    assert log == [{"dropped": "B5_S1", "covered_by": "B5_S2",
                    "merged_s": 3.22, "cap_s": 3.6}]


def test_storm_b5_is_not_dropped_past_its_hold_ceiling():
    # live_20261016_032600: S1 2.95 s + S2 1.67 s = 4.62 s > beat ceiling 3.99 s
    shots = [_shot("B5", 0, 10.0, 12.95, "p_fail"), _shot("B5", 1, 12.95, 14.62, "p_ok")]
    out, log = P.drop_unfixable_shots(shots, {"p_fail"}, {"B5": 3.99})
    assert out == shots and log == []                 # -> gate still FAILs it
    assert 4.62 > g.MAX_HOLD_S                        # and would be a frozen frame anyway


def test_never_drops_hook_copy_or_cross_beat():
    base = [_shot("B2", 0, 0.0, 1.5, "p_fail"), _shot("B2", 1, 1.5, 3.0, "p_ok")]
    hook = [dict(base[0], hook=True), base[1]]
    assert P.drop_unfixable_shots(hook, {"p_fail"}, {"B2": 4.0})[1] == []
    for field, val in (("headline", "NO ROCKETS?"), ("number", {"text": "3", "word": 0}),
                       ("label", {"text": "X", "word": 0})):
        sh = [dict(base[0], shot=dict(base[0]["shot"], **{field: val})), base[1]]
        assert P.drop_unfixable_shots(sh, {"p_fail"}, {"B2": 4.0})[1] == [], field
    # the only neighbour is another beat -> nothing may cover it
    other = [_shot("B1", 0, 0.0, 1.0, "p_ok"), _shot("B2", 0, 1.0, 2.0, "p_fail")]
    assert P.drop_unfixable_shots(other, {"p_fail"}, {"B2": 4.0})[1] == []
    # a sibling that also fails can't cover it either
    both = [_shot("B2", 0, 0.0, 1.0, "p_fail"), _shot("B2", 1, 1.0, 2.0, "p_fail2")]
    assert P.drop_unfixable_shots(both, {"p_fail", "p_fail2"}, {"B2": 4.0})[1] == []


def test_dropping_clears_the_plate_gate_only_because_no_failed_plate_ships():
    # the gate keys on still_failing / qa_fail: once the failing prompt is no
    # longer used by any shot, nothing failing is left to report ...
    assert g.check_plates({}, {"checked": True, "regenerated": 3, "second_check": True,
                               "still_failing": []})["ok"]
    # ... while a kept failing plate is still a critical FAIL
    r = g.check_plates({}, {"checked": True, "regenerated": 3, "second_check": True,
                            "still_failing": ["p_fail"]})
    assert not r["ok"] and r["critical"]
