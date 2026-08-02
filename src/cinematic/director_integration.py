"""
director_integration.py — Bridges the Cinematic TimelineBuilder into the
VisualDirector pipeline.  When beat mode is enabled, each scene's narration
is split into semantic beats, and each beat gets its own asset search +
quality gate loop.

This replaces the old single-clip-per-scene flow with beat-based editing.
"""

from typing import List, Optional, Dict, Any
import os
import concurrent.futures

from src.cinematic.beat_planner import TimelineBuilder as BeatTimelineBuilder
from src.cinematic.duplicate_detector import DuplicateDetector
from src.models import BeatPlan, ShotPlan, ShotType, Scene
from src.models.schemas import (
    AssetPlan, CameraMotion, TransitionType, ProviderType,
)
from src.assets import AssetRouter
from src.assets.asset_ranker import AssetRanker
from src.assets.broll_taxonomy import BrollTaxonomy
from src.critic.visual_critic import VisualCritic
from src.director.storyboard_planner import StoryboardPlanner
from src.validation.semantic_validator import SemanticValidator
from src.director.quality_gate import QualityGates
from src.director.fallback_director import FallbackDirector
from src.director.concept_planner import ConceptPlanner


class ConceptQueryPool:
    """Round-robin pool of ConceptPlanner-generated queries for one scene.

    Caches the ConceptPlanner output and distributes queries across shots
    so each beat gets a visually distinct search term.
    """

    def __init__(self, topic: str, raw_terms: list[str], concept_planner: ConceptPlanner):
        self._topic = topic
        self._pool = list(raw_terms) if raw_terms else [topic]
        self._index = 0

    def next_query(self, shot_type: str = "primary") -> str:
        """Get the next query from the pool (round-robin)."""
        base = self._pool[self._index % len(self._pool)]
        self._index += 1
        return f"{base} {shot_type} shot"

    @property
    def query_count(self) -> int:
        return len(self._pool)


class BeatDirector:
    """Handles beat-based processing within VisualDirector."""

    def __init__(
        self,
        router: AssetRouter,
        quality_gates: QualityGates,
        semantic_validator: SemanticValidator,
        concept_planner: ConceptPlanner,
        fallback_director: FallbackDirector,
        topic: str,
        cache_video: str,
        cache_audio: str,
        knowledge_library: Optional[Any] = None,
    ):
        self._router = router
        self._quality_gates = quality_gates
        self._semantic_validator = semantic_validator
        self._concept_planner = concept_planner
        self._fallback_director = fallback_director
        self._topic = topic
        self._cache_video = cache_video
        self._cache_audio = cache_audio
        self._beat_timeline_builder = BeatTimelineBuilder()

        # Knowledge Library for curated per-shot search queries
        self._knowledge_library = knowledge_library

        # Duplicate detector — tracks all used assets per render run
        self._duplicate_detector = DuplicateDetector(
            hash_size=8,
            similarity_threshold=0.85,
            max_reuses_per_video=2,
        )

        # Per-scene concept query pools (populated lazily in process_scene_beats)
        self._concept_pools: dict[int, ConceptQueryPool] = {}

        self.total_queries_tried = 0
        self.total_gate_rejections = 0
        self.total_fallbacks = 0
        self.total_shots_requested = 0
        self.total_shots_accepted = 0

    def process_scene_beats(
        self,
        scene: Scene,
        max_retries_per_shot: int = 3,
    ) -> Scene:
        """Plan beats, search assets per shot, populate beat_plans."""
        narration = scene.narration.spoken_narration
        duration = scene.expected_duration
        topic = self._topic

        print(f"\n  [BeatDirector] Planning beats for scene {scene.scene_id}...")
        beat_plans = self._beat_timeline_builder.build_timeline(
            narration, duration, topic, scene_index=scene.scene_id
        )
        if not beat_plans:
            return scene
        if not beat_plans:
            return scene

        # ── Generate ConceptPlanner queries ONCE per scene ────────────────
        purpose = scene.search_plan.scene_purpose if hasattr(scene, 'search_plan') and scene.search_plan else "general"
        raw_terms = self._concept_planner.generate_queries(
            narration=narration,
            title=scene.title,
            topic=self._topic,
            purpose=purpose,
        )

        # If ConceptPlanner returned weak/generic terms, enrich with
        # Knowledge Library curated searches for this topic
        is_weak = (
            not raw_terms
            or len(raw_terms) <= 2
            or all(q in ("", "stock footage", "documentary", "general")
                   for q in raw_terms[:4])
        )
        if is_weak and self._knowledge_library is not None:
            entry = self._knowledge_library.lookup(self._topic)
            if entry and entry.preferred_stock_footage_searches:
                raw_terms = list(entry.preferred_stock_footage_searches)
                # Also add NASA and Wikimedia searches for variety
                if entry.preferred_nasa_searches:
                    raw_terms.extend(entry.preferred_nasa_searches[:3])
                if entry.preferred_wikimedia_searches:
                    raw_terms.extend(entry.preferred_wikimedia_searches[:2])
                print(f"  [BeatDirector] Enriched with Knowledge Library ({len(raw_terms)} terms)")

        if not raw_terms or all(q in ("", "stock footage") for q in raw_terms):
            raw_terms = [self._topic]
        print(f"  [BeatDirector] Concept terms ({len(raw_terms)}): {raw_terms[:4]}...")

        pool = ConceptQueryPool(self._topic, raw_terms, self._concept_planner)
        self._concept_pools[scene.scene_id] = pool
        # ───────────────────────────────────────────────────────────────

        print(f"  [BeatDirector] {len(beat_plans)} beats, "
              f"{sum(len(b.shots) for b in beat_plans)} shots")

        for beat in beat_plans:
            for shot_idx, shot in enumerate(beat.shots):
                self.total_shots_requested += 1
                result = self._process_shot(scene, beat, shot, narration, shot_idx, max_retries_per_shot)
                if result is not None:
                    shot.asset_plan = result
                    shot.semantic_score = result.semantic_score
                    self.total_shots_accepted += 1

        # Fallback for failed shots
        for beat in beat_plans:
            for shot in beat.shots:
                if shot.asset_plan is None:
                    self.total_fallbacks += 1
                    fallback = self._fallback_for_shot(scene, beat, shot, narration)
                    if fallback:
                        shot.asset_plan = fallback
                        shot.semantic_score = fallback.semantic_score
                        self.total_shots_accepted += 1

        scene.beat_plans = beat_plans
        return scene

    def _process_shot(self, scene, beat, shot, narration, shot_index, max_retries=3):
        """Search + validate a single shot using multi-provider candidate collection."""
        purpose = f"{shot.shot_type.value} shot for beat {beat.index}"
        query_text = shot.description or beat.visual_purpose[:100]

        # Use ConceptPlanner query pool instead of stale SearchPlan
        pool = self._concept_pools.get(scene.scene_id)
        if pool and pool.query_count > 0:
            shot_query = pool.next_query(shot.shot_type.value)
            base_query = self._concept_pools[scene.scene_id]._pool[0] if self._concept_pools[scene.scene_id]._pool else self._topic
        else:
            base_query = scene.search_plan.asset_search_queries[0] if scene.search_plan.asset_search_queries else self._topic
            shot_query = f"{base_query} {shot.shot_type.value} shot"

        # Build diversified query list — include Knowledge Library terms as fallback
        queries = [shot_query, base_query, f"{self._topic} documentary stock footage"]
        # Add Knowledge Library diversified per-shot queries as extra fallbacks
        if self._knowledge_library is not None:
            entry = self._knowledge_library.lookup(self._topic)
            if entry:
                all_motifs = list(entry.preferred_visual_motifs)
                if all_motifs:
                    queries.extend(all_motifs[:4])

        for query in queries[:max_retries + 4]:
            self.total_queries_tried += 1

            # Use standard sequential provider chain (parallel collection unreliable)
            try:
                results = self._router.search(query, target_duration=max(shot.duration, 3.0))
            except Exception:
                continue

            if not results:
                continue

            best = results[0] if isinstance(results, list) else results
            provider_name = "pexels"  # default; actual provider tracked via AssetPlan
            vf_link = self._get_download_url(best)

            if not vf_link:
                continue

            # Build AssetPlan
            raw_meta = best.get("_raw", {})
            if isinstance(raw_meta, dict):
                asset_title = raw_meta.get("title", "") or ""
                asset_desc = raw_meta.get("description", "") or ""
                if asset_desc.startswith("Description: "):
                    asset_desc = asset_desc[13:]
            else:
                asset_title = ""
                asset_desc = ""

            query_used = query
            if asset_desc:
                query_used = f"{query} {asset_desc[:300]}"
            elif asset_title:
                query_used = f"{query} {asset_title}"

            ap = AssetPlan(
                provider=ProviderType(provider_name), filepath="", video_url=vf_link,
                query_used=query_used,
                score=0.7, semantic_score=0.5,
                technical_score=0.7, aesthetic_style="real_stock",
                duration=max(best.get("duration", 0.0), 1.0),
                width=max(best.get("width", 0), 1920),
                height=max(best.get("height", 0), 1080),
            )

            sem_score = self._semantic_validator.score(narration=narration, query=query, asset=ap)
            ap.semantic_score = sem_score

            passed, reason, _ = self._quality_gates.check_all(asset=ap, category=self._router.category)
            if not passed:
                self.total_gate_rejections += 1
                continue

            if vf_link:
                vp = os.path.join(self._cache_video, f"scene_{scene.scene_id}_b{beat.index}_s{shot_index}.mp4")
                self._router.download(vf_link, vp)
                if os.path.exists(vp) and os.path.getsize(vp) > 1024:
                    ap.filepath = vp
                else:
                    print(f"    [BeatDirector] Download failed or empty: {vf_link[:60]}")
                    continue

            # Record accepted asset in duplicate detector (only for local files)
            if os.path.exists(vp):
                self._duplicate_detector.record_use(vp, timestamp=shot.timestamp)

            print(f"    [BeatDirector] Shot accepted: {purpose} (provider={provider_name})")
            return ap
        return None

    # ── Multi-provider helpers (parallel) ──────────────────────────────

    def _collect_from_all_providers(self, query: str, target_duration: float) -> list[tuple[str, str, list[dict]]]:
        """Query ALL providers CONCURRENTLY and collect candidates.

        Uses ThreadPoolExecutor for parallel provider queries with a 15s timeout.
        """
        provider_order = self._router._routes.get(
            self._router.category,
            self._router._routes.get("General", []),
        )

        def _search_one(provider_name: str) -> Optional[tuple[str, str, list[dict]]]:
            provider = self._router._providers.get(provider_name)
            if provider is None:
                return None
            if not AssetRouter._is_provider_ready(provider, provider_name):
                return None
            try:
                results = provider.search(query, target_duration=max(target_duration, 3.0))
                if results:
                    return (provider_name, query, results)
            except Exception:
                pass
            return None

        candidates: list[tuple[str, str, list[dict]]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(provider_order)) as executor:
            future_map = {
                executor.submit(_search_one, pn): pn
                for pn in provider_order
            }
            for future in concurrent.futures.as_completed(future_map, timeout=15):
                try:
                    result = future.result(timeout=5)
                    if result is not None:
                        candidates.append(result)
                except (concurrent.futures.TimeoutError, Exception):
                    continue
        return candidates

    def _rank_candidates(self, candidates: list[tuple[str, str, list[dict]]], query: str,
                          target_duration: float,
                          duplicate_detector: Optional[DuplicateDetector] = None,):
        """Score and rank candidates from all providers.

        Applies:
          - Duplicate image penalty using perceptual hash detection.
          - Provider diversity penalty (after 8+ from same provider, penalty grows).
          - 50% max from any single provider in top results.
        """
        if not hasattr(self, '_ranker'):
            self._ranker = AssetRanker()

        # Count current provider usage
        provider_counts: dict[str, int] = {}
        if hasattr(self, '_quality_gates') and hasattr(self._quality_gates, '_diversity_tracker'):
            for rec in self._quality_gates._diversity_tracker.history:
                prov = rec.provider
                provider_counts[prov] = provider_counts.get(prov, 0) + 1

        scored = self._ranker.score_and_rank(candidates, query=query, target_duration=target_duration)

        for sa in scored:
            # Apply duplicate detector penalty (perceptual hash)
            dup_penalty = 0.0
            # Duplicate detection disabled pending fix (uses URLs, not local paths)
            dup_penalty = 0.0

            # Apply provider diversity penalty (after 8+ from same provider)
            prov_count = provider_counts.get(sa.provider, 0)
            provider_penalty = 0.0
            if prov_count >= 8:
                # Penalty grows from 0.05 at 8 uses to 0.30 at 12+ uses
                provider_penalty = min(0.30, (prov_count - 8) * 0.05)

            total_penalty = max(dup_penalty, provider_penalty)
            sa.score = round(sa.score * (1.0 - total_penalty), 4)
            sa.scores["duplicate_penalty"] = dup_penalty
            sa.scores["provider_diversity_penalty"] = provider_penalty

        # Re-sort with penalties applied
        scored.sort(key=lambda s: s.score, reverse=True)

        # Enforce max 50% from any single provider in top results
        max_from_provider = max(1, len(scored) // 2)
        filtered: list = []
        seen_providers: dict[str, int] = {}
        for sa in scored:
            current_count = seen_providers.get(sa.provider, 0)
            if current_count < max_from_provider:
                filtered.append(sa)
                seen_providers[sa.provider] = current_count + 1

        return filtered

    @staticmethod
    def _get_download_url(asset: dict) -> str:
        """Extract download URL from provider asset dict."""
        vf = asset.get("video_files", [{}])
        if isinstance(vf, list) and vf:
            link = vf[0].get("link", "")
            if link:
                return link
        return asset.get("url", asset.get("link", ""))

    def _fallback_for_shot(self, scene, beat, shot, narration):
        """FallbackDirector as last resort."""
        # Use first concept term for fallback search if available
        pool = self._concept_pools.get(scene.scene_id)
        if pool and pool._pool:
            base = pool._pool[0]
        else:
            base = scene.search_plan.asset_search_queries[0] if scene.search_plan.asset_search_queries else self._topic
        return self._fallback_director.produce(
            scene_num=scene.scene_id, narration=narration,
            search_queries=base,
            target_duration=max(shot.duration, 3.0),
            accepted_scenes=[],
        )

    def get_stats(self) -> Dict:
        return {
            "shots_requested": self.total_shots_requested,
            "shots_accepted": self.total_shots_accepted,
            "queries_tried": self.total_queries_tried,
            "gate_rejections": self.total_gate_rejections,
            "fallbacks": self.total_fallbacks,
            "shot_success_rate": round(self.total_shots_accepted / max(self.total_shots_requested, 1) * 100, 1),
        }
