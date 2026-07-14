#!/usr/bin/env python3
"""
Investigation #3: Instrument Scene 0, Beat 0, Shot 1 through the
entire primary pipeline with 8 checkpoints.

Captures every step from provider search through quality gates
to FallbackDirector (or success).

Do NOT modify any production code — monkey-patch only.
"""

import os, sys, json, time, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOG_PATH = "docs/investigations/investigation3_trace.log"
os.makedirs("docs/investigations", exist_ok=True)
_log_file = None


def log(msg):
    global _log_file
    ts = time.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    line = f"[{ts}] {msg}"
    print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def log_checkpoint(num, data):
    log(f"\n{'='*70}")
    log(f"  CHECKPOINT {num}")
    log(f"{'='*70}")
    if isinstance(data, str):
        log(f"  {data}")
    elif isinstance(data, dict):
        for k, v in data.items():
            log(f"  {k}: {v}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            log(f"  [{i}] {item}")
    else:
        log(f"  {data}")
    log("")


# ── Speed up by reducing socket timeouts ────────────────────────────
import socket
socket.setdefaulttimeout(8)

# ── Tracking vars per shot ──────────────────────────────────────────
_shot_trace = {}
_target_scene = 0
_target_beat = 0
_target_shot = 1  # Scene 0, Beat 0, Shot 1 (the first "failed" shot)


def is_target(scene_id, beat_id, shot_id):
    """True only for our one representative shot."""
    return (scene_id == _target_scene and
            beat_id == _target_beat and
            shot_id == _target_shot)


# =====================================================================
# Monkey-patch AssetRouter.multi_query_search  — CHECKPOINT 1
# =====================================================================
import src.assets.asset_router as ar_module
_original_mqs = ar_module.AssetRouter.multi_query_search


def _instrumented_mqs(self, queries, **kwargs):
    # Call original first so we can capture
    result = _original_mqs(self, queries, **kwargs)

    # We can't know which shot triggered this call here, so we
    # capture the last call and log in _process_shot
    _shot_trace["last_mqs_result"] = result
    return result


ar_module.AssetRouter.multi_query_search = _instrumented_mqs


# =====================================================================
# Monkey-patch AssetRouter.search  — provides provider-level logs
# =====================================================================
_original_search = ar_module.AssetRouter.search


def _instrumented_search(self, query, **kwargs):
    # Log per-provider attempt before the call
    provider_order = self._routes.get(self._category, self._routes.get("General", []))
    provider_log = []
    for pname in provider_order:
        provider = self._providers.get(pname)
        if provider is None:
            continue
        if not self._is_provider_ready(provider, pname):
            provider_log.append({"provider": pname, "status": "skipped"})
            continue
        provider_log.append({"provider": pname, "status": "will_try"})

    result = _original_search(self, query, **kwargs)
    _shot_trace["last_search_results"] = {
        "query": query,
        "provider_order": provider_order,
        "returned_count": len(result),
        "chosen_provider": self._last_provider_name,
    }
    return result


ar_module.AssetRouter.search = _instrumented_search


# =====================================================================
# Monkey-patch VolumeDirector._process_shot — THE MAIN INSTRUMENTATION
# =====================================================================
import src.cinematic.director_integration as di_module

_original_process_shot = di_module.BeatDirector._process_shot


def _instrumented_process_shot(self, scene, beat, shot, narration, shot_index, max_retries=3):
    if not is_target(scene.scene_id, beat.index, shot_index):
        # Not our target shot — pass through normally but still log fallback
        result = _original_process_shot(self, scene, beat, shot, narration, shot_index, max_retries)
        if result is not None:
            log(f"[Shot {scene.scene_id}/{beat.index}/{shot_index}] → SKIPPED (not target) | result={result.filepath}")
        return result

    log(f"\n{'#'*70}")
    log(f"  ### INVESTIGATION TARGET: Scene {scene.scene_id}, Beat {beat.index}, Shot {shot_index} ###")
    log(f"{'#'*70}")
    log(f"  Shot type: {shot.shot_type.value}")
    log(f"  Shot description: {shot.description}")
    log(f"  Shot duration: {shot.duration}s")
    log(f"\n")

    # ── Build queries (same logic as original _process_shot) ──────────
    purpose = f"{shot.shot_type.value} shot for beat {beat.index}"
    query_text = shot.description or beat.visual_purpose[:100]

    visual_intent = getattr(scene, 'visual_intent', None)
    if visual_intent and (visual_intent.search_terms or visual_intent.concepts):
        from src.assets.query_expander import expand_for_shot
        queries = expand_for_shot(
            base_query=visual_intent.search_terms[0] if visual_intent.search_terms else self._topic,
            shot_type=shot.shot_type.value,
            topic=self._topic,
            category=getattr(self._router, 'category', 'General'),
        )
    else:
        base_query = scene.search_plan.asset_search_queries[0] if scene.search_plan.asset_search_queries else self._topic
        queries = [
            f"{base_query} {shot.shot_type.value} shot",
            base_query,
            f"{self._topic} documentary stock footage",
        ]
    log(f"  Queries to try: {queries}")

    # ── Provider chain for this shot ──────────────────────────────────
    provider_order = self._router._routes.get(
        self._router._category, self._router._routes.get("General", [])
    )
    log(f"  Provider order for category '{self._router._category}': {provider_order}")
    log(f"\n")

    for query_idx, query in enumerate(queries[:max_retries]):
        self.total_queries_tried += 1
        log(f"  --- Attempt {query_idx+1}: query='{query}' ---")

        # ── CHECKPOINT 1: Provider search ────────────────────────────
        try:
            mq_result = self._router.multi_query_search(
                [query], min_acceptable_score=0.0, max_attempts=1,
                diversity_weighting=0.15, target_duration=max(shot.duration, 3.0),
            )
        except Exception as e:
            log(f"  [CHECKPOINT 1] multi_query_search EXCEPTION: {e}")
            continue

        videos = mq_result.get("assets", [])
        selected_query = mq_result.get("selected_query", query)
        selected_provider = mq_result.get("provider_name", "")
        selected_score = mq_result.get("selected_score", -1.0)

        # Discover which provider was actually used from the query_log
        query_log = mq_result.get("query_log", [])
        provider_used = selected_provider
        provider_http = "?"
        provider_count = len(videos)

        log_checkpoint(1, {
            "provider": provider_used or "none",
            "search_query": query,
            "HTTP status": "200 (assumed from provider libs)",
            "number_of_candidates_returned": provider_count,
            "all_video_ids": [v.get("id", f"idx_{i}") for i, v in enumerate(videos)],
            "provider_order_tried": provider_order,
        })

        if not videos:
            log(f"  -> No candidates returned for '{query}'")
            log_checkpoint(2, {
                "candidate_IDs": "[]",
                "candidate_scores": "[]",
                "selected_candidate_ID": "N/A",
                "rejection_reason": "No assets returned from provider search",
            })
            continue

        best = videos[0]

        # ── CHECKPOINT 2: After candidate scoring ────────────────────
        # Capture candidate IDs and their scores
        candidate_ids = []
        candidate_scores = []
        for v in videos:
            vid = v.get("id", "unknown")
            w = v.get("width", 0)
            h = v.get("height", 0)
            dur = v.get("duration", 0)
            # Approximate raw score from top-level fields
            candidate_ids.append(vid)
            candidate_scores.append({
                "id": vid,
                "width": w,
                "height": h,
                "duration": dur,
                "score_approx": selected_score if v is best else "unknown",
            })

        selected_id = best.get("id", "unknown")
        log_checkpoint(2, {
            "candidate_IDs": candidate_ids,
            "candidate_scores": json.dumps(candidate_scores, default=str),
            "selected_candidate_ID": selected_id,
            "rejection_reason": "N/A (candidate selected)",
        })

        # ── Extract vf_link — CHECKPOINT 3 ────────────────────────────
        vf = best.get("video_files", [{}])
        vf_link = vf[0].get("link", "") if isinstance(vf, list) and vf else ""
        vf_count = len(vf) if isinstance(vf, list) else 0

        log_checkpoint(3, {
            "selected_candidate_ID": selected_id,
            "video_files_count": vf_count,
            "extracted_vf_link": vf_link[:120] + ("..." if len(vf_link) > 120 else ""),
            "vf_link_is_empty": str(vf_link == ""),
        })

        if not vf_link:
            log(f"  -> vf_link is EMPTY — skipping download")
            log_checkpoint(4, {
                "download_URL": "EMPTY — skipped",
                "destination_path": "N/A",
            })
            log_checkpoint(5, {
                "download_success": False,
                "file_exists": False,
                "file_size": 0,
                "any_exception": "vf_link was empty, skip download",
            })
            continue

        # ── Build AssetPlan (same logic as original) ──────────────────
        raw_meta = best.get("_raw", {})
        if isinstance(raw_meta, dict):
            asset_title = raw_meta.get("title", "") or ""
            asset_desc = raw_meta.get("description", "") or ""
            if asset_desc.startswith("Description: "):
                asset_desc = asset_desc[13:]
        else:
            asset_title = ""
            asset_desc = ""

        query_text_for_score = str(selected_query[0] if isinstance(selected_query, list) else selected_query)
        if asset_desc:
            query_text_for_score = f"{query_text_for_score} {asset_desc[:300]}"
        elif asset_title:
            query_text_for_score = f"{query_text_for_score} {asset_title}"

        from src.models.schemas import AssetPlan, ProviderType

        ap = AssetPlan(
            provider=ProviderType(selected_provider),
            filepath="",
            video_url=vf_link,
            query_used=query_text_for_score,
            score=max(selected_score, 0.5),
            semantic_score=0.5,
            technical_score=max(selected_score, 0.5),
            aesthetic_style="real_stock",
            duration=max(best.get("duration", 0.0), 1.0),
            width=max(best.get("width", 0), 1920),
            height=max(best.get("height", 0), 1080),
        )

        # ── Semantic validation ──────────────────────────────────────
        sem_score = self._semantic_validator.score(
            narration=narration, query=str(selected_query), asset=ap,
        )
        ap.semantic_score = sem_score
        log(f"  Semantic score: {sem_score:.4f} (threshold: {self._semantic_validator._threshold})")

        # ── Asset ID for diversity tracking ───────────────────────────
        asset_id = ""
        if selected_provider == "nasa":
            asset_id = best.get("id", "") if isinstance(best, dict) else ""
        elif selected_provider in ("pexels", "pixabay"):
            asset_id = str(best.get("id", "")) if isinstance(best, dict) else ""

        # ── Quality Gates — CHECKPOINT 6 (pre-gate check) ────────────
        vp = os.path.join(
            self._cache_video,
            f"scene_{scene.scene_id}_b{beat.index}_s{shot_index}.mp4",
        )

        log_checkpoint(4, {
            "download_URL": vf_link[:120] + ("..." if len(vf_link) > 120 else ""),
            "destination_path": vp,
        })

        # ── Download — CHECKPOINT 5 ──────────────────────────────────
        try:
            self._router.download(vf_link, vp)
            download_success = os.path.isfile(vp) and os.path.getsize(vp) > 0
        except Exception as e:
            download_success = False
            log(f"  Download EXCEPTION: {e}")
            log_checkpoint(5, {
                "download_success": False,
                "file_exists": os.path.isfile(vp) if os.path.exists(os.path.dirname(vp)) else False,
                "file_size": os.path.getsize(vp) if os.path.isfile(vp) else 0,
                "any_exception": str(e),
            })
            continue

        file_size = os.path.getsize(vp) if os.path.isfile(vp) else 0
        log_checkpoint(5, {
            "download_success": download_success,
            "file_exists": os.path.isfile(vp),
            "file_size": file_size,
            "any_exception": "None",
        })

        if not download_success:
            log(f"  -> Download returned but file missing or empty")
            continue

        # ── Quality Gates — CHECKPOINT 6 ─────────────────────────────
        ap.filepath = vp
        passed, reason, gate_details = self._quality_gates.check_all(
            asset=ap,
            category=self._router.category,
            provider=selected_provider,
            asset_id=asset_id,
        )

        import subprocess as _sp
        dur_result = _sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", vp],
            capture_output=True, text=True, timeout=10,
        )
        actual_duration = float(dur_result.stdout.strip() or 0)
        res_result = _sp.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", vp],
            capture_output=True, text=True, timeout=10,
        )
        resolution = res_result.stdout.strip() or "unknown"

        log_checkpoint(6, {
            "filepath": vp,
            "duration": f"{actual_duration:.2f}s",
            "resolution": resolution,
            "gate_decision": "PASSED" if passed else "REJECTED",
            "exact_rejection_reason": reason if not passed else "N/A",
            "gate_details": json.dumps(gate_details, default=str),
        })

        if not passed:
            self.total_gate_rejections += 1
            log(f"  -> REJECTED by quality gates: {reason}")
            # Clean up downloaded file since it was rejected
            if os.path.isfile(vp):
                os.remove(vp)
                log(f"  -> Deleted rejected file: {vp}")
            continue

        # ── ALL GATES PASSED ─────────────────────────────────────────
        log(f"  -> ALL GATES PASSED ✅")
        log(f"  -> Provider: {selected_provider}, Query: {query}")
        log(f"  -> Technical score: {selected_score:.3f}, Semantic: {sem_score:.3f}")
        log(f"  -> Downloaded to: {vp}")

        ap.filepath = vp
        print(f"    [BeatDirector] Shot accepted: {purpose}")
        return ap

    # ── All queries exhausted — record fallback reason ────────────────
    log(f"\n  -> All {len(queries)} queries exhausted for shot {scene.scene_id}/{beat.index}/{shot_index}")

    # CHECKPOINT 7: Precise reason why primary pipeline failed
    fallback_reasons = []
    try:
        mq_has_assets = mq_result and mq_result.get("assets")
    except NameError:
        mq_has_assets = False
    try:
        dl_ok = download_success
    except NameError:
        dl_ok = False
    try:
        gates_passed = passed
        gates_reason = reason
    except NameError:
        gates_passed = False
        gates_reason = "never reached gates"

    if not mq_has_assets:
        fallback_reasons.append("No assets returned by any provider for any query")
    elif not dl_ok:
        fallback_reasons.append("Download of selected asset failed")
    elif not gates_passed:
        fallback_reasons.append(f"Quality gates rejected: {gates_reason}")
    else:
        fallback_reasons.append("Unknown — check individual checkpoint logs above")

    log_checkpoint(7, {
        "precise_reason_primary_pipeline_failed": "; ".join(fallback_reasons),
        "queries_tried": str(queries),
    })

    # Set flag so fallback handler knows this is our target shot falling back
    _shot_trace["in_fallback_for_target"] = True

    return None


di_module.BeatDirector._process_shot = _instrumented_process_shot


# =====================================================================
# Monkey-patch _fallback_for_shot — CHECKPOINT 8
# =====================================================================
_original_fallback_shot = di_module.BeatDirector._fallback_for_shot


def _instrumented_fallback_shot(self, scene, beat, shot, narration):
    result = _original_fallback_shot(self, scene, beat, shot, narration)

    # shot index isn't passed here, so we rely on context
    # We track via a flag set by _process_shot
    if _shot_trace.get("in_fallback_for_target"):
        fb_type = "unknown"
        fb_path = ""
        fb_exists = False
        fb_size = 0
        if result:
            fb_type = result.provider.value if hasattr(result, 'provider') else "fallback"
            fb_path = result.filepath or ""
            fb_exists = os.path.isfile(fb_path) if fb_path else False
            fb_size = os.path.getsize(fb_path) if fb_exists else 0

        log_checkpoint(8, {
            "fallback_type": fb_type,
            "output_path": fb_path,
            "file_exists": fb_exists,
            "file_size": fb_size,
        })
        # Clear the flag so we don't re-log on other fallbacks
        _shot_trace["in_fallback_for_target"] = False
    else:
        log(f"[Fallback] Scene {scene.scene_id}, Beat {beat.index} — non-target shot got fallback: type={result.provider.value if result else 'None'}")

    return result


di_module.BeatDirector._fallback_for_shot = _instrumented_fallback_shot


# Set a flag when we're about to fallback for the target
_original_process_scene_beats = di_module.BeatDirector.process_scene_beats

def _instrumented_process_scene_beats(self, scene, max_retries_per_shot=3):
    result = _original_process_scene_beats(self, scene, max_retries_per_shot)
    if scene.scene_id == 0:
        # Log beat/shot structure
        if scene.beat_plans:
            for bi, bp in enumerate(scene.beat_plans):
                for si, s in enumerate(bp.shots):
                    if s.asset_plan:
                        log(f"[post-process] Scene 0, Beat {bi}, Shot {si}: filepath='{s.asset_plan.filepath}'")
                    else:
                        log(f"[post-process] Scene 0, Beat {bi}, Shot {si}: NO ASSET PLAN (will get fallback)")
    return result

di_module.BeatDirector.process_scene_beats = _instrumented_process_scene_beats


if __name__ == "__main__":
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_PATH)
    _log_file = open(log_path, "w")
    _log_file.write(f"Investigation #3 trace: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
    _log_file.write(f"Target: Scene 0, Beat 0, Shot 1\n")
    _log_file.write("=" * 70 + "\n")
    _log_file.flush()

    log("Starting Investigation #3 — instrumented pipeline")
    log(f"Target: Scene {_target_scene}, Beat {_target_beat}, Shot {_target_shot}")

    import socket
    socket.setdefaulttimeout(8)

    sys.argv = [sys.argv[0], "--topic", "The Fermi Paradox"]

    from dotenv import load_dotenv
    load_dotenv()

    if not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = "placeholder"

    try:
        from orchestrator import app, AgentState

        initial_state = {
            "topic": "The Fermi Paradox",
            "output_path": "final_output.mp4",
            "plan_json": "",
            "scenes_json": "",
            "timeline_json": "",
            "iteration": 0,
            "approved": False,
            "critic_result": "",
            "subtitle_timeline": [],
        }

        log("Invoking pipeline...")
        result_state = app.invoke(initial_state)
        log("Pipeline completed.")
    except Exception as e:
        log(f"PIPELINE EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _log_file.close()
        print(f"\nInvestigation #3 trace saved to: {log_path}")
