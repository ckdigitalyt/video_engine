# Postmortem — Voyager 1: the farthest human-made object
**When:** 2026-08-02T06:48:13+00:00

## Techniques that worked
- multi-reviewer script review (3 passes, gate=False)
- director beat mode: 16 shots, providers={'manim': 1, 'pexels': 12, 'nasa': 3}
- ffmpeg sidechain music ducking (bed=cinematic.mp3)
- Gemini Pro end-to-end review score 62/100

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
- Replace the coastline at 0:14 and the astronaut at 0:52 with actual NASA archival footage of the Voyager launch or CGI m
- Remove the alien figure at 0:26. Replace with a montage of the actual images encoded on the Golden Record to better refl
- At 0:39, replace the red nebula streak with a visualization of the heliosphere or plasma waves to match the 'plasma dens
- Add high-quality burned-in subtitles to improve accessibility and retention for mobile viewers.

## Benchmark results
```json
{
  "llm": "deepseek",
  "renderer": "moviepy+ffmpeg",
  "tts": "kokoro bm_george",
  "video_review_model": "gemini-2.5-pro",
  "music_mix": "ffmpeg sidechaincompress"
}
```

## Metrics
```json
{
  "final_score": 62,
  "render_iterations": 1,
  "shots": 16,
  "fallbacks": 0,
  "duration_s": 61.765011
}
```
