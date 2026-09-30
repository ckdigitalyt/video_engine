"""WP7 — template library + pacing: engine.v16_plan's planner v2 rules
(content-signal mapping, no repeats, >=5 distinct templates, <=35% screen
time, frame0/last) and engine.v15_shots' new template compilers (Scene IR
validity, right-rail safety, the 1.8s pattern-interrupt gate).

Run: python3 -m pytest tests/test_wp7_templates.py   (no network, no render)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import v15_gate as g  # noqa: E402
from engine import v15_shots as S  # noqa: E402
from engine import v16_plan as P  # noqa: E402

BIBLE = {"palette": {"primary": "#22304E", "secondary": "#7A6A52",
                     "accent": "#C25B33", "background": "#171310",
                     "text": "#EFE6D4", "muted": "#8A7B63",
                     "highlight": "#E9DFC8"}, "texture": {}}

NEW_KINDS = ("kinetic_claim", "big_number", "map_pin", "timeline",
            "scale_compare", "parallax", "loop_bridge")


def _typical_story_plan(n_beats: int = 7):
    story = {"story_id": "wp7_typical", "beats": [
        {"beat_id": f"B{i}",
         "narration": " ".join(["word"] * 13) +
         ("  38 microseconds" if i == 2 else "") +
         (" near the Atlantic Ocean" if i == 3 else "") +
         (" three million years ago" if i == 4 else "") +
         (" twice the size of a car" if i == 5 else "")}
        for i in range(1, n_beats + 1)]}
    plan = {"beats": [
        {"beat_id": f"B{i}", "shots": [
            {"kind": "plate", "start_word": 0, "subject": "x"},
            {"kind": "plate", "start_word": 6, "subject": "y",
             **({"number": {"text": "38", "word": 7}} if i == 2 else {})}]}
        for i in range(1, n_beats + 1)]}
    return story, plan


# ------------------------------------------------------ template library --

def test_library_has_the_required_templates():
    required = {"KINETIC_CLAIM", "BIG_NUMBER", "MAP_PIN", "TIMELINE_DEEPTIME",
               "SCALE_COMPARE", "PARALLAX_25D", "LOOP_BRIDGE"}
    assert required <= set(P.TEMPLATE_LIBRARY)


def test_every_template_declares_a_sub_1s_motion_signature():
    for name, spec in P.TEMPLATE_LIBRARY.items():
        assert spec.motion_signature_s <= 1.0, name
        lo, hi = spec.duration_bounds
        assert 0 < lo < hi, name


def test_every_template_maps_to_a_real_shot_compiler():
    for name, spec in P.TEMPLATE_LIBRARY.items():
        assert spec.shot_kind in S.GRAMMAR, (name, spec.shot_kind)


# --------------------------------------------------------------- planner --

def test_content_signals_map_to_the_right_template():
    assert P._content_signal({"number": {"text": "5", "word": 0}}, "x") == "number"
    assert P._content_signal({"kind": "process"}, "x") == "process"
    assert P._content_signal({"kind": "zoom_through"}, "x") == "scale"
    assert P._content_signal({}, "it happened near the Atlantic Ocean") == "place"
    assert P._content_signal({}, "three million years ago") == "time_span"
    assert P._content_signal({}, "twice the size of a bus") == "compare"
    assert P._content_signal({}, "a plain sentence with nothing special") is None


def test_no_two_templates_repeat_back_to_back():
    story, plan = _typical_story_plan()
    P.assign_templates(plan, story)
    seq = [sh["template"] for pb in plan["beats"] for sh in pb["shots"]]
    for i in range(1, len(seq)):
        assert seq[i] != seq[i - 1], (i, seq)


def test_at_least_five_distinct_templates():
    story, plan = _typical_story_plan()
    res = P.assign_templates(plan, story)
    assert len(res["templates_used"]) >= 5, res["templates_used"]


def test_no_template_exceeds_35_percent_of_screen_time():
    story, plan = _typical_story_plan()
    P.assign_templates(plan, story)
    seq = [sh["template"] for pb in plan["beats"] for sh in pb["shots"]]
    total = sum(it["duration"] for it in P._flatten(plan, story))
    by_t = {}
    for it in P._flatten(plan, story):
        by_t[it["template"]] = by_t.get(it["template"], 0.0) + it["duration"]
    for t, s in by_t.items():
        assert s / total <= 0.35 + 1e-6, (t, s / total)


def test_frame_zero_is_hook_plate_or_kinetic_claim():
    story, plan = _typical_story_plan()
    P.assign_templates(plan, story)
    assert plan["beats"][0]["shots"][0]["template"] in ("HOOK_PLATE", "KINETIC_CLAIM")


def test_last_shot_is_loop_bridge():
    story, plan = _typical_story_plan()
    P.assign_templates(plan, story)
    assert plan["beats"][-1]["shots"][-1]["template"] == "LOOP_BRIDGE"


def test_assignment_is_deterministic_not_random():
    story, plan_a = _typical_story_plan()
    _, plan_b = _typical_story_plan()
    P.assign_templates(plan_a, story)
    P.assign_templates(plan_b, story)
    seq_a = [sh["template"] for pb in plan_a["beats"] for sh in pb["shots"]]
    seq_b = [sh["template"] for pb in plan_b["beats"] for sh in pb["shots"]]
    assert seq_a == seq_b


def test_heavy_repeat_input_still_resolves_to_zero_errors():
    story = {"story_id": "stress", "beats": [
        {"beat_id": f"B{i}", "narration": " ".join(["word"] * 13)}
        for i in range(1, 11)]}
    plan = {"beats": [
        {"beat_id": f"B{i}", "shots": [
            {"kind": "plate", "start_word": 0, "subject": "x"},
            {"kind": "plate", "start_word": 6, "subject": "y"}]}
        for i in range(1, 11)]}
    res = P.assign_templates(plan, story)
    assert res["errors"] == [], res["errors"]
    assert len(res["templates_used"]) >= 5


def test_repair_never_assigns_zoom_through_or_process_to_an_incompatible_shot():
    """Regression: repair passes used to be able to hand a plain plate shot
    the ZOOM_THROUGH/PROCESS_OVER_PLATE template (they need levels/steps
    only a shot of that original v15_plan kind has), and _write_back's
    kind-retarget would then crash compile_zoom_shot/compile_process_shot
    with a missing key. Force a heavy-repair scenario (all plate, all
    identical) and confirm every shot's assigned template is structurally
    compatible AND that compile_shot actually renders it."""
    story = {"story_id": "compat", "beats": [
        {"beat_id": f"B{i}", "narration": " ".join(["word"] * 13)}
        for i in range(1, 11)]}
    plan = {"beats": [
        {"beat_id": f"B{i}", "shots": [
            {"kind": "plate", "start_word": 0, "subject": "x"},
            {"kind": "plate", "start_word": 6, "subject": "y"}]}
        for i in range(1, 11)]}
    P.assign_templates(plan, story)
    bible = {"palette": {"primary": "#22304E", "secondary": "#7A6A52",
                         "accent": "#C25B33", "background": "#171310",
                         "text": "#EFE6D4", "muted": "#8A7B63",
                         "highlight": "#E9DFC8"}, "texture": {}}
    for pb in plan["beats"]:
        for sh in pb["shots"]:
            assert P._compatible(sh, sh["template"]), sh
            sc = {"scene_id": "x", "duration": 2.0, "plates": [],
                  "t_of": lambda w: 0.3, "first": False, "shot": sh}
            S.compile_shot(sc, bible)  # must not raise


def test_write_back_retargets_kind_to_the_assigned_templates_shot_kind():
    story, plan = _typical_story_plan()
    P.assign_templates(plan, story)
    for pb in plan["beats"]:
        for sh in pb["shots"]:
            assert sh["kind"] == P.TEMPLATE_LIBRARY[sh["template"]].shot_kind


def test_validate_templates_flags_a_manual_repeat():
    story, plan = _typical_story_plan()
    P.assign_templates(plan, story)
    plan["beats"][0]["shots"][1]["template"] = plan["beats"][0]["shots"][0]["template"]
    errs = P.validate_templates(plan, story)
    assert any("repeats" in e for e in errs), errs


# --------------------------------------------------- new shot compilers --

def _compile(kind: str, shot: dict, plates=None, t_of=None, first=False):
    sc = {"scene_id": f"sc_{kind}", "duration": 2.4, "plates": plates or [],
          "t_of": t_of or (lambda w: 0.4), "first": first,
          "shot": dict(shot, kind=kind)}
    return S.compile_shot(sc, BIBLE)


def test_every_new_template_kind_compiles_to_valid_scene_ir_and_clears_the_rail():
    fixtures = {
        "kinetic_claim": {"headline": "THE CLOCK LIES", "subject": "x"},
        "big_number": {"number": {"text": "38 MICROSECONDS", "word": 2}, "subject": "x"},
        "map_pin": {"headline": "THE CRATER SITE", "subject": "x"},
        "timeline": {"levels": [{"label": "HADEAN"}, {"label": "ARCHEAN"},
                                {"label": "NOW"}], "subject": "x"},
        "scale_compare": {"compare": {"a": {"text": "A SPARROW", "scale": 1.0},
                                      "b": {"text": "A T. REX", "scale": 2.6}},
                          "subject": "x"},
        "parallax": {"headline": "DEEP IN THE ICE", "subject": "x"},
        "loop_bridge": {"headline": "STILL TICKING.", "subject": "x"},
    }
    for kind, shot in fixtures.items():
        out = _compile(kind, shot)
        assert out["spec"]["meta"]["shot_kind"] == kind
        checks = g.check_text_bounds({"s": out["spec"]})
        assert checks["ok"], (kind, checks)


def test_map_pin_clears_the_right_rail_black_hole_case():
    """Reproduces the exact Phase 2 blackhole subject bbox (bench/ab/wp2.md:
    "THE BLACK HOLE" x 605-1010, y 794-878) through the MAP_PIN compiler's
    _label leader-line path (the same rail-safety mechanism WP6 fixed)."""
    plate = {"path": "/tmp/fake.png",
             "info": {"bbox": [605, 794, 1010, 878],
                      "mean_lum": {"top": 90, "bottom": 90, "all": 90}}}
    out = _compile("map_pin", {"label": {"text": "THE BLACK HOLE", "word": 0},
                               "subject": "x"}, plates=[plate],
                   t_of=lambda w: 1.0)
    checks = g.check_text_bounds({"s": out["spec"]})
    assert checks["ok"], checks


def test_timeline_and_scale_compare_clear_the_rail_with_long_labels():
    out = _compile("timeline", {"levels": [
        {"label": "THE HADEAN EON BEGINS HERE"}, {"label": "B"}, {"label": "C"},
        {"label": "D"}, {"label": "A VERY LONG YOU-ARE-HERE MARKER LABEL"}],
        "subject": "x"})
    assert g.check_text_bounds({"s": out["spec"]})["ok"]
    out = _compile("scale_compare", {"compare": {
        "a": {"text": "A HUMMINGBIRD FEATHER STRUCTURE"},
        "b": {"text": "THE ENTIRE TYRANNOSAURUS REX SKELETON", "scale": 3.0}},
        "subject": "x"})
    assert g.check_text_bounds({"s": out["spec"]})["ok"]


def test_loop_bridge_falls_back_cleanly_without_hook_context():
    out = _compile("loop_bridge", {"headline": "STILL TICKING.", "subject": "x"})
    assert out["spec"]["meta"]["shot_kind"] == "loop_bridge"


def test_parallax_camera_differs_deterministically_by_scene_id():
    a = _compile("parallax", {"headline": "X", "subject": "x"})
    sc = {"scene_id": "sc_parallax", "duration": 2.4, "plates": [],
          "t_of": lambda w: 0.4, "first": False,
          "shot": {"kind": "parallax", "headline": "X", "subject": "x"}}
    b = S.compile_shot(sc, BIBLE)
    assert a["spec"]["camera"] == b["spec"]["camera"]  # deterministic, not random


# ------------------------------------------------------------- hold gate --

def test_pattern_interrupt_passes_under_1_8s():
    meta = {"s0": {}, "s1": {}}
    specs = {"s0": {"duration_s": 1.5, "layers": []},
            "s1": {"duration_s": 1.2, "layers": []}}
    r = g.check_pattern_interrupt(meta, specs)
    assert r["ok"], r
    assert r["median_shot_s"] == 1.35


def test_pattern_interrupt_fails_over_1_8s_with_no_internal_reveal():
    meta = {"s0": {}}
    specs = {"s0": {"duration_s": 2.4, "layers": []}}
    r = g.check_pattern_interrupt(meta, specs)
    assert not r["ok"], r
    assert r["max_hold_s"] == 2.4


def test_pattern_interrupt_passes_a_long_shot_with_a_mid_shot_reveal():
    meta = {"s0": {}}
    specs = {"s0": {"duration_s": 3.0, "layers": [
        {"id": "reveal", "type": "text", "visibility": [1.5, 3.0]}]}}
    r = g.check_pattern_interrupt(meta, specs)
    assert r["ok"], r


def test_check_visual_hold_unchanged_after_the_wp7_refactor():
    """engine.v15_gate.check_visual_hold was refactored to share _hold_gaps
    with check_pattern_interrupt — same event model, same 4.5s threshold."""
    meta = {"s0": {}}
    specs = {"s0": {"duration_s": 5.0, "layers": []}}
    r = g.check_visual_hold(meta, specs)
    assert not r["ok"] and r["max_hold_s"] == 5.0, r
