#!/usr/bin/env python3
"""
run_benchmark.py — Run benchmark documentaries and collect metrics.

Generates 3 space documentaries:
1. The Fermi Paradox
2. James Webb Space Telescope
3. Black Holes Explained

Captures per-documentary metrics and produces summary.
"""

import argparse
import json
import os
import sys
import time
import subprocess
import traceback
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


TOPICS = [
    "The Fermi Paradox",
    "James Webb Space Telescope",
    "Black Holes Explained",
]

OUTPUT_DIR = Path("results/benchmark_suite")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class BenchmarkMetrics:
    topic: str = ""
    total_scenes: int = 0
    total_beats: int = 0
    total_shots: int = 0
    primary_asset_success: int = 0
    provider_usage: dict = field(default_factory=lambda: {"pexels": 0, "pixabay": 0, "nasa": 0, "wikimedia": 0})
    provider_searches: dict = field(default_factory=lambda: {"pexels": 0, "pixabay": 0, "nasa": 0, "wikimedia": 0})
    provider_hits: dict = field(default_factory=lambda: {"pexels": 0, "pixabay": 0, "nasa": 0, "wikimedia": 0})
    semantic_pass: int = 0
    semantic_fail: int = 0
    fallback_count: int = 0
    avg_semantic_score: float = 0.0
    total_semantic_score: float = 0.0
    semantic_samples: int = 0
    render_duration: float = 0.0
    final_video_duration: float = 0.0
    exceptions: list = field(default_factory=list)
    video_path: str = ""

    @property
    def primary_success_rate(self):
        return self.primary_asset_success / max(self.total_shots, 1)

    @property
    def fallback_pct(self):
        return self.fallback_count / max(self.total_shots, 1) * 100

    @property
    def semantic_pass_rate(self):
        total = self.semantic_pass + self.semantic_fail
        return self.semantic_pass / max(total, 1)

    @property
    def provider_hit_rate(self, provider="pexels"):
        s = self.provider_searches.get(provider, 0)
        h = self.provider_hits.get(provider, 0)
        return h / max(s, 1)


def instrument_pipeline(metrics, callback=None):
    """Apply instrumentation to the pipeline to collect metrics."""
    import src.director.director as director_mod
    import src.cinematic.director_integration as di_mod
    import src.validation.semantic_validator as sv_mod

    # Track beat director stats
    _orig_process = di_mod.BeatDirector.process_scene_beats
    def _instrumented_process(self, scene):
        result = _orig_process(self, scene)
        stats = self.get_stats()
        metrics.total_beats = stats.get('shots_requested', 0)  # rough
        metrics.total_shots = stats.get('shots_requested', 0)
        metrics.primary_asset_success = stats.get('shots_accepted', 0)
        metrics.fallback_count = stats.get('fallbacks', 0)
        return result
    di_mod.BeatDirector.process_scene_beats = _instrumented_process

    # Track semantic validator
    _orig_score = sv_mod.SemanticValidator.score
    def _instrumented_score(self, narration, query, asset):
        score = _orig_score(self, narration, query, asset)
        metrics.semantic_samples += 1
        metrics.total_semantic_score += score
        if score >= self._threshold:
            metrics.semantic_pass += 1
        else:
            metrics.semantic_fail += 1
        return score
    sv_mod.SemanticValidator.score = _instrumented_score

    # Restore on completion
    import atexit
    def _restore():
        di_mod.BeatDirector.process_scene_beats = _orig_process
        sv_mod.SemanticValidator.score = _orig_score
    atexit.register(_restore)
    return _restore


def run_documentary(topic, output_path):
    """Run the pipeline for one topic and collect metrics."""
    metrics = BenchmarkMetrics(topic=topic, video_path=output_path)

    from src.providers.factory import ProviderFactory
    from src.planner import ScenePlanner
    from src.director.director import VisualDirector
    from src.director.concept_planner import ConceptPlanner
    from src.assets.asset_router import AssetRouter
    from src.director.quality_gate import QualityGates
    from src.director.aesthetic_agent import AestheticAgent
    from src.director.visual_style import VisualStyle
    from src.director.fallback_director import FallbackDirector

    # Restore
    restore = instrument_pipeline(metrics)

    t0 = time.time()
    try:
        factory = ProviderFactory()
        planning_provider = factory.get_llm_provider_for_role("planner")
        planner = ScenePlanner(provider=planning_provider)
        scenes = planner.generate_plan(topic)

        director_scene_data = []
        for ps in scenes:
            search_queries = ps.search_plan.asset_search_queries
            search_query = search_queries[0] if search_queries else "general"
            director_scene_data.append({
                "scene_id": ps.scene_id,
                "narration": ps.narration.spoken_narration,
                "search_query": search_query,
                "scene_title": ps.title,
                "purpose": ps.search_plan.scene_purpose,
                "estimated_duration": ps.expected_duration,
            })

        metrics.total_scenes = len(scenes)

        director = VisualDirector(
            use_beats=True,
            topic=topic,
            llm_provider=planning_provider,
            scene_data=director_scene_data,
        )
        results = director.run()

        # Run through orchestrator execution + render
        from src.renderer import Renderer
        from src.renderer.moviepy_renderer import MoviePyRenderer
        from src.renderer.timeline_builder import TimelineBuilder
        from src.utils.config import get_config
        from src.utils.duration import get_media_duration
        from audio_engine import generate_voice
        from src.models import Scene as PydanticScene, SceneAsset
        from src.models.schemas import AssetPlan, AudioPlan, ProviderType
        from src.subtitles.engine import SubtitleEngine
        import shutil

        movie_renderer = MoviePyRenderer()

        cache_video = get_config("pipeline.cache.video", "cache/video")
        cache_audio = get_config("pipeline.cache.audio", "cache/audio")

        # Generate voice and build assets
        scene_assets = []
        scene_narrations = []
        for s in results:
            scene_id = s.scene_id
            narration = s.narration.spoken_narration
            audio_path = os.path.join(cache_audio, f"scene_{scene_id}.wav")
            if s.asset_plan and s.asset_plan.filepath:
                video_path = s.asset_plan.filepath
            else:
                video_path = os.path.join(cache_video, f"scene_{scene_id}.mp4")
            generate_voice(narration, audio_path)
            scene_assets.append(SceneAsset(scene_id=scene_id, video_path=video_path, audio_path=audio_path))
            scene_narrations.append((scene_id, narration, audio_path))

            if s.asset_plan:
                metrics.provider_usage[s.asset_plan.provider.value] += 1

        # Build and render timeline
        builder = TimelineBuilder()
        timeline_json = builder.build_and_write(results)

        output_path_full = str(Path(output_path).with_suffix(".mp4"))
        subtitle_engine = SubtitleEngine()
        subtitle_timeline = []

        for sid, narration_text, audio_path in scene_narrations:
            if os.path.exists(audio_path):
                word_timing = subtitle_engine.generate(
                    audio_path, narration_text, resolution=(1920, 1080),
                )
                subtitle_timeline.extend(subtitle_engine.to_renderer_clips(word_timing))

        movie_renderer.render(
            "timeline.json",
            output_path_full,
            subtitles=subtitle_timeline if subtitle_timeline else None,
        )

        # Get final duration
        if os.path.exists(output_path_full):
            metrics.final_video_duration = get_media_duration(output_path_full)

    except Exception as e:
        metrics.exceptions.append(str(e))
        traceback.print_exc()

    finally:
        restore()

    metrics.render_duration = time.time() - t0
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", nargs="*", default=[], help="Topics to skip")
    args = parser.parse_args()

    all_metrics = []
    results = {}

    for topic in TOPICS:
        if topic in args.skip:
            print(f"\n=== Skipping: {topic} ===")
            continue

        safe_name = topic.lower().replace(" ", "_").replace("'", "")
        output_path = str(OUTPUT_DIR / safe_name)

        print(f"\n{'='*60}")
        print(f"  BENCHMARK: {topic}")
        print(f"{'='*60}\n")

        metrics = run_documentary(topic, output_path)

        print(f"\n  {'─'*40}")
        print(f"  RESULTS: {topic}")
        print(f"{'─'*40}")
        print(f"    Scenes:             {metrics.total_scenes}")
        print(f"    Shots:              {metrics.total_shots}")
        print(f"    Primary success:    {metrics.primary_asset_success}")
        print(f"    Fallbacks:          {metrics.fallback_count} ({metrics.fallback_pct:.1f}%)")
        print(f"    Semantic pass rate: {metrics.semantic_pass_rate:.1%}")
        print(f"    Avg semantic score: {metrics.total_semantic_score/max(metrics.semantic_samples,1):.3f}")
        print(f"    Render duration:    {metrics.render_duration:.1f}s")
        print(f"    Final video:        {metrics.final_video_duration:.1f}s")
        print(f"    Exceptions:         {len(metrics.exceptions)}")

        all_metrics.append(metrics)
        results[topic] = asdict(metrics)

        # Save per-topic report
        topic_report = OUTPUT_DIR / f"{safe_name}_report.json"
        with open(topic_report, "w") as f:
            json.dump(asdict(metrics), f, indent=2, default=str)

    # Save all metrics
    metrics_path = OUTPUT_DIR / "metrics.json"
    with open(metrics_path, "w") as f:
        # Convert to serializable
        serializable = {}
        for topic, m in results.items():
            m["provider_usage"] = dict(m["provider_usage"])
            m["provider_searches"] = dict(m["provider_searches"])
            m["provider_hits"] = dict(m["provider_hits"])
            serializable[topic] = m
        json.dump(serializable, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"  BENCHMARK SUITE COMPLETE")
    print(f"  Metrics: {metrics_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
