"""
deterministic_qa.py — Deterministic quality assurance (pre-LLM).

Objective, software-based checks that never need an LLM:
  - repeated asset detection (same file used multiple times)
  - perceptual duplicate frames (dHash) + frozen shots
  - excessive static duration (no motion over a long window)
  - resolution / aspect checks
  - audio: silence, loudness, clipping, encoding integrity

Output is a QAReport with per-check pass/fail + metrics.  Rendering is
blocked ONLY on objective failures (see quality gates in mission docs).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image


# ═══════════════════════════════════════════════════════════════════════ #
# Perceptual hashing (dHash — difference hash, rotation/scale tolerant)
# ═══════════════════════════════════════════════════════════════════════ #

def dhash(image: Image.Image, hash_size: int = 16) -> str:
    """Compute the dHash of an image as a hex string."""
    img = image.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    bits = diff.flatten()
    # pack into hex
    hexed = []
    for i in range(0, len(bits), 4):
        v = 0
        for b in bits[i:i + 4]:
            v = (v << 1) | int(b)
        hexed.append(f"{v:x}")
    return "".join(hexed)


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))


# ═══════════════════════════════════════════════════════════════════════ #
# QA checks
# ═══════════════════════════════════════════════════════════════════════ #

@dataclass
class QACheck:
    name: str
    passed: bool
    detail: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class QAReport:
    checks: list[QACheck] = field(default_factory=list)
    blocking_failures: list[str] = field(default_factory=list)

    def add(self, check: QACheck):
        self.checks.append(check)
        if not check.passed:
            self.blocking_failures.append(check.name)

    def to_dict(self) -> dict:
        return {
            "passed": not self.blocking_failures,
            "blocking_failures": self.blocking_failures,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail,
                 "metrics": c.metrics}
                for c in self.checks
            ],
        }


class DeterministicQA:
    """Runs objective QA on a rendered video + its timeline."""

    def __init__(
        self,
        dup_threshold: int = 6,        # hamming distance < this => duplicate
        frozen_threshold_s: float = 2.5,  # identical frames for this long = frozen
        static_threshold_s: float = 8.0,  # low-motion window considered static
        silence_db: float = -50.0,
        clip_db: float = -0.5,
        sample_every: int = 15,        # sample every Nth frame for pHash
    ):
        self._dup_th = dup_threshold
        self._frozen_th = frozen_threshold_s
        self._static_th = static_threshold_s
        self._silence_db = silence_db
        self._clip_db = clip_db
        self._sample_every = sample_every

    # ── Main entry ─────────────────────────────────────────────────────

    def run(self, video_path: str, timeline_path: Optional[str] = None) -> QAReport:
        report = QAReport()
        if not os.path.exists(video_path):
            report.add(QACheck("file_exists", False, f"missing video: {video_path}"))
            return report

        # Encoding integrity + basic stream info
        probe = self._probe(video_path)
        report.add(QACheck("encoding", probe["has_video"] and probe["has_audio"],
                           detail=f"v={probe['video_codec']} a={probe['audio_codec']}",
                           metrics={"duration_s": probe["duration"],
                                    "resolution": probe["resolution"]}))
        if probe["resolution"]:
            w, h = probe["resolution"]
            report.add(QACheck("resolution", w >= 1280 and abs(w / h - 16 / 9) < 0.02,
                               detail=f"{w}x{h}"))
        else:
            report.add(QACheck("resolution", False, "unknown resolution"))

        # Repeated assets (from timeline if available)
        if timeline_path and os.path.exists(timeline_path):
            self._check_repeated_assets(timeline_path, report)
            self._check_motion_continuity(timeline_path, report)

        # Perceptual duplicate / frozen / static frames
        self._check_motion(video_path, report)

        # Audio checks
        self._check_audio(video_path, report)

        return report

    # ── Internals ──────────────────────────────────────────────────────

    def _probe(self, path: str) -> dict:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration:stream=codec_type,codec_name,width,height",
                 "-of", "json", path],
                capture_output=True, text=True, timeout=20,
            )
            data = json.loads(r.stdout)
            streams = data.get("streams", [])
            has_video = any(s.get("codec_type") == "video" for s in streams)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            vcodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "video"), "")
            acodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), "")
            vs = next((s for s in streams if s.get("codec_type") == "video"), {})
            res = (vs.get("width"), vs.get("height")) if vs.get("width") else None
            return {"has_video": has_video, "has_audio": has_audio,
                    "video_codec": vcodec, "audio_codec": acodec,
                    "resolution": res,
                    "duration": float(data.get("format", {}).get("duration", 0))}
        except Exception:
            return {"has_video": False, "has_audio": False, "video_codec": "",
                    "audio_codec": "", "resolution": None, "duration": 0}

    def _check_repeated_assets(self, timeline_path: str, report: QAReport):
        try:
            with open(timeline_path) as f:
                tl = json.load(f)
            entries = tl.get("video_timeline", [])
            files = [v.get("file", "") for v in entries]
            from collections import Counter
            counts = Counter(files)
            repeats = {f: c for f, c in counts.items() if c > 1 and "manim" not in f}
            # Perceptual repeats: same visual content under DIFFERENT filenames
            # (cached stills reused across scenes, coverage variants re-rendering
            # the same source still).  Exact-filename comparison alone misses
            # these — the Andromeda v5 run passed "no repeats" while reusing
            # 16 cached stills.  Sample one mid-frame per clip and compare dHashes.
            per_dups: list[dict] = []
            seen: list[tuple[float, str, str]] = []  # (ts, file, dhash)
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                for i, v in enumerate(entries):
                    f = v.get("file", "")
                    if not f or "manim" in f or not os.path.exists(f):
                        continue
                    st = v.get("start_time", 0.0)
                    et = v.get("end_time", st + 1.0)
                    mid = st + (et - st) / 2.0
                    # v21: prefer the SOURCE still (asset) when present — clip
                    # mid-frames are motion-shifted (Ken Burns) and dodge the
                    # hash; the source still is stable and catches coverage
                    # variants re-rendering the same image.
                    src = v.get("asset") or ""
                    hashed_path = src if (src and os.path.exists(src)) else f
                    frame = os.path.join(td, f"f{i}.jpg")
                    if hashed_path != src:
                        r = subprocess.run(
                            ["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}",
                             "-i", f, "-frames:v", "1", "-q:v", "5", frame],
                            capture_output=True, text=True, timeout=15)
                    else:
                        shutil.copy(src, frame)
                    if not os.path.exists(frame):
                        continue
                    try:
                        with Image.open(frame) as im:
                            h = dhash(im)
                    except Exception:
                        continue
                    for ts0, f0, h0 in seen:
                        if hamming(h, h0) < self._dup_th + 4:
                            per_dups.append({
                                "at": [round(ts0, 1), round(mid, 1)],
                                "files": [f0, f],
                                "hamming": hamming(h, h0),
                            })
                    seen.append((mid, f, h))
            detail = "no repeats"
            if repeats:
                detail = f"repeated files: {repeats}"
            if per_dups:
                detail += f"; perceptual repeats: {len(per_dups)} (same visual, different file)"
            report.add(QACheck(
                "repeated_assets", not repeats and not per_dups,
                detail=detail,
                metrics={"repeats": repeats, "perceptual_repeats": per_dups[:20]},
            ))
        except Exception as e:
            report.add(QACheck("repeated_assets", False, f"timeline parse error: {e}"))

    def _check_motion_continuity(self, timeline_path: str, report: QAReport):
        """Flag jarring camera-move flips at cut points.

        Uses the motion grammar (validate_motion_sequence): zoom_in→zoom_out,
        push_in→pull_out and similar directional reversals are forbidden
        because they read as a visible "jar" between clips.  Also flags
        lateral reversals (pan_left→pan_right).  The Andromeda v5 run had
        coverage variants that deliberately inverted the camera move, which is
        exactly this failure mode.
        """
        try:
            from src.director.motion_grammar import (
                validate_motion_sequence, get_motion_direction, MotionDirection,
            )
        except ImportError:
            return  # grammar unavailable — skip (planner enforces continuity too)
        try:
            with open(timeline_path) as f:
                tl = json.load(f)
            entries = tl.get("video_timeline", [])
            flips: list[dict] = []
            prev_move = None
            for v in entries:
                move = v.get("camera_move") or v.get("camera") or "static"
                if prev_move is not None and move != prev_move:
                    ok = validate_motion_sequence(prev_move, move)
                    if ok and prev_move in ("pan_left", "pan_right") and move in ("pan_left", "pan_right"):
                        ok = prev_move == move  # lateral reversal is a jar too
                    if not ok:
                        flips.append({
                            "at": v.get("start_time", 0.0),
                            "from": prev_move, "to": move,
                        })
                prev_move = move
            report.add(QACheck(
                "motion_continuity", not flips,
                detail=f"jarring camera flips at cuts: {flips}" if flips
                       else "camera moves continuous across cuts",
                metrics={"flips": flips},
            ))
        except Exception as e:
            report.add(QACheck("motion_continuity", False,
                               f"motion continuity check error: {str(e)[:120]}"))

    def _check_motion(self, video_path: str, report: QAReport):
        """Sample frames; detect perceptual dup runs (frozen) and static windows."""
        try:
            dur = self._probe(video_path)["duration"]
            fps = 30.0
            total_frames = max(1, int(dur * fps))
            step = max(1, int(fps * self._sample_every))
            hashes = []
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                for i in range(0, total_frames, step):
                    ts = i / fps
                    frame_path = os.path.join(td, f"f{i}.jpg")
                    r = subprocess.run(
                        ["ffmpeg", "-y", "-v", "error", "-ss", f"{ts:.2f}",
                         "-i", video_path, "-frames:v", "1", "-q:v", "5", frame_path],
                        capture_output=True, text=True, timeout=15,
                    )
                    if os.path.exists(frame_path):
                        try:
                            with Image.open(frame_path) as im:
                                hashes.append((ts, dhash(im)))
                        except Exception:
                            pass
            # Frozen runs: consecutive near-identical hashes
            frozen_runs = []
            run_start, run_len = None, 0
            for idx in range(len(hashes)):
                if idx > 0 and hamming(hashes[idx][1], hashes[idx - 1][1]) < self._dup_th:
                    if run_start is None:
                        run_start = hashes[idx - 1][0]
                    run_len += 1
                else:
                    if run_len and run_len * self._sample_every >= self._frozen_th:
                        frozen_runs.append((round(run_start, 1), round(run_len * self._sample_every, 1)))
                    run_start, run_len = None, 0
            report.add(QACheck(
                "frozen_shots", not frozen_runs,
                detail=f"frozen runs (>= {self._frozen_th}s): {frozen_runs}" if frozen_runs else "no frozen shots",
                metrics={"frozen_runs": frozen_runs, "frames_sampled": len(hashes)},
            ))
            # Static window: longest run regardless of threshold
            longest = max((r[1] for r in frozen_runs), default=0)
            report.add(QACheck(
                "excessive_static", longest <= self._static_th,
                detail=f"longest static window: {longest:.1f}s (limit {self._static_th}s)",
                metrics={"longest_static_s": longest},
            ))
        except Exception as e:
            report.add(QACheck("motion_qa", False, f"motion check error: {str(e)[:120]}"))

    def _check_audio(self, video_path: str, report: QAReport):
        try:
            r = subprocess.run(
                ["ffmpeg", "-i", video_path, "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
            import re
            mean = re.search(r"mean_volume: ([-\d.]+) dB", r.stderr)
            maxv = re.search(r"max_volume: ([-\d.]+) dB", r.stderr)
            mean_db = float(mean.group(1)) if mean else 0.0
            max_db = float(maxv.group(1)) if maxv else 0.0
            report.add(QACheck(
                "silence", max_db > self._silence_db,
                detail=f"max_volume={max_db:.1f} dB (silence < {self._silence_db} dB)",
                metrics={"max_db": max_db, "mean_db": mean_db},
            ))
            report.add(QACheck(
                "clipping", max_db < self._clip_db,
                detail=f"max_volume={max_db:.1f} dB (clip >= {self._clip_db} dB)",
                metrics={"max_db": max_db},
            ))
        except Exception as e:
            report.add(QACheck("audio_qa", False, f"audio check error: {str(e)[:120]}"))


if __name__ == "__main__":
    import sys
    qa = DeterministicQA()
    rep = qa.run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(rep.to_dict(), indent=2))
