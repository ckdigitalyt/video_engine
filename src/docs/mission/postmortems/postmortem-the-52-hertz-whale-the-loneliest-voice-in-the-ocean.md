# Postmortem — The 52-Hertz Whale: the loneliest voice in the ocean
**When:** 2026-08-09T14:49:07+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 35 shots, providers={'manim': 3, 'placeholder': 25, 'pexels': 5, 'emergency': 2}
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
- Replace the bar chart and blurry blue blob (0:11-0:19) with visuals directly related to sonar, ocean acoustics, or the U
- Remove the alien in the desert visual (0:19-0:24) entirely. This is completely irrelevant and highly distracting. Replac
- Replace the small, blurry picture-in-picture element at 0:49-0:54 with a clear animated map showing the whale's migrator
- Develop a consistent visual style. Either commit to abstract motion graphics (Manim-like) throughout, or use high-qualit
- Minimize solid color screens with text. Instead, use subtle background footage (e.g., deep ocean, abstract water texture

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
  "shots": 35,
  "fallbacks": 27,
  "duration_s": 81.266667
}
```
