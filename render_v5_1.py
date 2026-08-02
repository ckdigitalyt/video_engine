#!/usr/bin/env python3
"""
Render V5.1 — Fixed semantic validator fallback + lower threshold
Topic: The Great Silence — Why Haven't We Found Aliens Yet?
"""
import sys, os, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_DIR = "results/v5_fermi"
for d in ['cache/video', 'cache/audio', OUT_DIR]:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), d)
    if os.path.exists(p):
        shutil.rmtree(p)
    os.makedirs(p, exist_ok=True)

from src.models.schemas import Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan, AudioPlan, MusicStyle
from src.director import VisualDirector
from src.renderer.moviepy_renderer import MoviePyRenderer
from src.renderer.timeline_builder import TimelineBuilder
from src.cinematic.pace_profiler import analyze_vo_narration
from audio_engine import generate_voice
from src.providers.factory import ProviderFactory
from src.knowledge.visual_knowledge_library import VisualKnowledgeLibrary
from src.planner.editorial_planner import EditorialPlanner

print("=" * 60)
print("RENDER V5.1 — SemanticValidator fix + lower threshold")
print("Topic: The Great Silence — Fermi Paradox")
print("=" * 60)

topic = "Why Haven't We Found Aliens Despite the Vast Universe?"
lib = VisualKnowledgeLibrary()
lib.load_all()
ep = EditorialPlanner(knowledge_library=lib)

scenes_data = [
    {"title": "The Fermi Question",
     "narration": "Enrico Fermi asked a simple question that still haunts science. If the universe is teeming with life, where is everybody? The contradiction between high probability and zero contact is called the Fermi Paradox.",
     "duration": 14.0,
     "queries": ["Fermi paradox alien civilization", "Milky Way galaxy star field", "exoplanet habitable zone", "arecibo message radio telescope"]},
    {"title": "The Great Filter",
     "narration": "One theory suggests a Great Filter prevents civilizations from reaching the stars. It could be behind us — meaning we are the rare exception. Or ahead of us — meaning our extinction is inevitable.",
     "duration": 15.0,
     "queries": ["great filter extinction event", "asteroid impact extinction", "supernova cosmic radiation", "dyson sphere megastructure"]},
    {"title": "The Zoo Hypothesis",
     "narration": "Perhaps advanced civilizations know we exist but choose not to interfere. Earth might be a cosmic preserve, a protected zoo where primitive species evolve without outside contact.",
     "duration": 13.0,
     "queries": ["alien zoo hypothesis containment", "earth from space cosmic", "primitive civilization observation", "protected planet preserve"]},
    {"title": "The Dark Forest",
     "narration": "A darker theory suggests the universe is a forest full of hidden hunters. Any civilization that reveals its location is swiftly destroyed. Silence is survival. This is the Dark Forest hypothesis.",
     "duration": 14.0,
     "queries": ["dark forest theory hostile universe", "alien predator deep space", "supernova explosion destruction", "cosmic silence dark space"]},
    {"title": "The Lonely Cosmos",
     "narration": "Maybe we are alone. The conditions for life may be impossibly rare. A stable star, a planet with liquid water, plate tectonics, a magnetic field, a large moon, and just the right distance from the sun. Perhaps Earth truly is unique.",
     "duration": 16.0,
     "queries": ["rare earth hypothesis unique planet", "earth from space blue marble", "pale blue dot solar system", "goldilocks zone habitable planet"]},
]

print("\n[EditorialPlanner] Planning scenes...")
editorial_plans = ep.plan_all(scenes_with_narration=[
    {"scene_id": i, "title": s["title"], "narration": s["narration"]}
    for i, s in enumerate(scenes_data)
], topic=topic)

scenes = []
for i, sd in enumerate(scenes_data):
    role = ("hook" if i == 0 else "climax" if i == 3 else "conclusion" if i == len(scenes_data) - 1 else "exploration")
    profile = analyze_vo_narration(sd["narration"], narrative_role=role)
    scene = Scene(
        scene_id=i, title=sd["title"], expected_duration=sd["duration"], topic=topic,
        narration=SceneNarration(spoken_narration=sd["narration"]),
        visual_plan=VisualPlan(
            visual_description=editorial_plans[i].editorial_objective.visual_goal if i < len(editorial_plans) else f"Visuals for: {sd['title']}",
        ),
        search_plan=SearchPlan(asset_search_queries=sd["queries"]),
        editing_plan=EditingPlan(editing_instructions="cinematic documentary with varied pacing"),
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
min_shot = min(shot_durations) if shot_durations else 0
max_shot = max(shot_durations) if shot_durations else 0
print(f"\n  Shots: {total_shots} | Avg: {avg_shot:.1f}s | Min: {min_shot:.1f}s | Max: {max_shot:.1f}s")
print(f"  Transitions: {transitions_used}")
print(f"  Motions: {motions_used}")
print(f"  Providers: {provider_stats}")
print(f"  Fallbacks: {fallback_count}")

print("\n[Audio] Generating voiceovers...")
for scene in result_scenes:
    ap = os.path.join('cache/audio', f"scene_{scene.scene_id}.wav")
    generate_voice(scene.narration.spoken_narration, ap)
    scene.audio_plan = AudioPlan(
        narration_audio_path=ap, music_style=MusicStyle.CINEMATIC,
        ducking_enabled=True, ducking_reduction_db=8.0,
    )

print("\n[Timeline] Building...")
TimelineBuilder().build_and_write(result_scenes, "timeline.json")

output_path = f"{OUT_DIR}/fermi_paradox_v5.mp4"
os.makedirs(OUT_DIR, exist_ok=True)
print(f"\n[Render] Starting...")
t2 = time.time()
MoviePyRenderer().render("timeline.json", output_path)
t3 = time.time()

fs = os.path.getsize(output_path) if os.path.exists(output_path) else 0
print(f"\n{'=' * 60}")
print(f"RENDER V5.1 COMPLETE")
print(f"  Director: {t1-t0:.1f}s | Render: {t3-t2:.1f}s | Total: {t3-t0:.1f}s")
print(f"  Output: {output_path} ({fs/1024/1024:.1f} MB)")
print(f"  Real assets: {total_shots - fallback_count}/{total_shots}")
print(f"  Providers: {provider_stats}")
print(f"  Avg shot: {avg_shot:.1f}s | Min: {min_shot:.1f}s | Max: {max_shot:.1f}s")
print(f"  Transitions: {transitions_used}")
print(f"  Fallbacks: {fallback_count}")
print(f"{'=' * 60}")
