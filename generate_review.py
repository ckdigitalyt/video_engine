#!/usr/bin/env python3
"""
Generate review.html — a visual shot-by-shot review report for the last pipeline run.

Reads:
  - asset_pipeline.export_shot_log()  (structured per-shot log)
  - timeline.json                     (timeline with file paths, durations, narration)
  - cache/video/*.mp4                 (thumbnail generation)

Output:
  review.html — standalone HTML with one row per shot including:
    * thumbnail (extracted frame)
    * narration text
    * search query
    * provider name
    * fallback used (yes/no)
    * final asset path
    * clip duration
    * quality score
    * comments
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Import asset pipeline to get the shot log
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asset_pipeline

CACHE_VIDEO = Path("cache/video")
THUMB_DIR = Path("cache/thumbs")
THUMB_DIR.mkdir(parents=True, exist_ok=True)


def extract_thumbnail(video_path: str, shot_index: int) -> str:
    """
    Extract a single thumbnail frame at 0.5s mark.
    Returns relative path to the thumbnail image.
    """
    if not video_path or not os.path.exists(video_path):
        return ""
    thumb_name = f"shot_{shot_index:04d}.jpg"
    thumb_path = THUMB_DIR / thumb_name
    if thumb_path.exists():
        return str(thumb_path)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "0.5", "-i", video_path,
             "-vframes", "1", "-q:v", "3", str(thumb_path)],
            capture_output=True, timeout=15,
        )
        if thumb_path.exists():
            return str(thumb_path)
    except Exception:
        pass
    return ""


def get_duration(video_path: str) -> float:
    """Get duration in seconds via ffprobe."""
    if not video_path or not os.path.exists(video_path):
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip()) if result.stdout.strip() else 0.0
    except Exception:
        return 0.0


def get_quality_score(entry: dict, duration: float) -> int:
    """
    Heuristic quality score 0-100.
      - fallback = baseline 30
      - real provider = 50 base
      - longer duration = bonus
      - from cache = small bonus
      - rejection = 0
    """
    provider = entry.get("provider", "")
    rejection = entry.get("rejection_reason", "")
    fb_reason = entry.get("fallback_reason", "")

    if rejection:
        return 0

    if provider == "fallback":
        base = 30
    elif "cache" in provider:
        base = 60
    else:
        base = 50

    # Duration bonus (up to +20)
    dur_bonus = min(int(duration * 2), 20) if duration else 0
    # Cache bonus
    cache_bonus = 10 if entry.get("from_cache") else 0

    return min(base + dur_bonus + cache_bonus, 100)


def generate_review_html():
    """Read the shot log and timeline, produce review.html."""
    entries = asset_pipeline.export_shot_log()
    if not entries:
        print("No shot log entries found. Run a pipeline first.")
        return

    # Load timeline to cross-reference
    timeline = {}
    try:
        with open("timeline.json") as f:
            tl = json.load(f)
        for vt in tl.get("video_timeline", []):
            # key by file path or index
            pass
    except:
        pass

    rows_html = []
    for idx, entry in enumerate(entries):
        video_path = entry.get("final_video_path", "")
        thumb = extract_thumbnail(video_path, idx)
        dur = get_duration(video_path)
        qscore = get_quality_score(entry, dur)
        is_fallback = "yes" if entry.get("provider") == "fallback" else "no"

        thumb_html = f'<img src="{thumb}" width="160" />' if thumb else "(no thumbnail)"
        dur_str = f"{dur:.1f}s" if dur > 0 else "N/A"

        rows_html.append(f"""
        <tr>
            <td>{entry.get('search_query', '')}</td>
            <td>{entry.get('provider', '')}</td>
            <td>{is_fallback}</td>
            <td style="text-align:center">{thumb_html}</td>
            <td>{dur_str}</td>
            <td style="text-align:center"><span class="score-{'low' if qscore < 40 else 'mid' if qscore < 70 else 'high'}">{qscore}</span></td>
            <td style="font-size:0.85em;max-width:250px;word-wrap:break-word">{video_path}</td>
            <td style="font-size:0.85em;color:#666">{entry.get('fallback_reason', '') or entry.get('rejection_reason', '')}</td>
        </tr>""")

    total = len(entries)
    fallbacks = sum(1 for e in entries if e.get("provider") == "fallback")
    cached = sum(1 for e in entries if e.get("from_cache"))
    real = total - fallbacks - cached
    fb_pct = f"{fallbacks / total * 100:.0f}%" if total else "N/A"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pipeline Review Report</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 20px; background: #f5f5f5; }}
  h1 {{ color: #333; }}
  .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
  .stat {{ background: #fff; border-radius: 8px; padding: 15px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); flex:1; }}
  .stat .num {{ font-size: 2em; font-weight: bold; color: #2563eb; }}
  .stat .label {{ font-size: 0.85em; color: #666; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th {{ background: #2563eb; color: #fff; padding: 12px 10px; text-align: left; font-size: 0.85em; }}
  td {{ padding: 10px; border-bottom: 1px solid #eee; font-size: 0.9em; vertical-align: top; }}
  tr:hover {{ background: #f0f7ff; }}
  .score-low {{ color: #dc2626; font-weight: bold; }}
  .score-mid {{ color: #d97706; font-weight: bold; }}
  .score-high {{ color: #16a34a; font-weight: bold; }}
  img {{ border-radius: 4px; border: 1px solid #ddd; }}
</style>
</head>
<body>
<h1>📽️ Pipeline Review Report</h1>
<div class="summary">
  <div class="stat"><div class="num">{total}</div><div class="label">Total Shots</div></div>
  <div class="stat"><div class="num">{real}</div><div class="label">External Provider</div></div>
  <div class="stat"><div class="num">{cached}</div><div class="label">From Cache</div></div>
  <div class="stat"><div class="num">{fallbacks}</div><div class="label">Fallbacks</div></div>
  <div class="stat"><div class="num">{fb_pct}</div><div class="label">Fallback %</div></div>
</div>
<table>
<thead>
<tr><th>Search Query</th><th>Provider</th><th>Fallback</th><th>Thumbnail</th><th>Duration</th><th>Quality</th><th>Asset Path</th><th>Notes</th></tr>
</thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
<p style="color:#999;font-size:0.8em;margin-top:20px">Generated: {__import__('datetime').datetime.now().isoformat()}</p>
</body>
</html>"""

    with open("review.html", "w") as f:
        f.write(html)
    print(f"✅ review.html written ({total} shots, {fallbacks} fallback, {cached} cached)")


if __name__ == "__main__":
    generate_review_html()
