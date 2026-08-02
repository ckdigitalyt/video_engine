# Postmortem — Voyager 1: the farthest human-made object
**When:** 2026-08-02T08:04:14+00:00

## Techniques that worked
- multi-reviewer script review (3 passes, gate=False)
- director beat mode: 15 shots, providers={'manim': 2, 'pexels': 12, 'nasa': 1}
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
- Re-record the narration to correctly pronounce 'Io' as 'Eye-oh' and clarify if 'U.S.' should be 'U-S' or 'us'.
- Replace the beach (00:19) and camera (00:09) clips with archival footage of the Voyager launch or mission control at JPL
- Incorporate actual NASA flyby images of Io's volcanoes and Saturn's rings at 00:21 to match the specific claims in the s
- Replace the black vinyl record at 00:57 with a high-quality image or 3D model of the actual Voyager Golden Record.
- Add subtitles to improve accessibility and help viewers follow the technical data (distances and dates).

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
  "render_iterations": 3,
  "shots": 15,
  "fallbacks": 0,
  "duration_s": 69.799002
}
```
