# JADE V14 DIRECTIVE — Autonomous Illustration + Motion-Design Production System

> Received 2026-09-26 from owner (Jade_todo.txt). Supersedes the 2026-09-24 instructions
> (V13B-only plan + 2-video cut). Preserved verbatim below. Binding.

---

Jade — this is the next major upgrade of video_engine.

## CONTEXT

We now have a strong deterministic production pipeline:

- story/research
- visual planning
- asset generation
- motion
- captions
- audio
- compositing
- factual/semantic QA
- technical QA
- cache invalidation
- publish gates

The latest cell_scale_dive and ice_slippery renders proved that the engineering and QA layers are substantially better.

However, the rendered videos still reveal one major architectural limitation:

**The engine is too image/diagram-centric.**

It can produce a good asset and move a camera around it, but it does not yet behave like a professional illustration + motion-design production system.

The reference video I provided is the quality bar for production sophistication, not a style to copy.

Do NOT copy its:

- palette
- characters
- subject matter
- exact art direction
- typography
- scene layouts
- transitions

Instead reproduce the underlying production principles:

coherent visual world + rich layered illustration + story-specific composition + semantic motion + typography + camera/depth + controlled procedural graphics.

The objective is:

**END-TO-END AUTONOMOUS VIDEO GENERATION**

Given a story/topic, the upgraded engine must autonomously generate the final YouTube-ready video from start to finish.

There must be NO manual Illustrator/After Effects step.
There must be NO requirement for the user to manually arrange illustrations.
There must be NO separate "demo pipeline" that is never used by production.
The new illustration/motion tooling must be callable by the actual production algorithm.

## 1. NON-NEGOTIABLE INFRASTRUCTURE CONSTRAINTS

Target machine:

- OCI Always Free
- Ubuntu 24.04
- ARM64 / aarch64
- Ampere Neoverse-N1
- 4 OCPU
- ~24 GB RAM
- ~96 GB disk
- NO GPU

Therefore:

- CPU-first
- deterministic
- cacheable
- headless
- scriptable
- open/free where practical
- no paid desktop dependency
- no Adobe dependency
- no Cavalry dependency
- no GPU dependency
- no AI-video dependency
- no cloud rendering dependency

Do not redesign the whole system around a tool that cannot realistically run on this server.

## 2. TOOLCHAIN INVESTIGATION + BENCHMARK

Before changing the production renderer, create a contained toolchain benchmark.

Candidate stack:

**Primary candidate**

Remotion + SVG + resvg

Why:

- programmatic scene generation
- React/TypeScript scene descriptions
- SVG support
- animation
- video rendering
- Linux ARM64 GNU support
- H.264 output on Linux ARM64

**Secondary candidate**

Motion Canvas + SVG

Benchmark for:

- scene authoring
- vector animation
- timing
- camera movement
- voice-synchronised animation
- render performance

**Supporting tools**

resvg for fast/high-quality SVG rendering.
VTracer for selective raster → vector conversion.
Inkscape for SVG validation/conversion where useful; do not make the GUI part of the production workflow.

**Optional specialist**

Synfig

Use only if it materially helps with:

- character rigging
- cutout animation
- bone deformation
- reusable animated 2D subjects

It is available for Ubuntu 24.04 arm64.

Do NOT make Blender a critical dependency

Blender may be benchmarked later for specialist 2.5D scenes, but the current official Linux distribution is not a native ARM64 production package.
Do not create a hard dependency on compiling/maintaining Blender ARM64 unless a benchmark demonstrates a compelling benefit that cannot be achieved another way.

## 3. DO NOT INSTALL EVERYTHING BLINDLY

Create a benchmark directory outside the core production path, for example:

tools/visual_backend_benchmark/

The benchmark must:

1. Detect architecture/CPU/RAM/GPU.
2. Detect which candidate tools are already installed.
3. Install only lightweight required dependencies.
4. Record exact versions.
5. Never modify the production renderer until the benchmark is complete.
6. Produce a single benchmark report.

Do not spend excessive time building software from source if a usable native package/binary exists.

## 4. BENCHMARK TEST SCENES

Generate four small scenes.
Each should be approximately 6–10 seconds.
Output:
1080x1920 30 fps
Use the SAME scene specification wherever possible so the tools are comparable.

**TEST A — RICH SUBJECT SCENE**

Example:
A stylized scientific subject such as an eye/cell/planet/object.

Need:

- foreground
- subject
- background
- texture
- lighting
- shadow
- depth layers
- camera push
- subtle subject motion
- annotation

The result should look like an authored illustration, not a diagram.

**TEST B — STORY INFOGRAPHIC**

Create something such as:

- circular time scale
- comparison
- timeline
- numerical relationship

Need:

- vector geometry
- typography
- animated reveal
- highlights
- labels
- visual hierarchy
- integrated styling

It must look like part of the illustrated world, not a generic dashboard.

**TEST C — VISUAL TRANSFORMATION**

Example:
human eye → tissue → cell → DNA

Need:

- camera movement
- scale transition
- continuity
- persistent visual anchors
- semantic transformation

Do not simply crossfade between four unrelated images.

**TEST D — ENVIRONMENT / SCENE**

Example:
A stylized landscape/environment.

Need:

- foreground
- midground
- background
- atmosphere
- parallax
- camera movement
- contextual labels
- subtle environmental animation

This test is especially important because it demonstrates whether the system can create a visual WORLD rather than just a card.

## 5. BENCHMARK WHAT ACTUALLY MATTERS

Record:

- render time
- CPU utilization
- peak RAM
- output size
- startup cost
- cache behavior
- crash/retry behavior
- frame determinism
- SVG fidelity
- typography fidelity
- transparency/mask support
- gradients
- filters
- clipping/masks
- transforms
- nested groups
- camera support
- layer independence
- animation control
- audio synchronization
- ease of programmatic authoring
- ability to rerender one scene independently
- ability to replace one asset without rerendering unrelated scenes

Do not choose a tool because it has the prettiest demo.
Choose based on:
quality × controllability × ARM64 viability × CPU cost × autonomous authorability.

## 6. PRODUCTION DECISION

After the benchmark, select:

- one PRIMARY scene renderer
- optional SECONDARY/specialist renderer
- supporting SVG tooling

Do not keep multiple equivalent production renderers just because they are interesting.

The production architecture must have:

visual_backend = auto

and optionally:

visual_backend = <selected backend>

But auto should be the normal production path.

## 7. CRITICAL ARCHITECTURAL CHANGE

The current engine often thinks:

asset → camera → overlay → final

This must evolve into:

story → visual intent → scene design → scene graph → asset/layer generation → animation → camera → semantic overlays → composite → audio → QA → final video

The central new abstraction is:

**SCENE GRAPH**

Do NOT make a scene just a single JPG/PNG.
Represent it as editable layers.

Example conceptual structure:

```
scene
 ├── background
 ├── environment
 ├── subject
 ├── secondary_subjects
 ├── foreground
 ├── atmosphere
 ├── texture
 ├── lighting
 ├── scientific_layers
 ├── semantic_annotations
 ├── text
 ├── masks
 ├── depth
 └── camera
```

Every layer should have:

- id
- type
- asset/source
- position
- scale
- rotation
- opacity
- z-order
- anchor
- semantic role
- optional depth
- optional animation
- optional visibility interval

## 8. DEFINE A FORMAL SCENE IR

Create a stable intermediate representation.

Suggested:

scene_spec.json

Do not tie the story planner directly to Remotion/Synfig/Motion Canvas implementation details.

Planner produces:
Scene IR

Renderer consumes:
Scene IR

This keeps the engine independent of the rendering backend.

Conceptually:

```json
{
  "scene_id": "cell_03",
  "visual_grammar": "MICROSCOPIC_WORLD",
  "style_bible": "...",
  "layers": [],
  "camera": {},
  "animations": [],
  "annotations": [],
  "caption_safe_regions": [],
  "duration": 4.2
}
```

The exact schema can be refined during implementation.

## 9. NEW VISUAL GRAMMAR LIBRARY

Create a reusable library of story-specific visual grammars.
At minimum:

RICH_ILLUSTRATED_SCENE
CHARACTER_SCENE
OBJECT_SCENE
MICROSCOPIC_WORLD
BIOLOGICAL_CUTAWAY
TECHNICAL_CUTAWAY
ENVIRONMENT_RECONSTRUCTION
GEOGRAPHIC_WORLD
MAP_TRANSFORMATION
HISTORICAL_RECONSTRUCTION
ENGINEERING_MECHANISM
MATERIAL_DEFORMATION
FORCE_FIELD
PROCESS_FLOW
TIMELINE
COMPARISON
DATA_GRAPHIC
SCALE_DIVE
CAUSAL_CHAIN
VISUAL_CONTRADICTION

These are not fixed templates.
They are composition grammars.

Each grammar should define:

- preferred layer structure
- typical depth structure
- useful camera behavior
- useful semantic overlays
- transformation opportunities
- subject-specific visual anchors
- appropriate typography behavior

The actual composition must still be generated from the story.

## 10. VISUAL STYLE VS VISUAL COMPOSITION

This distinction is mandatory.

The visual bible controls:

- palette
- line treatment
- texture
- lighting
- contrast
- typography
- shadow language
- grain
- illustration treatment

But it must NOT dictate:

- same panel placement
- same number of boxes
- same camera position
- same hero location
- same diagram layout
- same scene sequence
- same transition

Therefore:

STYLE = coherent
COMPOSITION = story-dependent

This is exactly what the reference demonstrates.

## 11. AI IMAGE GENERATION REMAINS A COMPONENT, NOT THE WHOLE VISUAL SYSTEM

Keep the current image-generation providers.
Do not discard them.
But change the role.

Current:
AI image = scene

Desired:
AI image = one visual asset/layer/source for a scene

Whenever possible:

- generate clean hero/background imagery
- generate visual environments
- generate subject plates
- generate textures/materials
- generate rich illustrated objects

Then combine them with:

- vector elements
- SVG
- procedural lighting
- semantic annotations
- camera movement
- depth
- masks
- foreground elements

This is how we get richer scenes without requiring AI video.

## 12. BUILD A LAYER EXTRACTION / LAYER AUTHORING SYSTEM

For suitable assets, support:

background
midground
subject
secondary subject
foreground
effect
annotation

Do not assume automatic segmentation will always work.
Use whichever is more reliable:

- existing image segmentation
- manually defined masks
- vector geometry
- alpha channels
- simple deterministic cutouts
- AI-generated separated assets
- selective raster tracing

Prefer correctness over automation purity.

## 13. USE SVG AS A FIRST-CLASS VISUAL MEDIUM

The current engine underuses SVG.

Create reusable SVG primitives for:

- paths
- curves
- gradients
- masks
- clip paths
- filters
- glow
- shadows
- arrows
- rings
- particles
- timelines
- maps
- measurement lines
- labels
- technical outlines
- biological structures
- force vectors
- flow fields

But do NOT turn the whole system into simplistic SVG diagrams.
SVG is the underlying editable medium.
The rendered scene should still feel like an illustration.

## 14. VTRACER USAGE POLICY

VTracer is a TOOL, not the style generator.

Use it when converting a raster asset to vector materially improves:

- segmentation
- recoloring
- independent motion
- scalability
- shape manipulation

Do NOT vectorize every image.
Do NOT turn rich painterly artwork into ugly thousands-of-path SVG.

Reject vectorization when it damages:

- texture
- gradients
- visual richness
- material appearance
- silhouette quality

## 15. DEPTH / 2.5D

Keep and expand the current depth architecture.

A scene should support:

background
midground
subject
foreground
atmosphere
annotation

with different camera parallax.

Support:

- push-in
- pull-out
- lateral camera travel
- focus shift
- subject reveal
- occlusion
- depth transition
- scale transition

Do NOT introduce random camera motion.
Camera motion must have semantic purpose.

## 16. CAMERA MUST BE CONTINUOUS

Preserve the existing anti-jitter work.

Use:

- floating-point transforms
- continuous easing
- original source coordinates
- high-resolution internal render when useful
- single final downsample

No repeated integer rounding.
No per-frame destructive rescaling.
No tremble.

## 17. STORY-DRIVEN TRANSITIONS

Transitions should often transform one idea into another.

Examples:

cell → zoom into membrane
map → landscape
machine exterior → cutaway
person → internal process
small quantity → huge comparison
before → after

Prefer:
continuity + transformation
over:
generic transition effect.

Crossfade is allowed but should not be the primary storytelling mechanism.

## 18. TYPOGRAPHY MUST BECOME PART OF THE WORLD

Keep narration captions.

But allow important information to become an integrated visual element:

- giant number
- scale indicator
- timeline
- label
- measurement
- comparison
- directional annotation

Use typography deliberately.

Do not create permanent bottom UI bars.
Do not build every scene around caption containers.
Caption placement happens AFTER scene composition.

## 19. ELIMINATE THE OLD PRESENTATION TEMPLATE

The following combination must no longer be the default:

beige background
+
central panel
+
black rail
+
translucent rectangle
+
generic diagram
+
bottom caption

A scene may use one of those elements.
The problem is the standardized combination.

Add a lightweight template-signature check.
If a scene contains too many elements from the old presentation language without a strong story reason:
recompose/regenerate.
Do not merely lower a score.

## 20. REMOVE EMPTY VISUAL CONTAINERS

No:

- empty rectangles
- decorative boxes
- placeholder panels
- labels with no semantic purpose
- reserved template areas

Every visible graphical container must have a purpose.

If it does not communicate:

- object
- relationship
- measurement
- process
- comparison
- state
- annotation

remove it.

## 21. NEW END-TO-END DATA FLOW

The actual production pipeline should become:

RESEARCH
 ↓
FACTS
 ↓
STORY
 ↓
VISUAL BIBLE
 ↓
BEAT PLAN
 ↓
VISUAL GRAMMAR SELECTION
 ↓
SCENE IR
 ↓
ASSET PLAN
 ↓
AI / PROCEDURAL ASSETS
 ↓
LAYER / MASK PREPARATION
 ↓
VECTOR / SVG BUILD
 ↓
2D / 2.5D ANIMATION
 ↓
CAMERA
 ↓
SEMANTIC OVERLAYS
 ↓
CAPTIONS
 ↓
SCENE RENDER
 ↓
AUDIO
 ↓
FINAL COMPOSITE
 ↓
QA
 ↓
CAN_PUBLISH

This must execute through one production command/workflow.

## 22. RENDERING BACKEND ABSTRACTION

Build a renderer adapter such as:

```
SceneRenderer
  ├── render(scene_spec)
  ├── render_frame(scene_spec, t)
  ├── render_preview(scene_spec)
  ├── validate(scene_spec)
  └── capabilities()
```

Possible implementations:

RemotionRenderer
MotionCanvasRenderer
SynfigRenderer   [optional]
FallbackRenderer [existing pipeline]

Do not let business/story logic know which backend is being used.

## 23. BACKEND SELECTION

Use capability-driven selection.

For example:

rich_vector_scene → primary vector renderer

rigged_character_scene → specialist backend if benchmark proves better

simple technical diagram → existing deterministic SVG/vector renderer

existing successful raster cinematic scene → existing asset pipeline

unsupported feature → existing fallback

Do not force everything through the new renderer.
Use the best appropriate representation.

## 24. CACHE DESIGN MUST BE EXTENDED

The cache key must include:

- story hash
- beat hash
- scene-spec hash
- style-bible hash
- asset hashes
- layer/mask hashes
- renderer backend
- renderer version
- scene renderer configuration
- camera choreography
- narration/timing hash where relevant

If any of those change:
invalidate the scene render.

Never repeat the previous stale-render problem.

## 25. PARTIAL RERENDERING IS MANDATORY

Changing one scene must NOT require rebuilding the entire video.

The system should support:

asset changed → affected scene only

scene-spec changed → affected scene only

camera changed → affected scene only

caption timing changed → affected scene/segments only where possible

Then final composite can be rebuilt from scene outputs.

## 26. CPU / RAM BUDGET

Do not let the new backend consume the whole server indefinitely.

Target:

- normal operation within available RAM
- no runaway multiprocessing
- bounded worker count
- no uncontrolled subagents
- no concurrent heavy renders by default
- predictable disk cleanup

Start with conservative worker counts suitable for 4 OCPU.
Benchmark before increasing parallelism.

## 27. QUALITY TARGET

The reference should be treated as an art-direction benchmark, not a style template.

The desired result is:

**COHERENT**
The entire video looks like one deliberately designed visual world.

**RICH**
Scenes have:
- texture
- material
- lighting
- layers
- depth
- context
- recognisable subjects

**VARIED**
Scene composition changes according to the story.

**EXPLANATORY**
Motion shows:
- cause
- effect
- scale
- transformation
- process
- relationship

**EDITORIAL**
The sequence feels intentionally cut and paced.

**AUTONOMOUS**
No manual artist intervention is required.

## 28. NEW VISUAL AUTHORSHIP GATE

Before CAN_PUBLISH, inspect approximately every 2–4 seconds.
Ask:
If the narration audio were removed, would the visual itself communicate what changed or what the viewer should understand?
If NO:
flag weak visual authorship.

Also ask:

1. Is the subject visually interesting immediately?
2. Is the visual specific to this story?
3. Does the scene contain meaningful visual information?
4. Does the visual transform as the explanation advances?
5. Does the composition feel authored rather than templated?
6. Does the scene contribute to the story rather than simply accompany narration?

Critical failures should prevent publication.

Keep this lightweight.
Do NOT create another giant metrics framework.

## 29. HUMAN-EDITOR SIMULATION

Automated scoring must not be able to declare a video good simply because it contains:

- enough scene changes
- enough motion
- enough labels
- enough assets

Run a final human-editor style analysis:

FIRST 2 SECONDS
Would this stop a viewer scrolling?

5 SECONDS
Is there a genuine curiosity gap?

15 SECONDS
Has the viewer learned something visually?

30 SECONDS
Has the idea escalated?

FINAL 3–5 SECONDS
Does the ending resolve the opening curiosity?

TEMPLATE TEST
Could this scene be reused by replacing nouns only?
If YES repeatedly:
fail visual authorship.

## 30. TEST WITH SIX VERY DIFFERENT STORIES

After the toolchain is integrated, render:

1. ICE — mechanism/material
2. CELL/IMMUNE — biological scale dive
3. ATACAMA FOG OASIS — geographic/environmental
4. TUNGUSKA-CLASS EVENT — historical/spatial
5. CRUMPLE ZONE — engineering/material deformation
6. MICROWAVE/DIELECTRIC HEATING — counterintuitive everyday science

Do not individually hand-tune each video.
The point is to test whether the algorithm generalizes.

## 31. SUCCESS CONDITION FOR THE SIX VIDEOS

All six must:

- be complete end-to-end outputs
- require no manual art work
- retain factual/semantic correctness
- remain technically valid
- use safe captions
- have immediate visual hooks
- contain genuine visual transformations
- use rich subject-specific scenes where appropriate
- use diagrams only where they help
- maintain a coherent visual world
- avoid the old presentation-board template
- have story-specific visual grammars
- have meaningful visual payoff
- have no debug artifacts
- have no stale renders
- have clean audio
- remain computationally feasible on the OCI server

Most importantly:
The six videos should look like they came from the same creator, but not from the same template.

## 32. DO NOT USE AI VIDEO

Do not introduce AI-generated video.

We deliberately want:
illustration + SVG + layers + procedural animation + camera + depth + compositing

This is more controllable, cheaper and more appropriate for the current infrastructure.

## 33. DO NOT ABANDON THE CURRENT ENGINE

The new subsystem must be an upgrade to the current architecture.

Preserve:

- research
- story generation
- facts
- visual bible
- asset provider abstraction
- current image providers
- captions
- audio
- FFmpeg final assembly
- factual QA
- semantic QA
- technical QA
- publish gate
- cache invalidation
- watchdogs
- cost controls

Replace only the weak visual-authoring layer.

## 34. NO MANUAL ART-DIRECTION LOOP

The final production workflow must be:

topic → research → script → visual plan → scene graph → assets → illustration/layers → animation → camera → captions → audio → QA → MP4

One autonomous workflow.
The user should be able to ask for a new topic and receive the completed video.

## 35. COST / TOKEN CONTROL

We have limited LLM budget.
Do NOT solve this by creating many agent/subagent loops.

Use the existing architecture:

- one primary GLM-5.3-FLASH workflow
- compact context
- deterministic helper programs
- cached intermediate results
- only call the LLM when a creative/semantic decision is actually required

Do not repeatedly ask the model to rediscover the same toolchain or style bible.

Persist:

- tool capabilities
- backend choice
- visual grammar library
- style-bible schema
- scene schema
- renderer schema
- failure rules

## 36. JEV

Do NOT integrate Jev into the critical production path.
If later useful, Jev can remain a shadow decision-analysis layer for candidate visual plans.
It must NOT:
- generate assets
- render videos
- become a dependency
- introduce uncontrolled LLM calls

First make the deterministic production algorithm work.

## 37. IMPLEMENTATION ORDER

Do this in stages.

STAGE 1
Inventory current engine and identify:
- asset generation
- scene planning
- compositing
- current motion renderer
- QA
- caches
Do not duplicate functionality.

STAGE 2
Build the isolated visual-backend benchmark.

STAGE 3
Choose the best backend based on actual Oracle ARM64 results.

STAGE 4
Implement the Scene IR.

STAGE 5
Implement the renderer adapter.

STAGE 6
Implement 3–5 visual grammars.

STAGE 7
Integrate asset/layer pipeline.

STAGE 8
Integrate camera/depth/motion.

STAGE 9
Integrate captions/audio/final FFmpeg.

STAGE 10
Extend cache invalidation.

STAGE 11
Run one complete end-to-end pilot.

STAGE 12
Run the six-story validation set.

Do not declare success from the benchmark alone.

## 38. REQUIRED DELIVERABLES

At the end, provide:

A. Toolchain report — What was tested, versions, CPU/RAM/render performance.
B. Architecture report — How the chosen backend integrates with video_engine.
C. Scene IR schema — Location and example.
D. Renderer adapter — Production code, not demo-only code.
E. Visual grammar library — Current supported grammars and examples.
F. Cache/invalidation changes — Show that stale-render behavior is impossible or detected.
G. End-to-end command — One normal production command/workflow that creates the final video.
H. Six-story validation set — Six actual rendered videos.
I. Final verdict — Clearly state PASS / PARTIAL / FAIL for:
- visual authorship
- visual richness
- story-specific grammar
- technical production
- factual integrity
- caption quality
- audio
- anti-template
- autonomous generation
- Oracle performance

Do not inflate scores.

## 39. IMPORTANT STOP CONDITION

This is not permission to create an endless "V14/V15/V16" loop.
The purpose of this upgrade is to solve one architectural problem:
turn the engine from an image/diagram compositor into an autonomous illustration + motion-design video generator.

Once the six-story test demonstrates that the architecture can consistently produce:
rich visual worlds + story-specific compositions + meaningful animation + coherent style + varied scenes

then STOP changing the core architecture.
At that point:
freeze the engine and move to real YouTube testing.

Real audience retention and satisfaction data will then become more valuable than synthetic visual scores.

## FINAL OBJECTIVE

The finished system should not feel like:
"Jade generated a collection of images and animated them."

It should feel like:
"Jade designed and produced an illustrated science documentary from scratch."

That is the target.
Do not copy the reference video.
Use it as proof of the quality level that a disciplined illustration + motion-design architecture can achieve.
Build the system so that this level is produced autonomously, repeatably, cheaply, and entirely on the Oracle server.
