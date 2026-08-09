# Postmortem — The Bloop: the sound that shook the ocean
**When:** 2026-08-09T05:35:44+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 26 shots, providers={'manim': 3, 'pexels': 15, 'nasa': 8}
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
- Replace space, galaxy, and astronaut footage with underwater ocean, sonar, and glacier/iceberg calving visuals.
- Fix the TTS voiceover to correctly pronounce coordinates: 'fifty degrees South, one hundred degrees West' instead of 'fi
- Remove the picture-in-picture layout style; scale all primary visuals to fill the entire 16:9 frame.

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
  "final_score": 45,
  "render_iterations": 1,
  "shots": 26,
  "fallbacks": 0,
  "duration_s": 104.2
}
```
