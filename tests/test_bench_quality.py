import json

from bench.quality import runner


def test_topic_packs_load():
    topics = runner.load_topics()
    assert set(topics) == {"01_birds_dinosaurs", "02_tunguska", "03_time_crystals"}
    assert all(t["claims"] for t in topics.values())


def test_summarize_run_and_render(tmp_path):
    rep = {"gate": {"verdict": "PASS", "failures": {}, "checks": {
        "visual_hold": {"ok": True, "max_hold_s": 3.0}, "audio": {"ok": True, "lufs": -14.3},
        "judge": {"ok": True, "hook_stops_scroll": True, "frames_flagged": [{"n": 4, "issue": "text_garbled"}]}}},
        "shots": {"a": {"dur": 2.0}, "b": {"dur": 4.0}, "c": {"dur": 3.0}},
        "plate_qa": {"checked": False}, "plate_providers": {"x": 1}, "timings": {"total_s": 9}}
    (tmp_path / "pipeline_report.json").write_text(json.dumps(rep))
    row = runner.summarize_run("demo", tmp_path)
    assert row["verdict"] == "PASS" and row["median_shot_s"] == 3.0 and row["video"] == {}
    md = runner.render_md([row])
    assert "plate QA silently skipped" in md and "text_garbled" in md


def test_baseline_smoke(tmp_path):
    rows = runner.baseline(tmp_path)
    assert (tmp_path / "baseline.md").exists()
    assert all(r["verdict"] for r in rows)
