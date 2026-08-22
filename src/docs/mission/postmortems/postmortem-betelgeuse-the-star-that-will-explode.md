# Postmortem — Betelgeuse: the star that will explode
**When:** 2026-08-16T10:57:06+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 16 shots, providers={'pexels': 16}
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
- Replace the cartoon fish at 0:13 and gas giants at 0:26 and 0:47 with accurate 3D models of Earth and Betelgeuse.
- Replace the blank grey screen at 0:30 with a visual representing a glowing night sky or daylight supernova.
- Establish a unified realistic cinematic style across all scenes to improve visual continuity.

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
  "final_score": 45,
  "render_iterations": 1,
  "shots": 16,
  "fallbacks": 0,
  "duration_s": 54.4
}
```
