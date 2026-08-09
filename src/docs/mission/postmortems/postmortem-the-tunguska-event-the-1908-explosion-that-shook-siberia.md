# Postmortem — The Tunguska Event: the 1908 explosion that shook Siberia
**When:** 2026-08-06T15:43:02+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 25 shots, providers={'pexels': 15, 'nasa': 10}
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
- Replace all visuals with relevant footage of Siberian forests, meteor animations, historical photos of the flattened tre
- Fix the layout bug causing images to render only in the top-left corner of a black screen. Ensure all visual assets are 
- Remove the alien character and space telescope graphics entirely, as they mislead the audience and detract from the hist

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
  "final_score": 35,
  "render_iterations": 2,
  "shots": 25,
  "fallbacks": 0,
  "duration_s": 64.6
}
```
