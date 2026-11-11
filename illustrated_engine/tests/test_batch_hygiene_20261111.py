"""2026-11-11 review item 7: v16_batch --resume on a genuinely interrupted
batch_state.json (process killed mid-video, not a quota pause), and the
selection log distinguishing "0 topics selected" from "all held downstream".

Fake pipeline only -- no render, no network.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import v16_batch as B  # noqa: E402
from test_wp12_batch import _fake_report  # noqa: E402


def _killed_state(work: Path, stories: list) -> dict:
    """What run_batch's checkpoint holds when the process dies while
    rendering stories[1]: stories[0] done (row + totals), the in-flight one
    still pending[0] (the checkpoint is only advanced after a story ends)."""
    state = {"batch_id": work.name, "pending": [str(s) for s in stories[1:]],
             "done": [str(stories[0])],
             "rows": [{"story": stories[0].name, "verdict": "PASS", "wall_s": 5.0}],
             "totals": {"llm_calls": 1, "image_calls": 2, "vision_calls": 1},
             "started_at": time.time() - 600, "lanes_overlap": False}
    work.mkdir(parents=True, exist_ok=True)
    (work / "batch_state.json").write_text(json.dumps(state))
    return state


def _stories(tmp_path, n=3):
    out = []
    for i in range(n):
        d = tmp_path / "stories" / f"s{i}"
        d.mkdir(parents=True)
        (d / "story.json").write_text(json.dumps({"story_id": f"s{i}", "beats": []}))
        out.append(d)
    return out


def test_resume_reruns_the_in_flight_story_and_the_rest_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BUILD_DIR", str(tmp_path))
    stories = _stories(tmp_path)
    work = tmp_path / "batch"
    # a half-written work dir from the killed render must not matter
    (work / "s1").mkdir(parents=True)
    (work / "s1" / "final.mp4").write_bytes(b"partial")
    _killed_state(work, stories)
    calls = []

    def fake(sd, out, **kw):
        calls.append(Path(sd).name)
        return _fake_report(Path(sd).name)

    import engine.v15_pipeline as P
    monkeypatch.setattr(P, "run_pipeline", fake)
    monkeypatch.setattr(B, "_record_published", lambda *a, **k: True)
    rep = B.run_batch([], work, resume=True, package=False)
    assert calls == ["s1", "s2"]                   # s0 is not re-rendered
    assert rep["pending"] == [] and rep["paused"] is False
    assert [r["story"] for r in rep["rows"]] == ["s0", "s1", "s2"]
    assert rep["totals"]["llm_calls"] == 3          # carried over + 2 new
    saved = json.loads((work / "batch_report.json").read_text())
    assert [r["story"] for r in saved["rows"]] == ["s0", "s1", "s2"]
    cp = json.loads((work / "batch_state.json").read_text())
    assert cp["pending"] == [] and len(cp["done"]) == 3


def test_resume_ignores_new_story_args_when_a_checkpoint_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BUILD_DIR", str(tmp_path))
    stories = _stories(tmp_path, 4)
    work = tmp_path / "batch"
    _killed_state(work, stories[:3])
    calls = []
    import engine.v15_pipeline as P
    monkeypatch.setattr(P, "run_pipeline",
                        lambda sd, out, **kw: calls.append(Path(sd).name)
                        or _fake_report(Path(sd).name))
    monkeypatch.setattr(B, "_record_published", lambda *a, **k: True)
    B.run_batch([stories[3]], work, resume=True, package=False)
    assert calls == ["s1", "s2"]


def test_cli_resume_without_stories_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BUILD_DIR", str(tmp_path))
    stories = _stories(tmp_path)
    work = tmp_path / "batch"
    _killed_state(work, stories)
    monkeypatch.setattr(B, "preflight", lambda w, n_videos=1: {"ok": True})
    seen = {}

    def fake_run_batch(dirs, w, **kw):
        seen.update(dirs=dirs, **kw)
        return {"rows": [], "totals": {}, "paused": False}
    monkeypatch.setattr(B, "run_batch", fake_run_batch)
    monkeypatch.setattr(sys, "argv", ["v16_batch", "--work", str(work), "--resume"])
    assert B.main() == 0
    assert seen["dirs"] == [] and seen["resume"] is True


# ----------------------------------------------------------- log lines --

def test_zero_topics_selected_is_reported_as_such():
    lines = B.selection_summary({"picked": [], "queue": [], "raw_count": 18},
                                {"dirs": [], "holds": []})
    assert len(lines) == 1
    assert "topic engine selected 0 topics" in lines[0] and "18 raw" in lines[0]
    assert "held during research/script" not in lines[0]


def test_all_selected_slots_held_downstream_is_reported_as_such():
    lines = B.selection_summary({"picked": [{}, {}, {}], "queue": [{}] * 5, "raw_count": 18},
                                {"dirs": [], "holds": [{}, {}, {}]})
    assert "materialized 0/3" in lines[0]
    assert "all 3 selected slots held during research/script" in lines[1]


def test_partial_materialization_has_no_nothing_renderable_line():
    lines = B.selection_summary({"picked": [{}, {}], "queue": [], "raw_count": 9},
                                {"dirs": ["d"], "holds": [{}]})
    assert lines == ["materialized 1/2 slots into story dirs (1 held during "
                     "research/script generation — see materialize_report.json)"]
