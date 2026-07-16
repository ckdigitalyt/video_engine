#!/usr/bin/env python3
"""
Olbers Render — 1-minute documentary on Olbers' Paradox.
Uses the editorial intelligence pipeline for planning but provides
manually-tuned search queries to avoid Pydantic validation errors.
"""
import sys, os, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for d in ['cache/video', 'cache/audio', 'output', 'results/olbers_demo']:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), d)
    if os.path.exists(p):
        shutil.rmtree(p)
    os.makedirs(p, exist_ok=True)

from src.models.schemas import (
    MusicStyle,
    Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan, AudioPlan,
)
from src.director import VisualDirector
from src.renderer.moviepy_renderer import MoviePyRenderer
from src.renderer.timeline_builder import TimelineBuilder
from audio_engine import generate_voice
from src.providers.factory import ProviderFactory

from src.knowledge.visual_knowledge_library import VisualKnowledgeLibrary
from src.planner.editorial_planner import EditorialPlanner
from src.assets.visual_intent import VisualIntent, AssetType

print("=" * 60)
print("OLBERS' PARADOX — Editorial Intelligence Pipeline Demo")
print("Target: ~60 seconds")
print("=" * 60)

topic = "Why is the Sky Dark at Night?"

# Phase 0: Knowledge Library
print("\n[Phase 0] Loading Visual Knowledge Library...")
lib = VisualKnowledgeLibrary()
n = lib.load_all()
print(f"  Loaded {n} entries")

# Phase 1: EditorialPlanner
print("\n[Phase 1] Editorial Planning...")
ep = EditorialPlanner(knowledge_library=lib)

scenes_data = [
    {"title": "A Simple Question",
     "narration": "If the universe is infinite and filled with stars, why is the night sky dark? This question haunted astronomers for centuries. Known as Olbers' Paradox.",
     "duration": 12.0,
     "queries": ["night sky stars Milky Way", "observatory telescope stars", "deep space starfield dark", "universe star field"]},
    {"title": "The Static Universe",
     "narration": "In an infinite static universe, every line of sight would end at a star. The sky should blaze as bright as the sun. Yet it doesn't. Why?",
     "duration": 13.0,
     "queries": ["star-filled sky dark contrast", "universe full of stars", "deep space galaxy field", "star cluster dense", "universe infinite stars animation"]},
    {"title": "Expanding Universe",
     "narration": "The universe is expanding. Light from distant stars is redshifted — stretched to invisibility. Beyond a certain distance, starlight shifts out of the visible spectrum.",
     "duration": 14.0,
     "queries": ["expanding universe galaxies", "redshift light spectrum", "galaxy moving away", "universe expansion animation", "redshift galaxy light", "wavelength stretching diagram"]},
    {"title": "Finite Age",
     "narration": "The universe has a finite age. Only light that has had time to reach us is visible. Beyond the cosmic horizon, stars exist — but their light hasn't arrived yet.",
     "duration": 14.0,
     "queries": ["cosmic horizon deep field", "Hubble ultra deep field", "observable universe sphere", "light travel time animation", "distant galaxy cluster", "big bang light cone"]},
    {"title": "The Cosmic Darkness",
     "narration": "The darkness of the night sky is not empty. It contains the stretched echo of the Big Bang. The night is dark because the universe is finite, expanding, and young.",
     "duration": 12.0,
     "queries": ["cosmic microwave background", "big bang afterglow", "WMAP CMB map", "universe beginning", "cosmic web structure", "primordial universe"]},
]

# Phase 1+2: Editorial planning (for editorial objectives, not queries)
print("\n[EditorialPlanner] Planning scenes...")
editorial_plans = ep.plan_all(scenes_with_narration=[
    {"scene_id": i, "title": s["title"], "narration": s["narration"]}
    for i, s in enumerate(scenes_data)
], topic=topic)

for plan in editorial_plans:
    print(f"  Scene {plan.scene_id}: {plan.title} → {plan.editorial_objective.knowledge_entry_used} (confidence={plan.confidence:.2f})")

# Build scenes with short search queries
scenes = []
for i, sd in enumerate(scenes_data):
    scene = Scene(
        scene_id=i,
        title=sd["title"],
        expected_duration=sd["duration"],
        topic=topic,
        narration=SceneNarration(spoken_narration=sd["narration"]),
        visual_plan=VisualPlan(
            visual_description=editorial_plans[i].editorial_objective.visual_goal,
        ),
        search_plan=SearchPlan(
            asset_search_queries=sd["queries"],
        ),
        editing_plan=EditingPlan(
            editing_instructions="documentary style slow revealing cinematic transitions",
        ),
        metadata={"title": sd["title"]},
    )
    scenes.append(scene)

_factory = ProviderFactory()
llm = _factory.get_llm_provider_for_role("planner")

# VisualDirector
t0 = time.time()
director = VisualDirector(use_beats=True, topic=topic, llm_provider=llm, scene_data=scenes)

print("\n[Director] Processing scenes...")
sys.stdout.flush()
result_scenes = director.run()
t1 = time.time()

# Log results
total_beats = 0
total_shots = 0
provider_stats = {}
fallback_count = 0
for scene in result_scenes:
    bp = scene.beat_plans or []
    total_beats += len(bp)
    sh = sum(len(b.shots) for b in bp)
    total_shots += sh
    print(f"\n--- Scene {scene.scene_id}: {scene.title} ---")
    for beat in bp:
        for shot in beat.shots:
            asset = shot.asset_plan
            if asset:
                p = asset.provider.value
                provider_stats[p] = provider_stats.get(p, 0) + 1
                if p in ('placeholder', 'emergency'):
                    fallback_count += 1
            print(f"  B{beat.index}S{shot.shot_type.value}: {shot.duration:.1f}s "
                  f"prov={asset.provider.value if asset else 'none'} "
                  f"sem={asset.semantic_score:.2f}" if asset else f"  B{beat.index}S{shot.shot_type.value}: no asset")

# Audio
print("\n[Audio] Generating voiceovers...")
for scene in result_scenes:
    ap = os.path.join('cache/audio', f"scene_{scene.scene_id}.wav")
    generate_voice(scene.narration.spoken_narration, ap)
    scene.audio_plan = AudioPlan(
        narration_audio_path=ap, music_style=MusicStyle.CINEMATIC,
        ducking_enabled=True, ducking_reduction_db=8.0,
    )

# Timeline
print("\n[Timeline] Building...")
TimelineBuilder().build_and_write(result_scenes, "timeline.json")

# Render
output_path = "results/olbers_demo/olbers_paradox_demo.mp4"
os.makedirs("results/olbers_demo", exist_ok=True)
print(f"\n[Render] Starting...")
t2 = time.time()
MoviePyRenderer().render("timeline.json", output_path)
t3 = time.time()

fs = os.path.getsize(output_path) if os.path.exists(output_path) else 0
print(f"\n{'=' * 60}")
print(f"RENDER COMPLETE")
print(f"  Director: {t1-t0:.1f}s | Render: {t3-t2:.1f}s | Total: {t3-t0:.1f}s")
print(f"  {len(result_scenes)} scenes, {total_beats} beats, {total_shots} shots")
print(f"  Output: {output_path} ({fs/1024/1024:.1f} MB)")
print(f"  Real assets: {total_shots - fallback_count}/{total_shots}")
print(f"  Providers: {provider_stats}")
print(f"{'=' * 60}")
