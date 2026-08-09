# Postmortem — The 52-Hertz Whale: the loneliest voice in the ocean
**When:** 2026-08-09T12:28:28+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 45 shots, providers={'manim': 3, 'placeholder': 23, 'pexels': 17, 'emergency': 2}
- ffmpeg sidechain music ducking (bed=cinematic.mp3)
- Gemini Flash end-to-end review score 45/100

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
- Replace all irrelevant stock footage (e.g., 0:07-0:12, 0:15-0:26, 0:26-0:30, 0:37-0:45, 0:49-0:56, 1:44-1:47) with visua
- Establish a consistent visual style throughout the documentary. Decide whether the primary aesthetic is abstract, realis
- Integrate more actual footage or high-quality CGI of whales, underwater environments, and scientific equipment (like hyd
- Re-time cuts and transitions to align seamlessly with the narration, ensuring visuals support the spoken word rather tha
- Refine the on-screen text presentation. While effective, ensure its style and background are consistent and visually app

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
  "final_score": 45,
  "render_iterations": 1,
  "shots": 45,
  "fallbacks": 25,
  "duration_s": 119.266667
}
```
