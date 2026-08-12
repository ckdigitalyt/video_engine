"""v28 regression tests — hook_strength root fix.

The Wow! Signal run failed the publish gate with only 4 distinct visuals in
the first 15s (need >= 5).  Root causes fixed in v28:

  1. the planner capped stills at 2 per scene — the hook scene now plans
     >= HOOK_MIN_SHOTS distinct stills with AI-prompt padding;
  2. coverage variants re-used the same stills — they now rotate through
     ALL distinct scene stills (least-used first);
  3. the hook gate counted render FILES (variants inflate the count while
     showing the same image) — it now counts distinct SOURCE STILLS.

These tests pin the gate metric (3) and the planner budgets (1).
"""

import json
import os
import tempfile

from src.qa.jade_gates import HOOK_MIN_SHOTS, HOOK_WINDOW_S, PublishGate


def _run_hook(entries):
    """Run the hook check against a synthetic timeline file."""
    gate = PublishGate()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"video_timeline": entries}, f)
        path = f.name
    try:
        return gate._check_hook("", path)
    finally:
        os.unlink(path)


def test_hook_gate_counts_source_stills_not_render_files():
    """A variant file of the same still must NOT count as a new visual."""
    entries = [
        {"start_time": 0.0, "file": "s0_a.mp4", "asset": "stills/scene0_0.jpg"},
        {"start_time": 3.5, "file": "s0_b.mp4", "asset": "stills/scene0_1.jpg"},
        # two variants of the SAME stills (old gate counted 4 files)
        {"start_time": 7.0, "file": "s0_var1.mp4", "asset": "stills/scene0_0.jpg"},
        {"start_time": 10.5, "file": "s0_var2.mp4", "asset": "stills/scene0_1.jpg"},
    ]
    r = _run_hook(entries)
    assert r["metrics"]["distinct_in_hook"] == 2
    assert r["passed"] is False


def test_hook_gate_passes_five_distinct_stills():
    entries = [
        {"start_time": 0.0, "file": "s0_a.mp4", "asset": "stills/scene0_0.jpg"},
        {"start_time": 3.0, "file": "s0_b.mp4", "asset": "stills/scene0_1.jpg"},
        {"start_time": 6.0, "file": "s0_c.mp4", "asset": "stills/scene0_2.jpg"},
        {"start_time": 9.0, "file": "s0_d.mp4", "asset": "stills/scene0_3.jpg"},
        {"start_time": 12.0, "file": "s0_e.mp4", "asset": "stills/scene0_4.jpg"},
    ]
    r = _run_hook(entries)
    assert r["metrics"]["distinct_in_hook"] == 5
    assert r["passed"] is True


def test_hook_gate_manim_clips_count_by_filename():
    """Animated beats carry no asset field — they still count as visuals."""
    entries = [
        {"start_time": 0.0, "file": "cache/manim/intro.mp4", "asset": ""},
        {"start_time": 4.0, "file": "cache/manim/beat2.mp4", "asset": ""},
        {"start_time": 8.0, "file": "s0_a.mp4", "asset": "stills/scene0_0.jpg"},
        {"start_time": 11.0, "file": "s0_b.mp4", "asset": "stills/scene0_1.jpg"},
        {"start_time": 14.0, "file": "s0_c.mp4", "asset": "stills/scene0_2.jpg"},
    ]
    r = _run_hook(entries)
    assert r["metrics"]["distinct_in_hook"] == 5
    assert r["passed"] is True


def test_hook_gate_only_counts_within_window():
    """Shots starting at/after the hook window must not inflate the count."""
    entries = [
        {"start_time": 0.0, "file": "s0_a.mp4", "asset": "stills/scene0_0.jpg"},
        {"start_time": 3.0, "file": "s0_b.mp4", "asset": "stills/scene0_1.jpg"},
        {"start_time": 6.0, "file": "s0_c.mp4", "asset": "stills/scene0_2.jpg"},
        # outside the 15s window — should not count
        {"start_time": HOOK_WINDOW_S, "file": "s9_z.mp4", "asset": "stills/scene9_9.jpg"},
    ]
    r = _run_hook(entries)
    assert r["metrics"]["distinct_in_hook"] == 3
    assert r["passed"] is False


def test_hook_min_shots_constant_sane():
    assert HOOK_MIN_SHOTS >= 5
    assert HOOK_WINDOW_S >= 15.0
