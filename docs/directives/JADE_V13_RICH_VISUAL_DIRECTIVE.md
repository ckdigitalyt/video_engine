# JADE V13 DIRECTIVE — FINAL MAJOR VISUAL ARCHITECTURE UPGRADE

Received from ckdigital via Discord #illustration-video, 2026-09-20 19:29 UTC (`Jade_todo.txt`, verbatim below).
Status: **ACTIVE** — drives V13: rich visual asset engine + semantic layering + story-specific visual representation.
Final milestone: 6 fresh videos, reviewed muted, target = "six deliberately art-directed documentaries".

---

I reviewed the latest 5 production videos:

- fever_thermostat
- seawater_drop
- crumple_zones
- atacama_fog_oases
- tunguska_1908

Technical/render/audio quality is now sufficiently mature.

DO NOT start another broad "polish everything" cycle.

We are now in DIMINISHING RETURNS territory for:
- audio normalization
- generic camera motion
- transition count
- caption animation
- additional QA metrics
- cosmetic particles
- more easing curves
- additional panel styles

The remaining meaningful quality gap is VISUAL ASSET SOPHISTICATION.

The next milestone is therefore:

RICH VISUAL ASSET ENGINE + SEMANTIC LAYERING + STORY-SPECIFIC VISUAL REPRESENTATION.

====================================================
P0 — HARD PRODUCTION DEFECTS
====================================================

1. FINAL TRANSFORM SAFE-AREA QA

After all camera transforms, crop, scale and animation:

Check bounding boxes for:
- labels
- numbers
- annotations
- arrowheads
- diagrams
- important objects

Nothing semantically important may touch or cross the final canvas boundary.

Examples observed in latest videos:
- clipped left/right labels
- labels obscured by bars
- annotations too close to panel edges

Any semantic clipping:
CAN_PUBLISH = FALSE.

Do not patch these five videos.
Fix the renderer/planner globally.

====================================================
P0 — RICH VISUAL ASSET ENGINE
====================================================

Current problem:

Many assets are visually clean but structurally simple:
- circles
- rectangles
- lines
- dots
- arrows
- basic car/body/lake/terrain outlines.

These are useful as evidence overlays,
but they should no longer be the primary visual material for most major beats.

Introduce a new ASSET_CLASS:

RICH_VISUAL_PLATE

A rich visual plate should contain:
- detailed subject geometry
- material/texture
- controlled lighting
- environmental context
- depth cues
- foreground/midground/background separation
- atmospheric detail where appropriate
- enough detail to survive a strong zoom
- subject-specific visual identity

Examples:
- detailed fog-covered Atacama landscape
- realistic atmospheric Tunguska airburst over forest
- detailed car body/material deformation
- biologically rich microscopic seawater scene
- sophisticated human thermal-regulation cutaway
- detailed geological/geographic reconstruction

AI generation may create the base plate.

FFmpeg/SVG/procedural rendering remains the deterministic compositor.

DO NOT introduce AI video.

====================================================
P0 — HYBRID VISUALIZATION MODEL
====================================================

The final visual should normally be:

RICH_VISUAL_PLATE
+
SEMANTIC_VECTOR_OVERLAYS
+
DATA/EVIDENCE
+
DEPTH/PARALLAX
+
CAMERA

NOT:

flat_diagram_only

The diagram is evidence.

The rich plate is the visual experience.

====================================================
P0 — MULTI-STAGE IMAGE GENERATION
====================================================

Stop relying on single-pass image generation.

For high-value assets use:

1. COMPOSITION PASS
2. DETAIL / MATERIAL PASS
3. SEMANTIC EDIT PASS
4. OPTIONAL DEPTH/EDGE PASS

Where supported, use image editing with reference images rather than generating unrelated images for every beat.

Current image systems support:
- multi-reference composition
- image-to-image editing
- depth/edge conditioning
- higher-resolution output

Exploit these capabilities where already available.

Do not add a paid provider solely for this requirement.

Keep provider abstraction intact.

====================================================
P0 — ASSET LAYER EXTRACTION
====================================================

For rich visual plates, expose semantic layers when practical:

BACKGROUND
MIDGROUND
SUBJECT
FOREGROUND
ATMOSPHERE
EFFECTS
ANNOTATION

Then allow independent transforms.

Goal:

ONE STRONG ASSET
can support multiple meaningful shots.

Example:

wide scene
→ push toward subject
→ reveal internal layer
→ cutaway
→ consequence

Do not generate five unrelated flat images.

====================================================
P0 — DEPTH-AWARE 2.5D
====================================================

Depth must become real information-bearing structure.

Where feasible derive:
- relative depth
- foreground/background masks
- subject masks

Then support:

- parallax
- focus shift
- camera push-through
- foreground occlusion
- layer reveal
- scale transition

Blurred background extension does NOT count as depth.

Do not require a new GPU architecture.

Benchmark CPU-friendly segmentation/depth approaches before adoption.

If runtime cost is excessive, use the image provider's structural controls or simpler masks instead.

====================================================
P0 — STORY-SPECIFIC VISUAL REPRESENTATION
====================================================

Before rendering, classify every major beat into the most informative visual mode.

Allowed modes:

RICH_PLATE
CUTAWAY
MICROSCOPIC
MAP
TIMELINE
DATA_GRAPHIC
FORCE/FLOW_FIELD
MATERIAL_DEFORMATION
ENVIRONMENTAL_RECONSTRUCTION
SCALE_TRANSITION
VECTOR_DIAGRAM
COMPARISON
PROCESS_LOOP
CAUSAL_CHAIN

Do not default to VECTOR_DIAGRAM.

The planner chooses the mode.

====================================================
P0 — VISUAL COMPLEXITY IS NOT "MORE OBJECTS"
====================================================

Add diagnostic:

VISUAL_SOPHISTICATION

Evaluate:
- depth
- material cues
- lighting
- texture/detail
- environmental context
- scale cues
- semantic layers
- subject specificity
- visual hierarchy

Do NOT optimize for raw visual entropy.

A cluttered diagram is not sophisticated.

====================================================
P0 — FULL-CANVAS CINEMATIC COMPOSITION
====================================================

The 9:16 canvas should often become the world of the story.

Avoid default:
- central horizontal presentation board
- unused top/bottom areas
- permanent rails
- panel chrome
- repeated information-card structure

The same brand palette may remain.

The compositional architecture must vary by story.

====================================================
P0 — HOOK
====================================================

First 0.5 sec:
show the phenomenon.

First 2 sec:
create a visual contradiction / impossible scale / transformation.

Avoid:
black fade
generic title card
static explanatory diagram

unless the specific story genuinely requires it.

====================================================
P0 — PAYOFF
====================================================

Final 3–5 sec:
resolve the opening visual question.

Do not use generic poetic end cards as the final information event.

Prefer:

entire causal chain collapsing into one strong visual synthesis.

====================================================
P1 — ADVANCED SVG / PROCEDURAL GRAPHICS
====================================================

Do not abandon SVG.

Upgrade its use.

Support:
- gradients
- masking
- clipping
- filtered lighting
- soft glows
- material shading
- paths/curves
- field lines
- particles
- contours
- scales
- data encodings
- animated morphs

SVG should become the scientific/evidence layer above rich imagery,
not the entire visual world.

====================================================
P1 — MICRO → MACRO TRANSITIONS
====================================================

Add a first-class visual primitive:

SCALE_DIVE

Examples:
- landscape → plant → leaf → cell
- ocean → droplet → bacterium → molecule
- human → skin → blood vessel → immune cell
- car → crash zone → metal deformation
- volcano → atmosphere → aerosol → climate

This is a high-value cinematic/explanatory primitive.

====================================================
P1 — VISUAL CONTRADICTION
====================================================

Maintain the existing contradiction engine,
but now the contradiction should preferably be visualized with
RICH_VISUAL_PLATE + TRANSFORMATION,
not a text label over a flat diagram.

====================================================
P1 — CROSS-VIDEO TEMPLATE TEST
====================================================

Keep brand identity.

Prevent structural sameness.

Compare the last 10 videos for:
- primary visual mode
- composition architecture
- background architecture
- panel usage
- asset class
- camera grammar
- overlay density
- transition grammar

If unrelated stories repeatedly collapse into the same visual construction,
regenerate the visual plan.

====================================================
P1 — RICH_ASSET_COVERAGE
====================================================

Track:

RICH_ASSET_COVERAGE
=
duration using rich visual plates / total visual duration

Do not impose one universal target on every subject.

However, for general science/history/geography videos,
flat vector-diagram-only presentation should no longer dominate the video.

The planner should actively seek richer visual modes for major beats.

====================================================
P1 — LABEL/CAPTION SAFETY
====================================================

Keep current caption architecture.

Add final-frame transformed-position QA.

Check:
- clipping
- overlap
- occlusion
- competing text
- minimum safe distance from canvas edge

This must run AFTER every camera transform.

====================================================
P1 — PROVIDER CAPABILITY AUDIT
====================================================

Audit currently available image providers.

Prefer capabilities that support:
- image editing
- multi-reference generation
- structural/depth/edge control
- high resolution
- consistent composition

Do not blindly add another model.

Do not deploy huge image models locally on the OCI CPU server.

Use the existing provider abstraction.

====================================================
P1 — JEV
====================================================

Jev must NOT generate visual assets.

If Jev API access is available, use it only as a structured decision layer:

Candidate visual plans:
A — rich plate
B — hybrid plate + diagram
C — pure diagram
D — map/timeline/etc.

Jev may choose/score:
- explanatory fit
- visual surprise
- story-specific grammar
- redundancy
- visual sophistication
- semantic risk

Initially keep Jev in SHADOW MODE.

Do not let Jev alter production until decision agreement/disagreement
has been measured.

NOTE (owner standing rule 2026-09-19): Jev is fully rolled back and closed —
zero Jev in production. Implement shadow-mode interface as a disabled stub;
no API calls unless owner reopens Jev explicitly.

====================================================
DO NOT CHANGE
====================================================

Do NOT:
- switch to AI video
- switch compositor
- reintroduce Manim
- redesign audio
- chase more transition effects
- add decorative motion merely for novelty
- add dozens of new QA metrics
- force every video into a new style
- optimize numerical scores instead of visual quality

====================================================
FINAL MILESTONE
====================================================

Generate 6 fresh videos after implementation.

The six must include:
- science mechanism
- biology
- geography
- history
- engineering
- everyday counterintuitive science

Review them MUTED.

The test is:

"Does this look like six deliberately art-directed documentaries,
or six animated infographics made by the same template?"

Target answer:
SIX DELIBERATELY ART-DIRECTED DOCUMENTARIES.

If that is achieved, STOP MAKING COSMETIC ALGORITHM CHANGES.

At that point begin real YouTube production and use actual audience
retention data to guide subsequent changes.

Do not endlessly optimize the renderer before real-world feedback.
