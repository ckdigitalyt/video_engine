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
import re
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

# virality gates (v0.3, 2026-08 deep-review directive)
BLACK_LUMA_THRESHOLD = 0.02    # mean frame luma below this = black
BLACK_RUN_MAX_S = 0.5          # contiguous black run > this fails (post-render)
TEMPLATE_SIMILARITY_MAX = 0.75 # narration vs generic filler fuzzy ratio
MIN_TOPIC_TOKENS = 3           # distinct domain tokens required in script

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


# ── Virality gate: script topic-specificity (pre-TTS) ──────────────────
_TOPIC_TOKEN_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "her", "was", "one", "out", "has", "have", "with", "this", "that",
    "from", "what", "why", "how", "when", "where", "who", "into", "its",
    "it's", "his", "their", "they", "them", "than", "then", "more",
    "most", "much", "very", "over", "under", "about", "after", "before",
    "because", "does", "did", "will", "would", "could", "should",
    "there", "here", "never", "always", "exactly", "equal", "equals",
    "times", "per", "units", "unit", "area", "volume", "value", "claim",
})


def _generic_sentence_bank() -> list[str]:
    """The generic template filler bank, sourced from the templates code
    (world_director.ROLE_SENTENCES) so the two can never drift."""
    try:
        from engine.visuals.world_director import ROLE_SENTENCES
        return sorted({s.strip() for s in ROLE_SENTENCES.values() if s.strip()})
    except Exception:  # noqa: BLE001
        return []


def gate_script_specificity(visualspec: dict) -> GateResult:
    """Pre-TTS virality gate: the narration must be ABOUT the topic.

    Hard-fails when the topic has research facts (production path) and:
      - fewer than MIN_TOPIC_TOKENS distinct domain tokens from
        topic+facts appear in the script, or
      - the script carries no numeric claim (digit or math symbol), or
      - any narration sentence is >TEMPLATE_SIMILARITY_MAX similar to a
        generic template filler line ("What is really going on here?",
        "Now you know.", ...) — the topic-agnostic template leak that
        produced the content-free Gabriel's Horn video.

    Topics WITHOUT facts only get warnings here — they can never reach a
    render anyway: run_daily hard-fails them earlier with outcome
    no_topic_knowledge.
    """
    import difflib
    import re
    g = _gate("script_specificity")
    md = visualspec.get("metadata", {}) or {}
    topic = str(md.get("topic", ""))
    facts = md.get("facts", []) or []
    narrations = [str(b.get("narration", "")).strip()
                  for b in visualspec.get("beats", [])
                  if b.get("narration")]
    if not narrations:
        g.passed = False
        g.errors.append("no narration in visualspec — empty script")
        return g
    script_text = " ".join(narrations).lower()

    if not facts:
        g.warnings.append(
            "topic has no research facts — script is topic-agnostic; "
            "daily_run must hard-fail such topics (no_topic_knowledge)")
        g.passed = True
        return g

    tokens: set[str] = set()

    def _collect(text: str) -> None:
        for w in re.findall(r"[a-z][a-z\-']{2,}", text.lower()):
            w = w.strip("'-")
            if len(w) >= 3 and w not in _TOPIC_TOKEN_STOPWORDS:
                tokens.add(w)

    _collect(topic)
    for f in facts:
        if isinstance(f, dict):
            _collect(str(f.get("claim", "")))
            _collect(str(f.get("formula", "")))
        else:
            _collect(getattr(f, "claim", ""))
            _collect(getattr(f, "formula", ""))
    present = sorted(t for t in tokens if t in script_text)
    if len(present) < MIN_TOPIC_TOKENS:
        g.passed = False
        g.errors.append(
            f"script specificity: only {len(present)} topic domain tokens "
            f"{present[:8]} (need >= {MIN_TOPIC_TOKENS}) — narration is "
            f"not about '{topic}'")
    facts_mathy = False
    for f in facts:
        txt = (str(f.get("claim", "")) + str(f.get("formula", ""))) \
            if isinstance(f, dict) else \
            (str(getattr(f, "claim", "")) + str(getattr(f, "formula", "")))
        if re.search(r"[0-9\u03c0\u221e\u2248\u221a\u222b\u00d7\u00b1=<>]",
                     txt):
            facts_mathy = True
            break
    if facts_mathy and not re.search(
            r"[0-9\u03c0\u221e\u2248\u221a\u222b\u00d7\u00b1=<>]", script_text):
        g.passed = False
        g.errors.append("script specificity: no numeric claim (digit or "
                        "math symbol) in narration")
    bank = _generic_sentence_bank()
    for n in narrations:
        nl = n.lower().strip()
        for filler in bank:
            ratio = difflib.SequenceMatcher(None, nl, filler.lower()).ratio()
            if ratio > TEMPLATE_SIMILARITY_MAX:
                g.passed = False
                g.errors.append(
                    f"template leak: narration {n[:60]!r} is "
                    f"{ratio:.0%} similar to generic filler {filler!r}")
    g.warnings.append(f"topic tokens present: {present[:8]}")
    return g


# ── Virality gate: scene coverage (planning level) ────────────────────
def _beat_object_ids(beat: dict) -> list[str]:
    ids = []
    for o in beat.get("objects", []) or []:
        if isinstance(o, dict):
            ids.append(str(o.get("id", "")))
        else:
            ids.append(str(o))
    return [i for i in ids if i]


def _beat_action_keys(beat: dict) -> tuple:
    keys = []
    for a in beat.get("semantic_actions", []) or []:
        if isinstance(a, dict):
            keys.append((str(a.get("action", a.get("type", ""))),
                         str(a.get("target", ""))))
    return tuple(sorted(keys))


def gate_scene_coverage(visualspec: dict) -> GateResult:
    """Planning-level virality gate (the Gabriel's Horn black-frame fix):

      1. Every beat must map to REAL content: a beat with no entities and
         no semantic actions (narration + camera only) renders BLACK
         FRAMES — hard fail.
      2. A single diagram/asset may not span > 2 consecutive script
         lines: more than 2 consecutive beats with an identical
         (object-ids + action) signature mean one static rig covers the
         whole video (the generic cause->effect failure mode).
    """
    g = _gate("scene_coverage")
    beats = visualspec.get("beats", [])
    for b in beats:
        bid = b.get("beat_id", "?")
        objs = _beat_object_ids(b)
        acts = _beat_action_keys(b)
        tfs = [str(t.get("type", ""))
               for t in b.get("transformations", []) or []
               if isinstance(t, dict)]
        if not objs and not acts and not tfs:
            g.passed = False
            g.errors.append(
                f"{bid}: beat maps to an EMPTY scene (no entities, no "
                f"actions) — narration {str(b.get('narration', ''))[:40]!r} "
                "would render black frames")
    # static-rig span: identical signature across consecutive beats
    run_len = 0
    prev_sig = None
    for b in beats:
        sig = (tuple(sorted(_beat_object_ids(b))), _beat_action_keys(b))
        if sig == prev_sig:
            run_len += 1
        else:
            run_len = 1
            prev_sig = sig
        if run_len > 2:
            g.passed = False
            g.errors.append(
                f"{b.get('beat_id', '?')}: single diagram/asset spans "
                f"> 2 consecutive script lines (static rig, signature "
                f"{sig[0]}/{sig[1]}) — 1:1 line-to-scene coverage required")
    return g


# ── Virality gate: black frames (post-render, real pixels) ────────────
def gate_black_frames(video_path: Path,
                      allow_scripted_black: bool = False,
                      sample_fps: float = 4.0) -> GateResult:
    """Post-render virality gate on REAL sampled pixels: fail when any
    contiguous run longer than BLACK_RUN_MAX_S has mean luma below
    BLACK_LUMA_THRESHOLD (the ~5.2s black climax of the Gabriel's Horn
    video would have been caught here).

    ``allow_scripted_black`` (visualspec metadata 'allow_scripted_black')
    downgrades detected runs to warnings for intentional fadeouts."""
    import numpy as np
    g = _gate("black_frames")
    vp = Path(video_path)
    if not vp.exists():
        g.passed = False
        g.errors.append(f"video file missing: {video_path}")
        return g
    frames = _sample_gray_frames(vp, sample_fps)
    if not frames:
        g.passed = False
        g.errors.append("no frames could be sampled for black-frame QA")
        return g
    means = [float(f.mean()) / 255.0 for f in frames]
    runs: list[tuple[float, float, float]] = []  # (start_s, end_s, luma)
    start = None
    for i, m in enumerate(means):
        if m < BLACK_LUMA_THRESHOLD:
            if start is None:
                start = i
        else:
            if start is not None:
                runs.append((start / sample_fps, i / sample_fps,
                             float(np.mean(means[start:i]))))
                start = None
    if start is not None:
        runs.append((start / sample_fps, len(means) / sample_fps,
                     float(np.mean(means[start:]))))
    long_runs = [r for r in runs if (r[1] - r[0]) > BLACK_RUN_MAX_S]
    for a, b_, luma in long_runs:
        msg = (f"black frames: contiguous run {a:.2f}s–{b_:.2f}s "
               f"({b_ - a:.2f}s) with mean luma {luma:.4f} < "
               f"{BLACK_LUMA_THRESHOLD}")
        if allow_scripted_black:
            g.warnings.append(msg + " (allowed: scripted black)")
        else:
            g.passed = False
            g.errors.append(msg)
    g.warnings.append(
        f"black-frame scan: {len(frames)} frames @ {sample_fps:g}fps, "
        f"{len(long_runs)} run(s) > {BLACK_RUN_MAX_S}s")
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
    """Perceptual gate: avg visual explanation score >= 3.5, the video
    is not dominated by level 0-2 beats (spec §10), and the explanatory
    purposes (demonstrate/illustrate/compare) dominate support classes
    (spec §13 — visuals must explain, not decorate)."""
    g = _gate("explanation")
    try:
        # Always recompute from the ACTUAL beats: planning-time reports go
        # stale after local repair / recompose (§30), and scoring is cheap
        # and deterministic.  The cached metadata report stays as the
        # planning record in the artifact, but the gate judges reality.
        from engine.world.scoring import score_beatsheet
        report = score_beatsheet(visualspec.get("beats", [])).to_dict()
        avg = float(report.get("average_explanation_score", 0.0))
        dominated = bool(report.get("dominated_by_level_0_2", False))
        expl_dominated = bool(report.get("explanatory_dominated", False))
        if avg < 3.5:
            g.errors.append(f"avg visual explanation score {avg:.2f} < 3.5")
        if dominated:
            g.errors.append("video dominated by level 0-2 beats — send back "
                            "to the VisualDirector")
        if expl_dominated:
            g.errors.append("support purposes (emphasize/transition/"
                            "atmosphere) dominate — visuals must explain, "
                            "not decorate (§13)")
        g.passed = not g.errors
        g.warnings.append(f"avg explanation {avg:.2f}")
    except Exception as e:  # noqa: BLE001
        g.errors.append(f"explanation gate failed: {e}")
        g.passed = False
    return g


# ── Virality gate: text crossfade overlap (planning level) ────────────
_TEXT_LAYER_ENTER_RE = re.compile(
    r"\b(RevealText|PayoffText|QuestionMark|KineticTypography|ClaimReveal|"
    r"CycleReveal|MeasureValue|Comparison)\(self")
_TEXT_PRIM_OID = {
    "RevealText": "reveal", "PayoffText": "payoff",
    "QuestionMark": "question", "KineticTypography": "kinetic",
    "ClaimReveal": "claim", "CycleReveal": "cycle",
    "Comparison": "comparison",
}
_BEAT_RE = re.compile(r"begin_beat\(\s*['\"]([^'\"]+)['\"]\s*\)")
_TEXT_EXIT_RE = re.compile(
    r"\b(?:exit_object|clear_object)\(\s*self\s*,\s*self\._state\s*,"
    r"\s*['\"]([^'\"]+)['\"]")


def _extract_py_literal(line: str, prefix: str) -> Optional[str]:
    """Extract the balanced ``{...}`` literal following ``prefix`` on a
    generated single-statement source line (None when absent/unbalanced).
    Handles nested braces and quoted strings with backslash escapes."""
    i = line.find(prefix)
    if i < 0:
        return None
    j = line.find("{", i + len(prefix))
    if j < 0:
        return None
    depth = 0
    quote = None
    esc = False
    for k in range(j, len(line)):
        ch = line[k]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return line[j:k + 1]
    return None


def analyze_text_layer_source(source: str) -> list[str]:
    """Statically simulate the TEXT-layer lifecycle of a compiled world
    scene and return overlap errors (empty list = clean).

    The generated scene is one statement per line, so the simulation is a
    deterministic line scan: text layers enter via text-entity
    materializations, text semantic actions (measure/fill/compare/reveal,
    per ``world_primitives.text_layer_oid``) and the direct narrative
    primitives; they leave via ``exit_object``/``clear_object``.  A text
    layer entering while ANY text layer is still on stage is the
    crossfade-overlap bug (two superimposed formula layers, Gabriel's
    Horn -r3 t≈13–33s).  The one legal overlap-shaped pattern is a
    measure that retargets a text card already on stage — an in-place
    REPLACEMENT (``world_primitives._replace_text_layer``), never a
    second layer.
    """
    import ast
    from engine.primitives.world_primitives import (
        TEXT_ENTITY_TYPES, TEXT_LAYER_ACTIONS, text_layer_oid)
    errors: list[str] = []
    stage: dict[str, str] = {}  # text-layer oid -> beat it entered
    beat = "?"

    def _overlap(oid: str) -> None:
        held = ", ".join(f"'{o}'" for o in sorted(stage))
        errors.append(
            f"beat {beat}: text layer '{oid}' enters while text layer(s) "
            f"[{held}] still on stage — crossfade overlap (the previous "
            "text layer must be exited or replaced first)")

    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _BEAT_RE.search(line)
        if m:
            beat = m.group(1)
            continue
        if "exit_object(" in line or "clear_object(" in line:
            m = _TEXT_EXIT_RE.search(line)
            if m:
                stage.pop(m.group(1), None)
            continue
        if "materialize_entity(" in line:
            lit = _extract_py_literal(
                line, "materialize_entity(self, self._state, ")
            if lit:
                try:
                    ent = ast.literal_eval(lit)
                except (ValueError, SyntaxError):
                    ent = None
                if (isinstance(ent, dict)
                        and str(ent.get("type", "")) in TEXT_ENTITY_TYPES):
                    oid = str(ent.get("id", ""))
                    if stage:
                        _overlap(oid)
                    stage[oid] = beat
            continue
        if "apply_action(" in line:
            lit = _extract_py_literal(line, "apply_action(self, self._state, ")
            if lit:
                try:
                    act = ast.literal_eval(lit)
                except (ValueError, SyntaxError):
                    act = None
                if isinstance(act, dict):
                    name = str(act.get("action", ""))
                    if name in TEXT_LAYER_ACTIONS:
                        target = str(act.get("target", ""))
                        if name == "measure" and target in stage:
                            # in-place replacement of an on-stage text card
                            continue
                        oid = text_layer_oid(name, target) or name
                        if stage:
                            _overlap(oid)
                        stage[oid] = beat
            continue
        m = _TEXT_LAYER_ENTER_RE.search(line)
        if m:
            prim = m.group(1)
            mo = re.search(r"\boid\s*=\s*['\"]([^'\"]+)['\"]", line)
            oid = mo.group(1) if mo else _TEXT_PRIM_OID.get(prim,
                                                            prim.lower())
            if stage:
                _overlap(oid)
            stage[oid] = beat
    return errors


def gate_text_overlap(visualspec: dict) -> GateResult:
    """Planning-level virality gate: text crossfade overlap.

    Compiles the VisualSpec to scene source (dry — no rendering) and
    statically simulates the text-layer lifecycle (see
    ``analyze_text_layer_source``).  Fails when any text/label/formula
    layer would be on stage while the next one enters — the Gabriel's
    Horn -r3 failure that superimposed two formula layers for ~20s
    (t≈13–33s, 2026-08-27).  Deterministic and fast: pure source
    analysis, no pixels.  A spec that cannot compile fails here too —
    it could never render anyway.
    """
    g = _gate("text_overlap")
    try:
        from engine.renderers.manim.world_compiler import (
            WorldCompileError, emit_world_scene)
        source = emit_world_scene(visualspec)
    except WorldCompileError as e:
        g.passed = False
        g.errors.append(f"text_overlap: visualspec does not compile: {e}")
        return g
    except Exception as e:  # noqa: BLE001
        g.passed = False
        g.errors.append(f"text_overlap: compile crashed: {e}")
        return g
    errors = analyze_text_layer_source(source)
    if errors:
        g.passed = False
        g.errors.extend(errors)
    g.warnings.append(
        "text-layer lifecycle simulated on compiled scene source "
        "(planning level)")
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


def gate_hero_quality(visualspec: dict) -> GateResult:
    """Phase C gate (§9–10, §12): hero mechanism is first-class + QC'd.

    Every video must have exactly one hero mechanism (the visual the
    viewer should remember), with a why_this_visual rationale, real
    objects/actions (spec §9 shape), and a hero beat that actually
    exists, is marked importance=high, and demonstrates (explanation
    score >= 4).  A plan without a clear hero FAILs (§10) so the
    VisualDirector must revise instead of rendering decoration.
    """
    g = _gate("hero_quality")
    try:
        md = visualspec.get("metadata", {}) or {}
        hero = md.get("hero_mechanism")
        if not hero:
            g.errors.append("no hero_mechanism in metadata (§9)")
            g.passed = False
            return g
        if not hero.get("why_this_visual"):
            g.errors.append("hero lacks why_this_visual rationale (§12)")
        if not hero.get("objects"):
            g.errors.append("hero objects empty (§9)")
        if not hero.get("actions"):
            g.errors.append("hero actions empty (§9)")
        tb = hero.get("target_beat", "")
        beats = visualspec.get("beats", [])
        hero_beat = next((b for b in beats if b.get("beat_id") == tb), None)
        if tb and not hero_beat:
            g.errors.append(f"hero target_beat {tb} not found in beats")
        if hero_beat is not None:
            if hero_beat.get("importance") != "high":
                g.errors.append(f"hero beat {tb} not importance=high")
            score = float(hero_beat.get("explanation_score", 0) or 0)
            if score < 4:
                g.errors.append(
                    f"hero beat {tb} explanation_score {score:.1f} < 4 "
                    "(hero must demonstrate, not decorate)")
        g.passed = not g.errors
        g.warnings.append(
            f"hero={hero.get('visualization')} @ {tb or '?'}")
    except Exception as e:  # noqa: BLE001
        g.errors.append(f"hero-quality gate failed: {e}")
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


def run_preflight_v2(visualspec: dict) -> dict:
    """Planning-level QA — the gates that can run BEFORE rendering (§28).

    These gates judge the plan (schema, semantics, explanation,
    text-dominance, composition, hero QC) and need no video file:
    used by the §33 regression suite and pre-render preflight so a bad
    plan is rejected before expensive rendering.
    """
    bs, sl, vs = _v1_shims(visualspec)
    report: dict = {"gates": {}, "errors": [], "warnings": []}
    for name, fn in (
        ("schema", lambda: gate_schema(bs, sl, vs, {})),
        ("semantic", lambda: gate_semantic(bs, vs)),
        ("explanation", lambda: gate_explanation(visualspec)),
        ("text_dominance", lambda: gate_text_dominance(visualspec)),
        ("composition", lambda: gate_composition(visualspec)),
        ("hero_quality", lambda: gate_hero_quality(visualspec)),
        ("script_specificity",
         lambda: gate_script_specificity(visualspec)),
        ("scene_coverage", lambda: gate_scene_coverage(visualspec)),
        ("text_overlap", lambda: gate_text_overlap(visualspec)),
    ):
        g = fn()
        report["gates"][name] = {"passed": g.passed,
                                   "errors": g.errors,
                                   "warnings": g.warnings}
        for e in g.errors:
            if e not in report["errors"]:
                report["errors"].append(e)
    perc_keys = ["schema", "semantic", "explanation", "text_dominance",
                 "composition", "hero_quality", "script_specificity",
                 "scene_coverage", "text_overlap"]
    perc = [report["gates"][k] for k in perc_keys if k in report["gates"]]
    report["perceptual_quality"] = int(round(
        100.0 * sum(1 for g in perc if g["passed"]) / max(1, len(perc))))
    report["passed"] = all(g["passed"] for g in perc)
    report["score"] = report["perceptual_quality"]
    return report


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
    hg = gate_hero_quality(visualspec)
    report["gates"]["explanation"] = {"passed": eg.passed,
                                        "errors": eg.errors,
                                        "warnings": eg.warnings}
    report["gates"]["text_dominance"] = {"passed": tg.passed,
                                           "errors": tg.errors,
                                           "warnings": tg.warnings}
    report["gates"]["composition"] = {"passed": cg.passed,
                                        "errors": cg.errors,
                                        "warnings": cg.warnings}
    report["gates"]["hero_quality"] = {"passed": hg.passed,
                                         "errors": hg.errors,
                                         "warnings": hg.warnings}
    if video_path is not None:
        allow_black = bool((visualspec.get("metadata", {}) or {}).get(
            "allow_scripted_black", False))
        bf = gate_black_frames(Path(video_path),
                               allow_scripted_black=allow_black)
        report["gates"]["black_frames"] = {"passed": bf.passed,
                                             "errors": bf.errors,
                                             "warnings": bf.warnings}
    # recompute perceptual with the semantic gates
    perc_keys = ["semantic", "layout", "motion", "continuity",
                 "explanation", "text_dominance", "composition",
                 "hero_quality", "black_frames"]
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
    # black frames at the climax are publish-blocking, not a score ding:
    # force-fail regardless of thresholds (Gabriel's Horn failure mode)
    if video_path is not None and not report["gates"].get(
            "black_frames", {}).get("passed", True):
        report["passed"] = False
    bf_errors = report["gates"].get("black_frames", {}).get("errors", [])
    for e in eg.errors + tg.errors + cg.errors + hg.errors + bf_errors:
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
