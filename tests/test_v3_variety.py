"""Wave-3 tests: variety enforcement (§2B V1–V4).

Run: ./venv/bin/python -m pytest tests/test_v3_variety.py -q
"""

from __future__ import annotations

import pytest

from engine.v3.plan.variety import (
    INTERRUPT_RENDERER,
    MAX_CONSECUTIVE_SAME_RENDERER,
    analyze_variety,
    enforce_variety,
)


def shot(sid, renderer="AI_IMAGE_MOTION", duration=4.0, composition="wide",
         camera="static", hero=False, narration="n", music_state="ambient",
         text_overlay=None):
    return {
        "version": "v3", "shot_id": sid, "duration_sec": duration,
        "narration_start": 0.0, "narration_end": duration,
        "narrative_role": "escalation", "visual_goal": "g",
        "renderer": renderer, "fallback_renderer": "MOTION_CANVAS",
        "style": "s", "subject": narration, "background": "b",
        "camera": camera, "motion": "m", "composition": composition,
        "text_overlay": text_overlay, "sfx": [], "music_state": music_state,
        "duck_music_db": -12, "generation_priority":
            "hero" if hero else "normal",
        "requirements": {}, "metadata": {"narration": narration},
    }


def test_no_v1_change_needed_for_varied_list():
    shots = [shot("S01", "AI_IMAGE_MOTION"), shot("S02", "MOTION_CANVAS"),
             shot("S03", "PIXIJS")]
    _, changes, report = enforce_variety([dict(s) for s in shots])
    renderer_changes = [c for c in changes if c["field"] == "renderer"]
    assert not renderer_changes
    assert report["max_consecutive_same_renderer"] <= MAX_CONSECUTIVE_SAME_RENDERER


def test_v1_breaks_long_same_renderer_run():
    shots = [shot(f"S0{i}", "STOCK_VIDEO") for i in range(1, 6)]
    _, changes, report = enforce_variety(shots)
    assert report["max_consecutive_same_renderer"] <= MAX_CONSECUTIVE_SAME_RENDERER
    assert any(c["field"] == "renderer" for c in changes)


def test_v1_protects_hero_shots():
    shots = [shot("S01", "STOCK_VIDEO"),
             shot("S02", "STOCK_VIDEO", hero=True),
             shot("S03", "STOCK_VIDEO"),
             shot("S04", "STOCK_VIDEO")]
    _, changes, report = enforce_variety(shots)
    hero_shots = [s for s in shots if s["generation_priority"] == "hero"]
    assert all(s["renderer"] == "STOCK_VIDEO" for s in hero_shots)
    assert report["max_consecutive_same_renderer"] <= 3  # hero run may stay


def test_v2_rewrites_identical_consecutive_compositions():
    shots = [shot("S01", "MOTION_CANVAS", composition="timeline"),
             shot("S02", "MOTION_CANVAS", composition="timeline")]
    _, changes, _ = enforce_variety(shots)
    assert shots[0]["composition"] != shots[1]["composition"] or any(
        c["field"] == "composition" for c in changes)
    assert any(c["field"] == "composition" for c in changes)


def test_v3_alternates_camera():
    shots = [shot("S01", "PIXIJS", camera="slow push in"),
             shot("S02", "PIXIJS", camera="slow push in")]
    enforce_variety(shots)
    assert shots[1]["camera"] != "slow push in"


def test_v4_inserts_pattern_interrupts_when_missing():
    # Every shot differs in renderer but nothing else changes -> few
    # natural interrupts are present; force a monotone variant instead.
    shots = [shot(f"S0{i}", "AI_IMAGE_MOTION",
                  composition=f"comp-{i}", camera=f"cam-{i}",
                  music_state="ambient") for i in range(1, 9)]
    _, changes, report = enforce_variety(shots)
    assert report["pattern_interrupt_count"] >= \
        report["pattern_interrupt_target"]


def test_v4_interrupt_renderer_respects_availability():
    shots = [shot(f"S0{i}", "AI_IMAGE_MOTION", composition=f"c{i}",
                  camera=f"cam{i}") for i in range(1, 8)]
    _, _, report = enforce_variety(
        shots, availability={INTERRUPT_RENDERER: False})
    assert all(s["renderer"] != INTERRUPT_RENDERER for s in shots)


def test_determinism_same_input_same_output():
    shots = [shot(f"S0{i}", "STOCK_VIDEO" if i % 2 else "AI_IMAGE_MOTION")
             for i in range(1, 9)]
    a_shots, a_changes, a_report = enforce_variety(
        [dict(s) for s in shots])
    b_shots, b_changes, b_report = enforce_variety(
        [dict(s) for s in shots])
    assert a_changes == b_changes
    assert a_report["renderer_histogram"] == b_report["renderer_histogram"]
    assert [s["renderer"] for s in a_shots] == [s["renderer"] for s in b_shots]


def test_analyze_variety_counts():
    shots = [shot("S01", "A"), shot("S02", "A"), shot("S03", "B")]
    report = analyze_variety(shots)
    assert report["renderer_histogram"] == {"A": 2, "B": 1}
    assert report["max_consecutive_same_renderer"] == 2
