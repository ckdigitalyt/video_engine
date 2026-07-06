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
from src.providers import DeepSeekProvider, GeminiProvider
from src.assets import AssetRouter
from src.assets.search_planner import SearchPlanner
from src.planner import StoryPlanner
from src.renderer.timeline_builder import TimelineBuilder
from src.memory.memory_manager import MemoryManager
from src.models import Scene, SceneAsset, CriticResult
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
fallback_video = get_config("pipeline.fallback.video", "cache/video/test_clip.mp4")
background_music_path = os.path.join(
    cache_music,
    os.path.basename(get_config("voices.mixing.background_music", "cinematic.mp3")),
)


class AgentState(TypedDict):
    topic: str
    output_path: str
    plan_json: str
    timeline_json: str
    iteration: int
    approved: bool
    critic_result: str  # JSON-serialized CriticResult
    subtitle_timeline: list  # Per-word subtitle clips from SubtitleEngine


def planner_node(state: AgentState):
    iteration = state.get("iteration", 0) + 1
    print(f"\n[1/4] Node: Story Planning Engine (Iteration: {iteration})")

    planner = StoryPlanner(provider=deepseek)
    content = planner.generate_plan(state["topic"])
    return {"plan_json": content, "iteration": iteration}


def execution_node(state: AgentState):
    print("\n[2/4] Node: Deterministic Execution")
    plan = json.loads(state["plan_json"])
    scenes_data = plan["scenes"]
    print(f"-> Planner produced {len(scenes_data)} scenes")

    # Create topic-aware asset router for this execution
    topic = state["topic"]
    router = AssetRouter.for_topic(topic)

    # Create search planner for multi-query search
    search_planner = SearchPlanner(provider=deepseek)

    scene_assets: list[SceneAsset] = []
    scene_narrations: list[tuple[int, str, str]] = []

    for scene_data in scenes_data:
        scene = Scene(
            scene_id=scene_data["scene_id"],
            search_query=scene_data["search_query"],
            narration=scene_data["narration"],
        )

        video_path = f"{cache_video}/scene_{scene.scene_id}.mp4"
        audio_path = f"{cache_audio}/scene_{scene.scene_id}.wav"

        print(f"\n  Scene {scene.scene_id}: '{scene.search_query}'")
        target_dur = scene_data.get("estimated_duration")

        # ── Generate diverse search queries ────────────────────────────
        print(f"    -> Generating search queries...")
        queries = search_planner.generate_queries(
            narration=scene.narration,
            title=scene_data.get("scene_title", ""),
            topic=topic,
            purpose=scene_data.get("purpose", "general"),
        )

        # Log generated queries
        for i, q in enumerate(queries, 1):
            print(f"    Query {i}: {q}")

        # ── Execute multi-query search ────────────────────────────────
        result = []
        try:
            mq_result = router.multi_query_search(
                queries,
                min_acceptable_score=search_planner.min_acceptable_score,
                max_attempts=search_planner.max_provider_attempts,
                diversity_weighting=search_planner.diversity_weighting,
                target_duration=target_dur,
            )

            videos = mq_result.get("assets", [])
            selected_query = mq_result.get("selected_query", "")
            selected_provider = mq_result.get("provider_name", "")
            selected_score = mq_result.get("selected_score", -1.0)
            query_log = mq_result.get("query_log", [])

            # Log per-query results
            print(f"    Queries tried: {len(query_log)}")
            for log_entry in query_log:
                q = log_entry.get("query", "")
                status = log_entry.get("status", "attempted")
                providers = log_entry.get("tried_providers", [])
                provs = ", ".join(f"{p['provider']}:{p.get('status','?')}" for p in providers)
                score = log_entry.get("score", "-")
                print(f"      - '{q}' [{provs}] score={score}")

            print(f"    Selected provider: {selected_provider}")
            print(f"    Selected query: {selected_query}")
            print(f"    Reason: score={selected_score:.3f}")

            # Also update the scene's search query for the timeline
            scene.search_query = selected_query or scene.search_query

            if videos:
                video_url = videos[0]["video_files"][0]["link"]
                router.download(video_url, video_path)
                result = [video_path]
        except Exception as e:
            print(f"    -> Multi-query search error: {e}")

        if not result:
            print("    -> All providers exhausted. Using fallback.")
            video_path = fallback_video

        print(f"  Scene {scene.scene_id}: generating voiceover...")
        generate_voice(scene.narration, audio_path)
        scene_narrations.append((scene.scene_id, scene.narration, audio_path))

        scene_assets.append(SceneAsset(
            scene_id=scene.scene_id,
            video_path=video_path,
            audio_path=audio_path,
        ))

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

    # Build timeline using TimelineBuilder
    builder = TimelineBuilder()
    timeline_json = builder.build_and_write(scene_assets)

    return {"timeline_json": timeline_json, "subtitle_timeline": subtitle_timeline}


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
        print("  -> Defaulting to APPROVED to unblock pipeline.")
        approved = True
        result = CriticResult(approved=False, error=f"Configuration error: model not found — {e}")

    except ResourceExhausted as e:
        print(f"✗ GEMINI QUOTA EXHAUSTED: {e}")
        print("  -> Free-tier quota may be depleted. Wait or upgrade.")
        print("  -> Defaulting to APPROVED to unblock pipeline.")
        approved = True
        result = CriticResult(approved=False, error=f"Resource exhausted (quota): {e}")

    except PermissionDenied as e:
        print(f"✗ GEMINI AUTH ERROR: Invalid or missing GEMINI_API_KEY")
        print("  -> Check .env file and GEMINI_API_KEY value.")
        print("  -> Defaulting to APPROVED to unblock pipeline.")
        approved = True
        result = CriticResult(approved=False, error=f"Authentication error: {e}")

    except InvalidArgument as e:
        print(f"✗ GEMINI ARGUMENT ERROR: Invalid configuration: {e}")
        print("  -> Check model name and parameters in configs/models.yaml.")
        print("  -> Defaulting to APPROVED to unblock pipeline.")
        approved = True
        result = CriticResult(approved=False, error=f"Invalid argument: {e}")

    except Exception as e:
        print(f"✗ GEMINI UNKNOWN ERROR: {e}")
        print("  -> Defaulting to APPROVED to prevent pipeline block.")
        approved = True
        result = CriticResult(approved=False, error=f"Unknown error: {e}")

    print(f"-> CriticResult: approved={result.approved}, error={result.error}")
    return {"approved": approved, "critic_result": json.dumps({
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
        "timeline_json": "",
        "iteration": 0,
        "approved": False,
        "critic_result": "",
        "subtitle_timeline": [],
    }
    app.invoke(initial_state)
    print("\n========== PIPELINE COMPLETE ==========")
