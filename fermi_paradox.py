#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["VIRTUAL_ENV"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv")

"""
Render a Fermi Paradox documentary using beat-based editing.
"""

import sys
import os
import json
sys.path.insert(0, '.')

from src.cinematic import TimelineBuilder, BeatDirector
from src.models import Scene, BeatPlan
from src.models.schemas import (
    Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan,
    AudioPlan, RenderPlan, CameraMotion, TransitionType, ProviderType
)
from src.director import VisualDirector
from src.renderer.moviepy_renderer import MoviePyRenderer
from src.renderer.timeline_builder import TimelineBuilder as LegacyTimelineBuilder
from src.utils.config import get_config
from src.providers import DeepSeekProvider
from audio_engine import generate_voice, mix_audio

# ── Topic data ────────────────────────────────────────────────────────
topic = "The Fermi Paradox"

scenes_data = [
    {
        "title": "The Great Silence",
        "narration": "The universe is incomprehensibly vast. With hundreds of billions of stars in our galaxy alone, and trillions more beyond, the numbers suggest we should not be alone. Yet when we gaze at the stars, we hear nothing but silence. This is the Fermi Paradox.",
        "duration": 18.0,
    },
    {
        "title": "A Simple Question",
        "narration": "Enrico Fermi posed a deceptively simple question. If the conditions for life are common in the universe, where is everybody? The observable universe contains more stars than grains of sand on every beach on Earth. Even if intelligent life emerges only once in a million stars, the galaxy should be teeming with civilizations.",
        "duration": 18.0,
    },
    {
        "title": "The Drake Equation",
        "narration": "Frank Drake attempted to quantify this question with his famous equation. It multiplies the rate of star formation, the fraction of stars with planets, the number of habitable worlds, the likelihood of life arising, and the lifetime of technological civilizations. The answers range from thousands of civilizations to just one. Ours.",
        "duration": 20.0,
    },
    {
        "title": "The Great Filter",
        "narration": "One troubling solution is the Great Filter. Perhaps there is a step in evolution so difficult that almost no civilization passes through it. This filter could be behind us, in our past. The emergence of life itself. Or it could lie ahead. Waiting.",
        "duration": 16.0,
    },
    {
        "title": "Rare Earth Hypothesis",
        "narration": "Perhaps Earth is special. Our large moon stabilizes the axial tilt. Jupiter sweeps up dangerous asteroids. Our position in the galactic habitable zone is just right. The Cambrian explosion, the evolution of intelligence, the development of language. Each step required an improbable chain of events spanning billions of years.",
        "duration": 18.0,
    },
    {
        "title": "Dark Forest Theory",
        "narration": "The Dark Forest theory offers a chilling possibility. Every civilization is a hunter in a dark forest. Revealing your position means inviting destruction. Silence is survival. The universe appears empty not because civilizations don't exist, but because those that survive learn to stay hidden.",
        "duration": 16.0,
    },
    {
        "title": "Technological Singularity",
        "narration": "Perhaps advanced civilizations transcend biological form entirely. They upload their consciousness into digital realms, explore inner space rather than outer space. To them, the physical universe might be merely a brief stage in the evolution of mind. A launching pad, not a destination.",
        "duration": 16.0,
    },
    {
        "title": "The Zoo Hypothesis",
        "narration": "What if we are being observed like animals in a zoo? Advanced civilizations might have a prime directive, a cosmic quarantine. They watch, they study, but they do not interfere. Waiting for us to reach a certain threshold of development before making contact.",
        "duration": 16.0,
    },
    {
        "title": "Simulation Argument",
        "narration": "The simulation hypothesis suggests our universe might be a computer program running on an advanced civilization's hardware. Perhaps they've simulated billions of universes, each slightly different. The Fermi Paradox becomes trivial. We are not alone because nothing else is real.",
        "duration": 16.0,
    },
    {
        "title": "The Waiting Game",
        "narration": "The universe is 13.8 billion years old. Human civilization has existed for only ten thousand years. Our technological civilization capable of listening for alien signals is barely a century old. We may simply not have been listening long enough. The signal could arrive tomorrow. Or never.",
        "duration": 18.0,
    },
]

def main():
    print("="*60)
    print("  FERMI PARADOX — Beat-Based Render Test")
    print("  Topic: The Fermi Paradox")
    print(f"  Scenes: {len(scenes_data)}")
    print("  Duration: ~170 seconds")
    print("="*60)

    # ── Step 1: Create Scene objects ──────────────────────────────────
    scenes = []
    for i, sd in enumerate(scenes_data):
        scene = Scene(
            scene_id=i,
            title=sd["title"],
            expected_duration=sd["duration"],
            topic=topic,
            narration=SceneNarration(spoken_narration=sd["narration"]),
            visual_plan=VisualPlan(visual_description=f"Scene {i}: {sd['title']}"),
            search_plan=SearchPlan(asset_search_queries=[f"{sd['title'].lower()} documentary stock footage"]),
            editing_plan=EditingPlan(editing_instructions="cinematic documentary style"),
            metadata={"title": sd["title"], "narration_preview": sd["narration"][:80]},
        )
        scenes.append(scene)

    # ── Step 2: Run VisualDirector in beat mode ───────────────────────
    director = VisualDirector(
        topic=topic,
        llm_provider=None,
        scene_data=scenes,
        use_beats=True,
    )
    print("\n[STEP 1] Running VisualDirector (beat mode)...")
    result_scenes = director.run()
    print(f"\n  Produced {len(result_scenes)} processed scenes")

    # ── Step 3: Generate audio for each scene ─────────────────────────
    print("\n[STEP 2] Generating voiceovers...")
    for scene in result_scenes:
        audio_path = f"cache/audio/scene_{scene.scene_id}.wav"
        narration = scene.narration.spoken_narration
        print(f"  Scene {scene.scene_id}: '{narration[:60]}...' -> {audio_path}")
        generate_voice(narration, audio_path)
        scene.audio_plan = AudioPlan(
            narration_audio_path=audio_path,
            music_style="cinematic",
            music_volume=0.15,
            ducking_enabled=True,
        )

    # ── Step 4: Build timeline ────────────────────────────────────────
    print("\n[STEP 3] Building timeline...")
    timeline_builder = LegacyTimelineBuilder()
    timeline_path = timeline_builder.build_and_write(
        scenes=result_scenes,
        output_path="timeline.json",
    )

    # Log beat stats from each scene
    print("\n[STEP 4] Beat stats per scene:")
    total_beats = 0
    total_shots = 0
    for scene in result_scenes:
        if scene.beat_plans:
            n_beats = len(scene.beat_plans)
            n_shots = sum(len(b.shots) for b in scene.beat_plans)
            total_beats += n_beats
            total_shots += n_shots
            print(f"  Scene {scene.scene_id}: {n_beats} beats, {n_shots} shots")

    print(f"\n  Total: {total_beats} beats, {total_shots} shots")

    # ── Step 5: Render ────────────────────────────────────────────────
    print("\n[STEP 5] Rendering video...")
    output_path = "output/fermi_paradox_beat.mp4"
    renderer = MoviePyRenderer()
    renderer.render(
        timeline_path=timeline_path,
        output_path=output_path,
        subtitles=None,
    )

    # ── Verify ────────────────────────────────────────────────────────
    if os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n{'='*60}")
        print(f"  RENDER COMPLETE: {output_path}")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"{'='*60}")
    else:
        print(f"\n  ERROR: Output file not found!")

    return result_scenes


if __name__ == "__main__":
    scenes = main()
