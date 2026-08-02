# Postmortem — Voyager 1: the farthest human-made object
**When:** 2026-08-02T07:14:12+00:00

## Techniques that worked
- multi-reviewer script review (3 passes, gate=False)
- director beat mode: 13 shots, providers={'manim': 1, 'pexels': 8, 'nasa': 3, 'placeholder': 1}
- ffmpeg sidechain music ducking (bed=cinematic.mp3)
- Gemini Pro end-to-end review score 72/100

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
- Remove the black screen at 00:39 and the blue screen at 00:46. Replace with continuous space b-roll or cross-dissolves b
- Replace the footage at 00:16 with actual NASA imagery or CGI of Jupiter and Saturn to align with the narration.
- Replace the final shot (00:51) with a wide shot of the Voyager probe drifting into the deep void to maintain the 'inters
- Add stylized subtitles to improve accessibility and emphasize key data like '25 billion kilometers' and '17 kilometers p

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
  "final_score": 72,
  "render_iterations": 3,
  "shots": 13,
  "fallbacks": 1,
  "duration_s": 52.036009
}
```
