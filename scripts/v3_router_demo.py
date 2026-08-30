"""v3_router_demo.py — Router demo: 5 example shots from the directive.

Loads each example shot, runs the deterministic renderer router and prints
the chosen renderer + fallback chain. No LLM, no network.

    venv/bin/python scripts/v3_router_demo.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.renderers.router import select_renderer  # noqa: E402

EXAMPLE_SHOTS = [
    {
        "title": "Math proof (Kaprekar routine)",
        "shot": {
            "version": "v3", "shot_id": "S01", "duration_sec": 6.0,
            "narrative_role": "explanation",
            "visual_goal": "walk through the proof step by step with precise notation",
            "renderer": "MANIM", "generation_priority": "normal",
            "requirements": {"math_precision": True, "diagrammatic": True,
                             "text_heavy": True},
        },
    },
    {
        "title": "Exploding volcano",
        "shot": {
            "version": "v3", "shot_id": "S02", "duration_sec": 4.0,
            "narrative_role": "climax",
            "visual_goal": "volcano erupting with escalating scale",
            "generation_priority": "high",
            "requirements": {"realism": True, "physical_motion": True,
                             "emotional_impact": True},
        },
    },
    {
        "title": "NASA launch (archival)",
        "shot": {
            "version": "v3", "shot_id": "S03", "duration_sec": 5.0,
            "narrative_role": "context",
            "visual_goal": "authentic footage of a rocket lifting off",
            "generation_priority": "normal",
            "requirements": {"realism": True, "historical_authenticity": True},
        },
    },
    {
        "title": "Kinetic headline",
        "shot": {
            "version": "v3", "shot_id": "S04", "duration_sec": 2.5,
            "narrative_role": "hook",
            "visual_goal": "kinetic typography slamming the core question on screen",
            "generation_priority": "low",
            "requirements": {"text_heavy": True},
        },
    },
    {
        "title": "Cartoon scene (T. rex chase)",
        "shot": {
            "version": "v3", "shot_id": "S05", "duration_sec": 4.0,
            "narrative_role": "escalation",
            "visual_goal": "cartoon T. rex running through prehistoric jungle",
            "generation_priority": "normal",
            "requirements": {"character_interaction": True, "stylization": True,
                             "physical_motion": True},
        },
    },
]


def main() -> int:
    print(f"{'shot':32} {'chosen':16} {'score':>7}  fallback chain")
    print("-" * 110)
    for example in EXAMPLE_SHOTS:
        decision = select_renderer(example["shot"])
        chain = " → ".join(decision.fallback_chain[:6])
        print(f"{example['title']:32} {decision.renderer_id:16} "
              f"{decision.score:>7.3f}  {chain}")
    print()

    # Extra: degradation under quota pressure + outage
    shot = EXAMPLE_SHOTS[1]["shot"]
    no_quota = select_renderer(shot, quota={"AI_VIDEO": 0.0})
    print(f"volcano with AI_VIDEO quota 0.0 → {no_quota.renderer_id}")
    outage = select_renderer(
        {"requirements": {"math_precision": True, "diagrammatic": True}},
        availability={rid: False for rid in ("AI_VIDEO", "AI_IMAGE_MOTION",
                                             "STOCK_VIDEO", "ARCHIVAL")},
    )
    print(f"math proof with all remote services down → {outage.renderer_id} "
          f"(offline chain intact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
