"""2026-11-11 review item 6: v16_feedback reads lifetime analytics (window
from the earliest publish date) and stores real_published_at; autoweight
drops rows whose window started after the publish date.

Fake YouTube clients, temp dirs. No network.
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import v16_autoweight as AW  # noqa: E402
from engine import v16_feedback as F  # noqa: E402
from test_feedback_20261024 import HEADERS, _Exec  # noqa: E402

TODAY = dt.date(2026, 11, 11)


class Analytics:
    """Window query -> 35 views for the old video; lifetime query -> 420."""

    def __init__(self):
        self.calls = []

    def reports(self):
        return self

    def query(self, **kw):
        def data(kw):
            lifetime = kw["startDate"] < "2026-10-14"
            views, ret = (420, 71.5) if lifetime else (35, 36.7)
            return {"columnHeaders": [{"name": h} for h in HEADERS],
                    "rows": [["oldvid", views, 1, 1, ret, 0, 0, 0, 0],
                             ["newvid", 300, 1, 1, 80.0, 0, 0, 0, 0]]}
        return _Exec(data, self.calls, kw)


class Data:
    PUB = {"oldvid": "2026-09-20T10:00:00Z", "newvid": "2026-11-01T10:00:00Z",
           "goneid": "2026-08-01T00:00:00Z"}

    def __init__(self):
        self.calls = []

    def videos(self):
        return self

    def list(self, **kw):
        def page(kw):
            return {"items": [{"id": i, "snippet": {"title": f"Title {i}",
                                                    "publishedAt": self.PUB[i]}}
                              for i in kw["id"].split(",") if i in self.PUB]}
        return _Exec(page, self.calls, kw)


def _world(tmp_path):
    stories, build, batches = tmp_path / "stories", tmp_path / "build", tmp_path / "b"
    batches.mkdir()
    rows = []
    for vid, tid in (("oldvid", "t_old"), ("newvid", "t_new")):
        (stories / tid).mkdir(parents=True)
        (stories / tid / "story.json").write_text(json.dumps({"story_id": tid,
                                                              "topic_id": tid}))
        (build / tid).mkdir(parents=True)
        (build / tid / "manifest.json").write_text(json.dumps(
            {"video_id": tid, "metadata": {"title": f"Title {vid}"}}))
        rows.append({"id": tid, "cluster": "deep_time", "status": "queued"})
    hist = tmp_path / "h.jsonl"
    hist.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return dict(stories_dir=stories, build_dir=build, batches_dir=batches,
                history_path=hist)


def test_earliest_publish():
    assert F.earliest_publish({"a": {"published_at": "2026-09-20T10:00:00Z"},
                               "b": {"published_at": "2026-11-01T00:00:00Z"},
                               "c": {"published_at": ""}}) == dt.date(2026, 9, 20)
    assert F.earliest_publish({}) is None


def test_old_video_gets_lifetime_numbers_and_publish_date(tmp_path):
    w = _world(tmp_path)
    an = Analytics()
    rep = F.run(services=(an, Data()), today=TODAY, days=28, autoweight=False, **w)
    assert [c["startDate"] for c in an.calls] == ["2026-10-14", "2026-09-20"]
    assert rep["window"] == "2026-09-20..2026-11-11"
    rows = {r["id"]: r for r in map(json.loads, w["history_path"].read_text().splitlines())}
    assert rows["t_old"]["real_views"] == 420
    assert rows["t_old"]["real_retention_pct"] == 71.5
    assert rows["t_old"]["real_published_at"] == "2026-09-20T10:00:00Z"
    assert not AW.truncated_window(rows["t_old"])


def test_known_history_ids_extend_the_lifetime_start(tmp_path):
    w = _world(tmp_path)
    with open(w["history_path"], "a") as f:
        f.write(json.dumps({"id": "t_gone", "cluster": "deep_time",
                            "real_video_id": "goneid"}) + "\n")
    an = Analytics()
    F.run(services=(an, Data()), today=TODAY, days=28, autoweight=False, dry_run=True, **w)
    assert an.calls[-1]["startDate"] == "2026-08-01"


def test_no_second_query_when_everything_is_inside_the_window(tmp_path):
    w = _world(tmp_path)
    an = Analytics()
    F.run(services=(an, Data()), today=TODAY, days=60, autoweight=False, dry_run=True, **w)
    assert len(an.calls) == 1


def test_truncated_window_rows_are_excluded_from_autoweight():
    base = {"cluster": "deep_time", "real_retention_pct": 36.7, "real_views": 400,
            "real_updated_at": "2026-11-11T00:00:00+00:00"}
    trunc = {**base, "real_video_id": "a", "real_window": "2026-10-14..2026-11-11",
             "real_published_at": "2026-09-20T10:00:00Z"}
    life = {**base, "real_video_id": "b", "real_window": "2026-09-20..2026-11-11",
            "real_published_at": "2026-09-20T10:00:00Z"}
    legacy = {**base, "real_video_id": "c", "real_window": "2026-10-14..2026-11-11"}
    assert AW.truncated_window(trunc)
    assert not AW.truncated_window(life) and not AW.truncated_window(legacy)
    samples, excluded = AW.video_samples([trunc, life, legacy])
    assert {s["video_id"] for s in samples} == {"b", "c"}
    assert excluded == {"truncated_window": 1}
