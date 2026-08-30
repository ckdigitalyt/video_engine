"""test_motion_toolkit.py — §16 subject-motion toolkit + §4 micro-event
rendering verification.

Core assertion (phase-4 deliverable 2): a synthetic event shot rendered
through the AI_IMAGE_MOTION (ffmpeg) path with toolkit micro-event ops
scores well above a pure-zoom (Ken Burns only) shot on the v4 audit's
discrete-event metric — the phase-3 failure (0 scene-internal events) must
be structurally impossible now.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.v4.motion_toolkit import (  # noqa: E402
    canvas_event_cues,
    kenburns_ops,
    micro_event_ops,
    plan_primitive,
    render_overlay,
)


def _audit_mod():
    spec = importlib.util.spec_from_file_location(
        "v4_audit", PROJECT_ROOT / "tools" / "v4_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AUDIT = _audit_mod()

MICRO = [
    {"t": 0.4, "duration": 1.0, "event": "sunlight breaks through the smoke",
     "kind": "lighting_change", "intensity": 0.8},
    {"t": 1.4, "duration": 0.8, "event": "shockwave impact flash",
     "kind": "impact", "intensity": 0.9},
]


# ── determinism (§16 contract) ───────────────────────────────────────────────

def test_plan_primitive_deterministic():
    a = plan_primitive("flock", seed=42, duration=2.0, fps=30, intensity=0.7)
    b = plan_primitive("flock", seed=42, duration=2.0, fps=30, intensity=0.7)
    assert a.spec == b.spec
    assert a.blend == b.blend == "multiply"
    c = plan_primitive("shake", seed=42, duration=2.0, fps=30)
    assert c.category == "camera"
    assert np.array_equal(c.curve["dx"], plan_primitive(
        "shake", seed=42, duration=2.0, fps=30).curve["dx"])


def test_plan_primitive_rejects_unknown_kind():
    with pytest.raises(ValueError):
        plan_primitive("teleport", seed=1, duration=1.0, fps=30)


def test_micro_event_ops_deterministic_and_spaced():
    ops1 = micro_event_ops(MICRO, duration=6.0, fps=30, seed=7,
                           fill_spacing=2.2)
    ops2 = micro_event_ops(MICRO, duration=6.0, fps=30, seed=7,
                           fill_spacing=2.2)
    assert ops1 == ops2
    strong = [o["center"] for o in ops1
              if o["op"] in ("lighting_step", "flash", "grade_swap",
                             "zoom_kick", "shake")]
    assert strong, "event ops must produce strong discrete events"
    # anti-hold: no gap between strong events (plus shot bounds) > 2.2 s
    marks = [0.0] + sorted(strong) + [6.0 * 30]
    for a, b in zip(marks, marks[1:]):
        assert b - a <= 2.2 * 30 + 1e-6


def test_micro_event_ops_guarantee_a_strong_event():
    # a shot with ONLY overlay-ish cues still gets one strong event
    ops = micro_event_ops(
        [{"t": 0.5, "duration": 1.0, "event": "dust rises",
          "kind": "environment_change", "intensity": 0.5}],
        duration=4.0, fps=30, seed=3)
    assert any(o["op"] == "lighting_step" for o in ops)


def test_canvas_event_cues_frame_timed():
    ops = micro_event_ops(MICRO, duration=4.0, fps=30, seed=1)
    cues = canvas_event_cues(ops, 30)
    assert cues
    for c in cues:
        assert 0 <= c["start"] < c["end"] <= 4.0 * 30 + 2


# ── overlay rendering (deterministic bytes) ─────────────────────────────────

def test_render_overlay_deterministic(tmp_path):
    plan = plan_primitive("rain", seed=9, duration=1.0, fps=24, intensity=0.8)
    p1 = render_overlay(plan, tmp_path / "a.mp4")
    p2 = render_overlay(plan, tmp_path / "b.mp4")
    assert p1.read_bytes() == p2.read_bytes()


def test_multiply_overlay_is_inverted(tmp_path):
    plan = plan_primitive("flock", seed=5, duration=1.0, fps=24)
    # multiply layers store 255 = background untouched
    frames = AUDIT.decode_frames(render_overlay(plan, tmp_path / "f.mp4"))
    assert float(frames.max()) > 240  # mostly-untouched background


# ── §4 core: event shot >> pure-zoom shot on the audit metric ───────────────

@pytest.mark.slow
def test_event_shot_outruns_pure_zoom_on_audit(tmp_path):
    from engine.renderers.media.kenburns import render_kenburns

    still = tmp_path / "still.png"
    _make_test_still(still)

    zoom_clip = render_kenburns(
        still, tmp_path / "zoom.mp4", duration=3.0, fps=24)
    ops = micro_event_ops(MICRO, duration=3.0, fps=24, seed=11)
    events = kenburns_ops(ops, duration=3.0, fps=24, work_dir=tmp_path)
    event_clip = render_kenburns(
        still, tmp_path / "event.mp4", duration=3.0, fps=24, events=events,
        overlays=events.get("overlays") or [])

    za = AUDIT.audit_video(zoom_clip)
    ea = AUDIT.audit_video(event_clip)
    assert za["visual_event_density"]["events"] == 0, \
        "a pure-zoom shot must score 0 discrete events (the §2 failure)"
    assert ea["visual_event_density"]["events"] >= 1, \
        "the same still with toolkit micro-event ops must spike >= 1 event"
    assert (ea["visual_event_density"]["mean_delta"]
            > za["visual_event_density"]["mean_delta"])


def _make_test_still(path: Path) -> None:
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "gradients=s=1280x720:c0=0x203050:c1=0xd0c0a0",
         "-frames:v", "1", str(path)],
        check=True, capture_output=True)


# ── gate refinement: shot-design metadata (deliverable 3) ───────────────────

def _hold_gate(shots, shot_audits, approvals, master_holds=None):
    ma = {
        "static_holds": {
            "total_hold_sec": 0.0,
            "holds_over_2_5s": master_holds or [],
        },
        "visual_event_density": {"duration_sec": 10.0},
    }
    from engine.v4.gates import static_hold_gate
    return static_hold_gate(ma, shot_audits, approvals,
                            shot_bounds={"S01": (0, 10)})


def test_static_hold_approval_respects_max_sec():
    shots = [{"shot_id": "S01", "design": {"approved_hold": {
        "max_sec": 3.0, "justification": "explanatory hold, §3"}}}]
    audits = {"S01": {"static_holds": {
        "total_hold_sec": 2.8,
        "holds_over_2_5s": [{"duration_sec": 2.8, "start_sec": 1.0}]}}}
    gate = _hold_gate(shots, audits, {
        "S01": {"max_sec": 3.0, "justification": "explanatory hold, §3"}})
    assert gate["pass"] and "explanatory hold" in gate["detail"]

    # hold beyond the approved max stays an offender
    audits["S01"]["static_holds"]["holds_over_2_5s"] = [
        {"duration_sec": 4.0, "start_sec": 1.0}]
    gate2 = _hold_gate(shots, audits, {
        "S01": {"max_sec": 3.0, "justification": "x"}})
    assert not gate2["pass"]


def test_static_hold_unapproved_shot_fails():
    audits = {"S12": {"static_holds": {
        "total_hold_sec": 8.9,
        "holds_over_2_5s": [{"duration_sec": 8.9, "start_sec": 0.2}]}}}
    gate = _hold_gate([{"shot_id": "S12"}], audits, {})
    assert not gate["pass"]
    assert any("S12" in o for o in gate["unapproved"])


def test_text_card_dark_atmospheric_exclusion():
    from engine.v4.gates import text_card_overuse_gate

    master = {"black_flat": {"flat_fraction": 0.20},
              "visual_event_density": {"duration_sec": 100.0}}
    shots = [
        {"shot_id": "S06", "design": {"dark_atmospheric": {
            "justification": "continent-scale fire at dusk — intentional "
                             "dark grade, shot design not a text card"}}},
        {"shot_id": "S07"},
    ]
    audits = {
        "S06": {"black_flat": {"flat_sec": 12.0}},
        "S07": {"black_flat": {"flat_sec": 5.0}},
    }
    gate = text_card_overuse_gate(master, shots, audits)
    # (12 + 5 - 12) / 100 = 5% < 10% → the designed dark shot is excluded
    assert gate["flat_fraction"] == pytest.approx(0.05)
    assert gate["pass"]
    assert "S06" in gate["detail"] and "rule" in gate["detail"]
    # without per-shot audits the raw fraction is reported unmodified
    raw = text_card_overuse_gate(master, shots, None)
    assert raw["flat_fraction"] == pytest.approx(0.20)
    assert not raw["pass"]
