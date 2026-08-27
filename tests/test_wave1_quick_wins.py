"""Wave-1 quick wins (2026-08-27) — review docs/review_viral_platform_2026-08-27.md.

- A: black-opening root cause (manim `background_colour` is a silent no-op;
  the generated scene never actually left pure black) + end-to-end render
  check that a minimal world spec has NO dark run > 0.5s.
- B: per-beat pre-concat QA (beat_luma.json, one re-render on black-clip).
- C: post-render retry (no silent REPAIR dead end: PASS or ABORT).
- D: state hygiene (learning call, record_topic gating, repo-root topic
  history, idempotent run dirs).
- E: packaging wiring (youtube_metadata.json + thumbnail.jpg on PASS).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from engine.cli import run as cli_run
from engine.cli.run import (
    _annotate_beat_luma,
    _render_scene,
    _sample_luma,
    _write_beat_luma,
)
from engine.qa import gates as qa_gates
from engine.renderers.manim.world_compiler import (
    compile_world_to_file,
    emit_world_scene,
)
from engine.validation.schema import validate_visualspec_v2
from engine.visuals.world_director import build_visualspec
from engine.world.knowledge import build_world

TOPIC = "Why is the sky blue?"
# pre-existing primitive quirk: sky-blue spec beats crash MeasureValue on
# '100 km'; the popcorn spec renders cleanly — used for the pixel test.
RENDER_TOPIC = "Why does popcorn pop?"
RES = (1280, 720)


# ── helpers ───────────────────────────────────────────────────────────
def _tiny_spec(topic: str = TOPIC, n_beats: int = 2, beat_dur: float = 2.5):
    """Minimal-but-real v2 spec: first n beats of a known topic, re-timed."""
    world = build_world(topic)
    vs = build_visualspec(topic, world)
    vs["beats"] = vs["beats"][:n_beats]
    t = 0.0
    for b in vs["beats"]:
        b["start"] = round(t, 2)
        b["duration"] = beat_dur
        b["end"] = round(t + beat_dur, 2)
        t += beat_dur
    return vs


def _make_video(path: Path, color: str, seconds: float = 3.0,
                size: str = "320x180") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c={color}:s={size}:d={seconds}:r=4",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    return path


def _fake_manim_bin(tmp_path: Path, color: str = "black") -> Path:
    """A fake `manim` executable that just copies a prepared clip into the
    media dir (lets us exercise _render_scene's retry logic cheaply)."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    clip_src = _make_video(tmp_path / f"src_{color}.mp4", color)
    script = bin_dir / "manim"
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        media=""
        prev=""
        for a in "$@"; do
          if [ "$prev" = "--media_dir" ]; then media="$a"; fi
          prev="$a"
        done
        mkdir -p "$media/videos/fake"
        cp "{clip_src}" "$media/videos/fake/WorldScene.mp4"
        """))
    script.chmod(0o755)
    return bin_dir


# ── A: black-opening root cause ───────────────────────────────────────
def test_compiler_pins_navy_background_color():
    """The Gabriel's Horn 0-8s black opening root cause: manim 0.20.1 has
    no `background_colour` attribute — the assignment was a silent no-op
    and every scene rendered on pure black.  The generated scene must set
    the correctly-spelled `background_color` before Scene instantiation."""
    vs = _tiny_spec()
    src = emit_world_scene(vs, "WorldScene")
    assert '_manim_config.background_color = "#0b0f1a"' in src
    assert 'self.camera.background_color = "#0b0f1a"' in src
    # no executable assignment with the (nonexistent) British spelling
    assert "background_colour =" not in src


def test_minimal_world_spec_renders_no_dark_runs(tmp_path):
    """End-to-end: a tiny 2-beat world spec rendered at 720p must contain
    NO contiguous dark run > 0.5s (gate_black_frames passes on the clip)."""
    vs = _tiny_spec(RENDER_TOPIC)
    assert validate_visualspec_v2(vs) == []
    scene_file = tmp_path / "world_scene.py"
    compile_world_to_file(vs, scene_file, "WorldScene")
    clip = _render_scene(scene_file, "WorldScene", tmp_path / "work",
                         RES, 30)
    assert clip.exists()
    gate = qa_gates.gate_black_frames(clip)
    assert gate.passed, gate.errors
    bl = json.loads((tmp_path / "work" / "beat_luma.json").read_text())
    assert bl["attempts"] == 1
    assert bl["min_luma"] >= 0.02


# ── B: per-beat pre-concat QA ─────────────────────────────────────────
def test_sample_luma_and_beat_annotation(tmp_path):
    black = _make_video(tmp_path / "black.mp4", "black")
    white = _make_video(tmp_path / "white.mp4", "white")
    assert max(_sample_luma(black)) < 0.02
    assert min(_sample_luma(white)) > 0.5
    assert not qa_gates.gate_black_frames(black).passed
    assert qa_gates.gate_black_frames(white).passed

    p = _write_beat_luma(tmp_path, white)
    _annotate_beat_luma(p, [{"beat_id": "b001", "start": 0.0, "end": 1.5},
                            {"beat_id": "b002", "start": 1.5, "end": 3.0}])
    doc = json.loads(p.read_text())
    assert [b["beat_id"] for b in doc["per_beat"]] == ["b001", "b002"]
    assert all(b["min_luma"] > 0.5 for b in doc["per_beat"])


def test_render_scene_retries_once_then_raises(tmp_path, monkeypatch):
    """A clip that still fails the black-frame gate after ONE re-render
    (cache purged each time) must fail loudly — never reach the compositor."""
    bin_dir = _fake_manim_bin(tmp_path, color="black")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    with pytest.raises(RuntimeError, match="after 1 re-render"):
        _render_scene(tmp_path / "scene.py", "WorldScene",
                      tmp_path / "work", RES, 30)
    bl = json.loads((tmp_path / "work" / "beat_luma.json").read_text())
    assert bl["attempts"] == 2
    assert bl["errors"], "offending time ranges must be recorded"


def test_render_scene_accepts_clean_clip(tmp_path, monkeypatch):
    bin_dir = _fake_manim_bin(tmp_path, color="white")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    clip = _render_scene(tmp_path / "scene.py", "WorldScene",
                         tmp_path / "work", RES, 30)
    assert clip.exists()
    bl = json.loads((tmp_path / "work" / "beat_luma.json").read_text())
    assert bl["attempts"] == 1
    assert bl["errors"] == []


# ── C: post-render retry (no silent REPAIR dead end) ──────────────────
def _qa_report(passed: bool) -> dict:
    return {"passed": passed, "score": 95 if passed else 40,
            "video": "", "errors": [] if passed else
            ["black frames: contiguous run 0.00s-8.00s (8.00s) with mean "
             "luma 0.0094 < 0.02"]}


def test_render_retry_recovers_pass(tmp_path, monkeypatch):
    from engine.cli import autonomous
    calls = []

    def fake_run_autonomous(topic, out, **kw):
        calls.append(1)
        return _qa_report(len(calls) > 1)

    monkeypatch.setattr(autonomous, "run_autonomous", fake_run_autonomous)
    from engine.daily_run import run_daily
    r = run_daily(topic=TOPIC, out_root=tmp_path, render=True,
                  history_base=tmp_path)
    assert r.outcome == "PASS"
    assert len(calls) == 2, "exactly ONE render retry"
    assert "after 1 retry" in r.outcome_reason


def test_render_retry_exhausts_to_abort(tmp_path, monkeypatch):
    from engine.cli import autonomous
    calls = []

    def fake_run_autonomous(topic, out, **kw):
        calls.append(1)
        return _qa_report(False)

    monkeypatch.setattr(autonomous, "run_autonomous", fake_run_autonomous)
    from engine.daily_run import run_daily
    r = run_daily(topic=TOPIC, out_root=tmp_path, render=True,
                  history_base=tmp_path)
    assert len(calls) == 2, "exactly ONE render retry"
    assert r.outcome == "ABORT"
    assert not r.qa_passed
    assert r.errors, "QA errors must surface in result.errors"
    assert "retry" in r.outcome_reason


# ── D: state hygiene ──────────────────────────────────────────────────
def test_learning_record_is_real_on_plan_only(tmp_path):
    from engine.daily_run import run_daily
    r = run_daily(topic=TOPIC, out_root=tmp_path, history_base=tmp_path)
    assert r.outcome == "PASS"
    rec = json.loads((tmp_path / "learning.json").read_text())
    # the old bug: dict passed as Critique -> AttributeError -> 'not_run'
    assert rec.get("status") != "not_run"
    assert rec.get("topic") == TOPIC


def test_record_topic_only_on_pass(tmp_path, monkeypatch):
    import engine.daily_run as dr
    seen = []
    monkeypatch.setattr(dr, "record_topic",
                        lambda topic, cat, base=None: seen.append(topic))
    # unknown topic -> no facts -> ABORT -> must NOT be recorded
    r = dr.run_daily(topic="Wobblefish quantum flair",
                     out_root=tmp_path / "a", history_base=tmp_path)
    assert r.outcome == "ABORT"
    assert seen == []
    # known topic, plan-only PASS -> recorded exactly once
    dr.run_daily(topic=TOPIC, out_root=tmp_path / "b", history_base=tmp_path)
    assert seen == [TOPIC]


def test_run_dir_never_overwritten(tmp_path):
    from engine.daily_run import run_daily
    r1 = run_daily(topic=TOPIC, out_root=tmp_path / "run",
                   history_base=tmp_path)
    first_report = (tmp_path / "run" / "daily_report.json").read_text()
    r2 = run_daily(topic=TOPIC, out_root=tmp_path / "run",
                   history_base=tmp_path)
    assert Path(r1.artifacts_dir).name == "run"
    assert Path(r2.artifacts_dir).name == "run-r2"
    # previous run's artifacts untouched
    assert (tmp_path / "run" / "daily_report.json").read_text() == first_report


def test_topic_history_defaults_to_repo_root():
    from engine.scout import topic_scout
    assert topic_scout._history_path() == (
        topic_scout.REPO_ROOT / "topic_history.json")
    # explicit base still honoured
    p = topic_scout._history_path(Path("/tmp"))
    assert str(p).startswith("/tmp")


def test_record_topic_explicit_base(tmp_path):
    from engine.scout.topic_scout import record_topic
    record_topic("test topic", "science", base=tmp_path)
    hist = json.loads((tmp_path / "topic_history.json").read_text())
    assert "test topic" in hist["recent"]


# ── E: packaging wiring ───────────────────────────────────────────────
def test_emit_packaging_metadata_and_thumbnail(tmp_path):
    from engine.cli.autonomous import emit_packaging
    video = _make_video(tmp_path / "final.mp4", "cyan", seconds=4.0)
    vs = _tiny_spec()
    beats = vs["beats"]
    out = emit_packaging(tmp_path, TOPIC, beats, vs, video_path=video,
                         qa_report={"passed": True, "score": 95})
    meta = json.loads((tmp_path / "youtube_metadata.json").read_text())
    assert len(meta["title_candidates"]) == 3
    assert all(len(t) <= 100 for t in meta["title_candidates"])
    assert meta["description"]
    assert meta["tags"]
    assert meta["thumbnail"] == "thumbnail.jpg"
    thumb = Path(out["thumbnail"])
    assert thumb.exists()
    from PIL import Image
    with Image.open(thumb) as im:
        assert im.size == (1280, 720)


def test_packaging_wired_into_run_autonomous(tmp_path, monkeypatch):
    from engine.cli import autonomous
    white = _make_video(tmp_path / "white.mp4", "white", seconds=3.0,
                        size="1280x720")
    wav = tmp_path / "n.wav"
    wav.write_bytes(b"")

    monkeypatch.setattr(autonomous, "synthesize_narration",
                        lambda text, d, voice="": (wav, []))
    monkeypatch.setattr(autonomous, "measure_loudness",
                        lambda p: {"integrated_lufs": -14.0,
                                   "true_peak_db": -1.0, "clipping": False})
    monkeypatch.setattr(autonomous, "_render_scene",
                        lambda *a, **k: white)
    monkeypatch.setattr(autonomous, "compose_final",
                        lambda clips, narration=None, music=None,
                        subtitles=None, out=None, **kw:
                        (shutil.copyfile(clips[0], out), {})[1])
    monkeypatch.setattr(autonomous.qa_gates, "run_all_v2",
                        lambda *a, **k: {"passed": True, "score": 95,
                                         "errors": []})
    report = autonomous.run_autonomous(TOPIC, tmp_path / "run",
                                       resolution=RES, render=True)
    assert report["passed"] is True
    assert (tmp_path / "run" / "youtube_metadata.json").exists()
    assert (tmp_path / "run" / "thumbnail.jpg").exists()
    meta = json.loads((tmp_path / "run" / "youtube_metadata.json").read_text())
    assert len(meta["title_candidates"]) == 3
