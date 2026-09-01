We are starting a COMPLETELY NEW video-generation program for the YouTube channel.

Treat the existing Manim-based video-generation project as a failed prototype.

DO NOT extend, repair, or redesign the existing Manim architecture.

Build a new system from scratch.

1. CORE OBJECTIVE

Build an autonomous YouTube video production engine that converts:

TOPIC
→ RESEARCH
→ STORY
→ VISUAL STORYBOARD
→ ILLUSTRATION / GRAPHIC ASSETS
→ MOTION DESIGN
→ NARRATION
→ COMPOSITING
→ QA
→ FINAL VIDEO

The target style is:

ILLUSTRATED DOCUMENTARY + EDITORIAL MOTION GRAPHICS

Use the supplied reference video as a VISUAL INSPIRATION.

Do not copy it literally.

The key idea is to create visually interesting videos primarily from excellent still artwork, diagrams, graphical elements, intelligent camera movement, kinetic text, and narration.

2. IMPORTANT PIVOT

Do NOT make AI-generated video clips a core dependency.

The system must be able to produce an excellent complete video WITHOUT generating a single AI video clip.

This is a hard requirement.

AI video generation may eventually be added as an OPTIONAL enhancement, but the pipeline must work perfectly without it.

Reason:

	•	video generation is slower
	•	video generation is less deterministic
	•	visual consistency is harder
	•	API availability varies
	•	cost is higher
	•	controlling exact timing is difficult
	•	repeated generations can become expensive
	•	a 3–5 minute documentary would require many individual clips

Therefore:

STILLS + MOTION DESIGN = PRIMARY ENGINE

AI VIDEO = OPTIONAL SECONDARY ENGINE

3. ASSET PRIORITY

Default visual asset hierarchy:

	1.	AI-generated/custom illustrations
	2.	AI-generated diagrams
	3.	AI-generated maps
	4.	AI-generated infographics
	5.	SVG/vector graphical elements
	6.	generated charts/timelines
	7.	typography/kinetic text

Do NOT depend on:

	•	stock footage
	•	licensed footage
	•	public-domain footage
	•	external video libraries

For the first implementation, completely eliminate external footage from the architecture.

Every video must be capable of being generated from internally created visual assets.

4. VISUAL PHILOSOPHY

The output should NOT look like:

“still image + narration + subtitles”

It should look like a professionally edited motion documentary.

Use:

	•	cinematic compositions
	•	intelligent crops
	•	camera movement
	•	layered artwork
	•	parallax
	•	foreground/background separation
	•	animated diagrams
	•	highlights
	•	arrows
	•	labels
	•	callouts
	•	kinetic typography
	•	numbers
	•	transitions
	•	visual reveals
	•	controlled pacing

The viewer should feel that the camera is moving through an illustrated world.

5. ONE IMAGE SHOULD PRODUCE MULTIPLE SHOTS

This is a core optimization.

If one generated illustration contains:

Earth + Moon + spacecraft

do not immediately generate three more images.

Instead create multiple shots from the same asset:

SHOT 1:
full composition

SHOT 2:
slow push toward Earth

SHOT 3:
pan Earth → Moon

SHOT 4:
zoom toward spacecraft

SHOT 5:
pull back to the complete composition

The program should automatically identify useful regions of an image and create multiple camera compositions.

6. BUILD A VISUAL MOTION GRAMMAR

Create a reusable set of deterministic motion primitives.

At minimum:

ZOOM_IN
ZOOM_OUT
PAN_LEFT
PAN_RIGHT
PAN_UP
PAN_DOWN
DIAGONAL_PAN
PUSH_IN
PULL_OUT
CROP_REVEAL
FOCUS_REVEAL
MASK_REVEAL
PARALLAX
LAYER_MOVE
SUBTLE_ROTATION
DIAGRAM_DRAW
ARROW_DRAW
HIGHLIGHT
CALLOUT
NUMBER_POP
TEXT_REVEAL
WORD_EMPHASIS
IMAGE_WIPE
CROSSFADE
LIGHT_SWEEP
SUBTLE_CAMERA_SHAKE

Do NOT generate arbitrary animation code separately for every shot.

Create a reusable motion system.

7. RENDERING

Use a deterministic compositor.

FFmpeg should be the primary rendering/encoding engine.

Use other lightweight technologies only where necessary for:

	•	SVG
	•	text
	•	masks
	•	vector animation
	•	compositing
	•	image processing

Do NOT make Manim the primary rendering system.

Manim may only be used later for genuinely mathematical scenes if there is a compelling reason.

8. STORY ENGINE

The system must build the story BEFORE building visuals.

Create:

story.json

with:

	•	title
	•	premise
	•	target audience
	•	hook
	•	beats
	•	narration
	•	factual claims
	•	sources
	•	emotional purpose
	•	curiosity mechanism
	•	payoff

Every beat must answer:

“Why would the viewer continue watching?”

Do not begin videos with generic introductions.

Avoid:

“Today we are going to explore…”

Prefer immediate curiosity.

Example:

“We know why Mars is red.

But almost nobody asks why it stayed red after losing its atmosphere.”

9. VISUAL STORYBOARD

Create:

visual_plan.json

For every beat specify:

	•	beat_id
	•	narration
	•	duration
	•	visual concept
	•	asset type
	•	required asset
	•	camera movement
	•	crop
	•	overlays
	•	typography
	•	transition
	•	visual emphasis

The visual plan must be created BEFORE rendering.

10. ASSET GENERATION

Build an asset-generation abstraction.

The image-generation provider/model must be configurable.

Do not hard-code the architecture around one image model.

Each asset should store:

asset_id
prompt
model
source
style
resolution
aspect_ratio
generation_time
story_beat
license/status

Prefer fewer high-quality assets over dozens of mediocre assets.

11. STYLE CONSISTENCY

Each video must have a deliberate visual art direction.

Examples:

	•	cinematic scientific illustration
	•	editorial science artwork
	•	vintage scientific plates
	•	graphic-novel documentary
	•	futuristic technical illustration
	•	hand-drawn educational illustration

Choose a style appropriate to the story.

The system should establish a “visual bible” before generating assets.

The visual bible should define:

	•	illustration style
	•	lighting
	•	color treatment
	•	line quality
	•	typography
	•	composition style
	•	camera language

Then all assets for that video should follow that bible.

12. DEPTH / PARALLAX

When an illustration benefits from depth, create separate layers:

background
midground
subject
foreground

Then use small differential movements to create convincing parallax.

Do NOT attempt complicated 3D rendering unless genuinely necessary.

2.5D is sufficient.

13. TEXT

Do not use captions merely as subtitles.

Use editorial typography.

Examples:

Normal narration:
small readable subtitle

Important concept:
large phrase

Important number:
large numerical treatment

Scientific mechanism:
annotated diagram

Reveal:
word-by-word or phrase-based animation

Text must never obscure the primary visual.

14. NARRATION-FIRST TIMING

Narration is authoritative.

Do NOT create arbitrary 5-second shots and then force narration into them.

Create the narration.

Break it into semantic phrases.

Then design visuals around those phrases.

The edit should follow the rhythm of the narration.

15. PACING

Avoid long periods where nothing changes visually.

However, do NOT solve pacing simply by changing the image every second.

Use:

camera movement
cropping
layer movement
text
callouts
diagram animation
visual reveals

to create continuous visual interest without requiring a new generated asset for every sentence.

16. AI VIDEO BACKEND — OPTIONAL ONLY

Create an abstraction called:

VideoGenerator

but do not require it for successful rendering.

Potential future providers may include hosted APIs for models such as Wan or other contemporary video models.

The backend should be swappable.

The default implementation should be:

DISABLED / OPTIONAL

If an AI video clip would materially improve a shot, the storyboard may mark:

“video_generation”: true

Otherwise:

false

The entire video must still render successfully when video_generation=false for every shot.

For now, DO NOT spend development effort trying to find a permanently free AI-video API.

Free inference credits are suitable for experiments but are not a dependable production architecture.

17. NO EXTERNAL FOOTAGE

For this first version:

DO NOT use:

	•	stock video
	•	YouTube footage
	•	licensed footage
	•	public-domain footage
	•	downloaded clips

The channel should be visually self-contained.

Generated illustrations, graphics, diagrams, typography, and animation are the default.

18. VIDEO FORMAT

Support:

16:9
9:16

The first prototype should be:

9:16

because it is easier to test rapidly and provides a natural fit for the reference visual language.

Later support:

30–90 sec
90–180 sec
3–5 min

The same underlying storytelling engine should support all formats.

19. FIRST PROTOTYPE

DO NOT build a huge system first.

Build ONE excellent vertical slice.

Target:

45–60 seconds.

Requirements:

	•	5–7 story beats
	•	5–8 generated illustrations
	•	intelligent reuse of illustrations
	•	camera movement
	•	at least one diagram
	•	kinetic typography
	•	narration
	•	captions
	•	transitions
	•	audio mastering
	•	final MP4
	•	automated QA report

The objective is not architectural completeness.

The objective is:

“Can this system produce a video that actually looks good?”

20. QUALITY BAR

The prototype should be judged on:

STORY
HOOK
VISUAL QUALITY
PACING
CLARITY
ORIGINALITY
EDITORIAL QUALITY
NARRATION SYNC
TEXT QUALITY
VISUAL VARIETY

A technically successful render that looks boring is a FAILURE.

21. QA

Automate checks for:

	•	missing assets
	•	missing shots
	•	black frames
	•	rendering errors
	•	caption clipping
	•	text overflow
	•	audio/video duration mismatch
	•	narration synchronization
	•	excessive stillness
	•	excessive repetition
	•	visual continuity
	•	incorrect aspect ratio
	•	corrupted final output

Also create a visual QA contact sheet so the generated shots can be reviewed rapidly.

22. ITERATION MODEL

Never regenerate the entire video because one shot is bad.

Identify the failed component.

Examples:

bad image
→ regenerate image

bad crop
→ modify camera

bad caption
→ modify typography

bad timing
→ modify edit plan

bad narration
→ regenerate audio

bad transition
→ change transition

Then render only the affected section.

23. COST CONTROL

We are deliberately designing around low cost.

Use:

GLM-5.3-FLASH only for orchestration.

DO NOT use GLM-5.3 main unless explicitly instructed.

Keep prompts compact.

Keep context compact.

Do not dump entire project history into every request.

Use structured JSON artifacts.

Do not spawn uncontrolled sub-agents.

Use bounded parallelism only when justified.

Cache every successfully generated asset.

Never regenerate unchanged assets.

24. ARCHITECTURE

Suggested structure:

video_engine/
research/
story/
visual/
assets/
motion/
typography/
audio/
compositor/
qa/
providers/
templates/
output/

Intermediate artifacts:

research.json
story.json
visual_plan.json
assets.json
edit_plan.json
qa.json

Every generated video must be reproducible from these artifacts.

25. IMPORTANT DEVELOPMENT RULE

Do NOT spend the first development cycle building a sophisticated framework.

First prove the visual language.

Build:

ONE STORY
→ ONE VISUAL BIBLE
→ ONE 60-SECOND VIDEO
→ REVIEW

Then improve the engine.

Only after the visual quality is convincing should you generalize it.

26. SUCCESS DEFINITION

Success is NOT:

“the program generated an MP4.”

Success is:

“A viewer who does not know that this was generated automatically would perceive it as a deliberately edited, visually interesting science/technology documentary.”

Priorities:

STORY

VISUAL QUALITY

PACING

CLARITY

ORIGINALITY

POLISH

TECHNICAL COMPLEXITY

Build for quality first, automation second.

Start by examining the existing repository only for reusable components such as:

	•	research
	•	TTS
	•	audio mastering
	•	FFmpeg
	•	QA
	•	telemetry

Do NOT preserve the old video architecture merely because it exists.

At the end of the first milestone, provide:

	1.	architecture
	2.	files created
	3.	prototype topic
	4.	generated visual assets
	5.	final video path
	6.	QA results
	7.	known weaknesses
	8.	recommended next change

Do not claim the approach works until an actual video has been rendered and visually inspected.