"""Wave-2 improvement tests (glm_review_v3 §4, 2026-08-28).

Covers: continuous scene-param tweening + frame-diff motion gate,
local soundtrack synthesis + ducking, closure gate + Gabriel end card,
fade hardening + thumbnail-candidate exclusion, packaging QA, the '..'
script-join fix, phrase-boundary captions, and the palette fixes.
"""

from __future__ import annotations

import json
import math
import subprocess
import wave
from pathlib import Path

import pytest

from engine.visuals.tween import (
    build_param_timelines, ease_smoothstep, frame_diff_ratios,
    sample_param, static_windows, tween_statements_for_beat,
)
from engine.qa.fade import (
    MAX_FADE_S, alpha_weighted_contrast, clamp_fade,
    fade_windows_from_spec, in_fade_window, passes_fade_contrast,
    safe_timestamp, thumbnail_candidate_times,
)
from engine.qa.gates import gate_closure, gate_frame_diff
from engine.audio.soundtrack import (
    build_soundtrack, sfx_cues_from_beats, synthesize_music_bed,
    synthesize_sfx,
)
from engine.visuals.world_director import build_visualspec
from engine.world.world_model import WorldState


# ── helpers ────────────────────────────────────────────────────────────
def _gabriel_world() -> WorldState:
    return WorldState.from_dict({
        "topic": "gabriel's horn",
        "entities": [
            {"id": "horn", "type": "horn", "properties": {}},
            {"id": "paint", "type": "medium", "properties": {}},
            {"id": "payoff_card", "type": "text", "properties": {}},
        ],
        "hero_mechanism": {"concept": "painter's paradox",
                           "visualization": "painter_paradox_fill",
                           "objects": ["horn"]},
    })


def _make_video(tmp_path: Path, moving: bool) -> Path:
    """Tiny synthetic clip: static color or animated testsrc (ffmpeg)."""
    out = tmp_path / ("moving.mp4" if moving else "static.mp4")
    src = "testsrc=size=128x72:rate=4:duration=3" if moving else \
          "color=c=navy:size=128x72:rate=4:duration=3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src,
                    "-pix_fmt", "yuv420p", str(out)], check=True,
                   capture_output=True)
    return out


# ── 1. MOTION: tween contract ─────────────────────────────────────────
def test_schema_accepts_scene_params():
    from engine.validation.schema import validate_visualspec_v2
    vs = {"version": "v2", "beats": [{
        "beat_id": "b001", "intent": "hook", "objects": [],
        "transformations": [], "start": 0.0, "end": 2.0, "duration": 2.0,
        "scene_params": [{"param": "fill_level", "from": 0.0, "to": 1.0,
                          "ease": "smooth"}],
    }]}
    assert validate_visualspec_v2(vs) == []


def test_tween_timeline_chains_and_samples():
    vs = {"beats": [
        {"start": 0.0, "end": 2.0,
         "scene_params": [{"param": "fill_level", "to": 0.5}]},
        {"start": 2.0, "end": 4.0,
         "scene_params": [{"param": "fill_level", "to": 1.0}]},
    ]}
    tracks = build_param_timelines(vs)
    assert sample_param(tracks, "fill_level", 0.0) == pytest.approx(0.0)
    assert sample_param(tracks, "fill_level", 1.0) > 0.2   # mid-beat motion
    assert sample_param(tracks, "fill_level", 2.0) == pytest.approx(0.5)
    assert sample_param(tracks, "fill_level", 3.0) > 0.6   # still moving
    assert sample_param(tracks, "fill_level", 4.0) == pytest.approx(1.0)
    assert sample_param(tracks, "fill_level", 9.0) == pytest.approx(1.0)


def test_ease_bounds_and_smoothstep():
    assert ease_smoothstep(-0.5) == 0.0
    assert ease_smoothstep(1.5) == 1.0
    assert ease_smoothstep(0.5) == pytest.approx(0.5)
    assert ease_smoothstep(0.25) < 0.25  # ease-in shape


def test_static_window_detector():
    # 4 fps: 8 consecutive samples below floor == 2s static window
    ratios = [0.5, 0.0001] * 4 + [0.0001] * 8 + [0.5]
    bad = static_windows(ratios, sample_fps=4.0, window_s=1.5)
    assert len(bad) == 1
    assert bad[0][1] - bad[0][0] >= 1.5


def test_frame_diff_ratios_pure():
    w, h = 8, 6
    f1 = bytes([0] * (w * h))
    f2 = bytes([255] * (w * h))
    out = frame_diff_ratios([f1, f2, f2], w, h)
    assert out[0] == pytest.approx(1.0)
    assert out[1] == pytest.approx(0.0)


def test_gate_frame_diff_fails_static_video(tmp_path):
    v = _make_video(tmp_path, moving=False)
    g = gate_frame_diff(v)
    assert not g.passed
    assert any("static window" in e or "near-zero motion" in e
               for e in g.errors)


def test_gate_frame_diff_passes_moving_video(tmp_path):
    v = _make_video(tmp_path, moving=True)
    g = gate_frame_diff(v)
    assert g.passed, g.errors


def test_compiler_emits_tween_param():
    from engine.renderers.manim.world_compiler import emit_world_scene
    vs = _gabriel_spec_with_tween()
    src = emit_world_scene(vs, "TweenScene")
    assert "tween_param(self, 'fill_level', 0.75" in src
    assert "ValueTracker" in src
    assert "_apply_param" in src


def _gabriel_spec_with_tween() -> dict:
    vs = build_visualspec("gabriel's horn", _gabriel_world())
    vs["beats"][3]["scene_params"] = [{"param": "fill_level", "to": 0.75,
                                       "ease": "smooth"}]
    return vs


# ── 2. AUDIO: local soundtrack ────────────────────────────────────────
def test_synthesized_bed_duration(tmp_path):
    wav = synthesize_music_bed(3.0, tmp_path / "bed.wav")
    with wave.open(str(wav)) as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
    assert abs(frames / rate - 3.0) < 0.1


def test_synthesized_sfx_kinds(tmp_path):
    for kind in ("whoosh", "pour", "pop", "sting"):
        wav = synthesize_sfx(kind, tmp_path / f"{kind}.wav")
        assert wav.exists() and wav.stat().st_size > 1000
    with pytest.raises(ValueError):
        synthesize_sfx("guitar", tmp_path / "x.wav")


def test_sfx_cues_keyed_to_beats():
    vs = build_visualspec("gabriel's horn", _gabriel_world())
    cues = sfx_cues_from_beats(vs["beats"])
    kinds = [c["type"] for c in cues]
    assert 3 <= len(cues) <= 4
    assert kinds[-1] == "sting"          # end card
    assert kinds[0] in ("whoosh", "pour", "pop")
    # times strictly increasing and inside the video duration
    times = [c["time"] for c in cues]
    assert times == sorted(times)
    total = sum(b.get("duration", 0.0) or (b.get("end", 0.0)
                                           - b.get("start", 0.0))
                for b in vs["beats"])
    assert times[-1] <= total + 0.01


def test_build_soundtrack_mixes_locally(tmp_path):
    from engine.audio.timeline import measure_loudness
    bed = synthesize_music_bed(3.0, tmp_path / "voice.wav")  # stand-in VO
    cues = [{"time": 0.5, "type": "pop", "volume": 1.0},
            {"time": 2.0, "type": "sting", "volume": 1.0}]
    out = build_soundtrack(bed, cues, total_duration=3.0,
                           out_aac=tmp_path / "st.aac", workdir=tmp_path)
    assert out.exists()
    m = measure_loudness(out)
    assert m["integrated_lufs"] is not None


# ── 3. CLOSURE: hero survives to the last frame ───────────────────────
def test_gabriel_end_card_keeps_hero():
    vs = build_visualspec("gabriel's horn", _gabriel_world())
    last = vs["beats"][-1]
    ids = {o["id"] for o in last["objects"]}
    assert "horn" in ids
    # end card content: paradox numbers + question bait narration
    texts = " ".join(str(o.get("value", "")) for o in last["objects"])
    acts = json.dumps(last.get("semantic_actions", []), ensure_ascii=False)
    assert "π" in texts + acts and "∞" in texts + acts
    assert "paint" in last["narration"].lower()
    assert not (last.get("composition") or {}).get("exits")


def test_gate_closure_passes_gabriel_spec():
    vs = build_visualspec("gabriel's horn", _gabriel_world())
    g = gate_closure(vs)
    assert g.passed, g.errors


def test_gate_closure_fails_hero_removal():
    vs = build_visualspec("gabriel's horn", _gabriel_world())
    last = vs["beats"][-1]
    last["objects"] = [o for o in last["objects"] if o["id"] != "horn"]
    last["composition"] = {"beat_id": last["beat_id"], "pacing": "release",
                           "attention_metrics": {}, "exits": ["horn"]}
    g = gate_closure(vs)
    assert not g.passed
    assert any("hero" in e.lower() for e in g.errors)


# ── 4. TRANSITIONS: fade hardening ────────────────────────────────────
def test_clamp_fade_bound():
    assert clamp_fade(2.0) == MAX_FADE_S
    assert clamp_fade(0.4) == MAX_FADE_S
    assert clamp_fade(0.01) >= 0.05
    assert MAX_FADE_S <= 0.4


def test_fade_windows_and_thumbnail_exclusion():
    vs = {"beats": [
        {"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 10.0},
        {"start": 10.0, "end": 15.0},
    ]}
    windows = fade_windows_from_spec(vs)
    assert in_fade_window(5.0, windows)
    assert not in_fade_window(7.5, windows)
    cands = thumbnail_candidate_times(15.0, n=5, exclude=windows)
    assert all(not in_fade_window(c, windows) for c in cands)
    assert len(cands) == 5


def test_safe_timestamp_moves_out_of_fade():
    windows = [(4.6, 5.4)]
    ts = safe_timestamp(5.0, windows, total_duration=20.0)
    assert not in_fade_window(ts, windows)


def test_alpha_weighted_contrast_rules():
    # dark-gray ghost (fg 0.3) on navy (bg 0.08) at partial opacity
    assert not passes_fade_contrast(0.30, 0.08, 0.5)   # the t≈28.5s ghost
    assert passes_fade_contrast(1.0, 0.08, 0.5)        # white text ok
    assert passes_fade_contrast(0.30, 0.08, 0.02)      # too faint to sample


# ── 5. PACKAGING: dedicated thumbnail ────────────────────────────────
def test_designed_thumbnail_no_caption_band(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    from engine.publishing.thumbnail import compose_designed_thumbnail
    # source frame with a bright 'caption' band at the bottom
    frame = tmp_path / "frame.png"
    img = Image.new("RGB", (1280, 720), (10, 15, 26))
    for x in range(1280):
        for y in range(600, 720):
            img.putpixel((x, y), (255, 255, 255))
    img.save(frame)
    out = tmp_path / "thumb.jpg"
    compose_designed_thumbnail(frame_path=str(frame), topic="Test",
                               hook="Claim — twist", out_path=str(out))
    thumb = Image.open(out).convert("RGB")
    # the bottom rows under the headline block must not be the raw white
    # caption band (headline + navy gradient cover it; check corner)
    px = thumb.getpixel((1270, 715))
    assert px != (255, 255, 255)


def test_qa_thumbnail_composition_rules(tmp_path):
    from engine.publishing.thumbnail import qa_thumbnail_composition
    missing = qa_thumbnail_composition(str(tmp_path / "nope.jpg"), ["x"], [])
    assert not missing["passed"]
    pytest.importorskip("PIL")
    from PIL import Image
    p = tmp_path / "t.png"
    Image.new("RGB", (1280, 720), (0, 0, 0)).save(p)
    ok = qa_thumbnail_composition(str(p), ["THIS IS THE HEADLINE"], [])
    assert ok["passed"], ok["errors"]
    empty = qa_thumbnail_composition(str(p), [], [])
    assert not empty["passed"]


def test_vision_hook_off_by_default(tmp_path):
    from engine.publishing.thumbnail import vision_score_thumbnail
    assert vision_score_thumbnail(str(tmp_path / "x.jpg")) is None


# ── 6. SCRIPT: '..' join fix + phrase-boundary captions ──────────────
def test_narration_join_no_double_period():
    from engine.cli.autonomous import _join_script_narration
    script = [{"narration": "First sentence."},
              {"narration": "Second one."},
              {"narration": "Third."}]
    out = _join_script_narration(script, fallback="topic")
    assert out == "First sentence. Second one. Third."
    assert ".." not in out


def test_caption_chunks_hit_phrase_boundaries():
    from engine.cli.run import _caption_entries_sequential
    words = [{"word": w, "start": 0.0, "end": 12.0} for w in
             ("fill", "it", "with", "paint,", "but", "never", "more")]
    entries = _caption_entries_sequential(words, max_words=4)
    assert len(entries) >= 2
    assert entries[0]["text"].endswith("paint,")  # boundary slid to comma
    # no overlap
    for a, b in zip(entries, entries[1:]):
        assert a["end"] <= b["start"] + 1e-6


# ── 7. COLOR: gold accent + label contrast ────────────────────────────
def test_horn_label_is_high_contrast_white():
    import inspect
    from engine.primitives import world_primitives as WP
    src = inspect.getsource(WP.HornProfile)
    assert '"#F5F7FA"' in src or "#F5F7FA" in src


def test_paint_fill_pulse_is_scale_only():
    import inspect
    from engine.primitives import world_primitives as WP
    src = inspect.getsource(WP.PaintFill)
    assert "Indicate(fill" not in src            # no yellow recolor flicker
    assert "there_and_back" in src
