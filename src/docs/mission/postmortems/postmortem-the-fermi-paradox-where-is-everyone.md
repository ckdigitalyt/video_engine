# Postmortem — The Fermi Paradox: where is everyone?
**When:** 2026-08-16T12:54:44+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 19 shots, providers={'pexels': 19}
- ffmpeg sidechain music ducking (bed=cinematic.mp3)
- Gemini Flash end-to-end review score 62/100

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
- Replace microscope visual at 0:16 with radio telescope imagery.
- Eliminate the 3-second black gap between 0:50 and 0:53.
- Apply consistent color grading to unify 2D art and live footage.

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
  "final_score": 62,
  "render_iterations": 1,
  "shots": 19,
  "fallbacks": 0,
  "duration_s": 55.3
}
```
