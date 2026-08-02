# Postmortem — voyager 1  the farthest human made object
**When:** 2026-08-02T05:53:03+00:00

## Techniques that worked
- resumed from stage 13 after render (review model fallback chain)
- Gemini review (model=None) score 72/100
- ffmpeg sidechain music ducking (bed=cinematic.mp3)

## Techniques that failed
- gemini-2.5-pro quota 429 on free tier — fallback to 3.5-flash

## Prompt improvements
- review prompt asks for timestamps + prioritized categories

## Visual improvements
_(none recorded)_

## Narration improvements
_(none recorded)_

## Rendering optimizations
_(none recorded)_

## Review feedback
- Replace the Space Shuttle launch at 00:29 with archival footage of the Titan IIIE-Centaur rocket used for the Voyager mi
- Replace the generic satellite at 01:14 with a high-quality 3D model or accurate illustration of Voyager 1 to maintain te
- Eliminate the 'picture-in-picture' style with black backgrounds (e.g., 00:04, 00:13, 01:08, 01:22). Use full-screen cine
- Replace the galaxy evolution chart at 00:41 with a diagram of the Voyager 1 trajectory or the Golden Record's pulsar map

## Benchmark results
```json
{
  "video_review_model": null,
  "music_mix": "ffmpeg sidechaincompress"
}
```

## Metrics
```json
{
  "final_score": 72,
  "render_iterations": 1,
  "duration_s": 126.038005
}
```
