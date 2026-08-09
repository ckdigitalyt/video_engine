# Postmortem — The 52-Hertz Whale: the loneliest voice in the ocean
**When:** 2026-08-09T11:10:23+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=True)
- director beat mode: 30 shots, providers={'manim': 4, 'pexels': 16, 'placeholder': 7, 'emergency': 3}
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
- Revise the script to correct grammatical errors and word choices. Specifically, change 'no one seen it' to 'no one has s
- Replace all irrelevant visuals (0:06-0:13 bar chart, 0:14-0:17 alien, 0:34-0:35 moon, 0:45-0:52 iceberg/rope) with high-
- Establish and maintain a consistent visual style and color palette throughout the video. Avoid jarring shifts between di
- Improve transitions between scenes. Utilize smoother techniques like dissolves, subtle wipes, or thematic cuts instead o
- Ensure burned-in subtitles are perfectly synchronized with the narration and reflect the corrected script, including gra

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
  "render_iterations": 2,
  "shots": 30,
  "fallbacks": 10,
  "duration_s": 64.6
}
```
