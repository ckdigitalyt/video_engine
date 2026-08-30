# OpenClaw V4 Directive — Creative Quality / AI Cinematography Upgrade
_Received via Discord #math-motion from ckdigital, 2026-08-30 18:18 UTC. Verbatim external directive. User note: use GLM flash going forward (much cheaper)._

The V3 architecture is accepted as the baseline.
Do NOT redesign the entire system again.
The next objective is to make the system capable of producing a genuinely publishable YouTube video, not merely a technically valid multi-renderer video.
The V3 dinosaur video is the mandatory baseline and must be critically analyzed before implementation.
The V3 architecture is technically impressive, but the output still visually behaves like an animated slideshow.
The primary objective of V4 is therefore:
Convert the system from a multi-renderer video assembler into an AI-directed cinematography system.

## 1. Start by auditing the actual V3 output
Before changing code, inspect: the actual MP4 metadata, every shot, shot duration, renderer, source asset, motion type, narration alignment, actual frame-to-frame visual change, black/title-card duration, repeated imagery, visual entropy/novelty.
Do NOT rely only on publish_gate.json. Compare the actual artifact with the reported metadata.
In particular: The V3 report says 1920×1080, but the delivered master artifact currently appears as 910×512. Find the root cause. A publish gate must verify the actual final artifact with ffprobe. The declared specification and the actual MP4 must match.

## 2. Create a new metric: VISUAL EVENT DENSITY
A shot should score higher when meaningful visual events occur (object enters/exits, camera movement, subject movement, environmental change, lighting change, scale change, spatial reveal, interaction, transformation, text transformation, impact, reaction, transition, compositional change).
A slow zoom on an unchanged image should score extremely low. A meaningful object transformation should score high.

## 3. Add STATIC-HOLD detection
Detect when visual content remains effectively unchanged for too long. For AI_IMAGE_MOTION shots distinguish: true_motion, pseudo_motion, static_hold. Ken Burns alone is NOT dynamic. Rule: static_hold > 2.5 sec triggers a warning (longer only if narration is highly explanatory and justified).

## 4. Introduce MICRO-SHOT decomposition
Add Shot → MicroEvents. Example:
```json
{ "shot_id": "S12", "duration": 6.0, "micro_events": [ { "t": 0.0, "duration": 1.5, "event": "asteroid enters frame" }, { "t": 1.5, "duration": 1.2, "event": "camera accelerates toward Earth" } ] }
```
The renderer should implement those events.

## 5. Change the AI director's planning question
STEP 1 Narrative event — what is happening? STEP 2 Viewer perception — what should the viewer see? STEP 3 Cinematography — how should the camera experience it? STEP 4 Motion — what physically moves? STEP 5 Renderer — which engine can create it? Renderer choice is LAST.

## 6. Add explicit cinematography fields to VisualSpec
shot_scale (wide|medium|close|macro), camera_move (static|push_in|pull_out|pan|tilt|orbit|tracking|whip|dolly|handheld), subject_motion, environment_motion, lighting_change, depth_change, visual_event, transition_in, transition_out, emotional_intent, viewer_attention_target. These must influence every renderer.

## 7. AI_VIDEO becomes the preferred renderer for HERO events
Realistic physical motion, spectacle, scale, destruction, animals, humans, natural phenomena, cinematic action, emotional reaction, environmental transformation → prefer AI video. Order: try AI_VIDEO → retry once intelligently → another AI_VIDEO provider/model → only then downgrade. Record attempted_provider, failure_reason, fallback_reason.

## 8. Test Hugging Face ZeroGPU properly
Quota-aware scheduling; discover/test multiple working Spaces; inspect Gradio API metadata; authenticate; submit async; poll; detect queue vs quota errors; distinguish provider failure from account-quota exhaustion; retry on a different Space; cache successful jobs. Free users 5 min/day; PRO 40 min/day + prepaid credits. For this dev cycle temporarily enable enough quota to actually test real AI-video generation. AI_VIDEO is not production-ready until: ≥3 successful generations, 2 distinct providers/models, 1 successful I2V, 1 successful T2V.

## 9. Add MiniMax H3 as a first-class experimental provider
Research the current official API and integration requirements directly. No unofficial downloaders. No hard-coded assumptions from old docs. Implement minimax_h3 behind the broker. Test T2V, I2V, reference/image-conditioned generation where available. NOT a mandatory dependency.

## 10. Evaluate Wan 2.2 and LTX as alternatives
Both remain behind the broker. The problem is successful production generation — fix the path and prove it. Model-appropriate prompting: for LTX, prompts must explicitly specify subject, action, environment, camera, movement, lighting, sequence.

## 11. Upgrade AI video prompting
Create a dedicated cinematic_prompt_builder generating prompts from structured VisualSpec (not free-form): e.g. "Low-angle cinematic tracking shot through a Late Cretaceous forest. A herd of hadrosaurs moves rapidly between towering cycads while a Tyrannosaurus emerges in the deep background. The camera tracks backward as the herd rushes toward lens, leaves and dust moving through foreground, warm late-afternoon sunlight filtering through vegetation, realistic animal motion, shallow depth of field, escalating urgency."

## 12. Introduce three shot classes
HERO (spectacle → AI video), EXPLANATORY (Motion Canvas/Pixi/diagrams/maps), BRIDGE (short transitions, quick stock, motion graphics, AI imagery). Targets: HERO 20–30%, EXPLANATORY 40–50%, BRIDGE 20–30%.

## 13. Reduce full-screen text cards drastically
< 1.5 sec normally; never use text cards to replace missing visuals. "Could this claim be shown instead?" If yes, show it.

## 14. Introduce PATTERN INTERRUPT logic
Significant perceptual change at least every ~5–8 seconds (live→animation, wide→close, realistic→cartoon, bright→dark, character→diagram, motion→freeze, image→AI video, camera direction reversal, major SFX, sudden typography). Narrative-aware, not arbitrary.

## 15. Improve AI_IMAGE_MOTION
Beyond image+zoom: layered depth, foreground motion, atmospheric particles, lighting animation, subject isolation, parallax, simulated camera shake, environmental motion, animated effects, masked object motion. A still image should become a 2–4 second animated scene, not a 7-second Ken Burns slide.

## 16. Build a subject-motion toolkit
Deterministic primitives: animals (run/fly/walk/head_turn/bite/roar/flock), natural (smoke/fire/dust/water/rain/lightning/clouds), camera (push/pull/orbit/pan/tilt/tracking/shake/whip), environment (wind/vegetation/particles/atmospheric haze). Layerable over AI backgrounds.

## 17. Upgrade PixiJS from "asset motion" to "scene animation"
character → action → interaction → environment → camera (not just sprite→move).

## 18. Re-score renderer selection
Add cinematic_value and visual_event_density to router scoring. A renderer that can technically depict something but not compellingly should score poorly.

## 19. Change the Publish Gate
Add gates: CINEMATIC, VISUAL_EVENT_DENSITY, STATIC_HOLD, AI_VIDEO_COVERAGE, SHOT_DIVERSITY, TEXT_CARD_OVERUSE, VISUAL_NOVELTY. The video must NOT pass simply because all technical gates pass.

## 20. Add a mandatory HUMAN-LIKE CREATIVE CRITIC
"Imagine watching this without knowing it was AI-generated. Would you continue watching?"
Output: hook_strength, visual_interest, pacing, cinematography, story_clarity, originality, would_publish, top_5_problems, recommended_cuts, recommended_new_shots. A technically valid video with a low creative score MUST fail.

## 21. Re-edit rather than merely regenerate
Preferred order: trim → shorten → rearrange → replace → regenerate.

## 22. Rebuild the dinosaur video as V2
results/dino_v2/. Same research unless improved evidence exists. 90–150 seconds. Mix targets: ≥3 real AI-video HERO shots, 4 AI-image+motion, 4 Motion Canvas, 2 PixiJS/cartoon, 2 archival/real footage, minimal text cards, zero unnecessary Manim.

## 23. Mandatory hero scenes for the dinosaur video
HERO 1 asteroid approaching Earth; HERO 2 atmospheric entry/impact; HERO 3 immediate aftermath on the surface; HERO 4 global environmental collapse. ≥3 of these should use true AI video if provider access permits.

## 24. Use visual storytelling instead of narration repetition
The visual should carry the explanation (impact plume → particles rise → camera follows upward → atmosphere darkens → cut to surface → sunlight fades), not a text label.

## 25. Science accuracy
Maintain current research standard. Do not imply asteroid = instant death of every dinosaur. Distinguish impact, atmospheric consequences, ecosystem collapse, survival filtering, bird lineage, Deccan volcanism/background stress, uncertainty where appropriate.

## 26. Thumbnail and title are secondary to video quality
Keep the current automated system; don't over-optimize titles while the video is visually weak.

## 27. Success criteria for V4
Technical gates pass. Creative critic ≥ 8.0/10. No static hold > 2.5 sec unless approved. ≥3 successful genuine AI-video shots in dino V2. No renderer repeated excessively. Text-only scenes rare. Actual MP4 metadata exactly matches declared spec. Feels like "a professionally edited animated documentary," not "a generated slideshow."

## 28. Do not stop at the code implementation
Implement → test → render → inspect → critique → revise → render again. Primary success signal: "Would we actually publish this video on a real YouTube channel?"
At the end report: exact changes, AI-video providers successfully used, successful/failed generation counts, renderer distribution, visual-event-density score, static-hold analysis, creative critic score, actual MP4 metadata, remaining weaknesses, final V4 dinosaur video path.
