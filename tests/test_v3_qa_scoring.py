"""Wave-3 tests: QA scoring — mock vision provider, offline fallback,
force-fail injection, §25 caching.

Run: ./venv/bin/python -m pytest tests/test_v3_qa_scoring.py -q
"""

from __future__ import annotations

import json
import subprocess

import pytest

from engine.v3.qa import shot_qa as shot_qa_mod
from engine.v3.qa import vision as vision_mod


def _patch_vision(monkeypatch, result):
    """Vision QA is imported into shot_qa's namespace — patch there."""
    monkeypatch.setattr(shot_qa_mod, "vision_qa_shot",
                        lambda *a, **k: result)
from engine.v3.qa.shot_qa import qa_shot


@pytest.fixture()
def tiny_mp4(tmp_path):
    out = tmp_path / "S01.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=3:size=320x240:rate=30",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out)],
        capture_output=True, check=True)
    return out


SHOT = {"version": "v3", "shot_id": "S01", "duration_sec": 3.0,
        "renderer": "MOTION_CANVAS", "visual_goal": "g", "subject": "s",
        "composition": "wide", "camera": "static", "motion": "m",
        "generation_priority": "normal", "metadata": {}}


def test_technical_only_scoring_offline(tmp_path, tiny_mp4, monkeypatch):
    # Force vision unavailable: no DeepSeek key path — patch provider.
    _patch_vision(monkeypatch, {"available": False, "score": 0,
                                "issues": []})
    doc = qa_shot(SHOT, tiny_mp4, tmp_path / "qa", use_vision=True,
                  min_height=0, cache=False)
    assert doc["vision_available"] is False
    assert doc["technical_pass"] is True
    assert doc["score"] >= 70
    assert doc["action"] == "keep"


def test_mock_vision_high_score_keeps(tmp_path, tiny_mp4, monkeypatch):
    _patch_vision(monkeypatch, {"available": True, "score": 92,
                                "issues": [], "ok": True})
    doc = qa_shot(SHOT, tiny_mp4, tmp_path / "qa", min_height=0,
                  cache=False)
    assert doc["vision_available"] is True
    assert doc["action"] == "keep"
    assert doc["score"] >= 85


def test_mock_vision_low_score_regenerates(tmp_path, tiny_mp4, monkeypatch):
    _patch_vision(monkeypatch, {"available": True, "score": 25,
                                "issues": ["garbled text"], "ok": False})
    doc = qa_shot(SHOT, tiny_mp4, tmp_path / "qa", min_height=0,
                  cache=False)
    assert doc["action"] == "regenerate"
    assert any("garbled" in i for i in doc["issues"])


def test_force_fail_injects_failure(tmp_path, tiny_mp4):
    doc = qa_shot(SHOT, tiny_mp4, tmp_path / "qa", min_height=0,
                  force_fail=True, cache=False)
    assert doc["action"] == "regenerate"
    assert doc["score"] <= 40
    assert any("forced failure" in i for i in doc["issues"])


def test_qa_cache_hit(tmp_path, tiny_mp4, monkeypatch):
    calls = {"n": 0}

    def fake_vision(*a, **k):
        calls["n"] += 1
        return {"available": False, "score": 0, "issues": []}

    monkeypatch.setattr(shot_qa_mod, "vision_qa_shot", fake_vision)
    a = qa_shot(SHOT, tiny_mp4, tmp_path / "qa", min_height=0, cache=True)
    b = qa_shot(SHOT, tiny_mp4, tmp_path / "qa", min_height=0, cache=True)
    assert a["score"] == b["score"]
    assert calls["n"] == 1  # second call served from cache
    assert b.get("cached") is True


def test_failed_render_report(tmp_path):
    from engine.v3.qa.shot_qa import qa_shotlist

    shots = [dict(SHOT, shot_id="S09")]
    records = {"S09": {"ok": False, "attempts": [{"renderer": "X",
                                                  "error": "boom"}]}}
    out = qa_shotlist(shots, records, tmp_path / "qa", min_height=0)
    assert out["S09"]["action"] == "regenerate"
    assert out["S09"]["score"] == 0
