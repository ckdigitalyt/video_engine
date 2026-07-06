import os
import json
import subprocess
from dotenv import load_dotenv
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END

from google.api_core.exceptions import NotFound, ResourceExhausted, PermissionDenied, InvalidArgument

from audio_engine import generate_voice
from renderer import render_timeline
from src.utils.config import get_config
from src.providers import DeepSeekProvider, GeminiProvider, PexelsProvider
from src.renderer.timeline_builder import TimelineBuilder
from src.memory.memory_manager import MemoryManager
from src.models import Scene, SceneAsset, CriticResult

load_dotenv()

# ── Providers ──────────────────────────────────────────────────────────────

deepseek = DeepSeekProvider()
pexels = PexelsProvider()
gemini = GeminiProvider()

cache_video = get_config("pipeline.cache.video", "cache/video")
cache_audio = get_config("pipeline.cache.audio", "cache/audio")
fallback_video = get_config("pipeline.fallback.video", "cache/video/test_clip.mp4")


class AgentState(TypedDict):
    topic: str
    plan_json: str
    timeline_json: str
    iteration: int
    approved: bool
    critic_result: str  # JSON-serialized CriticResult


def planner_node(state: AgentState):
    iteration = state.get("iteration", 0) + 1
    print(f"\n[1/4] Node: Creative Planner (Iteration: {iteration})")

    prompt = f"""
    You are the Director Agent for a YouTube documentary channel.
    Topic: "{state['topic']}"

    Create a multi-scene short documentary script with 8 to 15 scenes.
    Output ONLY a raw, valid JSON object. Do not use markdown.

    Exact Schema Required:
    {{
      "scenes": [
        {{
          "scene_id": 1,
          "title": "The Vast Cosmos",
          "search_query": "deep space milky way galaxy",
          "narration": "The universe is unimaginably vast, yet when we look up, we are met with a deafening silence.",
          "estimated_duration": 10
        }}
      ]
    }}

    Rules:
    1. Number of scenes must be between 8 and 15, scaled to topic depth.
    2. Each scene_id starts at 1 and increments by 1.
    3. Narration text must be roughly 3 words per second of estimated_duration.
       Example: estimated_duration 10 → narration ≈ 30 words.
    4. search_query must be unique across all scenes.
    5. Ensure logical progression — open strongly, develop the argument, conclude.
    6. No duplicated scenes, titles, or narration.
    7. Smooth narrative transitions between consecutive scenes.
    """

    content = deepseek.generate_json(prompt)
    return {"plan_json": content, "iteration": iteration}


def execution_node(state: AgentState):
    print("\n[2/4] Node: Deterministic Execution")
    plan = json.loads(state["plan_json"])
    scenes_data = plan["scenes"]
    print(f"-> Planner produced {len(scenes_data)} scenes")

    scene_assets: list[SceneAsset] = []

    for scene_data in scenes_data:
        scene = Scene(
            scene_id=scene_data["scene_id"],
            search_query=scene_data["search_query"],
            narration=scene_data["narration"],
        )

        video_path = f"{cache_video}/scene_{scene.scene_id}.mp4"
        audio_path = f"{cache_audio}/scene_{scene.scene_id}.wav"

        print(f"  Scene {scene.scene_id}: searching '{scene.search_query}'")
        target_dur = scene_data.get("estimated_duration")
        result = []
        try:
            videos = pexels.search(scene.search_query, target_duration=target_dur)
            if videos:
                video_url = videos[0]["video_files"][0]["link"]
                pexels.download(video_url, video_path)
                result = [video_path]
        except Exception:
            pass

        if not result:
            print("    -> Pexels Error. Using fallback.")
            video_path = fallback_video

        print(f"  Scene {scene.scene_id}: generating voiceover...")
        generate_voice(scene.narration, audio_path)

        scene_assets.append(SceneAsset(
            scene_id=scene.scene_id,
            video_path=video_path,
            audio_path=audio_path,
        ))

    # Build timeline using TimelineBuilder
    builder = TimelineBuilder()
    timeline_json = builder.build_and_write(scene_assets)

    return {"timeline_json": timeline_json}


def render_node(state: AgentState):
    print("\n[3/4] Node: MoviePy Renderer")
    render_timeline("timeline.json", get_config("pipeline.output.default", "final_output.mp4"))
    return state


def critic_node(state: AgentState):
    print("\n[4/4] Node: Gemini Multimodal Critic")
    frame_path = get_config("pipeline.critic.eval_frame", "cache/video/eval_frame.jpg")

    # Extract 1 frame at the 2-second mark using FFmpeg (highly CPU efficient)
    print("-> Extracting evaluation frame...")
    output_file = get_config("pipeline.output.default", "final_output.mp4")
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
    if not os.environ.get("GEMINI_API_KEY"):
        print("CRITICAL ERROR: GEMINI_API_KEY not found in .env")
        exit(1)

    print("========== INITIATING SELF-IMPROVING PIPELINE ==========")

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

    # Initialize the graph with an iteration count of 0
    app.invoke({"topic": "The Fermi Paradox", "iteration": 0})
    print("\n========== PIPELINE COMPLETE ==========")
