import os
import json
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END

from google.api_core.exceptions import NotFound, ResourceExhausted, PermissionDenied, InvalidArgument

from audio_engine import generate_voice, mix_audio
from src.renderer import Renderer
from src.renderer.moviepy_renderer import MoviePyRenderer
from src.utils.config import get_config
from src.utils.duration import ensure_video_duration, get_media_duration
from src.providers import DeepSeekProvider, GeminiProvider
from src.assets import AssetRouter
from src.assets.search_planner import SearchPlanner
from src.validation.semantic_validator import SemanticValidator
from src.planner import StoryPlanner
from src.renderer.timeline_builder import TimelineBuilder
from src.memory.memory_manager import MemoryManager
from src.models import Scene as PydanticScene, SceneAsset, CriticResult
from src.models.schemas import (
    SceneNarration,
    VisualPlan,
    SearchPlan,
    EditingPlan,
    AssetPlan,
    AudioPlan,
    RenderPlan,
    PipelineState,
    ProviderType,
    scene_to_flat_dict,
)
from src.subtitles.engine import SubtitleEngine

load_dotenv()

# ── Providers ──────────────────────────────────────────────────────────────

deepseek = DeepSeekProvider()
gemini = GeminiProvider()
renderer: Renderer = MoviePyRenderer()
subtitle_engine = SubtitleEngine()

cache_video = get_config("pipeline.cache.video", "cache/video")
cache_audio = get_config("pipeline.cache.audio", "cache/audio")
cache_music = get_config("pipeline.cache.music", "cache/music")
# FallbackDirector handles all degradation — no static fallback clip
background_music_path = os.path.join(
    cache_music,
    os.path.basename(get_config("voices.mixing.background_music", "cinematic.mp3")),
)


class AgentState(TypedDict):
    topic: str
    output_path: str
    plan_json: str
    scenes_json: str  # JSON-serialized list of Scene dicts (Pydantic models)
    timeline_json: str
    iteration: int
    approved: bool
    critic_result: str  # JSON-serialized CriticResult
    subtitle_timeline: list  # Per-word subtitle clips from SubtitleEngine


def planner_node(state: AgentState):
    iteration = state.get("iteration", 0) + 1
    print(f"\n[1/4] Node: Story Planning Engine (Iteration: {iteration})")

    planner = StoryPlanner(provider=deepseek)
    scenes: list[PydanticScene] = planner.generate_plan(state["topic"])

    # Serialize Scene models to JSON for LangGraph state compatibility.
    # Each scene is converted to a dict via model_dump() for transport.
    scenes_json = json.dumps([s.model_dump(mode="json") for s in scenes])

    return {"plan_json": "", "scenes_json": scenes_json, "iteration": iteration}


def execution_node(state: AgentState):
    print("\n[2/4] Node: Visual Director Execution")

    # Reconstruct Pydantic Scene objects from serialized JSON
    scenes_data_raw = json.loads(state["scenes_json"])
    pydantic_scenes: list[PydanticScene] = [
        PydanticScene(**sd) for sd in scenes_data_raw
    ]
    print(f"-> Planner produced {len(pydantic_scenes)} scenes")

    # Build the director-compatible scene dict format from Scene objects
    director_scene_data: list[dict] = []
    for ps in pydantic_scenes:
        # Build search queries from SearchPlan (NEVER from narration)
        search_queries = ps.search_plan.asset_search_queries
        search_query = search_queries[0] if search_queries else "general"

        director_scene_data.append({
            "scene_id": ps.scene_id,
            "narration": ps.narration.to_tts_input(),  # CRITICAL: TTS gets ONLY spoken_narration
            "search_query": search_query,                # CRITICAL: Search gets ONLY SearchPlan
            "scene_title": ps.title,
            "purpose": ps.search_plan.scene_purpose,
            "estimated_duration": ps.expected_duration,
        })

    # ── Create the closed-loop Visual Director ─────────────────────────
    from src.director.director import VisualDirector

    director = VisualDirector(use_beats=True, 
        topic=state["topic"],
        llm_provider=deepseek,
        scene_data=director_scene_data,
    )

    # Run the director's quality-gated pipeline
    direct_results = director.run()

    # Convert director results to SceneAsset and update Scene objects
    scene_assets: list[SceneAsset] = []
    scene_narrations: list[tuple[int, str, str]] = []

    for i, result in enumerate(direct_results):
        # result is a Scene object (Pydantic) or dict (backward compat)
        if hasattr(result, "scene_id"):
            scene_id = result.scene_id
            video_path = result.asset_plan.filepath if result.asset_plan else ""
            # Audio path: prefer asset_plan.audio_filepath or derive from cache
            cache_audio = get_config("pipeline.cache.audio", "cache/audio")
            audio_path = os.path.join(cache_audio, f"scene_{scene_id}.wav")
            if not os.path.exists(audio_path):
                audio_path = result.audio_plan.narration_audio_path if result.audio_plan else ""
            narration = result.narration.spoken_narration
        else:
            scene_id = result["scene_id"]
            video_path = result["video_path"]
            audio_path = result["audio_path"]
            narration = result["narration"]

        scene_assets.append(SceneAsset(
            scene_id=scene_id,
            video_path=video_path,
            audio_path=audio_path,
        ))
        scene_narrations.append((scene_id, narration, audio_path))

        # Update the Pydantic Scene with the resolved assets
        if scene_id < len(pydantic_scenes):
            ps = pydantic_scenes[scene_id]
            if hasattr(result, "asset_plan") and result.asset_plan:
                ps.asset_plan = result.asset_plan
            else:
                ps.asset_plan = AssetPlan(
                    provider=ProviderType(result.get("provider", "pixabay")),
                    filepath=video_path,
                    video_url=result.get("video_url", ""),
                    query_used=result.get("query", ""),
                score=max(
                    result.get("technical_score", 0.0),
                    result.get("semantic_score", 0.0),
                ),
                semantic_score=result.get("semantic_score", 0.0),
                technical_score=result.get("technical_score", 0.0),
                aesthetic_style=result.get("aesthetic_style", "documentary"),
                duration=ps.expected_duration,
                width=1920,
                height=1080,
            )
            ps.audio_plan = AudioPlan(
                narration_audio_path=audio_path,
            )

    # ── Background music mixing ───────────────────────────────────────
    fade_in = get_config("voices.mixing.fade_in_ms", 3000)
    fade_out = get_config("voices.mixing.fade_out_ms", 3000)
    music_volume = get_config("voices.mixing.music_volume_db", 0.0)

    if os.path.exists(background_music_path):
        print(f"-> Mixing scenes with background music: {background_music_path}")
        for asset in scene_assets:
            mixed_path = asset.audio_path.replace(".wav", "_mixed.wav")
            mix_audio(
                asset.audio_path,
                background_music_path,
                mixed_path,
                fade_in_ms=fade_in,
                fade_out_ms=fade_out,
                music_volume_db=music_volume,
            )
            asset.audio_path = mixed_path
            # Update the Scene's audio plan with the mixed path
            for ps in pydantic_scenes:
                if ps.scene_id == asset.scene_id and ps.audio_plan is not None:
                    ps.audio_plan.narration_audio_path = mixed_path
                    break
    else:
        print(f"-> No background music found at {background_music_path}. Using voice only.")

    # ── Subtitle generation ──────────────────────────────────────────
    subtitle_timeline: list[dict] = []
    if subtitle_engine._enabled:
        print(f"-> Generating subtitles for {len(scene_narrations)} scenes...")
        for sid, narration_text, audio_path in scene_narrations:
            if os.path.exists(audio_path):
                word_timing = subtitle_engine.generate(
                    audio_path,
                    narration_text,
                    resolution=(1920, 1080),
                )
                renderer_clips = subtitle_engine.to_renderer_clips(word_timing)
                subtitle_timeline.extend(renderer_clips)
        print(f"-> {len(subtitle_timeline)} subtitle clips generated")
    else:
        print("-> Subtitles disabled")

    # Build timeline using TimelineBuilder — pass Scene objects so the
    # builder can read asset_plan/audio_plan fields directly.
    builder = TimelineBuilder()
    timeline_json = builder.build_and_write(pydantic_scenes)

    # Serialize updated scenes back to state for downstream nodes
    updated_scenes_json = json.dumps([ps.model_dump(mode="json") for ps in pydantic_scenes])

    return {
        "scenes_json": updated_scenes_json,
        "timeline_json": timeline_json,
        "subtitle_timeline": subtitle_timeline,
    }


def render_node(state: AgentState):
    print("\n[3/4] Node: MoviePy Renderer")
    subtitle_timeline = state.get("subtitle_timeline", [])
    output_path = state.get("output_path") or get_config("pipeline.output.default", "final_output.mp4")
    renderer.render(
        "timeline.json",
        output_path,
        subtitles=subtitle_timeline if subtitle_timeline else None,
    )
    return state


def critic_node(state: AgentState):
    print("\n[4/4] Node: Gemini Multimodal Critic")
    frame_path = get_config("pipeline.critic.eval_frame", "cache/video/eval_frame.jpg")

    # Extract 1 frame at the 2-second mark using FFmpeg (highly CPU efficient)
    print("-> Extracting evaluation frame...")
    output_file = state.get("output_path") or get_config("pipeline.output.default", "final_output.mp4")
    subprocess.run(["ffmpeg", "-y", "-i", output_file, "-ss", get_config("pipeline.critic.frame_extraction_ss", "00:00:02"), "-vframes", "1", frame_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("-> Querying Gemini API for Visual QA...")
    try:
        prompt = "You are a ruthless video QA critic. Analyze this extracted frame. You MUST REJECT it (Answer NO) if you see ANY of the following: 1. Large black borders, letterboxing, or pillarboxing. 2. The video not filling the entire frame. 3. Solid blue or black error frames. If the image perfectly fills the screen and looks cinematic, answer YES."
        decision = gemini.generate_text(prompt, image_path=frame_path).upper()

        print(f"-> Gemini Assessment: {decision}")
        # Parse the decision — must contain YES for approval
        if "YES" in decision:
            approved = True
            reason = "Frame passed visual QA (YES detected)"
        else:
            approved = False
            reason = f"Frame rejected: {decision[:200]}"

        result = CriticResult(approved=approved, decision=decision, error=None)

    except NotFound as e:
        print(f"✗ CRITICAL CONFIG ERROR: Gemini model not found: {e}")
        print("  -> Update 'llm.gemini.model' in configs/models.yaml to a supported model.")
        print("  -> FAIL CLOSED: marking render as pending review. Pipeline will NOT auto-approve.")
        approved = False
        result = CriticResult(approved=False, error=f"Configuration error: model not found — {e}")

    except ResourceExhausted as e:
        print(f"✗ GEMINI QUOTA EXHAUSTED: {e}")
        print("  -> Retrying with exponential backoff...")
        import time as _time
        for backoff in [2, 4, 8]:
            _time.sleep(backoff)
            try:
                decision = gemini.generate_text(prompt, image_path=frame_path).upper()
                if "YES" in decision:
                    approved = True
                    result = CriticResult(approved=True, decision=decision, error=None)
                    break
            except Exception:
                continue
        else:
            print("  -> All retries exhausted. FAIL CLOSED: marking as pending review.")
            approved = False
            result = CriticResult(approved=False, error=f"Resource exhausted (quota): {e}")

    except PermissionDenied as e:
        print(f"✗ GEMINI AUTH ERROR: Invalid or missing GEMINI_API_KEY")
        print("  -> FAIL CLOSED: cannot evaluate without valid credentials.")
        print("  -> Marking render as pending manual review.")
        approved = False
        result = CriticResult(approved=False, error=f"Authentication error: {e}")

    except InvalidArgument as e:
        print(f"✗ GEMINI ARGUMENT ERROR: Invalid configuration: {e}")
        print("  -> Check model name and parameters in configs/models.yaml.")
        print("  -> FAIL CLOSED: marking as pending review.")
        approved = False
        result = CriticResult(approved=False, error=f"Invalid argument: {e}")

    except Exception as e:
        print(f"✗ GEMINI UNKNOWN ERROR: {e}")
        print("  -> FAIL CLOSED: marking as pending review. Pipeline will NOT auto-approve.")
        approved = False
        result = CriticResult(approved=False, error=f"Unknown error: {e}")

    print(f"-> CriticResult: approved={result.approved}, error={result.error}")
    return {"approved": result.approved, "critic_result": json.dumps({
        "approved": result.approved,
        "decision": result.decision,
        "error": result.error,
    })}


# Conditional Routing Logic
def route_evaluation(state: AgentState):
    if state["approved"]:
        print("\n>>> Video APPROVED by Critic. Terminating loop. <<<")
        return END
    elif state["iteration"] >= get_config("pipeline.max_iterations", 3):
        print("\n>>> Max iterations (3) reached. Forcing APPROVAL. <<<")
        return END
    else:
        print("\n>>> Video REJECTED. Looping back to Planner. <<<")
        return "planner"


workflow = StateGraph(AgentState)
workflow.add_node("planner", planner_node)
workflow.add_node("execution", execution_node)
workflow.add_node("render", render_node)
workflow.add_node("critic", critic_node)

workflow.set_entry_point("planner")
workflow.add_edge("planner", "execution")
workflow.add_edge("execution", "render")
workflow.add_edge("render", "critic")
workflow.add_conditional_edges("critic", route_evaluation)

app = workflow.compile()

# ── Memory ─────────────────────────────────────────────────────────────────

memory = MemoryManager(get_config("pipeline.memory.db_path", "cache/memory.db"))

if __name__ == "__main__":
    import argparse

    if not os.environ.get("GEMINI_API_KEY"):
        print("CRITICAL ERROR: GEMINI_API_KEY not found in .env")
        exit(1)

    parser = argparse.ArgumentParser(description="Run the video generation pipeline")
    parser.add_argument("--topic", default="The Fermi Paradox", help="Video topic")
    parser.add_argument("--output", default=None, help="Output video path")
    args = parser.parse_args()

    print(f"========== INITIATING SELF-IMPROVING PIPELINE ==========")
    print(f"Topic: {args.topic}")
    if args.output:
        print(f"Output: {args.output}")

    # Initialize memory tables
    memory.initialize()

    # Apply retention / cleanup policy
    cleaned = memory.cleanup(
        retention_days=get_config("pipeline.memory.retention_days", 90),
        max_exec_logs=get_config("pipeline.memory.max_execution_logs", 1000),
    )
    for table, count in cleaned.items():
        if count:
            print(f"[memory] Cleaned {count} rows from {table}")

    # Initialize the graph
    initial_state: AgentState = {
        "topic": args.topic,
        "output_path": args.output or "final_output.mp4",
        "plan_json": "",
        "scenes_json": "",
        "timeline_json": "",
        "iteration": 0,
        "approved": False,
        "critic_result": "",
        "subtitle_timeline": [],
    }
    app.invoke(initial_state)
    print("\n========== PIPELINE COMPLETE ==========")
