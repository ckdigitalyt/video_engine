#!/usr/bin/env python3
"""
Render V5 — Algorithm improvements from V4 review:
1. Fix shot durations (target 4.5-6.0s, merge short shots)
2. Duplicate detection via perceptual hashing
3. Better transition mixing (mood-based, not 100% CUT_SYNC)
4. Narrative arc tracking for motion progression
"""
import sys, os, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_DIR = "results/v5_early_universe"
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
print("RENDER V5 — V4 review fixes applied")
print("Target shot: 4.5-6.0s | Duplicate detection ON")
print("Mood-based transitions | Narrative arc ON")
print("=" * 60)

topic = "What Happened in the First Second of the Universe?"
lib = VisualKnowledgeLibrary()
lib.load_all()
ep = EditorialPlanner(knowledge_library=lib)

scenes_data = [
    {"title": "The Beginning",
     "narration": "In the first trillionth of a second after the Big Bang, the universe was a searing plasma of fundamental particles. Temperatures reached a hundred billion degrees. Space itself was expanding faster than light.",
     "duration": 14.0,
     "queries": ["big bang early universe plasma", "cosmic inflation expansion", "primordial universe particles", "big bang explosion space"]},
    {"title": "The Four Forces",
     "narration": "At first, all four fundamental forces were unified into a single superforce. As the universe cooled, gravity separated first, then the strong nuclear force. The electromagnetic and weak forces followed shortly after.",
     "duration": 15.0,
     "queries": ["fundamental forces physics", "unified field theory particles", "standard model particle physics", "subatomic particles collision"]},
    {"title": "Matter Wins",
     "narration": "For every billion particles of matter, there were a billion and one of antimatter. When they annihilated, that tiny surplus of ordinary matter remained. This is why the universe exists at all.",
     "duration": 14.0,
     "queries": ["matter antimatter annihilation physics", "particle physics collision", "quarks gluons plasma", "matter antimatter asymmetry"]},
    {"title": "The First Nuclei",
     "narration": "After three minutes, the universe had cooled enough for protons and neutrons to fuse into the first atomic nuclei. Most were hydrogen and helium. This primordial soup would later form the first stars.",
     "duration": 14.0,
     "queries": ["big bang nucleosynthesis hydrogen helium", "first atomic nuclei formation", "primordial elements universe", "proton neutron fusion"]},
    {"title": "The Cosmic Dawn",
     "narration": "For three hundred thousand years, the universe was an opaque fog of plasma. Then, as it finally cooled, electrons bonded with nuclei. Light could travel freely for the first time. The cosmic microwave background was born.",
     "duration": 15.0,
     "queries": ["cosmic microwave background radiation", "recombination era universe", "first light universe CMB", "WMAP cosmic background radiation"]},
]

print("\n[EditorialPlanner] Planning scenes...")
editorial_plans = ep.plan_all(scenes_with_narration=[
    {"scene_id": i, "title": s["title"], "narration": s["narration"]}
    for i, s in enumerate(scenes_data)
], topic=topic)

scenes = []
for i, sd in enumerate(scenes_data):
    role = ("hook" if i == 0 else "climax" if i == 2 else "conclusion" if i == len(scenes_data) - 1 else "exploration")
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
print("\n[Director] Processing scenes (V5: merge_shorts + dup_detect + narrative_arc)...")
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
min_shot = min(shot_durations) if shot_durations else 0
max_shot = max(shot_durations) if shot_durations else 0
print(f"\n  Shots: {total_shots} | Avg: {avg_shot:.1f}s | Min: {min_shot:.1f}s | Max: {max_shot:.1f}s")
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
output_path = f"{OUT_DIR}/early_universe_v5.mp4"
os.makedirs(OUT_DIR, exist_ok=True)
print(f"\n[Render] Starting (V5: merge_shorts + dup_detect + better_transitions)...")
t2 = time.time()
MoviePyRenderer().render("timeline.json", output_path)
t3 = time.time()

fs = os.path.getsize(output_path) if os.path.exists(output_path) else 0
print(f"\n{'=' * 60}")
print(f"RENDER V5 COMPLETE")
print(f"  Director: {t1-t0:.1f}s | Render: {t3-t2:.1f}s | Total: {t3-t0:.1f}s")
print(f"  Output: {output_path} ({fs/1024/1024:.1f} MB)")
print(f"  Real assets: {total_shots - fallback_count}/{total_shots}")
print(f"  Providers: {provider_stats}")
print(f"  Avg shot: {avg_shot:.1f}s | Min: {min_shot:.1f}s | Max: {max_shot:.1f}s")
print(f"  Transitions: {transitions_used} | Motions: {motions_used}")
print(f"  Fallbacks: {fallback_count}")
print(f"{'=' * 60}")
