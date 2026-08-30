"""Phase 2A-finisher tests: run.py §19 --analyze mode + §21 re-edit wiring.

Run: ./venv/bin/python -m pytest tests/test_v4_runner_wiring.py -q
"""

from __future__ import annotations

import json
import subprocess

import pytest

from engine.v3.run import main
from engine.v4.reedit import apply_reedit, plan_reedit


def _render_scenes(path, colors, scene_sec=1.33, size="320x180"):
    """Master built from hard scene cuts (solid colors) — cuts register as
    visual-event spikes in the audit; a single color = frozen flat video."""
    n = len(colors)
    inputs: list[str] = []
    for c in colors:
        inputs += ["-f", "lavfi", "-i",
                   f"color=c={c}:size={size}:rate=30:duration={scene_sec}"]
    fc = ("".join(f"[{i}:v]" for i in range(n))
          + f"concat=n={n}:v=1:a=0[out]")
    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[out]",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)],
        capture_output=True, check=True)


# ── §19 analysis mode ───────────────────────────────────────────────────

def test_analyze_frozen_artifact_fails_with_findings(tmp_path):
    """A frozen flat master must FAIL the artifact gates with specific
    findings, and the report must record the exact probed path."""
    master = tmp_path / "master.mp4"
    _render_scenes(master, ["0x202020"], scene_sec=6.0)
    rc = main(["--analyze", str(tmp_path)])
    assert rc == 1  # FAIL → exit 1 (CI-usable)
    doc = json.loads((tmp_path / "publish_gate_v4_analysis.json").read_text())
    assert doc["overall"] == "FAIL"
    assert doc["analysis_mode"] is True
    assert doc["artifact"]["path"] == str(master.resolve())
    assert doc["artifact"]["probed_by"] == "ARTIFACT_METADATA gate"
    assert doc["artifact"]["probe"]["codec"] == "h264"
    for name in ("VISUAL_EVENT_DENSITY", "STATIC_HOLD", "CINEMATIC",
                 "CREATIVE"):
        assert name in doc["failed_gates"], doc["failed_gates"]
    # gates that define repair guidance must carry findings
    for name in ("VISUAL_EVENT_DENSITY", "STATIC_HOLD", "CREATIVE"):
        assert doc["gates"][name]["fixes"], f"{name} must carry findings"
    # frozen input: density must be ~0
    assert doc["gates"]["VISUAL_EVENT_DENSITY"]["density_per_10s"] < 0.5


def test_analyze_cut_artifact_density_gate_passes(tmp_path):
    """An artifact with real scene changes passes the event-density gate
    while the planless CINEMATIC gate fails honestly — the analysis must
    measure the artifact, not assume."""
    master = tmp_path / "master.mp4"
    _render_scenes(master, ["red", "green", "blue", "yellow", "magenta",
                            "cyan"], scene_sec=1.33)
    rc = main(["--analyze", str(tmp_path)])
    doc = json.loads((tmp_path / "publish_gate_v4_analysis.json").read_text())
    assert rc == 1  # CINEMATIC fails honestly (no shotlist context)
    assert doc["gates"]["VISUAL_EVENT_DENSITY"]["pass"], \
        doc["gates"]["VISUAL_EVENT_DENSITY"]["detail"]
    assert doc["gates"]["VISUAL_EVENT_DENSITY"]["density_per_10s"] >= 1.5
    assert "CINEMATIC" in doc["failed_gates"]
    assert "no shots" in doc["gates"]["CINEMATIC"]["detail"]


# ── §21 re-edit wiring ──────────────────────────────────────────────────

def test_reedit_demotes_regenerate_to_trim_on_frozen_shot():
    """§21: regenerate requests on long/frozen shots are mechanically
    demoted to trim — re-edit before regeneration."""
    shots = [{"shot_id": "S01", "duration_sec": 10.0, "renderer": "PIXIJS"}]
    critic = {"recommended_cuts": [
        {"shot_id": "S01", "action": "regenerate",
         "detail": "frozen slideshow"}]}
    ops = plan_reedit(critic, shots)
    assert ops and ops[0]["action"] == "trim"
    new_shots, applied, _ = apply_reedit(shots, ops)
    assert applied and new_shots[0]["duration_sec"] < 10.0
    assert new_shots[0]["metadata"]["reedited"] == "trim"


def test_reedit_retimes_narration_chain():
    shots = [
        {"shot_id": "S01", "duration_sec": 4.0},
        {"shot_id": "S02", "duration_sec": 6.0},
    ]
    critic = {"recommended_cuts": [
        {"shot_id": "S02", "action": "shorten", "detail": "pacing"}]}
    ops = plan_reedit(critic, shots)
    new_shots, applied, _ = apply_reedit(shots, ops)
    assert applied
    # re-chained timings stay consistent after the op
    t = 0.0
    for s in new_shots:
        assert s["narration_start"] == pytest.approx(t, abs=0.01)
        t += s["duration_sec"]
        assert s["narration_end"] == pytest.approx(t, abs=0.01)


def test_reedit_unknown_and_master_targets_resolved():
    shots = [{"shot_id": "S01", "duration_sec": 3.0},
             {"shot_id": "S02", "duration_sec": 9.0}]
    critic = {"recommended_cuts": [
        {"shot_id": "master", "action": "trim", "detail": "frozen hold"},
        {"shot_id": "S99", "action": "trim", "detail": "ghost"}]}
    ops = plan_reedit(critic, shots)
    assert all(op["shot_id"] in {"S01", "S02"} for op in ops)
    # master-level cut lands on the LONGEST shot
    assert any(op["shot_id"] == "S02" for op in ops)
