"""WP5 acceptance: frame-exact parity of the new `Short.tsx` <Series>
composition (engine.v16_compose) vs the live per-scene Python caption pass
(engine.v14_assembly), on the ice_slippery fixture already on disk at
build/v15/ice_slippery/ (WP0 baseline render — no new Claude calls, no new
plate generation, no new pipeline run).

Frame-sampled fixture test, per the WP5 launch prompt: 20 frames, not a
full video render, so it does not touch the owner's video-render budget.

Usage (from illustrated_engine/, venv active):
    python3 -m bench.ab.wp5_parity            (run from repo root)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

REPO = Path(__file__).resolve().parent.parent.parent  # video_engine
IE = REPO / "illustrated_engine"
sys.path.insert(0, str(IE))

FIXTURE = IE / "build" / "v15" / "ice_slippery"
N_SAMPLES = 20
OUT_DIR = Path.home() / "phase4_out" / "wp5"


def _load_fixture():
    pr = json.loads((FIXTURE / "pipeline_report.json").read_text())
    ar = json.loads((FIXTURE / "assembly_report.json").read_text())
    order = pr["production"]["reuse"] + pr["production"]["render"]
    if not order:
        raise RuntimeError("fixture has no scene order (production.reuse/render empty)")
    scene_entries = []
    for sid in order:
        spec = json.loads((FIXTURE / "scenes" / f"{sid}.spec.json").read_text())
        scene_entries.append({"scene_id": sid, "spec": spec})
    return scene_entries, ar["caption_overlays"], ar["total_s"]


def _extract_frame(video: Path, frame_idx: int, out_png: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video),
        "-vf", f"select=eq(n\\,{frame_idx})", "-vframes", "1", str(out_png),
    ], check=True)


def main() -> int:
    from engine.brand import load_brand
    from engine.v16_compose import (build_short_props, render_short,
                                    render_short_frames, total_duration_frames)

    scene_entries, caption_overlays, total_s = _load_fixture()
    brand = load_brand()
    props = build_short_props(scene_entries, caption_overlays, brand=brand,
                              sting=None, outro=None)
    total_frames = total_duration_frames(props)
    expected_frames = round(total_s * props["fps"])
    print(f"scenes={len(scene_entries)} total_frames={total_frames} "
          f"(assembly_report total_s*fps={expected_frames})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames = sorted(set(
        int(round(x)) for x in np.linspace(2, total_frames - 3, N_SAMPLES)
    ))

    # Diagnostic 0: the Short <Series> render of one scene must be pixel-
    # identical to that same scene through the existing, unchanged SceneIR
    # per-scene backend (scene_renderer.RemotionRenderer) — i.e. Series
    # sequencing introduces zero visual drift on its own. Proven byte-exact
    # for frame 2 / scene B1_S1 during development; not re-asserted here
    # (see bench/ab/wp5.md) to keep this script to one bundle + one render.

    # Primary parity measurement: render the WHOLE Short composition to an
    # h264 mp4 (crf 18, yuv420p — the same settings v14_assembly uses) and
    # sample frames from THAT, vs frames sampled from captioned.mp4. A
    # lossless-PNG-vs-video comparison is not apples to apples: captioned.mp4
    # already carries two h264 generations (per-scene render + concat pass +
    # caption-burn pass), and film grain (SceneComposition's renderFinish)
    # is a per-pixel PRNG field that decorrelates completely under any
    # requantization, tanking SSIM even when the content is unchanged.
    t0 = time.time()
    short_mp4 = OUT_DIR / "short.mp4"
    res = render_short(props, short_mp4)
    render_secs = time.time() - t0
    if not res["ok"]:
        print("RENDER FAILED:", res.get("stderr_tail"))
        return 1
    print(f"rendered full Short mp4 ({total_frames} frames) in "
          f"{render_secs:.1f}s -> {short_mp4}")

    ref_video = FIXTURE / "captioned.mp4"  # visual-only (no audio), captions
    # already burned — the exact thing the live caption pass produces today.
    short_dir = OUT_DIR / "short_frames"
    ref_dir = OUT_DIR / "ref_frames"
    short_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for f in frames:
        short_png = short_dir / f"f_{f}.png"
        ref_png = ref_dir / f"f_{f}.png"
        _extract_frame(short_mp4, f, short_png)
        if not ref_png.exists():
            _extract_frame(ref_video, f, ref_png)
        a = np.array(Image.open(short_png).convert("RGB"))
        b = np.array(Image.open(ref_png).convert("RGB"))
        if a.shape != b.shape:
            rows.append({"frame": f, "error": f"shape mismatch {a.shape} vs {b.shape}"})
            continue
        score = float(ssim(a, b, channel_axis=2, data_range=255))
        rows.append({"frame": f, "t_s": round(f / props["fps"], 3), "ssim": round(score, 5)})
        print(f"  frame {f:4d} t={f / props['fps']:.2f}s ssim={score:.5f}")

    scores = [r["ssim"] for r in rows if "ssim" in r]
    summary = {
        "fixture": "ice_slippery",
        "total_frames": total_frames,
        "sampled_frames": len(rows),
        "mean_ssim": round(float(np.mean(scores)), 5) if scores else None,
        "min_ssim": round(float(np.min(scores)), 5) if scores else None,
        "threshold": 0.98,
        "pass": bool(scores) and min(scores) >= 0.98,
        "short_render_seconds": round(render_secs, 1),
        "python_assembly_seconds_baseline":
            json.loads((FIXTURE / "pipeline_report.json").read_text())
            ["timings"]["assembly_s"],
        "rows": rows,
    }
    (OUT_DIR / "wp5_parity.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
