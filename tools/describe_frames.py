#!/usr/bin/env python3
"""describe_frames.py — Generate per-frame visual descriptions via Gemini flash."""
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
from dotenv import load_dotenv
load_dotenv(override=True)

FRAME_DESC_PROMPT = """You are a documentary video assistant. Below are sampled
frames from a rendered documentary video, each tagged with its timestamp (sec).
For EACH frame, write ONE concise sentence describing what is visually shown:
subject, style (photorealistic render / animation / diagram / stock), colors,
any text/UI elements, and whether it looks like a real photograph, a CGI
render, a flat illustration, or a data diagram. Also flag anything that looks
like an artifact (mirrored edges, smearing, black frames, letterbox bars).
Output STRICT JSON (no fences): {"frames": [{"t": <sec>, "desc": "..."}]}"""

frames_dir = sys.argv[1]
out_path = sys.argv[2]

from google import genai
from google.genai import types
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".jpg"))
content = [FRAME_DESC_PROMPT]
for f in frames:
    t = f.split("_")[1].split(".")[0]
    b64 = base64.b64encode(open(os.path.join(frames_dir, f), "rb").read()).decode()
    content.append(f"FRAME t={t}s (filename {f}):")
    content.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/jpeg"))

last_err = None
for model in ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3-flash-preview"]:
    for attempt in range(4):
        try:
            resp = client.models.generate_content(model=model, contents=content,
                config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json"))
            text = resp.text or ""
            text = text.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            descs = data.get("frames", [])
            with open(out_path, "w") as f:
                json.dump(descs, f, indent=2)
            print(f"OK model={model} frames={len(descs)} -> {out_path}")
            sys.exit(0)
        except Exception as e:
            last_err = e
            msg = str(e)
            print(f"  !! {model} attempt {attempt+1}: {str(e)[:120]}")
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                time.sleep(15 * (attempt + 1))
                continue
            break
print(f"FAILED: {last_err}")
sys.exit(1)
