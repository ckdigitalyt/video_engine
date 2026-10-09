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
