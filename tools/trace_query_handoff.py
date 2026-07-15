#!/usr/bin/env python3
"""
trace_query_handoff.py — Trace where ConceptPlanner search terms become "general".

Runs Scene 0, Beat 0, Shot 0 of The Fermi Paradox.
Prints the exact object at every handoff boundary.
"""

import os, sys, json, inspect, textwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

LOG = []
def log(obj, label, extra=""):
    """Print exact repr of an object at a boundary."""
    LOG.append(f"\n{'='*70}")
    LOG.append(f"  {label}")
    if extra:
        LOG.append(f"  Context: {extra}")
    LOG.append(f"{'='*70}")
    if isinstance(obj, str):
        LOG.append(f"  VALUE: {obj!r}")
    elif isinstance(obj, (list, tuple)):
        LOG.append(f"  VALUE ({len(obj)} items):")
        for i, item in enumerate(obj):
            LOG.append(f"    [{i}] {item!r}")
    elif isinstance(obj, dict):
        LOG.append(f"  VALUE ({len(obj)} keys):")
        for k, v in obj.items():
            LOG.append(f"    {k}: {v!r}")
    elif obj is None:
        LOG.append(f"  VALUE: None")
    else:
        LOG.append(f"  TYPE: {type(obj).__name__}")
        LOG.append(f"  REPR: {obj!r}")
        # Try common attributes
        for attr in ['search_terms', 'asset_search_queries', 'visual_intent', 'concepts',
                      'query_used', 'query', 'base_query', 'queries', 'search_query',
                      'search_plan', 'spoken_narration']:
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                LOG.append(f"  .{attr} = {val!r}")


# ── 1. Build planner and generate plan ────────────────────────────────
from src.providers.factory import ProviderFactory
factory = ProviderFactory()
planning_provider = factory.get_llm_provider_for_role("planner")

from src.planner import ScenePlanner
planner = ScenePlanner(provider=planning_provider)

topic = "The Fermi Paradox"
log(topic, "1. INPUT TOPIC")

scenes = planner.generate_plan(topic)
log(len(scenes), f"SCENES GENERATED")

scene0 = scenes[0]
log(scene0, "2. SCENE 0 OBJECT (Pydantic Scene)")

# ── 2. Print every search-related field on the Scene ──────────────────
log(scene0.search_plan, "3. scene0.search_plan (SearchPlan)")
log(scene0.search_plan.asset_search_queries, "3a. scene0.search_plan.asset_search_queries")
log(scene0.search_plan.scene_purpose, "3b. scene0.search_plan.scene_purpose")

# Check if visual_intent exists
if hasattr(scene0, 'visual_intent'):
    log(scene0.visual_intent, "3c. scene0.visual_intent")
else:
    log(None, "3c. scene0.visual_intent (NOT PRESENT on this Scene object)")

log(scene0.narration.spoken_narration, "3d. scene0.narration.spoken_narration")
log(scene0.title, "3e. scene0.title")

# ── 3. Build director scene_data ──────────────────────────────────────
search_queries = scene0.search_plan.asset_search_queries
search_query = search_queries[0] if search_queries else "general"
log(search_query, "4. FIRST SEARCH QUERY FROM SearchPlan", f"len(asset_search_queries)={len(search_queries)}")

director_scene_data = [{
    "scene_id": scene0.scene_id,
    "narration": scene0.narration.spoken_narration,
    "search_query": search_query,
    "scene_title": scene0.title,
    "purpose": scene0.search_plan.scene_purpose,
    "estimated_duration": scene0.expected_duration,
}]
log(director_scene_data[0], "5. DIRECTOR SCENE DATA DICT")

# ── 4. Build director and trace ConceptPlanner ────────────────────────
from src.director.visual_style import VisualStyle
from src.director.concept_planner import ConceptPlanner
from src.assets.asset_router import AssetRouter

router = AssetRouter.for_topic(topic)
style = VisualStyle.for_topic(topic, router.category)
concept_planner = ConceptPlanner(provider=planning_provider, visual_style=style)

# Call ConceptPlanner directly to see what it produces
raw_terms = concept_planner.generate_queries(
    narration=scene0.narration.spoken_narration,
    title=scene0.title,
    topic=topic,
    purpose=scene0.search_plan.scene_purpose,
)
log(raw_terms, "6. CONCEPTPLANNER.generate_queries() OUTPUT")

# ── 5. Build director and trace VisualDirector._process_scene ─────────
# Monkey-patch _process_scene to log what queries it receives
from src.director.director import VisualDirector
import src.director.director as director_mod

_orig_process_scene = VisualDirector._process_scene

def traced_process_scene(self, **kwargs):
    LOG.append(f"\n{'='*70}")
    LOG.append(f"  7. VisualDirector._process_scene() CALLED")
    LOG.append(f"{'='*70}")
    LOG.append(f"  search_query param = {kwargs.get('search_query', 'NOT PROVIDED')!r}")
    LOG.append(f"  narration param    = {kwargs.get('narration', '')[:100]!r}...")
    LOG.append(f"  scene_title param  = {kwargs.get('scene_title', '')!r}")
    LOG.append(f"  purpose param      = {kwargs.get('purpose', '')!r}")

    # Now trace what happens inside — the query generation
    # Monkey-patch ConceptPlanner.generate_queries for this call
    _orig_gen = ConceptPlanner.generate_queries
    def traced_gen(self, narration, title="", topic="", purpose="general"):
        LOG.append(f"\n  ── INSIDE ConceptPlanner.generate_queries (traced) ──")
        LOG.append(f"    narration = {narration[:80]!r}...")
        LOG.append(f"    title     = {title!r}")
        LOG.append(f"    topic     = {topic!r}")
        LOG.append(f"    purpose   = {purpose!r}")
        result = _orig_gen(self, narration, title=title, topic=topic, purpose=purpose)
        LOG.append(f"    OUTPUT    = {result!r}")
        return result
    ConceptPlanner.generate_queries = traced_gen

    # Call original
    result = _orig_process_scene(self, **kwargs)
    ConceptPlanner.generate_queries = _orig_gen
    return result

VisualDirector._process_scene = traced_process_scene

# ── 6. Also trace BeatDirector ────────────────────────────────────────
from src.cinematic.director_integration import BeatDirector

_orig_process_shot = BeatDirector._process_shot

def traced_process_shot(self, scene, beat, shot, narration, shot_index, max_retries=3):
    LOG.append(f"\n{'='*70}")
    LOG.append(f"  8. BeatDirector._process_shot() CALLED")
    LOG.append(f"{'='*70}")
    LOG.append(f"  shot.description = {shot.description!r}")
    LOG.append(f"  shot.shot_type   = {shot.shot_type.value if hasattr(shot, 'shot_type') else '?'}")
    LOG.append(f"  narration        = {narration[:80]!r}...")

    # Look at what queries it builds
    if scene and scene.search_plan:
        LOG.append(f"  scene.search_plan.asset_search_queries = {scene.search_plan.asset_search_queries!r}")
    base_query = scene.search_plan.asset_search_queries[0] if scene and scene.search_plan and scene.search_plan.asset_search_queries else "N/A"
    LOG.append(f"  base_query (first from search_plan) = {base_query!r}")

    shot_type = shot.shot_type.value if hasattr(shot, 'shot_type') else ""
    shot_query = f"{base_query} {shot_type} shot"
    LOG.append(f"  shot_query = {shot_query!r}")
    LOG.append(f"  queries list = {[shot_query, base_query, f'{self._topic} documentary stock footage']!r}")

    return _orig_process_shot(self, scene, beat, shot, narration, shot_index, max_retries)

BeatDirector._process_shot = traced_process_shot

# ── 7. Monitor AssetRouter.multi_query_search ─────────────────────────
_orig_multi = AssetRouter.multi_query_search

def traced_multi(self, queries, **kwargs):
    LOG.append(f"\n{'='*70}")
    LOG.append(f"  9. AssetRouter.multi_query_search() INPUT")
    LOG.append(f"{'='*70}")
    LOG.append(f"  queries = {queries!r}")
    stack = inspect.stack()
    for frame in stack[:5]:
        LOG.append(f"    called from: {os.path.basename(frame.filename)}:{frame.lineno} {frame.function}()")
    result = _orig_multi(self, queries, **kwargs)
    LOG.append(f"  output selected_query = {result.get('selected_query', 'N/A')!r}")
    LOG.append(f"  provider = {result.get('provider_name', 'N/A')!r}")
    LOG.append(f"  asset count = {len(result.get('assets', []))}")
    return result

AssetRouter.multi_query_search = traced_multi

# ── 8. Run director for scene 0 only ──────────────────────────────────
director = VisualDirector(
    use_beats=True,
    topic=topic,
    llm_provider=planning_provider,
    scene_data=director_scene_data,
)

# Run but catch errors
try:
    results = director.run()
except Exception as e:
    LOG.append(f"\n{'='*70}")
    LOG.append(f"  EXCEPTION during director.run(): {e}")
    LOG.append(f"{'='*70}")
    import traceback
    LOG.append(traceback.format_exc())

# ── 9. Print the full log ─────────────────────────────────────────────
for line in LOG:
    print(line)

# ── 10. Save to file ──────────────────────────────────────────────────
report_lines = [
    "# Search Query Handoff Trace",
    "",
    f"**Date:** 2026-07-14",
    f"**Topic:** The Fermi Paradox — Scene 0, Beat 0, Shot 0",
    f"**Commit:** `{os.popen('cd ' + os.path.dirname(os.path.abspath(__file__)) + '/.. && git rev-parse HEAD').read().strip()}`",
    "",
    "---",
    "```",
]
report_lines.extend(LOG)
report_lines.append("```")

report_path = "docs/investigations/search_query_handoff_trace.md"
with open(report_path, "w") as f:
    f.write("\n".join(report_lines))

print(f"\n\nReport saved to: {report_path}")
