#!/usr/bin/env python3
"""engine.cli.run — entry point for the re-engineered video engine.

Pipeline (directive §3, §49):
    topic -> (research) -> story/narration -> beats -> shots ->
    VisualSpec -> Manim compile -> render beats -> FFmpeg compose ->
    audio master (LUFS) -> QA gates -> PASS/REPAIR -> final video.

Usage:
    python -m engine.cli.run --topic "Kaprekar's constant" --out results/kaprekar_bench

Deterministic by default (no LLM required for the Kaprekar benchmark).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from engine import qa  # noqa: F401
from engine.qa import gates as qa_gates
from engine.composition.ffmpeg_compositor import (
    build_contact_sheet,
    compose_final,
    generate_srt,
)
from engine.config.loader import get_style
from engine.primitives import manim_primitives  # noqa: F401  (register primitives)
from engine.renderers.manim.compiler import compile_to_file
from engine.validation.schema import (
    check_cross_references,
    validate_beatsheet,
    validate_shotlist,
)
from engine.visuals.visual_director import direct

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIM_BIN = REPO_ROOT / "venv" / "bin" / "manim"


# ── Stage helpers ─────────────────────────────────────────────────────
def _compile_visualspec(beatsheet: dict, shotlist: dict) -> dict:
    """Build a VisualSpec from the beat sheet + shot list (schema v1)."""
    vs_beats = []
    for shot in shotlist["shots"]:
        beat = next((b for b in beatsheet["beats"] if b["beat_id"] == shot["beat_id"]), None)
        if beat is None:
            continue
        vs_beats.append({
            "beat_id": beat["beat_id"],
            "narration": beat.get("narration", ""),
            "start": beat.get("start", 0),
            "duration": beat.get("duration", 1.5),
            "intent": beat.get("intent", "explanation"),
            "importance": beat.get("importance", "medium"),
            "objects": shot.get("objects", []),
            "transformations": shot.get("actions", []),
            "camera": shot.get("camera", {"type": "static"}),
            "audio_cues": shot.get("audio_cues", []),
            "visual_type": shot.get("visual_type", ""),
        })
    return {"version": "v1", "beats": vs_beats,
            "metadata": {"style_spec": "v1"}}


def _render_scene(scene_file: Path, scene_name: str, out_dir: Path,
                  resolution: tuple[int, int], fps: int) -> Path:
    """Render one Manim scene to MP4.  Returns the clip path."""
    manim_exe = shutil.which("manim") or str(MANIM_BIN)
    w, h = resolution
    # Map resolution to manim quality flag: 480p15 / 720p30 / 1080p60 / 4K60
    if h >= 2160:
        qflag = "-qk"
    elif h >= 1080:
        qflag = "-qh"
    elif h >= 720:
        qflag = "-qm"
    else:
        qflag = "-ql"
    cmd = [
        manim_exe, qflag,
        "--format", "mp4",
        "--fps", str(fps),
        "--media_dir", str(out_dir),
        str(scene_file), scene_name,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Manim render failed:\n{proc.stderr[-3000:]}")
    import glob
    cands = sorted(glob.glob(str(out_dir / "**" / f"{scene_name}.mp4"), recursive=True))
    if not cands:
        raise RuntimeError("no rendered mp4 found")
    return Path(cands[-1])


def _caption_entries_sequential(words: list[dict], max_words: int = 4) -> list[dict]:
    """Build non-overlapping caption entries from per-word timings.

    When the TTS provider stamps every word in a sentence with the same
    start..end window (sentence-level timing fallback), naive grouping made
    all chunks from one sentence share the window and stack on top of each
    other.  We split the word list into runs of words that share a
    timestamp; each run's window is subdivided across its caption chunks so
    captions appear sequentially and never overlap.
    """
    entries: list[dict] = []
    run: list[dict] = []
    run_key = None

    def flush(r: list[dict], key: tuple):
        if not r:
            return
        span = key[1] - key[0]
        n = (len(r) + max_words - 1) // max_words or 1
        for i in range(0, len(r), max_words):
            chunk = r[i:i + max_words]
            chunk_idx = i // max_words
            a = key[0] + span * chunk_idx / n
            b = key[0] + span * (chunk_idx + 1) / n
            entries.append({
                "start": round(a, 3),
                "end": round(max(b, a + 0.1), 3),
                "text": " ".join(w["word"] for w in chunk).strip(),
            })

    for w in words:
        k = (w["start"], w["end"])
        if run_key is None or k == run_key:
            run.append(w)
            run_key = k
        else:
            flush(run, run_key)
            run = [w]
            run_key = k
    flush(run, run_key)
    return entries


def _script_from_words(narration: str, words: list[dict],
                       total_duration: float) -> dict:
    """Build script.json: {text, sentences:[{text,start,end}], total_duration}
    from TTS word timing (sentence boundaries by word order)."""
    import re
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration.strip())
                 if s.strip()]
    out_sentences: list[dict] = []
    widx = 0
    for s in sentences:
        nwords = len(s.split())
        chunk = words[widx:widx + nwords]
        widx += nwords
        if chunk:
            out_sentences.append({
                "text": s,
                "start": round(chunk[0]["start"], 3),
                "end": round(chunk[-1]["end"], 3),
            })
        else:
            out_sentences.append({"text": s, "start": 0.0, "end": total_duration})
    return {"text": narration, "sentences": out_sentences,
            "total_duration": round(total_duration, 3)}


def _state_log_from_visualspec(vs: dict) -> list[dict]:
    """Derive a real per-beat enter/update/exit log from the VisualSpec
    (matches SceneState.to_log() shape: beat_id/entering/updating/exiting/
    persisting).  Real object lifecycle, derived deterministically."""
    log: list[dict] = []
    active: set[str] = set()
    for b in vs.get("beats", []):
        ids = {o.get("id") for o in b.get("objects", []) if o.get("id")}
        entering = sorted(ids - active)
        exiting = sorted(active - ids)
        updating = sorted(ids & active)
        persisting = sorted(ids & active)
        log.append({"beat_id": b.get("beat_id", ""),
                    "entering": entering, "updating": updating,
                    "exiting": exiting, "persisting": persisting})
        active = ids
    return log


def _peak_usage() -> dict:
    """Peak RSS (MB) + peak CPU (s) for self and child processes."""
    try:
        import resource
        self_ru = resource.getrusage(resource.RUSAGE_SELF)
        ch_ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        return {
            "peak_ram_mb": round(max(self_ru.ru_maxrss, ch_ru.ru_maxrss) / 1024.0, 1),
            "peak_cpu_s": round(self_ru.ru_utime + self_ru.ru_stime
                                + ch_ru.ru_utime + ch_ru.ru_stime, 2),
        }
    except ImportError:  # pragma: no cover
        return {"peak_ram_mb": None, "peak_cpu_s": None}


def _probe_audio_duration(path: Path) -> float:
    try:
        from engine.composition.ffmpeg_compositor import _probe_duration
        return float(_probe_duration(path))
    except Exception:  # noqa: BLE001
        return 0.0


def run(topic: str, out_root: str | Path, use_llm: bool = False,
        resolution: tuple[int, int] = (1280, 720), fps: int = 30,
        narration: str = "") -> dict:
    """Execute the full pipeline.  Returns the QA report + summary dict."""
    t0 = time.time()
    out = Path(out_root)
    out.mkdir(parents=True, exist_ok=True)
    workdir = out / "work"
    workdir.mkdir(parents=True, exist_ok=True)

    # 1) Story/narration (research is minimal for benchmark; expand later)
    if not narration:
        narration = (
            "Pick any four-digit number. What happens if we keep rearranging "
            "its digits? Arrange them largest to smallest, then smallest to "
            "largest. Subtract. Take the result and repeat. Amazingly, every "
            "starting number falls into the same trap — every path leads to "
            "6174. This is Kaprekar's constant. Unless all digits are "
            "identical, then nothing changes. A simple rule, a stubborn constant."
        )

    # 2) TTS narration is the temporal source of truth (§19/§20): synthesize
    #    the voice and measure its actual duration BEFORE planning beats, so
    #    total animation matches the narration (never freeze-frame a tail).
    workdir.mkdir(parents=True, exist_ok=True)
    narration_audio = None
    srt_path = None
    words: list[dict] = []
    if narration:
        try:
            from engine.audio.timeline import synthesize_narration
            from engine.composition.ffmpeg_compositor import generate_srt
            narration_audio, words = synthesize_narration(
                narration, workdir / "narration", voice="")
            if words:
                order = sorted(words, key=lambda w: w["start"])
                narration_dur = order[-1]["end"]
            else:
                narration_dur = _probe_audio_duration(narration_audio)
        except Exception as e:  # noqa: BLE001
            print(f"[tts] narration synthesis failed, proceeding silent: {e}")
            narration_audio = None
            words = []
            narration_dur = 0.0
    else:
        narration_dur = 0.0

    # 2b) Visual Director -> BeatSheet + ShotList (sized to the narration)
    beatsheet, shotlist = direct(topic, narration, use_llm=use_llm,
                                 target_duration=narration_dur if narration_dur > 0 else None)
    cross = check_cross_references(beatsheet, shotlist)
    if cross:
        raise RuntimeError("cross-ref failed:\n" + "\n".join(cross))

    # 3) VisualSpec
    vs = _compile_visualspec(beatsheet, shotlist)
    (out / "beatsheet.json").write_text(json.dumps(beatsheet, indent=2))
    (out / "shotlist.json").write_text(json.dumps(shotlist, indent=2))
    (out / "visualspec.json").write_text(json.dumps(vs, indent=2))

    # 4) Compile -> Manim scene (single scene for the benchmark; incremental
    #    per-beat rendering is supported by the architecture, §31)
    scene_file = workdir / "bench_scene.py"
    scene_name = "KaprekarBenchScene"
    compile_failures: list[str] = []
    render_failures: list[str] = []
    try:
        compile_to_file(vs, scene_file, scene_name)
    except Exception as e:  # noqa: BLE001
        compile_failures.append(str(e))
        raise

    # 5) Render
    try:
        clip = _render_scene(scene_file, scene_name, workdir, resolution, fps)
    except Exception as e:  # noqa: BLE001
        render_failures.append(str(e))
        raise

    # 6) Compose: narration (TTS, already synthesized in step 2 as temporal
    #    source of truth) + subtitles + final audio mix
    final = out / "final.mp4"
    # Build non-overlapping caption entries from the step-2 word timings.
    # The Kokoro provider stamps every word in a sentence with the sentence's
    # start..end window, so naive 4-word grouping made every chunk from one
    # sentence share the SAME window -> captions layered on top of each other.
    # We detect runs of words that share a timestamp and subdivide that run's
    # window across its chunks so captions appear sequentially, never stacked.
    if words:
        from engine.composition.ffmpeg_compositor import generate_srt
        order = sorted(words, key=lambda w: w["start"])
        entries = _caption_entries_sequential(order)
        srt_path = generate_srt(entries, workdir / "narration.srt")
        print(f"[tts] narration {narration_audio.name} "
              f"({len(words)} words, {entries[-1]['end']:.1f}s)")

    compose_result = compose_final(
        [clip], narration=narration_audio, music=None,
        subtitles=srt_path, out=final, resolution=resolution, fps=fps)

    # 7) QA gates (real audio metrics from the final mix, §22)
    try:
        from engine.audio.timeline import measure_loudness
        audio_metrics = measure_loudness(final)
    except Exception as e:  # noqa: BLE001
        print(f"[qa] loudness measurement failed: {e}")
        audio_metrics = {"integrated_lufs": None, "true_peak_db": None,
                         "clipping": False}
    motion_metrics = {
        "beat_count": len(beatsheet["beats"]),
        "avg_beat_duration": (sum(b["duration"] for b in beatsheet["beats"])
                              / max(1, len(beatsheet["beats"]))),
    }
    report = qa_gates.run_all(
        beatsheet, shotlist, vs, {"version": "v1", "cues": []},
        video_path=final, audio_metrics=audio_metrics,
        motion_metrics=motion_metrics,
        expected_res=resolution, expected_fps=fps,
    )
    (out / "qareport.json").write_text(json.dumps(report, indent=2))

    # 8) Debug artifacts (directive: script / audio timing / state log /
    #    render diagnostics / contact sheet)
    audio_dur = _probe_audio_duration(narration_audio) if narration_audio else 0.0
    if words:
        audio_dur = max(audio_dur, words[-1]["end"])
    script_doc = _script_from_words(narration, words, audio_dur)
    (out / "script.json").write_text(json.dumps(script_doc, indent=2))
    (out / "audio_timing.json").write_text(json.dumps({
        "duration_s": round(audio_dur, 3),
        "words": words,
        "provider": (narration_audio.suffix.lstrip(".")
                      if narration_audio else None),
    }, indent=2))
    state_log = _state_log_from_visualspec(vs)
    (out / "scene_state_log.json").write_text(json.dumps(state_log, indent=2))

    frame_qa = report.get("frame_visual_qa", {})
    layout_qa = report.get("frame_layout_qa", {})
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
    static_intervals = frame_qa.get("static_intervals", [])
    longest_static = max((iv[1] - iv[0] for iv in static_intervals), default=0.0)
    math_failures = report.get("gates", {}).get("mathematical", {}).get("errors", [])
    layout_failures = report.get("gates", {}).get("layout", {}).get("errors", [])

    render_diag = {
        "resolution": list(resolution),
        "fps": fps,
        "actual_duration_s": round(actual_dur, 3),
        "actual_resolution": actual_res,
        "actual_fps": actual_fps,
        "audio_duration_s": round(audio_dur, 3),
        "compose": compose_result,
        "render_failures": render_failures,
        "compile_failures": compile_failures,
        "frame_visual_qa": frame_qa,
        "frame_layout_qa": layout_qa,
        "math_validation_failures": math_failures,
        "layout_failures": layout_failures,
    }
    (out / "render_diagnostics.json").write_text(json.dumps(render_diag, indent=2))

    try:
        sheet = build_contact_sheet(final, out / "contact_sheet.jpg")
        render_diag["contact_sheet"] = str(sheet)
        (out / "render_diagnostics.json").write_text(
            json.dumps(render_diag, indent=2))
    except Exception as e:  # noqa: BLE001
        print(f"[qa] contact sheet failed: {e}")
        render_diag["contact_sheet"] = None
        (out / "render_diagnostics.json").write_text(
            json.dumps(render_diag, indent=2))

    report["runtime_s"] = round(time.time() - t0, 1)
    report["resolution"] = list(resolution)
    report["fps"] = fps
    report["video"] = str(final)
    report["actual_duration_s"] = round(actual_dur, 3)
    report["actual_resolution"] = actual_res
    report["actual_fps"] = actual_fps
    report["audio_duration_s"] = round(audio_dur, 3)
    report["integrated_lufs"] = audio_metrics.get("integrated_lufs")
    report["true_peak_db"] = audio_metrics.get("true_peak_db")
    report["beat_count"] = len(beatsheet["beats"])
    report["avg_beat_duration_s"] = round(
        sum(b["duration"] for b in beatsheet["beats"]) / max(1, len(beatsheet["beats"])), 2)
    objs = {"enters": 0, "updates": 0, "exits": 0}
    for rec in state_log:
        objs["enters"] += len(rec["entering"])
        objs["updates"] += len(rec["updating"])
        objs["exits"] += len(rec["exiting"])
    report["object_enters"] = objs["enters"]
    report["object_updates"] = objs["updates"]
    report["object_exits"] = objs["exits"]
    report["static_intervals"] = [
        [round(a, 2), round(b, 2)] for a, b in static_intervals]
    report["longest_static_interval_s"] = round(longest_static, 2)
    report["render_failures"] = render_failures
    report["compile_failures"] = compile_failures
    report["math_validation_failures"] = math_failures
    report["layout_failures"] = layout_failures
    report["perceptual_score"] = report.get("perceptual_quality")
    report["technical_score"] = report.get("technical_correctness")
    report.update(_peak_usage())
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Automated math motion-graphics studio")
    ap.add_argument("--topic", default="Kaprekar's constant",
                    help="Video topic / title")
    ap.add_argument("--out", default="results/kaprekar_bench_engine",
                    help="Output directory")
    ap.add_argument("--narration", default="", help="Exact narration text")
    ap.add_argument("--use-llm", action="store_true",
                    help="Use DeepSeek for the Visual Director (default deterministic)")
    ap.add_argument("--dev", action="store_true",
                    help="Dev resolution 1280x720 (default); production is 1920x1080")
    args = ap.parse_args()

    res = (1280, 720) if args.dev else (1920, 1080)
    report = run(args.topic, args.out, use_llm=args.use_llm,
                 resolution=res, narration=args.narration)
    print(json.dumps(report, indent=2))
    if report.get("passed"):
        print("\n✅ PASSED: ", report["video"])
    else:
        print("\n❌ FAILED QA:")
        for e in report.get("errors", []):
            print("  -", e)


if __name__ == "__main__":
    main()
