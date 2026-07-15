#!/usr/bin/env python3
"""
validate_concept_pipeline.py — Run 3 documentaries to validate the
ConceptPlanner→BeatDirector integration fix.

Collects per-topic and aggregate metrics.
"""

import json, os, sys, time, traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

TOPICS = [
    "The Fermi Paradox",
    "James Webb Space Telescope",
    "Black Holes Explained",
]
OUTPUT_DIR = Path("results/validation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run_topic(topic):
    """Run one documentary, collect metrics."""
    from src.providers.factory import ProviderFactory
    from src.planner import StoryPlanner
    from src.director.director import VisualDirector
    from src.assets.asset_router import AssetRouter
    from src.director.quality_gate import QualityGates
    from src.director.aesthetic_agent import AestheticAgent
    from src.director.visual_style import VisualStyle
    from src.director.fallback_director import FallbackDirector
    from src.director.concept_planner import ConceptPlanner
    from src.validation.semantic_validator import SemanticValidator
    from src.cinematic.director_integration import BeatDirector
    from src.utils.config import get_config
    from src.renderer.moviepy_renderer import MoviePyRenderer
    from src.renderer.timeline_builder import TimelineBuilder
    from src.subtitles.engine import SubtitleEngine
    from src.utils.duration import get_media_duration
    from audio_engine import generate_voice
    from src.models import Scene as PydanticScene, SceneAsset
    from src.models.schemas import AssetPlan, AudioPlan, ProviderType

    safe = topic.lower().replace(" ", "_").replace("'", "")
    output_path = str(OUTPUT_DIR / f"{safe}.mp4")
    metrics = {
        "topic": topic,
        "total_scenes": 0,
        "total_shots": 0,
        "primary_success": 0,
        "fallbacks": 0,
        "provider_usage": {},
        "semantic_pass": 0,
        "semantic_fail": 0,
        "total_semantic": 0.0,
        "render_duration": 0.0,
        "final_video_duration": 0.0,
        "exceptions": [],
        "video_path": output_path,
    }
    t0 = time.time()

    try:
        factory = ProviderFactory()
        planning_provider = factory.get_llm_provider_for_role("planner")
        planner = StoryPlanner(provider=planning_provider)
        scenes = planner.generate_plan(topic)

        director_scene_data = []
        for ps in scenes:
            sq = ps.search_plan.asset_search_queries
            search_query = sq[0] if sq else "general"
            director_scene_data.append({
                "scene_id": ps.scene_id,
                "narration": ps.narration.spoken_narration,
                "search_query": search_query,
                "scene_title": ps.title,
                "purpose": ps.search_plan.scene_purpose,
                "estimated_duration": ps.expected_duration,
            })

        metrics["total_scenes"] = len(scenes)

        director = VisualDirector(
            use_beats=True,
            topic=topic,
            llm_provider=planning_provider,
            scene_data=director_scene_data,
        )
        results = director.run()

        # Get beat director stats
        beat_director = getattr(director, '_beat_director', None)
        if beat_director:
            stats = beat_director.get_stats()
            metrics["total_shots"] = stats.get("shots_requested", 0)
            metrics["primary_success"] = stats.get("shots_accepted", 0)
            metrics["fallbacks"] = stats.get("fallbacks", 0)

        # Build timeline and render
        cache_video = get_config("pipeline.cache.video", "cache/video")
        cache_audio = get_config("pipeline.cache.audio", "cache/audio")

        scene_assets = []
        scene_narrations = []
        for s in results:
            sid = s.scene_id
            narration = s.narration.spoken_narration
            audio_path = os.path.join(cache_audio, f"scene_{sid}.wav")
            vid_path = s.asset_plan.filepath if s.asset_plan and s.asset_plan.filepath else os.path.join(cache_video, f"scene_{sid}.mp4")
            generate_voice(narration, audio_path)
            scene_assets.append(SceneAsset(scene_id=sid, video_path=vid_path, audio_path=audio_path))
            scene_narrations.append((sid, narration, audio_path))

            # Track provider usage
            if s.asset_plan and s.asset_plan.provider:
                prov = s.asset_plan.provider.value
                metrics["provider_usage"][prov] = metrics["provider_usage"].get(prov, 0) + 1

        # Populate audio_plan on each scene so the timeline builder
        # can pick up the narration audio path from beat-based scenes.
        for s in results:
            for sid, n_text, a_path in scene_narrations:
                if s.scene_id == sid:
                    s.audio_plan = AudioPlan(narration_audio_path=a_path)
                    break

        builder = TimelineBuilder()
        builder.build_and_write(results)

        renderer = MoviePyRenderer()
        subtitle_engine = SubtitleEngine()
        subtitle_timeline = []

        for sid, n_text, a_path in scene_narrations:
            if os.path.exists(a_path):
                wt = subtitle_engine.generate(a_path, n_text, resolution=(1920, 1080))
                subtitle_timeline.extend(subtitle_engine.to_renderer_clips(wt))

        renderer.render("timeline.json", output_path, subtitles=subtitle_timeline or None)

        if os.path.exists(output_path):
            metrics["final_video_duration"] = get_media_duration(output_path)
            metrics["render_duration"] = time.time() - t0

    except Exception as e:
        metrics["exceptions"].append(str(e))
        traceback.print_exc()
        metrics["render_duration"] = time.time() - t0

    return metrics


def main():
    all_metrics = []
    for topic in TOPICS:
        print(f"\n{'='*60}")
        print(f"  VALIDATION: {topic}")
        print(f"{'='*60}")
        m = run_topic(topic)

        stats = beat_director = None
        # Re-read fallback counts
        shots = m["total_shots"]
        primary = m["primary_success"]
        fallbacks = m["fallbacks"]
        fallback_pct = fallbacks / max(shots, 1) * 100
        primary_pct = primary / max(shots, 1) * 100

        print(f"\n  RESULTS:")
        print(f"    Shots:              {shots}")
        print(f"    Primary success:    {primary} ({primary_pct:.1f}%)")
        print(f"    Fallbacks:          {fallbacks} ({fallback_pct:.1f}%)")
        print(f"    Provider usage:     {m['provider_usage']}")
        print(f"    Final video:        {m['final_video_duration']:.1f}s")
        print(f"    Render duration:    {m['render_duration']:.1f}s")
        print(f"    Exceptions:         {len(m['exceptions'])}")
        for exc in m["exceptions"]:
            print(f"      ! {exc[:120]}")

        all_metrics.append(m)

    # Save
    report_path = OUTPUT_DIR / "validation_metrics.json"
    with open(report_path, "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)
    print(f"\n{'='*60}")
    print(f"  VALIDATION COMPLETE")
    print(f"  Report: {report_path}")
    print(f"{'='*60}\n")

    # Summary table
    print(f"{'Topic':40s} {'Shots':>6} {'Prim%':>6} {'Fall%':>6} {'Video(s)':>9}")
    print("-" * 75)
    for m in all_metrics:
        s = m["total_shots"]
        pp = m["primary_success"] / max(s, 1) * 100
        fp = m["fallbacks"] / max(s, 1) * 100
        vd = m["final_video_duration"]
        print(f"{m['topic']:40s} {s:>6} {pp:>5.1f}% {fp:>5.1f}% {vd:>8.1f}s")

if __name__ == "__main__":
    main()
