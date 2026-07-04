import os
import json
import requests
from dotenv import load_dotenv
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from pydub import AudioSegment

from audio_engine import generate_voice
from renderer import render_timeline

load_dotenv()

class AgentState(TypedDict):
    topic: str
    plan_json: str
    timeline_json: str

def planner_node(state: AgentState):
    print(f"\n[1/3] Node: Creative Planner (Topic: {state['topic']})")
    llm = ChatOpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        max_tokens=1000
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
          "narration": "Welcome to Most Amazing Wonders. The universe is unimaginably vast, yet when we look up, we are met with a deafening silence."
        }}
      ]
    }}
    """
    
    response = llm.invoke([HumanMessage(content=prompt)])
    clean_json = response.content.replace("```json", "").replace("```", "").strip()
    return {"plan_json": clean_json}

def execution_node(state: AgentState):
    print("\n[2/3] Node: Deterministic Execution (Downloading & Math)")
    plan = json.loads(state["plan_json"])
    scene = plan["scenes"][0]
    
    video_path = f"cache/video/scene_{scene['scene_id']}.mp4"
    audio_path = f"cache/audio/scene_{scene['scene_id']}.wav"
    
    print(f"-> Searching Pexels for: '{scene['search_query']}'")
    headers = {"Authorization": os.environ.get("PEXELS_API_KEY")}
    url = f"https://api.pexels.com/videos/search?query={scene['search_query']}&per_page=5&orientation=landscape"
    
    try:
        res = requests.get(url, headers=headers).json()
        video_url = res["videos"][0]["video_files"][0]["link"]
        print("-> Downloading video asset...")
        with open(video_path, "wb") as f:
            f.write(requests.get(video_url).content)
    except Exception as e:
        print("-> Pexels Error/Empty. Falling back to dummy clip.")
        video_path = "cache/video/test_clip.mp4"
        
    print("-> Generating voiceover...")
    generate_voice(scene['narration'], audio_path)
    
    print("-> Calculating exact timestamps...")
    audio_len = len(AudioSegment.from_wav(audio_path)) / 1000.0 
    
    timeline = {
      "render_settings": {"resolution": [1920, 1080], "fps": 30},
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
    print("\n[3/3] Node: MoviePy Renderer")
    render_timeline("timeline.json", "final_output.mp4")
    return state

workflow = StateGraph(AgentState)
workflow.add_node("planner", planner_node)
workflow.add_node("execution", execution_node)
workflow.add_node("render", render_node)

workflow.set_entry_point("planner")
workflow.add_edge("planner", "execution")
workflow.add_edge("execution", "render")
workflow.add_edge("render", END)

app = workflow.compile()

if __name__ == "__main__":
    if not os.environ.get("PEXELS_API_KEY"):
        print("CRITICAL ERROR: PEXELS_API_KEY not found in .env")
        exit(1)
        
    print("========== INITIATING AUTONOMOUS PIPELINE ==========")
    app.invoke({"topic": "The Fermi Paradox"})
    print("\n========== PIPELINE COMPLETE ==========")
    print("Check final_output.mp4 in your directory.")
