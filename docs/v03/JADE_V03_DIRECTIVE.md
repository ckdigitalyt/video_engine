FINAL V0.3 DIRECTIVE
Build an Agentic Daily Video Generation System, Not a One-Off Video
The objective of this phase is NOT to make “Why is the sky blue?” perfect.
The objective is to upgrade the video-generation program itself so that it can autonomously create a stream of high-quality educational motion-graphics videos on different topics every day.
The system must become an agentic video-production system that can:
discover topic
→ research
→ design story
→ select visual representation
→ identify hero mechanism
→ construct semantic world
→ generate animation plan
→ render
→ inspect actual output
→ diagnose weaknesses
→ repair
→ learn from the result
→ produce final video
→ update its reusable knowledge/primitive/template library
The system should be designed for:
different topics every day, without manually designing the storyboard or animation for each topic.
 
⸻
 
1. DO NOT OPTIMIZE FOR A PERFECT BENCHMARK VIDEO
The Sky Blue video is a diagnostic test.
Do NOT hard-code a perfect solution for:
	•	sky
	•	scattering
	•	sunlight
	•	atmosphere
Do NOT create topic-specific scene logic merely to make the benchmark look better.
The goal is to make the engine capable of discovering the appropriate visual treatment itself.
The next success criterion is therefore:
Can the engine autonomously produce good visual explanations for topics it has never seen before?
 
⸻
 
2. THE CORE PRODUCT IS THE PROGRAM
The product is NOT:
a collection of beautiful videos
The product is:
a system that reliably produces beautiful videos
Every change should therefore be evaluated according to:
	1.	Does it generalize?
	2.	Does it reduce manual intervention?
	3.	Does it improve multiple unrelated topics?
	4.	Does it create reusable capability?
	5.	Does it make future videos easier to generate?
	6.	Can the agent diagnose and repair failures automatically?
Reject changes that improve only one benchmark through hard-coded logic.
 
⸻
 
3. TARGET END-TO-END DAILY LOOP
The eventual production loop should be:
DAILY JOB
   ↓
Topic discovery
   ↓
Topic scoring
   ↓
Research
   ↓
Fact verification
   ↓
Story architecture
   ↓
Script
   ↓
Visual concept planning
   ↓
Hero mechanism selection
   ↓
Semantic world
   ↓
Shot/beat planning
   ↓
TTS
   ↓
Animation compilation
   ↓
Preview render
   ↓
Visual QA
   ↓
Audio QA
   ↓
Fact/math/physics QA
   ↓
Agent critique
   ↓
Automatic repair
   ↓
Final render
   ↓
Thumbnail/title/description
   ↓
Publish-ready package
   ↓
Post-run learning
   ↓
Library update
No human storyboard should be required for normal operation.
 
⸻
 
4. MAKE THE SYSTEM AGENTIC
The agent should not simply execute a fixed pipeline.
It should make decisions.
Introduce explicit agent roles/stages:
TopicScout
Researcher
FactChecker
StoryArchitect
VisualDirector
HeroMechanismDesigner
WorldBuilder
AnimationDirector
AudioDirector
QAReviewer
RepairAgent
LearningAgent
Publisher
These can use DeepSeek V4 Flash.
They should communicate through structured artifacts rather than free-form text.
 
⸻
 
5. EVERY STAGE MUST PRODUCE A MACHINE-READABLE ARTIFACT
For example:
topic.json
research.json
facts.json
story.json
script.json
world.json
visual_plan.json
hero.json
beats.json
shots.json
visualspec.json
audio_timeline.json
qa.json
repair_plan.json
learning.json
This allows the system to:
	•	retry individual stages
	•	compare versions
	•	cache results
	•	diagnose errors
	•	learn from prior runs
	•	resume interrupted jobs
Do NOT store critical state only in logs.
 
⸻
 
6. CREATE A LONG-TERM KNOWLEDGE LIBRARY
This is one of the most important additions.
Create a persistent internal library containing:
knowledge/
├── topics/
├── visual_patterns/
├── story_templates/
├── hero_mechanisms/
├── primitives/
├── simulations/
├── camera_patterns/
├── audio_patterns/
├── successful_shots/
├── failed_shots/
├── qa_failures/
└── learned_rules/
The agent should learn from every completed run.
 
⸻
 
7. CREATE A VISUAL PATTERN LIBRARY
A visual pattern is reusable across many topics.
Examples:
signal → processor → output

cause → mechanism → effect

input → transformation → output

before → change → after

many paths → common destination

small experiment → extreme experiment

zoom out → reveal system

zoom in → reveal mechanism

microscopic process → macroscopic effect

comparison A vs B

timeline evolution

network propagation
These are much more valuable than topic-specific scenes.
 
⸻
 
8. CREATE A STORY TEMPLATE LIBRARY
Maintain reusable narrative structures:
Mystery → Experiment → Reveal

Question → Demonstration → Explanation

Counterintuitive Fact → Proof → Payoff

Prediction → Test → Surprise → Explanation

Simple Case → Extreme Case → General Rule

Problem → Failure → Insight → Solution

What You See → What Actually Happens → Why

Zoom In → Mechanism → Zoom Out → Consequence

Follow One Object → Reveal the System
The StoryArchitect chooses one based on the topic.
The story template must NOT dictate the visuals mechanically.
It provides a structural starting point.
 
⸻
 
9. HERO MECHANISM MUST BE A FIRST-CLASS OBJECT
For each video the system should identify:
{
  "hero_mechanism": {
    "concept": "...",
    "representation": "...",
    "objects": [],
    "actions": [],
    "why_this_visual": "..."
  }
}
The hero mechanism is:
the single visual demonstration that makes the core concept click.
This is the most important visual decision in the entire production.
Examples:
Satellite
fall + sideways velocity → orbit
McGurk
visual speech + auditory speech → fused perception
Sky
wavelength-dependent scattering → blue sky
Noise cancellation
sound wave + inverse wave → interference
Kaprekar
digit transformation → fixed point
The engine should discover this rather than receive it manually.
 
⸻
 
10. ADD HERO-MECHANISM QUALITY CONTROL
Before rendering, the agent must ask:
“If the viewer remembers only one visual from this video, what should it be?”
If there is no clear answer:
hero_quality = FAIL
The StoryArchitect/VisualDirector must revise the plan.
 
⸻
 
11. REPRESENTATION SELECTION MUST BE GENERAL
The system should choose among:
SIMULATION
DIRECT_DIAGRAM
PHYSICAL_MODEL
SIGNAL_FLOW
CAUSE_EFFECT
COMPARISON
GRAPH
TIMELINE
NETWORK
TRANSFORMATION
EXPERIMENT
CHARACTER_ACTION
METAPHOR
REAL_MEDIA
KINETIC_TEXT
HYBRID
The default should NOT be text.
The selection should be based on the information structure of the concept.
 
⸻
 
12. INTRODUCE “WHY THIS VISUAL?” REASONING
For every major beat, store:
{
  "concept": "gravity causes orbital curvature",
  "representation": "physical_simulation",
  "visual": "satellite_fall_plus_tangent_velocity",
  "reason": "directly demonstrates the causal mechanism"
}
This is important for self-critique.
The QA agent can then ask:
Does the rendered visual actually fulfill the stated reason?
This creates a feedback loop between intention and result.
 
⸻
 
13. VISUALS MUST EXPLAIN, NOT DECORATE
Every beat should be classified:
demonstrate
illustrate
compare
emphasize
transition
atmosphere
Normally:
demonstrate / illustrate / compare
should dominate.
Do not allow the engine to produce:
narration
→ decorative shapes
just to increase motion.
 
⸻
 
14. KEEP KINETIC TYPOGRAPHY, BUT DEMOTE IT
Kinetic typography is useful for:
	•	hooks
	•	questions
	•	key terms
	•	numbers
	•	surprising claims
	•	final reveals
But:
a full explanatory sentence should normally be spoken rather than displayed as the main visual.
The system should ask:
Can this sentence be demonstrated visually?
If yes, do that.
If not, use text.
 
⸻
 
15. CREATE A GENERAL SEMANTIC WORLD MODEL
Continue the new WorldState architecture.
It should support:
entities
relationships
states
forces
signals
measurements
events
facts
assumptions
sources
The world model is what allows the system to reason about:
what exists
what affects what
what changes
what should persist
what should disappear
This should become the central abstraction between research and animation.
 
⸻
 
16. MAKE RELATIONSHIPS FIRST-CLASS
Examples:
gravity → satellite

sound → microphone

microphone → processor

processor → inverse signal

eye → brain

ear → brain

sunlight → atmosphere

wavelength → scattering probability
The Visual Director should be able to request:
show relationship
animate relationship
highlight relationship
reverse relationship
break relationship
strengthen relationship
compare relationships
This is more powerful than simply requesting objects.
 
⸻
 
17. EXPAND THE ACTION GRAMMAR
The action grammar should become generic enough to describe many domains.
Include:
enter
exit
move
transform
morph
grow
shrink
rotate
orbit
fall
accelerate
decelerate
oscillate
scatter
converge
diverge
branch
merge
flow
pulse
propagate
collide
miss
interfere
cancel
trace
compare
measure
highlight
focus
zoom
pan
reveal
hide
assemble
disassemble
Every action must map to a reusable implementation.
Unknown actions must fail explicitly.
 
⸻
 
18. SIMULATION SHOULD BE A FIRST-CLASS CAPABILITY
For suitable topics, prefer deterministic simulation over illustration.
Create generic simulation frameworks for:
physics
waves
signals
particles
networks
growth
decay
motion
orbits
collisions
probability
spreading
Each simulation must expose parameters.
Example:
{
  "simulation": "wave_interference",
  "parameters": {
    "frequency": ...,
    "amplitude": ...,
    "phase_difference": ...
  }
}
The simulation output must be deterministic.
 
⸻
 
19. SEPARATE “WORLD MODEL” FROM “RENDERING”
This is essential.
The World Model should say:
satellite has velocity
earth exerts gravity
satellite follows curved trajectory
The renderer decides how to display it.
This lets the same world model later render through:
Manim
SVG
Motion Canvas
Web
without changing the semantic intelligence.
 
⸻
 
20. MAKE COMPOSITION AN EXPLICIT STAGE
The current system is improving the semantic content, but composition must become its own planning problem.
Create:
CompositionPlanner
It determines:
	•	focal object
	•	object scale
	•	spatial arrangement
	•	camera target
	•	visual hierarchy
	•	negative space
	•	when to zoom
	•	when to reframe
	•	what exits
	•	what remains
The same objects can produce a bad or excellent video depending on composition.
 
⸻
 
21. USE ATTENTION AS A DESIGN OBJECTIVE
For each shot determine:
focal_object
supporting_objects
background
text
camera
There should normally be one clear focal point.
Create metrics:
focal_area_ratio
semantic_object_area
empty_area_ratio
text_area_ratio
focal_contrast
Do not maximize density.
Maximize:
clarity of attention.
 
⸻
 
22. ADD PACING INTELLIGENCE
The system should understand:
fast reveal
slow explanation
pause
build
escalation
climax
release
Don’t make every beat the same length.
The StoryArchitect should vary pacing based on narrative importance.
Hero mechanisms should have enough time to be understood.
 
⸻
 
23. TTS IS TEMPORAL INPUT, NOT THE STORY DESIGNER
Continue:
script
→ TTS
→ actual timing
but do NOT let TTS duration determine the conceptual depth.
The correct sequence is:
topic
→ story
→ script of appropriate length
→ TTS
→ timing
→ visual plan
If the explanation needs 45 seconds, write a 45-second explanation.
Do not force a complex concept into 20 seconds merely because the initial generated script was short.
 
⸻
 
24. DAILY TOPIC ENGINE
Build a TopicScout that can choose one topic per day.
Scoring should consider:
curiosity
novelty
visual potential
educational value
story potential
search interest
shareability
comment potential
production feasibility
source availability
Avoid selecting topics that cannot be meaningfully visualized.
 
⸻
 
25. TOPIC DIVERSITY
The production scheduler should avoid repeating the same visual grammar too frequently.
Track:
topic category
representation type
story template
hero mechanism type
recent topics
Example daily rotation:
science
psychology
technology
mathematics
space
history
human body
everyday phenomenon
engineering
The exact schedule can be learned from channel performance later.
 
⸻
 
26. CREATE A VIDEO PROFILE BEFORE GENERATION
Before starting production, create:
{
  "topic": "...",
  "category": "...",
  "story_template": "...",
  "hero_mechanism": "...",
  "representation": "...",
  "target_duration": "...",
  "visual_style": "...",
  "primary_primitives": [],
  "risk_flags": []
}
This is the video’s production contract.
 
⸻
 
27. ADD RISK-BASED PLANNING
Research should identify:
factual_risk
math_risk
physics_risk
visual_complexity
asset_dependency
copyright_risk
rendering_complexity
The system should choose simpler alternatives when a concept is too difficult to render reliably.
 
⸻
 
28. ADD SELF-CRITIQUE BEFORE RENDER
The agent should review the plan before expensive rendering.
Questions:
Is the hook strong?

Is there a clear hero mechanism?

Are the visuals actually explanatory?

Is text overused?

Does each important concept have a representation?

Is the composition likely to be readable?

Are there unnecessary objects?

Will the animation fit the narration?

Are facts verified?
Reject bad plans early.
 
⸻
 
29. ADD SELF-CRITIQUE AFTER PREVIEW
After rendering:
Inspect actual frames.
The reviewer should return:
{
  "score": 0-100,
  "strengths": [],
  "problems": [],
  "repair_actions": []
}
Problems should be tied to beats.
Example:
{
  "beat": "b005",
  "problem": "hero mechanism too small",
  "severity": "high",
  "repair": "zoom camera to scattering field and remove secondary labels"
}
 
⸻
 
30. AUTOMATIC REPAIR MUST BE LOCAL
Do not regenerate the entire video if Beat 5 is bad.
Instead:
Beat 5 fails
→ modify Beat 5
→ rerender Beat 5
→ recompose
→ rerun QA
This is essential for daily operation.
 
⸻
 
31. ADD A LEARNING AGENT
This is the most important “agentic” addition.
After every production run:
video
+
QA
+
critic feedback
+
repair history
should create:
learning.json
Example:
{
  "failure": "hero mechanism too small",
  "cause": "default composition scale 0.6",
  "fix": "hero scale 1.3",
  "domain": "science",
  "representation": "simulation",
  "reusable_rule": "hero objects need >= X% active frame area"
}
The next videos should be able to reuse these learned rules.
 
⸻
 
32. NEVER LET THE LEARNING AGENT MODIFY CODE DIRECTLY WITHOUT TESTS
Learned rules should initially go into:
learned_rules.yaml
or equivalent structured storage.
The agent can propose code changes, but code modification must go through:
proposal
→ tests
→ benchmark
→ acceptance
→ promote
This prevents the system from degrading itself.
 
⸻
 
33. CREATE A REGRESSION BENCHMARK SUITE
Maintain five representative topics:
Kaprekar
Collatz
Satellite orbit
McGurk effect
Sky blue
After every meaningful engine change:
run all five
Do not require every benchmark to improve every time.
But no existing capability should regress silently.
Record:
story score
visual score
explanation score
text dominance
QA
render time
failure count
 
⸻
 
34. ADD UNSEEN-TOPIC EVALUATION
The five regression topics are not enough.
Periodically generate completely new topics.
Examples:
How noise-cancelling headphones work
Why popcorn pops
How a microwave heats food
Why ice is slippery
Why airplane wings generate lift
Why GPS needs relativity
Why mirrors reverse left-right
How a barcode works
How a camera autofocuses
The engine must not receive manually created storyboards for these.
These are the true generalization tests.
 
⸻
 
35. DAILY AUTONOMOUS MODE
Create a production command conceptually like:
python -m engine.daily_run
It should:
choose topic
research
plan
generate
QA
repair
finalize
with no manual storyboard.
At the end:
results/YYYY-MM-DD/topic_slug/
contains all artifacts.
 
⸻
 
36. DAILY FAILURE POLICY
Do NOT force publication when the output is poor.
Classify:
PASS
REPAIR
REGENERATE
ABORT
For example:
technical failure
→ repair

visual score 65
→ repair

fact verification failure
→ regenerate research/story

visual explanation < 3
→ regenerate visual plan

copyright/asset risk
→ choose alternative representation
A daily system needs the ability to reject its own bad work.
 
⸻
 
37. DAILY BUDGET / COMPUTE MANAGEMENT
Because the server is only:
4 CPU
24 GB RAM
the agent should optimize:
cache
incremental rendering
local procedural graphics
limited concurrency
preview-first QA
Do not generate expensive full renders before the plan passes preflight.
 
⸻
 
38. KEEP DEEPSEEK FOR HIGH-VALUE REASONING
Use DeepSeek for:
topic selection
research synthesis
story
visual representation
hero mechanism
shot planning
critique
repair
learning
Don’t waste calls on:
simple arithmetic
layout calculations
physics formulas
file management
schema validation
frame measurements
Those should be deterministic.
 
⸻
 
39. MAKE THE AGENT CHEAPER OVER TIME
Caching should occur at:
research
facts
story templates
visual patterns
primitive selection
TTS
rendered beats
QA
If a previous topic has already been researched, reuse it where factual freshness permits.
If a known visual pattern works, reuse its planning structure.
Do not regenerate everything from scratch.
 
⸻
 
40. PROMOTE SUCCESSFUL PATTERNS INTO THE LIBRARY
If the system repeatedly discovers:
signal → inverse signal → combine
is effective for sound explanations, save it.
If:
zoom into mechanism
works repeatedly for science videos, save it.
If:
experiment → variable increase → extreme → insight
produces strong videos, save it as a reusable story pattern.
This is how the system should improve.
 
⸻
 
41. QA SHOULD MEASURE THE PROGRAM, NOT ONLY THE VIDEO
Track over time:
average explanation score
average perceptual score
technical failure rate
repair rate
regeneration rate
text-dominance rate
hero-mechanism success rate
visual primitive reuse
render time
DeepSeek cost
manual intervention
The objective is not just better individual videos.
It is:
better videos with less intervention over time.
 
⸻
 
42. DEFINE THE REAL SUCCESS METRIC
The program’s success metric should eventually be:
Autonomous Publishable Video Rate
=
videos that pass quality threshold
/
videos attempted
Track:
APVR
alongside:
average visual score
average explanation score
repair rate
manual intervention rate
A system that makes one perfect video but requires manual work is inferior to one that reliably produces 8 strong videos out of 10 autonomously.
 
⸻
 
43. DON’T OVERFIT TO THE REFERENCE VIDEOS
Use the reference channels to learn principles:
	•	strong hooks
	•	visual explanation
	•	motion
	•	narrative
	•	hierarchy
	•	payoff
Do not hard-code their exact visual language.
The channel should develop its own consistent visual identity.
 
⸻
 
44. KEEP MathMotion Lab AS R&D
Maintain:
~/mathmotion-lab/
as an experimental laboratory.
Use it to develop:
	•	new primitive
	•	new animation
	•	new simulation
	•	new camera style
	•	new hero mechanism
Then:
prototype
→ test
→ generalize
→ unit test
→ promote to video_engine
Do not make the production engine dependent on experimental code.
 
⸻
 
45. PRIORITY ORDER
Do NOT implement everything simultaneously.
Proceed in this order:
Phase A
Complete the v0.3 autonomous architecture.
Phase B
Make composition/attention a first-class planning stage.
Phase C
Make hero-mechanism planning robust.
Phase D
Make visual explanation scoring robust.
Phase E
Implement automatic preview critique and local repair.
Phase F
Implement learning memory.
Phase G
Implement daily topic scouting.
Phase H
Implement five-topic regression suite.
Phase I
Implement unseen-topic evaluation.
Phase J
Implement autonomous daily mode.
 
⸻
 
46. FIRST DEVELOPMENT TEST
Do NOT optimize a single Sky Blue video manually.
Instead perform this experiment:
Run the EXACT SAME v0.3 program with topic-only input:
Why is the sky blue?
then:
How do noise-cancelling headphones work?
then:
Why does popcorn pop?
No manually supplied storyboard.
Compare the three.
The engine succeeds if it independently chooses three different visual grammars:
sky:
light + atmosphere + scattering

noise cancellation:
wave + microphone + inverse signal + interference

popcorn:
water/steam + pressure + shell + explosion
without falling back to text-heavy narration.
 
⸻
 
47. THE KEY DESIGN TEST
For every generated video ask:
“Could a human animator understand the intended visual explanation from the JSON plan without hearing the narration?”
If yes:
good.
If the JSON plan is effectively:
show sentence
zoom
highlight sentence
the visual director has failed.
 
⸻
 
48. FINAL DEFINITION OF DONE
The v0.3 engine is complete when:
I can provide ONLY:
topic
and the system autonomously produces:
research
story
script
hero mechanism
world
visual representation
beats
shots
animation
audio
QA
repair
final video
thumbnail
metadata
and does so across different domains without manual storyboarding.
It must be able to handle:
mathematics
physics
space
psychology
technology
everyday science
engineering
using different visual grammars.
The engine must learn from prior successes/failures and continuously improve its reusable library.
 
⸻
 
49. MOST IMPORTANT PRINCIPLE
Do not build:
a program that knows how to make one beautiful video.
Build:
a program that knows how to figure out how a beautiful explanatory video should be made.
That is the system we ultimately need for daily autonomous YouTube production.
