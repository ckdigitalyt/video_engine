"""2026-10-24 analytics review, item 4: real-performance feedback loop
(engine/v16_feedback.py). Fake YouTube Analytics/Data clients, temp dirs.
No network, no render.
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_feedback as F  # noqa: E402

HEADERS = ["video", "views", "estimatedMinutesWatched", "averageViewDuration",
           "averageViewPercentage", "subscribersGained", "likes", "comments", "shares"]


class _Exec:
    def __init__(self, data, log, kw):
        self.data, self.log, self.kw = data, log, kw

    def execute(self):
        self.log.append(self.kw)
        return self.data(self.kw) if callable(self.data) else self.data


class FakeAnalytics:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def reports(self):
        return self

    def query(self, **kw):
        return _Exec({"columnHeaders": [{"name": h} for h in HEADERS], "rows": self.rows},
                     self.calls, kw)


class FakeData:
    def __init__(self, titles):
        self.titles, self.calls = titles, []

    def videos(self):
        return self

    def list(self, **kw):
        def page(kw):
            return {"items": [{"id": i, "snippet": {"title": self.titles[i],
                                                    "publishedAt": "2026-10-16T00:00:00Z"}}
                              for i in kw["id"].split(",") if i in self.titles]}
        return _Exec(page, self.calls, kw)


ROWS = [  # real numbers of three 2026-10-24 review videos
    ["iDFPStlkG0c", 1188, 157, 18, 67.2, 2, 41, 0, 0],
    ["_MMy_H7XxcQ", 777, 342, 45, 72.33, 16, 39, 1, 4],
    ["vp7NcbIS84o", 1130, 82, 13, 44.17, 0, 4, 0, 0],
    ["old_csv_vid", 2, 20, 628, 99.9, 0, 0, 0, 0],
]
TITLES = {"iDFPStlkG0c": "Why Pilots Train To Black Out On Purpose",
          "_MMy_H7XxcQ": "Sound Waves That Levitate Objects (It's Real)",
          "vp7NcbIS84o": "This White Redwood Can't Feed Itself",
          "old_csv_vid": "Scientists Shocked by Warp Drive"}


def _world(tmp_path):
    stories, build, batches = tmp_path / "stories", tmp_path / "build", tmp_path / "build/batches"
    for sid, tid in (("t_pilots", "t_centrifuge"), ("t_levitate", "t_sound_lev"),
                     ("t_ghost_tree", "t_ghost"), ("t_handmade", None)):
        (stories / sid).mkdir(parents=True)
        (stories / sid / "story.json").write_text(json.dumps(
            {"story_id": sid, **({"topic_id": tid} if tid else {})}))
    for sid, title in (("t_pilots", "Why Pilots Train To Black Out On Purpose"),
                       ("t_levitate", "Sound Waves That Levitate Objects (It's Real)"),
                       ("t_ghost_tree", "Some Other Title Entirely")):
        (build / sid).mkdir(parents=True)
        (build / sid / "manifest.json").write_text(json.dumps(
            {"video_id": sid, "metadata": {"title": title}}))
    # ghost tree's upload id was recorded by the batch (title on YouTube differs)
    (batches / "live_1").mkdir(parents=True)
    (batches / "live_1" / "batch_report.json").write_text(json.dumps({"rows": [
        {"story": "t_ghost_tree", "package": {"youtube": {"video_id": "vp7NcbIS84o"}}},
        {"story": "t_failed", "package": {"youtube": None}}]}))
    hist = tmp_path / "topic_history.jsonl"
    rows = [
        {"id": "t_centrifuge", "title": "A Centrifuge Spins Astronaut Trainees", "cluster":
         "exotic_space_travel", "status": "queued", "source": "topic_ideate", "score": 68},
        {"id": "t_sound_lev", "title": "Sound Waves Can Levitate", "cluster": "spectacle_physics",
         "status": "duplicate", "source": "topic_ideate", "reason": "x"},
        {"id": "t_sound_lev", "title": "Sound Waves Can Levitate", "cluster": "spectacle_physics",
         "status": "queued", "source": "topic_ideate", "score": 82},
        {"id": "t_sound_lev", "title": "Sound Waves Again", "cluster": "spectacle_physics",
         "status": "duplicate", "source": "topic_ideate", "reason": "y"},
        {"id": "t_ghost", "title": "Ghost trees", "cluster": "general_explainer",
         "status": "queued", "source": "topic_ideate", "score": 70},
        {"id": "yt_x", "title": "Old", "cluster": None, "status": "published",
         "source": "channel_csv", "views": 5},
    ]
    hist.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return dict(stories_dir=stories, build_dir=build, batches_dir=batches, history_path=hist)


def _run(tmp_path, **kw):
    w = _world(tmp_path)
    svc = (FakeAnalytics(ROWS), FakeData(TITLES))
    rep = F.run(services=svc, today=dt.date(2026, 10, 24), **w, **kw)
    return rep, w, svc


def test_query_uses_the_proven_analytics_shape(tmp_path):
    rep, _, (an, data) = _run(tmp_path, dry_run=True)
    q = an.calls[0]
    assert q["ids"] == "channel==MINE" and q["dimensions"] == "video"
    assert q["metrics"] == ("views,estimatedMinutesWatched,averageViewDuration,"
                            "averageViewPercentage,subscribersGained,likes,comments,shares")
    assert q["startDate"] == "2026-09-26" and q["endDate"] == "2026-10-24"
    assert rep["window"] == "2026-09-26..2026-10-24"
    assert set(data.calls[0]["id"].split(",")) == {r[0] for r in ROWS}


def test_matches_by_batch_report_first_then_title(tmp_path):
    rep, _, _ = _run(tmp_path, dry_run=True)
    by = {m["video_id"]: m for m in rep["matches"]}
    assert by["vp7NcbIS84o"]["matched_by"] == "batch_report"
    assert by["vp7NcbIS84o"]["topic_id"] == "t_ghost"
    assert by["iDFPStlkG0c"]["matched_by"] == "title"
    assert by["_MMy_H7XxcQ"]["topic_id"] == "t_sound_lev"
    assert {u["video_id"] for u in rep["unmatched"]} == {"old_csv_vid"}


def test_writes_real_fields_onto_the_queued_row_without_breaking_schema(tmp_path):
    rep, w, _ = _run(tmp_path)
    rows = [json.loads(x) for x in w["history_path"].read_text().splitlines()]
    assert len(rows) == 6 and rep["updated_rows"] == 3 and not rep["dry_run"]
    lev = rows[2]                                   # the queued t_sound_lev row, not a duplicate
    assert lev["status"] == "queued" and lev["score"] == 82          # existing fields intact
    assert lev["real_views"] == 777 and lev["real_retention_pct"] == 72.33
    assert lev["real_subs_gained"] == 16 and lev["real_shares"] == 4
    assert lev["real_avg_view_s"] == 45 and lev["real_minutes_watched"] == 342
    assert lev["real_video_id"] == "_MMy_H7XxcQ" and lev["real_story_id"] == "t_levitate"
    assert lev["real_window"] == "2026-09-26..2026-10-24" and lev["real_updated_at"]
    assert not any(k.startswith("real_") for k in rows[1]) and \
        not any(k.startswith("real_") for k in rows[3])
    assert rows[0]["real_retention_pct"] == 67.2 and rows[4]["real_retention_pct"] == 44.17
    assert rows[5] == {"id": "yt_x", "title": "Old", "cluster": None, "status": "published",
                       "source": "channel_csv", "views": 5}


def test_dry_run_writes_nothing(tmp_path):
    w = _world(tmp_path)
    original = w["history_path"].read_text()
    F.run(services=(FakeAnalytics(ROWS), FakeData(TITLES)), today=dt.date(2026, 10, 24),
          dry_run=True, **w)
    assert w["history_path"].read_text() == original


def test_rerun_is_idempotent(tmp_path):
    w = _world(tmp_path)
    for _ in range(2):
        F.run(services=(FakeAnalytics(ROWS), FakeData(TITLES)), today=dt.date(2026, 10, 24), **w)
    rows = [json.loads(x) for x in w["history_path"].read_text().splitlines()]
    assert len(rows) == 6 and rows[2]["real_views"] == 777


def test_ambiguous_title_and_storyless_topic_are_reported_not_guessed(tmp_path):
    w = _world(tmp_path)
    (w["build_dir"] / "dup").mkdir()
    (w["build_dir"] / "dup" / "manifest.json").write_text(json.dumps(
        {"video_id": "t_other", "metadata": {"title": "why pilots train to black out, on purpose"}}))
    titles = {**TITLES, "old_csv_vid": "David's Marble"}
    (w["build_dir"] / "marble").mkdir()
    (w["build_dir"] / "marble" / "manifest.json").write_text(json.dumps(
        {"video_id": "t_handmade", "metadata": {"title": "David's Marble"}}))
    rep = F.run(services=(FakeAnalytics(ROWS), FakeData(titles)), today=dt.date(2026, 10, 24),
                dry_run=True, **w)
    reasons = {u["video_id"]: u["reason"] for u in rep["unmatched"]}
    assert "shared by stories" in reasons["iDFPStlkG0c"]
    assert "no topic_id" in reasons["old_csv_vid"]


def test_rows_appended_during_the_run_are_kept(tmp_path, monkeypatch):
    w = _world(tmp_path)
    late = {"id": "t_new", "title": "Appended by a running batch", "status": "queued"}
    real_apply = F.apply_to_history

    def apply_then_append(*a, **k):
        out = real_apply(*a, **k)
        with w["history_path"].open("a") as f:
            f.write(json.dumps(late) + "\n")
        return out
    monkeypatch.setattr(F, "apply_to_history", apply_then_append)
    rep = F.run(services=(FakeAnalytics(ROWS), FakeData(TITLES)), today=dt.date(2026, 10, 24), **w)
    rows = [json.loads(x) for x in w["history_path"].read_text().splitlines()]
    assert rep["late_rows_kept"] == 1 and rows[-1] == late and rows[2]["real_views"] == 777


def test_non_append_change_during_run_aborts(tmp_path):
    w = _world(tmp_path)
    lines = F.read_history_lines(w["history_path"])
    w["history_path"].write_text("{}\n")
    try:
        F.write_history(w["history_path"], [{}], lines)
    except RuntimeError as e:
        assert "changed underneath" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_cli_entry_point(tmp_path, monkeypatch, capsys):
    w = _world(tmp_path)
    monkeypatch.setattr(F, "build_services", lambda *a, **k: (FakeAnalytics(ROWS),
                                                              FakeData(TITLES)))
    monkeypatch.setattr(F, "_defaults", lambda: (w["history_path"], w["stories_dir"]))
    monkeypatch.setattr(F, "BATCHES_DIR", w["batches_dir"])
    monkeypatch.setattr(F, "BUILD_V16", w["build_dir"])
    monkeypatch.setattr(F.run, "__kwdefaults__",
                        {**F.run.__kwdefaults__, "batches_dir": w["batches_dir"],
                         "build_dir": w["build_dir"]})
    assert F.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "3 matched to topics, 3 topic_history rows would be updated" in out
    assert "_MMy_H7XxcQ" in out and "unmatched old_csv_vid" in out
