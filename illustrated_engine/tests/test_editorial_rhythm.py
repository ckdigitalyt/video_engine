"""Owner review 2026-10-14 ("feels AI generated", item 1): shot duration
rhythm — per-beat hold ceilings, seeded split points, per-beat tails.

Evidence the fix targets (11 batch renders, 2026-10-13/14): 70% of shots
were 1.5-2.5 s, 39% were midpoint-split punch-in halves (2-shot beats had
a median shorter/longer ratio of 0.885), every sentence gap ~1.0 s."""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import v15_pipeline as P  # noqa: E402


def _beat(bid, fn="NORMAL", words=11, end="."):
    return {"beat_id": bid, "function": fn,
            "narration": " ".join(["word"] * (words - 1) + ["last" + end])}


def _story(n=12):
    beats = [_beat("B1", "HOOK")]
    beats += [_beat(f"B{i}", words=6 + (i * 5) % 9) for i in range(2, n)]
    beats += [_beat(f"B{n}", "PAYOFF")]
    return beats


# --------------------------------------------------------------- holds --

def test_hold_ceiling_follows_beat_role_and_stays_under_gate():
    from engine.v15_gate import MAX_HOLD_S as GATE_HOLD
    beats = _story()
    for seed in ("t_a", "t_b", "t_c", "t_d"):
        holds = [P.beat_max_hold(b, i, len(beats), seed)
                 for i, b in enumerate(beats)]
        assert all(P.HOLD_MIN_S <= h <= P.HOLD_MAX_S < GATE_HOLD for h in holds)
        # the hook cuts faster than the payoff lets its image land
        assert holds[0] < holds[-1], holds
    # not one global constant any more
    holds = [P.beat_max_hold(b, i, len(beats), "t_a")
             for i, b in enumerate(beats)]
    assert len(set(holds)) >= 6, holds


def test_hold_ceiling_is_deterministic_and_story_specific():
    b = _beat("B4")
    assert P.beat_max_hold(b, 3, 12, "t_x") == P.beat_max_hold(b, 3, 12, "t_x")
    vals = {P.beat_max_hold(b, 3, 12, f"t_{k}") for k in range(12)}
    assert len(vals) >= 5, vals


def test_short_punchy_line_is_kept_as_one_picture():
    short, long_ = _beat("B5", words=5), _beat("B5", words=14)
    for seed in ("t_a", "t_b", "t_c"):
        assert P.beat_max_hold(short, 4, 12, seed) > \
            P.beat_max_hold(long_, 4, 12, seed)


# --------------------------------------------------------------- tails --

def test_beat_tail_depends_on_what_follows():
    beats = _story()
    beats[5]["narration"] = "So why does it float?"
    tails = [P.beat_tail(beats, i, "t_a") for i in range(len(beats))]
    assert tails[0] == P.TAIL_AFTER_HOOK_S
    assert tails[-2] == P.TAIL_BEFORE_PAYOFF_S      # beat before the payoff
    assert tails[-1] == P.TAIL_END_S
    assert tails[5] == P.TAIL_QUESTION_S
    normal = [t for i, t in enumerate(tails) if i not in (0, 5, 10, 11)]
    lo, hi = P.TAIL_RANGE_S
    assert all(lo <= t <= hi for t in normal)
    assert len(set(normal)) >= 5, normal           # no metronome
    assert tails == [P.beat_tail(beats, i, "t_a") for i in range(len(beats))]


def test_shot_timeline_uses_the_given_tail():
    timing = {"words": [{"w": "w", "t0": 0.3 * i, "t1": 0.3 * i + 0.25}
                        for i in range(10)]}
    bplan = {"shots": [{"kind": "plate", "start_word": 0, "subject": "x"}]}
    a = P.shot_timeline(_beat("B2"), bplan, timing, 3.0)
    b = P.shot_timeline(_beat("B2"), bplan, timing, 3.0, tail_s=0.3)
    assert a[-1]["t1"] == round(P.LEAD_S + 3.0 + P.TAIL_S, 3)
    assert b[-1]["t1"] == round(P.LEAD_S + 3.0 + 0.3, 3)


# --------------------------------------------------------------- splits --

def _words(n, punct_at=()):
    return {"words": [{"w": "word," if i in punct_at else "word",
                       "t0": 0.3 * i, "t1": 0.3 * i + 0.25} for i in range(n)]}


def _one_shot(t1):
    return [{"shot": {"kind": "plate", "subject": "a frog floating",
                      "view": "medium", "composition": "centered",
                      "camera": "push_in", "start_word": 0},
             "t0": 0.0, "t1": t1}]


def test_unseeded_split_keeps_the_old_midpoint():
    tim = _words(20)
    tl = P.split_long_holds(_one_shot(6.0), tim, max_hold_s=4.0, margin_s=1.2)
    assert len(tl) == 2
    assert abs((tl[0]["t1"] - tl[0]["t0"]) - (tl[1]["t1"] - tl[1]["t0"])) < 0.35


def test_seeded_splits_are_not_all_midpoint_halves():
    tim = _words(20)
    ratios = []
    for k in range(16):
        tl = P.split_long_holds(_one_shot(5.0), tim, max_hold_s=4.0,
                                margin_s=1.2, seed=f"t_{k}|B2")
        assert len(tl) == 2
        d = sorted(s["t1"] - s["t0"] for s in tl)
        ratios.append(d[0] / d[1])
        # reproducible
        assert tl == P.split_long_holds(_one_shot(5.0), tim, max_hold_s=4.0,
                                        margin_s=1.2, seed=f"t_{k}|B2")
    assert statistics.median(ratios) < 0.8, ratios
    assert min(ratios) < 0.6, ratios


def test_seeded_split_prefers_a_phrase_boundary():
    # word 9 ends a clause -> word 10 starts a phrase; a cut there is
    # preferred over a nearer mid-phrase word.
    tim = _words(20, punct_at={9})
    hits = 0
    for k in range(12):
        tl = P.split_long_holds(_one_shot(6.0), tim, max_hold_s=4.0,
                                margin_s=1.2, seed=f"t_{k}|B3")
        cut = tl[1]["shot"]["start_word"]
        hits += cut == 10
    assert hits >= 6, hits


def test_split_margin_never_leaves_a_flicker():
    for h in (2.2, 2.6, 3.0, 4.0):
        assert 1.2 <= P.split_margin(h) <= 1.5
