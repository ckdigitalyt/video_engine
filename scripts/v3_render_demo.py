#!/usr/bin/env python3
"""v3_render_demo.py — Wave-2 verification: render one 720p sample shot per
renderer, ffprobe-verify each output, print a results table.

Usage:
    ./venv/bin/python scripts/v3_render_demo.py [--live]

Without --live: AI_VIDEO is attempted only if a keyframe + provider are
available; offline-safe stub keyframes are used where needed.
With --live: also exercises live AI generation through the broker (LTX /
SiliconFlow), requires .env keys and network.

Every renderer in the canonical §24 chain is exercised:
MANIM, AI_IMAGE_MOTION, STOCK_VIDEO, MOTION_CANVAS, PIXIJS (+ AI_VIDEO live).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.renderers.base import RenderContext  # noqa: E402
from engine.renderers.registry import get_renderer  # noqa: E402


def ffprobe(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", str(path)],
        capture_output=True, text=True, timeout=60)
    info = json.loads(out.stdout)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {
        "codec": stream.get("codec_name"),
        "res": f"{stream.get('width')}x{stream.get('height')}",
        "duration": float(info["format"].get("duration", 0)),
        "bytes": Path(path).stat().st_size,
    }


def make_test_still(path: Path, color: str = "steelblue") -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", f"-i", f"color=c={color}:s=1280x720",
         "-frames:v", "1", str(path)],
        capture_output=True, timeout=60, check=True)
    return path


def render_shot(renderer_id: str, shot: dict, out_dir: Path,
                style: dict | None = None) -> tuple[bool, str, dict | None]:
    try:
        renderer = get_renderer(renderer_id)
        ctx = RenderContext(output_dir=str(out_dir), fps=24,
                            resolution=(1280, 720), aspect="16:9", seed=42)
        t0 = time.time()
        result = renderer.render(shot, style, ctx)
        if renderer_id == "MANIM":
            # MANIM adapter emits a scene file (Wave-1 contract); the CLI
            # encode + ffprobe happens in main().
            return True, renderer_id, {"scene_file": result.path}
        probe = ffprobe(result.path)
        probe["render_sec"] = round(time.time() - t0, 1)
        return True, renderer_id, probe
    except Exception as exc:  # noqa: BLE001 — demo reports per-renderer
        return False, renderer_id, None if not isinstance(exc, Exception) \
            else {"error": str(exc)[:180]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="allow live AI generation (broker providers)")
    args = ap.parse_args()

    # Project-local artifacts: the generated Manim scene imports the engine
    # package relative to its own path, so output must live under the repo.
    tmp = PROJECT_ROOT / "tmp" / "v3_demo"
    tmp.mkdir(parents=True, exist_ok=True)
    style = {"palette": {"background": "#0b0e1a", "accent": "#5ac8fa",
                         "highlight": "#ffd166"}}

    keyframe = make_test_still(tmp / "kf.png", "teal")
    still = make_test_still(tmp / "still.png", "sienna")

    shots = {
        "MANIM": {
            "shot_id": "D_MANIM", "duration_sec": 2.0,
            "visual_goal": "demo", "narrative_role": "reveal",
            "visualspec": {
                "version": "v1",
                "beats": [
                    {
                        "beat_id": "b001",
                        "intent": "demonstrate_transformation",
                        "narration": "wave two renderer demo",
                        "duration": 2.0,
                        "visual_type": "digit_sort",
                        "objects": [
                            {"id": "number_main", "type": "number",
                             "value": "3524"},
                        ],
                        "transformations": [
                            {"type": "sort", "from": "3524", "to": "5432"}],
                    },
                ],
            },
        },
        "AI_IMAGE_MOTION": {
            "shot_id": "D_AIVIMG", "duration_sec": 2.0,
            "subject": "demo dunes", "visual_goal": "demo dunes",
            "motion": {"atmosphere": True},
            "asset_requirements": {"still_path": str(still)},
        },
        "STOCK_VIDEO": {
            "shot_id": "D_STOCK", "duration_sec": 2.0,
            "subject": "waves", "visual_goal": "waves",
            "asset_requirements": {"footage_path": str(_make_test_footage(tmp))},
        },
        "MOTION_CANVAS": {
            "shot_id": "D_MC", "duration_sec": 2.0, "narrative_role": "hook",
            "text_overlay": {"text": "Kinetic Title"},
            "motion": {"template": "kinetic_title",
                       "props": {"title": "Wave 2", "subtitle": "motion engine"}},
        },
        "PIXIJS": {
            "shot_id": "D_PIXI", "duration_sec": 2.5, "narrative_role": "action",
            "background": "jungle", "subject": "a t_rex sprints",
            "camera": {"move": "push_in", "duration": 2.5},
            "motion": {"scene": {
                "background": {"asset": "jungle", "depth": 0.5, "scale": 1.15},
                "characters": [{"type": "t_rex", "position": [0.6, 0.92],
                                "action": "run", "scale": 0.7, "path": [0.35]}],
                "camera": {"move": "push_in"},
                "particles": "dust", "atmosphere": "fog",
            }},
        },
    }

    # AI_VIDEO: live = real broker i2v; offline = skipped with note.
    if args.live:
        shots["AI_VIDEO"] = {
            "shot_id": "D_AIVIDEO", "duration_sec": 4.0,
            "subject": "calm ocean at sunset, slow cinematic pan",
            "asset_requirements": {"image_path": str(keyframe)},
        }
    else:
        pass  # reported as skipped below

    results = []
    for rid, shot in shots.items():
        print(f"→ rendering {rid} ...", flush=True)
        ok, _, probe = render_shot(rid, shot, tmp, style)
        if ok and rid == "MANIM":
            # MANIM adapter emits a scene file (Wave-1 contract); encode it
            # with the manim CLI to verify the full path to a real video.
            scene_file = tmp / "D_MANIM_manim_scene.py"
            scene_name = "BenchScene"
            mp4 = tmp / "D_MANIM_manim.mp4"
            try:
                proc = subprocess.run(
                    ["./venv/bin/manim", "-ql", "--fps", "24",
                     str(scene_file), scene_name, "-o", str(mp4)],
                    capture_output=True, text=True, timeout=600,
                    cwd=str(PROJECT_ROOT))
                if proc.returncode == 0 and mp4.exists():
                    probe = ffprobe(mp4)
                else:
                    ok, probe = False, {"error":
                        (proc.stderr or proc.stdout)[-150:]}
            except Exception as exc:  # noqa: BLE001
                ok, probe = False, {"error": str(exc)[:150]}
        results.append((rid, ok, probe))

    # ARCHIVAL: needs network; try broker-backed, else report skip.
    print("→ rendering ARCHIVAL (network) ...", flush=True)
    ok, _, probe = render_shot(
        "ARCHIVAL",
        {"shot_id": "D_ARCH", "duration_sec": 2.0, "subject": "earth from space",
         "visual_goal": "earth"},
        tmp, style)
    results.append(("ARCHIVAL", ok, probe))

    if not args.live:
        results.append(("AI_VIDEO", None, {"note": "skipped (run with --live "
                                                   "for real ZeroGPU generation)"}))

    # ── table ──
    print()
    print(f"{'renderer':<16} {'status':<8} {'codec':<7} {'res':<11} "
          f"{'dur':<7} {'bytes':<9} {'t':<6}")
    print("-" * 72)
    for rid, ok, probe in results:
        if ok is None:
            print(f"{rid:<16} {'SKIP':<8} {'-':<7} {'-':<11} {'-':<7} "
                  f"{'-':<9} {'-':<6}")
        elif ok and probe:
            print(f"{rid:<16} {'PASS':<8} {probe['codec']:<7} "
                  f"{probe['res']:<11} {probe['duration']:<7.2f} "
                  f"{probe['bytes']:<9} {probe.get('render_sec','')!s:<6}")
        else:
            err = (probe or {}).get("error", "unknown")
            print(f"{rid:<16} {'FAIL':<8} {err[:52]}")

    out_dir_arg = tmp
    print(f"\nartifacts: {out_dir_arg}")
    return 0 if all(r[1] is not False for r in results) else 1


def _make_test_footage(tmp: Path) -> Path:
    path = tmp / "test_footage.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24",
         "-t", "3", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, timeout=120, check=True)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
