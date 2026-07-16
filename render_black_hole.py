#!/usr/bin/env python3
"""
Black Hole Documentary — v3 pipeline, editorial intelligence, Gemini-powered.
"""
import sys, os, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Clear caches for clean run
for d in ['cache/video', 'cache/audio', 'output', 'results/black_hole']:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), d)
    if os.path.exists(p):
        shutil.rmtree(p)
    os.makedirs(p, exist_ok=True)

from src.models.schemas import Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan, AudioPlan, MusicStyle
from src.director import VisualDirector
from src.renderer.moviepy_renderer import MoviePyRenderer
from src.renderer.timeline_builder import TimelineBuilder
from audio_engine import generate_voice
from src.providers.factory import ProviderFactory
from src.knowledge.visual_knowledge_library import VisualKnowledgeLibrary
from src.planner.editorial_planner import EditorialPlanner

print("=" * 60)
print("BLACK HOLE DOCUMENTARY")
print("Pipeline: EditorialPlanner → VisualDirector → TimelineBuilder → Render")
print(f"LLM: Gemini (primary), DeepSeek (fallback)")
print(f"Motion=OFF | Transitions=CUT | Beat mode ON")
print("=" * 60)

topic = "Black Holes"
lib = VisualKnowledgeLibrary()
lib.load_all()
# Use DeepSeek for editorial planning since Gemini free tier is quota-exhausted
from src.providers.factory import ProviderFactory
ep = EditorialPlanner(
    knowledge_library=lib,
    provider=ProviderFactory().get_llm_provider("deepseek"),
)

scenes_data = [
    {
        "title": "The Invisible Monster",
        "narration": "What is a black hole? A region of spacetime where gravity is so intense that nothing — not even light — can escape. They are invisible by definition, yet we know they exist. How?",
        "duration": 14.0,
    },
    {
        "title": "Birth From Collapse",
        "narration": "When a massive star exhausts its nuclear fuel, its core collapses under its own gravity. If the core exceeds about three solar masses, nothing can stop the collapse. A black hole is born.",
        "duration": 16.0,
    },
    {
        "title": "The Event Horizon",
        "narration": "The event horizon is the point of no return. Cross it, and all paths lead to the center. Time itself appears to freeze at the horizon from the outside. Inside, spacetime breaks down entirely at the singularity.",
        "duration": 16.0,
    },
    {
        "title": "Supermassive Giants",
        "narration": "Supermassive black holes, millions to billions of times the mass of our Sun, sit at the centers of most galaxies. Our own Milky Way harbors Sagittarius A* — four million solar masses in a single point.",
        "duration": 14.0,
    },
    {
        "title": "Seeing the Unseen",
        "narration": "In 2019, the Event Horizon Telescope captured the first image of a black hole — M87's shadow against its glowing accretion disk. We finally saw the invisible. A ring of fire around darkness itself.",
        "duration": 15.0,
    },
]

print("\n[EditorialPlanner] Planning scenes with Knowledge Library...")
editorial_plans = ep.plan_all(scenes_with_narration=[
    {"scene_id": i, "title": s["title"], "narration": s["narration"]}
    for i, s in enumerate(scenes_data)
], topic=topic)

entry = lib.lookup(topic)
scenes = []
for i, sd in enumerate(scenes_data):
    ep_plan = editorial_plans[i]
    # Build per-scene queries from Knowledge Library — rotate through
    # stock, NASA, and Wikimedia searches so each scene gets unique terms.
    queries = []
    if entry:
        stock = list(entry.preferred_stock_footage_searches or [])
        nasa = list(entry.preferred_nasa_searches or [])
        wikimedia = list(entry.preferred_wikimedia_searches or [])
        motifs = list(entry.preferred_visual_motifs or [])
        # Build a diverse set for this scene by rotating through sources
        queries.extend(stock[i*2:(i+1)*2] if len(stock) > i*2 else stock[:2])
        queries.extend(nasa[i:i+1] if len(nasa) > i else nasa[:1])
        queries.extend(wikimedia[i:i+1] if len(wikimedia) > i else wikimedia[:1])
        queries.extend(motifs[i:i+1] if len(motifs) > i else motifs[:1])
    queries = [q for q in queries if q][:6]
    if not queries:
        queries = ["black hole documentary space"]

    scene = Scene(
        scene_id=i, title=sd["title"], expected_duration=sd["duration"], topic=topic,
        narration=SceneNarration(spoken_narration=sd["narration"]),
        visual_plan=VisualPlan(
            visual_description=ep_plan.editorial_objective.visual_goal,
        ),
        search_plan=SearchPlan(asset_search_queries=queries),
        editing_plan=EditingPlan(editing_instructions="documentary static cuts"),
        metadata={"title": sd["title"]},
    )
    scenes.append(scene)

llm = ProviderFactory().get_llm_provider_for_role("planner")
t0 = time.time()

director = VisualDirector(use_beats=True, topic=topic, llm_provider=llm, scene_data=scenes)
print("\n[Director] Processing scenes with beat-based editing...")
sys.stdout.flush()
result_scenes = director.run()
t1 = time.time()

# Stats
provider_stats = {}
fallback_count = 0
total_shots = 0
shot_durations = []
transitions_used = {}
motions_used = {}
for scene in result_scenes:
    for beat in (scene.beat_plans or []):
        for shot in beat.shots:
            total_shots += 1
            shot_durations.append(shot.duration)
            t = shot.transition.value
            transitions_used[t] = transitions_used.get(t, 0) + 1
            m = shot.motion
            motions_used[m] = motions_used.get(m, 0) + 1
            if shot.asset_plan:
                p = shot.asset_plan.provider.value
                provider_stats[p] = provider_stats.get(p, 0) + 1
                if p in ('placeholder', 'emergency'):
                    fallback_count += 1

avg_shot = sum(shot_durations)/len(shot_durations) if shot_durations else 0
print(f"\n  Shots: {total_shots} | Avg duration: {avg_shot:.1f}s")
if shot_durations:
    print(f"  Min: {min(shot_durations):.1f}s | Max: {max(shot_durations):.1f}s")
print(f"  Transitions: {transitions_used}")
print(f"  Motions: {motions_used}")
print(f"  Providers: {provider_stats}")

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
output_path = "results/black_hole/black_hole_documentary.mp4"
os.makedirs("results/black_hole", exist_ok=True)
print(f"\n[Render] Starting (motion=OFF, transitions=CUT)...")
t2 = time.time()
MoviePyRenderer().render("timeline.json", output_path)
t3 = time.time()

fs = os.path.getsize(output_path) if os.path.exists(output_path) else 0
total_real = total_shots - fallback_count
print(f"\n{'=' * 60}")
print(f"RENDER COMPLETE")
print(f"  Director: {t1-t0:.1f}s | Render: {t3-t2:.1f}s | Total: {t3-t0:.1f}s")
print(f"  Output: {output_path} ({fs/1024/1024:.1f} MB)")
print(f"  Real assets: {total_real}/{total_shots}")
print(f"  Providers: {provider_stats}")
print(f"  Avg shot: {avg_shot:.1f}s | Transitions: {transitions_used}")
print(f"{'=' * 60}")
