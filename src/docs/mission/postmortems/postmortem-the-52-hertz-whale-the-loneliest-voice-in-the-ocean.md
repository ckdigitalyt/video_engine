# Postmortem — The 52-Hertz Whale: the loneliest voice in the ocean
**When:** 2026-08-09T13:55:55+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 43 shots, providers={'manim': 3, 'placeholder': 35, 'pexels': 4, 'emergency': 1}
- ffmpeg sidechain music ducking (bed=cinematic.mp3)
- Gemini Flash end-to-end review score 85/100

## Techniques that failed
- web search in research agent (no API key — used DeepSeek knowledge base)
- NVIDIA NIM FLUX image-gen endpoint 404 (needs endpoint refresh)

## Prompt improvements
- research prompt now requests strict JSON with value/unit/source/year schema
- script prompt enforces ~60s word budget + bans generic AI phrasing
- script review uses 4 independent personas with quality gate

## Visual improvements
_(none recorded)_

## Narration improvements
_(none recorded)_

## Rendering optimizations
_(none recorded)_

## Review feedback
- Replace irrelevant visuals (e.g., the record player at 0:33, the vintage camera at 1:17) with more thematic or abstract 
- Enhance visual relevance for generic ocean shots (e.g., 0:21, 0:45). Consider abstract visualizations of sound waves tra
- Strive for greater visual style consistency across all assets. If using AI art/stock footage, aim for a cohesive aesthet
- Extend the duration of some impactful visual segments (e.g., the whale breaching at 0:55) slightly to allow the viewer m

## Benchmark results
```json
{
  "llm": "mistral",
  "renderer": "moviepy+ffmpeg",
  "tts": "kokoro bm_george",
  "video_review_model": "gemini-2.5-flash",
  "music_mix": "ffmpeg sidechaincompress"
}
```

## Metrics
```json
{
  "final_score": 85,
  "render_iterations": 1,
  "shots": 43,
  "fallbacks": 36,
  "duration_s": 93.233333
}
```
