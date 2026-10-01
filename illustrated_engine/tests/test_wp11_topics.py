"""WP11 — topic engine: clusters, ideation, dedupe, scoring, series planner,
`data/topic_history.jsonl` (engine/v16_topics.py, DESIGN §9).

Run: python3 tests/test_wp11_topics.py   (exit 0 = all passed; fake `ask`, no network, no LLM)
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
REPO = ROOT.parent                              # video_engine
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

from engine import v16_topics as T  # noqa: E402
from llm import client  # noqa: E402
from llm.prompts import render  # noqa: E402

CHANNEL_CSV = REPO / "research" / "phase2" / "channel_videos.csv"
STORIES_DIR = ROOT / "stories"


# -------------------------------------------------------- tokens/slugify --

def test_key_terms_drops_stopwords_and_short_tokens():
    assert T.key_terms("The Blood Falls in Antarctica") == {"blood", "falls", "antarctica"}
    assert T.key_terms("Why Time Moves Slower Near Black Holes") == \
        {"time", "moves", "slower", "black", "holes"}          # "near" is a stopword
    assert T.key_terms("") == set()


def test_slugify_is_stable_and_bounded():
    assert T.slugify("The Blast With No Crater") == "t_the_blast_with_no_crater"
    assert T.slugify("A" * 100).startswith("t_")
    assert len(T.slugify("A" * 100)) <= 42


def test_unique_id_disambiguates_collisions():
    seen = {"t_x"}
    assert T._unique_id("t_x", seen) == "t_x_2"
    seen.add("t_x_2")
    assert T._unique_id("t_x", seen) == "t_x_3"


# -------------------------------------------------------------- dedupe --

def test_entity_jaccard_and_claim_overlap_math():
    assert T.entity_jaccard({"a", "b"}, {"a", "b", "c"}) == 2 / 3
    assert T.entity_jaccard(set(), {"a"}) == 0.0
    # containment, not union: a short claim fully inside a longer one is 1.0
    assert T.claim_overlap({"a", "b"}, {"a", "b", "c", "d"}) == 1.0
    assert T.claim_overlap(set(), {"a"}) == 0.0


def test_dedupe_against_real_channel_csv_fixtures():
    """Fixtures come from the real channel CSV (DESIGN §9.2), not synthetic data."""
    history = T.seed_from_channel_csv(CHANNEL_CSV)
    assert history, "channel CSV fixture is required for this test"
    titles = {h["title"] for h in history}
    assert "Blood Falls in Antarctica" in titles

    near_dup = {"id": "t_new1", "title": "Why Blood Falls In Antarctica Stains The Ice Red",
                "claim": "Blood Falls in Antarctica stains ice red with iron-rich water"}
    distinct = {"id": "t_new2", "title": "The Mathematics of a Perfect Soap Bubble",
                "claim": "Soap bubbles always form the shape that minimises surface area"}

    unique, dupes = T.dedupe([near_dup, distinct], history)
    assert [c["id"] for c in unique] == ["t_new2"]
    assert [c["id"] for c in dupes] == ["t_new1"]
    assert "entity overlap" in dupes[0]["duplicate_reason"]


def test_dedupe_series_exception_bypasses_entity_overlap():
    history_row = {"id": "h1", "entities": ["blast", "siberia", "forest"], "series_id": "s_blast"}
    same_series = {"title": "x", "entities": {"subject": "blast forest siberia"},
                   "series_id": "s_blast"}
    assert T.is_duplicate(same_series, history_row) is None        # series exception
    other_series = {**same_series, "series_id": "s_other"}
    assert T.is_duplicate(other_series, history_row) is not None   # same entities, no exception


# ---------------------------------------------------------------- score --

def test_score_candidate_is_reproducible_and_matches_the_weighted_sum():
    cand = {"cluster": "deep_time", "evergreen": True}
    row = {"counter_intuitive": 5, "visualisability": 5, "hook_strength": 5,
           "series_potential": 5, "evidence_strength": 5}
    score1, breakdown1 = T.score_candidate(cand, row)
    score2, breakdown2 = T.score_candidate(cand, row)
    assert score1 == score2 == 100 and breakdown1 == breakdown2        # same inputs -> same output
    assert breakdown1 == {"cluster_prior": 25.0, "counter_intuitive": 20.0,
                           "visualisability": 15.0, "hook_strength": 15.0,
                           "series_potential": 10.0, "evidence_strength": 10.0, "evergreen": 5.0}


def test_score_candidate_excluded_cluster_scores_zero():
    cand = {"cluster": "crypto"}
    row = dict.fromkeys(["counter_intuitive", "visualisability", "hook_strength",
                         "series_potential", "evidence_strength"], 5)
    score, breakdown = T.score_candidate(cand, row)
    assert score == 0 and breakdown["excluded_cluster"] is True


def test_score_candidate_partial_rubric_is_below_threshold():
    cand = {"cluster": "general_explainer", "evergreen": False}
    row = dict.fromkeys(["counter_intuitive", "visualisability", "hook_strength",
                         "series_potential", "evidence_strength"], 2)
    score, _ = T.score_candidate(cand, row)
    assert score < T.MIN_SCORE


# ------------------------------------------------------- series planner --

def test_plan_series_groups_valid_pairs_and_triples():
    a = {"id": "a", "series_id": "s1", "series_part": 1, "score": 70}
    b = {"id": "b", "series_id": "s1", "series_part": 2, "score": 80}
    c = {"id": "c", "series_id": None, "score": 90}
    groups, standalone = T.plan_series([a, b, c])
    assert len(groups) == 1 and [p["id"] for p in groups[0]["parts"]] == ["a", "b"]
    assert [s["id"] for s in standalone] == ["c"]


def test_plan_series_demotes_invalid_groupings():
    solo = {"id": "a", "series_id": "s1", "series_part": 1}
    quad = [{"id": f"q{i}", "series_id": "s2", "series_part": i} for i in range(4)]
    dup_part = [{"id": "d1", "series_id": "s3", "series_part": 1},
                {"id": "d2", "series_id": "s3", "series_part": 1}]
    groups, standalone = T.plan_series([solo, *quad, *dup_part])
    assert groups == []
    assert len(standalone) == 1 + 4 + 2
    assert all(s["series_id"] is None for s in standalone)


# ----------------------------------------------------------- LLM calls --

class Fake:
    """Queue of responses per stage; records prompts (same shape as the other WP tests)."""

    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}
        self.prompts = []

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        self.prompts.append((stage, prompt))
        item = self.q[stage].pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(data=item, model="fake", cached=False, attempts=1, usage={})


def _cand(i, cluster="deep_time", series_id=None, series_part=None):
    return {"title": f"Topic number {i} about ancient rock formations",
            "cluster": cluster, "claim": f"claim number {i} about ancient rock formations",
            "entities": {"subject": f"rock{i}", "place": "", "era": "", "phenomenon": ""},
            "hooks": [f"hook {i} a", f"hook {i} b", f"hook {i} c"],
            "templates": ["BIG_NUMBER"], "series_id": series_id, "series_part": series_part,
            "evergreen": True}


def test_ideate_assigns_stable_unique_ids():
    raw = [_cand(1), {**_cand(2), "id": "t_the_blast_with_no_crater"},
           {**_cand(3), "id": "t_the_blast_with_no_crater"}]      # id collision
    f = Fake(topic_ideate=[{"candidates": raw}])
    out = T.ideate(3, ask=f)
    ids = [c["id"] for c in out]
    assert len(ids) == len(set(ids)) == 3
    assert ids[1] == "t_the_blast_with_no_crater"
    assert ids[2] == "t_the_blast_with_no_crater_2"


def test_score_candidates_annotates_every_candidate():
    cands = [{**_cand(1), "id": "t_1"}, {**_cand(2), "id": "t_2"}]
    row = {"counter_intuitive": 4, "visualisability": 4, "hook_strength": 4,
           "series_potential": 4, "evidence_strength": 4, "best_hook": "the strongest hook"}
    f = Fake(topic_score=[{"scores": [{"id": "t_1", **row}, {"id": "t_2", **row}]}])
    out = T.score_candidates(cands, ask=f)
    assert [c["score"] for c in out] == [86, 86]
    assert all(c["best_hook"] == "the strongest hook" for c in out)


def test_score_candidates_raises_on_omitted_id():
    cands = [{**_cand(1), "id": "t_1"}]
    f = Fake(topic_score=[{"scores": []}])
    try:
        T.score_candidates(cands, ask=f)
    except ValueError as e:
        assert "t_1" in str(e)
    else:
        raise AssertionError("expected ValueError for an omitted candidate id")


# ------------------------------------------------- build_queue end-to-end --

def test_build_queue_20_candidates_no_duplicate_of_existing_uploads(tmp_path):
    """DESIGN §15.2 WP11 acceptance: 20 candidates -> ranked queue, no duplicate
    of an existing upload. History seeded from the real channel CSV + V15 stories."""
    history_path = tmp_path / "topic_history.jsonl"
    seed_rows = T.seed_from_channel_csv(CHANNEL_CSV) + T.seed_from_v15_stories(STORIES_DIR)
    assert len(seed_rows) >= 20, "need real channel/story data for this acceptance test"
    T.append_history(seed_rows, history_path)

    raw = [_cand(i) for i in range(20)]
    raw[0] = {**raw[0], "title": "Blood Falls in Antarctica",
              "claim": "Blood Falls in Antarctica stains ice red",
              "entities": {"subject": "blood falls", "place": "antarctica", "era": "", "phenomenon": ""}}
    ideate_resp = {"candidates": raw}
    good_row = {"counter_intuitive": 4, "visualisability": 4, "hook_strength": 4,
                "series_potential": 3, "evidence_strength": 4, "best_hook": "a strong hook"}
    scores = {"scores": [{"id": T.slugify(c["title"]) if "id" not in c else c["id"], **good_row}
                         for c in raw]}
    # `ideate` assigns ids before `score_candidates` runs; mirror that id assignment here.
    assigned_ids, seen = [], set()
    for c in raw:
        cid = T._unique_id(c.get("id") or T.slugify(c["title"]), seen)
        seen.add(cid)
        assigned_ids.append(cid)
    scores = {"scores": [{"id": cid, **good_row} for cid in assigned_ids]}

    f = Fake(topic_ideate=[ideate_resp], topic_score=[scores])
    result = T.build_queue(n=20, history_path=history_path, ask=f, persist=True)

    assert result["raw_count"] == 20
    dup_titles = {d["title"] for d in result["duplicates"]}
    assert "Blood Falls in Antarctica" in dup_titles

    def flat_titles(queue):
        for e in queue:
            yield from ([p["title"] for p in e["parts"]] if "parts" in e else [e["title"]])

    queue_titles = list(flat_titles(result["queue"]))
    assert queue_titles, "expected a non-empty ranked queue"
    history_titles = {h["title"] for h in seed_rows}
    assert not (set(queue_titles) & history_titles)

    scores_seen = [e["score"] if "score" in e else max(p["score"] for p in e["parts"])
                   for e in result["queue"]]
    assert scores_seen == sorted(scores_seen, reverse=True)
    assert all(s >= T.MIN_SCORE for s in scores_seen)

    grown = T.load_history(history_path)
    assert len(grown) > len(seed_rows)                      # dupes/rejected/queued all persisted


# ------------------------------------------------------- real seed data --

def test_seed_from_channel_csv_matches_the_real_csv():
    import csv
    rows = T.seed_from_channel_csv(CHANNEL_CSV)
    with open(CHANNEL_CSV, newline="") as fh:
        csv_rows = sum(1 for r in csv.DictReader(fh) if (r.get("title") or "").strip())
    assert len(rows) == csv_rows and len(rows) > 50
    assert all(r["status"] == "published" and r["source"] == "channel_csv" for r in rows)
    assert all(r["entities"] for r in rows)                 # title key-terms fallback


def test_seed_from_v15_stories_reads_real_story_packs():
    rows = T.seed_from_v15_stories(STORIES_DIR)
    assert len(rows) >= 10
    assert all(r["source"] == "v15_story" and r["title"] for r in rows)


# ------------------------------------------------------- prompts/schemas --

def test_prompts_render_and_schemas_are_valid():
    prompt, ver = render("topic_ideate", clusters="- deep_time (prior 1.00)", n=20, avoid_titles="(none)")
    assert ver and "{{" not in prompt
    jsonschema.Draft202012Validator.check_schema(client.load_schema("topic_ideate"))

    prompt, ver = render("topic_score", candidates="id: t_1\ntitle: x")
    assert ver and "{{" not in prompt
    jsonschema.Draft202012Validator.check_schema(client.load_schema("topic_score"))

    good_candidate = {"candidates": [{
        "title": "A sufficiently long candidate title", "cluster": "deep_time",
        "claim": "a claim sentence of at least twenty characters",
        "entities": {"subject": "x", "place": "y", "era": "z", "phenomenon": "w"},
        "hooks": ["hook one", "hook two", "hook three"], "templates": ["BIG_NUMBER"],
        "series_id": None, "series_part": None, "evergreen": True}]}
    jsonschema.validate(good_candidate, client.load_schema("topic_ideate"))

    good_score = {"scores": [{"id": "t_1", "counter_intuitive": 4, "visualisability": 4,
                              "hook_strength": 4, "series_potential": 4, "evidence_strength": 4,
                              "best_hook": "the chosen hook"}]}
    jsonschema.validate(good_score, client.load_schema("topic_score"))


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                if "tmp_path" in inspect.signature(fn).parameters:
                    import tempfile
                    with tempfile.TemporaryDirectory() as d:
                        fn(Path(d))
                else:
                    fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {e!r}"[:400])
    print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)
