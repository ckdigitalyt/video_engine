"""
director_integration.py — Bridges the Cinematic TimelineBuilder into the
VisualDirector pipeline.  When beat mode is enabled, each scene's narration
is split into semantic beats, and each beat gets its own asset search +
quality gate loop.

This replaces the old single-clip-per-scene flow with beat-based editing.
"""

from typing import List, Optional, Dict, Any
import os

from src.cinematic.beat_planner import TimelineBuilder as BeatTimelineBuilder
from src.models import BeatPlan, ShotPlan, ShotType, Scene
from src.models.schemas import (
    AssetPlan, CameraMotion, TransitionType, ProviderType,
)
from src.assets import AssetRouter
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
        beat_plans = self._beat_timeline_builder.build_timeline(narration, duration, topic)
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
        if not raw_terms or all(q in ("", "stock footage") for q in raw_terms):
            # Fallback to topic-based terms
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
        """Search + validate a single shot."""
        purpose = f"{shot.shot_type.value} shot for beat {beat.index}"
        query_text = shot.description or beat.visual_purpose[:100]

        # Use ConceptPlanner query pool instead of stale SearchPlan
        pool = self._concept_pools.get(scene.scene_id)
        if pool and pool.query_count > 0:
            shot_query = pool.next_query(shot.shot_type.value)
            base_query = self._concept_pools[scene.scene_id]._pool[0] if self._concept_pools[scene.scene_id]._pool else self._topic
        else:
            # Fallback: use scene's search plan or topic
            base_query = scene.search_plan.asset_search_queries[0] if scene.search_plan.asset_search_queries else self._topic
            shot_query = f"{base_query} {shot.shot_type.value} shot"

        queries = [shot_query, base_query, f"{self._topic} documentary stock footage"]

        for query in queries[:max_retries]:
            self.total_queries_tried += 1
            try:
                mq_result = self._router.multi_query_search(
                    [query], min_acceptable_score=0.0, max_attempts=1,
                    diversity_weighting=0.15, target_duration=max(shot.duration, 3.0),
                )
            except Exception as e:
                continue

            videos = mq_result.get("assets", [])
            sq = mq_result.get("selected_query", query)
            sp = mq_result.get("provider_name", "")
            ts = mq_result.get("selected_score", -1.0)
            if not videos:
                continue

            best = videos[0]
            vf = best.get("video_files", [{}])
            vf_link = vf[0].get("link", "") if isinstance(vf, list) and vf else ""

            # Include NASA/Wikimedia metadata in query_used for better semantic scoring
            raw_meta = best.get("_raw", {})
            if isinstance(raw_meta, dict):
                asset_title = raw_meta.get("title", "") or ""
                asset_desc = raw_meta.get("description", "") or ""
                # Strip "Description: " prefix that NASA prepends
                if asset_desc.startswith("Description: "):
                    asset_desc = asset_desc[13:]
            else:
                asset_title = ""
                asset_desc = ""

            query_text = str(sq[0] if isinstance(sq, list) else sq)
            if asset_desc:
                query_text = f"{query_text} {asset_desc[:300]}"
            elif asset_title:
                query_text = f"{query_text} {asset_title}"

            ap = AssetPlan(
                provider=ProviderType(sp), filepath="", video_url=vf_link,
                query_used=query_text,
                score=max(ts, 0.5), semantic_score=0.5,
                technical_score=max(ts, 0.5), aesthetic_style="real_stock",
                duration=best.get("duration", 0.0),
                width=best.get("width", 0),
                height=best.get("height", 0),
            )

            sem_score = self._semantic_validator.score(narration=narration, query=str(sq), asset=ap)
            ap.semantic_score = sem_score

            passed, reason, _ = self._quality_gates.check_all(asset=ap, category=self._router.category)
            if not passed:
                self.total_gate_rejections += 1
                continue

            if vf_link:
                vp = os.path.join(self._cache_video, f"scene_{scene.scene_id}_b{beat.index}_s{shot_index}.mp4")
                self._router.download(vf_link, vp)
                ap.filepath = vp

            print(f"    [BeatDirector] Shot accepted: {purpose}")
            return ap
        return None

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

    def get_stats(self) -> Dict:
        return {
            "shots_requested": self.total_shots_requested,
            "shots_accepted": self.total_shots_accepted,
            "queries_tried": self.total_queries_tried,
            "gate_rejections": self.total_gate_rejections,
            "fallbacks": self.total_fallbacks,
            "shot_success_rate": round(self.total_shots_accepted / max(self.total_shots_requested, 1) * 100, 1),
        }
