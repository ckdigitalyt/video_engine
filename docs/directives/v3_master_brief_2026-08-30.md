# OpenClaw Master Brief — Holistic Video Engine Upgrade + Fresh Production
_Received via Discord #math-motion from ckdigital, 2026-08-30 09:22 UTC. Verbatim external directive._

You are responsible for implementing the next-generation version of the autonomous YouTube video-generation system end to end.
This is not a request for a superficial refactor. Treat it as an architectural upgrade of the entire video-production algorithm.
The current system has reached a visual ceiling because it is effectively:
script → deterministic Manim scenes → narration → FFmpeg
That architecture must now evolve into a multi-renderer, AI-directed video production system.
The attached/current latest video should be treated as the baseline to improve against. Do not simply make another Manim video with more transitions.

## 1. Primary objective
Build a production system in which OpenClaw acts as a creative director, not merely a script generator.
The agent must be able to decide, shot by shot, which visual medium is best:
- AI-generated video
- AI-generated still image + procedural motion
- stock/archival footage
- Motion Canvas animation
- PixiJS 2D/cartoon animation
- Manim mathematical/scientific visualization
- optionally Godot or another specialist renderer where genuinely useful

The final video should feel like a professionally designed YouTube video, not like an automated presentation.
The architecture must be renderer-agnostic and future-proof.
Do not hard-code the system around one AI video model.

## 2. Non-negotiable principles
### A. Manim is no longer the default renderer
Keep Manim because it is excellent for: equations, graphs, geometry, mathematical constructions, scientific diagrams, precise quantitative explanations. But it must become a specialist renderer, not the visual language of the entire video.

### B. Visual variety is mandatory
Do not allow long sequences of visually similar scenes.
Introduce an explicit visual-variety policy.
Starting policy:
- avoid identical compositions for more than ~2–3 seconds
- use pattern interrupts frequently
- alternate shot scale
- alternate camera behaviour
- alternate visual medium
- use occasional hero shots
- use kinetic typography where appropriate
- use character/cartoon motion where appropriate
- use real footage when it improves authenticity
Narrative coherence overrides arbitrary cutting.

### C. AI video is a component, not the whole pipeline
Use expensive AI video generation only for high-value hero shots.
The rest should use: procedural animation, stock footage, AI stills, motion graphics, diagrams, archival material, simple character animation.

## 3. Target architecture
Implement this conceptual flow:
OPENCLAW → RESEARCH → TOPIC / VIRAL ANGLE ANALYSIS → SCRIPT → STORY STRUCTURE → SHOT PLAN → VISUAL DIRECTOR → ASSET PLANNER → RENDERER ROUTER → INDIVIDUAL SHOT GENERATION → SHOT QA → ASSEMBLY → AUDIO MASTERING → FULL VIDEO QA → RETENTION / VIRALITY CRITIC → REWRITE / RECUT IF NECESSARY → FINAL VIDEO

The renderer router should support:
AI_VIDEO AI_IMAGE STOCK_VIDEO ARCHIVAL MOTION_CANVAS PIXIJS MANIM GODOT OPEN_TOONZ CUSTOM

## 4. Create a formal Shot abstraction
Stop treating the video as a collection of generic "scenes".
Create a first-class Shot representation. Every shot should contain at least:
```json
{
 "shot_id": "S07",
 "duration_sec": 3.8,
 "narration_start": 18.2,
 "narration_end": 22.0,
 "narrative_role": "reveal",
 "visual_goal": "show the asteroid impact with escalating scale",
 "renderer": "AI_VIDEO",
 "style": "cinematic_documentary",
 "subject": "...",
 "background": "...",
 "camera": "...",
 "motion": "...",
 "composition": "...",
 "text_overlay": "...",
 "sfx": ["impact", "rumble"],
 "music_state": "build",
 "asset_requirements": [],
 "generation_priority": "high",
 "fallback_renderer": "AI_IMAGE",
 "qa_requirements": []
}
```
Do not let the LLM directly improvise implementation details everywhere.
The LLM creates the VisualSpec. The renderer implements it deterministically.

## 5. Introduce a renderer-selection algorithm
Build an explicit renderer-selection layer. The planner should evaluate every shot against:
- realism required? physical motion required? mathematical precision required?
- character interaction? emotional impact? historical authenticity?
- diagrammatic explanation? camera movement? text-heavy?
- generation cost? availability? quota? expected visual value?

Examples:
- mathematical proof → MANIM
- exploding volcano → AI_VIDEO
- historic dinosaur reconstruction → AI_VIDEO / ARCHIVAL
- simple explanatory diagram → MOTION_CANVAS
- cartoon conversation → PIXIJS
- scientist looking at fossil → AI_IMAGE + MOTION_CANVAS
- NASA launch → ARCHIVAL/STOCK
- abstract visual metaphor → AI_IMAGE / AI_VIDEO
- kinetic headline → MOTION_CANVAS

The system must choose automatically.

## 6. Motion Canvas implementation
Add Motion Canvas as a first-class renderer. Use it for: kinetic typography, vector illustrations, infographic animation, arrows and callouts, maps, timelines, diagram animation, character-like simple rigs, animated icons, camera moves, layered parallax, voice-synchronised educational sequences.
Use TypeScript. Build reusable templates rather than generating arbitrary one-off animation code every time:
```
motion/
  templates/
    kinetic_title/ timeline/ map_zoom/ infographic/ comparison/ diagram/
    callout/ number_counter/ scientific_process/ character_intro/
    quote_card/ before_after/ reveal/ zoom_sequence/
```
The system should be able to instantiate templates from structured JSON.

## 7. PixiJS implementation
Add PixiJS as a second procedural renderer for visually rich 2D/cartoon/game-like sequences. Prioritize: sprites, parallax, particles, camera movement, cutout-style characters, simple facial animation, object interaction, explosions, atmospheric effects, cartoon environments, game-style worlds.
Build a reusable scene framework so the LLM can describe (JSON) e.g.:
```json
{
  "background": "prehistoric jungle",
  "characters": [{ "type": "t_rex", "position": [0.6, 0.7], "action": "run" }],
  "camera": { "move": "push_in", "duration": 2.5 }
}
```

## 8. Keep Manim but narrow its role
Do not delete the existing Manim infrastructure. Refactor it behind the same renderer interface.
Manim remains for: equations, geometry, charts, scientific models, orbital mechanics, mathematical transformations, quantitative comparisons.
A video should never default to Manim simply because the topic is scientific.

## 9. AI media broker
Create a new abstract service: AI Media Broker. It must hide model/provider details from the rest of the system.
Interface: generate_image(...), generate_video(...), image_to_video(...), edit_image(...), check_provider_health(...), get_quota(...), get_capabilities(...)
The video planner should request generate_high_value_hero_shot(...) rather than use_model_X(...).

## 10. Hugging Face ZeroGPU integration
Implement Hugging Face Gradio/ZeroGPU support as a provider:
1. discover/validate the target Space
2. inspect /gradio_api/info or OpenAPI metadata
3. determine available endpoints
4. upload local assets when necessary
5. submit generation jobs
6. poll asynchronously
7. handle queueing
8. download results
9. validate output
10. cache successful outputs
11. retry intelligently
12. fail over to another model/provider
Do not hard-code endpoint names without checking them. Use HF token where available. Never expose the token in logs. Do not depend on anonymous quotas.

## 11. AI video provider strategy
- MiniMax H3: cinematic hero shots, complex scene motion, high-value narrative moments. Shot generator, not complete-video generator.
- Wan 2.2: image-to-video, strong visual motion, alternative hero shots, fallback when H3 unavailable.
- LTX family: alternative video generation, image-to-video, motion-heavy shots, fallback provider.
- Continuously monitor open-source ecosystem; make adding a new provider trivial.
Create: providers/ hf/ minimax/ wan/ ltx/ future_provider/
Do not run GPU-oriented large models locally on the Oracle CPU server.

## 12. AI image generation must become a first-class capability
AI_IMAGE → MOTION is a major path: slow camera push, parallax, depth layers, particles, atmosphere, lighting changes, typography, image-to-video. Prefer this when full AI video generation would be wasteful.

## 13. Asset system
Support: Pexels, Pixabay, NASA, Wikimedia Commons, Internet Archive, other legally usable archival sources.
For every externally sourced asset store metadata: source, URL, asset_id, license, download_date, creator, attribution_required, usage_notes.
Never publish an asset if the license cannot be established.
Deterministic asset cache.

## 14. Local reusable asset library
Local library of: SVG illustrations, icons, characters, backgrounds, props, particles, UI elements, maps, arrows, callouts, cartoon assets. Prefer reusable local assets when they produce a better result than repeatedly generating AI imagery.

## 15. Storytelling algorithm
Begin with "Why should a viewer care enough to continue watching?"
Each video: Hook (first few seconds create curiosity/surprise/emotion/question), Promise, Escalation, Pattern interrupts, Reveal, Payoff, Optional callback.
Avoid generic introductions ("In this video, we are going to explore…").

## 16. Build an explicit visual budget
Before rendering, calculate a target mix, e.g.:
```json
{ "hero_ai_video_shots": 3, "ai_image_motion_shots": 5, "stock_or_archival_shots": 7, "motion_canvas_shots": 7, "pixijs_shots": 3, "manim_shots": 2, "pattern_interrupts": 8 }
```
Numbers are examples; the director may change them per topic. Purpose: prevent drift into repetitive output.

## 17. Visual continuity and style system
Introduce a VideoStyleSpec: style_name, palette, typography, camera_language, lighting, texture, motion_language, transition_language, character_style, caption_style. Every renderer must receive this style context.

## 18. Audio upgrade
Keep the existing deterministic audio pipeline (Fish Audio when usable, Chatterbox, Kokoro, Edge-TTS fallback, local SFX synthesis, FFmpeg mastering). Make audio part of the shot plan: per-shot music_state, sfx, duck_music_db. Audio should reinforce visual changes.

## 19. Automated QA
For every rendered shot check:
- Technical: frame rate, resolution, duration, audio presence, codec compatibility, corrupted frames, black frames, unexpected silence
- Visual: correct subject, no obvious generation artifacts, no distorted anatomy, no hallucinated text, no irrelevant objects, no severe continuity errors
- Temporal: shot matches narration, visual event timing, caption alignment, no dead visual time
- Editorial: sufficient visual change, no repetitive composition, no long static shots, strong hook, climax stronger than middle
- Platform: at least 16:9 YouTube; 9:16 Shorts/Reels/TikTok when feasible

## 20. Vision QA must inspect representative frames
Sample: opening, every shot, transitions, major reveals, end card, thumbnail candidates. Use the available vision model/provider. Record structured findings: { shot_id, score, issues[], action }.

## 21. Introduce creative QA
A second critic focused purely on audience retention: Would a stranger stop scrolling? Is the opening immediately understandable? Does each shot add information or emotion? Is anything visually boring or unnecessarily complicated? Is there a reason to continue watching? Is the ending satisfying? Is the video visually distinctive from generic AI content?
Do not confuse factual correctness with entertainment quality.

## 22. Automatic regeneration loop
Selectively regenerate bad shots only; reassemble; full QA. Maintain versioning: video_01, video_01_r1, video_01_r2. Preserve best-performing shot versions.

## 23. Performance constraints
Oracle server: ~4 CPU, 24 GB RAM, no local high-end GPU. Oracle does: orchestration, research, planning, asset management, procedural rendering, FFmpeg, QA, caching, API calls. Remote GPU services for expensive AI generation. Local CPU rendering must remain viable when all remote AI services are unavailable.

## 24. Offline degradation strategy
Fallback chain: AI_VIDEO → AI_IMAGE + MOTION → STOCK_VIDEO → MOTION_CANVAS → PIXIJS → MANIM. The pipeline must not collapse.

## 25. Caching
Cache all: research results, generated images, generated videos, TTS audio, SFX, stock assets, rendered shots, QA results. Deterministic hashes based on: prompt, model, seed, input asset, style spec, duration, aspect ratio, renderer version.

## 26. Cost control
Shot-level generation budget: LOW / MEDIUM / HIGH / HERO. Only HIGH and HERO shots should normally consume scarce remote video-generation resources.

## 27. Fresh test production
After implementing the architecture, create a real publishable video on "Why Did the Dinosaurs Die?" — approximately 2–4 minutes, 16:9 master, YouTube-ready, visually rich, documentary/cinematic style, strong opening, multiple visual modes, no long static Manim sequences. Also produce a 9:16 version if the pipeline can do so without compromising the 16:9 master.

## 28. Important factual direction for the dinosaur video
Do not oversimplify into "An asteroid killed all the dinosaurs." Distinguish the dominant Chicxulub impact explanation from other factors. Cover: what happened ~66 Mya; what/where Chicxulub was; why globally devastating; atmospheric/environmental effects; darkness/cooling and ecosystem disruption; food-chain collapse; why some organisms survived; evidence connecting extinction to impact; role of volcanism/longer-term stress; why birds survived while non-avian dinosaurs did not. Do not present uncertainties as settled facts. Citations/source metadata internally for all major claims.

## 29. Dinosaur-video visual strategy
HOOK → cinematic dinosaur world → unexpected statement → asteroid approaching Earth → close-up impact sequence → flash/shockwave → Earth atmosphere animation → global darkness → food-chain collapse → timeline animation → fossil/evidence visual → impact crater map → scientific comparison → survivor sequence → bird/dinosaur lineage reveal → strong conclusion. Renderer mix deliberately varied (AI_VIDEO, AI_IMAGE+PARALLAX, PIXIJS, MOTION_CANVAS, ARCHIVAL/SCIENTIFIC, MANIM, AI_VIDEO, MOTION_CANVAS, PIXIJS, AI_IMAGE, AI_VIDEO). Do not force this exact sequence; the visual director should improve it.

## 30. Hook requirement for the dinosaur video
Reject generic openings. Prefer curiosity-driven openings of the type: "The asteroid didn't kill the dinosaurs. What came next did." or "For 160 million years, dinosaurs ruled Earth. Then, in a matter of hours, their world changed forever." The exact final hook must be independently researched and creatively selected. The opening must be visually powerful within the first seconds.

## 31. Thumbnail generation
Generate at least 4 thumbnail concepts. Score for: curiosity, visual simplicity, face/subject recognizability, contrast, readability at mobile size, emotional impact. Not too much text. Save the best one.

## 32. Title generation
Generate several title concepts. Avoid bland documentary wording. Variants around: curiosity, mystery, scale, contradiction, "what really happened", survival, final hours, asteroid aftermath. No misleading clickbait.

## 33. Deliverables
1. Updated source code 2. Updated renderer architecture 3. Updated OpenClaw configuration 4. Documentation 5. Renderer capability registry 6. AI-provider registry 7. Shot/VisualSpec schemas 8. QA reports 9. Dinosaur video 10. Dinosaur thumbnail candidates 11. Dinosaur title candidates 12. Final publish-readiness report

## 34. Publish-readiness gate
TECHNICAL QA PASS, AUDIO QA PASS, FACTUAL QA PASS, VISUAL QA PASS, TEMPORAL QA PASS, STYLE QA PASS, VARIETY QA PASS, RETENTION CRITIC PASS, MONETIZATION/ASSET QA PASS. If it does not pass, continue improving the failed components.

## 35. Most important success criterion
The final dinosaur video must be qualitatively different from the previous Manim-heavy video. A viewer should NOT reasonably describe it as "an animated presentation". It should feel closer to "a professionally edited mini-documentary created by an AI production studio."
Use whatever combination of open-source/local/remote/free infrastructure is necessary. Replace weak components when a better approach is available. Do not ask permission for routine implementation decisions. Make the architecture robust, modular, observable and extensible.
At the end report: (1) what changed (2) renderers implemented (3) external AI providers successfully tested (4) what failed and why (5) exact renderer mix in the dinosaur video (6) QA scores (7) remaining weaknesses (8) next highest-value improvement.
Most importantly: do the implementation, then actually generate the dinosaur video through the upgraded pipeline. Do not stop after producing an architecture document or prototype.
