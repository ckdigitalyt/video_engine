# Postmortem — The 52-Hertz Whale: the loneliest voice in the ocean
**When:** 2026-08-09T09:14:51+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 43 shots, providers={'manim': 3, 'nasa': 26, 'pexels': 14}
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
- Replace all space, astronomy, and alien-themed visuals with relevant footage of oceans, marine life, sonar screens, and 
- Fix the layout scaling bugs at 0:18, 0:24, 0:28, 0:57, and 1:09 so that the video assets fill the entire 16:9 frame inst
- Re-record the narration with a professional voice actor or a more advanced AI voice model to eliminate the robotic caden
- Replace the 'Goldilocks Zone' bar chart at 0:14 with an animated spectrogram comparing the 52 Hz frequency to normal blu

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
  "shots": 43,
  "fallbacks": 0,
  "duration_s": 89.6
}
```
