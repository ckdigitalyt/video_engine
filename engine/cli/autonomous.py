#!/usr/bin/env python3
"""engine.cli.autonomous — autonomous topic->video pipeline (v0.3 §25–27, §31).

Input: ONLY a topic (no storyboard, no narration, no scene selection).

Stages (each writes deterministic artifacts):
    research (verified facts + sources)
    -> world model (entities/relationships/signals/forces/hero)
    -> representation selection
    -> story template + hero mechanism
    -> script (narration)
    -> local TTS (kokoro first — no network needed)
    -> timed beats (narration is the temporal source of truth)
    -> v2 VisualSpec (semantic actions + explanation scores)
    -> world compiler -> Manim scene
    -> render -> compose (narration + captions + master) -> v2 QA gates
    -> spec-§27 comparison report

Usage:
    python -m engine.cli.autonomous --topic "Why is the sky blue?" --out results/sky_blue
    python -m engine.cli.autonomous --topic "Why is the sky blue?" --no-render  # compile only
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from engine.audio.timeline import synthesize_narration, measure_loudness
from engine.cli.run import (
    _annotate_beat_luma,
    _caption_entries_sequential,
    _peak_usage,
    _probe_audio_duration,
    _render_scene,
    _script_from_words,
    _state_log_from_visualspec,
)
from engine.composition.ffmpeg_compositor import (
    build_contact_sheet,
    compose_final,
    generate_srt,
)
from engine.qa import gates as qa_gates
from engine.renderers.manim.world_compiler import compile_world_to_file
from engine.validation.schema import validate_visualspec_v2, validate_worldmodel
from engine.visuals.world_director import build_visualspec, script_for
from engine.world.actions import ACTION_REGISTRY
from engine.world.knowledge import build_world, research
from engine.world.representations import select_representation
from engine.world.scoring import score_beatsheet
from engine.world.story_templates import select_template
from engine.world.world_model import WorldState


# Primitives promoted from MathMotion Lab v0.2 (provenance tracking, §27).
_FROM_MATHMOTION_LAB = [
    "CelestialBody", "OrbitPath", "MovingBody", "FollowBody", "FallBody",
    "MissBody", "TracePath", "ImpactBurst", "VelocityVector", "ForceVector",
    "ProjectilePath", "CurvePath", "ScatteringField",
]

# Simulation-class actions (counted as simulation beats, §27).
_SIMULATION_ACTIONS = {
    "orbit", "fall", "accelerate", "decelerate", "collide", "miss",
    "oscillate", "scatter", "flow", "branch", "merge", "assemble",
    "disassemble", "trace",
}


def _time_beats(vs: dict, narration_sentences: list[str],
                words: list[dict], narration_dur: float) -> dict:
    """Size each beat to its narration (temporal source of truth, §19/§20).

    Per-sentence timing when word alignment matches the beat order;
    proportional scaling otherwise.  Never freeze-frames a tail.
    """
    beats = vs["beats"]
    if not words or narration_dur <= 0:
        return vs
    order = sorted(words, key=lambda w: w["start"])
    # sentence word counts
    counts = [len(s.split()) for s in narration_sentences]
    total_words = sum(counts)
    if total_words == len(order) and len(counts) == len(beats):
        # aligned: beat i gets sentence i's window + pad
        widx = 0
        for i, beat in enumerate(beats):
            n = counts[i]
            chunk = order[widx:widx + n]
            widx += n
            if chunk:
                dur = max(1.4, chunk[-1]["end"] - chunk[0]["start"] + 0.45)
                beat["duration"] = round(dur, 2)
    else:
        # proportional scale so total animation == narration
        total = sum(float(b.get("duration", 1.5)) for b in beats)
        if total > 0:
            scale = narration_dur / total
            for b in beats:
                b["duration"] = round(max(1.4, float(b.get("duration", 1.5))
                                          * scale), 2)
    # keep total beat duration == narration (±2%): prevents the
    # compositor's black tpad tail (video shorter than narration) that
    # both looks broken and trips the black-frame QA gate
    total = sum(float(b.get("duration", 1.5)) for b in beats)
    if total > 0 and abs(narration_dur - total) > 0.02 * narration_dur:
        scale = narration_dur / total
        for b in beats:
            b["duration"] = round(max(1.4, float(b.get("duration", 1.5))
                                      * scale), 2)
    # recompute start/end + refresh the explanation report (durations feed
    # the text-dominance ratio)
    t = 0.0
    for b in beats:
        b["start"] = round(t, 2)
        b["end"] = round(t + float(b["duration"]), 2)
        t += float(b["duration"])
    vs["metadata"]["explanation_report"] = score_beatsheet(beats).to_dict()
    return vs


def _count_primitives(vs: dict) -> int:
    """Distinct procedural primitives referenced by the spec (via actions)."""
    used = set()
    for b in vs.get("beats", []):
        for a in b.get("semantic_actions", []) or []:
            name = str(a.get("action", a.get("type", "")))
            spec = ACTION_REGISTRY.get(name)
            if spec:
                used.update(spec.primitives)
    return len(used)


def _hero_timestamp(beats: list[dict], vs: dict) -> float:
    """Deterministic hero-frame timestamp (seconds) for the thumbnail.

    Prefers the hero mechanism's target beat; falls back to the beat at
    ~35% of the total duration.  Returns a timestamp 60% into that beat
    so the hero visual is fully on stage.
    """
    if not beats:
        return 0.0
    hero = (vs.get("metadata", {}) or {}).get("hero_mechanism") or {}
    target = str(hero.get("target_beat", ""))
    beat = next((b for b in beats if b.get("beat_id") == target), None)
    if beat is None:
        beat = beats[min(len(beats) - 1, int(len(beats) * 0.35))]
    start = float(beat.get("start", 0.0) or 0.0)
    dur = float(beat.get("duration", 0.0) or 0.0)
    return max(0.0, start + 0.6 * dur)


def emit_packaging(out_dir: str | Path, topic: str, beats: list[dict],
                   vs: dict, video_path: str | Path | None = None,
                   qa_report: dict | None = None) -> dict:
    """Emit deterministic publishing artifacts for a finished run (P0-6).

    Writes ``youtube_metadata.json`` (3 title variants <=100 chars,
    description, tags derived from topic tokens, chapters) and a
    1280x720 ``thumbnail.jpg`` extracted from the hero frame of the
    rendered video (falls back to the deterministic Pillow layout
    thumbnail when the video is unavailable).  No API calls, fully
    deterministic content.

    Returns a small status dict; packaging failures never block a PASS
    video, so callers should treat exceptions as non-fatal.
    """
    from engine.publishing.metadata import (
        MAX_TITLE_CHARS, generate_metadata, save)
    out = Path(out_dir)
    meta = generate_metadata(
        topic=topic,
        beatsheet={"version": "v1", "beats": beats,
                   "metadata": {"topic": topic}},
        qareport=qa_report,
    )
    # YouTube title limit (metadata.py already emits clean <=60-char
    # variants; this clamp is a belt-and-braces guarantee).
    meta["title_candidates"] = [t[:MAX_TITLE_CHARS] for t in
                                meta.get("title_candidates", [])][:3]
    meta["title"] = meta["title_candidates"][0] if meta["title_candidates"] else topic[:MAX_TITLE_CHARS]
    meta["thumbnail"] = "thumbnail.jpg"

    thumb_path = out / "thumbnail.jpg"
    made = False
    if video_path and Path(video_path).exists():
        ts = _hero_timestamp(beats, vs)
        frame_path = out / "_hero_frame.png"
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-ss", f"{ts:.2f}", "-i", str(video_path),
             "-frames:v", "1", "-vf", "scale=1280:720",
             str(frame_path)],
            capture_output=True, text=True)
        if proc.returncode == 0 and frame_path.exists():
            # DESIGNED thumbnail (review 2026-08-27: "never export the
            # thumbnail from a transition frame"): the hero frame dimmed
            # under the navy wash + a hook-derived two-tone headline.
            try:
                from engine.publishing.metadata import _key_narration_phrase
                from engine.publishing.thumbnail import (
                    compose_designed_thumbnail)
                compose_designed_thumbnail(
                    frame_path=str(frame_path), topic=topic,
                    hook=_key_narration_phrase(beats),
                    out_path=str(thumb_path))
                made = thumb_path.exists()
            except Exception:  # noqa: BLE001 — packaging never blocks PASS
                made = False
            if not made:
                # raw hero-frame fallback (previous behavior)
                shutil.copyfile(frame_path, thumb_path)
                made = True
        try:
            frame_path.unlink()
        except OSError:
            pass
    if not made:
        # deterministic Pillow/SVG layout thumbnail fallback
        from engine.publishing.thumbnail import generate_thumbnail
        thumb_path = Path(generate_thumbnail(run_dir=None, topic=topic,
                                             out_dir=str(out)))
    save(meta, str(out), filename="youtube_metadata.json")
    return {"metadata": str(out / "youtube_metadata.json"),
            "thumbnail": str(thumb_path),
            "hero_timestamp_s": round(_hero_timestamp(beats, vs), 2)}


def run_autonomous(topic: str, out_root: str | Path,
                   resolution: tuple[int, int] = (1280, 720), fps: int = 30,
                   render: bool = True,
                   visualspec: dict | None = None) -> dict:
    """Full autonomous topic -> video pipeline.  Returns the QA report +
    the spec-§27 comparison fields.

    ``visualspec`` (optional) lets the §36 daily runner inject a plan
    that already passed preflight + local repair, so the expensive
    render stage never sees a plan that would fail QA (§37 budget).
    """
    t0 = time.time()
    out = Path(out_root)
    out.mkdir(parents=True, exist_ok=True)
    workdir = out / "work"
    workdir.mkdir(parents=True, exist_ok=True)

    # ── 1) research + world + representation + story (autonomous) ──────
    research_result = research(topic)
    world = build_world(topic)
    rep = select_representation(topic)
    plan = select_template(topic, rep.primary)
    hero = world.hero_mechanism
    (out / "research.json").write_text(json.dumps({
        "topic": topic,
        "summary": research_result.summary,
        "facts": [f.__dict__ for f in research_result.facts],
        "sources": research_result.sources,
    }, indent=2))
    (out / "world.json").write_text(json.dumps(world.to_dict(), indent=2))

    # ── 2) script + local TTS (temporal source of truth) ───────────────
    script = script_for(topic, plan.roles, world)
    narration = ". ".join(s["narration"] for s in script if s["narration"])
    if not narration:
        narration = topic
    narration_audio = None
    words: list[dict] = []
    narration_dur = 0.0
    try:
        narration_audio, words = synthesize_narration(
            narration, workdir / "narration", voice="")
        if words:
            narration_dur = max(w["end"] for w in words)
        else:
            narration_dur = _probe_audio_duration(narration_audio)
    except Exception as e:  # noqa: BLE001
        print(f"[tts] narration failed ({e}); proceeding silent")
        narration_audio = None
        words = []
        narration_dur = 0.0

    # ── 3) v2 VisualSpec + timed beats ─────────────────────────────────
    if visualspec is not None:
        # §36/§37: plan already passed preflight + local repair; keep the
        # world/plan artifacts consistent with the injected spec
        vs = dict(visualspec)
        plan_name = (vs.get("metadata", {}) or {}).get(
            "story_template", plan.template_name)
        plan.template_name = plan_name
    else:
        vs = build_visualspec(topic, world, story_plan=plan)
    sentences = [s["narration"] for s in script]
    vs = _time_beats(vs, sentences, words, narration_dur)
    errs = validate_visualspec_v2(vs)
    if errs:
        raise RuntimeError("v2 spec invalid:\n" + "\n".join(errs[:10]))
    errs = validate_worldmodel(vs["metadata"]["world"])
    if errs:
        raise RuntimeError("world invalid:\n" + "\n".join(errs[:10]))
    (out / "visualspec.json").write_text(json.dumps(vs, indent=2))
    (out / "story_plan.json").write_text(json.dumps({
        "template": plan.template_name,
        "rationale": plan.rationale,
        "roles": plan.roles,
        "hero_mechanism": hero.__dict__ if hero else None,
        "representation": rep.primary.value,
        "representation_secondary": [r.value for r in rep.secondary],
    }, indent=2))

    # ── 3b) spec-§5 artifact contract (15 named artifacts) ────────────
    # topic / research / facts / story / hero / visual plan / beats /
    # shots / visualspec / world / audio_timeline / qa / repair / learning
    (out / "topic.json").write_text(json.dumps({"topic": topic}, indent=2))
    (out / "facts.json").write_text(json.dumps(
        [f.__dict__ for f in research_result.facts], indent=2))
    (out / "story.json").write_text(json.dumps({
        "template": plan.template_name,
        "rationale": plan.rationale,
        "roles": plan.roles,
    }, indent=2))
    (out / "hero.json").write_text(json.dumps(
        hero.__dict__ if hero else None, indent=2))
    (out / "visual_plan.json").write_text(json.dumps({
        "representation": rep.primary.value,
        "representation_secondary": [r.value for r in rep.secondary],
        "rationale": rep.rationale,
        "beat_count": len(vs["beats"]),
    }, indent=2))
    (out / "beats.json").write_text(json.dumps(vs["beats"], indent=2))
    shots = []
    for i, b in enumerate(vs["beats"]):
        shots.append({
            "shot_id": f"s{i:03d}",
            "beat_id": b["beat_id"],
            "objects": b["objects"],
            "semantic_actions": b["semantic_actions"],
            "camera": b["camera"],
            "visual_type": b["visual_type"],
        })
    (out / "shots.json").write_text(json.dumps(shots, indent=2))
    (out / "repair_plan.json").write_text(json.dumps(
        {"status": "not_run",
         "note": "Phase E (automatic repair) not yet implemented"},
        indent=2))
    (out / "learning.json").write_text(json.dumps(
        {"status": "not_run",
         "note": "Phase F (learning agent) not yet implemented"},
        indent=2))

    # ── 4) compile ─────────────────────────────────────────────────────
    scene_file = workdir / "world_scene.py"
    scene_name = "WorldScene"
    compile_world_to_file(vs, scene_file, scene_name)

    report: dict = {}
    if render:
        # ── 5) render ────────────────────────────────────────────────
        clip = _render_scene(scene_file, scene_name, workdir, resolution, fps)

        # per-beat luma map artifact (pre-concat QA, P0-2)
        try:
            _annotate_beat_luma(workdir / "beat_luma.json",
                                vs.get("beats", []))
        except Exception as e:  # noqa: BLE001
            print(f"[qa] beat-luma annotation failed: {e}")

        # ── 6) compose: narration + captions + master ─────────────────
        final = out / "final.mp4"
        srt_path = None
        if words:
            order = sorted(words, key=lambda w: w["start"])
            entries = _caption_entries_sequential(order)
            srt_path = generate_srt(entries, workdir / "narration.srt")
            print(f"[tts] narration {narration_audio.name} "
                  f"({len(words)} words, {entries[-1]['end']:.1f}s)")
        compose_result = compose_final(
            [clip], narration=narration_audio, music=None,
            subtitles=srt_path, out=final, resolution=resolution, fps=fps)

        # ── 7) QA (v2: proven gates + explanation + text dominance) ───
        try:
            audio_metrics = measure_loudness(final)
        except Exception as e:  # noqa: BLE001
            print(f"[qa] loudness failed: {e}")
            audio_metrics = {"integrated_lufs": None, "true_peak_db": None,
                             "clipping": False}
        motion_metrics = {
            "beat_count": len(vs["beats"]),
            "avg_beat_duration": (sum(b["duration"] for b in vs["beats"])
                                  / max(1, len(vs["beats"]))),
        }
        report = qa_gates.run_all_v2(
            vs, video_path=final, audio_metrics=audio_metrics,
            motion_metrics=motion_metrics,
            expected_res=resolution, expected_fps=fps)
        (out / "qareport.json").write_text(json.dumps(report, indent=2))
        (out / "qa.json").write_text(json.dumps(report, indent=2))

        # ── 8) artifacts ──────────────────────────────────────────────
        audio_dur = _probe_audio_duration(narration_audio) if narration_audio else 0.0
        if words:
            audio_dur = max(audio_dur, words[-1]["end"])
        (out / "script.json").write_text(json.dumps(
            _script_from_words(narration, words, audio_dur), indent=2))
        (out / "audio_timing.json").write_text(json.dumps({
            "duration_s": round(audio_dur, 3),
            "words": words,
            "provider": (narration_audio.suffix.lstrip(".")
                         if narration_audio else None),
        }, indent=2))
        (out / "audio_timeline.json").write_text(json.dumps({
            "duration_s": round(audio_dur, 3),
            "words": words,
            "provider": (narration_audio.suffix.lstrip(".")
                         if narration_audio else None),
        }, indent=2))
        (out / "scene_state_log.json").write_text(json.dumps(
            _state_log_from_visualspec(vs), indent=2))

        actual_dur = qa_gates.probe_duration_ffprobe(final)
        actual_info = qa_gates.probe_streams(final)
        actual_res = None
        actual_fps = None
        for s in actual_info.get("streams", []):
            if s.get("codec_type") == "video":
                actual_res = [s.get("width"), s.get("height")]
                fr = s.get("avg_frame_rate", "0/1").split("/")
                try:
                    actual_fps = round(float(fr[0]) / float(fr[1]), 2)
                except (ValueError, ZeroDivisionError):
                    actual_fps = None
                break
        diag = {
            "resolution": list(resolution), "fps": fps,
            "actual_duration_s": round(actual_dur, 3),
            "actual_resolution": actual_res, "actual_fps": actual_fps,
            "audio_duration_s": round(audio_dur, 3),
            "compose": compose_result,
        }
        try:
            sheet = build_contact_sheet(final, out / "contact_sheet.jpg")
            diag["contact_sheet"] = str(sheet)
        except Exception as e:  # noqa: BLE001
            diag["contact_sheet"] = None
        (out / "render_diagnostics.json").write_text(json.dumps(diag, indent=2))

        report["runtime_s"] = round(time.time() - t0, 1)
        report["video"] = str(final)
        report["actual_duration_s"] = round(actual_dur, 3)
        report["audio_duration_s"] = round(audio_dur, 3)
        report["integrated_lufs"] = audio_metrics.get("integrated_lufs")
        report["true_peak_db"] = audio_metrics.get("true_peak_db")

        # ── 8b) packaging (P0-6): every PASS run emits publishing
        # artifacts deterministically; never blocks the PASS video
        if report.get("passed"):
            try:
                report["packaging"] = emit_packaging(
                    out, topic, vs.get("beats", []), vs,
                    video_path=final, qa_report=report)
            except Exception as e:  # noqa: BLE001
                print(f"[publish] packaging failed (non-fatal): {e}")
                report["packaging"] = {"error": str(e)}

    # ── 9) spec-§27 comparison fields ──────────────────────────────────
    expl = (vs.get("metadata", {}) or {}).get("explanation_report", {})
    sim_beats = sum(1 for b in vs["beats"]
                    for a in b.get("semantic_actions", []) or []
                    if str(a.get("action", a.get("type", "")))
                    in _SIMULATION_ACTIONS)
    v27 = {
        "topic": topic,
        "story_template_selected": plan.template_name,
        "template_rationale": plan.rationale,
        "hero_mechanism": hero.__dict__ if hero else None,
        "beat_count": len(vs["beats"]),
        "representation_types": [rep.primary.value]
            + [r.value for r in rep.secondary],
        "text_dominant_ratio": expl.get("text_dominance_ratio"),
        "average_visual_explanation_score": expl.get("average_explanation_score"),
        "explanation_passed_avg_ge_3_5": expl.get("passed_avg_ge_3_5"),
        "procedural_primitive_count": _count_primitives(vs),
        "simulation_beat_count": sim_beats,
        "audio_duration_s": report.get("audio_duration_s", narration_dur),
        "render_time_s": report.get("runtime_s"),
        "qa_technical_score": report.get("technical_correctness"),
        "qa_perceptual_score": report.get("perceptual_quality"),
        "qa_passed": report.get("passed"),
        "facts": [f.__dict__ for f in world.facts],
        "provenance": {
            "from_mathmotion_lab": _FROM_MATHMOTION_LAB,
            "from_video_engine": [
                "SceneState lifecycle", "math/physics verifiers",
                "strict schemas", "10-gate QA (ffprobe/ebur128/frame)",
                "kokoro local TTS", "ffmpeg compose + LUFS master",
                "deterministic seeds", "YAML style config",
            ],
        },
    }
    report["v03_report"] = v27
    (out / "v03_report.json").write_text(json.dumps(v27, indent=2))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Autonomous topic -> video (v0.3, no storyboard input)")
    ap.add_argument("--topic", required=True, help="Bare topic, e.g. "
                    "'Why is the sky blue?'")
    ap.add_argument("--out", default="", help="Output directory (default: "
                    "results/<topic-slug>)")
    ap.add_argument("--res", choices=["dev", "hd", "4k"], default="dev",
                    help="dev=1280x720 (default), hd=1920x1080, 4k=3840x2160")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-render", action="store_true",
                    help="Compile only (no Manim render)")
    args = ap.parse_args()

    res = {"dev": (1280, 720), "hd": (1920, 1080), "4k": (3840, 2160)}[args.res]
    out_root = args.out or f"results/{args.topic.lower()[:40]}" \
        .replace(" ", "_").replace("?", "").replace("'", "").strip("_")
    report = run_autonomous(args.topic, out_root, resolution=res,
                            fps=args.fps, render=not args.no_render)
    print(json.dumps(report.get("v03_report", report), indent=2))
    if not args.no_render:
        if report.get("passed"):
            print("\n✅ PASSED:", report.get("video"))
        else:
            print("\n❌ FAILED QA:")
            for e in report.get("errors", []):
                print("  -", e)


if __name__ == "__main__":
    main()
