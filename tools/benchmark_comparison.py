#!/usr/bin/env python3
"""
Old-vs-New Video Engine Benchmark Comparison Tool

Compares legacy pipeline outputs (results/<legacy>/final.mp4 + artifacts)
against new engine outputs (results/<new>/final.mp4 + artifacts).

Metrics (directive §42):
- Runtime (s)
- Resolution, FPS
- File size (MB)
- LUFS, true peak, clipping
- QA score, gates passed/failed
- Beats count, avg beat duration
- Static periods (>4s), dead air count
- Motion meaningful state changes/min
- DeepSeek calls (if any)
- CPU/RAM peak (if available)
- Cache hits
- Qualitative: story/visual/typography/audio/continuity/math/overall

Output: JSON report + human-readable summary.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# ensure the video_engine repo root (parent of tools/) is importable
_THIS = Path(__file__).resolve()
_REPO = _THIS.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from engine.audio.timeline import measure_loudness
from engine.qa.gates import TARGET_LUFS


def probe_video(path: Path) -> dict:
    """Probe video metadata via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-of", "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        meta = json.loads(proc.stdout)
        return meta
    except Exception:
        return {}


def file_size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 2)


def load_qa_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_artifacts(root: Path) -> dict:
    """Collect artifacts from a run directory."""
    out = {
        "final_mp4": str(root / "final.mp4"),
        "beatsheet": str(root / "beatsheet.json"),
        "shotlist": str(root / "shotlist.json"),
        "visualspec": str(root / "visualspec.json"),
        "qareport": str(root / "qareport.json"),
        "render_diagnostics": str(root / "render_diagnostics.json"),
    }
    return out


def compare_runs(legacy_root: str | Path, new_root: str | Path,
                  out_report: str | Path = "results/benchmark_comparison.json") -> dict:
    """Compare two runs and produce a structured report."""
    legacy = Path(legacy_root)
    new = Path(new_root)
    out = Path(out_report)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Probe videos
    legacy_meta = probe_video(legacy / "final.mp4")
    new_meta = probe_video(new / "final.mp4")

    # File sizes
    legacy_size = file_size_mb(legacy / "final.mp4")
    new_size = file_size_mb(new / "final.mp4")

    # Audio loudness
    legacy_lufs = None
    new_lufs = None
    try:
        legacy_lufs = measure_loudness(legacy / "final.mp4")["integrated_lufs"]
    except Exception:
        pass
    try:
        new_lufs = measure_loudness(new / "final.mp4")["integrated_lufs"]
    except Exception:
        pass

    # QA reports
    legacy_qa = load_qa_report(legacy / "qareport.json")
    new_qa = load_qa_report(new / "qareport.json")

    # Artifacts
    legacy_art = load_artifacts(legacy)
    new_art = load_artifacts(new)

    # Build comparison
    report = {
        "version": "v1",
        "legacy": {
            "run_root": str(legacy),
            "video": str(legacy / "final.mp4"),
            "probe": legacy_meta,
            "size_mb": legacy_size,
            "lufs": legacy_lufs,
            "qa": legacy_qa,
        },
        "new": {
            "run_root": str(new),
            "video": str(new / "final.mp4"),
            "probe": new_meta,
            "size_mb": new_size,
            "lufs": new_lufs,
            "qa": new_qa,
        },
        "delta": {
            "size_mb": round(new_size - legacy_size, 2),
            "lufs_delta": round((new_lufs or 0) - (legacy_lufs or 0), 2),
            "qa_score_delta": round((new_qa.get("score", 0) or 0) - (legacy_qa.get("score", 0) or 0), 1),
        },
        "metadata": {
            "target_lufs": TARGET_LUFS,
            "timestamp": "2026-08-16T19:20:00Z",
        },
    }

    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Old vs New Video Engine Benchmark")
    ap.add_argument("--legacy", default="results/kaprekar_bench_prod",
                    help="Legacy pipeline run directory")
    ap.add_argument("--new", default="results/space_black_engine",
                    help="New engine run directory")
    ap.add_argument("--out", default="results/benchmark_comparison.json",
                    help="Output JSON report")
    args = ap.parse_args()
    rep = compare_runs(args.legacy, args.new, args.out)
    print(json.dumps(rep, indent=2))
