"""2026-11-09: automated feedback, real retention -> cluster weights
(engine/v16_autoweight.py + the override layer in engine/v16_topics.py +
the auto step in engine/v16_feedback.py).

Built around the 28955f3 lesson: a signal that looked strong on 8 videos
(r = +0.55 / +0.59) was noise on 20, and a hard floor fit to it blocked a
promoted topic category. These tests show that:
  - small samples barely move weights, and below MIN_N they do not move at all;
  - large samples move them more, but never more than MAX_STEP per update;
  - re-runs do not compound, and weights converge to a shrunk target;
  - nothing leaves the 0.7x-1.3x band, so no weight reaches 0 (no gate);
  - score_candidate / rank_by_share / clusters_prompt_block / build_queue
    really use the override file, and a bad or stale file falls back to the
    hand-set baseline.

Synthetic history + fake YouTube clients only -- no network, no LLM, no render.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import v16_autoweight as AW  # noqa: E402
from engine import v16_topics as T  # noqa: E402

BASE_P, BASE_S = dict(T.CLUSTER_PRIORS), dict(T.CLUSTER_TARGET_SHARE)
ROW = {"counter_intuitive": 4, "visualisability": 4, "hook_strength": 4,
       "series_potential": 4, "evidence_strength": 4, "still_image_fit": 4}
_vid = iter(range(10 ** 6))


def _rows(cluster, n, ret, views=500, subs=0):
    out = []
    for _ in range(n):
        i = next(_vid)
        out.append({"id": f"t_{cluster}_{i}", "cluster": cluster, "status": "queued",
                    "real_video_id": f"yt{i}", "real_retention_pct": ret, "real_views": views,
                    "real_subs_gained": subs, "real_updated_at": "2026-11-01T00:00:00+00:00"})
    return out


def _rel(new, old):
    return abs(new / old - 1)


def _use_state(monkeypatch, path):
    monkeypatch.setenv(T.WEIGHT_STATE_ENV, str(path))


# ------------------------------------------------------- shrinkage math --

def test_confidence_is_zero_below_min_n_and_grows_with_n():
    assert AW.MIN_N == 5 and AW.PSEUDO_N == 20
    assert [AW.confidence(n) for n in (0, 1, 4)] == [0.0, 0.0, 0.0]
    assert AW.confidence(5) == pytest.approx(0.20)
    assert AW.confidence(30) == pytest.approx(0.60)
    cs = [AW.confidence(n) for n in range(5, 200)]
    assert cs == sorted(cs) and cs[-1] < 1.0


def test_small_samples_below_min_n_do_not_move_anything():
    """4 videos each, with a huge gap (120% vs 40%): exactly the 8-video
    trap of 28955f3. Nothing moves."""
    rows = _rows("spectacle_physics", 4, 120.0) + _rows("deep_time", 4, 40.0)
    st = AW.compute_state(rows)
    assert st["n_videos"] == 8
    assert st["priors"] == BASE_P
    assert st["shares"] == pytest.approx(BASE_S)
    assert all(c["factor"] == 1.0 for c in st["clusters"].values())


def test_small_n_barely_moves_large_n_moves_more_same_signal():
    """Same retention gap (deep_time 90% vs space_discovery 60%), n=5 vs n=30
    per cluster."""
    small = AW.compute_state(_rows("deep_time", 5, 90.0) + _rows("space_discovery", 5, 60.0))
    large = AW.compute_state(_rows("deep_time", 30, 90.0) + _rows("space_discovery", 30, 60.0))
    ds = _rel(small["priors"]["deep_time"], BASE_P["deep_time"])
    dl = _rel(large["priors"]["deep_time"], BASE_P["deep_time"])
    assert 0 < ds <= 0.07                      # a 50% retention gap on n=5 -> ~6%
    assert dl >= 0.15 and dl > 2 * ds          # n=30 -> ~18%
    # direction is right on both sides
    assert large["priors"]["deep_time"] > BASE_P["deep_time"]
    assert large["priors"]["space_discovery"] < BASE_P["space_discovery"]
    assert large["shares"]["deep_time"] > BASE_S["deep_time"]
    # clusters without data are untouched
    assert large["priors"]["spectacle_physics"] == BASE_P["spectacle_physics"]


def test_realistic_gap_on_live_sized_sample_moves_weights_by_a_couple_percent():
    """Live history (2026-10-26) shape: 5-7 clean videos per cluster with
    cluster means 64-70%. Adjustments stay around 2% or less."""
    rows = (_rows("deep_time", 7, 64.4) + _rows("space_discovery", 6, 70.3)
            + _rows("exotic_space_travel", 5, 70.0) + _rows("spectacle_physics", 2, 76.5))
    st = AW.compute_state(rows)
    for c in BASE_P:
        assert _rel(st["priors"][c], BASE_P[c]) < 0.03, c
    for c in BASE_S:
        assert _rel(st["shares"][c], BASE_S[c]) < 0.03, c


# ---------------------------------------------------------------- caps --

def _extreme(n=500):
    return _rows("deep_time", n, 120.0) + _rows("space_discovery", n, 30.0)


def test_single_update_never_exceeds_the_step_cap_even_on_overwhelming_data():
    st = AW.compute_state(_extreme())
    for c in BASE_P:
        assert _rel(st["priors"][c], BASE_P[c]) <= AW.MAX_STEP + 1e-6, c
    for c in BASE_S:
        assert _rel(st["shares"][c], BASE_S[c]) <= AW.MAX_STEP + 1e-6, c
    # the cap actually binds here (target is further away than 20%)
    assert _rel(st["priors"]["deep_time"], BASE_P["deep_time"]) == pytest.approx(0.20, abs=1e-6)
    assert sum(st["shares"].values()) == pytest.approx(1.0)


def test_repeated_updates_respect_cap_each_step_and_never_leave_the_band():
    lo, hi = T.AUTOWEIGHT_BAND
    rows, state = _extreme(), None
    for k in range(8):
        rows = rows + _rows("deep_time", 1, 120.0)       # new data -> new fingerprint
        new = AW.compute_state(rows, state)
        prev_p = state["priors"] if state else BASE_P
        prev_s = state["shares"] if state else BASE_S
        for c in BASE_P:
            assert _rel(new["priors"][c], prev_p[c]) <= AW.MAX_STEP + 1e-6
            assert lo * BASE_P[c] - 1e-9 <= new["priors"][c] <= hi * BASE_P[c] + 1e-9
        for c in BASE_S:
            assert _rel(new["shares"][c], prev_s[c]) <= AW.MAX_STEP + 1e-5
            assert lo * BASE_S[c] - 1e-6 <= new["shares"][c] <= hi * BASE_S[c] + 1e-6
            assert new["shares"][c] > 0                   # never a gate
        assert sum(new["shares"].values()) == pytest.approx(1.0, abs=1e-5)
        assert set(new["shares"]) == set(BASE_S)          # no cluster added/removed
        state = new
    assert state["priors"]["deep_time"] == pytest.approx(hi * BASE_P["deep_time"])
    assert state["priors"]["space_discovery"] == pytest.approx(lo * BASE_P["space_discovery"])


def test_rerun_on_same_data_is_a_noop_not_a_ratchet():
    rows = _extreme()
    s1 = AW.compute_state(rows)
    s2 = AW.compute_state(rows, s1)
    assert s2["changed_on_last_check"] is False
    assert s2["priors"] == s1["priors"] and s2["shares"] == s1["shares"]


def test_target_is_not_compounding_weights_converge_to_the_shrunk_target():
    """Even with the fingerprint guard defeated, repeated updates converge to
    baseline x factor (inside the band), not to the band edge."""
    rows = _rows("deep_time", 30, 90.0) + _rows("space_discovery", 30, 60.0)
    _, factors = AW.cluster_factors(AW.video_samples(rows)[0])
    target = BASE_P["deep_time"] * factors["deep_time"]["factor"]
    assert target < T.AUTOWEIGHT_BAND[1] * BASE_P["deep_time"]       # target is interior
    state = None
    for _ in range(12):
        state = AW.compute_state(rows, state and {**state, "data_fingerprint": "x"})
    assert state["priors"]["deep_time"] == pytest.approx(target, rel=1e-6)


# ------------------------------------------------------------ cleaning --

def test_cleaning_drops_noise_and_artifacts_winsorizes_loops_and_dedupes():
    rows = [
        {"cluster": "deep_time", "real_video_id": "a", "real_retention_pct": 116.1,
         "real_views": 3},                                            # low views
        {"cluster": "space_discovery", "real_video_id": "b", "real_retention_pct": 1099.0,
         "real_views": 52},                                           # artifact
        {"cluster": "exotic_space_travel", "real_video_id": "c", "real_retention_pct": 142.3,
         "real_views": 91},                                           # loop -> capped
        {"cluster": None, "real_video_id": "d", "real_retention_pct": 50, "real_views": 900},
        {"cluster": "deep_time", "real_video_id": "e", "real_retention_pct": 50.0,
         "real_views": 100, "real_updated_at": "2026-10-01"},
        {"cluster": "deep_time", "real_video_id": "e", "real_retention_pct": 60.0,
         "real_views": 200, "real_updated_at": "2026-11-01"},         # newer row wins
        {"cluster": "deep_time", "id": "no_real_fields"},
    ]
    samples, excluded = AW.video_samples(rows)
    assert excluded == {"low_views": 1, "implausible_retention": 1, "unknown_cluster": 1}
    by = {s["video_id"]: s for s in samples}
    assert set(by) == {"c", "e"}
    assert by["c"]["retention"] == AW.RETENTION_CAP and by["c"]["retention_raw"] == 142.3
    assert by["e"]["retention"] == 60.0 and by["e"]["views"] == 200


def test_secondary_signals_are_reported_but_do_not_move_weights():
    a = AW.compute_state(_rows("deep_time", 30, 70.0, views=5000, subs=50)
                         + _rows("space_discovery", 30, 70.0, views=30, subs=0))
    assert a["priors"] == BASE_P and a["shares"] == pytest.approx(BASE_S)
    dt_ = a["clusters"]["deep_time"]
    assert dt_["median_views"] == 5000 and dt_["subs_per_1k_views"] == 10.0


def test_state_file_holds_only_aggregates():
    st = AW.compute_state(_rows("deep_time", 6, 70.0))
    blob = json.dumps(st)
    assert "yt" not in blob.replace("data_fingerprint", "")       # no video ids
    assert st["base_priors"] == BASE_P and st["base_shares"] == BASE_S


# ------------------------------------- v16_topics override layer (read) --

def test_score_candidate_uses_the_autoweight_state_end_to_end(tmp_path, monkeypatch):
    """INTEGRATION: AW.run on a history writes the state, v16_topics reads it,
    and score_candidate's cluster_prior points follow it."""
    hist = tmp_path / "topic_history.jsonl"
    rows = _rows("deep_time", 30, 90.0) + _rows("space_discovery", 30, 60.0)
    hist.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rep = AW.run(history_path=hist)
    state_path = Path(rep["state_path"])
    assert state_path == tmp_path / "cluster_weight_state.json" and state_path.exists()

    cand = {"cluster": "deep_time", "evergreen": True}
    base_pts = T.score_candidate(cand, ROW)[1]["cluster_prior"]       # env=off -> baseline
    assert base_pts == round(BASE_P["deep_time"] * 25, 2)

    _use_state(monkeypatch, state_path)
    new_prior = json.loads(state_path.read_text())["priors"]["deep_time"]
    assert new_prior > BASE_P["deep_time"]
    assert T.cluster_priors()["deep_time"] == pytest.approx(new_prior)
    score, bd = T.score_candidate(cand, ROW)
    assert bd["cluster_prior"] == round(new_prior * 25, 2) > base_pts
    sp = T.score_candidate({"cluster": "space_discovery", "evergreen": True}, ROW)[1]
    assert sp["cluster_prior"] < round(BASE_P["space_discovery"] * 25, 2)
    assert "deep_time (prior %.2f" % new_prior in T.clusters_prompt_block()


def _entries():
    out = []
    for c in ("spectacle_physics", "deep_time", "space_discovery", "exotic_space_travel"):
        out += [{"id": f"{c}{i}", "title": f"{c}{i}", "cluster": c, "score": 80 - i}
                for i in range(12)]
    return out


def _write_state(path, priors=None, shares=None, **extra):
    st = {"version": 1, "base_priors": BASE_P, "base_shares": BASE_S,
          "priors": priors or BASE_P, "shares": shares or BASE_S, **extra}
    path.write_text(json.dumps(st))
    return path


def test_rank_by_share_default_uses_the_override_shares(tmp_path, monkeypatch):
    """INTEGRATION: rank_by_share(entries) with no explicit shares follows the
    state file, while an explicit shares= still wins."""
    shares = {"spectacle_physics": 0.40, "deep_time": 0.325,
              "space_discovery": 0.175, "exotic_space_travel": 0.10}
    base_q = T.rank_by_share(_entries())
    _use_state(monkeypatch, _write_state(tmp_path / "s.json", shares=shares))
    assert T.cluster_target_share() == pytest.approx(shares)
    q = T.rank_by_share(_entries())
    assert q == T.rank_by_share(_entries(), shares=shares)
    assert q != base_q
    new20, base20 = T.queue_share(q[:20]), T.queue_share(base_q[:20])
    assert base20["deep_time"] == base20["space_discovery"] == 0.25
    assert new20["deep_time"] >= 0.30 and new20["space_discovery"] <= 0.20
    assert T.rank_by_share(_entries(), shares=BASE_S) == base_q


def test_build_queue_scores_and_prompts_with_the_override(tmp_path, monkeypatch):
    """INTEGRATION through the production entry point v16_batch calls."""
    priors = {**BASE_P, "deep_time": 1.04}                            # 1.3 x 0.80
    shares = {"spectacle_physics": 0.40, "deep_time": 0.325,
              "space_discovery": 0.175, "exotic_space_travel": 0.10}
    _use_state(monkeypatch, _write_state(tmp_path / "s.json", priors=priors, shares=shares))
    raw = [{"title": f"Distinct topic {i} {c} words{i}", "cluster": c, "claim": f"claim {i} {c}",
            "entities": {"subject": f"subj{i}"}, "hooks": ["h"], "templates": ["BIG_NUMBER"],
            "series_id": None, "series_part": None, "evergreen": True}
           for i, c in enumerate(["deep_time", "space_discovery"] * 3)]
    seen, ids = set(), []
    for c in raw:
        ids.append(T._unique_id(T.slugify(c["title"]), seen))
        seen.add(ids[-1])
    scores = [{"id": i, **ROW, "best_hook": "h"} for i in ids]
    q = {"topic_ideate": [{"candidates": raw}], "topic_score": [{"scores": scores}]}
    prompts = []

    def ask(stage, prompt, **kw):
        prompts.append(prompt)
        return SimpleNamespace(data=q[stage].pop(0), model="fake", cached=False,
                               attempts=1, usage={})
    res = T.build_queue(n=6, history_path=tmp_path / "h.jsonl", ask=ask, persist=False)
    assert "deep_time (prior 1.04; aim for ~32% of candidates)" in prompts[0]
    by = {e["cluster"]: e for e in res["queue"]}
    assert by["deep_time"]["score_breakdown"]["cluster_prior"] == 26.0
    assert by["space_discovery"]["score_breakdown"]["cluster_prior"] == 12.5


def test_out_of_band_or_foreign_values_are_clamped_on_read(tmp_path, monkeypatch):
    lo, hi = T.AUTOWEIGHT_BAND
    _use_state(monkeypatch, _write_state(
        tmp_path / "s.json",
        priors={**BASE_P, "deep_time": 5.0, "space_discovery": 0.0, "quiz": 9.0,
                "general_explainer": "junk"},
        shares={"spectacle_physics": 0.0, "deep_time": 0.9, "space_discovery": 0.05,
                "exotic_space_travel": 0.05, "general_explainer": 0.5}))
    p = T.cluster_priors()
    assert set(p) == set(BASE_P)                                  # quiz never enters
    assert p["deep_time"] == pytest.approx(hi * BASE_P["deep_time"])
    assert p["space_discovery"] == pytest.approx(lo * BASE_P["space_discovery"])
    assert p["general_explainer"] == BASE_P["general_explainer"]
    s = T.cluster_target_share()
    assert set(s) == set(BASE_S) and "general_explainer" not in s
    assert sum(s.values()) == pytest.approx(1.0)
    for c, v in s.items():
        assert lo * BASE_S[c] - 1e-9 <= v <= hi * BASE_S[c] + 1e-9
    assert s["spectacle_physics"] > 0
    assert T.score_candidate({"cluster": "quiz"}, ROW)[0] == 0       # still excluded


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""])
def test_malformed_state_falls_back_to_baseline(tmp_path, monkeypatch, content):
    f = tmp_path / "s.json"
    f.write_text(content)
    _use_state(monkeypatch, f)
    assert T.cluster_priors() == BASE_P and T.cluster_target_share() == BASE_S


def test_state_from_a_different_baseline_is_ignored(tmp_path, monkeypatch):
    """A human re-baselines CLUSTER_PRIORS: the stale override must not cancel it."""
    _use_state(monkeypatch, _write_state(
        tmp_path / "s.json", priors={**BASE_P, "deep_time": 1.0},
        base_priors={**BASE_P, "deep_time": 0.9}))
    assert T.cluster_priors() == BASE_P
    st = json.loads((tmp_path / "s.json").read_text())
    # and the writer restarts from the current baseline instead of the stale values
    new = AW.compute_state([], st)
    assert new["priors"] == BASE_P and new["base_priors"] == BASE_P


def test_missing_file_and_env_off_mean_baseline(tmp_path, monkeypatch):
    _use_state(monkeypatch, tmp_path / "nope.json")
    assert T.cluster_priors() == BASE_P and T.cluster_target_share() == BASE_S
    _use_state(monkeypatch, _write_state(tmp_path / "s.json", priors={**BASE_P, "deep_time": 1.0}))
    assert T.cluster_priors()["deep_time"] == 1.0
    monkeypatch.setenv(T.WEIGHT_STATE_ENV, "off")
    assert T.cluster_priors() == BASE_P


def test_rewritten_state_is_picked_up_without_restart(tmp_path, monkeypatch):
    f = _write_state(tmp_path / "s.json", priors={**BASE_P, "deep_time": 0.9})
    _use_state(monkeypatch, f)
    assert T.cluster_priors()["deep_time"] == 0.9
    AW.write_state(f, {"base_priors": BASE_P, "base_shares": BASE_S,
                       "priors": {**BASE_P, "deep_time": 0.7}, "shares": BASE_S})
    assert T.cluster_priors()["deep_time"] == 0.7


# ------------------------------------------------------ run / CLI / I/O --

def test_run_writes_atomically_and_skips_rewrite_on_unchanged_data(tmp_path):
    hist = tmp_path / "h.jsonl"
    hist.write_text("".join(json.dumps(r) + "\n" for r in _rows("deep_time", 6, 80.0)))
    st = tmp_path / "w.json"
    AW.run(history_path=hist, state_path=st, now="2026-11-09T00:00:00+00:00")
    first = st.read_text()
    rep = AW.run(history_path=hist, state_path=st, now="2026-11-10T00:00:00+00:00")
    assert rep["state"]["changed_on_last_check"] is False
    assert st.read_text() == first and not (tmp_path / "w.json.tmp").exists()


def test_dry_run_and_cli_write_nothing(tmp_path, capsys):
    hist = tmp_path / "h.jsonl"
    hist.write_text("".join(json.dumps(r) + "\n" for r in _rows("deep_time", 6, 80.0)))
    assert AW.main(["--history", str(hist), "--dry-run"]) == 0
    assert not (tmp_path / "cluster_weight_state.json").exists()
    assert "would write" in capsys.readouterr().out
    assert AW.main(["--history", str(hist)]) == 0
    assert (tmp_path / "cluster_weight_state.json").exists()


def test_default_state_path_production_vs_temp(tmp_path):
    assert AW.default_state_path(None) == T.CLUSTER_WEIGHT_STATE_PATH
    assert AW.default_state_path(T.DEFAULT_HISTORY_PATH) == T.CLUSTER_WEIGHT_STATE_PATH
    assert AW.default_state_path(tmp_path / "h.jsonl") == tmp_path / "cluster_weight_state.json"


# --------------------------------------------- v16_feedback auto step --

def test_feedback_run_recomputes_weights_into_the_history_dir(tmp_path):
    import test_feedback_20261024 as TF
    prod = T.CLUSTER_WEIGHT_STATE_PATH
    before = prod.stat().st_mtime_ns if prod.exists() else None
    rep, w, _ = TF._run(tmp_path)
    aw = rep["autoweight"]
    assert "error" not in aw and Path(aw["state_path"]) == tmp_path / "cluster_weight_state.json"
    st = json.loads((tmp_path / "cluster_weight_state.json").read_text())
    assert st["n_videos"] == 3                        # the 3 matched videos, read back from history
    assert st["priors"] == BASE_P                     # n=1 per cluster -> no change
    assert (prod.stat().st_mtime_ns if prod.exists() else None) == before


def test_feedback_dry_run_previews_weights_without_writing(tmp_path):
    import test_feedback_20261024 as TF
    rep, _, _ = TF._run(tmp_path, dry_run=True)
    assert rep["autoweight"]["dry_run"] is True and rep["autoweight"]["state"]["n_videos"] == 3
    assert not (tmp_path / "cluster_weight_state.json").exists()


def test_feedback_keeps_history_when_autoweight_fails(tmp_path, monkeypatch):
    import test_feedback_20261024 as TF

    def boom(**kw):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(AW, "run", boom)
    rep, w, _ = TF._run(tmp_path)
    assert rep["autoweight"] == {"error": "RuntimeError: synthetic"}
    rows = [json.loads(x) for x in w["history_path"].read_text().splitlines()]
    assert rows[2]["real_views"] == 777


def test_feedback_no_autoweight_flag(tmp_path):
    import test_feedback_20261024 as TF
    rep, _, _ = TF._run(tmp_path, autoweight=False)
    assert rep["autoweight"] is None
    assert not (tmp_path / "cluster_weight_state.json").exists()
