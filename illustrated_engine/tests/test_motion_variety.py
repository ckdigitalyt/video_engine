"""Owner review 2026-10-14 ("feels AI generated", item 2): camera motion
variety — engine.v15_motion.

Evidence the fix targets (11 batch renders, 2026-10-13/14): 68% of shots
(167/246) rendered as push_in with runs of 4-6 in a row; every push_in was
the identical 1.0 -> 1.15 ease_in_out track."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import v15_motion as M  # noqa: E402
from engine import v15_shots as S  # noqa: E402
from engine.scene_ir import CAMERA_TYPES, EASINGS, validate_scene_spec  # noqa: E402
from engine.v15_style import load_style  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _items(n=24, camera="push_in"):
    """A worst case: the planner asks for push_in on EVERY shot."""
    return [{"kind": "plate", "camera": camera, "dur": 1.6 + (i % 5) * 0.5,
             "hook": i == 0, "derived": i % 3 == 2, "copy": i in (0, 7, 23),
             "function": "HOOK" if i == 0 else "NORMAL"} for i in range(n)]


def test_no_back_to_back_repeat_even_when_planner_repeats():
    for seed in ("t_a", "t_b", "t_c", "t_frog"):
        mv = [m["move"] for m in M.plan_motion(_items(), seed)]
        assert all(a != b for a, b in zip(mv, mv[1:])), mv
        fam = [M.FAMILY[m] for m in mv]
        runs = M.describe([{"move": m} for m in mv])
        assert runs["max_move_run"] == 1
        assert runs["max_family_run"] <= 2, fam


def test_mix_of_zoom_pan_and_vertical_not_mostly_push_in():
    mv = [m["move"] for m in M.plan_motion(_items(), "t_frog")]
    fam = Counter(M.FAMILY[m] for m in mv)
    assert {"zoom_in", "zoom_out", "lateral"} <= set(fam), fam
    assert len(fam) >= 4, fam
    assert max(fam.values()) / len(mv) <= 0.4, fam
    assert Counter(mv)["push_in"] / len(mv) < 0.35


def test_planner_intent_is_honoured_when_it_is_not_repetitive():
    cams = ("push_in", "pan_left", "rise", "pull_out", "pan_right", "descend")
    items = [{"kind": "plate", "camera": cams[i % 6], "dur": 2.4,
              "function": "NORMAL"} for i in range(30)]
    mv = M.plan_motion(items, "t_intent")
    hits = sum(1 for it, m in zip(items, mv)
               if m["move"] in M.INTENT[it["camera"]])
    assert hits / len(items) >= 0.5, hits


def test_deterministic_per_story_and_different_across_stories():
    a = M.plan_motion(_items(), "t_story_one")
    assert a == M.plan_motion(_items(), "t_story_one")
    b = M.plan_motion(_items(), "t_story_two")
    assert [m["move"] for m in a] != [m["move"] for m in b]


def test_hook_moves_with_energy_and_zoom_through_keeps_its_dive():
    items = _items(6)
    items.insert(3, {"kind": "zoom_through", "dur": 4.0})
    for seed in ("t_a", "t_b", "t_c", "t_d", "t_e"):
        mv = M.plan_motion(items, seed)
        assert mv[0]["move"] in M.HOOK_MOVES
        assert mv[0]["easing"] == "ease_out_cubic"   # moving on frame 0
        assert mv[3] is None


def test_hold_only_on_short_shots_and_not_clustered():
    items = [{"kind": "plate", "camera": "push_in", "dur": 2.0 if i % 2 else 3.6,
              "function": "NORMAL"} for i in range(40)]
    mv = M.plan_motion(items, "t_hold")
    holds = [i for i, m in enumerate(mv) if m["move"] == "hold"]
    assert all(items[i]["dur"] <= M.HOLD_MAX_DUR_S for i in holds)
    assert all(b - a >= M.HOLD_GAP for a, b in zip(holds, holds[1:]))


def test_easing_varies_so_the_camera_does_not_stop_before_every_cut():
    eas = Counter(m["easing"] for m in M.plan_motion(_items(40), "t_ease"))
    assert eas["linear"] + eas["ease_out_cubic"] > eas["ease_in_out_cubic"]
    assert len(eas) >= 2


def test_every_track_is_valid_and_never_exposes_the_plate_edge():
    for move in M.MOVES:
        for dur in (1.2, 2.5, 4.0):
            for amount in (0.8, 1.4):
                for c in ([0, 0], [1080, 1920], [540, 960], [80, 200]):
                    cam = M.camera_for_motion(
                        {"move": move, "easing": "linear", "amount": amount,
                         "sx": -1, "sy": 1}, dur, {"centroid": c})
                    assert cam["type"] in CAMERA_TYPES
                    assert cam["purpose"].strip()
                    for k in cam["keyframes"]:
                        assert k.get("easing", "linear") in EASINGS
                        v = k["value"]
                        lx, ly = M._limits(v["scale"])
                        assert abs(v["x"]) <= lx + 1e-6, (move, v)
                        assert abs(v["y"]) <= ly + 1e-6, (move, v)
                        assert 1.0 <= v["scale"] <= 1.35
                    assert cam["keyframes"][-1]["t"] == round(dur, 3)


def test_moves_read_on_screen():
    """The plate sits at pf=0.545: a zoom must change the on-screen scale
    by >= 7% and a pan must travel >= 9% of the frame width."""
    pf = M._pf(M.BG_DEPTH)
    z = M.camera_for_motion({"move": "push_in", "amount": 1.0}, 2.0, None)
    s0, s1 = (k["value"]["scale"] for k in z["keyframes"])
    assert (1 + (s1 - 1) * pf) / (1 + (s0 - 1) * pf) >= 1.07
    p = M.camera_for_motion({"move": "pan_right", "amount": 1.0}, 2.0, None)
    x0, x1 = (k["value"]["x"] for k in p["keyframes"])
    assert abs(x1 - x0) * pf / 1080 >= 0.09


def test_constants_match_the_shot_compiler():
    assert M.OVERSCAN == S.OVERSCAN
    assert (M.BG_DEPTH, M.SUBJ_DEPTH) == (S.BG_DEPTH, S.SUBJ_DEPTH)


def test_compile_shot_uses_the_planned_motion_and_falls_back_without_it():
    story = json.loads((ROOT / "stories/ice_slippery/story.json").read_text())
    bible = load_style(ROOT / "stories/ice_slippery", story)
    sc = {"scene_id": "sc_m", "duration": 2.4, "plates": [],
          "t_of": lambda w: 0.4, "first": False,
          "shot": {"kind": "plate", "subject": "ice", "camera": "push_in"}}
    legacy = S.compile_shot(dict(sc), bible)["spec"]
    assert legacy["camera"]["type"] == "push_in"
    planned = S.compile_shot(dict(sc, motion={"move": "rise",
                                              "easing": "linear",
                                              "amount": 1.0}), bible)["spec"]
    assert planned["camera"]["type"] == "travel"
    assert validate_scene_spec(planned)[0]
    proc = dict(sc, shot={"kind": "process", "subject": "ice melting",
                          "steps": [{"text": "PRESSURE", "word": 1},
                                    {"text": "MELT", "word": 3}]},
                motion={"move": "pan_left", "easing": "ease_out_cubic",
                        "amount": 1.0})
    assert S.compile_shot(proc, bible)["spec"]["camera"]["type"] == "pan"
