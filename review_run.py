#!/usr/bin/env python3
"""
review_run.py — Generate two evaluation videos for the quality review phase.

Usage:
    python review_run.py

Each video is produced by the existing pipeline with a different topic.
Artifacts are saved under review_outputs/<topic_name>/.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

VIDEOS = [
    {
        "topic": "Why Haven't We Found Aliens? The Fermi Paradox Explained",
        "slug": "fermi_paradox",
    },
    {
        "topic": "The Rise and Fall of the Roman Empire in 10 Minutes",
        "slug": "roman_empire",
    },
]

# Files to archive after each run (relative to project root)
ARTIFACTS = [
    ("timeline.json", "timeline.json"),
    ("eval_reports/eval_report.json", "eval_report.json"),
    ("eval_reports/eval_report.csv", "eval_report.csv"),
    ("eval_reports/eval_report.md", "eval_report.md"),
]


def run_pipeline(topic: str, output_rel: str) -> None:
    """Run the pipeline for a single topic."""
    cmd = [
        sys.executable, str(PROJECT_ROOT / "orchestrator.py"),
        "--topic", topic,
        "--output", str(PROJECT_ROOT / output_rel),
    ]
    print(f"\n{'='*70}")
    print(f"RUNNING: {topic}")
    print(f"OUTPUT:  {output_rel}")
    print(f"{'='*70}\n")

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"\n✗ Pipeline failed for topic: {topic}")
        raise RuntimeError(f"Pipeline exited with code {result.returncode}")
    print(f"\n✓ Pipeline completed for: {topic}")


def archive_artifacts(slug: str) -> None:
    """Copy artifacts into review_outputs/<slug>/."""
    out_dir = PROJECT_ROOT / "review_outputs" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy the final video
    video_src = PROJECT_ROOT / f"{slug}.mp4"
    if video_src.exists():
        shutil.copy2(video_src, out_dir / f"{slug}.mp4")
        print(f"  Video  → {out_dir / f'{slug}.mp4'}")

    # Copy other artifacts
    for rel, name in ARTIFACTS:
        src = PROJECT_ROOT / rel
        if src.exists():
            shutil.copy2(src, out_dir / name)
            print(f"  {name} → {out_dir / name}")

    # Also copy subtitles if generated
    for sub_file in ["subtitles.srt", "subtitles.vtt"]:
        src = PROJECT_ROOT / sub_file
        if src.exists():
            shutil.copy2(src, out_dir / sub_file)
            print(f"  {sub_file} → {out_dir / sub_file}")

    print(f"\nAll artifacts saved to: {out_dir}")


def main() -> None:
    os.chdir(PROJECT_ROOT)

    for vid in VIDEOS:
        topic = vid["topic"]
        slug = vid["slug"]
        output_rel = f"{slug}.mp4"

        # Run pipeline
        run_pipeline(topic, output_rel)

        # Archive artifacts
        archive_artifacts(slug)

    print(f"\n{'='*70}")
    print("BOTH VIDEOS COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
