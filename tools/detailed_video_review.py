#!/usr/bin/env python3
"""detailed_video_review.py — Deep dual-model review of a rendered video.

Gemini (vision): reviews the ACTUAL video (sampled frames) + script +
audio diagnostics across: script, voice/delivery, audio engineering,
pacing, visualization, storyline, factual accuracy, music, transitions.
Also produces per-frame visual descriptions (visual transcript).

ZAI GLM (text-only): reviews script + visual transcript + timeline +
audio diagnostics with the same detailed rubric, independently.

Usage:
    python3 tools/detailed_video_review.py \
        --video results/.../mixed.mp4 \
        --script results/.../script_final.json \
        --timeline results/.../timeline.json \
        --audio-diag tmp/.../audio_diag_results.json \
        --frames tmp/.../frames \
        --out logs/detailed_review_venus_v3 \
        --providers gemini,zai
"""
import argparse, base64, json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
from dotenv import load_dotenv
load_dotenv(override=True)

DETAILED_PROMPT = """You are the executive producer of a world-class science documentary studio, reviewing a rendered documentary video END-TO-END with a fine-tooth comb. You see sampled frames (timestamped) plus the narration script and objective audio diagnostics.

Evaluate EVERY dimension below with a 0-10 score and concrete, timestamped evidence:

1. SCRIPT — hook quality, structure, clarity, scientific accuracy of the wording, curiosity arc
2. VOICE / DELIVERY — narration delivery, clarity, pronunciation, naturalness; note any jitter, stutter, choppiness, or robotic artifacts (cross-check the AUDIO DIAGNOSTICS timestamps)
3. AUDIO ENGINEERING — mix balance (voice vs music vs SFX), ducking artifacts, pumping, clipping, hiss, loudness consistency, silence management
4. PACING — rhythm scene-to-scene, WPM feel, pause placement, dead air, rushed or draggy sections
5. VISUALIZATION — still relevance to narration, style consistency, Ken Burns motion quality, camera continuity across cuts, artifacts (mirrored edges, smears, black frames)
6. STORYLINE / NARRATIVE COHERENCE — does it hang together as a story? clear arc, satisfying close?
7. FACTUAL ACCURACY — flag any claim that seems wrong or unsupported
8. MUSIC — fit, level, emotional alignment
9. TRANSITIONS — cut quality, continuity of motion and style
10. SUBTITLES (if present)

AUDIO DIAGNOSTICS (objective measurements — verify or refute with your judgment):
{audio_diag}

Respond in STRICT JSON (no markdown fences) with schema:
{{
  "quality_score": <int 0-100>,
  "confidence": <float 0-1>,
  "dimensions": {{
    "script": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "voice_delivery": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "audio_engineering": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "pacing": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "visualization": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "storyline": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "factual_accuracy": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "music": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}},
    "transitions": {{"score": <int 0-10>, "evidence": "...", "issues": ["..."]}}
  }},
  "strengths": ["..."],
  "weaknesses": ["..."],
  "prioritized_recommendations": [
    {{"priority": "critical|high|medium|low",
      "category": "script|voice|audio_engineering|pacing|visualization|storyline|music|transitions|other",
      "recommendation": "<specific, actionable, timestamped where possible>"}}
  ],
  "voice_jitter_report": {{
    "confirmed": <bool>,
    "timestamps": ["<mm:ss>..."],
    "description": "<what it sounds like / what causes it>",
    "suggested_fix": "..."
  }},
  "factual_issues": [{{"claim": "...", "issue": "...", "suggested_fix": "..."}}],
  "defects": [{{"scene": <int>, "shot": "<id or null>", "problem": "...", "severity": "fatal|high|medium|low", "action": "..."}}],
  "title_recommendations": ["t1","t2","t3"],
  "thumbnail_recommendation": {{"timestamp": "<mm:ss>", "description": "..."}},
  "overall_assessment": "<2-4 sentences>"
}}

SCRIPT (scene index: narration):
{script}

SHOT TIMELINE:
{timeline}

Be specific. Reference timestamps. Prioritize fixes by impact."""

FRAME_DESC_PROMPT = """Describe each sampled frame from a documentary video in ONE concise sentence: subject, style (photorealistic render / animation / diagram / stock photo / illustration), colors, any text/UI, and any artifact (mirrored edges, smearing, black frame, letterbox bars). Output STRICT JSON: {"frames": [{"t": <sec>, "desc": "..."}]}"""


def _b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            return json.loads(text[s:e + 1])
        raise RuntimeError(f"non-JSON: {text[:200]}")


def _load_script(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("scenes") or data.get("final_scenes") or []
    lines = []
    for i, s in enumerate(data):
        if isinstance(s, dict):
            lines.append(f"SCENE {i} [{s.get('title','')}]: {s.get('narration','')}")
        else:
            lines.append(f"SCENE {i}: {s}")
    return "\n".join(lines)


def _load_timeline(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path) as f:
        d = json.load(f)
    vt = d.get("video_timeline", [])
    if not isinstance(vt, list):
        return ""
    rows = []
    for s in vt:
        rows.append(f"{s.get('start_time',0):.1f}-{s.get('end_time',0):.1f}s scene{s.get('scene_id')} [{s.get('shot_type')}] {s.get('asset_source')} cam={s.get('camera_move','')}")
    return "\n".join(rows)


def extract_frames(video, outdir, interval=5.0, width=960):
    os.makedirs(outdir, exist_ok=True)
    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", video]).strip())
    n = max(1, int(dur // interval))
    files = []
    for i in range(n + 1):
        t = round(i * interval, 1)
        out = os.path.join(outdir, f"f_{int(t):04d}.jpg")
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", video,
                            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", out],
                           check=True)
        files.append((t, out))
    return files


def gemini_call(contents_parts, model_chain, max_retries=3):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    last = None
    for model in model_chain:
        for attempt in range(max_retries):
            try:
                resp = client.models.generate_content(model=model, contents=contents_parts)
                if resp.text:
                    return model, resp.text
                last = Exception(f"{model}: empty response")
            except Exception as e:  # noqa: BLE001
                last = e
                print(f"  !! {model} attempt {attempt+1}: {str(e)[:110]}")
                time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"all gemini models failed: {str(last)[:120]}")


def zai_call(prompt, max_tokens=5000):
    import urllib.request
    key = os.environ.get("ZAI_API_KEY")
    body = {
        # glm-5.3-flash always thinks: no "thinking" field, generous max_tokens.
        "model": os.environ.get("ZAI_MODEL", "glm-5.3-flash"),
        "messages": [
            {"role": "system", "content": "You are a rigorous documentary executive producer. Respond only in strict JSON."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4").rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            print(f"  !! zai attempt {attempt+1}: {str(e)[:120]}")
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("zai failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--timeline", default=None)
    ap.add_argument("--audio-diag", default=None)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--providers", default="gemini,zai")
    ap.add_argument("--gemini-models", default="gemini-2.5-flash,gemini-3.5-flash,gemini-3-flash-preview")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    script_text = _load_script(args.script)
    timeline_text = _load_timeline(args.timeline)
    audio_diag = ""
    if args.audio_diag and os.path.exists(args.audio_diag):
        with open(args.audio_diag) as f:
            audio_diag = f.read()[:6000]

    print("extracting frames...")
    frames = extract_frames(args.video, args.frames)
    print(f"  {len(frames)} frames")

    meta = {"video": args.video, "ts": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    reports = {}

    if "gemini" in args.providers:
        print("=== GEMINI DETAILED REVIEW ===")
        prompt = DETAILED_PROMPT.format(script=script_text[:14000], timeline=timeline_text[:8000], audio_diag=audio_diag)
        content = [prompt]
        for t, fp in frames:
            content.append(f"FRAME t={t}s:")
            content.append(types_part(fp))
        model, out = gemini_call(content, args.gemini_models.split(","))
        review = _parse_json(out)
        review["_meta"] = {"provider": "gemini", "model": model, **meta}
        with open(os.path.join(args.out, "review_gemini.json"), "w") as f:
            json.dump(review, f, indent=2)
        reports["gemini"] = review
        print(f"  score {review.get('quality_score')}/100 ({model})")

        # frame descriptions for ZAI GLM
        print("=== GEMINI FRAME DESCRIPTIONS ===")
        dcontent = [FRAME_DESC_PROMPT]
        for t, fp in frames:
            dcontent.append(f"FRAME t={t}s:")
            dcontent.append(types_part(fp))
        _, dout = gemini_call(dcontent, args.gemini_models.split(","))
        try:
            descs = _parse_json(dout).get("frames", [])
        except Exception:  # noqa: BLE001
            descs = []
        with open(os.path.join(args.out, "frame_descriptions.json"), "w") as f:
            json.dump(descs, f, indent=2)
        print(f"  {len(descs)} frame descriptions")

    if "zai" in args.providers:
        print("=== ZAI GLM DETAILED REVIEW ===")
        desc_path = os.path.join(args.out, "frame_descriptions.json")
        descs = []
        if os.path.exists(desc_path):
            with open(desc_path) as f:
                descs = json.load(f)
        vt = "\n".join(f"[{d.get('t')}s] {d.get('desc')}" for d in descs)
        prompt = DETAILED_PROMPT.format(script=script_text[:14000], timeline=timeline_text[:8000], audio_diag=audio_diag)
        prompt += "\n\nVISUAL TRANSCRIPT (frame descriptions):\n" + (vt or "(none)")
        out = zai_call(prompt)
        review = _parse_json(out)
        review["_meta"] = {"provider": "zai", "model": os.environ.get("ZAI_MODEL", "glm-5.3-flash"), **meta}
        with open(os.path.join(args.out, "review_zai.json"), "w") as f:
            json.dump(review, f, indent=2)
        reports["zai"] = review
        print(f"  score {review.get('quality_score')}/100")

    print("\n=== SUMMARY ===")
    for k, r in reports.items():
        print(f"{k}: {r.get('quality_score')}/100 conf {r.get('confidence')}")
        dims = r.get("dimensions", {})
        for name, d in dims.items():
            print(f"  {name}: {d.get('score')}/10")
        vj = r.get("voice_jitter_report", {})
        print(f"  voice_jitter confirmed={vj.get('confirmed')} timestamps={vj.get('timestamps')}")
        for rec in r.get("prioritized_recommendations", [])[:8]:
            print(f"  [{rec.get('priority','?').upper()}][{rec.get('category','?')}] {rec.get('recommendation','')[:140]}")


def types_part(fp):
    from google.genai import types
    with open(fp, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")


if __name__ == "__main__":
    main()
