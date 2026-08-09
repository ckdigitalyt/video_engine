#!/usr/bin/env python3
"""
review_video.py — End-to-end video review with Gemini Flash.

Uploads the rendered MP4 to Gemini (files API) and asks Gemini Flash to
review the ACTUAL video: narration, pacing, visuals, transitions, timing,
music balance, cinematography, factual accuracy, and more.  Returns a
structured JSON review used by the improvement pass.

Usage:
    python3 review_video.py results/voyager/voyager_v1.mp4 --script script.json --out review.json
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

REVIEW_PROMPT = """You are the executive producer of a world-class documentary studio.
Review this rendered documentary video END-TO-END (watch the actual video frames
and listen to the audio). Evaluate:

1. factual accuracy (compare against the script claims provided)
2. narration quality (delivery, clarity, pronunciation)
3. script effectiveness (hook, structure, curiosity, pacing)
4. audience engagement & retention
5. visual relevance (do visuals match narration?)
6. visual continuity (style consistency across shots)
7. transitions and timing
8. cinematography & animation quality (motion, Ken Burns, Manim segments)
9. music balance (does music overwhelm narration?)
10. subtitle quality (if present)
11. thumbnail recommendation (a concrete frame description + timestamp)
12. title recommendation (3 options)

Respond in STRICT JSON (no markdown fences) with this schema:
{{
  "quality_score": <int 0-100>,
  "confidence": <float 0-1>,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "prioritized_recommendations": [
    {{"priority": "critical|high|medium|low",
      "category": "pacing|transitions|music|audio_balance|color|subtitles|shot_order|zoom|story_change|fact_change|script_change|new_scene|new_asset|thumbnail|other",
      "recommendation": "<specific, actionable, parameter-level where possible>"}}
  ],
  "factual_issues": [{{"claim": "...", "issue": "...", "suggested_fix": "..."}}],
  "title_recommendations": ["t1", "t2", "t3"],
  "thumbnail_recommendation": "{{"timestamp": "<mm:ss>", "description": "..."}},
  "overall_assessment": "<2-3 sentences>"
}}

SCRIPT:
{script}

ATOMIC RUBRIC CHECKS (v12 — decoupled preference optimization): in addition
to the holistic score, sample the video at these exact timestamps and answer
each as a strict boolean.  Timecodes are relative to the video start; if a
timestamp exceeds video length, answer null.
{{
  "atomic_rubrics": [
    {{"t": "0:03", "check": "a single clear visual subject is visible", "pass": true}},
    {{"t": "0:15", "check": "the visual matches the narration playing at that moment", "pass": true}},
    {{"t": "0:30", "check": "there is camera motion or an animated element (not a frozen frame)", "pass": true}},
    {{"t": "0:45", "check": "no jarring cut or black frame", "pass": true}},
    {{"t": "1:00", "check": "narration is audible and not clipped mid-sentence", "pass": true}},
    {{"t": "1:30", "check": "visual style is consistent with the rest of the video", "pass": true}},
    {{"t": "1:45", "check": "music does not overpower the voice", "pass": true}}
  ],
  "rubric_pass_rate": <float 0-1>
}}
Answer each rubric as pass: true/false (or null if out of range).  Base the
holistic quality_score on the rubric outcomes plus your expert judgment.

Be specific. Reference timestamps where useful. Prioritize fixes by impact."""


def _upload_and_review(video_path: str, script_text: str, model: str = "gemini-2.5-flash") -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=api_key)

    print(f"→ Uploading {video_path} to Gemini...")
    upload = client.files.upload(file=video_path)
    print(f"→ Uploaded: {upload.name} ({upload.state})")

    # Wait for processing
    for _ in range(60):
        meta = client.files.get(name=upload.name)
        if meta.state.name == "ACTIVE":
            break
        time.sleep(2)
    else:
        print("! File still processing after 120s — attempting review anyway.")

    prompt = REVIEW_PROMPT.format(script=script_text[:12000])
    video_part = types.Part.from_uri(file_uri=upload.uri, mime_type=upload.mime_type)

    # v13 vision lock (free tier): Gemini 2.5 Flash first, then other Gemini
    # flash variants (all video-capable). NO text-only fallback below: video
    # review REQUIRES a multimodal model that can actually see the video.
    model_chain = [model, "gemini-3.5-flash", "gemini-3-flash-preview"]
    model_chain = list(dict.fromkeys(model_chain))  # dedupe, keep order
    last_err: Exception | None = None
    for m in model_chain:
        # Retry 429/RESOURCE_EXHAUSTED up to 4x with backoff (free-tier quota
        # is per-minute; a short wait usually clears it).
        for attempt in range(5):
            print(f"→ Reviewing with {m}..." + (f" (attempt {attempt+1}/5)" if attempt else ""))
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=[prompt, video_part],
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json",
                    ),
                )
                text = response.text or ""
                if not text.strip():
                    raise RuntimeError("empty response")
                review = _parse_review_json(text)
                review["_meta"]["model_used"] = m
                return review
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    time.sleep(15 * (attempt + 1))
                    continue
                break  # non-quota error: move to next model
            print(f"    !! {m} failed: {str(e)[:120]}")
            continue
    # v13: VISION LOCK — no text-only degradation. A script-only "review" of
    # a video the model never saw is worse than no review (it could pass a
    # broken render or reject a good one on text alone). If every Gemini flash
    # variant fails, fail loudly so the run stops instead of shipping a fake
    # review. Retry the run when Gemini quota clears (the 429 backoff above
    # already handles short free-tier quota windows).
    raise RuntimeError(
        "Video review failed: all Gemini flash variants unavailable "
        f"(last error: {last_err}). Vision-required review will NOT fall back "
        "to text-only models (Mistral/DeepSeek cannot see video)."
    )


def _parse_review_json(text: str) -> dict:
    """Defensive JSON extraction from Gemini text output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        review = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            review = json.loads(text[start:end + 1])
        else:
            raise RuntimeError(f"Gemini returned non-JSON review: {text[:300]}")
    review.setdefault("_meta", {})
    return review


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="Path to rendered MP4")
    ap.add_argument("--script", default=None, help="JSON with scenes (for fact check)")
    ap.add_argument("--out", default=None, help="Output review JSON path")
    ap.add_argument("--model", default="gemini-2.5-flash")
    args = ap.parse_args()

    script_text = ""
    if args.script and os.path.exists(args.script):
        with open(args.script) as f:
            data = json.load(f)
        scenes = data.get("scenes") or data.get("final_scenes") or []
        script_text = "\n".join(f"SCENE {i}: {s}" for i, s in enumerate(scenes))

    t0 = time.time()
    review = _upload_and_review(args.video, script_text, model=args.model)
    elapsed = time.time() - t0

    review["_meta"] = {"video": args.video, "model": args.model,
                       "elapsed_s": round(elapsed, 1)}
    out = args.out or (os.path.splitext(args.video)[0] + "_review.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(review, f, indent=2)

    print(f"\n=== GEMINI VIDEO REVIEW ({args.model}) ===")
    print(f"Quality score: {review.get('quality_score')}/100 (confidence {review.get('confidence')})")
    print(f"Strengths: {len(review.get('strengths', []))} | Weaknesses: {len(review.get('weaknesses', []))}")
    recs = review.get("prioritized_recommendations", [])
    print(f"Recommendations: {len(recs)}")
    for r in recs[:10]:
        p = r.get("priority", "?")
        c = r.get("category", "?")
        print(f"  [{p.upper()}][{c}] {r.get('recommendation','')[:140]}")
    print(f"\nReview saved: {out} ({elapsed:.0f}s)")


if __name__ == "__main__":
    main()
