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


# ── v2 semantic gates: visual explanation + text dominance (spec §9, §10) ─
def gate_explanation(visualspec: dict) -> GateResult:
    """Perceptual gate: avg visual explanation score >= 3.5 and the video
    is not dominated by level 0-2 beats (spec §10)."""
    g = _gate("explanation")
    try:
        report = (visualspec.get("metadata", {}) or {}).get("explanation_report")
        if report is None:
            from engine.world.scoring import score_beatsheet
            report = score_beatsheet(visualspec.get("beats", [])).to_dict()
        avg = float(report.get("average_explanation_score", 0.0))
        dominated = bool(report.get("dominated_by_level_0_2", False))
        if avg < 3.5:
            g.errors.append(f"avg visual explanation score {avg:.2f} < 3.5")
        if dominated:
            g.errors.append("video dominated by level 0-2 beats — send back "
                            "to the VisualDirector")
        g.passed = not g.errors
        g.warnings.append(f"avg explanation {avg:.2f}")
    except Exception as e:  # noqa: BLE001
        g.errors.append(f"explanation gate failed: {e}")
        g.passed = False
    return g


def gate_text_dominance(visualspec: dict) -> GateResult:
    """Perceptual gate: text-dominance ratio < 0.35 (spec §9 — kinetic
    text is a fallback, not the default)."""
    g = _gate("text_dominance")
    try:
        report = (visualspec.get("metadata", {}) or {}).get("explanation_report")
        if report is None:
            from engine.world.scoring import score_beatsheet
            report = score_beatsheet(visualspec.get("beats", [])).to_dict()
        ratio = float(report.get("text_dominance_ratio", 1.0))
        if ratio >= 0.35:
            g.errors.append(f"text-dominance ratio {ratio:.2f} >= 0.35")
        g.passed = not g.errors
        g.warnings.append(f"text ratio {ratio:.2f}")
    except Exception as e:  # noqa: BLE001
        g.errors.append(f"text-dominance gate failed: {e}")
        g.passed = False
    return g


def gate_composition(visualspec: dict) -> GateResult:
    """Phase B gate (§20–21): attention clarity, not density.

    Requires every beat to carry a composition plan with exactly one
    focal point (release/pause beats may be full-frame), sane negative
    space (avg empty >= 0.20) and decent focal contrast (avg >= 0.5).
    """
    g = _gate("composition")
    try:
        report = (visualspec.get("metadata", {}) or {}).get("composition_report")
        if report is None:
            from engine.visuals.composition_planner import plan_composition
            beats = visualspec.get("beats", [])
            wd = (visualspec.get("metadata", {}) or {}).get("world")
            world = None
            if wd:
                from engine.world.world_model import WorldState
                try:
                    world = WorldState.from_dict(wd)
                except Exception:  # noqa: BLE001
                    world = None
            report = plan_composition(beats, world).to_dict()
        avg_contrast = float(report.get("avg_focal_contrast", 0.0))
        avg_empty = float(report.get("avg_empty_area_ratio", 0.0))
        multi = report.get("beats_with_multiple_focal", []) or []
        no_focal = report.get("beats_without_focal", []) or []
        if avg_contrast < 0.5:
            g.errors.append(f"avg focal contrast {avg_contrast:.2f} < 0.5")
        if avg_empty < 0.20:
            g.errors.append(f"avg empty-area ratio {avg_empty:.2f} < 0.20 "
                            "(density maximized, attention unclear)")
        if multi:
            g.errors.append(f"beats with multiple focal points: {multi}")
        if len(no_focal) > max(1, len(visualspec.get("beats", [])) * 0.35):
            g.errors.append(f"too many beats without a focal point: {no_focal}")
        g.passed = not g.errors
        g.warnings.append(f"focal contrast {avg_contrast:.2f}, "
                          f"empty ratio {avg_empty:.2f}")
    except Exception as e:  # noqa: BLE001
        g.errors.append(f"composition gate failed: {e}")
        g.passed = False
    return g


# v2 entity types -> v1 Object.type enum (spec §1: v1 gates run
# unchanged; unknown v2 world types collapse to the generic "shape").
_V1_TYPE_MAP = {
    "light_source": "shape", "medium": "shape", "scatterer": "shape",
    "eye": "shape", "signal": "shape", "particle": "shape",
    "body": "shape", "planet": "shape", "observer": "shape",
    "molecule": "shape", "atom": "shape", "wave": "shape",
    "field": "shape", "label": "text", "node": "shape",
    "connection": "graph", "equation": "equation",
    "number": "number", "vector": "vector", "text": "text",
    "graph": "graph", "fraction": "fraction", "matrix": "matrix",
}


def _v1_object(obj: dict) -> dict:
    """Map a v2 object (world entity) to the v1 Object schema.

    v2 objects carry rich `properties` and open-ended `type` values;
    the v1 schema only allows id/type/value/position with a closed
    type enum.  Strip unknowns, remap the type, hoist position.
    """
    if not isinstance(obj, dict):
        return {"id": str(obj), "type": "shape"}
    props = obj.get("properties", {}) or {}
    out = {"id": str(obj.get("id", "obj")),
           "type": _V1_TYPE_MAP.get(str(obj.get("type", "shape")),
                                    "shape")}
    val = obj.get("value")
    if val is not None:
        out["value"] = str(val)
    pos = props.get("position") or (obj.get("position"))
    if isinstance(pos, dict) and "x" in pos and "y" in pos:
        out["position"] = {"x": float(pos["x"]), "y": float(pos["y"])}
    return out


def _v1_shims(visualspec: dict) -> tuple[dict, dict, dict]:
    """Derive v1-compatible beatsheet/shotlist/visualspec from a v2 spec
    so the proven v1 gates can run unchanged (spec §1: never replace
    proven correctness work)."""
    beats = visualspec.get("beats", [])
    bs_beats, sl_shots, vs_beats = [], [], []
    for i, b in enumerate(beats):
        bid = b.get("beat_id", f"b{i + 1:03d}")
        dur = float(b.get("duration", 1.5))
        bs_beats.append({
            "beat_id": bid, "start": 0.0, "end": dur, "duration": dur,
            "narration": b.get("narration", ""),
            "intent": b.get("intent", "explanation"),
            "importance": b.get("importance", "medium"),
            "objects": [o.get("id") for o in b.get("objects", [])
                         if isinstance(o, dict) and o.get("id")],
            "visual_change_required": True,
        })
        sl_shots.append({
            "shot_id": f"s{i + 1:03d}", "beat_id": bid,
            "visual_type": b.get("visual_type", "") or "highlight",
            "renderer": "manim",
            "objects": [_v1_object(o) for o in b.get("objects", [])],
            "actions": [t for t in b.get("transformations", [])
                         if isinstance(t, dict) and t.get("type")],
            "camera": b.get("camera", {"type": "static"}),
        })
        vs_beats.append({
            "beat_id": bid,
            "intent": b.get("intent", "explanation"),
            "duration": dur,
            "narration": b.get("narration", ""),
            "objects": [_v1_object(o) for o in b.get("objects", [])],
            "transformations": [t for t in b.get("transformations", [])
                                 if isinstance(t, dict) and t.get("type")],
            "camera": b.get("camera", {"type": "static"}),
            "visual_type": b.get("visual_type", ""),
        })
    topic = (visualspec.get("metadata", {}) or {}).get("topic", "")
    return ({"version": "v1", "beats": bs_beats},
            {"version": "v1", "shots": sl_shots},
            {"version": "v1", "beats": vs_beats,
             "metadata": {"topic": topic}})


def run_all_v2(visualspec: dict, video_path: Optional[Path] = None,
               audio_metrics: Optional[dict] = None,
               motion_metrics: Optional[dict] = None,
               expected_res: tuple = (1280, 720),
               expected_fps: int = 30) -> dict:
    """QA runner for v2 VisualSpecs (world model + semantic actions).

    Runs the proven v1 gates on v1 shims, then adds the v0.3 semantic
    gates (explanation score, text-dominance ratio) and recomputes the
    perceptual score with them included (spec §10, §27, §28).
    """
    bs, sl, vs = _v1_shims(visualspec)
    report = run_all(bs, sl, vs, {"version": "v1", "cues": []},
                     video_path=video_path, audio_metrics=audio_metrics,
                     motion_metrics=motion_metrics,
                     expected_res=expected_res, expected_fps=expected_fps)

    eg = gate_explanation(visualspec)
    tg = gate_text_dominance(visualspec)
    cg = gate_composition(visualspec)
    report["gates"]["explanation"] = {"passed": eg.passed,
                                        "errors": eg.errors,
                                        "warnings": eg.warnings}
    report["gates"]["text_dominance"] = {"passed": tg.passed,
                                           "errors": tg.errors,
                                           "warnings": tg.warnings}
    report["gates"]["composition"] = {"passed": cg.passed,
                                        "errors": cg.errors,
                                        "warnings": cg.warnings}
    # recompute perceptual with the semantic gates
    perc_keys = ["semantic", "layout", "motion", "continuity",
                 "explanation", "text_dominance", "composition"]
    perc = [report["gates"][k] for k in perc_keys if k in report["gates"]]
    perceptual = int(round(100.0 * sum(1 for g in perc if g["passed"])
                           / max(1, len(perc))))
    if report.get("frame_visual_qa"):
        longest = report["frame_visual_qa"].get("longest_static_interval_s", 0.0)
        if longest >= DEAD_AIR_THRESHOLD_S:
            perceptual = max(0, perceptual - 15)
        if report.get("frame_layout_qa") \
                and report["frame_layout_qa"].get("conflict_frames"):
            perceptual = max(0, perceptual - 10)
    tech = report.get("technical_correctness", 0)
    report["perceptual_quality"] = perceptual
    report["score"] = int(round(0.6 * tech + 0.4 * perceptual))
    report["passed"] = (tech >= TECH_PASS_THRESHOLD
                         and perceptual >= PERC_PASS_THRESHOLD)
    for e in eg.errors + tg.errors + cg.errors:
        if e not in report["errors"]:
            report["errors"].append(e)
    report["explanation_report"] = (visualspec.get("metadata", {}) or {}).get(
        "explanation_report", {})
    report["composition_report"] = (visualspec.get("metadata", {}) or {}).get(
        "composition_report", {})
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
