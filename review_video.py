#!/usr/bin/env python3
"""
review_video.py — Send the finished video's metadata and stats to DeepSeek
for an expert algorithm review and improvement suggestions.

Usage:
    python3 review_video.py results/olbers_v3/olbers_paradox_v3.mp4
"""

import json, os, sys, subprocess, textwrap
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.providers.factory import ProviderFactory
from src.providers.llm_provider import DeepSeekProvider
from src.utils.config import get_config
import os

REPORT_PATH = "docs/review_v3.md"


def probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except Exception:
        return 0.0


def probe_resolution(path: str) -> str:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        parts = r.stdout.strip().split(",")
        if len(parts) == 2:
            return f"{parts[0]}x{parts[1]}"
    except Exception:
        pass
    return "unknown"


def gather_stats() -> dict:
    """Collect all available stats from the log and timeline."""
    stats = {}

    # Parse the log for stats section
    log_path = "/tmp/olbers_v3_run.log"
    log_text = ""
    if os.path.exists(log_path):
        with open(log_path) as f:
            log_text = f.read()

    # Extract numbers from the log
    import re
    m = re.search(r'Director: ([\d.]+)s.*Render: ([\d.]+)s.*Total: ([\d.]+)s', log_text)
    if m:
        stats["director_time_s"] = float(m.group(1))
        stats["render_time_s"] = float(m.group(2))
        stats["total_time_s"] = float(m.group(3))

    m = re.search(r'Real assets: (\d+)/(\d+)', log_text)
    if m:
        stats["real_assets"] = int(m.group(1))
        stats["total_shots"] = int(m.group(2))

    m = re.search(r'Avg shot: ([\d.]+)s', log_text)
    if m:
        stats["avg_shot_s"] = float(m.group(1))

    m = re.search(r'Transitions: ({.*?})', log_text)
    if m:
        try:
            stats["transitions"] = json.loads(m.group(1).replace("'", '"'))
        except:
            pass

    m = re.search(r'Motions: ({.*?})', log_text)
    if m:
        try:
            stats["motions"] = json.loads(m.group(1).replace("'", '"'))
        except:
            pass

    m = re.search(r'Providers: ({.*?})', log_text)
    if m:
        try:
            stats["providers"] = json.loads(m.group(1).replace("'", '"'))
        except:
            pass

    # Timeline data
    timeline_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timeline.json")
    if os.path.exists(timeline_path):
        with open(timeline_path) as f:
            tl = json.load(f)
        stats["num_video_clips"] = len(tl.get("video_timeline", []))
        stats["num_scenes"] = len(tl.get("scenes", []))

    return stats


def build_prompt(stats: dict, video_path: str) -> str:
    """Build the review prompt with all available data."""

    transitions_str = json.dumps(stats.get("transitions", {}), indent=2)
    motions_str = json.dumps(stats.get("motions", {}), indent=2)
    providers_str = json.dumps(stats.get("providers", {}), indent=2)

    prompt = f"""You are a senior video-engineering algorithms expert. Review this AI-generated video render and suggest specific, actionable algorithm improvements.

## Video Metadata
- File: {video_path}
- Size: {os.path.getsize(video_path) / 1024 / 1024:.1f} MB
- Duration: {probe_duration(video_path):.1f}s
- Resolution: {probe_resolution(video_path)}

## Pipeline Performance
- Director planning: {stats.get('director_time_s', '?')}s
- Render: {stats.get('render_time_s', '?')}s
- Total: {stats.get('total_time_s', '?')}s

## Asset Quality
- Real assets (non-fallback): {stats.get('real_assets', '?')} / {stats.get('total_shots', '?')}
- Providers used: {providers_str}
- Average shot duration: {stats.get('avg_shot_s', '?')}s

## Editing Config
- Transitions: {transitions_str}
- Motions: {motions_str}

This video was rendered with "Olbers V3" algorithm — a documentary-style short (~65s target) about Olbers' Paradox ("Why is the Sky Dark at Night?"). It uses:
- Asset-first pipeline: Pexels → Pixabay → NASA → Wikimedia → fallback
- Cinematic voiceover (kokoro TTS)
- Beat-based shot planning via VisualDirector
- Scene-level editorial planner

## Review Request
1. **Transition analysis**: The config aimed for CUT/static, but the output shows crossfade and motion. Why would this happen? Fix recommendation.
2. **Shot duration**: Min 3.0s was configured but motion + multiple assets per beat were used. What's the optimal shot length for documentary pacing?
3. **Provider chain**: NASA provided 19/22 shots. Should we prioritize video providers (Pexels/Pixabay) over still-image providers? Tradeoffs?
4. **Visual variety**: 3 Pexels + 19 NASA stills + ken burns motion. How can we improve visual interest without flickering?
5. **Render speed**: 7.6min planning + 1min render for a ~65s video. What bottlenecks exist? How to speed up?
6. **Quality heuristic**: How should we weight image quality, relevance, and motion safety when selecting shots?
7. **Summary recommendations**: Top 3-5 specific code/algorithm changes you'd make.

Be specific — reference line numbers not needed, but do suggest concrete config values, parameter changes, or architectural shifts."""

    return prompt


def write_report(review_text: str, stats: dict, video_path: str):
    os.makedirs("docs", exist_ok=True)
    report = f"""# Video Algorithm Review — Olbers V3

**Reviewed:** {__import__('datetime').datetime.now().isoformat()}
**Video:** {video_path} ({os.path.getsize(video_path)/1024/1024:.1f} MB, {probe_duration(video_path):.1f}s)

---

## Pipeline Stats Summary

| Metric | Value |
|---|---|
| Director planning | {stats.get('director_time_s', '?')}s |
| Render time | {stats.get('render_time_s', '?')}s |
| Total time | {stats.get('total_time_s', '?')}s |
| Real assets | {stats.get('real_assets', '?')}/{stats.get('total_shots', '?')} |
| Avg shot | {stats.get('avg_shot_s', '?')}s |
| Providers | {json.dumps(stats.get('providers', {}))} |
| Transitions | {json.dumps(stats.get('transitions', {}))} |
| Motions | {json.dumps(stats.get('motions', {}))} |

---

## LLM Review

{review_text}

---

*Generated by review_video.py*
"""
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    print(f"✅ Report written to {REPORT_PATH}")


def main():
    video_path = sys.argv[1] if len(sys.argv) > 1 else "results/olbers_v3/olbers_paradox_v3.mp4"
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), video_path)
    if not os.path.exists(full_path):
        print(f"❌ Video not found: {full_path}")
        sys.exit(1)

    print(f"📊 Gathering stats for {video_path}...")
    stats = gather_stats()

    print(f"🤖 Sending to DeepSeek for review...")
    prompt = build_prompt(stats, video_path)

    llm = DeepSeekProvider()

    try:
        review = llm.generate_text(prompt)
        print("\n" + "=" * 60)
        print("REVIEW RECEIVED")
        print("=" * 60)
        print(review)
        write_report(review, stats, video_path)
    except Exception as e:
        print(f"❌ LLM call failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
