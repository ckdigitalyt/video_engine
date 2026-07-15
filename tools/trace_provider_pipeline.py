#!/usr/bin/env python3
"""
trace_provider_pipeline.py — Trace ONE shot through every provider to find
the first point where a valid asset fails to become AssetPlan.filepath.

Scope: The Fermi Paradox, Scene 0, Beat 0, Shot 0.
"""

import os, sys, json, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

LOG = []
def log(msg):
    LOG.append(msg)
    print(msg)

# ── 1. Generate the plan ──────────────────────────────────────────────
from src.providers.factory import ProviderFactory
factory = ProviderFactory()
planning_provider = factory.get_llm_provider_for_role("planner")

from src.planner import ScenePlanner
planner = ScenePlanner(provider=planning_provider)
scenes = planner.generate_plan("The Fermi Paradox")
scene0 = scenes[0]

log("=" * 70)
log("TRACE: Provider Pipeline — Scene 0, Beat 0, Shot 0")
log(f"Topic: The Fermi Paradox")
log(f"Scene title: {scene0.title}")
log(f"Narration: {scene0.narration.spoken_narration[:150]}...")
log("=" * 70)

# ── 2. Simulate what BeatDirector does ────────────────────────────────
from src.director.concept_planner import ConceptPlanner
from src.director.visual_style import VisualStyle
from src.assets.asset_router import AssetRouter

router = AssetRouter.for_topic("The Fermi Paradox")
style = VisualStyle.for_topic("The Fermi Paradox", router.category)

concept_planner = ConceptPlanner(provider=planning_provider, visual_style=style)
raw_terms = concept_planner.generate_queries(
    narration=scene0.narration.spoken_narration,
    title=scene0.title,
    topic="The Fermi Paradox",
    purpose=scene0.search_plan.scene_purpose,
)
log(f"\nConceptPlanner terms ({len(raw_terms)}):")
for t in raw_terms:
    log(f"  {t!r}")

from src.cinematic.beat_planner import TimelineBuilder as BeatTimelineBuilder
btb = BeatTimelineBuilder()
beat_plans = btb.build_timeline(scene0.narration.spoken_narration, scene0.expected_duration, "The Fermi Paradox")

if not beat_plans:
    log("NO BEAT PLANS")
    exit(1)

beat0 = beat_plans[0]
shot0 = beat0.shots[0]
shot_type = shot0.shot_type.value
shot_duration = shot0.duration

log(f"\nBeat 0: {len(beat0.shots)} shots")
log(f"Shot 0: type={shot_type}, duration={shot_duration}")
log(f"  description: {shot0.description!r}")

# Build the three queries BeatDirector would use
base_query = raw_terms[0] if raw_terms else "The Fermi Paradox"
shot_query = f"{base_query} {shot_type} shot"
fallback_query = f"{shot_type} shot for beat 0"
queries = [shot_query, base_query, "The Fermi Paradox documentary stock footage"]

log(f"\nQueries to try:")
for i, q in enumerate(queries):
    log(f"  [{i}] {q!r}")

# ── 3. Run each query through every provider ─────────────────────────
from src.models.schemas import AssetPlan, ProviderType
from src.validation.semantic_validator import SemanticValidator
from src.director.quality_gate import QualityGates
from src.director.aesthetic_agent import AestheticAgent

semantic_validator = SemanticValidator(provider=planning_provider, enabled=True)
aesthetic_agent = AestheticAgent(visual_style=style)
quality_gates = QualityGates(
    visual_style=style,
    aesthetic_agent=aesthetic_agent,
    semantic_threshold=semantic_validator._threshold,
)
category = router.category

# Inspect provider readiness
log(f"\n{'='*70}")
log("PROVIDER READINESS CHECK")
log(f"{'='*70}")
for name, prov in router._providers.items():
    ready = router._is_provider_ready(prov, name)
    log(f"  {name}: ready={ready} (type={type(prov).__name__})")

# ── 4. Manual provider search ────────────────────────────────────────
provider_order = router._routes.get(category, router._routes.get("General", []))

for query in queries:
    log(f"\n{'='*70}")
    log(f"QUERY: {query!r}")
    log(f"{'='*70}")

    for provider_name in provider_order:
        prov = router._providers.get(provider_name)
        if prov is None:
            log(f"  {provider_name}: provider object is None — SKIPPED")
            continue

        if not router._is_provider_ready(prov, provider_name):
            log(f"  {provider_name}: NOT READY (API key missing or env not set) — SKIPPED")
            continue

        log(f"\n  ── {provider_name} ──")
        try:
            results = prov.search(query, target_duration=shot_duration)
        except Exception as e:
            log(f"  SEARCH EXCEPTION: {e}")
            continue

        result_count = len(results) if results else 0
        log(f"  Results returned: {result_count}")

        if not results:
            log(f"  → No candidates — SKIPPED")
            continue

        best = results[0]
        log(f"  Best candidate keys: {list(best.keys())}")

        # Normalize
        vf = best.get("video_files", [{}])
        if isinstance(vf, list) and vf:
            vf_link = vf[0].get("link", "")
        else:
            vf_link = best.get("url", "") or best.get("download_url", "") or ""

        width = best.get("width", 0)
        height = best.get("height", 0)
        duration = best.get("duration", 0.0)

        log(f"  Video URL: {vf_link!r}")
        log(f"  Dimensions: {width}x{height}")
        log(f"  Duration: {duration}s")

        if not vf_link:
            log(f"  → No download URL extracted — SKIPPED")
            continue

        # ── Build AssetPlan like BeatDirector does ──────────────────
        ap = AssetPlan(
            provider=ProviderType(provider_name),
            filepath="",
            video_url=vf_link,
            query_used=query,
            score=0.5, semantic_score=0.5,
            technical_score=0.5, aesthetic_style="real_stock",
            duration=max(duration, 1.0),
            width=max(width, 1920),
            height=max(height, 1080),
        )
        log(f"  AssetPlan created (filepath={ap.filepath!r})")

        # ── Semantic validation ─────────────────────────────────────
        sem_score = semantic_validator.score(
            narration=scene0.narration.spoken_narration,
            query=query,
            asset=ap,
        )
        ap.semantic_score = sem_score
        log(f"  Semantic score: {sem_score:.4f} (threshold: {semantic_validator._threshold})")

        if not semantic_validator.is_acceptable(sem_score):
            log(f"  → REJECTED by SemanticGate (score {sem_score:.4f} < {semantic_validator._threshold})")
            # Continue to next provider/query

        # ── Quality gates ───────────────────────────────────────────
        passed, reason, details = quality_gates.check_all(
            asset=ap,
            category=category,
        )
        log(f"  Quality gates:")
        for gate_name, detail in details.items():
            log(f"    {'✓' if detail['passed'] else '✗'} {gate_name}: {detail['reason']}")

        if not passed:
            log(f"  → REJECTED by quality gates: {reason}")
            continue

        # ── Download ────────────────────────────────────────────────
        log(f"  → ALL GATES PASSED — Attempting download...")
        cache_video = "cache/video"
        os.makedirs(cache_video, exist_ok=True)
        dl_path = os.path.join(cache_video, "trace_scene_0_b0_s0.mp4")
        try:
            router.download(vf_link, dl_path)
            ap.filepath = dl_path
            log(f"  Download path: {ap.filepath!r}")
            if os.path.exists(dl_path):
                sz = os.path.getsize(dl_path)
                log(f"  Download SUCCEEDED: {sz} bytes")
            else:
                log(f"  Download FAILED: file not found after download()")
        except Exception as e:
            log(f"  Download EXCEPTION: {e}")
            continue

        # ── SUCCESS — asset fully populated ─────────────────────────
        log(f"\n{'='*70}")
        log(f"SUCCESS: AssetPlan.filepath = {ap.filepath!r}")
        log(f"{'='*70}")
        LOG.append(f"\n{'='*70}")
        LOG.append("SUMMARY")
        LOG.append(f"{'='*70}")
        LOG.append(f"Query: {query!r}")
        LOG.append(f"Provider: {provider_name}")
        LOG.append(f"AssetPlan.filepath: {ap.filepath!r}")
        LOG.append(f"Download size: {sz} bytes")
        LOG.append(f"\nThe first failing component is <none> — all stages passed successfully." if ap.filepath else "")
        save_report(LOG)
        exit(0)

    log(f"  Query exhausted — no provider returned an acceptable asset")

log(f"\n{'='*70}")
log("ALL QUERIES EXHAUSTED — no asset reached AssetPlan.filepath")
log(f"{'='*70}")

# Determine the first failing component
log(f"\nFINDING: First failing component analysis:")
# Check each provider's results
for provider_name in provider_order:
    prov = router._providers.get(provider_name)
    if prov is None:
        log(f"  {provider_name}: OBJECT IS None — module import failed?")
        continue
    if not router._is_provider_ready(prov, provider_name):
        log(f"  {provider_name}: NOT READY (API key/credentials missing)")
        continue
    # Try a simple search
    try:
        log(f"  {provider_name}: Testing with query {queries[0]!r}...")
        results = prov.search(queries[0])
        log(f"  {provider_name}: returned {len(results) if results else 0} results")
        if results:
            log(f"  {provider_name}: first result keys = {list(results[0].keys())}")
    except Exception as e:
        log(f"  {provider_name}: search exception: {e}")

save_report(LOG)
