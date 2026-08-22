# Postmortem — 6174: the number that eats every other number
**When:** 2026-08-16T10:25:14+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 15 shots, providers={'pexels': 10, 'generated': 5}
- ffmpeg sidechain music ducking (bed=cinematic.mp3)
- Gemini Flash end-to-end review score 68/100

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
- Replace the generic space footage with dynamic, on-screen mathematical animations (such as Manim-style motion graphics) 
- Establish a consistent visual theme. If using real-world footage, stick to a unified aesthetic (e.g., minimalist academi
- Increase the energy and pacing of the narration. The current delivery is slightly robotic and slow, which hurts audience

## Benchmark results
```json
{
  "llm": "gemini37",
  "renderer": "moviepy+ffmpeg",
  "tts": "kokoro bm_george",
  "video_review_model": "gemini-2.5-flash",
  "music_mix": "ffmpeg sidechaincompress"
}
```

## Metrics
```json
{
  "final_score": 68,
  "render_iterations": 1,
  "shots": 15,
  "fallbacks": 0,
  "duration_s": 56.9
}
```
