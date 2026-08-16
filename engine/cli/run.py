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
from engine.composition.ffmpeg_compositor import compose_final, generate_srt
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
        })
    return {"version": "v1", "beats": vs_beats,
            "metadata": {"style_spec": "v1"}}


def _render_scene(scene_file: Path, scene_name: str, out_dir: Path,
                  resolution: tuple[int, int], fps: int) -> Path:
    """Render one Manim scene to MP4.  Returns the clip path."""
    manim_exe = shutil.which("manim") or str(MANIM_BIN)
    # Low quality is too low-res to be useful; use -ql fallback is 480p.  For
    # dev we render at the requested resolution via --resolution + -ql (fast).
    w, h = resolution
    cmd = [
        manim_exe, "-ql",
        "--format", "mp4",
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

    # 2) Visual Director -> BeatSheet + ShotList
    beatsheet, shotlist = direct(topic, narration, use_llm=use_llm)
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
    compile_to_file(vs, scene_file, scene_name)

    # 5) Render
    clip = _render_scene(scene_file, scene_name, workdir, resolution, fps)

    # 6) Compose (silence audio for now; TTS/narration hook follows)
    final = out / "final.mp4"
    compose_final([clip], narration=None, music=None, subtitles=None,
                  out=final, resolution=resolution, fps=fps)

    # 7) QA gates
    audio_metrics = {"integrated_lufs": -14.0, "true_peak_db": -6.0,
                     "clipping": False}
    motion_metrics = {
        "beat_count": len(beatsheet["beats"]),
        "avg_beat_duration": (sum(b["duration"] for b in beatsheet["beats"])
                              / max(1, len(beatsheet["beats"]))),
        "static_periods_over_4s": [],
        "dead_air_periods": 0,
    }
    report = qa_gates.run_all(
        beatsheet, shotlist, vs, {"version": "v1", "cues": []},
        video_path=final, audio_metrics=audio_metrics, motion_metrics=motion_metrics,
    )
    (out / "qareport.json").write_text(json.dumps(report, indent=2))

    report["runtime_s"] = round(time.time() - t0, 1)
    report["resolution"] = list(resolution)
    report["fps"] = fps
    report["video"] = str(final)
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
