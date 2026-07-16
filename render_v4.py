#!/usr/bin/env python3
"""
Render V4 — DeepSeek review algorithm improvements integrated:
1. Motion Grammar — archetypal sequences, direction validation
2. Parallel provider chain with diversity pooling (max 50% per provider)
3. Adaptive shot duration via PaceProfiler (3.5-6.0s breath-matched)
4. Transition Triggers — 80% CUT_SYNC on word boundaries
5. Pre-rendered Transition Cache
"""
import sys, os, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_DIR = "results/v4_black_hole"
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
print("RENDER V4 — Algorithm improvements active")
print("Motion Grammar ON | PaceProfiler ON | DiversityPool ON")
print("TransitionCache ON | CUT_SYNC default")
print("=" * 60)

topic = "What Happens Inside a Black Hole?"
lib = VisualKnowledgeLibrary()
lib.load_all()
ep = EditorialPlanner(knowledge_library=lib)

scenes_data = [
    {"title": "The Point of No Return",
     "narration": "A black hole is a region of spacetime where gravity is so strong that nothing, not even light, can escape. The boundary around it is called the event horizon. Cross this threshold, and there is no turning back.",
     "duration": 14.0,
     "queries": ["black hole event horizon space", "supermassive black hole galaxy", "black hole gravity warping spacetime", "accretion disk black hole"]},
    {"title": "Spaghettification",
     "narration": "As you approach a black hole, the difference in gravity between your head and your feet becomes extreme. You would be stretched into a thin strand of particles. This process is called spaghettification.",
     "duration": 13.0,
     "queries": ["spaghettification black hole gravity", "tidal forces extreme gravity", "black hole stretching matter", "gravitational gradient space"]},
    {"title": "Time Dilation",
     "narration": "Near a black hole, time slows down dramatically. To an outside observer, you would appear to freeze at the event horizon. Meanwhile, for you, time would pass normally, but the universe outside would age rapidly.",
     "duration": 14.0,
     "queries": ["time dilation black hole relativity", "Einstein relativity space-time", "gravitational time warp", "black hole time slowing"]},
    {"title": "The Singularity",
     "narration": "At the center lies the singularity — a point of infinite density where the laws of physics break down. Space and time as we know them cease to exist. What happens there is unknown.",
     "duration": 13.0,
     "queries": ["black hole singularity core", "infinite density spacetime", "quantum gravity theory", "center of black hole"]},
    {"title": "Hawking Radiation",
     "narration": "Stephen Hawking discovered that black holes are not completely black. Quantum effects near the event horizon cause them to emit radiation and slowly evaporate. Over trillions of years, even the largest black holes will fade away.",
     "duration": 14.0,
     "queries": ["Hawking radiation black hole", "quantum vacuum particles", "black hole evaporation", "Stephen Hawking quantum theory"]},
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
        visual_plan=VisualPlan(
            visual_description=editorial_plans[i].editorial_objective.visual_goal if i < len(editorial_plans) else f"Visuals for: {sd['title']}",
        ),
        search_plan=SearchPlan(asset_search_queries=sd["queries"]),
        editing_plan=EditingPlan(editing_instructions="cinematic documentary with varied pacing"),
        metadata={"title": sd["title"]},
    )
    scenes.append(scene)

# Pace profiler
print("\n[PaceProfiler] Analyzing narration pacing...")
for i, sd in enumerate(scenes_data):
    role = ("hook" if i == 0 else "climax" if i == len(scenes_data) // 2 else "conclusion" if i == len(scenes_data) - 1 else "exploration")
    profile = analyze_vo_narration(sd["narration"], narrative_role=role)
    print(f"  Scene {i} ({sd['title']}): {profile.sentence_count} sentences, "
          f"avg_dur={profile.avg_sentence_duration:.1f}s, "
          f"energy={profile.energy_level:.1f}, "
          f"shots: {profile.recommended_min:.1f}-{profile.recommended_max:.1f}s, "
          f"avg={profile.recommended_avg:.1f}s")
    scenes[i].expected_duration = max(scenes[i].expected_duration, profile.recommended_avg * (profile.sentence_count or 1))

llm = ProviderFactory().get_llm_provider_for_role("planner")
t0 = time.time()
director = VisualDirector(use_beats=True, topic=topic, llm_provider=llm, scene_data=scenes)
print("\n[Director] Processing scenes with Motion Grammar...")
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
print(f"  Providers: {provider_stats}")
print(f"  Fallbacks: {fallback_count}")

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
output_path = f"{OUT_DIR}/black_hole_v4.mp4"
os.makedirs(OUT_DIR, exist_ok=True)
print(f"\n[Render] Starting (v4 algorithm: motion_grammar + pace_profiler + cut_sync)...")
t2 = time.time()
MoviePyRenderer().render("timeline.json", output_path)
t3 = time.time()

fs = os.path.getsize(output_path) if os.path.exists(output_path) else 0
print(f"\n{'=' * 60}")
print(f"RENDER V4 COMPLETE")
print(f"  Director: {t1-t0:.1f}s | Render: {t3-t2:.1f}s | Total: {t3-t0:.1f}s")
print(f"  Output: {output_path} ({fs/1024/1024:.1f} MB)")
print(f"  Real assets: {total_shots - fallback_count}/{total_shots}")
print(f"  Providers: {provider_stats}")
print(f"  Avg shot: {avg_shot:.1f}s | Transitions: {transitions_used} | Motions: {motions_used}")
print(f"  Fallbacks: {fallback_count}")
print(f"{'=' * 60}")
