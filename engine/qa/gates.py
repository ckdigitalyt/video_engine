"""Quality gates engine (directive §32–§36).

Ten independent gates.  Deterministic checks ALWAYS override LLM judgment:
if Python says 5432 - 2345 != 3087, no model can "approve" it.  Motion QA
uses multiple metrics — never a single "motion density" score — and static
periods are classified as purposeful_pause vs dead_air, not auto-failed.

Technical and perceptual quality are scored SEPARATELY: a video can be
technically 100 (right codec/streams/resolution) but perceptually 35
(frozen tail, static dead air, cluttered layout).  `run_all` never
collapses the two into one fake 100/100.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from engine.validation import math_verify as M
from engine.validation.schema import (
    validate_beatsheet,
    validate_qareport,
    validate_shotlist,
    validate_visualspec,
)
from engine.audio.timeline import ffmpeg, measure_loudness

TARGET_LUFS = -14.0
STATIC_THRESHOLD_S = 4.0       # a static interval >= this is flagged
DEAD_AIR_THRESHOLD_S = 6.0     # >= this is dead air (narration advances but frames don't)
TECH_PASS_THRESHOLD = 80
PERC_PASS_THRESHOLD = 70

# ebur128 summary values are in the last "Summary:" section, e.g.:
#   [Parsed_ebur128_0 @ ...] Summary:
#   [Parsed_ebur128_0 @ ...]   Integrated loudness:
#   [Parsed_ebur128_0 @ ...]     I:         -13.9 LUFS
#   [Parsed_ebur128_0 @ ...]   True peak:
#   [Parsed_ebur128_0 @ ...]     Peak:       -1.1 dBFS


@dataclass
class GateResult:
    name: str
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _gate(name: str) -> GateResult:
    return GateResult(name=name)


# ── ffprobe helpers (no string-matching on -i dump) ────────────────────
def ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe not found")
    return exe


def probe_streams(video_path: Path) -> dict:
    """Real ffprobe: JSON streams + format info for the file."""
    cmd = [
        ffprobe(), "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": "ffprobe returned non-JSON output"}


def probe_duration_ffprobe(video_path: Path) -> float:
    info = probe_streams(video_path)
    if "error" in info:
        return 0.0
    try:
        return float(info.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


# ── Gate 1: Schema ─────────────────────────────────────────────────────
def gate_schema(beatsheet: dict, shotlist: dict, visualspec: dict,
                audiocues: dict) -> GateResult:
    g = _gate("schema")
    for name, doc, fn in [
        ("beatsheet", beatsheet, validate_beatsheet),
        ("shotlist", shotlist, validate_shotlist),
        ("visualspec", visualspec, validate_visualspec),
    ]:
        for e in fn(doc):
            g.passed = False
            g.errors.append(f"{name}: {e}")
    return g


# ── Gate 2: Semantic — narration and visual intent agree ──────────────
def gate_semantic(beatsheet: dict, visualspec: dict) -> GateResult:
    g = _gate("semantic")
    vs_map = {b["beat_id"]: b for b in visualspec["beats"]}
    for bid, b in vs_map.items():
        if b.get("visual_change_required", True):
            if not b.get("transformations"):
                g.warnings.append(f"{bid}: marked visual_change_required but no transformations")
        # intent mismatch: if narration says "reverse" but no sort/reverse tf
        nar = (b.get("narration") or "").lower()
        tfs = [t["type"] for t in b.get("transformations", [])]
        if "reverse" in nar and "reverse" not in tfs and "sort" not in tfs:
            g.warnings.append(f"{bid}: narration mentions reverse but no sort/reverse visual")
    return g


# ── Gate 3: Mathematical ──────────────────────────────────────────────
def gate_mathematical(visualspec: dict) -> GateResult:
    g = _gate("mathematical")
    for b in visualspec["beats"]:
        for tf in b.get("transformations", []):
            t = tf.get("type")
            if t == "subtract":
                frm = str(tf.get("from", "")).zfill(4)
                to = str(tf.get("to", "")).zfill(4)
                v = M.verify_kaprekar_step(to, 4, frm)
                if not v.ok:
                    g.passed = False
                    for f in v.failures():
                        g.errors.append(f"{b['beat_id']}: {f['detail']}")
    return g


# ── Gate 4: Layout — visualspec heuristic + real frame-density data ───
def gate_layout(visualspec: dict, frame_layout: Optional[dict] = None) -> GateResult:
    g = _gate("layout")
    for b in visualspec["beats"]:
        if len(b.get("objects", [])) < 1:
            g.warnings.append(f"{b['beat_id']}: beat has no objects")
    # Real frame-level evidence (zone density) beats the structural guess.
    if frame_layout:
        conflict_frames = frame_layout.get("conflict_frames", [])
        crowded = frame_layout.get("crowded_zones", 0)
        max_density = frame_layout.get("max_zone_density", 0.0)
        if conflict_frames:
            g.passed = False
            g.errors.append(
                f"layout clutter on {len(conflict_frames)} frame(s) "
                f"(max zone density {max_density:.2f}): "
                f"frames at {[f'{t:.1f}s' for t in conflict_frames[:5]]}")
        if not conflict_frames and crowded > 0:
            g.warnings.append(f"{crowded} crowded zones (density>0.55) but no hard conflict")
    return g


# ── Gate 6: Motion — real frame metrics (never the BeatSheet alone) ───
def gate_motion(visualspec: dict, motion_metrics: Optional[dict] = None) -> GateResult:
    g = _gate("motion")
    mm = motion_metrics or {}

    real = mm.get("frame_analyzed", False)
    if real:
        # REAL frame-derived evidence.
        intervals = mm.get("static_intervals", [])  # list of [start, end] seconds
        dead = [iv for iv in intervals
                if (iv[1] - iv[0]) >= DEAD_AIR_THRESHOLD_S]
        purposeful = [iv for iv in intervals
                      if STATIC_THRESHOLD_S <= (iv[1] - iv[0]) < DEAD_AIR_THRESHOLD_S]
        avg_motion = mm.get("avg_motion_ratio", 1.0)
        if dead:
            g.passed = False
            g.errors.append(
                f"{len(dead)} dead-air static interval(s) >= {DEAD_AIR_THRESHOLD_S}s: "
                + ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in dead[:5]))
        if purposeful:
            g.warnings.append(
                f"{len(purposeful)} purposeful pause(s) ({STATIC_THRESHOLD_S}-"
                f"{DEAD_AIR_THRESHOLD_S}s): "
                + ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in purposeful[:5]))
        if avg_motion < 0.002 and not dead:
            g.warnings.append(f"near-zero average motion ({avg_motion:.4f}) — video may be static")
        return g

    # No video yet — structural fallback with an honest warning.
    g.warnings.append("motion gate ran on VisualSpec only (no rendered video provided)")
    meaningful = 0
    for b in visualspec["beats"]:
        for tf in b.get("transformations", []):
            if tf.get("from") != tf.get("to"):
                meaningful += 1
    beats = len(visualspec["beats"])
    dur = sum(b.get("duration", 1.0) for b in visualspec["beats"]) or 1.0
    per_min = meaningful * 60.0 / dur
    if per_min < 8 and meaningful < 5:
        g.passed = False
        g.errors.append(f"too few meaningful state changes: {meaningful} ({per_min:.1f}/min)")
    return g


# ── Gate 7: Continuity — important objects persist ────────────────────
def gate_continuity(visualspec: dict) -> GateResult:
    g = _gate("continuity")
    seen: dict[str, str] = {}
    for b in visualspec["beats"]:
        for obj in b.get("objects", []):
            oid = obj.get("id")
            if not oid:
                continue
            persistent = obj.get("persistent", True)
            if persistent and oid in seen and seen[oid] != b["beat_id"]:
                pass  # persists across beats — good continuity
            seen[oid] = b["beat_id"]
    main_used = sum(1 for b in visualspec["beats"]
                    if any(o.get("id") == "number_main" for o in b.get("objects", [])))
    if main_used < max(1, len(visualspec["beats"]) // 2):
        g.warnings.append("number_main not persistent across most beats (weak object continuity)")
    return g


# ── Gate 8: Audio — correctly parsed LUFS + true peak ─────────────────
def gate_audio(audio_metrics: dict) -> GateResult:
    g = _gate("audio")
    lufs = audio_metrics.get("integrated_lufs")
    peak = audio_metrics.get("true_peak_db")
    if lufs is None:
        g.passed = False
        g.errors.append("no LUFS measurement — cannot pass audio gate")
    else:
        if lufs < TARGET_LUFS - 4 or lufs > TARGET_LUFS + 4:
            g.passed = False
            g.errors.append(f"integrated LUFS {lufs:.1f} outside target {TARGET_LUFS}±4")
    if peak is not None and peak > -1.0:
        g.passed = False
        g.errors.append(f"true peak {peak:.1f} dB near clipping (>-1dB)")
    if audio_metrics.get("clipping"):
        g.passed = False
        g.errors.append("clipping detected")
    return g


# ── Gate 9: Technical — real ffprobe verification ─────────────────────
def gate_technical(video_path: Path, expected_res: tuple = (1280, 720),
                   expected_fps: int = 30) -> GateResult:
    """Verify the actual container with ffprobe: H.264 video at expected
    resolution/fps + AAC audio at 48 kHz stereo.  No string-matching on
    `ffmpeg -i` stderr."""
    g = _gate("technical")
    vp = Path(video_path)
    if not vp.exists():
        g.passed = False
        g.errors.append(f"video file missing: {video_path}")
        return g

    info = probe_streams(vp)
    if "error" in info:
        g.passed = False
        g.errors.append(f"ffprobe failed: {info['error']}")
        return g

    streams = info.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]

    if not vstreams:
        g.passed = False
        g.errors.append("no video stream")
    else:
        v = vstreams[0]
        if v.get("codec_name") != "h264":
            g.passed = False
            g.errors.append(f"video codec is {v.get('codec_name')!r}, expected 'h264'")
        w = v.get("width")
        h = v.get("height")
        if (w, h) != tuple(expected_res):
            g.passed = False
            g.errors.append(f"video resolution {w}x{h}, expected {expected_res[0]}x{expected_res[1]}")
        fps = _fps_of(v)
        if fps is None or abs(fps - expected_fps) > 0.6:
            g.passed = False
            g.errors.append(f"video fps {fps}, expected ~{expected_fps}")

    if not astreams:
        g.passed = False
        g.errors.append("no audio stream (or audio not muxed)")
    else:
        a = astreams[0]
        if a.get("codec_name") != "aac":
            g.passed = False
            g.errors.append(f"audio codec is {a.get('codec_name')!r}, expected 'aac'")
        try:
            sr = int(a.get("sample_rate", 0))
        except (TypeError, ValueError):
            sr = 0
        if sr != 48000:
            g.passed = False
            g.errors.append(f"audio sample rate {sr}, expected 48000")
        if a.get("channels") != 2:
            g.passed = False
            g.errors.append(f"audio channels {a.get('channels')}, expected 2 (stereo)")

    dur = probe_duration_ffprobe(vp)
    if dur <= 0:
        g.passed = False
        g.errors.append("unreadable duration")
    return g


def _fps_of(vstream: dict) -> Optional[float]:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = vstream.get(key, "0/1")
        try:
            num, den = raw.split("/")
            if float(den) != 0:
                return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            continue
    return None


# ── Frame-based visual QA (real pixels from the final MP4) ────────────
def _sample_gray_frames(video_path: Path, sample_fps: float = 1.0,
                        width: int = 160, height: int = 90) -> list:
    """Sample ~1 fps as grayscale numpy arrays (rawvideo pipe)."""
    import numpy as np
    cmd = [
        ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(video_path),
        "-vf", f"fps={sample_fps},scale={width}:{height}",
        "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return []
    n = width * height
    frames = []
    buf = proc.stdout
    for off in range(0, len(buf) - n + 1, n):
        frames.append(np.frombuffer(buf[off:off + n], dtype=np.uint8)
                      .reshape(height, width))
    return frames


def frame_visual_qa(video_path: Path, sample_fps: float = 1.0) -> dict:
    """Deterministic motion/static/scene analysis from real sampled frames.

    Returns pixel_motion_ratio, static_intervals (real seconds), scene
    changes, frames analyzed, brightness/contrast estimate.  Never derived
    from the BeatSheet."""
    import numpy as np
    frames = _sample_gray_frames(video_path, sample_fps)
    if not frames:
        return {"frames_analyzed": 0, "error": "no frames could be sampled"}

    motion_ratios: list[float] = []
    scene_changes = 0
    brightness: list[float] = []
    contrast: list[float] = []
    for i, f in enumerate(frames):
        brightness.append(float(f.mean()))
        contrast.append(float(f.std()))
        if i > 0:
            diff = np.abs(f.astype(np.int16) - frames[i - 1].astype(np.int16))
            ratio = float((diff > 10).mean())
            motion_ratios.append(ratio)
            if ratio > 0.35:
                scene_changes += 1

    # static intervals: consecutive gaps with near-zero motion
    static_thr = 0.004
    intervals: list[list[float]] = []
    run_start: Optional[int] = None
    for i, ratio in enumerate(motion_ratios):
        if ratio < static_thr:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                intervals.append([run_start / sample_fps,
                                  (i + 1) / sample_fps])
                run_start = None
    if run_start is not None:
        intervals.append([run_start / sample_fps, len(motion_ratios) / sample_fps])

    return {
        "frames_analyzed": len(frames),
        "pixel_motion_ratio": float(np.mean(motion_ratios)) if motion_ratios else 0.0,
        "avg_motion_ratio": float(np.mean(motion_ratios)) if motion_ratios else 0.0,
        "max_motion_ratio": float(np.max(motion_ratios)) if motion_ratios else 0.0,
        "static_intervals": intervals,
        "static_intervals_over_4s": [iv for iv in intervals
                                     if iv[1] - iv[0] >= STATIC_THRESHOLD_S],
        "longest_static_interval_s": max((iv[1] - iv[0] for iv in intervals),
                                         default=0.0),
        "scene_changes": scene_changes,
        "brightness": float(np.mean(brightness)),
        "contrast": float(np.mean(contrast)),
        "sample_fps": sample_fps,
    }


def frame_layout_qa(video_path: Path, sample_fps: float = 1.0) -> dict:
    """Zone-density layout/overlap heuristic on real frames.

    Each sampled frame is split into a 4x3 zone grid; a zone is 'crowded'
    when >55% of its pixels are ink (differ from the frame mean).  A frame
    is a 'conflict' when a crowded zone has crowded neighbours (crammed
    text/numbers/equations), which is the strongest cheap pixel-level
    signal of overlapping content."""
    import numpy as np
    frames = _sample_gray_frames(video_path, sample_fps)
    if not frames:
        return {"frames_analyzed": 0, "error": "no frames could be sampled"}
    rows, cols = 3, 4
    conflict_frames: list[float] = []
    crowded_zones_total = 0
    max_zone_density = 0.0
    ink_fractions: list[float] = []
    for i, f in enumerate(frames):
        mean = float(f.mean())
        ink = np.abs(f.astype(np.int16) - mean) > 25
        ink_fractions.append(float(ink.mean()))
        zr = f.shape[0] // rows
        zc = f.shape[1] // cols
        zone_dens: list[float] = []
        for r in range(rows):
            for c in range(cols):
                zone = ink[r * zr:(r + 1) * zr, c * zc:(c + 1) * zc]
                zone_dens.append(float(zone.mean()))
        max_zone_density = max(max_zone_density, max(zone_dens))
        grid = [zone_dens[r * cols:(r + 1) * cols] for r in range(rows)]
        crowded = [[r, c] for r in range(rows) for c in range(cols)
                   if grid[r][c] > 0.55]
        crowded_zones_total += len(crowded)
        # conflict: any crowded zone touching another crowded zone (4-neighbour)
        conflict = False
        for r, c in crowded:
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] > 0.55:
                    conflict = True
        if conflict:
            conflict_frames.append(round(i / sample_fps, 2))
    return {
        "frames_analyzed": len(frames),
        "conflict_frames": conflict_frames,
        "crowded_zones": crowded_zones_total,
        "max_zone_density": round(max_zone_density, 4),
        "avg_ink_fraction": float(np.mean(ink_fractions)),
    }


# ── Aggregate runner ──────────────────────────────────────────────────
def run_all(beatsheet: dict, shotlist: dict, visualspec: dict,
            audiocues: dict, video_path: Optional[Path] = None,
            audio_metrics: Optional[dict] = None,
            motion_metrics: Optional[dict] = None,
            expected_res: tuple = (1280, 720), expected_fps: int = 30) -> dict:
    """Run every gate.  Reports TWO independent scores:
    technical_correctness (codec/streams/resolution/audio spec) and
    perceptual_quality (motion/layout/continuity/static dead air)."""
    results: dict[str, GateResult] = {
        "schema": gate_schema(beatsheet, shotlist, visualspec, audiocues),
        "semantic": gate_semantic(beatsheet, visualspec),
        "mathematical": gate_mathematical(visualspec),
        "layout": gate_layout(visualspec),
        "motion": gate_motion(visualspec, motion_metrics),
        "continuity": gate_continuity(visualspec),
    }

    frame_qa: Optional[dict] = None
    layout_qa: Optional[dict] = None
    if video_path and Path(video_path).exists():
        # REAL evidence from the final MP4 — never the BeatSheet.
        frame_qa = frame_visual_qa(video_path)
        layout_qa = frame_layout_qa(video_path)
        real_motion = dict(motion_metrics or {})
        real_motion.update({
            "frame_analyzed": True,
            "static_intervals": frame_qa.get("static_intervals", []),
            "static_periods_over_4s": frame_qa.get("static_intervals_over_4s", []),
            "dead_air_periods": sum(
                1 for iv in frame_qa.get("static_intervals", [])
                if iv[1] - iv[0] >= DEAD_AIR_THRESHOLD_S),
            "avg_motion_ratio": frame_qa.get("avg_motion_ratio", 0.0),
            "pixel_motion_ratio": frame_qa.get("pixel_motion_ratio", 0.0),
            "scene_changes": frame_qa.get("scene_changes", 0),
            "frames_analyzed": frame_qa.get("frames_analyzed", 0),
        })
        results["motion"] = gate_motion(visualspec, real_motion)
        results["layout"] = gate_layout(visualspec, layout_qa)
        results["technical"] = gate_technical(video_path, expected_res, expected_fps)
        if audio_metrics:
            results["audio"] = gate_audio(audio_metrics)
    else:
        results["technical"] = _gate("technical")
        results["technical"].passed = False
        results["technical"].errors.append("no video file provided for technical gate")

    # ── Two independent scores ─────────────────────────────────────────
    tech_gates = ["schema", "mathematical", "technical", "audio"]
    perc_gates = ["semantic", "layout", "motion", "continuity"]
    tech_ok = [results.get(k) for k in tech_gates if k in results]
    perc_ok = [results.get(k) for k in perc_gates if k in results]
    technical_correctness = int(round(
        100.0 * sum(1 for g in tech_ok if g.passed) / max(1, len(tech_ok))))
    perceptual_quality = int(round(
        100.0 * sum(1 for g in perc_ok if g.passed) / max(1, len(perc_ok))))

    # perceptual deductions from real frame evidence (dead air / clutter)
    if frame_qa:
        longest = frame_qa.get("longest_static_interval_s", 0.0)
        if longest >= DEAD_AIR_THRESHOLD_S:
            perceptual_quality = max(0, perceptual_quality - 15)
        if layout_qa and layout_qa.get("conflict_frames"):
            perceptual_quality = max(0, perceptual_quality - 10)

    passed = (technical_correctness >= TECH_PASS_THRESHOLD
              and perceptual_quality >= PERC_PASS_THRESHOLD)
    report = {
        "version": "v1",
        "video_id": str(video_path or ""),
        "passed": passed,
        "gates": {k: {"passed": r.passed, "errors": r.errors, "warnings": r.warnings}
                  for k, r in results.items()},
        "errors": [e for r in results.values() for e in r.errors],
        "technical_correctness": technical_correctness,
        "perceptual_quality": perceptual_quality,
        "score": int(round(0.6 * technical_correctness
                           + 0.4 * perceptual_quality)),
        "motion_metrics": dict(motion_metrics or {}),
        "audio_metrics": dict(audio_metrics or {}),
    }
    if frame_qa:
        report["motion_metrics"].update({
            "frame_analyzed": True,
            "static_intervals": frame_qa.get("static_intervals", []),
            "static_periods_over_4s": frame_qa.get("static_intervals_over_4s", []),
            "dead_air_periods": sum(
                1 for iv in frame_qa.get("static_intervals", [])
                if iv[1] - iv[0] >= DEAD_AIR_THRESHOLD_S),
            "avg_motion_ratio": frame_qa.get("avg_motion_ratio", 0.0),
            "pixel_motion_ratio": frame_qa.get("pixel_motion_ratio", 0.0),
            "scene_changes": frame_qa.get("scene_changes", 0),
            "frames_analyzed": frame_qa.get("frames_analyzed", 0),
        })
        report["frame_visual_qa"] = frame_qa
    if layout_qa:
        report["frame_layout_qa"] = layout_qa
    if audio_metrics:
        report["audio_metrics"].update(audio_metrics)
    validate_qareport(report)
    return report


if __name__ == "__main__":
    bs = {"version": "v1", "beats": [
        {"beat_id": "b001", "start": 0.0, "end": 1.5, "narration": "Try this.",
         "intent": "hook", "importance": "high", "objects": ["number_main"],
         "visual_change_required": True},
        {"beat_id": "b002", "start": 1.5, "end": 3.3, "narration": "Reverse.",
         "intent": "demonstrate_transformation", "importance": "high",
         "objects": ["number_main"], "visual_change_required": True},
    ]}
    sl = {"version": "v1", "shots": [
        {"shot_id": "s001", "beat_id": "b001", "visual_type": "highlight",
         "renderer": "manim", "objects": [{"id": "number_main", "type": "number"}]},
        {"shot_id": "s002", "beat_id": "b002", "visual_type": "digit_sort",
         "renderer": "manim", "objects": [{"id": "number_main", "type": "digit_array"}]},
    ]}
    vs = {"version": "v1", "beats": [
        {"beat_id": "b001", "intent": "hook", "duration": 1.5,
         "objects": [{"id": "number_main", "type": "number"}],
         "transformations": [{"type": "highlight", "from": "3524", "to": "3524"}]},
        {"beat_id": "b002", "intent": "demonstrate_transformation", "duration": 1.8,
         "objects": [{"id": "number_main", "type": "number"}],
         "transformations": [{"type": "subtract", "from": "3524", "to": "3087"}]},
    ]}
    rep = run_all(bs, sl, vs, {"version": "v1", "cues": []})
    print("QA passed:", rep["passed"],
          "| technical:", rep["technical_correctness"],
          "| perceptual:", rep["perceptual_quality"])
    print(json.dumps(rep["errors"], indent=2))
