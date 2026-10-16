"""2026-10-16 zero-publish day, research/topic funnel:

  - research sources were searched with the curiosity-gap TITLE: "The
    Burgess Shale Froze an Explosion of Alien-Looking Animal Life" -> 0
    Wikipedia articles, "...Grand Canyon ... Blink of an Eye" -> Manhattan +
    Los_Angeles_River (every claim then dropped off-subject), glass-rain
    planet -> 1, magnetar -> 1. Now entities.subject is searched first.
  - select_topics asked for max(2n, n+5) raw topics; at today's ~1/3
    dedupe+score yield that queued 0-3, so slots got 1-2 topics instead of
    MAX_TOPICS_PER_SLOT=3.

Run: python3 -m pytest -q tests/test_research_funnel_20261016.py   (no network)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_autostory as A  # noqa: E402
from engine import v16_batch as B  # noqa: E402
from engine import v16_sources as SRC  # noqa: E402

BURGESS = {"id": "t_burgess", "cluster": "deep_time",
           "title": "The Burgess Shale Froze an Explosion of Alien-Looking Animal Life",
           "entities": {"subject": "Burgess Shale fossils", "place": "British Columbia",
                        "era": "Cambrian Period", "phenomenon": "evolutionary explosion"}}

# what Wikipedia search returned live on 2026-10-16 for these queries
LIVE_SEARCH = {
    BURGESS["title"]: [],
    "Burgess Shale fossils": ["Fossils of the Burgess Shale", "Burgess Shale", "Hallucigenia"],
    "Burgess Shale fossils evolutionary explosion": ["Cambrian explosion", "Burgess Shale"],
}


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _fake_wiki(monkeypatch, search=LIVE_SEARCH, empty=()):
    calls = []

    def get(url, params=None, timeout=None, headers=None):
        if "srsearch" in params:
            calls.append(params["srsearch"])
            hits = search.get(params["srsearch"], [])[:params["srlimit"]]
            return _Resp({"query": {"search": [{"title": t} for t in hits]}})
        t = params["titles"]
        return _Resp({"query": {"pages": {"1": {"extract": "" if t in empty
                                                 else f"Article text about {t}."}}}})
    monkeypatch.setattr(SRC.requests, "get", get)
    return calls


def test_queries_lead_with_the_candidate_subject():
    assert SRC.source_queries(BURGESS) == [
        "Burgess Shale fossils", "Burgess Shale fossils evolutionary explosion",
        BURGESS["title"]]
    # no entities -> title only, as before
    assert SRC.source_queries({"title": "Topic"}) == ["Topic"]


def test_burgess_shale_now_finds_on_subject_sources(monkeypatch):
    assert SRC.wikipedia_sources.__name__  # old entry point still exists
    _fake_wiki(monkeypatch)
    assert len(SRC.wikipedia_sources(BURGESS["title"])) == 0     # the live hold
    out = SRC.candidate_sources(BURGESS, 3)
    urls = [s["url"].rsplit("/", 1)[1] for s in out]
    # round-robin: best hit of each entity query first, no duplicates
    assert urls == ["Fossils_of_the_Burgess_Shale", "Cambrian_explosion", "Burgess_Shale"]
    assert [s["id"] for s in out] == ["wiki_1", "wiki_2", "wiki_3"]


def test_title_hits_only_fill_remaining_slots(monkeypatch):
    search = {"magnetar": ["Magnetar"], "Magnetar Hard Drive": ["2020 in science"]}
    _fake_wiki(monkeypatch, search)
    out = SRC.candidate_sources({"title": "Magnetar Hard Drive",
                                 "entities": {"subject": "magnetar"}}, 3)
    assert [s["url"].rsplit("/", 1)[1] for s in out] == ["Magnetar", "2020_in_science"]


def test_empty_extract_falls_through_to_next_article(monkeypatch):
    _fake_wiki(monkeypatch, empty={"Cambrian explosion"})
    out = SRC.candidate_sources(BURGESS, 3)
    assert [s["url"].rsplit("/", 1)[1] for s in out] == [
        "Fossils_of_the_Burgess_Shale", "Burgess_Shale", "Hallucigenia"]


def test_autostory_default_uses_candidate_sources(monkeypatch):
    seen = []
    monkeypatch.setattr(A, "candidate_sources", lambda c, n: seen.append(c["id"]) or [])
    res = A.generate_story_ranked([BURGESS])
    assert seen == ["t_burgess"] and res["status"] == "hold"
    assert "need >= 2" in res["reason"]          # MIN_SOURCES bar unchanged


def test_injected_fetch_sources_keeps_title_contract():
    got = []
    A.generate_story(BURGESS, fetch_sources=lambda q, n: got.append((q, n)) or [])
    assert got == [(BURGESS["title"], 3)]


def test_raw_topic_headroom_fills_three_topics_per_slot():
    # at the measured ~1/3 raw->queued yield: >= 2 queued topics per slot
    # (the old max(2n, n+5) gave < 1 per slot for n=3: 8 raw -> ~2.7 queued)
    for n in (1, 3, 5):
        assert B.raw_topic_count(n) / 3 >= 2 * n, n
        assert max(2 * n, n + 5) / 3 < 2 * n or n == 1
    assert B.raw_topic_count(3) == 18
    assert B.raw_topic_count(10) == B.RAW_TOPICS_MAX == 40   # topic_ideate schema maxItems


def test_select_topics_requests_the_new_headroom(monkeypatch, tmp_path):
    asked = {}
    import engine.v16_topics as T

    def fake_build_queue(*, n, history_path, ask):
        asked["n"] = n
        return {"queue": [], "raw_count": 0}
    monkeypatch.setattr(T, "build_queue", fake_build_queue)
    B.select_topics(3, history_path=tmp_path / "h.jsonl")
    assert asked["n"] == 18          # was max(2n, n+5) = 8
