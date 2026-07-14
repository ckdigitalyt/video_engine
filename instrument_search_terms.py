#!/usr/bin/env python3
"""
Instrumentation script to trace the exact origin of the literal search term "general".
Traces Scene 0 -> Beat 0 -> Shot 1 through the full pipeline.

No code changes — only reads at trace points.
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path

# Add project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.models.schemas import VisualIntent, SearchPlan, Scene, SceneNarration, BeatPlan, ShotPlan, ShotType
from src.planner.planner import StoryPlanner
from src.providers.factory import ProviderFactory

TRACE_LOG = "docs/investigations/search_terms_trace.log"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    with open(TRACE_LOG, "a") as f:
        f.write(line + "\n")

def log_block(title, content, indent=0):
    prefix = "  " * indent
    log(f"{prefix}=== {title} ===")
    for k, v in content.items():
        log(f"{prefix}  {k}: {v}")
    log(f"{prefix}=== END {title} ===")

def main():
    # Clear log
    with open(TRACE_LOG, "w") as f:
        f.write(f"Search Term Lineage Trace — {time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write("=" * 70 + "\n\n")

    log("=" * 70)
    log("INSTRUMENTATION: Search Term \"general\" Lineage")
    log("Target: Scene 0 -> Beat 0 -> Shot 1")
    log("=" * 70)

    # ── 1. Create a planner and trace through generate_plan ──────────────
    log("\n[1] Setting up StoryPlanner...")
    factory = ProviderFactory()
    provider = factory.get_llm_provider_for_role("planner")
    planner = StoryPlanner(provider=provider)

    topic = "The Fermi Paradox"

    # ── 2. Trace Phase 1: Outline generation ─────────────────────────────
    log("\n[2] Phase 1: Generating outline...")
    outline = planner._generate_outline(topic)
    log_block("OUTLINE RAW", {"length": len(outline), "preview": outline[:500]})

    # ── 3. Trace Phase 2: Scene generation ────────────────────────────────
    log("\n[3] Phase 2: Generating scenes...")
    scenes_json = planner._generate_scenes(topic, outline)
    log_block("SCENES RAW", {"length": len(scenes_json), "preview": scenes_json[:1000]})

    # ── 4. Parse scenes and trace visual_intent generation ────────────────
    scene_dicts = json.loads(scenes_json).get("scenes", [])
    log(f"\n[4] Scene count: {len(scene_dicts)}")

    for i, sd in enumerate(scene_dicts):
        log(f"\n--- Scene {i}: {sd.get('title', 'N/A')} ---")
        log(f"  narration: {sd.get('narration', 'N/A')[:200]}")

        # ── 5. Visual Intent generation ──────────────────────────────────
        log(f"\n[5] Generating visual_intent for Scene {i}...")
        visual_intent = planner._generate_visual_intent(sd, topic, i)

        log_block(f"VISUAL_INTENT (Scene {i})", {
            "visual_objective": visual_intent.visual_objective[:100] if visual_intent.visual_objective else "",
            "search_terms": str(visual_intent.search_terms[:5]),
            "search_terms_count": len(visual_intent.search_terms),
            "concepts": str(visual_intent.concepts[:5]),
            "class": type(visual_intent).__name__,
        })

        # ── 6. Sanitise search terms ─────────────────────────────────────
        narration_text = sd.get("narration", "")
        sanitised = planner._sanitise_search_terms(
            visual_intent.search_terms,
            narration_text,
            topic,
        )
        log_block(f"SANITISED TERMS (Scene {i})", {
            "original_count": len(visual_intent.search_terms),
            "sanitised_count": len(sanitised),
            "sanitised_preview": str(sanitised[:5]),
            "contains_general_str": "general" in str(sanitised),
        })

        # ── 7. Build Scene object — where SearchPlan.asset_search_queries is set ──
        log(f"\n[7] Building Scene object with SearchPlan...")
        scene = Scene(
            scene_id=i,
            title=sd.get("title", f"Scene {i}"),
            expected_duration=sd.get("estimated_duration", 12.0),
            topic=topic,
            narration=SceneNarration(
                spoken_narration=sd.get("narration", "narration pending"),
            ),
            visual_intent=visual_intent,
            search_plan=SearchPlan(
                asset_search_queries=sanitised or ["general"],  # ← KEY INSERTION POINT
                primary_topic=topic,
                scene_purpose=(visual_intent.visual_objective or "general")[:200],  # ← KEY INSERTION POINT
            ),
        )

        log_block(f"SEARCH_PLAN (Scene {i})", {
            "asset_search_queries": str(scene.search_plan.asset_search_queries[:5]),
            "scene_purpose": scene.search_plan.scene_purpose,
            "sanitised_was_empty": str(sanitised == []),
            "line_185_fired": str(sanitised == []),
        })

        # For Scene 0, trace deeper into beat mode
        if i == 0:
            log(f"\n{'='*70}")
            log("TRACING SCENE 0 INTO BEAT MODE")
            log(f"{'='*70}")

            # ── 8. BeatTimelineBuilder ───────────────────────────────────
            from src.cinematic.beat_planner import TimelineBuilder as BeatTimelineBuilder
            bt = BeatTimelineBuilder()
            beat_plans = bt.build_timeline(scene.narration.spoken_narration, scene.expected_duration, topic)

            log(f"\n[8] BeatTimelineBuilder produced {len(beat_plans)} beats:")
            for bi, bp in enumerate(beat_plans):
                log(f"  Beat {bi}: {bp.text[:80]}... {len(bp.shots)} shots")

                for si, sp in enumerate(bp.shots):
                    log(f"    Shot {si}: type={sp.shot_type.value}, dur={sp.duration:.2f}s, "
                        f"desc='{sp.description}', motion={sp.motion}")

            # ── 9. BeatDirector.shot queries generation (simulated) ──────
            # This reproduces the logic from director_integration.py _process_shot
            log(f"\n[9] Simulating BeatDirector._process_shot for Scene 0 Beat 0 Shot 1...")
            
            beat_0 = beat_plans[0]
            if len(beat_0.shots) > 1:
                target_shot = beat_0.shots[1]
            else:
                log("ERROR: Beat 0 has < 2 shots, using shot 0")
                target_shot = beat_0.shots[0]

            visual_intent = getattr(scene, 'visual_intent', None)
            log(f"  visual_intent available: {visual_intent is not None}")
            
            # Replicate the query generation from director_integration.py lines 104-120
            if visual_intent and (visual_intent.search_terms or visual_intent.concepts):
                base_query = visual_intent.search_terms[0] if visual_intent.search_terms else topic
                log(f"  Using visual_intent path: base_query='{base_query}'")
                log(f"  visual_intent.search_terms[0] = '{visual_intent.search_terms[0] if visual_intent.search_terms else 'N/A'}'")
            else:
                base_query = scene.search_plan.asset_search_queries[0] if scene.search_plan.asset_search_queries else topic
                log(f"  Using fallback path: base_query='{base_query}'")
                log(f"  asset_search_queries[0] = '{scene.search_plan.asset_search_queries[0] if scene.search_plan.asset_search_queries else 'N/A'}'")

            # Now replicate expand_for_shot call from director_integration.py line 110-115
            from src.assets.query_expander import expand_for_shot
            category = "General"  # will be classified from topic
            # Classify topic
            tl = topic.lower()
            if any(w in tl for w in ["space", "star", "galaxy", "universe", "planet", "cosmic"]):
                category = "Space"

            queries = expand_for_shot(
                base_query=base_query,
                shot_type=target_shot.shot_type.value,
                topic=topic,
                category=category,
            )
            log_block(f"EXPAND_FOR_SHOT OUTPUT", {
                "input_base_query": base_query,
                "input_shot_type": target_shot.shot_type.value,
                "input_topic": topic,
                "input_category": category,
                "output_queries": str(queries),
                "contains_general": "general" in str(queries),
                "source_description": target_shot.description,
            })

            # ── 10. Check the specific "general cutaway shot" pattern ────
            log(f"\n[10] Analyzing how 'general cutaway shot' is formed:")
            if base_query == "general" and target_shot.shot_type.value == "cutaway":
                gen_query = f"{base_query} {target_shot.shot_type.value} shot"
                log(f"  Pattern: '{base_query}' + ' ' + '{target_shot.shot_type.value}' + ' shot'")
                log(f"  Result: '{gen_query}'")
                log(f"  Root cause: expand_for_shot line 1: queries = [f'{{base_query}} {{shot_type}} shot']")
            else:
                log(f"  Not the 'general cutaway shot' case:")
                log(f"  base_query='{base_query}', shot_type='{target_shot.shot_type.value}'")

        # Only instrument Scene 0 for the beat trace
        if i > 0:
            break

    log(f"\n{'='*70}")
    log("INSTRUMENTATION COMPLETE")
    log(f"{'='*70}")

    # ── Summary table ────────────────────────────────────────────────────
    log(f"\n\nVALUE_CHAIN_TABLE")
    log(f"{'Stage':<45} | {'Runtime Value':<40}")
    log("-" * 87)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        traceback.print_exc()
