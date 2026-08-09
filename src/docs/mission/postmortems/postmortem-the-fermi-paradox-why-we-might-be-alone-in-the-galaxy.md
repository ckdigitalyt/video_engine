# Postmortem — The Fermi Paradox: Why We Might Be Alone in the Galaxy
**When:** 2026-08-07T04:37:19+00:00

## Techniques that worked
- multi-reviewer script review (2 passes, gate=False)
- director beat mode: 17 shots, providers={'manim': 3, 'placeholder': 2, 'pexels': 9, 'nasa': 3}
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
- Rerecord the entire narration with a professional human voice actor. Ensure accurate pronunciation of all scientific ter
- Replace or remove all irrelevant visuals. Specifically, the blank purple screen (0:04-0:11), the bar chart (0:12-0:18), 
- Establish a consistent visual style. Decide whether to lean into abstract animations, high-quality stock footage, or a b
- Implement smoother transitions between scenes. Avoid abrupt cuts and black frames. Consider fades, wipes, or subtle anim
- Adjust visual and narration timing to allow for better pacing. The current delivery feels rushed. Allow visuals to breat

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
  "shots": 17,
  "fallbacks": 2,
  "duration_s": 56.766667
}
```
