#!/usr/bin/env python3
"""
Olbers Render V3 — All fixes applied:
1. Motion disabled in config (render.yaml)
2. Crossfade → cut default (0.3s short transitions instead of 0.5s crossfade)
3. BeatPlanner defaults: motion=NONE, transition=CUT
4. Camera/emotion mappers return STATIC
5. FallbackDirector: no Ken Burns on image animations
6. Min shot duration enforced by BeatPlanner
"""
import sys, os, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Clear caches
for d in ['cache/video', 'cache/audio', 'output', 'results/olbers_v3']:
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
print("OLBERS V3 — All flicker fixes applied")
print("Motion=OFF | Transitions=CUT | Min shot=3.0s")
print("Target: ~60 seconds")
print("=" * 60)

topic = "Why is the Sky Dark at Night?"
lib = VisualKnowledgeLibrary()
lib.load_all()
ep = EditorialPlanner(knowledge_library=lib)

scenes_data = [
    {"title": "A Simple Question",
     "narration": "If the universe is infinite and filled with stars, why is the night sky dark? This question haunted astronomers for centuries. Known as Olbers' Paradox.",
     "duration": 12.0,
     "queries": ["night sky stars Milky Way", "observatory telescope stars", "deep space starfield dark", "universe star field"]},
    {"title": "The Static Universe",
     "narration": "In an infinite static universe, every line of sight would end at a star. The sky should blaze as bright as the sun. Yet it doesn't. Why?",
     "duration": 13.0,
     "queries": ["star-filled sky dark contrast", "universe full of stars", "deep space galaxy field", "star cluster dense"]},
    {"title": "Expanding Universe",
     "narration": "The universe is expanding. Light from distant stars is redshifted — stretched to invisibility. Beyond a certain distance, starlight shifts out of the visible spectrum.",
     "duration": 14.0,
     "queries": ["expanding universe galaxies", "redshift light spectrum", "galaxy moving away", "universe expansion animation"]},
    {"title": "Finite Age",
     "narration": "The universe has a finite age. Only light that has had time to reach us is visible. Beyond the cosmic horizon, stars exist — but their light hasn't arrived yet.",
     "duration": 14.0,
     "queries": ["cosmic horizon deep field", "Hubble ultra deep field", "observable universe sphere", "distant galaxy cluster"]},
    {"title": "The Cosmic Darkness",
     "narration": "The darkness of the night sky is not empty. It contains the stretched echo of the Big Bang. The night is dark because the universe is finite, expanding, and young.",
     "duration": 12.0,
     "queries": ["cosmic microwave background", "big bang afterglow", "WMAP CMB map", "universe beginning"]},
]

print("\n[EditorialPlanner] Planning scenes...")
editorial_plans = ep.plan_all(scenes_with_narration=[
    {"scene_id": i, "title": s["title"], "narration": s["narration"]}
    for i, s in enumerate(scenes_data)
], topic=topic)

scenes = []
for i, sd in enumerate(scenes_data):
    scene = Scene(
        scene_id=i, title=sd["title"], expected_duration=sd["duration"], topic=topic,
        narration=SceneNarration(spoken_narration=sd["narration"]),
        visual_plan=VisualPlan(visual_description=editorial_plans[i].editorial_objective.visual_goal),
        search_plan=SearchPlan(asset_search_queries=sd["queries"]),
        editing_plan=EditingPlan(editing_instructions="static cuts documentary style"),
        metadata={"title": sd["title"]},
    )
    scenes.append(scene)

llm = ProviderFactory().get_llm_provider_for_role("planner")
t0 = time.time()
director = VisualDirector(use_beats=True, topic=topic, llm_provider=llm, scene_data=scenes)
print("\n[Director] Processing scenes...")
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
print(f"\n  Shots: {total_shots} | Avg duration: {avg_shot:.1f}s | Min: {min(shot_durations):.1f}s")
print(f"  Transitions: {transitions_used}")
print(f"  Motions: {motions_used}")

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
output_path = "results/olbers_v3/olbers_paradox_v3.mp4"
os.makedirs("results/olbers_v3", exist_ok=True)
print(f"\n[Render] Starting (motion=OFF, transitions=CUT)...")
t2 = time.time()
MoviePyRenderer().render("timeline.json", output_path)
t3 = time.time()

fs = os.path.getsize(output_path) if os.path.exists(output_path) else 0
print(f"\n{'=' * 60}")
print(f"RENDER COMPLETE")
print(f"  Director: {t1-t0:.1f}s | Render: {t3-t2:.1f}s | Total: {t3-t0:.1f}s")
print(f"  Output: {output_path} ({fs/1024/1024:.1f} MB)")
print(f"  Real assets: {total_shots - fallback_count}/{total_shots}")
print(f"  Providers: {provider_stats}")
print(f"  Avg shot: {avg_shot:.1f}s | Transitions: {transitions_used} | Motions: {motions_used}")
print(f"{'=' * 60}")
