"""2026-11-11 review, item 1: topic dedupe blocked against the wrong rows and
matched too literally.

Evidence (108 live batches): of 920 duplicate matches, 872 were against
rows that were only ever "queued" (then held at research/script, never
rendered); only 24 against published videos. Ideation lost ~16 of ~18 raw
candidates per cycle (89%), leaving ~1.56 queued vs the 3 per slot the
topic-fallback chain assumes. Meanwhile plain-token Jaccard let
"fulgurite" through twice (published as JR53-E2EOio and yvjF7jSO8b4) and
"fossil" vs "fossilized" never matched. The fixtures below are the real
topic_history rows of those cases.

Run: python3 -m pytest tests/test_topic_dedupe_20261111.py -q
"""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v16_topics as T  # noqa: E402

DAY = 86400.0
NOW = 1794400000.0

# real rows (data/topic_history.jsonl lines 3519 and 4457)
FULGURITE_PUBLISHED = {
    "id": "t_a_lightning_strike_can_fuse_sand_into_gl",
    "title": "A Lightning Strike Can Fuse Sand Into Glass Branches Underground",
    "cluster": "spectacle_physics", "status": "queued", "source": "topic_ideate",
    "entities": ["fulgurite", "fused", "glass", "sand"],
    "claim_tokens": ["branching", "called", "fulgurites", "glass", "hitting", "instantly",
                     "lightning", "melt", "sand", "strike", "tubes"],
    "real_video_id": "JR53-E2EOio", "series_id": None}
FULGURITE_AGAIN = {
    "id": "t_a_lightning_strike_can_fuse_sand_into_a_",
    "title": "A Lightning Strike Can Fuse Sand Into a Glass Tube Underground",
    "cluster": "deep_time",
    "entities": ["fulgurite", "lightning-fused", "sand"],
    "claim": "A powerful lightning strike can instantly melt sand into a hollow glass "
             "tube preserved underground for centuries"}


def _row(i, status, *, ts=None, title=None, ents=None, **kw):
    r = {"id": f"t_row{i}", "title": title or f"Row {i}", "status": status,
         "source": "topic_ideate", "entities": ents or [f"subject{i}", "thing"],
         "claim_tokens": [f"subject{i}", "thing", "does", "stuff"], "series_id": None}
    if ts is not None:
        r["ts"] = T._utc_iso(ts)
    r.update(kw)
    return r


# ------------------------------------------------------------- stemming --

def test_stem_term_collapses_plural_tense_derivation_variants():
    for group in (["fossil", "fossils", "fossilized", "fossilised", "fossilization"],
                  ["petrified", "petrify", "petrification"],
                  ["raindrop", "raindrops"], ["galaxy", "galaxies"],
                  ["fuse", "fused"], ["strike", "striking", "strikes"],
                  ["mountain", "mountains"], ["appalachian", "appalachians"],
                  ["stop", "stopped"]):
        assert len({T.stem_term(w) for w in group}) == 1, group
    assert T.stem_term("glass") == "glass" and T.stem_term("gas") == "gas"


def test_norm_terms_splits_hyphens_and_drops_generic_filler():
    assert "fus" in T.norm_terms(["lightning-fused"])
    assert T.norm_terms(["ancient", "billion", "raindrops"]) == {"raindrop"}
    # an all-generic row is never emptied
    assert T.norm_terms(["ancient", "years"]) == {"ancient", "year"}


def test_fulgurite_repeat_is_now_a_duplicate():
    """Old matcher: 2/5 = 0.40 < 0.5 -> sailed through and was published again."""
    old = T.entity_jaccard(set(FULGURITE_AGAIN["entities"]),
                           set(FULGURITE_PUBLISHED["entities"]))
    assert old < T.DUP_ENTITY_JACCARD
    reason = T.is_duplicate(FULGURITE_AGAIN, FULGURITE_PUBLISHED)
    assert reason and "t_a_lightning_strike_can_fuse_sand_into_gl" in reason


def test_fossilized_raindrops_wording_variant_matches():
    published = _row(1, "published", title="Fossil Raindrops Reveal Ancient Air",
                     ents=["fossil", "raindrops", "imprints"])
    cand = {"title": "Fossilized Raindrop Imprints", "entities": ["fossilized", "raindrop",
                                                                  "imprint"]}
    assert T.is_duplicate(cand, published)


def test_short_seed_claim_does_not_swallow_every_galaxy_topic():
    seed = {"id": "yt_x", "title": "How Galaxies form - finally Revealed", "status": "published",
            "entities": ["galaxies", "form", "finally", "revealed"],
            "claim_tokens": ["galaxies", "form", "finally", "revealed"]}
    cand = {"title": "Astronomers Found a Galaxy That Formed Too Soon After the Big Bang",
            "entities": ["galaxy", "jwst", "redshift"],
            "claim": "A galaxy formed only 300 million years after the big bang"}
    assert T.is_duplicate(cand, seed) is None


# -------------------------------------------------- which rows may block --

def test_old_held_queued_rejected_and_duplicate_rows_no_longer_block():
    subj = ["volcano", "lightning", "ash"]
    hist = [_row(1, "queued", ts=NOW - 10 * DAY, ents=subj),     # held weeks ago
            _row(2, "rejected", ts=NOW - 1 * DAY, ents=subj),
            _row(3, "duplicate", ts=NOW - 1 * DAY, ents=subj),
            _row(4, "queued", ents=subj)]                        # legacy, no ts, not recent
    cand = {"id": "t_new", "title": "Volcanic Lightning", "entities": subj}
    unique, dupes = T.dedupe([cand], hist, now=NOW)
    assert [c["id"] for c in unique] == ["t_new"] and not dupes


def test_recent_queued_and_published_rows_block():
    subj = ["volcano", "lightning", "ash"]
    cand = {"id": "t_new", "title": "Volcanic Lightning", "entities": subj}
    for hist, kw in (([_row(1, "queued", ts=NOW - 1 * DAY, ents=subj)], {}),
                     ([_row(1, "queued", ents=subj)], {"recent_queued_ids": {"t_row1"}}),
                     ([_row(1, "queued", ts=NOW - 90 * DAY, ents=subj)],
                      {"published_ids": {"t_row1"}}),
                     ([_row(1, "queued", ts=NOW - 90 * DAY, ents=subj, real_video_id="v")], {}),
                     ([_row(1, "published", ents=subj)], {})):
        unique, dupes = T.dedupe([cand], hist, now=NOW, **kw)
        assert not unique and dupes, (hist, kw)


def test_rows_without_status_still_block_for_back_compat():
    assert T.is_blocking_row({"id": "h", "entities": ["a"]}, now=NOW)


def test_batch_outcome_ids_reads_pass_rows_and_recent_queues(tmp_path, monkeypatch):
    stories = tmp_path / "stories"
    (stories / "s_pass").mkdir(parents=True)
    (stories / "s_pass" / "story.json").write_text(json.dumps({"topic_id": "t_pass"}))
    (stories / "s_hold").mkdir(parents=True)
    (stories / "s_hold" / "story.json").write_text(json.dumps({"topic_id": "t_hold"}))
    monkeypatch.setattr(T, "STORIES_DIR", stories)
    b = tmp_path / "batches"
    (b / "live_1").mkdir(parents=True)
    (b / "live_1" / "batch_report.json").write_text(json.dumps(
        {"rows": [{"story": "s_pass", "verdict": "PASS"}, {"story": "s_hold", "verdict": "HOLD"}]}))
    (b / "live_1" / "topics_queued.json").write_text(json.dumps(
        {"picked": [{"id": "t_a"}], "queue": [{"id": "t_a"}, {"series_id": "s",
                                                             "parts": [{"id": "t_b"}]}]}))
    pub, recent = T.batch_outcome_ids(b, now=time.time())
    assert pub == {"t_pass"} and recent == {"t_a", "t_b"}
    pub, recent = T.batch_outcome_ids(b, now=time.time() + 10 * DAY)   # queue file now old
    assert pub == {"t_pass"} and recent == set()
    assert T.batch_outcome_ids(tmp_path / "missing") == (set(), set())


# ------------------------------------------------------------ avoid list --

def test_avoid_titles_lead_with_published_not_last_50_rows():
    hist = [_row(0, "published", title="Old Seed", source="channel_csv")]
    hist += [_row(1, "queued", title="Published V16 Topic", real_video_id="v1")]
    hist += [_row(i, "duplicate", title=f"Dup {i}", ts=NOW) for i in range(2, 80)]
    hist += [_row(90, "queued", title="In Flight", ts=NOW - 3600)]
    hist += [_row(91, "queued", title="Held Long Ago", ts=NOW - 30 * DAY)]
    out = T.avoid_titles_for_prompt(hist, now=NOW)
    assert out[:2] == ["Published V16 Topic", "In Flight"]
    assert "Old Seed" in out
    assert not any(t.startswith("Dup ") for t in out) and "Held Long Ago" not in out


# ------------------------------------------------------------- history --

def test_history_rows_carry_a_timestamp():
    row = T._history_row({"id": "t_x", "title": "X"}, "queued", "topic_ideate")
    assert T._row_epoch(row) is not None


def test_record_published_appends_a_durable_published_row(tmp_path):
    hp = tmp_path / "h.jsonl"
    T.append_history([{**FULGURITE_PUBLISHED, "real_views": 28, "score": 80}], hp)
    sd = tmp_path / "t_fulgurite_story"
    sd.mkdir()
    (sd / "story.json").write_text(json.dumps(
        {"story_id": "t_fulgurite_story", "topic_id": FULGURITE_PUBLISHED["id"],
         "title": "Fulgurite", "subject": "spectacle_physics"}))
    row = T.record_published(sd, hp, extra={"youtube_video_id": "abc"})
    rows = T.load_history(hp)
    assert len(rows) == 2 and rows[-1] == row
    assert row["status"] == "published" and row["source"] == "v16_batch"
    assert row["entities"] == FULGURITE_PUBLISHED["entities"]
    assert row["youtube_video_id"] == "abc" and "real_views" not in row and "score" not in row
    # hand-authored story -> nothing written
    (sd / "story.json").write_text(json.dumps({"story_id": "x"}))
    assert T.record_published(sd, hp) is None and len(T.load_history(hp)) == 2


def test_run_batch_records_pass_topics_in_history(tmp_path, monkeypatch):
    from engine import v15_pipeline
    from engine import v16_batch as B
    hp = tmp_path / "h.jsonl"
    sds = []
    for name, tid in (("s_pass", "t_p"), ("s_hold", "t_h")):
        sd = tmp_path / name
        sd.mkdir()
        (sd / "story.json").write_text(json.dumps({"story_id": name, "topic_id": tid,
                                                   "title": name}))
        sds.append(sd)

    def fake_run(sd, work, **kw):
        verdict = "PASS" if sd.name == "s_pass" else "HOLD"
        return {"publish_gate": verdict, "gate": {"failures": {}, "checks": {
            "av": {}, "distinctness": {"ok": True}}}, "plan": {"source": "x"},
            "costs": {}, "timings": {}, "manifest": {"completeness": {"ok": True}}}
    monkeypatch.setattr(v15_pipeline, "run_pipeline", fake_run)
    rep = B.run_batch(sds, tmp_path / "work", package=False, use_llm=False, history_path=hp)
    assert [r.get("history_recorded") for r in rep["rows"]] == [True, None]
    rows = T.load_history(hp)
    assert [(r["id"], r["status"]) for r in rows] == [("t_p", "published")]


def test_build_queue_no_longer_starved_by_old_held_rows(tmp_path):
    """The live failure mode: a fresh candidate whose subject only matches
    an old HELD queued row (never rendered) used to be discarded."""
    hp = tmp_path / "h.jsonl"
    old_held = {**_row(1, "queued", ts=time.time() - 20 * DAY, ents=["volcano", "lightning"]),
                "title": "Volcanic Lightning Old", "claim_tokens": ["volcano", "lightning"]}
    T.append_history([old_held, {**FULGURITE_PUBLISHED, "ts": T._utc_iso(time.time() - 9 * DAY)}],
                     hp)
    raw = [{"title": "Volcanic Lightning Storms", "cluster": "spectacle_physics",
            "claim": "Volcanic eruptions make their own lightning",
            "entities": {"subject": "volcano lightning", "place": "", "era": "",
                         "phenomenon": ""},
            "hooks": ["h"], "templates": ["BIG_NUMBER"], "series_id": None,
            "series_part": None, "evergreen": True},
           {**FULGURITE_AGAIN, "hooks": ["h"], "templates": ["BIG_NUMBER"],
            "series_id": None, "series_part": None, "evergreen": True,
            "entities": {"subject": "fulgurite lightning-fused sand"}}]
    ids, seen = [], set()
    for c in raw:
        cid = T._unique_id(T.slugify(c["title"]), seen)
        seen.add(cid)
        ids.append(cid)
    good = {"counter_intuitive": 5, "visualisability": 5, "hook_strength": 5,
            "series_potential": 4, "evidence_strength": 5, "still_image_fit": 5, "best_hook": "h"}
    q = {"topic_ideate": [{"candidates": raw}],
         "topic_score": [{"scores": [{"id": i, **good} for i in ids]}]}
    prompts = []

    def ask(stage, prompt, **kw):
        prompts.append(prompt)
        return SimpleNamespace(data=q[stage].pop(0), model="fake", cached=False,
                               attempts=1, usage={})
    res = T.build_queue(n=2, history_path=hp, ask=ask, persist=True)
    assert [e["title"] for e in res["queue"]] == ["Volcanic Lightning Storms"]
    assert [d["title"] for d in res["duplicates"]] == [FULGURITE_AGAIN["title"]]
    assert FULGURITE_PUBLISHED["title"] in prompts[0]          # avoid list leads with it
    assert all("ts" in r for r in T.load_history(hp)[2:])


def test_one_broad_shared_entity_term_is_not_a_duplicate():
    seed = {"id": "v15_x", "title": "1.6 Billion Years of Rock Are Missing",
            "entities": ["billion", "years", "rock", "missing"], "claim_tokens": []}
    assert T.is_duplicate({"title": "t", "entities": ["rock"]}, seed) is None
    assert T.is_duplicate({"title": "t", "entities": ["tardigrade"]},
                          {"id": "h", "entities": ["tardigrades"]})
