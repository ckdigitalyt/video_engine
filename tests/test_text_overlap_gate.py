"""Tests for the text crossfade-overlap fix + QA gate (2026-08-27).

Regression: the Gabriel's Horn -r3 render superimposed two formula layers
for ~20s (t≈13–33s) because TEMP text primitives declared enter+exit in
the same breath without ever removing their pixels, and the compiler's
EXIT sweep never saw action-created layers.  Covers:

- gate_text_overlap (planning level, via compiled scene source)
- analyze_text_layer_source against the REAL pre-fix scene artifact
- clean title generation (3 variants, <=60 chars, no truncation artifacts)
- the designed thumbnail composer
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Minimal Gabriel's Horn-style v2 VisualSpec (fill → measure → compare →
# measure on a payoff card) — the exact action sequence that garbled -r3.
def _gabriel_spec() -> dict:
    world = {
        "topic": "Gabriel's Horn: the shape you can fill but never paint",
        "entities": [
            {"id": "horn", "type": "horn",
             "properties": {"label": "y = 1/x, x ≥ 1",
                            "position": [0, 2.7, 0]}},
            {"id": "payoff_card", "type": "payoff",
             "properties": {"text": "V = π, A = ∞"}},
        ],
        "relationships": [], "forces": [], "signals": [], "facts": [],
        "camera": {"target": "horn"},
    }
    beats = [
        {"beat_id": "b001", "intent": "hook", "importance": "high",
         "narration": "This shape holds exactly π paint.",
         "visual_type": "", "duration": 3.0, "transformations": [],
         "objects": [{"id": "horn", "type": "horn",
                      "properties": {"label": "y = 1/x, x ≥ 1"}}]},
        {"beat_id": "b002", "intent": "demonstrate_transformation",
         "importance": "high",
         "narration": "Pour paint into it: the fill volume converges to π.",
         "visual_type": "", "duration": 4.0, "transformations": [],
         "objects": [{"id": "horn", "type": "horn",
                      "properties": {"label": "y = 1/x, x ≥ 1"}}],
         "semantic_actions": [
             {"action": "fill", "target": "horn",
              "params": {"label": "V(b) = π(1 − 1/b)"}}]},
        {"beat_id": "b003", "intent": "discovery", "importance": "high",
         "narration": "V equals π times one minus one over b.",
         "visual_type": "", "duration": 4.0, "transformations": [],
         "objects": [{"id": "horn", "type": "horn",
                      "properties": {"label": "y = 1/x, x ≥ 1"}}],
         "semantic_actions": [
             {"action": "measure", "target": "horn",
              "params": {"value": "V → π as b → ∞", "label": "limit"}}]},
        {"beat_id": "b004", "intent": "build_intuition", "importance": "high",
         "narration": "The inside wall area is 2π times the log of b.",
         "visual_type": "", "duration": 4.0, "transformations": [],
         "objects": [{"id": "horn", "type": "horn",
                      "properties": {"label": "y = 1/x, x ≥ 1"}}],
         "semantic_actions": [
             {"action": "compare", "target": "horn",
              "params": {"left_label": "V = π", "right_label": "A = ∞"}}]},
        {"beat_id": "b005", "intent": "build_intuition",
         "importance": "high",
         "narration": "Gabriel's Horn: volume π, surface infinite.",
         "visual_type": "payoff", "duration": 3.0, "transformations": [],
         "objects": [{"id": "payoff_card", "type": "payoff",
                      "properties": {"text": "V = π, A = ∞"}}],
         "semantic_actions": [
             {"action": "measure", "target": "payoff_card",
              "params": {"value": "V = π, A = ∞", "label": "payoff"}}]},
    ]
    world["representation"] = ""
    return {
        "version": "v2",
        "metadata": {"topic": world["topic"], "world": world,
                     "representation": "",
                     "hero_mechanism": {
                         "concept": "painter's paradox",
                         "visualization": "painter_paradox_fill",
                         "target_beat": "b002",
                         "objects": ["horn"], "actions": ["fill"],
                         "why_this_visual": "the paradox in one shot"}},
        "beats": beats,
    }


def _double_text_spec() -> dict:
    """Two text-layer actions in the SAME beat — must fail the gate."""
    spec = _gabriel_spec()
    spec["beats"][1]["semantic_actions"].append(
        {"action": "measure", "target": "horn",
         "params": {"value": "V → π", "label": "limit"}})
    return spec


# ── gate_text_overlap ────────────────────────────────────────────────

def test_gate_passes_postfix_gabriel_spec():
    from engine.qa.gates import gate_text_overlap
    g = gate_text_overlap(_gabriel_spec())
    assert g.passed, g.errors


def test_gate_fails_two_text_layers_same_beat():
    from engine.qa.gates import gate_text_overlap
    g = gate_text_overlap(_double_text_spec())
    assert not g.passed
    assert any("crossfade overlap" in e for e in g.errors)


def test_gate_fails_real_prefix_scene():
    """The analyzer must catch the ACTUAL pre-fix -r3 scene (the artifact
    that produced the garbled t≈13–33s crossfade)."""
    from engine.qa.gates import analyze_text_layer_source
    fixture = Path(__file__).parent / "fixtures" / \
        "prefix_gabriel_world_scene.py"
    if not fixture.exists():  # pragma: no cover
        pytest.skip("pre-fix scene fixture not present")
    errors = analyze_text_layer_source(fixture.read_text(encoding="utf-8"))
    assert errors, "pre-fix scene must fail the text-overlap analyzer"
    assert any("crossfade overlap" in e for e in errors)
    # the first overlap is exactly where the review saw it: the second
    # fill layer entering while the first was still on stage
    assert "b004" in errors[0]


def test_gate_fail_spec_does_not_compile():
    from engine.qa.gates import gate_text_overlap
    g = gate_text_overlap({"version": "v2", "beats": [], "metadata": {}})
    assert not g.passed
    assert g.errors


# ── clean title generation ───────────────────────────────────────────

def test_title_candidates_clean_and_bounded():
    from engine.publishing.metadata import _title_candidates
    topic = "Gabriel's Horn: the shape you can fill but never paint"
    hook = "This shape holds exactly π paint — but can never be painted"
    out = _title_candidates(topic, hook)
    assert len(out) == 3
    assert len(set(out)) == 3
    for t in out:
        assert len(t) <= 60, t
        assert not t.endswith("…"), t          # no mid-word truncation
        assert not t.rstrip().endswith((": ", "| ", "— ")), t
    # the hook survives as a complete claim, never the "…paint: This" cut
    assert any(t.startswith("This shape holds exactly π paint") for t in out)
    assert any(t.startswith("Gabriel's Horn") for t in out)


def test_metadata_titles_bounded_end_to_end():
    from engine.publishing.metadata import generate_metadata
    spec = _gabriel_spec()
    meta = generate_metadata(
        topic=spec["metadata"]["topic"],
        beatsheet={"version": "v1", "beats": spec["beats"],
                   "metadata": {"topic": spec["metadata"]["topic"]}},
    )
    assert len(meta["title_candidates"]) == 3
    assert all(len(t) <= 60 for t in meta["title_candidates"])
    assert all(len(t) <= 60 for t in [meta["title"]])


# ── designed thumbnail ───────────────────────────────────────────────

def test_split_hook_claim_twist():
    from engine.publishing.thumbnail import split_hook
    claim, twist = split_hook(
        "This shape holds exactly π paint — but can never be painted")
    assert claim == "This shape holds exactly π paint"
    assert twist == "can never be painted"
    claim, twist = split_hook("Just one line, no hinge")
    assert twist == ""
    assert claim == "Just one line, no hinge"


def test_compose_designed_thumbnail(tmp_path):
    from PIL import Image
    from engine.publishing.thumbnail import compose_designed_thumbnail
    frame = tmp_path / "frame.png"
    Image.new("RGB", (1920, 1080), (30, 40, 70)).save(frame)
    out = tmp_path / "thumbnail.jpg"
    compose_designed_thumbnail(
        frame_path=str(frame),
        topic="Gabriel's Horn: the shape you can fill but never paint",
        hook="This shape holds exactly π paint — but can never be painted",
        out_path=str(out))
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (1280, 720)


def test_compose_designed_thumbnail_no_frame(tmp_path):
    from PIL import Image
    from engine.publishing.thumbnail import compose_designed_thumbnail
    out = tmp_path / "thumbnail.jpg"
    compose_designed_thumbnail(frame_path=None, topic="Some topic",
                               hook="A claim — but a twist",
                               out_path=str(out))
    with Image.open(out) as im:
        assert im.size == (1280, 720)


def test_emit_packaging_designed_thumbnail(tmp_path):
    """Wave-1 wiring: emit_packaging must produce the DESIGNED thumbnail,
    not a raw (possibly garbled) video frame."""
    import numpy as np
    from engine.cli.autonomous import emit_packaging

    def _make_video(path: Path) -> None:
        import subprocess
        import shutil as sh
        ffmpeg = sh.which("ffmpeg")
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi",
             "-i", "testsrc=size=1280x720:rate=10:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True)

    video = tmp_path / "final.mp4"
    _make_video(video)
    spec = _gabriel_spec()
    out = emit_packaging(tmp_path, spec["metadata"]["topic"],
                         spec["beats"], spec, video_path=video,
                         qa_report={"passed": True, "score": 95})
    meta = json.loads((tmp_path / "youtube_metadata.json").read_text())
    assert len(meta["title_candidates"]) == 3
    assert all(len(t) <= 60 for t in meta["title_candidates"])
    thumb = Path(out["thumbnail"])
    assert thumb.exists()
    from PIL import Image
    with Image.open(thumb) as im:
        assert im.size == (1280, 720)
        # designed thumbnails differ from any raw frame: the headline
        # paints near-white pixels into the lower-left quadrant
        arr = np.asarray(im.convert("RGB"))
    region = arr[520:, 60:900]
    assert (region > 200).all(axis=-1).mean() > 0.01
