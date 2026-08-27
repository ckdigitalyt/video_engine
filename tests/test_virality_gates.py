"""Virality gates (2026-08-27): topic specificity, scene coverage,
black-frame detection, and the daily_run no-facts hard-fail.

Root cause under test: the Gabriel's Horn video passed QA 100 while the
script never mentioned the topic and the climax rendered ~5.2s of black.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from engine.qa.gates import (
    gate_black_frames,
    gate_scene_coverage,
    gate_script_specificity,
)


# ── fixtures ─────────────────────────────────────────────────────────────
GABRIEL_FACTS = [
    {"claim": "the horn holds exactly π cubic units of paint",
     "formula": "V = π∫₁^∞ (1/x²) dx = π"},
    {"claim": "surface area grows as 2π ln b and diverges to infinity",
     "formula": "A = 2π∫₁^b (1/x)√(1+1/x⁴) dx ≥ 2π ln b"},
]


def _spec(script_lines: list[str], facts=GABRIEL_FACTS,
          topic="Gabriel's Horn: the shape you can fill but never paint"):
    return {
        "version": "v2",
        "metadata": {"topic": topic, "facts": facts},
        "beats": [
            {"beat_id": f"b{i:03d}", "narration": t,
             "objects": [{"id": f"o{i}"}],
             "semantic_actions": [{"action": "show", "target": f"o{i}"}]}
            for i, t in enumerate(script_lines)
        ],
    }


GOOD_SCRIPT = [
    "This trumpet shape holds exactly π paint — but can never be painted.",
    "Revolve the curve y equals 1 over x around its axis and it never ends.",
    "Pour paint in: the volume is finite, exactly π cubic units.",
    "But the surface area grows without bound — to infinity.",
    "Finite volume, infinite surface: that is the painter's paradox.",
    "The end card says it all: V = π, A = ∞.",
]

GENERIC_SCRIPT = [
    "What is really going on here?",
    "Let's answer it with one simple experiment.",
    "Here is the setup.",
    "Now change one thing at a time.",
    "Watch what changes.",
    "Push it to the extreme.",
    "A clear rule emerges.",
    "Here is the principle behind it.",
    "Now you know.",
]


# ── gate_script_specificity ─────────────────────────────────────────────
def test_specificity_passes_topic_bound_script():
    g = gate_script_specificity(_spec(GOOD_SCRIPT))
    assert g.passed, g.errors


def test_specificity_fails_generic_template_leak():
    g = gate_script_specificity(_spec(GENERIC_SCRIPT))
    assert not g.passed
    assert any("template leak" in e for e in g.errors)


def test_specificity_warns_when_topic_has_no_facts():
    g = gate_script_specificity(_spec(GENERIC_SCRIPT, facts=[]))
    # no-facts topics must not hard-fail HERE — daily_run aborts instead
    assert g.passed
    assert any("no_topic_knowledge" in w for w in g.warnings)


def test_specificity_fails_empty_script():
    g = gate_script_specificity({"version": "v2",
                                 "metadata": {"topic": "x", "facts": []},
                                 "beats": []})
    assert not g.passed


# ── gate_scene_coverage ─────────────────────────────────────────────────
def test_coverage_fails_empty_beat():
    spec = _spec(["line one", "line two"])
    spec["beats"].append({"beat_id": "b_empty", "narration": "empty beat"})
    g = gate_scene_coverage(spec)
    assert not g.passed
    assert any("EMPTY scene" in e for e in g.errors)


def test_coverage_fails_static_rig_span():
    beat = {"beat_id": "b", "narration": "n", "objects": [{"id": "rig"}],
            "semantic_actions": [{"action": "show", "target": "rig"}]}
    spec = {"version": "v2", "metadata": {}, "beats": [beat] * 3}
    g = gate_scene_coverage(spec)
    assert not g.passed
    assert any("> 2 consecutive" in e for e in g.errors)


def test_coverage_passes_varied_beats():
    g = gate_scene_coverage(_spec(GOOD_SCRIPT))
    assert g.passed, g.errors


# ── gate_black_frames ───────────────────────────────────────────────────
def _render_color(path: Path, color: str, seconds: float) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c={color}:s=64x64:d={seconds}:r=8",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True)
    return path


def test_black_frames_fails_long_black_run(tmp_path):
    vid = _render_color(tmp_path / "black.mp4", "black", 2.0)
    g = gate_black_frames(vid, sample_fps=4.0)
    assert not g.passed
    assert any("black frames" in e for e in g.errors)


def test_black_frames_passes_bright_video(tmp_path):
    vid = _render_color(tmp_path / "white.mp4", "white", 2.0)
    g = gate_black_frames(vid, sample_fps=4.0)
    assert g.passed, g.errors


def test_black_frames_scripted_black_downgrades_to_warning(tmp_path):
    vid = _render_color(tmp_path / "black2.mp4", "black", 2.0)
    g = gate_black_frames(vid, allow_scripted_black=True, sample_fps=4.0)
    assert g.passed
    assert any("scripted black" in w for w in g.warnings)


# ── daily_run no-facts hard-fail ────────────────────────────────────────
def test_daily_run_aborts_unknown_topic(monkeypatch, tmp_path):
    import engine.daily_run as dr
    from engine.world.knowledge import ResearchResult

    monkeypatch.setattr(
        dr, "research",
        lambda t: ResearchResult(topic=t))
    res = dr.run_daily(topic="totally unknown topic xyz", out_root=str(tmp_path))
    assert res.outcome == "ABORT"
    assert "no_topic_knowledge" in res.outcome_reason
    # must abort BEFORE planning — no visualspec artifact
    assert not (Path(res.artifacts_dir) / "visualspec.json").exists()


def test_daily_run_known_topic_has_facts():
    from engine.world.knowledge import research
    r = research("Gabriel's Horn: the shape you can fill but never paint")
    assert r.facts, "Gabriel's Horn must resolve to knowledge-base facts"
    text = json.dumps([f.__dict__ for f in r.facts], ensure_ascii=False)
    assert "π" in text and "paint" in text.lower()
