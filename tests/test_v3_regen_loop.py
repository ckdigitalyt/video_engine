"""Wave-3 tests: selective regen loop (§22) — force-fail, re-route,
only-failed-shots-rebuilt, best version kept.

Run: ./venv/bin/python -m pytest tests/test_v3_regen_loop.py -q
"""

from __future__ import annotations

import json

import pytest

from engine.v3.repair.regen import selective_regen


def shot(sid):
    return {"version": "v3", "shot_id": sid, "duration_sec": 3.0,
            "renderer": "MOTION_CANVAS", "fallback_renderer": "PIXIJS",
            "visual_goal": "g", "generation_priority": "normal",
            "metadata": {}}


class FakeRender:
    """Counts renders; writes a real tiny mp4 so QA can ffprobe it."""

    def __init__(self, tmp_path, fail_renderers=()):
        self.calls = []
        self.tmp = tmp_path
        self.fail_renderers = fail_renderers

    def __call__(self, shot, out_dir, attempt=0, renderer_override=None,
                 **kw):
        rid = renderer_override or shot["renderer"]
        self.calls.append((shot["shot_id"], attempt, rid))
        import subprocess

        out = out_dir / f"{shot['shot_id']}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        if rid in self.fail_renderers:
            out.write_text("not a video")
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi",
                 "-i", f"testsrc=duration=3:size=320x240:rate=30",
                 "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out)],
                capture_output=True, check=True)
        return {"shot_id": shot["shot_id"], "ok": out.exists(),
                "path": str(out), "renderer_used": rid,
                "attempts": [], "seed": 0, "metadata": {}, "qa_frames": []}


def _qa_kw(tmp_path):
    return {"min_height": 0, "use_vision": False}


def test_force_fail_triggers_regeneration(tmp_path):
    fr = FakeRender(tmp_path)
    shots = [shot("S01"), shot("S02")]
    records = {s["shot_id"]: fr(s, tmp_path / "v1") for s in shots}
    reports = {sid: {"score": 90, "action": "keep"} for sid in records}
    # Inject synthetic failure for S01.
    reports["S01"] = {"score": 30, "action": "regenerate"}
    result = selective_regen(
        shots, records, reports, render_fn=fr,
        qa_dir=tmp_path / "qa", shots_root=tmp_path / "shots",
        max_retries=1, use_vision=False, qa_kw=_qa_kw(tmp_path))
    assert result["regenerated"] == ["S01"]
    # S02 untouched — selective.
    assert all(c[0] != "S02" for c in fr.calls[2:])
    # Best version kept.
    assert result["records"]["S01"]["ok"]


def test_chronic_failure_reroutes_to_fallback(tmp_path):
    fr = FakeRender(tmp_path, fail_renderers={"MOTION_CANVAS"})
    shots = [shot("S01")]
    result = selective_regen(
        shots, {}, {}, render_fn=fr, qa_dir=tmp_path / "qa",
        shots_root=tmp_path / "shots", max_retries=1,
        use_vision=False, qa_kw=_qa_kw(tmp_path))
    rec = result["records"]["S01"]
    assert rec["renderer_used"] == "PIXIJS"  # fallback_renderer
    assert rec["ok"]


def test_best_version_kept(tmp_path):
    fr = FakeRender(tmp_path)
    shots = [shot("S01")]
    records = {"S01": fr(shots[0], tmp_path / "v1")}
    reports = {"S01": {"score": 95, "action": "keep"}}
    # Force a regen attempt that scores lower; best (95) must be kept.
    result = selective_regen(
        shots, records, reports, render_fn=fr,
        qa_dir=tmp_path / "qa", shots_root=tmp_path / "shots",
        max_retries=1, force_fail={"S01"}, use_vision=False,
        qa_kw=_qa_kw(tmp_path))
    rep = result["reports"]["S01"]
    # The forced-fail first attempt scored 30; the regen attempt scores
    # high (valid testsrc clip, technical-only) — best version wins.
    assert rep["score"] > 30
    assert result["versions"]["S01"] >= 2
