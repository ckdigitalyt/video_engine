# Postmortem — paradox
**When:** 2026-08-16T06:45:52+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 8 shots, providers={'pexels': 8}
- ffmpeg sidechain music ducking (bed=cinematic.mp3)
- Gemini Flash end-to-end review score 35/100

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
- Animate the vector illustrations to dynamically demonstrate the paradoxes, such as showing Achilles and the tortoise or 
- Remove or relocate the 'Like Share Subscribe' text overlay so it does not clash with the main subtitles and narration.
- Expand the script and video length to at least 60 seconds to properly introduce, explain, and resolve (or leave open) ea

## Benchmark results
```json
{
  "llm": "gemini",
  "renderer": "moviepy+ffmpeg",
  "tts": "kokoro bm_george",
  "video_review_model": "gemini-2.5-flash",
  "music_mix": "ffmpeg sidechaincompress"
}
```

## Metrics
```json
{
  "final_score": 35,
  "render_iterations": 1,
  "shots": 8,
  "fallbacks": 0,
  "duration_s": 9.0
}
```
