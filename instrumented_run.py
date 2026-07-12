#!/usr/bin/env python3
"""
Instrumented pipeline runner — captures filepath state at every checkpoint
for Scene 0, Shot 0. Fast execution with aggressive timeouts on API calls.
"""
import os, sys, json, time, signal, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOG_PATH = "docs/investigations/runtime-trace.log"
os.makedirs("docs/investigations", exist_ok=True)
_log_file = None

def log(msg):
    global _log_file
    ts = time.strftime("%H:%M:%S.%f")[:12]
    line = f"[{ts}] {msg}"
    print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()

def log_checkpoint(label, data):
    log(f"=== CHECKPOINT {label} ===")
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

# ── Speed up NASA API by reducing timeout ──────────────────────────────
import socket
socket.setdefaulttimeout(5)

# ── Monkey-patch AssetRouter search to skip slow NASA searches ────────
# We don't need full search — we need the CHECKPOINT data.
# Let the first NASA call through then fail fast.

# ── Monkey-patch BeatDirector._process_shot for CHECKPOINT A ──────────
import src.cinematic.director_integration as di_module
_original_process_shot = di_module.BeatDirector._process_shot

def _instrumented_process_shot(self, scene, beat, shot, narration, shot_index, max_retries=3):
    result = _original_process_shot(self, scene, beat, shot, narration, shot_index, max_retries)
    cp_data = {
        "scene_id": scene.scene_id,
        "beat_id": beat.index,
        "shot_id": shot_index,
        "has_result": result is not None,
    }
    if result is not None:
        cp_data["asset_plan.filepath"] = result.filepath
        cp_data["asset_plan.video_url"] = result.video_url
        if result.filepath:
            cp_data["file_exists"] = os.path.isfile(result.filepath)
            cp_data["file_size"] = os.path.getsize(result.filepath) if os.path.isfile(result.filepath) else 0
        else:
            cp_data["file_exists"] = False
            cp_data["file_size"] = 0
    log_checkpoint("A (after _process_shot returns)", cp_data)
    return result

di_module.BeatDirector._process_shot = _instrumented_process_shot

# ── Monkey-patch Process_scene_beats post-loop for fallback tracking ──
_original_process_scene_beats = di_module.BeatDirector.process_scene_beats

def _instrumented_process_scene_beats(self, scene, max_retries_per_shot=3):
    result = _original_process_scene_beats(self, scene, max_retries_per_shot)
    if scene.scene_id == 0:
        log_checkpoint("A1 (after process_scene_beats for Scene 0)", {
            "scene_id": scene.scene_id,
            "beat_plans_count": len(scene.beat_plans) if scene.beat_plans else 0,
        })
        if scene.beat_plans:
            for bi, bp in enumerate(scene.beat_plans):
                for si, s in enumerate(bp.shots):
                    if s.asset_plan:
                        log(f"  Beat {bi}, Shot {si}: filepath='{s.asset_plan.filepath}' exists={os.path.isfile(s.asset_plan.filepath)}")
                    else:
                        log(f"  Beat {bi}, Shot {si}: NO ASSET PLAN (asset_plan is None)")
    return result

di_module.BeatDirector.process_scene_beats = _instrumented_process_scene_beats

# ── Monkey-patch _fallback_for_shot ───────────────────────────────────
_original_fallback_shot = di_module.BeatDirector._fallback_for_shot

def _instrumented_fallback_shot(self, scene, beat, shot, narration):
    log(f"[FALLBACK PATH] Scene {scene.scene_id}, Beat {beat.index}, Shot fallback invoked")
    result = _original_fallback_shot(self, scene, beat, shot, narration)
    if result:
        log(f"  FallbackDirector returned: filepath='{result.filepath}' exists={os.path.isfile(result.filepath) if result.filepath else False}")
    else:
        log("  FallbackDirector returned None")
    return result

di_module.BeatDirector._fallback_for_shot = _instrumented_fallback_shot

# ── Monkey-patch VisualDirector._run_beat_mode ────────────────────────
import src.director.director as director_module
_original_run_beat_mode = director_module.VisualDirector._run_beat_mode

def _instrumented_run_beat_mode(self):
    log("\\n[Beat Mode] Director starting _run_beat_mode")
    result = _original_run_beat_mode(self)
    log(f"[Beat Mode] Director returned {len(result)} scenes")
    for sc in result[:3]:  # Just first 3 scenes
        beats_info = []
        if sc.beat_plans:
            for bp in sc.beat_plans:
                shot_info = []
                for s in bp.shots:
                    sd = {"shot_type": s.shot_type.value}
                    if s.asset_plan:
                        sd["filepath"] = s.asset_plan.filepath
                        sd["video_url"] = s.asset_plan.video_url
                        sd["exists"] = os.path.isfile(s.asset_plan.filepath) if s.asset_plan.filepath else False
                    else:
                        sd["asset_plan"] = "None"
                    shot_info.append(sd)
                beats_info.append({"beat_index": bp.index, "shots": shot_info})
        log_checkpoint("A2 (after _run_beat_mode returns)", {
            "scene_id": sc.scene_id,
            "title": sc.title,
            "scene.asset_plan": sc.asset_plan.filepath if sc.asset_plan else "None",
            "beat_plans": beats_info,
        })
    return result

director_module.VisualDirector._run_beat_mode = _instrumented_run_beat_mode

# ── Monkey-patch execution_node ───────────────────────────────────────
import orchestrator as orch_module
_original_execution_node = orch_module.execution_node

def _instrumented_execution_node(state):
    log("\\n" + "="*60)
    log("INSTRUMENTED EXECUTION NODE")
    log("="*60)

    from src.models import Scene as PydanticScene
    scenes_data_raw = json.loads(state["scenes_json"])

    # CHECKPOINT B: Before director runs
    for ps in [PydanticScene(**sd) for sd in scenes_data_raw]:
        if ps.scene_id <= 2:
            ap_info = None
            if ps.asset_plan:
                ap_info = {"filepath": ps.asset_plan.filepath, "video_url": ps.asset_plan.video_url}
            log_checkpoint("B (before director exec)", {"scene_id": ps.scene_id, "title": ps.title, "asset_plan": ap_info})

    result = _original_execution_node(state)

    # CHECKPOINT C: After execution node populated scenes
    updated_scenes_raw = json.loads(result["scenes_json"])
    for ps_dict in updated_scenes_raw:
        ps = PydanticScene(**ps_dict)
        if ps.scene_id > 2:
            continue
        cp_c = {"scene_id": ps.scene_id}
        if ps.asset_plan:
            cp_c["scene.asset_plan.filepath"] = ps.asset_plan.filepath
            cp_c["scene.asset_plan.video_url"] = ps.asset_plan.video_url
            f_exists = os.path.isfile(ps.asset_plan.filepath) if ps.asset_plan.filepath else False
            f_size = os.path.getsize(ps.asset_plan.filepath) if f_exists else 0
            cp_c["file_exists"] = f_exists
            cp_c["file_size"] = f_size
        else:
            cp_c["scene.asset_plan"] = "None"
        # Beat plans
        if ps.beat_plans:
            beats = []
            for b in ps.beat_plans:
                shots = []
                for s in b.shots:
                    sd = {"shot_type": s.shot_type.value}
                    if s.asset_plan:
                        sd["asset_plan.filepath"] = s.asset_plan.filepath
                        sd["file_exists"] = os.path.isfile(s.asset_plan.filepath) if s.asset_plan.filepath else False
                    else:
                        sd["asset_plan"] = "None"
                    shots.append(sd)
                beats.append({"beat_index": b.index, "shots": shots})
            cp_c["beat_plans"] = beats
        log_checkpoint("C (after exec node populates scenes)", cp_c)

    log("="*60)
    log("EXECUTION NODE COMPLETE")
    log("="*60)
    return result

orch_module.execution_node = _instrumented_execution_node

# ── Monkey-patch TimelineBuilder._build for CHECKPOINT D ──────────────
from src.renderer import timeline_builder as tb_module
_original_build = tb_module.TimelineBuilder._build

def _instrumented_build(self, scenes):
    result = _original_build(self, scenes)
    log("\\n" + "="*60)
    log("CHECKPOINT D (after _build)")
    log("="*60)
    for ti, entry in enumerate(result.get("video_timeline", [])):
        fp = entry.get("file", "")
        log(f"  video_timeline[{ti}]: file='{fp}' exists={os.path.isfile(fp)} size={os.path.getsize(fp) if os.path.isfile(fp) else 0}")
    for ti, entry in enumerate(result.get("audio_timeline", [])):
        fp = entry.get("file", "")
        log(f"  audio_timeline[{ti}]: file='{fp}' exists={os.path.isfile(fp)} size={os.path.getsize(fp) if os.path.isfile(fp) else 0}")
    log("="*60)
    return result

tb_module.TimelineBuilder._build = _instrumented_build

# ── Run the pipeline with timeout per request ──────────────────────────
if __name__ == "__main__":
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_PATH)
    _log_file = open(log_path, "w")
    _log_file.write(f"Runtime trace: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
    _log_file.write("="*70 + "\n")
    _log_file.flush()

    log("Starting instrumented pipeline — fast mode")

    # Set a short default timeout for all urllib requests
    import socket
    socket.setdefaulttimeout(8)

    sys.argv = [sys.argv[0], "--topic", "The Fermi Paradox"]

    # Ensure GEMINI_API_KEY is available (planner needs it)
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
        log(f"EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _log_file.close()
        print(f"\nRuntime trace: {log_path}")
