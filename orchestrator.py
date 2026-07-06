import os
import json
import requests
import subprocess
from dotenv import load_dotenv
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import google.generativeai as genai
import PIL.Image
from langgraph.graph import StateGraph, END
from pydub import AudioSegment

from audio_engine import generate_voice
from renderer import render_timeline
from src.utils.config import get_config

load_dotenv()

# Initialize Gemini Client
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

class AgentState(TypedDict):
    topic: str
    plan_json: str
    timeline_json: str
    iteration: int
    approved: bool

def planner_node(state: AgentState):
    iteration = state.get("iteration", 0) + 1
    print(f"\n[1/4] Node: Creative Planner (Iteration: {iteration})")
    
    llm = ChatOpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        base_url=get_config("providers.deepseek.base_url", "https://api.deepseek.com"),
        model=get_config("llm.deepseek.model", "deepseek-chat"),
        max_tokens=get_config("llm.deepseek.max_tokens", 1000)
    )
    
    prompt = f"""
    You are the Director Agent for a YouTube documentary channel.
    Topic: "{state['topic']}"
    
    Create a 1-scene short script.
    Output ONLY a raw, valid JSON object. Do not use markdown.
    
    Exact Schema Required:
    {{
      "scenes": [
        {{
          "scene_id": 1,
          "search_query": "deep space milky way galaxy",
          "narration": "The universe is unimaginably vast, yet when we look up, we are met with a deafening silence."
        }}
      ]
    }}
    """
    
    response = llm.invoke([HumanMessage(content=prompt)])
    clean_json = response.content.replace("```json", "").replace("```", "").strip()
    return {"plan_json": clean_json, "iteration": iteration}

def execution_node(state: AgentState):
    print("\n[2/4] Node: Deterministic Execution")
    plan = json.loads(state["plan_json"])
    scene = plan["scenes"][0]
    
    video_path = f"{get_config('pipeline.cache.video', 'cache/video')}/scene_{scene['scene_id']}.mp4"
    audio_path = f"{get_config('pipeline.cache.audio', 'cache/audio')}/scene_{scene['scene_id']}.wav"
    
    print(f"-> Searching Pexels for: '{scene['search_query']}'")
    headers = {"Authorization": os.environ.get("PEXELS_API_KEY")}
    pexels_base = get_config("providers.pexels.base_url", "https://api.pexels.com/videos/search")
    pexels_per_page = get_config("providers.pexels.per_page", 5)
    pexels_orientation = get_config("providers.pexels.orientation", "landscape")
    url = f"{pexels_base}?query={scene['search_query']}&per_page={pexels_per_page}&orientation={pexels_orientation}"
    
    try:
        res = requests.get(url, headers=headers).json()
        video_url = res["videos"][0]["video_files"][0]["link"]
        with open(video_path, "wb") as f:
            f.write(requests.get(video_url).content)
    except Exception:
        print("-> Pexels Error. Using fallback.")
        video_path = get_config("pipeline.fallback.video", "cache/video/test_clip.mp4")
        
    print("-> Generating voiceover...")
    generate_voice(scene['narration'], audio_path)
    
    audio_len = len(AudioSegment.from_wav(audio_path)) / 1000.0 
    
    timeline = {
      "render_settings": {
          "resolution": [
              get_config("render.resolution.width", 1920),
              get_config("render.resolution.height", 1080)
          ],
          "fps": get_config("render.fps", 30)
      },
      "audio_timeline": [
        {"track": "voice", "file": audio_path, "start_time": 0.0, "end_time": audio_len}
      ],
      "video_timeline": [
        {"layer": 1, "file": video_path, "start_time": 0.0, "end_time": audio_len, "transition_out": "none"}
      ]
    }
    
    with open("timeline.json", "w") as f:
        json.dump(timeline, f, indent=2)
        
    return {"timeline_json": json.dumps(timeline)}

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
        model = genai.GenerativeModel(get_config("llm.gemini.model", "gemini-1.5-flash"))
        img = PIL.Image.open(frame_path)
        prompt = "You are a ruthless video QA critic. Analyze this extracted frame. You MUST REJECT it (Answer NO) if you see ANY of the following: 1. Large black borders, letterboxing, or pillarboxing. 2. The video not filling the entire frame. 3. Solid blue or black error frames. If the image perfectly fills the screen and looks cinematic, answer YES."
        response = model.generate_content([prompt, img])
        decision = response.text.strip().upper()
        
        print(f"-> Gemini Assessment: {decision}")
        approved = "YES" in decision
    except Exception as e:
        print(f"-> Gemini Error: {e}. Defaulting to APPROVED to prevent pipeline block.")
        approved = True
        
    return {"approved": approved}

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

if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("CRITICAL ERROR: GEMINI_API_KEY not found in .env")
        exit(1)
        
    print("========== INITIATING SELF-IMPROVING PIPELINE ==========")
    # Initialize the graph with an iteration count of 0
    app.invoke({"topic": "The Fermi Paradox", "iteration": 0})
    print("\n========== PIPELINE COMPLETE ==========")
