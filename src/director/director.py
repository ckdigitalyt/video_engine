"""
director.py — VisualDirector: Closed-loop, self-correcting pipeline orchestrator.

The VisualDirector replaces the execution_node's linear retrieval with a
director-driven loop.  For each scene:

1. ConceptPlanner generates 5-10 concept-driven visual queries
2. AssetRouter searches providers for each query
3. SemanticValidator scores candidate relevance (threshold 0.75)
4. AestheticAgent checks style consistency
5. QualityGates enforce all hard gates
6. IF any gate fails → retry with next query/provider
7. IF all queries exhausted → regenerate scene narration via planner
8. IF max retries reached → fall back to best available (with warning)

Only after ALL quality gates pass does the director move to the next scene.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from src.assets.asset_router import AssetRouter
from src.providers.llm_provider import LLMProvider
from src.planner import StoryPlanner
from src.utils.config import get_config
from src.utils.duration import ensure_video_duration, get_media_duration
from src.validation.semantic_validator import SemanticValidator
from src.director.visual_style import VisualStyle
from src.director.concept_planner import ConceptPlanner
from src.director.aesthetic_agent import AestheticAgent
from src.director.quality_gate import QualityGates
from audio_engine import generate_voice


class VisualDirector:
    """Closed-loop Visual Director that manages the entire asset pipeline.

    Parameters
    ----------
    topic : str
        The video topic string.
    llm_provider : LLMProvider | None
        LLM used for concept planning and semantic validation.
    scene_data : list[dict]
        Scene data from the StoryPlanner (scenes list).
    """

    def __init__(
        self,
        topic: str,
        llm_provider: Optional[LLMProvider] = None,
        scene_data: Optional[list[dict]] = None,
    ):
        self._topic = topic
        self._llm_provider = llm_provider
        self._scene_data = scene_data or []
        self._cache_video = get_config("pipeline.cache.video", "cache/video")
        self._cache_audio = get_config("pipeline.cache.audio", "cache/audio")
        self._fallback_video = get_config("pipeline.fallback.video", "cache/video/test_clip.mp4")

        # ── Create the Visual Style ────────────────────────────────────
        self._router = AssetRouter.for_topic(topic)
        self._style = VisualStyle.for_topic(topic, self._router.category)

        # ── Component stack ────────────────────────────────────────────
        self._concept_planner = ConceptPlanner(
            provider=llm_provider,
            visual_style=self._style,
        )
        self._semantic_validator = SemanticValidator(
            provider=llm_provider,
            enabled=True,
            threshold=get_config("visual_director.quality_gates.semantic_threshold", 0.75),
        )
        self._aesthetic_agent = AestheticAgent(visual_style=self._style)
        self._quality_gates = QualityGates(
            visual_style=self._style,
            aesthetic_agent=self._aesthetic_agent,
            semantic_threshold=self._semantic_validator._threshold,
        )

        # Overall tracking
        self._results: dict[str, Any] = {
            "scene_results": [],
            "total_queries_tried": 0,
            "total_scene_regenerations": 0,
            "total_gate_rejections": 0,
            "total_fallbacks": 0,
        }

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def style(self) -> VisualStyle:
        return self._style

    @property
    def router(self) -> AssetRouter:
        return self._router

    @property
    def results(self) -> dict:
        return self._results

    def run(self) -> list[dict]:
        """Execute the closed-loop director pipeline for all scenes.

        Returns a list of scene asset dicts with keys:
            scene_id, video_path, audio_path, narration, provider, query,
            semantic_score, aesthetic_style
        """
        scene_assets: list[dict] = []

        print(f"\n{'='*60}")
        print(f"  Visual Director: {self._style.describe()}")
        print(f"  Topic: {self._topic}")
        print(f"{'='*60}\n")

        for scene_data in self._scene_data:
            scene_id = scene_data["scene_id"]
            narration = scene_data["narration"]
            search_query = scene_data.get("search_query", "")
            scene_title = scene_data.get("scene_title", "")
            purpose = scene_data.get("purpose", "general")

            print(f"\n{'─'*50}")
            print(f"  Scene {scene_id}: {scene_title or search_query}")
            print(f"{'─'*50}")

            result = self._process_scene(
                scene_id=scene_id,
                narration=narration,
                search_query=search_query,
                scene_title=scene_title,
                purpose=purpose,
                target_duration=scene_data.get("estimated_duration"),
            )

            self._results["scene_results"].append(result)
            scene_assets.append(result)

        print(f"\n{'='*50}")
        print(f"  Director Results:")
        print(f"    Queries tried: {self._results['total_queries_tried']}")
        print(f"    Gate rejections: {self._results['total_gate_rejections']}")
        print(f"    Scene regenerations: {self._results['total_scene_regenerations']}")
        print(f"    Fallbacks: {self._results['total_fallbacks']}")
        print(f"{'='*50}\n")

        return scene_assets

    # ── Single scene processing ────────────────────────────────────────

    def _process_scene(
        self,
        scene_id: int,
        narration: str,
        search_query: str,
        scene_title: str = "",
        purpose: str = "general",
        target_duration: Optional[float] = None,
    ) -> dict:
        """Process a single scene with full retry loop.

        Returns a result dict with all metadata about the selected asset.
        """
        max_retries = get_config("visual_director.max_retries_per_scene", 3)
        max_regenerations = get_config("visual_director.max_scene_regenerations", 2)

        current_narration = narration
        current_query = search_query
        attempts = 0

        for regeneration in range(max_regenerations + 1):
            # Generate concept-driven queries
            queries = self._concept_planner.generate_queries(
                narration=current_narration,
                title=scene_title,
                topic=self._topic,
                purpose=purpose,
            )

            # If no concept queries, prepend the original search query
            if not queries or all(q in ("", "stock footage") for q in queries):
                queries = [current_query] if current_query else ["stock footage"]

            queries = queries[:get_config("search_planner.num_queries", 7)]

            print(f"    Generated {len(queries)} visual concepts")

            for query_idx, query in enumerate(queries):
                if attempts >= max_retries * (regeneration + 1):
                    print(f"    -> Max retries reached for scene {scene_id}")
                    break

                attempts += 1
                self._results["total_queries_tried"] += 1

                # ── Search via AssetRouter ─────────────────────────────
                print(f"    Attempt {attempts}: '{query}'")
                try:
                    mq_result = self._router.multi_query_search(
                        [query],
                        min_acceptable_score=0.0,
                        max_attempts=3,
                        diversity_weighting=0.2,
                        target_duration=target_duration,
                    )
                except Exception as e:
                    print(f"    -> Search error: {e}")
                    continue

                videos = mq_result.get("assets", [])
                selected_query = mq_result.get("selected_query", query)
                selected_provider = mq_result.get("provider_name", "")
                technical_score = mq_result.get("selected_score", -1.0)

                if not videos:
                    print(f"    -> No assets found for '{query}'")
                    continue

                best_asset = videos[0]

                # ── Semantic Validation ────────────────────────────────
                sem_score = self._semantic_validator.score(
                    narration=current_narration,
                    query=selected_query,
                    asset=best_asset,
                )
                print(f"    Semantic score: {sem_score:.3f} (threshold: {self._semantic_validator._threshold})")

                # ── Quality Gates ──────────────────────────────────────
                gate_passed, gate_reason, gate_details = self._quality_gates.check_all(
                    asset=best_asset,
                    provider=selected_provider,
                    query=selected_query,
                    category=self._router.category,
                    semantic_score=sem_score,
                )

                # Log per-gate details
                for gate_name, detail in gate_details.items():
                    status = "\u2713" if detail["passed"] else "\u2717"
                    print(f"    Gate {status} {gate_name}: {detail['reason']}")

                if not gate_passed:
                    self._results["total_gate_rejections"] += 1
                    print(f"    -> REJECTED by quality gates: {gate_reason}")
                    continue

                # ── ALL GATES PASSED ──────────────────────────────────
                print(f"    -> ACCEPTED: provider={selected_provider}, query='{selected_query}'")
                print(f"    -> Technical score={technical_score:.3f}, semantic={sem_score:.3f}")

                # Download
                video_path = f"{self._cache_video}/scene_{scene_id}.mp4"
                audio_path = f"{self._cache_audio}/scene_{scene_id}.wav"

                video_url = best_asset["video_files"][0]["link"]
                self._router.download(video_url, video_path)

                # Generate voiceover
                print(f"    Generating voiceover...")
                generate_voice(current_narration, audio_path)

                # Duration verification
                audio_dur = get_media_duration(audio_path)
                if audio_dur > 0 and os.path.exists(video_path):
                    adjusted_path = ensure_video_duration(
                        video_path, audio_dur,
                        output_path=video_path.replace(".mp4", "_dur.mp4"),
                    )
                    if adjusted_path != video_path and os.path.exists(adjusted_path):
                        os.replace(adjusted_path, video_path)

                # Determine aesthetic style from the agent's history
                aesthetic_styles = self._aesthetic_agent.history
                current_style = aesthetic_styles[-1] if aesthetic_styles else "real_stock"

                return {
                    "scene_id": scene_id,
                    "video_path": video_path,
                    "audio_path": audio_path,
                    "narration": current_narration,
                    "provider": selected_provider,
                    "query": selected_query,
                    "technical_score": technical_score,
                    "semantic_score": sem_score,
                    "aesthetic_style": current_style,
                    "video_url": video_url,
                }

            # ── All queries exhausted for this regeneration ────────────
            if regeneration < max_regenerations:
                # Regenerate scene narration
                print(f"    -> All queries exhausted. Regenerating narration (attempt {regeneration + 1})...")
                self._results["total_scene_regenerations"] += 1
                new_narration = self._regenerate_narration(scene_id, current_narration)
                if new_narration and new_narration != current_narration:
                    current_narration = new_narration
                    print(f"    New narration: {current_narration[:100]}...")
                    continue

        # ── ALL ATTEMPTS EXHAUSTED — fall back ────────────────────────
        self._results["total_fallbacks"] += 1
        print(f"    -> WARNING: All attempts exhausted for scene {scene_id}. Using fallback.")

        video_path = self._fallback_video
        audio_path = f"{self._cache_audio}/scene_{scene_id}.wav"
        generate_voice(current_narration, audio_path)

        return {
            "scene_id": scene_id,
            "video_path": video_path,
            "audio_path": audio_path,
            "narration": current_narration,
            "provider": "fallback",
            "query": "",
            "technical_score": 0.0,
            "semantic_score": 0.0,
            "aesthetic_style": "fallback",
            "video_url": "",
        }

    # ── Narration regeneration ─────────────────────────────────────────

    def _regenerate_narration(self, scene_id: int, current_narration: str) -> Optional[str]:
        """Use the LLM to regenerate a scene's narration to match
        available assets better.

        Returns the new narration string, or *None* if regeneration fails.
        """
        if not self._llm_provider:
            return None

        prompt = (
            f"You are a documentary scriptwriter. The current scene narration "
            f"is semantically difficult to find stock footage for. "
            f"Rewrite the following narration to be more visually descriptive "
            f"while keeping the same factual content. "
            f"Add concrete, visual, searchable elements. "
            f"Keep the length approximately the same.\n\n"
            f"Current narration:\n{current_narration}\n\n"
            f"Rewritten narration (return ONLY the new text, no quotes):"
        )
        try:
            new_text = self._llm_provider.generate_text(prompt).strip()
            if len(new_text) > 20:
                return new_text
        except Exception as e:
            print(f"    -> Narration regeneration failed: {e}")

        return None
