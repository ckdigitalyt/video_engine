"""Decision #13 item 5: topic-candidate -> real sources -> facts -> script ->
story.json (engine.v16_sources, engine.v16_autostory). No network, no real
LLM: `fetch_sources`/`ask` are both stubbed.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
REPO = ROOT.parent                              # video_engine
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v16_autostory as A  # noqa: E402
from engine import v16_sources as SRC  # noqa: E402


class Fake:
    """Queue of responses per stage; same shape as test_wp4_story.py's Fake."""

    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        item = self.q[stage].pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(data=item, model="fake", cached=False,
                               attempts=1, usage={})


SOURCE_TEXT = (
    "Witnesses reported a dazzling flash of light followed by a powerful "
    "wave of heat across the taiga. Near the epicenter a ring of trees "
    "remained standing while the surrounding forest was flattened for "
    "miles. The shockwave was recorded far from the site and no impact "
    "crater was ever found despite decades of searching."
)
GOOD_SOURCES = [{"id": "src1", "url": "https://en.wikipedia.org/wiki/Test",
                "text": SOURCE_TEXT},
               {"id": "src2", "url": "https://en.wikipedia.org/wiki/Test2",
                "text": "A second, unrelated corroborating source."}]
RESEARCH_CLAIMS = {"claims": [
    {"id": "f_witness", "claim": "Witnesses saw a bright flash and felt heat.",
     "quote": "witnesses reported a dazzling flash of light followed by a "
              "powerful wave of heat", "source_id": "src1", "nuance": "ESTABLISHED"},
    {"id": "f_treering", "claim": "A ring of trees near the center stayed standing.",
     "quote": "near the epicenter a ring of trees remained standing while "
              "the surrounding forest was flattened", "source_id": "src1",
     "nuance": "ESTABLISHED"},
    {"id": "f_shockwave", "claim": "The shockwave was detected with no crater found.",
     "quote": "the shockwave was recorded far from the site and no impact "
              "crater was ever found", "source_id": "src1", "nuance": "ESTABLISHED"},
]}
GOOD_SCRIPT = {
    "hook_headline": "The Silent Blast",
    "sentences": [
        {"text": "A forest can fall flat with no explosion ever reaching the ground.",
         "role": "hook", "fact_ids": ["f_witness"]},
        {"text": "Witnesses described a flash of light followed by a wave of "
                 "heat across the land.", "role": "normal", "fact_ids": ["f_witness"]},
        {"text": "Trees for a wide stretch were knocked down in a single "
                 "enormous blast.", "role": "normal", "fact_ids": ["f_treering"]},
        {"text": "Near the center a strange ring of trees stayed upright "
                 "while everything else fell outward.", "role": "normal",
         "fact_ids": ["f_treering"]},
        {"text": "Scientists who studied the site years later found no "
                 "crater anywhere in the debris field.", "role": "normal",
         "fact_ids": ["f_shockwave"]},
        {"text": "The lack of a crater pointed away from a ground impact "
                 "and toward something stranger.", "role": "normal",
         "fact_ids": ["f_shockwave"]},
        {"text": "Instruments on the far side of the world still registered "
                 "the shockwave rolling through the air.", "role": "normal",
         "fact_ids": ["f_witness"]},
        {"text": "The blast happened high above the forest, and that is "
                 "why the trees fell but the ground stayed whole.",
         "role": "payoff", "fact_ids": ["f_shockwave"]},
    ],
}
GOOD_CRITIC = {"scores": {"hook_strength": 5, "curiosity_gap": 5, "escalation": 5,
                          "payoff_clarity": 5, "loop_coherence": 5, "human_voice": 5,
                          "emotional_charge": 5, "one_idea_only": 5}, "critique": ""}
GOOD_META = {"title": "The Blast With No Crater", "title_fact_ids": ["f_shockwave"],
            "description": "A strange blast flattened a forest and left no crater.",
            "hashtags": ["#mystery", "#science", "#history"], "series_tag": "",
            "pinned_comment": "What do you think really happened?"}


def _fact_check_ok(n):
    return {"sentences": [{"n": i, "label": "supported"} for i in range(1, n + 1)]}


CANDIDATE = {"id": "t_1", "title": "The Blast With No Crater", "cluster": "deep_time"}


# --------------------------------------------------------- script_to_story --

def test_script_to_story_maps_roles_and_fact_ids():
    story_engine = {"script": GOOD_SCRIPT, "metadata": GOOD_META}
    story = A.script_to_story(CANDIDATE, story_engine)
    assert story["story_id"] == "t_the_blast_with_no_crater"
    assert story["title"] == "The Blast With No Crater"
    assert len(story["beats"]) == len(GOOD_SCRIPT["sentences"])
    assert story["beats"][0]["function"] == "HOOK"
    assert story["beats"][-1]["function"] == "PAYOFF"
    assert all(b["function"] == "NORMAL" for b in story["beats"][1:-1])
    assert story["beats"][0]["narration"] == GOOD_SCRIPT["sentences"][0]["text"]
    assert story["beats"][0]["fact_ids"] == ["f_witness"]


# ------------------------------------------------------------ generate_story --

def test_generate_story_holds_on_too_few_sources():
    res = A.generate_story(CANDIDATE, fetch_sources=lambda q, n: [GOOD_SOURCES[0]])
    assert res["status"] == "hold" and "source" in res["reason"]


def test_generate_story_holds_on_research_failure():
    f = Fake(research_extract=[{"claims": [RESEARCH_CLAIMS["claims"][0]]}])  # only 1, need 3
    res = A.generate_story(CANDIDATE, ask=f, fetch_sources=lambda q, n: GOOD_SOURCES)
    assert res["status"] == "hold" and "research" in res["reason"]


def test_generate_story_holds_on_script_failure():
    bad_script = {**GOOD_SCRIPT, "sentences": [
        {**GOOD_SCRIPT["sentences"][0], "role": "normal"},  # no hook role at all
        *GOOD_SCRIPT["sentences"][1:],
    ]}
    f = Fake(research_extract=[RESEARCH_CLAIMS], script_write=[bad_script, bad_script])
    res = A.generate_story(CANDIDATE, ask=f, fetch_sources=lambda q, n: GOOD_SOURCES)
    assert res["status"] == "hold" and "script" in res["reason"]


def test_generate_story_happy_path():
    f = Fake(research_extract=[RESEARCH_CLAIMS], script_write=[GOOD_SCRIPT],
            script_critic=[GOOD_CRITIC], fact_check=[_fact_check_ok(len(GOOD_SCRIPT["sentences"]))],
            metadata_pack=[GOOD_META])
    res = A.generate_story(CANDIDATE, ask=f, fetch_sources=lambda q, n: GOOD_SOURCES)
    assert res["status"] == "ok", res
    assert res["story"]["story_id"] == "t_the_blast_with_no_crater"
    assert len(res["story"]["beats"]) == 8


def test_write_story_dir_writes_story_json(tmp_path):
    story = {"story_id": "t_demo", "title": "Demo", "subject": "x", "beats": []}
    d = A.write_story_dir(story, stories_dir=tmp_path)
    assert (d / "story.json").exists()
    import json
    assert json.loads((d / "story.json").read_text())["story_id"] == "t_demo"


# ------------------------------------------------------------- v16_sources --

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_wikipedia_sources_happy_path(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        if params["action"] == "query" and "srsearch" in params:
            return _FakeResp({"query": {"search": [{"title": "Tunguska event"}]}})
        return _FakeResp({"query": {"pages": {"1": {"extract": "Some extract text."}}}})

    monkeypatch.setattr(SRC.requests, "get", fake_get)
    out = SRC.wikipedia_sources("tunguska", n=1)
    assert len(out) == 1
    assert out[0]["id"] == "wiki_1"
    assert out[0]["text"] == "Some extract text."
    assert out[0]["url"].endswith("Tunguska_event")


def test_wikipedia_sources_empty_on_network_failure(monkeypatch):
    import requests

    def raise_err(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr(SRC.requests, "get", raise_err)
    assert SRC.wikipedia_sources("anything") == []
