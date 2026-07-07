#!/usr/bin/env python3
"""
Fermi Paradox — Production validation render with verbose logging.
Clears caches, processes 10 scenes with beat-based editing.
"""
import sys, os, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Clear caches
for d in ['cache/video', 'cache/audio', 'output']:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), d)
    if os.path.exists(p):
        shutil.rmtree(p)
    os.makedirs(p, exist_ok=True)

from src.models.schemas import (
    MusicStyle,
    Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan, AudioPlan,
)
from src.director import VisualDirector
from src.director import VisualDirector as VD
from src.renderer.moviepy_renderer import MoviePyRenderer
from src.renderer.timeline_builder import TimelineBuilder

from src.utils.config import get_config
from audio_engine import generate_voice
from src.providers import DeepSeekProvider

topic = "The Fermi Paradox"

scenes_data = [
    {"title": "The Great Silence", "narration": "The universe is incomprehensibly vast. With hundreds of billions of stars in our galaxy alone, and trillions more beyond, the numbers suggest we should not be alone. Yet when we gaze at the stars, we hear nothing but silence.", "duration": 15.0},
    {"title": "A Simple Question", "narration": "Enrico Fermi posed a deceptively simple question. If the conditions for life are common in the universe, where is everybody? The observable universe contains more stars than grains of sand on every beach on Earth.", "duration": 14.0},
    {"title": "The Drake Equation", "narration": "Frank Drake attempted to quantify this question with his famous equation. It multiplies the rate of star formation with the fraction of stars that have planets and the likelihood of life arising.", "duration": 12.0},
    {"title": "The Great Filter", "narration": "One troubling solution is the Great Filter. Perhaps there is a step in evolution so difficult that almost no civilization passes through it. This filter could be behind us in our past. Or it could lie ahead waiting.", "duration": 14.0},
    {"title": "Rare Earth Hypothesis", "narration": "Perhaps Earth is special. Our large moon stabilizes the axial tilt. Jupiter sweeps up dangerous asteroids. Our position in the galactic habitable zone is just right for life to flourish.", "duration": 14.0},
    {"title": "Dark Forest Theory", "narration": "The Dark Forest theory offers a chilling possibility. Every civilization is a hunter in a dark forest. Revealing your position means inviting destruction. Silence is survival.", "duration": 12.0},
    {"title": "Technological Singularity", "narration": "Perhaps advanced civilizations transcend biological form entirely. They upload their consciousness into digital realms and explore inner space rather than outer space.", "duration": 12.0},
    {"title": "The Zoo Hypothesis", "narration": "What if we are being observed like animals in a zoo? Advanced civilizations might have a prime directive. They watch and study but they do not interfere. Waiting for us to reach a threshold.", "duration": 12.0},
    {"title": "Waiting for the Signal", "narration": "The universe is 13.8 billion years old. Human civilization has existed for only ten thousand years. Our technological age capable of listening for alien signals is barely a century old.", "duration": 12.0},
    {"title": "The Answer", "narration": "We may simply not have been listening long enough. The signal could arrive tomorrow. Or never. That is the nature of a question without an answer. But we keep searching anyway.", "duration": 13.0},
]

print("=" * 60)
print("FERMI PARADOX — Production Validation")
print(f"Scenes: {len(scenes_data)}")
print(f"Target: ~130 seconds")
print("=" * 60)

# ── Step 1: Create scenes ────────────────────────────────────────────
scenes = []
for i, sd in enumerate(scenes_data):
    scene = Scene(
        scene_id=i, title=sd["title"], expected_duration=sd["duration"], topic=topic,
        narration=SceneNarration(spoken_narration=sd["narration"]),
        visual_plan=VisualPlan(visual_description=f"Documentary scene: {sd['title']}"),
        search_plan=SearchPlan(asset_search_queries=[
            f"{sd['title'].lower()} documentary space cinematic",
            f"space universe cinematic stock footage"
        ]),
        editing_plan=EditingPlan(editing_instructions="cinematic documentary slow revealing shots"),
        metadata={"title": sd["title"]},
    )
    scenes.append(scene)

llm = DeepSeekProvider()

# ── Step 2: VisualDirector in beat mode ───────────────────────────────
t0 = time.time()
director = VisualDirector(
    use_beats=True,
    topic=topic, llm_provider=llm, scene_data=scenes,
)

print("\n[Director] Starting beat-based processing...")
sys.stdout.flush()
result_scenes = director.run()
t1 = time.time()

# ── Step 3: Per-scene beat logging ────────────────────────────────────
total_beats = 0
total_shots = 0
for scene in result_scenes:
    bp = scene.beat_plans or []
    n_beats = len(bp)
    n_shots = sum(len(b.shots) for b in bp)
    total_beats += n_beats
    total_shots += n_shots
    print(f"\n--- Scene {scene.scene_id}: {scene.title} ---")
    for beat in bp:
        for shot in beat.shots:
            asset = shot.asset_plan
            print(f"  B{beat.index}S{shot.shot_type.value}: dur={shot.duration:.1f}s "
                  f"cam={shot.camera.value} mot={shot.motion} trans={shot.transition.value} "
                  f"asset={'YES' if asset else 'NONE'} "
                  f"prov={asset.provider.value if asset else '?'} "
                  f"sem={asset.semantic_score:.2f}" if asset else "  no asset")

# ── Step 4: Generate audio ────────────────────────────────────────────
print("\n[Audio] Generating voiceovers...")
for scene in result_scenes:
    ap = os.path.join('cache/audio', f"scene_{scene.scene_id}.wav")
    generate_voice(scene.narration.spoken_narration, ap)
    scene.audio_plan = AudioPlan(
        narration_audio_path=ap, music_style=MusicStyle.CINEMATIC,
        ducking_enabled=True, ducking_reduction_db=8.0,
    )

# ── Step 5: Build timeline ────────────────────────────────────────────
print("\n[Timeline] Building...")
tl = TimelineBuilder()
tl.build_and_write(result_scenes, "timeline.json")

# ── Step 6: Render ────────────────────────────────────────────────────
print("\n[Render] Starting...")
t2 = time.time()
MoviePyRenderer().render("timeline.json", "output/fermi_paradox_final.mp4")
t3 = time.time()

# ── Stats ─────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"RENDER COMPLETE")
print(f"  Director time: {t1-t0:.1f}s")
print(f"  Audio+Timeline: {t2-t1:.1f}s")
print(f"  Render time: {t3-t2:.1f}s")
print(f"  Total: {t3-t0:.1f}s")
print(f"  Scenes: {len(result_scenes)}")
print(f"  Beats: {total_beats}")
print(f"  Shots: {total_shots}")
print(f"{'=' * 60}")

# Summary stats
shot_durations = []
transitions = {}
motions = {}
cameras = {}
providers = {}
fallback_count = 0
for scene in result_scenes:
    for beat in (scene.beat_plans or []):
        for shot in beat.shots:
            shot_durations.append(shot.duration)
            t = shot.transition.value
            transitions[t] = transitions.get(t, 0) + 1
            m = shot.motion
            motions[m] = motions.get(m, 0) + 1
            c = shot.camera.value
            cameras[c] = cameras.get(c, 0) + 1
            if shot.asset_plan:
                p = shot.asset_plan.provider.value
                providers[p] = providers.get(p, 0) + 1
                if p in ('placeholder', 'emergency'):
                    fallback_count += 1

if shot_durations:
    avg_s = sum(shot_durations) / len(shot_durations)
    max_s = max(shot_durations)
    min_s = min(shot_durations)
    print(f"\n  Avg shot: {avg_s:.1f}s | Max: {max_s:.1f}s | Min: {min_s:.1f}s")
    print(f"  Transitions: {transitions}")
    print(f"  Motions: {motions}")
    print(f"  Cameras: {cameras}")
    print(f"  Providers: {providers}")
    print(f"  Fallbacks: {fallback_count}")
