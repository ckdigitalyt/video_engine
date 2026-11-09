"""2026-11-09: re-runnable competitor trend snapshot (engine/v16_trends.py),
replicating the 2026-10-26 study's per-channel, age-adjusted method.
Fake YouTube Data client only -- no network.
"""
import datetime as dt
import json
import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_trends as TR  # noqa: E402

NOW = dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc)


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeYT:
    """channels/playlistItems/videos for synthetic channels: {cid: (subs, [video dicts])}."""

    def __init__(self, chans):
        self.chans, self.calls = chans, []

    def channels(self):
        return self

    def playlistItems(self):
        return self

    def videos(self):
        return self

    def list(self, **kw):
        self.calls.append(kw)
        if "playlistId" in kw:
            vids = self.chans[kw["playlistId"][2:]][1]
            return _Req(lambda: {"items": [{"contentDetails": {"videoId": v["id"]}}
                                           for v in vids[:kw["maxResults"]]]})
        if kw.get("part", "").startswith("snippet,statistics"):
            cid = kw["id"]
            if cid not in self.chans:
                return _Req(lambda: {"items": []})
            return _Req(lambda: {"items": [{
                "id": cid, "snippet": {"title": cid},
                "statistics": {"subscriberCount": str(self.chans[cid][0])},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid}}}]})
        ids = set(kw["id"].split(","))
        allv = {v["id"]: v for _, vs in self.chans.values() for v in vs}
        return _Req(lambda: {"items": [{
            "id": i, "snippet": {"title": allv[i]["title"], "publishedAt": allv[i]["pub"]},
            "contentDetails": {"duration": allv[i]["dur"]},
            "statistics": {"viewCount": str(allv[i]["views"]),
                           "likeCount": str(allv[i]["views"] // 50)}} for i in ids]})


def _world(n_ch=6, per=30, scale_boost=2.0, seed=1):
    """Channels of very different sizes; views decay-in with age; scale
    titles get `scale_boost` x views."""
    rnd = random.Random(seed)
    chans, comps = {}, []
    for c in range(n_ch):
        cid = f"UC{c:022d}"
        level = 10 ** (3 + c)                     # 1K .. 100M: size must not swamp
        vids = []
        for i in range(per):
            age = 8 + i * 3
            scale = i % 3 == 0
            title = (f"Earth vs Jupiter size {i}" if scale else f"A strange fact number {i}")
            views = int(level * math.sqrt(age) * (scale_boost if scale else 1.0)
                        * math.exp(rnd.gauss(0, 0.3)))
            vids.append({"id": f"v{c}_{i}", "title": title, "views": views,
                         "dur": "PT35S" if i % 2 else "PT1M10S",
                         "pub": (NOW - dt.timedelta(days=age)).isoformat().replace("+00:00", "Z")})
        vids.append({"id": f"v{c}_long", "title": "long video", "views": 5, "dur": "PT12M",
                     "pub": (NOW - dt.timedelta(days=20)).isoformat()})
        vids.append({"id": f"v{c}_new", "title": "fresh", "views": 5, "dur": "PT30S",
                     "pub": (NOW - dt.timedelta(days=2)).isoformat()})
        chans[cid] = (level, vids)
        comps.append((cid, f"Chan{c}", "analog"))
    return FakeYT(chans), comps


def test_competitor_panel_is_the_2026_10_26_eighteen():
    assert len(TR.COMPETITORS) == 18
    assert len({c[0] for c in TR.COMPETITORS}) == 18
    assert all(c[0].startswith("UC") and len(c[0]) == 24 for c in TR.COMPETITORS)
    assert sum(g == "analog" for *_, g in TR.COMPETITORS) == 8


def test_iso_duration():
    assert TR.iso_duration_s("PT35S") == 35
    assert TR.iso_duration_s("PT1M10S") == 70
    assert TR.iso_duration_s("PT1H2M3S") == 3723
    assert TR.iso_duration_s("P1DT1S") == 86401
    assert TR.iso_duration_s("bogus") == 0


def test_mann_whitney_p_sane():
    assert TR.mann_whitney_p([1, 2, 3], []) == 1.0
    assert TR.mann_whitney_p([1.0] * 20, [1.0] * 20) == 1.0
    assert TR.mann_whitney_p(list(range(30, 60)), list(range(0, 30))) < 1e-6
    assert TR.mann_whitney_p([1, 3, 5, 7], [2, 4, 6, 8]) > 0.5


def test_residuals_remove_channel_size_and_age():
    yt, comps = _world(scale_boost=1.0)
    rep = TR.run(yt=yt, competitors=comps, dry_run=True, now=NOW)
    assert rep["n_shorts"] == 6 * 30                 # long and <7-day videos filtered out
    assert rep["age_slope"] == pytest.approx(0.5, abs=0.1)     # views ~ sqrt(age)
    sc = next(f for f in rep["findings"] if f["feature"] == "scale_comparison")
    assert sc["verdict"] != "supported" and abs(math.log(sc["multiplier"])) < 0.2


def test_detects_a_real_cross_channel_effect():
    yt, comps = _world(scale_boost=2.0)
    rep = TR.run(yt=yt, competitors=comps, dry_run=True, now=NOW)
    sc = next(f for f in rep["findings"] if f["feature"] == "scale_comparison")
    assert sc["multiplier"] == pytest.approx(2.0, rel=0.2)
    assert sc["p"] < 0.01 and sc["channels_agree"] == sc["channels_tested"] == 6
    assert sc["verdict"] == "supported"
    assert rep["findings"][0]["feature"] == "scale_comparison"       # supported sorts first


def test_writes_timestamped_aggregate_json_and_how_to_use(tmp_path):
    yt, comps = _world()
    out = tmp_path / "trend_signals.json"
    TR.run(yt=yt, competitors=comps, out=out, now=NOW)
    rep = json.loads(out.read_text())
    assert rep["generated_at"].startswith("2026-11-09")
    assert rep["how_to_use"] and any("Never add a gate" in s for s in rep["how_to_use"])
    assert "top_outliers" not in rep                                   # aggregates only
    assert "v0_1" not in out.read_text()                               # no video ids
    prof = {c["name"]: c for c in rep["channels"]}
    assert prof["Chan0"]["shorts_analysed"] == 30 and prof["Chan0"]["median_length_s"] > 0
    assert rep["baseline_2026_10_26"]["scale_comparison"]["multiplier"] == 1.63


def test_examples_flag_and_dry_run(tmp_path):
    yt, comps = _world()
    out = tmp_path / "t.json"
    rep = TR.run(yt=yt, competitors=comps, out=out, now=NOW, dry_run=True, examples=True)
    assert not out.exists()
    assert len(rep["top_outliers"]) == 10 and "title" in rep["top_outliers"][0]
    assert "outlier" in TR.format_report(rep)


def test_missing_or_failing_channel_is_reported_not_fatal():
    yt, comps = _world(n_ch=3)
    comps = comps + [("UCmissing_______________", "Gone", "analog")]
    rep = TR.run(yt=yt, competitors=comps, dry_run=True, now=NOW)
    gone = next(c for c in rep["channels"] if c["name"] == "Gone")
    assert gone["error"] == "channel not found" and gone["shorts_analysed"] == 0
    assert rep["n_channels"] == 3
    assert "Gone skipped" in TR.format_report(rep)


def test_quota_cost_is_about_three_units_per_channel():
    yt, comps = _world(n_ch=4, per=30)
    TR.run(yt=yt, competitors=comps, dry_run=True, now=NOW)
    assert len(yt.calls) == 4 * 3
