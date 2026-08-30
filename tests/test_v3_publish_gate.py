"""Wave-3 tests: publish-gate logic (§34) — pure-logic gates + a real
tiny-master TECHNICAL/AUDIO gate run.

Run: ./venv/bin/python -m pytest tests/test_v3_publish_gate.py -q
"""

from __future__ import annotations

import json
import subprocess

import pytest

from engine.v3.qa.video_qa import (
    audio_gate,
    factual_gate,
    style_gate,
    technical_gate,
    temporal_gate,
    variety_gate,
    visual_gate,
)


@pytest.fixture(scope="module")
def tiny_master(tmp_path_factory):
    out = tmp_path_factory.mktemp("master") / "master.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=4:size=1920x1080:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
         "-shortest", str(out)],
        capture_output=True, check=True)
    return out


def test_technical_gate_passes_real_h264(tiny_master):
    gate = technical_gate(tiny_master, 4.0)
    assert gate["pass"], gate["detail"]


def test_technical_gate_fails_wrong_duration(tiny_master):
    gate = technical_gate(tiny_master, 30.0)
    assert not gate["pass"]
    assert any("duration" in f for f in gate["fixes"])


def test_audio_gate_measures_loudness(tiny_master):
    gate = audio_gate(tiny_master)
    # A 440 Hz sine may or may not hit -14 LUFS; assert the gate *runs*
    # and reports a measurement rather than erroring.
    assert "gate" in gate
    assert gate["detail"]


def test_factual_gate_flags_invented_numbers():
    research = {"claims": [
        {"text": "The asteroid was 10 kilometres wide", "source_ref": "s1",
         "confidence": "high"}],
        "sources": [{"ref": "s1", "title": "t"}],
        "provenance": "llm_general_knowledge"}
    script = {"beats": [{"narration": "It was 99 kilometres wide."}]}
    gate = factual_gate(research, script)
    assert not gate["pass"]
    assert any("not found in research" in f for f in gate["fixes"])


def test_factual_gate_passes_consistent_numbers():
    research = {"claims": [
        {"text": "The object was 10 kilometres wide", "source_ref": "s1",
         "confidence": "high"},
        {"text": "c2", "source_ref": "s1", "confidence": "medium"},
        {"text": "c3", "source_ref": "s1", "confidence": "medium"}],
        "sources": [{"ref": "s1", "title": "t"}],
        "provenance": "llm_general_knowledge"}
    script = {"beats": [{"narration": "It was 10 kilometres wide."}]}
    gate = factual_gate(research, script)
    assert gate["pass"], gate["detail"]


def test_style_gate(tmp_path):
    style = {"version": "v2", "style_name": "cinematic_documentary"}
    shots = [{"shot_id": "S01", "renderer": "PIXIJS", "style": "x"}]
    assert style_gate(style, shots)["pass"]
    bad = {"style_name": "x"}  # missing version
    assert not style_gate(bad, shots)["pass"]


def test_variety_gate_flags_monotone_mix():
    shots = [{"shot_id": f"S0{i}", "renderer": "PIXIJS",
              "duration_sec": 4, "composition": f"c{i}",
              "camera": f"cam{i}", "music_state": "ambient",
              "text_overlay": None} for i in range(1, 9)]
    gate = variety_gate(shots)
    assert not gate["pass"]


def test_temporal_gate():
    shots = [{"shot_id": "S01", "duration_sec": 4}]
    assert temporal_gate(shots, 4.0, {"S01": {"probe": {"duration": 4}}})[
        "pass"]
    gate = temporal_gate(shots, 40.0, {})
    assert not gate["pass"]


def test_visual_gate_threshold():
    reports = {"S01": {"score": 80, "action": "keep"},
               "S02": {"score": 90, "action": "keep"}}
    assert visual_gate(reports)["pass"]
    bad = {"S01": {"score": 40, "action": "regenerate"}}
    assert not visual_gate(bad)["pass"]


def test_retention_gate_offline_heuristic():
    from engine.v3.qa.video_qa import retention_gate

    shots = [
        {"shot_id": "S01", "renderer": "AI_IMAGE_MOTION",
         "duration_sec": 5, "narrative_role": "hook",
         "subject": "a dramatic wide scene", "text_overlay": "HOOK LINE",
         "generation_priority": "hero", "music_state": "build",
         "composition": "wide", "camera": "push", "metadata":
             {"narration": "a surprising line"}},
        {"shot_id": "S02", "renderer": "MOTION_CANVAS", "duration_sec": 4,
         "narrative_role": "payoff", "subject": "closing", "text_overlay":
             None, "generation_priority": "normal", "music_state":
             "resolve", "composition": "close", "camera": "static",
         "metadata": {"narration": "and that is why it matters"}},
    ]
    gate = retention_gate(shots, "test topic", use_llm=False)
    assert gate["pass"], gate["detail"]


def test_publish_gate_end_to_end(tmp_path, tiny_master):
    from engine.v3.qa.video_qa import publish_gate

    shots = [
        {"shot_id": "S01", "renderer": "MOTION_CANVAS", "duration_sec": 3,
         "narrative_role": "hook", "visual_goal": "g", "style": "s",
         "subject": "a dramatic wide scene", "text_overlay": "HOOK",
         "generation_priority": "hero", "music_state": "build",
         "composition": "wide establishing", "camera": "slow push in",
         "metadata": {"narration": "A surprising opening line here."}},
        {"shot_id": "S02", "renderer": "PIXIJS", "duration_sec": 3,
         "narrative_role": "payoff", "visual_goal": "g", "style": "s",
         "subject": "closing image", "text_overlay": None,
         "generation_priority": "normal", "music_state": "resolve",
         "composition": "close-up detail", "camera": "static hold",
         "metadata": {"narration": "And that is why it matters."}},
    ]
    script = {"topic": "t", "beats": [
        {"narration": "A surprising opening line here."},
        {"narration": "And that is why it matters."}]}
    research = {"claims": [{"text": "c1", "source_ref": "", "confidence":
                            "medium"}] * 3, "sources": [],
                "provenance": "offline_template"}
    style = {"version": "v2", "style_name": "cinematic_documentary"}
    reports = {s["shot_id"]: {"score": 85, "action": "keep",
                              "vision_available": False}
               for s in shots}
    gate = publish_gate(tiny_master, shots, script, research, style,
                        reports, tmp_path / "publish_gate.json",
                        use_vision=False, use_llm=False)
    doc = json.loads((tmp_path / "publish_gate.json").read_text())
    assert doc["overall"] in ("PASS", "FAIL")
    assert set(doc["gates"]) == {"TECHNICAL", "AUDIO", "FACTUAL",
                                 "TEMPORAL", "STYLE", "VARIETY", "VISUAL",
                                 "RETENTION"}
