"""2026-10-15 review CRITICAL fix: a REJECT/HOLD §10.2 scorecard must stop the
gate verdict from being PASS (two REJECT-scored videos -- 66.6, 63.2 --
shipped publish_gate=PASS and auto-uploaded); story=0-by-construction proxy
bug; check_duration (30-60 s) wired into the gate.

Run: python3 -m pytest -q tests/test_gate_scorecard_blocks.py   (no network)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v15_gate  # noqa: E402
from engine import v16_gate as g  # noqa: E402
from engine import v16_manifest as m  # noqa: E402


def _meta_specs(n=12, dur=4.0, headline=True):
    meta, specs = {}, {}
    for i in range(1, n + 1):
        key = f"B{i}_S1"
        meta[key] = {"beat": f"B{i}", "kind": "plate", "function": "NORMAL"}
        specs[key] = {"duration_s": dur, "layers": [],
                      "meta": {"text_boxes": [{"id": "headline"}] if headline and i == 1 else []}}
    return meta, specs


def _fake_base(duration_s, judge_flagged=0):
    checks = {
        "judge": {"ok": True, "hook_stops_scroll": True,
                  "frames_flagged": [{"f": i} for i in range(judge_flagged)]},
        "caption_identity": {"ok": True, "fails": []},
        "text_bounds": {"ok": True, "fails": []},
        "caption_safe": {"ok": True, "fails": []},
        "audio": {"ok": True, "fails": [], "lufs": -14.0},
        "av": {"ok": True, "fails": [], "duration_s": duration_s},
    }
    return {"checks": checks, "verdict": "PASS", "failures": {}}


def _run(monkeypatch, story, *, duration_s=48.0, judge_flagged=0, n=12, dur=4.0):
    monkeypatch.setattr(v15_gate, "run_gate",
                        lambda *a, **k: _fake_base(duration_s, judge_flagged))
    monkeypatch.setattr(v15_gate, "_plate_paths", lambda specs: [])
    meta, specs = _meta_specs(n, dur)
    timing = {"B1": {"words": [{"t0": 0.0}]}}
    return g.run_gate("/nonexistent", story, meta, specs, timing, {}, 0.1,
                      brand={}, plates={}, sting_present=True, video_id="v")


def _weak_story():
    # an auto-generated story whose critic scored it poorly (0-5 scale)
    beats = [{"beat_id": f"B{i}", "claim": "x", "fact_ids": ["f"]} for i in range(1, 13)]
    return {"story_id": "weak", "beats": beats,
            "critic": {"scores": {"hook_strength": 0, "payoff_clarity": 0,
                                  "escalation": 0}}}


def test_reject_scorecard_blocks_publish(monkeypatch):
    out = _run(monkeypatch, _weak_story(), judge_flagged=4)
    assert out["scorecard"]["verdict"] == "REJECT"
    assert out["verdict"] != "PASS"
    assert out["verdict"] == "FAIL"
    assert "scorecard" in out["failures"]
    # the manifest's `publishable` derives from the same verdict
    assert m.build_manifest(video_id="v", brand={}, voice={}, plates={},
                            plate_realistic=None, audio_rows=[], llm_calls=[],
                            verdict=out["verdict"])["publishable"] is False


def test_hold_scorecard_holds():
    c = g.check_scorecard({"total": 74.0, "verdict": "HOLD",
                           "dimensions": {"story": 40.0, "hook": 100.0}})
    assert not c["ok"] and not c["critical"]
    assert v15_gate.verdict_of({"scorecard": c}) == "HOLD"


def test_pass_scorecard_still_passes(monkeypatch):
    story = _weak_story()
    story["critic"]["scores"] = {"a": 5, "b": 5}
    out = _run(monkeypatch, story)
    assert out["scorecard"]["verdict"] == "PASS"
    assert out["verdict"] == "PASS"
    assert out["checks"]["scorecard"]["ok"]


def test_real_reviewed_scorecards_are_not_pass():
    # verbatim dimensions of the two reviewed renders (live_20261014_*)
    for dims, total in (({"hook": 100.0, "story": 0.0, "visuals": 40.0, "pacing": 100.0,
                          "captions": 100.0, "audio": 56.0, "brand": 100.0}, 66.6),
                        ({"hook": 100.0, "story": 0.0, "visuals": 20.0, "pacing": 97.6,
                          "captions": 100.0, "audio": 56.0, "brand": 100.0}, 63.2)):
        c = g.check_scorecard({"total": total, "verdict": "REJECT", "dimensions": dims})
        assert not c["ok"] and c["critical"]
        assert v15_gate.verdict_of({"scorecard": c}) == "FAIL"


def test_duration_over_60s_holds(monkeypatch):
    story = _weak_story()
    story["critic"]["scores"] = {"a": 5, "b": 5}
    out = _run(monkeypatch, story, duration_s=62.7)
    assert not out["checks"]["duration"]["ok"]
    assert out["verdict"] == "HOLD"
    assert out["scorecard"] is None


def test_duration_falls_back_to_timeline():
    meta, specs = _meta_specs(n=4, dur=5.0)
    c = g.check_duration_gate(specs, meta, {})
    assert c["duration_s"] == 20.0 and not c["ok"]


def test_story_proxy_no_longer_zero_by_construction():
    # the asteroid story.json shape: claim + fact_ids, no contradiction/critic
    story = {"beats": [{"claim": "x", "fact_ids": ["f"]} for _ in range(12)]}
    assert g._score_story(story) == 40.0


def test_autostory_threads_critic_scores():
    from engine.v16_autostory import script_to_story
    eng = {"script": {"sentences": [{"text": "A b c.", "role": "hook", "fact_ids": ["f"]}]},
           "metadata": {"title": "A Title Here Now"},
           "critic": {"scores": {"hook_strength": 4}, "critique": "ok"}}
    story = script_to_story({"title": "t"}, eng)
    assert story["critic"]["scores"] == {"hook_strength": 4}
    # 2026-10-24: a 4 maps to 92 on the critic's own scale (v16_script.CRITIC_POINTS), was 4 x 20
    assert g._score_story(story) == 92.0
