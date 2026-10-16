"""WP12 — batch runner: preflight, topic selection, quota pause/resume,
packaging (engine/v16_batch.py, DESIGN §13).

Run: python3 -m pytest -q tests/test_wp12_batch.py   (no network, no real render)
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
REPO = ROOT.parent                              # video_engine
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v16_batch as B  # noqa: E402
from llm import client  # noqa: E402

STORIES_DIR = ROOT / "stories"


class FakeAsk:
    """Same shape as WP11's `Fake` (llm.client.ask stand-in): queue of
    responses per stage, records prompts."""

    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}
        self.prompts = []

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        self.prompts.append((stage, prompt))
        item = self.q[stage].pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(data=item, text=json.dumps(item), model="fake",
                               cached=False, attempts=1, usage={})


def _cand(i, cluster="deep_time"):
    return {"title": f"Topic number {i} about ancient formations {cluster}",
            "cluster": cluster, "claim": f"claim {i}",
            "entities": {"subject": f"s{i}", "place": "", "era": "", "phenomenon": ""},
            "hooks": [f"hook {i} a", f"hook {i} b", f"hook {i} c"],
            "templates": ["BIG_NUMBER"], "series_id": None, "series_part": None,
            "evergreen": True}


def _queue_fixture(clusters):
    """-> FakeAsk wired so `v16_topics.build_queue` returns one candidate
    per entry in `clusters`, all scoring well above MIN_SCORE."""
    from engine import v16_topics as T
    raw = [_cand(i, c) for i, c in enumerate(clusters)]
    row = {"counter_intuitive": 4, "visualisability": 4, "hook_strength": 4,
           "series_potential": 4, "evidence_strength": 4, "still_image_fit": 4,
           "best_hook": "a strong hook"}
    ids, seen = [], set()
    for c in raw:
        cid = T._unique_id(T.slugify(c["title"]), seen)
        seen.add(cid)
        ids.append(cid)
    scores = {"scores": [{"id": cid, **row} for cid in ids]}
    return FakeAsk(topic_ideate=[{"candidates": raw}], topic_score=[scores])


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BUILD_DIR", str(tmp_path))
    client.reset()


# ================================================================ preflight

def test_preflight_disk_check_hard_stops_when_space_is_too_low(tmp_path):
    rep = B._disk_check(tmp_path, n_videos=1)
    assert rep["ok"] is True          # the real test disk has plenty of room
    starved = dict(rep)
    assert B.MIN_FREE_GB_PER_VIDEO > 0
    # a batch asking for an absurd number of videos must hard-stop on disk
    huge = B._disk_check(tmp_path, n_videos=10_000_000)
    assert huge["ok"] is False


def test_preflight_voice_check_reports_kokoro_clearance():
    rep = B._voice_check()
    assert rep["ok"] is True
    assert rep["provider"] == "kokoro"
    assert rep["commercial_ok"] is True     # DESIGN owner decision 2: Kokoro sole channel voice


def test_preflight_audio_library_check_sees_the_real_licensed_assets():
    rep = B._audio_library_check()
    assert rep["ok"] is True
    assert rep["moods"]
    assert rep["kinds"]


def test_preflight_images_reports_chain_state():
    rep = B._image_check()
    assert "provider_order" in rep and "low_plate_mode" in rep


def test_preflight_overall_ok_requires_voice_and_disk(tmp_path):
    rep = B.preflight(tmp_path, n_videos=1)
    assert rep["ok"] is True
    assert set(rep["checks"]) == {"llm", "voice", "images", "audio_library", "disk"}


# ============================================================ topic select

def test_select_topics_caps_at_two_per_cluster(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ask = _queue_fixture(["deep_time", "deep_time", "deep_time",
                          "spectacle_physics", "spectacle_physics", "spectacle_physics",
                          "exotic_space_travel"])
    sel = B.select_topics(6, history_path=tmp_path / "topic_history.jsonl", ask=ask)
    picked = sel["picked"]
    assert len(picked) <= 6
    per_cluster = {}
    for e in picked:
        c = e["cluster"]
        per_cluster[c] = per_cluster.get(c, 0) + 1
    assert all(n <= B.MAX_PER_CLUSTER for n in per_cluster.values()), per_cluster
    assert per_cluster.get("deep_time") == 2
    assert per_cluster.get("spectacle_physics") == 2
    assert per_cluster.get("exotic_space_travel") == 1


def test_select_topics_series_bypasses_cluster_cap(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from engine import v16_topics as T
    raw = [{**_cand(i, "deep_time"), "series_id": "tunguska", "series_part": p}
          for i, p in enumerate((1, 2))]
    row = {"counter_intuitive": 4, "visualisability": 4, "hook_strength": 4,
          "series_potential": 4, "evidence_strength": 4, "still_image_fit": 4,
          "best_hook": "hook"}
    ids, seen = [], set()
    for c in raw:
        cid = T._unique_id(T.slugify(c["title"]), seen)
        seen.add(cid)
        ids.append(cid)
    scores = {"scores": [{"id": cid, **row} for cid in ids]}
    ask = FakeAsk(topic_ideate=[{"candidates": raw}], topic_score=[scores])
    sel = B.select_topics(2, series="tunguska",
                          history_path=tmp_path / "topic_history.jsonl", ask=ask)
    assert sel["picked"], "expected the series group to be picked"


# ============================================== decision #14: topic fallback

def _entry(cid, title="t"):
    return {"id": cid, "title": title, "cluster": "c"}


def test_materialize_offers_up_to_three_topics_up_front_and_picks_the_winner(tmp_path, monkeypatch):
    """decision #15 item 2 (rank-not-block): one call covering all 3
    candidates for the slot, not one call per topic with fallback on hold."""
    import engine.v16_batch as batch_mod
    picked = [_entry("a", "A")]
    queue = [_entry("a", "A"), _entry("b", "B"), _entry("c", "C")]
    calls = []

    def fake_generate_story_ranked(cands, ask=None):
        calls.append([c["id"] for c in cands])
        return {"status": "ok", "story": {"story_id": "b", "title": "B"},
               "picked_topic": "B",
               "candidates": [{"topic": "A", "status": "hold", "reason": "below floor"},
                              {"topic": "B", "status": "scored", "mean": 3.2, "min": 3},
                              {"topic": "C", "status": "scored", "mean": 2.9, "min": 3}]}

    import engine.v16_autostory as autostory_mod
    monkeypatch.setattr(autostory_mod, "generate_story_ranked", fake_generate_story_ranked)
    monkeypatch.setattr(autostory_mod, "write_story_dir",
                        lambda s, d=None: Path(f"/tmp/{s['story_id']}"))
    mat = batch_mod.materialize_candidates(picked, tmp_path, queue=queue)
    assert calls == [["a", "b", "c"]]          # all 3 offered up front, one call
    assert len(mat["dirs"]) == 1 and not mat["holds"]
    titles = [a["title"] for a in mat["attempts"]]
    assert titles == ["A", "B", "C", "B"]      # 3 scored + the picked marker
    assert mat["attempts"][-1]["status"] == "picked"


def test_materialize_holds_when_no_candidate_clears_the_floor(tmp_path, monkeypatch):
    import engine.v16_batch as batch_mod
    import engine.v16_autostory as autostory_mod
    picked = [_entry("a", "A")]
    queue = [_entry("a", "A"), _entry("b", "B"), _entry("c", "C"), _entry("d", "D")]
    calls = []

    def fake_generate_story_ranked(cands, ask=None):
        calls.append([c["id"] for c in cands])
        return {"status": "hold", "reason": "rank-not-block: no candidate cleared the floor",
               "candidates": [{"topic": c["title"], "status": "hold", "reason": "held"}
                              for c in cands]}

    monkeypatch.setattr(autostory_mod, "generate_story_ranked", fake_generate_story_ranked)
    mat = batch_mod.materialize_candidates(picked, tmp_path, queue=queue)
    assert calls == [["a", "b", "c"]]          # MAX_TOPICS_PER_SLOT=3, "d" never offered
    assert not mat["dirs"] and len(mat["holds"]) == 1
    assert mat["holds"][0]["topics_tried"] == ["a", "b", "c"]
    assert len(mat["attempts"]) == 3


# ====================================================== quota pause/resume

def _fake_report(story_id: str) -> dict:
    return {
        "story_id": story_id, "costs": {"llm_calls": 1, "image_calls": 2, "vision_calls": 1},
        "timings": {"total_s": 1.0}, "plan": {"source": "llm"}, "plate_providers": {},
        "publish_gate": "PASS",
        "gate": {"failures": {}, "scorecard": {"total": 91.0, "verdict": "PASS"},
                 "checks": {"av": {"duration_s": 42.0}, "distinctness": {"ok": True}}},
        "manifest": {"completeness": {"ok": True}},
    }


def test_resume_after_simulated_quota_at_s6_visual_plan(tmp_path, monkeypatch):
    """DESIGN §15.2 WP12 test proof: 'resume after a simulated quota at
    S6' (S6 = visual_plan, DESIGN §1.2's stage graph). Simulates a real
    Claude-CLI quota cooldown (the same `llm_state.json` the adapter
    itself writes on a real quota hit, WP1) landing while story A is
    still pending, proves the batch pauses BEFORE running story A (never
    silently degrades to a fallback plan), then proves `--resume` behaves
    correctly once the cooldown clears: story A and B both complete, in
    order, with nothing re-run twice."""
    _env(tmp_path, monkeypatch)
    work = tmp_path / "batch"
    calls = []

    def fake_run_pipeline(story_dir, out, **kw):
        calls.append(Path(story_dir).name)
        return _fake_report(Path(story_dir).name)

    import engine.v15_pipeline as v15p
    monkeypatch.setattr(v15p, "run_pipeline", fake_run_pipeline)

    # 1. simulate a quota hit at S6 (visual_plan's only configured provider,
    #    claude_cli) — the exact state file engine.director.text_ask's own
    #    LLMUnavailable("quota") path writes on a real outage (llm/client.py
    #    `_set_cooldown`), written directly here per the existing adapter
    #    test convention (tests/test_llm_adapter.py).
    retry_at = datetime.now(timezone.utc) + timedelta(hours=2)
    (tmp_path / "llm_state.json").write_text(json.dumps(
        {"cooldown": {"claude_cli": retry_at.isoformat()}}))
    client.reset()

    story_a, story_b = STORIES_DIR / "ice_slippery", STORIES_DIR / "tunguska_1908"
    rep1 = B.run_batch([story_a, story_b], work, resume=False, package=False, use_llm=True)

    assert rep1["paused"] is True
    assert rep1["exit_code"] == 75
    assert rep1["retry_at"] is not None
    assert calls == [], "must pause BEFORE calling run_pipeline, not after"
    assert rep1["pending"] == [str(story_a), str(story_b)]
    assert (work / "batch_state.json").exists()

    # 2. quota resets — clear the cooldown, exactly like a real `retry_at` elapsing
    (tmp_path / "llm_state.json").write_text(json.dumps({"cooldown": {}}))
    client.reset()

    rep2 = B.run_batch([], work, resume=True, package=False, use_llm=True)

    assert rep2.get("paused") is False
    assert calls == ["ice_slippery", "tunguska_1908"], "resume must not re-run a done story"
    assert rep2["pending"] == []
    assert len(rep2["rows"]) == 2
    assert [r["story"] for r in rep2["rows"]] == ["ice_slippery", "tunguska_1908"]
    assert all(r["verdict"] == "PASS" for r in rep2["rows"])
    assert rep2["totals"]["llm_calls"] == 2
    assert rep2["lanes_overlap"] is False   # DESIGN §13.3, deferred — see module docstring


def test_quota_landing_mid_video_keeps_that_story_pending(tmp_path, monkeypatch):
    """live_20261016_043811: the pre-video check passed, then story A's first
    LLM call hit 'claude_cli: quota (You've hit your session limit · resets
    8:20am (UTC))'. The render finished degraded (plate QA + final judge
    'unavailable') and HOLDed as unverified, yet was recorded as done, so
    --resume would never re-judge it. It must stay pending, unpackaged."""
    _env(tmp_path, monkeypatch)
    work = tmp_path / "batch3"
    calls = []

    def quota_mid_run(story_dir, out, **kw):
        calls.append(Path(story_dir).name)
        if len(calls) == 1:   # the quota lands while A is rendering
            until = datetime.now(timezone.utc) + timedelta(hours=2)
            (tmp_path / "llm_state.json").write_text(json.dumps(
                {"cooldown": {"claude_cli": until.isoformat()}}))
            rep = _fake_report(Path(story_dir).name)
            rep["publish_gate"] = "HOLD"
            rep["gate"]["failures"] = {
                "plates": ["plate QA did not run: judge unavailable or unparseable"],
                "judge": ["judge unavailable/unparseable -> unverified"]}
            return rep
        return _fake_report(Path(story_dir).name)

    import engine.v15_pipeline as v15p
    monkeypatch.setattr(v15p, "run_pipeline", quota_mid_run)
    monkeypatch.setattr(B, "package_video", lambda *a, **k: pytest.fail(
        "a quota-degraded render must not be packaged/uploaded"))

    story_a, story_b = STORIES_DIR / "ice_slippery", STORIES_DIR / "tunguska_1908"
    rep1 = B.run_batch([story_a, story_b], work, package=True, upload=False,
                       use_llm=True)
    assert rep1["paused"] is True and rep1["exit_code"] == 75
    assert rep1["pending"] == [str(story_a), str(story_b)]
    assert rep1["done"] == [] and rep1["rows"] == []
    assert rep1["interrupted"][0]["story"] == "ice_slippery"
    assert json.loads((work / "batch_state.json").read_text())["pending"] == \
        [str(story_a), str(story_b)]

    (tmp_path / "llm_state.json").write_text(json.dumps({"cooldown": {}}))
    client.reset()
    rep2 = B.run_batch([], work, resume=True, package=False, use_llm=True)
    assert rep2["paused"] is False
    assert calls == ["ice_slippery", "ice_slippery", "tunguska_1908"]
    assert [r["verdict"] for r in rep2["rows"]] == ["PASS", "PASS"]


def test_a_mid_video_quota_after_a_verified_pass_keeps_the_pass(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)

    def pass_then_quota(story_dir, out, **kw):
        until = datetime.now(timezone.utc) + timedelta(hours=2)
        (tmp_path / "llm_state.json").write_text(json.dumps(
            {"cooldown": {"claude_cli": until.isoformat()}}))
        return _fake_report(Path(story_dir).name)

    import engine.v15_pipeline as v15p
    monkeypatch.setattr(v15p, "run_pipeline", pass_then_quota)
    rep = B.run_batch([STORIES_DIR / "ice_slippery"], tmp_path / "b4",
                      package=False, use_llm=True)
    assert [r["verdict"] for r in rep["rows"]] == ["PASS"]
    assert rep["pending"] == [] and "interrupted" not in rep


def test_a_story_error_never_stops_the_batch(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    work = tmp_path / "batch2"

    def flaky_run_pipeline(story_dir, out, **kw):
        if Path(story_dir).name == "bad_story":
            raise RuntimeError("boom")
        return _fake_report(Path(story_dir).name)

    import engine.v15_pipeline as v15p
    monkeypatch.setattr(v15p, "run_pipeline", flaky_run_pipeline)

    rep = B.run_batch([STORIES_DIR / "bad_story", STORIES_DIR / "ice_slippery"],
                      work, package=False, use_llm=False)
    assert [r["verdict"] for r in rep["rows"]] == ["ERROR", "PASS"]
    assert rep["paused"] is False


# =================================================================== packaging

def test_package_video_produces_final_proxy_cover_metadata(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    final = work_dir / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=blue:s=64x114:d=1:r=10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(final)], check=True, capture_output=True)
    (work_dir / "manifest.json").write_text(json.dumps({"video_id": "x"}))
    # 2026-10-15: cover.png comes from the caption-free first scene render
    (work_dir / "scenes").mkdir()
    import shutil
    shutil.copyfile(final, work_dir / "scenes" / "B1_S1.mp4")

    report = _fake_report("ice_slippery")
    out = package_dir = tmp_path / "package"
    result = B.package_video(STORIES_DIR / "ice_slippery", work_dir, out, report=report)

    assert result["ok"] is True
    assert (out / "final.mp4").exists()
    assert result["proxy"] is True and (out / "proxy.mp4").exists()
    assert result["cover"] is True and (out / "cover.png").exists()
    assert (out / "manifest.json").exists()
    assert (out / "scorecard.json").exists()
    meta = (out / "metadata.txt").read_text()
    assert "WHY ICE IS SLIPPERY" in meta
    assert "Gate verdict: PASS" in meta


def test_package_video_repackages_a_rerendered_story(tmp_path):
    """live_20261016_043811: re-running a story into the same work dir hit
    SameFileError — package/final.mp4 was still a hardlink to final.mp4."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    final = work_dir / "final.mp4"
    final.write_bytes(b"first render")
    out = tmp_path / "work" / "package"
    B.package_video(STORIES_DIR / "ice_slippery", work_dir, out,
                    report=_fake_report("ice_slippery"))
    final.write_bytes(b"second render")     # in place: same inode as the link
    result = B.package_video(STORIES_DIR / "ice_slippery", work_dir, out,
                             report=_fake_report("ice_slippery"))
    assert result["final"] and (out / "final.mp4").read_bytes() == b"second render"


def test_package_video_reports_missing_final_mp4_instead_of_crashing(tmp_path):
    result = B.package_video(STORIES_DIR / "ice_slippery", tmp_path / "nowhere",
                             tmp_path / "out", report=_fake_report("ice_slippery"))
    assert result["ok"] is False
    assert "final.mp4" in result["error"]


def test_metadata_txt_uses_llm_metadata_with_tags():
    """decision #18 item 8: the copy-paste file carries the real metadata."""
    rep = _fake_report("ice_slippery")
    rep["metadata"] = {"title": "T1", "description": "D1 long text",
                       "tags": ["ice", "physics"]}
    story = {"title": "S", "beats": [{"function": "HOOK", "narration": "H"}]}
    txt = B._metadata_txt(rep, story)
    assert txt.startswith("Title: T1\n\nD1 long text\n\nTags: ice, physics\n")
    rep.pop("metadata")
    assert B._metadata_txt(rep, story).startswith("Title: S\n\nH\n\n--- Disclosure")


# ---------------------------------------- 2026-10-15 review: thumbnail --

def test_thumbnail_stat_picks_last_escalation_number_not_year_or_hook():
    from engine.v16_batch import thumbnail_stat
    story = {"beats": [{"beat_id": "B1", "function": "HOOK"},
                       {"beat_id": "B2", "function": "NORMAL"},
                       {"beat_id": "B3", "function": "NORMAL"},
                       {"beat_id": "B4", "function": "PAYOFF"}]}
    plan = {"beats": [
        {"beat_id": "B1", "shots": [{"number": {"text": "10 KM", "word": 1}}]},
        {"beat_id": "B2", "shots": [{"number": {"text": "200 KM", "word": 1}},
                                    {"number": {"text": "1933", "word": 3}}]},
        {"beat_id": "B3", "shots": [{"number": {"text": "1.5 KM WAVE", "word": 2}}]},
        {"beat_id": "B4", "shots": [{"headline": "x"}]}]}
    assert thumbnail_stat(plan, story) == "1.5 KM WAVE"
    assert thumbnail_stat({"beats": [{"beat_id": "B1", "shots": [
        {"number": {"text": "10 KM"}}]}]}, story) == "10 KM"
    assert thumbnail_stat({"beats": []}, story) is None


def test_thumbnail_never_truncates_and_cover_is_caption_free(tmp_path):
    from PIL import Image, ImageDraw
    from engine.brand import _fit_lines, load_brand, render_thumbnail
    from engine.v16_batch import _cover_source
    brand = load_brand()
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    long_title = "A VERY LONG HOOK HEADLINE THAT WOULD NEVER FIT IN THREE LINES AT FULL SIZE"
    f, lines = _fit_lines(d, brand, long_title, 960, 132, 3)
    assert " ".join(lines) == long_title and len(lines) <= 3
    bg = tmp_path / "bg.png"
    Image.new("RGB", (540, 960), (20, 40, 60)).save(bg)
    out = render_thumbnail(tmp_path / "t.jpg", bg_image=bg, title="ONE ROCK",
                           stat="930 MILES")
    assert out.exists()
    # cover source: first scene render (pre-caption), never final.mp4
    work = tmp_path / "w"
    (work / "scenes").mkdir(parents=True)
    for n in ("B10_S1.mp4", "B1_S2.mp4", "B1_S1.mp4"):
        (work / "scenes" / n).write_bytes(b"")
    (work / "final.mp4").write_bytes(b"")
    assert _cover_source(work, {}).name == "B1_S1.mp4"
    assert _cover_source(tmp_path / "none", {"hook_plate_path": str(bg)}) == bg
