# JADE V13B DIRECTIVE — STORY-SPECIFIC VISUAL GRAMMAR (FINAL VISUAL-ARCHITECTURE UPGRADE)

Received from ckdigital via Discord #illustration-video, 2026-09-24 01:24 UTC (`Jade_Todo.txt`, verbatim below).
Status: **ACTIVE** — successor to the 2026-09-20 V13 directive; same endgame: freeze the core engine after this upgrade, then controlled YouTube production. Validation = six-story muted set, judged together.

---

Jade — deep review of the latest rendered videos cell_scale_dive and ice_slippery is complete.
The current pipeline is technically strong and substantially improved. Cache invalidation, judge hardening, contracts, vertical rendering, captions, audio normalization, factual/semantic gates, and the scale-dive architecture are working.
However, the rendered pixels reveal one remaining major algorithmic problem:
The generator still defaults too often to a recognizable presentation-template visual language rather than story-specific visual authorship.
The repeated combination is:
- beige/parchment background
- central presentation area/panel
- translucent rectangular information boxes
- black horizontal rails/dividers
- generic vector/diagram graphics
- standard bottom caption treatment
- orange highlight accents
This is visible even though the underlying story and QA metrics have improved.
The next work is therefore NOT another cosmetic pass and NOT another large collection of metrics.
OBJECTIVE
Make the visual generator answer:
"What is the most compelling visual representation of THIS idea?"
instead of:
"Which diagram/template should represent this narration?"
This is the final major visual-architecture upgrade before we freeze the core engine.

⸻

P0 — REMOVE PRESENTATION-TEMPLATE DEFAULT
The system must no longer treat the current parchment/panel/diagram/label composition as a general-purpose default.
A scene should NOT automatically become:
background → panel → diagram → label → caption
unless that structure is genuinely required by the story.
Presentation-board UI must become an occasional storytelling choice, not the channel's visual identity.
Do not simply randomize the template.
Instead make composition story-driven.

⸻

P0 — STORY-SPECIFIC VISUAL GRAMMAR
Before generating shots, the planner must determine the most appropriate visual representation for each concept.
Examples:
Biology
Prefer:
- tissue / organism / cell visual world
- membrane and internal structures
- organelles
- microscopic environments
- material/biological texture
- scale transition
- cutaway
- particle/process visualization
- transformation
Physics / mechanism
Prefer:
- recognizable physical object
- actual contact/interactions
- force/deformation
- material response
- fields/particles where appropriate
- microscopic explanation after macroscopic setup
- cause → effect
Geography / environment
Prefer:
- recognizable landscape
- terrain
- atmosphere
- geographic silhouette
- regional overlays
- weather/environmental reconstruction
- map transitions
- spatial cause/effect
History
Prefer:
- recognizable place/environment
- spatial reconstruction
- map
- movement
- timeline
- before/after state
- event reconstruction
- consequence
Engineering
Prefer:
- actual machine/object
- material geometry
- cutaway
- exploded view
- deformation
- force/load path
- internal mechanism
- failure → consequence
Everyday counterintuitive science
Prefer:
- recognizable real-world object
- obvious physical interaction
- transformation
- zoom from macro → micro
- mechanism reveal
- consequence
The planner must choose visual grammar from the subject and narration, not from a universal house template.

⸻

P0 — RICH VISUALS MUST BE PRIMARY
The desired hierarchy is:
RICH VISUAL PLATE → CAMERA / DEPTH / TRANSFORMATION → SEMANTIC OVERLAYS → DATA / LABEL / VECTOR EVIDENCE
NOT:
PROCEDURAL DIAGRAM → BOXES → LABELS → CAMERA MOTION
Current procedural graphics remain valuable, but they should normally explain or annotate a visually rich scene.
A circle/rectangle/line/arrow is an explanatory layer, not automatically the primary visual.

⸻

P0 — RICH ASSET FALLBACK HIERARCHY
When AI/custom visual generation fails, do NOT immediately downgrade to the same simple diagram template.
Use this hierarchy:
1. Rich visual plate
2. Rich procedural/vector reconstruction
3. Layered hybrid visual
4. Subject-specific technical diagram
5. Simple diagram only when the concept genuinely requires it
A deterministic fallback is allowed to preserve factual/explanatory correctness, but it must NOT be treated as visually equivalent to a successful rich plate.
Track this internally as asset quality/type, but do not create a giant new scoring system.

⸻

P0 — NO EMPTY VISUAL CONTAINERS
The latest videos contain graphical boxes/containers that sometimes occupy meaningful screen area without providing meaningful information.
Hard rule:
No empty or semantically unnecessary information boxes.
A graphical container must contain a useful:
- label
- measurement
- comparison
- state
- relationship
- process
- annotation
Otherwise remove it.
Do not reserve screen space merely because a template expects a box there.

⸻

P0 — FULL-CANVAS COMPOSITION
Do not default to a horizontal presentation board placed inside a vertical canvas.
The vertical frame should feel intentionally composed for 9:16.
Use the screen for:
- foreground/background depth
- large subject
- scale
- motion
- environmental context
- negative space for captions
- meaningful composition
Avoid large areas that feel like unused presentation chrome.

⸻

P0 — VISUAL-FIRST CAPTION PLACEMENT
The visual should be composed first.
Then captions must be placed intelligently into available negative space.
Do NOT build the visual around a caption box.
Maintain the existing caption safety/semantic QA.
A readable caption is not enough; it must also avoid making the underlying visual feel like a UI presentation.

⸻

P0 — HOOK MUST BE VISUALLY STRONG FROM FRAME 1
The first ~2 seconds are still below the required standard.
Do not allow:
- blank/near-blank opening
- generic background fade
- title-first opening
- decorative setup before the subject appears
For the opening:
show the subject / contradiction / scale / consequence immediately.
Text can support the hook.
It must not be the primary event.
Example for a scale-dive:
human eye → extreme push-in → tissue → cell
rather than:
background → title → divider → caption → eventual subject

⸻

P0 — VISUAL INFORMATION, NOT DECORATIVE MOTION
Every meaningful narration beat should cause a useful visual change.
Valid changes include:
- reveal
- transformation
- scale change
- cause/effect
- comparison
- spatial movement
- new object
- new relationship
- process progression
- material deformation
- consequence
Do NOT count these as information gain:
- zooming without new information
- panning
- number popping onto screen without visual context
- decorative particles
- generic camera movement
- boxes appearing
- stylistic transitions
The existing information-gain and redundancy concepts should remain, but keep them lightweight.

⸻

P0 — SCALE DIVE MUST BECOME A VISUAL JOURNEY
Keep the current scale-dive architecture.
But make each stage a visual world rather than merely a new diagram.
For example:
eye / tissue → cell membrane → cell interior → organelle → nucleus → DNA → molecular scale
Use rich plates, depth, texture, lighting and camera movement between stages.
Procedural scientific overlays can appear inside these scenes.
The scale transition itself should create curiosity and payoff.

⸻

P0 — STORY-SPECIFIC VISUAL CONTINUITY
Maintain conceptual continuity across shots.
Objects may:
- transform
- zoom into another layer
- become the next diagram
- reveal an internal structure
- transition into a map
- morph into a microscopic representation
- carry through as a persistent visual reference
Avoid unrelated shot A → shot B → shot C presentation slides.

⸻

P0 — PRESENTATION-TEMPLATE DETECTION
Add a lightweight deterministic check for overuse of the current presentation language.
Flag a shot when it combines several of:
- generic parchment/beige background
- central presentation panel
- standardized translucent boxes
- standard rail/divider
- generic diagram
- standard caption container
This is NOT a blanket prohibition.
It means:
when several of these appear together without strong story justification, the shot must be reconsidered.
Do not simply score this and allow it to pass.
The planner should regenerate/recompose the scene.

⸻

P0 — PRESERVE EXISTING HARDENING
Do NOT regress these fixes:
- input-staleness/cache invalidation
- forced rerender after asset/visual-bible changes
- judge parser hardening
- contract token-budget fix
- semantic asset verification
- caption safety
- factual verification
- render technical QA
- zero-debug-leak requirement
These are now permanent parts of the engine.

⸻

P1 — VISUAL AUTHORSHIP TEST
Add one lightweight qualitative automated/hybrid test:
For each ~2–4 second segment ask:
"If the narration audio were removed, would the visual itself communicate what changed, what matters, or what the viewer should look at?"
If not, classify the segment as weak visual authorship.
This is more important than adding dozens of numerical metrics.

⸻

P1 — HUMAN-EDITOR TEST
Before CAN_PUBLISH, evaluate the six questions:
1. Is something visually interesting happening immediately?
2. Does the visual explain the narration rather than merely accompany it?
3. Does the scene feel specific to this subject?
4. Does the visual materially transform as the explanation progresses?
5. Could the same composition be reused by replacing only the nouns?
6. Does the ending visually resolve the opening curiosity?
If #1, #2, #3, #4 or #6 fails → CAN_PUBLISH=false.
If #5 repeatedly fails across many shots/videos, the generator is still too template-driven and must revise the visual grammar.
Do not turn this into a huge scoring framework.

⸻

P1 — DO NOT OVERCORRECT
Do NOT:
- add AI video generation
- bring back Manim
- redesign FFmpeg unnecessarily
- replace the audio architecture
- endlessly tune subtitle cosmetics
- add dozens of new metrics
- force random visual styles
- generate a different art style merely for variety
- make every shot AI-generated
- destroy good scientific diagrams that genuinely communicate better
The objective is story-specific visual authorship, not maximum visual complexity.

⸻

P1 — SIX-STORY MUTED-SET TEST
After implementation, render these six deliberately different stories:
1. Ice slipping — microscopic/material mechanism
2. Cell / immune system — biological scale dive
3. Atacama fog / fog oasis — geography/environment
4. Tunguska-class event — historical/spatial reconstruction
5. Crumple zone — engineering/material deformation
6. Microwave / dielectric heating — counterintuitive everyday physics
These are a validation set, not individual one-off fixes.
Judge the SIX VIDEOS TOGETHER.
Success means:
- they feel like the same creator/channel
- they do NOT feel like the same template
- each uses an appropriate visual grammar
- rich visual assets are primary where appropriate
- procedural graphics are supporting evidence
- hooks are immediately visual
- visual information changes throughout
- no empty presentation containers
- no generic presentation-board dominance
- captions remain safe/readable
- factual/semantic gates remain intact
- ending resolves the story
- no debug artifacts
- technical QA remains 100%

⸻

FINAL STOP CONDITION
Do not enter another endless visual-optimization cycle.
After this implementation, review the six-story set as a human editor.
If:
- the visual grammars are genuinely different,
- rich assets are consistently used where useful,
- the presentation-template signature is no longer dominant,
- hooks/payoffs work,
- technical/factual/caption QA remains clean,
- and remaining issues are ordinary editorial polish rather than architecture failures,
then STOP changing the core video engine.
At that point the system should move to controlled YouTube production and real audience testing.
Real YouTube retention data will then be more valuable than another round of synthetic visual metrics.
Do not make individual video-specific hacks. Any fix must improve the reusable algorithm/pipeline for future stories.
