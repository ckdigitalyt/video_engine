"""
Bridge between the Visual Director and the video asset pipeline.
For each shot, this module:
  1. Builds a search query from scene/beat metadata
  2. Calls asset_pipeline.search_asset() with cache-first + provider chain
  3. Downloads the best result
  4. Runs quality gates
  5. Falls through to FallbackDirector if all providers fail
"""

import logging, os, subprocess, tempfile
from pathlib import Path

import quality_gate as qg
from src.director.fallback_director import FallbackDirector
import asset_pipeline

logging.basicConfig(level=logging.WARNING)

_fallback_director = FallbackDirector()


def _build_search_query(scene, shot) -> str:
    """Build a concise search query from scene + shot metadata."""
    parts = []
    # Scene topic
    if hasattr(scene, "title") and scene.title:
        parts.append(scene.title)
    if hasattr(scene, "topic") and scene.topic:
        parts.append(scene.topic)
    # Shot keywords
    if hasattr(shot, "keywords") and shot.keywords:
        if isinstance(shot.keywords, list):
            parts.extend(shot.keywords[:3])
        else:
            parts.append(str(shot.keywords))
    if hasattr(shot, "description") and shot.description:
        parts.append(shot.description)
    # Scene style
    if hasattr(scene, "visual_style") and scene.visual_style:
        parts.append(scene.visual_style)
    if hasattr(scene, "mood") and scene.mood:
        parts.append(scene.mood)

    # Filter to meaningful words, limit length
    query = " ".join(str(p) for p in parts if p)
    # Remove very common/noise words
    stopwords = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "is", "it"}
    words = [w for w in query.split() if w.lower() not in stopwords]
    return " ".join(words[:10])  # max 10 words


def _probe_mp4(path: str) -> dict:
    """Use ffprobe to get video metadata."""
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "valid": False, "has_audio": False}
    if not path or not os.path.exists(path):
        return info
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-show_entries", "stream=codec_type,width,height,r_frame_rate",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
        import json
        data = json.loads(result.stdout)
        info["duration"] = float(data.get("format", {}).get("duration", 0))
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                info["width"] = int(s.get("width", 0))
                info["height"] = int(s.get("height", 0))
                fps_str = s.get("r_frame_rate", "0/1")
                if "/" in fps_str:
                    try:
                        num, den = fps_str.split("/")
                        info["fps"] = float(num) / float(den) if float(den) > 0 else 0
                    except:
                        pass
                info["valid"] = True
            elif s.get("codec_type") == "audio":
                info["has_audio"] = True
    except Exception:
        pass
    return info


def evaluate_asset(path: str) -> bool:
    """
    Quality gate: pass/fail for a downloaded asset.
    Returns True if the asset passes.
    """
    if not path or not os.path.exists(path):
        return False
    # Check file size (at least 50KB)
    if os.path.getsize(path) < 50 * 1024:
        return False
    info = _probe_mp4(path)
    if not info["valid"]:
        return False
    # Reject very short clips (< 1s)
    if info["duration"] < 1.0:
        return False
    # Resolution check
    if info["width"] < 640 or info["height"] < 360:
        return False
    if info["width"] > 7680 or info["height"] > 4320:
        return False
    return True


def fetch_asset(scene, shot, scene_number=0, beat_number=0, shot_number=0) -> str:
    """
    Main entry point: fetch the best video asset for a given shot.
    Returns local filepath string, or empty string on total failure.
    """
    query = _build_search_query(scene, shot)

    asset_pipeline.log_shot(
        scene_number=scene_number,
        beat_number=beat_number,
        shot_number=shot_number,
        search_query=query,
        provider="pending",
    )

    # Use the chain-of-responsibility pipeline
    local_path, provider_name = asset_pipeline.search_asset(
        query=query,
        scene_id=getattr(scene, "scene_id", 0),
        beat_num=beat_number,
        shot_num=shot_number,
        scene_number=scene_number,
    )

    if local_path and os.path.exists(local_path):
        # Run quality gate — skip for fallback clips (they're made to pass)
        if provider_name == "fallback" or "cache" in str(provider_name) or evaluate_asset(local_path):
            return local_path
        else:
            logging.warning(f"Asset failed quality gate: {local_path}")

    return ""
