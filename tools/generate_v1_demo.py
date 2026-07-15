#!/usr/bin/env python3
"""
generate_v1_demo.py — Generate a ~1 minute documentary using v1 modules.

Runs the full pipeline (script → narration → visual intent → semantic queries →
asset retrieval → storyboard → render) with all v1 quality improvements enabled.
"""

import json, os, sys, time, traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from src.providers.factory import ProviderFactory
from src.planner import ScenePlanner
from src.director.director import VisualDirector
from src.director.concept_planner import ConceptPlanner
from src.assets.asset_router import AssetRouter
from src.renderer.timeline_builder import TimelineBuilder
from src.renderer.moviepy_renderer import MoviePyRenderer
from src.subtitles.engine import SubtitleEngine
from src.assets.asset_ranker import AssetRanker
from src.assets.visual_intent_planner import VisualIntentPlanner, VisualIntent, SceneType, VisualCategory, CameraStyle
from src.assets.broll_taxonomy import BrollTaxonomy
from src.director.visual_memory import VisualMemory
from src.gates.quality_gate import QualityGate
from src.telemetry.collector import TelemetryCollector
from src.utils.config import get_config
from audio_engine import generate_voice
from src.models import SceneAsset
from src.models.schemas import AudioPlan, AssetPlan

TOPIC = "The Fermi Paradox"
OUTPUT_DIR = Path("results/v1_demo")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

telemetry = TelemetryCollector(topic=TOPIC)

def main():
    t0 = time.time()
    factory = ProviderFactory()
    planning_provider = factory.get_llm_provider_for_role("planner")
    
    # ── Phase 1-2: Script + Visual Intent ─────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Generating ~1 min documentary on: {TOPIC}")
    print(f"{'='*60}\n")
    
    planner = ScenePlanner(provider=planning_provider)
    scenes = planner.generate_plan(TOPIC)
    
    # Take first 3 scenes for ~1 minute
    scenes = scenes[:3]
    total_duration = sum(s.expected_duration for s in scenes)
    print(f"  {len(scenes)} scenes, ~{total_duration:.0f}s target duration")
    
    # ── Phase 2: Visual Intent for each scene ──────────────────────────
    intent_planner = VisualIntentPlanner(provider=planning_provider)
    visual_intents = {}
    for s in scenes:
        intent = intent_planner.plan(
            narration=s.narration.spoken_narration,
            scene_title=s.title,
        )
        visual_intents[s.scene_id] = intent
        print(f"  Scene {s.scene_id}: {intent.visual_category.value} / {intent.camera_style.value}")
    
    # ── Phase 13: B-roll taxonomy for query templates ─────────────────
    broll = BrollTaxonomy()
    tax_templates = broll.get_templates_for_category("Space")
    if not tax_templates:
        tax_templates = broll.get_templates_for_category("General")
    print(f"  Loaded {len(tax_templates)} b-roll templates")
    
    # ── Phase 1 & 3: Prepare scene data with semantic queries ────────
    director_scene_data = []
    for s in scenes:
        intent = visual_intents.get(s.scene_id, VisualIntent())
        sq = s.search_plan.asset_search_queries
        search_query = sq[0] if sq else "general"
        
        # Use b-roll taxonomy to find better queries
        tax_matches = broll.find_matching_templates(
            [intent.scientific_topic] + intent.must_have
        )
        if tax_matches:
            search_query = tax_matches[0].queries[0]
            print(f"  B-roll match for scene {s.scene_id}: '{search_query}'")
        
        director_scene_data.append({
            "scene_id": s.scene_id,
            "narration": s.narration.spoken_narration,
            "search_query": search_query,
            "scene_title": s.title,
            "purpose": s.search_plan.scene_purpose if s.search_plan else "general",
            "estimated_duration": s.expected_duration,
        })
    
    # ── Phase 9: Visual memory for diversity ──────────────────────────
    visual_memory = VisualMemory(window_seconds=60)
    
    # ── Run Visual Director with beat mode ────────────────────────────
    print(f"\n  Starting Visual Director (beat mode)...")
    director = VisualDirector(
        use_beats=True,
        topic=TOPIC,
        llm_provider=planning_provider,
        scene_data=director_scene_data,
    )
    results = director.run()
    
    # ── Get beat director stats ───────────────────────────────────────
    beat_director = getattr(director, '_beat_director', None)
    if beat_director:
        stats = beat_director.get_stats()
        print(f"\n  Beat Director Stats:")
        print(f"    Shots requested: {stats.get('shots_requested', 0)}")
        print(f"    Shots accepted:  {stats.get('shots_accepted', 0)}")
        print(f"    Fallbacks:       {stats.get('fallbacks', 0)}")
        telemetry.record_fallback_use()
    
    # ── Phase 4: Asset scoring (integrated into BeatDirector already) ─
    ranker = AssetRanker()
    
    # ── Build timeline and render ──────────────────────────────────────
    cache_video = get_config("pipeline.cache.video", "cache/video")
    cache_audio = get_config("pipeline.cache.audio", "cache/audio")
    
    output_path = str(OUTPUT_DIR / "fermi_paradox_v1_demo.mp4")
    
    scene_narrations = []
    scene_assets_list = []
    
    for s in results:
        sid = s.scene_id
        narration = s.narration.spoken_narration
        audio_path = os.path.join(cache_audio, f"scene_{sid}.wav")
        vid_path = (s.asset_plan.filepath if s.asset_plan and s.asset_plan.filepath
                     else os.path.join(cache_video, f"scene_{sid}.mp4"))
        
        # Generate TTS
        telemetry.record_provider_call("kokoro_tts", narration[:30])
        generate_voice(narration, audio_path)
        telemetry.record_cache_hit() if os.path.exists(audio_path) else telemetry.record_cache_miss()
        
        scene_assets_list.append(SceneAsset(scene_id=sid, video_path=vid_path, audio_path=audio_path))
        scene_narrations.append((sid, narration, audio_path))
    
    # ── Populate audio_plan on scenes ─────────────────────────────────
    for s in results:
        for sid, n_text, a_path in scene_narrations:
            if s.scene_id == sid:
                s.audio_plan = AudioPlan(narration_audio_path=a_path)
                break
    
    # ── Phase 11: Build timeline ──────────────────────────────────────
    builder = TimelineBuilder()
    try:
        builder.build_and_write(results)
        print(f"\n  Timeline built successfully")
        telemetry.record_event_type = "timeline_success"
    except Exception as e:
        print(f"\n  Timeline build error: {e}")
        raise
    
    # ── Render ────────────────────────────────────────────────────────
    renderer = MoviePyRenderer()
    subtitle_engine = SubtitleEngine()
    subtitle_timeline = []
    
    for sid, n_text, a_path in scene_narrations:
        if os.path.exists(a_path):
            wt = subtitle_engine.generate(a_path, n_text, resolution=(1920, 1080))
            subtitle_timeline.extend(subtitle_engine.to_renderer_clips(wt))
    
    render_start = time.time()
    try:
        renderer.render("timeline.json", output_path, subtitles=subtitle_timeline or None)
        render_duration = time.time() - render_start
        telemetry.record_render_success()
        print(f"\n  Render complete: {output_path} ({render_duration:.0f}s)")
    except Exception as e:
        print(f"\n  Render error: {e}")
        traceback.print_exc()
    
    # ── Phase 14: Telemetry report ────────────────────────────────────
    telemetry.record_render_success()
    print(f"\n{'='*60}")
    print(f"  TELEMETRY DASHBOARD")
    print(f"{'='*60}")
    print(telemetry.dashboard_text())
    telemetry.write_report(str(OUTPUT_DIR / "telemetry.json"))
    
    total_time = time.time() - t0
    print(f"\n  Total time: {total_time:.0f}s")
    print(f"  Output: {output_path}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
