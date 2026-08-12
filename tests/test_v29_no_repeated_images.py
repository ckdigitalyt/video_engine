"""v29 regression tests — "same image repeated" root fix.

ckdigital reported (Wow! Signal video): between 33-44s one image was
zoomed/panned more than once.  Timeline confirmed the defect:
scene2_0.jpg was re-rendered 4x contiguously (32.12-44.91s), scene3_0.jpg
4x, scene1_0.jpg 3x.

Root causes fixed in v29:
  1. non-hook scenes had a fixed 2-still budget — when a scene collapsed
     to ONE still, every coverage variant re-rendered that same image;
     budgets now scale with narration length and every scene gets AI
     candidate padding;
  2. coverage variants preferred re-rendering a placed still — they now
     GENERATE a fresh photorealistic AI still first (fallback reuses);
  3. the repeated_assets gate had a v22 exemption permitting contiguous
     same-scene variant repeats — removed, so any repeated source still
     is flagged.

These tests pin the gate behaviour (3) on synthetic timelines.
"""

import json
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

from src.qa.deterministic_qa import DeterministicQA, QAReport


def _make_still(path: str, seed: int) -> str:
    """Random-texture still (dHash-distinct per seed)."""
    import random
    im = Image.new("RGB", (64, 64))
    d = ImageDraw.Draw(im)
    rnd = random.Random(seed)
    for _ in range(60):
        x0, y0 = rnd.randrange(64), rnd.randrange(64)
        x1 = min(63, x0 + rnd.randrange(3, 12))
        y1 = min(63, y0 + rnd.randrange(3, 12))
        d.rectangle([x0, y0, x1, y1],
                    fill=(rnd.randrange(255), rnd.randrange(255), rnd.randrange(255)))
    im.save(path)
    return path


def _make_clip(path: str) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "color=c=red:s=64x64:r=5:d=1", "-c:v", "libx264",
         "-preset", "ultrafast", path],
        capture_output=True, timeout=30)
    return path


def _run_repeated_assets(entries, tmp_path):
    tl = os.path.join(tmp_path, "timeline.json")
    json.dump({"video_timeline": entries}, open(tl, "w"))
    rep = QAReport()
    DeterministicQA()._check_repeated_assets(tl, rep)
    return next(c for c in rep.checks if c.name == "repeated_assets")


def test_same_still_rendered_4x_fails(tmp_path):
    """The exact Wow! Signal defect — one still re-rendered 4x contiguously
    in a single scene — must FAIL the repeated_assets gate (v29)."""
    still = _make_still(os.path.join(tmp_path, "scene2_0.jpg"), seed=7)
    entries, t = [], 0.0
    for i in range(4):
        entries.append({
            "file": _make_clip(os.path.join(tmp_path, f"scene2_0_{i}.mp4")),
            "asset": still, "start_time": t, "end_time": t + 4.0,
            "scene_id": 2,
            "shot_type": "primary" if i == 0 else "variant",
        })
        t += 4.0
    chk = _run_repeated_assets(entries, tmp_path)
    assert chk.passed is False
    assert chk.metrics.get("perceptual_repeats")


def test_distinct_stills_pass(tmp_path):
    """4 genuinely different stills must pass — the gate is not a false
    positive machine for legitimately distinct coverage."""
    entries, t = [], 0.0
    for i in range(4):
        still = _make_still(os.path.join(tmp_path, f"scene2_{i}.jpg"), seed=100 + i)
        entries.append({
            "file": _make_clip(os.path.join(tmp_path, f"scene2b_{i}.mp4")),
            "asset": still, "start_time": t, "end_time": t + 4.0,
            "scene_id": 2,
            "shot_type": "primary" if i == 0 else "variant",
        })
        t += 4.0
    chk = _run_repeated_assets(entries, tmp_path)
    assert chk.passed is True


def test_cross_scene_repeat_still_fails(tmp_path):
    """Same still reused in TWO different scenes is a repeat — flagged."""
    still = _make_still(os.path.join(tmp_path, "shared.jpg"), seed=3)
    entries = [
        {"file": _make_clip(os.path.join(tmp_path, "s0.mp4")),
         "asset": still, "start_time": 0.0, "end_time": 4.0,
         "scene_id": 0, "shot_type": "primary"},
        {"file": _make_clip(os.path.join(tmp_path, "s4.mp4")),
         "asset": still, "start_time": 30.0, "end_time": 34.0,
         "scene_id": 4, "shot_type": "primary"},
    ]
    chk = _run_repeated_assets(entries, tmp_path)
    assert chk.passed is False
