"""2026-11-11 review item 3: v15_pipeline exits before the expensive stages
(subject bible / plan LLM calls, image generation, render, assembly) when
the voice result or the projected duration already decides a HOLD.

Run: python3 -m pytest -q tests/test_pipeline_early_exit_20261111.py
(no network, no TTS, no render: synthesize_video / beat_timing are stubbed)
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v15_pipeline as P  # noqa: E402
from engine.v16_script import DURATION_S  # noqa: E402

LO, HI = DURATION_S


def _beats(n=8):
    fns = ["HOOK"] + ["ESCALATION"] * (n - 2) + ["PAYOFF"]
    return [{"beat_id": f"B{i + 1}", "function": fns[i],
             "narration": f"line number {i + 1} of the story here."}
            for i in range(n)]


def _even(beats, total):
    """tts per beat so that sum(LEAD + tts + tail) == total with tails=0."""
    per = total / len(beats) - P.LEAD_S
    return {b["beat_id"]: per for b in beats}, {b["beat_id"]: 0.0 for b in beats}


# ------------------------------------------------------- plan_duration --

def test_projection_is_lead_plus_tts_plus_tail():
    beats = _beats(3)
    tts = {"B1": 5.0, "B2": 10.0, "B3": 12.0}
    tails = {"B1": 0.0, "B2": 0.28, "B3": 0.35}
    d = P.plan_duration(beats, tts, tails)
    assert d["projected_s"] == pytest.approx(3 * P.LEAD_S + 27.0 + 0.63)
    assert d["fails"] == [] and d["pad"] == {}


def test_comfortably_long_story_is_untouched():
    beats = _beats()
    tts, tails = _even(beats, 40.0)
    d = P.plan_duration(beats, tts, tails)
    assert d["pad"] == {} and d["fails"] == []
    assert d["padded_s"] == d["projected_s"]


def test_small_shortfall_is_padded_on_non_hook_tails():
    """the observed case: 24.3 s against the 25 s floor."""
    beats = _beats()
    tts, tails = _even(beats, 24.3)
    d = P.plan_duration(beats, tts, tails)
    assert d["fails"] == []
    assert "B1" not in d["pad"]                       # hook tail stays 0
    assert set(d["pad"]) == {f"B{i}" for i in range(2, 9)}
    assert all(0 < v <= P.DURATION_PAD_MAX_PER_BEAT_S for v in d["pad"].values())
    assert d["padded_s"] >= LO + P.DURATION_PAD_MARGIN_S - 0.01


def test_shortfall_beyond_pad_capacity_holds_early():
    beats = _beats()
    tts, tails = _even(beats, 20.0)      # 7 paddable beats * 0.25 = 1.75 s max
    d = P.plan_duration(beats, tts, tails)
    assert d["pad"] == {}
    assert d["fails"] and d["fails"][0].startswith("duration: 20.0s <")


def test_pad_can_reach_floor_even_if_not_the_margin():
    beats = _beats()
    cap = P.DURATION_PAD_MAX_PER_BEAT_S * 7
    tts, tails = _even(beats, LO - cap + 0.05)
    d = P.plan_duration(beats, tts, tails)
    assert d["fails"] == []
    assert d["padded_s"] >= LO


def test_over_length_without_justification_holds_early():
    beats = _beats()
    tts, tails = _even(beats, HI + 3.0)
    d = P.plan_duration(beats, tts, tails, {})
    assert d["fails"] and "length_justification" in d["fails"][0]
    d2 = P.plan_duration(beats, tts, tails, {"length_justification": "x"})
    assert d2["fails"] == []


def test_over_length_inside_measurement_tolerance_is_not_held_early():
    beats = _beats()
    tts, tails = _even(beats, HI + 0.05)
    assert P.plan_duration(beats, tts, tails, {})["fails"] == []


# ---------------------------------------------------- voice_early_hold --

def _voice(held=(), unchecked=(), publishable=True):
    return {"provider": "kokoro", "voice_id": "v", "publishable": publishable,
            "qa": {"verdict": "HOLD" if held else "PASS",
                   "held_beats": list(held), "unchecked_beats": list(unchecked),
                   "beat_wer": {b: 0.2 for b in held}, "max_wer": 0.03}}


def test_clean_voice_does_not_exit():
    assert P.voice_early_hold(_voice()) == []


def test_single_held_beat_is_borderline_and_runs_on():
    assert P.voice_early_hold(_voice(held=["B3"])) == []


def test_two_held_beats_exit_with_the_gate_reason():
    fails = P.voice_early_hold(_voice(held=["B3", "B6"]))
    assert fails and "round-trip QA failed on beats ['B3', 'B6']" in fails[0]


def test_unchecked_beats_never_trigger_the_exit():
    v = _voice(held=["B3", "B6"], unchecked=["B3", "B6"])
    assert P.voice_early_hold(v) == []


def test_voice_not_cleared_for_commercial_use_exits():
    fails = P.voice_early_hold(_voice(publishable=False))
    assert any("commercial" in f for f in fails)


# ------------------------------------------------- run_pipeline wiring --

@pytest.fixture
def stub_story(tmp_path, monkeypatch):
    sd = tmp_path / "story"
    sd.mkdir()
    beats = _beats()
    (sd / "story.json").write_text(json.dumps(
        {"story_id": "t_early", "title": "t", "beats": beats}))
    monkeypatch.setattr(P, "load_style", lambda d, s: {"deck": "x"})
    monkeypatch.setattr(P, "beat_timing",
                        lambda path, narr: {"anchored": True, "boundaries": [],
                                            "words": []})

    def explode(*a, **k):
        raise AssertionError("expensive stage reached after a decided HOLD")
    import engine.subject_bible as SB
    monkeypatch.setattr(SB, "build_subject_bible", explode)
    monkeypatch.setattr(P, "make_plan", explode)
    monkeypatch.setattr(P, "generate_plate", explode)
    return sd, beats


def _stub_voice(monkeypatch, beats, per_beat_s, voice):
    import engine.voice as V
    monkeypatch.setattr(V, "synthesize_video", lambda d, b: {
        "voice": voice,
        "beats": {x["beat_id"]: {"duration": per_beat_s, "file": "a.wav"}
                  for x in beats}})


def test_run_pipeline_holds_on_duration_before_any_image(stub_story, tmp_path,
                                                         monkeypatch):
    sd, beats = stub_story
    _stub_voice(monkeypatch, beats, 2.0, _voice())       # ~17 s total
    rep = P.run_pipeline(sd, tmp_path / "work")
    assert rep["publish_gate"] == "HOLD"
    assert rep["gate"]["early_exit"] == "duration"
    assert list(rep["gate"]["failures"]) == ["duration"]
    assert rep["gate"]["checks"]["duration"]["duration_s"] < LO
    assert rep["costs"]["image_calls"] == 0
    saved = json.loads((tmp_path / "work" / "pipeline_report.json").read_text())
    assert saved["early_exit"]["stage"] == "duration"


def test_run_pipeline_holds_on_voice_before_any_image(stub_story, tmp_path,
                                                      monkeypatch):
    sd, beats = stub_story
    _stub_voice(monkeypatch, beats, 4.0, _voice(held=["B2", "B5"]))
    rep = P.run_pipeline(sd, tmp_path / "work")
    assert rep["publish_gate"] == "HOLD"
    assert rep["gate"]["early_exit"] == "voice"
    assert list(rep["gate"]["failures"]) == ["voice"]


def test_batch_row_accepts_an_early_exit_report(stub_story, tmp_path,
                                                monkeypatch):
    sd, beats = stub_story
    _stub_voice(monkeypatch, beats, 2.0, _voice())
    monkeypatch.setenv("LLM_BUILD_DIR", str(tmp_path))
    from engine import v16_batch as B
    monkeypatch.setattr(B, "_llm_blocked", lambda: None)
    rep = B.run_batch([sd], tmp_path / "batch", package=True, upload=False,
                      history_path=tmp_path / "h.jsonl")
    row = rep["rows"][0]
    assert row["verdict"] == "HOLD", row
    assert row["early_exit"] == "duration"
    assert row["duration_s"] < LO
    assert row["package"]["ok"] is False        # no final.mp4, nothing uploaded
