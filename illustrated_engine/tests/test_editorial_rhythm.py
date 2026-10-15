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


def test_seeded_splits_are_not_all_midpoint_halves(monkeypatch):
    # split statistics are calibrated on this synthetic 0.3 s word grid at
    # the original 0.18 s LEAD_S; LEAD_S only shifts every cut uniformly
    # (2026-10-15 pacing change 0.18 -> 0.06) and moves the grid alignment,
    # not the split logic under test.
    monkeypatch.setattr(P, "LEAD_S", 0.18)
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


def test_seeded_split_prefers_a_phrase_boundary(monkeypatch):
    # split statistics are calibrated on this synthetic 0.3 s word grid at
    # the original 0.18 s LEAD_S; LEAD_S only shifts every cut uniformly
    # (2026-10-15 pacing change 0.18 -> 0.06) and moves the grid alignment,
    # not the split logic under test.
    monkeypatch.setattr(P, "LEAD_S", 0.18)
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


# ---------------------------------------------- progressive lengthening --
# Owner follow-up 2026-10-14: "isn't 2 s too low? fine to start, but later
# in the video?" -- holds trend longer as the story unfolds, for every role.

def _mean_holds(beats, seeds=200):
    n = len(beats)
    return [statistics.mean(P.beat_max_hold(b, i, n, f"t_{k}")
                            for k in range(seeds))
            for i, b in enumerate(beats)]


def test_holds_trend_longer_as_the_video_progresses():
    # 14 identical long-line NORMAL beats (same id -> same jitter per
    # seed): only position differs
    beats = [_beat("Bx", words=12) for _ in range(14)]
    n = len(beats)
    holds = _mean_holds(beats)
    runup = n - P.HOLD_RUNUP_BEATS
    pre = holds[:runup]
    assert all(b >= a for a, b in zip(pre, pre[1:])), pre
    assert pre[-1] - pre[0] >= 0.3, pre
    # the run-up before the payoff still dips against the trend ...
    assert holds[runup] < holds[runup - 1], holds
    # ... and the late run-up still sits above the opening beats
    assert holds[-1] > holds[0], holds
    # modest: the ramp never pins everything at the ceiling
    assert max(holds) < P.HOLD_MAX_S, holds


def test_progression_applies_to_every_role_not_just_reveal_payoff():
    for fn in ("CURIOSITY", "ESCALATION", "REVEAL", "EXPLANATION"):
        b = _beat("B5", fn=fn, words=12)
        early = statistics.mean(P.beat_max_hold(b, 1, 12, f"t_{k}")
                                for k in range(100))
        late = statistics.mean(P.beat_max_hold(b, 10, 12, f"t_{k}")
                               for k in range(100))
        assert late > early + 0.2, (fn, early, late)


def test_progression_keeps_the_hook_fast_and_is_deterministic():
    beats = _story()
    n = len(beats)
    for seed in ("t_a", "t_b", "t_c"):
        # bi=0 gets no ramp: the hook ceiling is exactly the role+jitter one
        old = P.HOLD_PROGRESS_S
        try:
            P.HOLD_PROGRESS_S = 0.0
            flat = P.beat_max_hold(beats[0], 0, n, seed)
        finally:
            P.HOLD_PROGRESS_S = old
        assert P.beat_max_hold(beats[0], 0, n, seed) == flat
        assert [P.beat_max_hold(b, i, n, seed) for i, b in enumerate(beats)] \
            == [P.beat_max_hold(b, i, n, seed) for i, b in enumerate(beats)]


# -------------------------------------------------------- pacing score --
# Owner follow-up 2026-10-14: "scorer target should be upgraded" -- the
# v16 scorecard rewarded the old 1.8 s / 1.2-2.0 s uniform-cut target.

def _shots(durs):
    meta = {f"s{i}": {} for i in range(len(durs))}
    specs = {f"s{i}": {"duration_s": d, "layers": []}
             for i, d in enumerate(durs)}
    return meta, specs


def test_pacing_score_bands_track_the_rhythm_constants():
    from engine import v16_gate as V
    assert V.PACING_HOLD_BAND_S == (P.HOLD_MIN_S, P.HOLD_MAX_S)


def test_pacing_score_rewards_varied_role_based_holds_over_uniform_cuts():
    from engine import v16_gate as V
    varied = _shots([1.6, 2.2, 2.7, 2.0, 1.9, 3.6, 3.3, 3.9, 2.4, 2.6,
                     1.5, 3.1, 2.8, 3.8])
    uniform = _shots([2.25] * 14)              # midpoint-split metronome
    old_target = _shots([1.5, 1.6, 1.7, 1.5, 1.6, 1.8] * 2)  # WP7 1.8 s band
    assert V._score_pacing(*varied) >= 95.0
    assert V._score_pacing(*uniform) < V._score_pacing(*varied)
    assert V._score_pacing(*old_target) < V._score_pacing(*varied)


def test_pacing_score_still_penalises_a_hold_past_the_ceiling():
    from engine import v16_gate as V
    ok = _shots([2.4, 3.9, 1.8, 3.0, 2.2, 3.4])
    long_ = _shots([2.4, 4.4, 1.8, 3.0, 2.2, 3.4])
    assert V._score_pacing(*long_) < V._score_pacing(*ok)
