# Gemini Video Review — Black Hole Documentary (2026-07-16)

## Summary

This review evaluates the **Black Hole Documentary** pipeline (v3 architecture, beat-based editing, Gemini/DeepSeek LLM, VisualKnowledgeLibrary enrichment) at commit `8522d9f` (the latest HEAD — "three fixes for video-clip-dominant renders"). The video file at `results/black_hole/black_hole_documentary.mp4` **does not exist** — the render script (`render_black_hole.py`) has been written but never executed to completion. The assessment below is based on: the pipeline architecture as captured in source code, the 12 prior investigation reports, the benchmark run on the same topic (5 scenes, 23 shots, **100% fallback rate**), and the timeline JSON from the most recent Fermi Paradox v3 render.

**Critical finding: 0% primary asset success rate.** All 23 shots in the black hole benchmark run were fallback-generated (NASA Ken Burns still images, animated placeholders, emergency gradients). The pipeline is architecturally intact but executionally non-functional for real primary video assets without working API keys for Pexels/Pixabay.

---

## Current Algorithm State

### Pipeline Architecture (Working)
- **EditorialPlanner** → **VisualDirector** (beat mode) → **TimelineBuilder** → **MoviePyRenderer**
- Beat mode: 5 scenes → ~23 beats → ~23 shots
- Transitions forced to `CUT` / `FADE` (motion=OFF per `render_black_hole.py`)
- Ken Burns restored in `_ken_burns_animate` (commit `8522d9f`)
- KnowledgeLibrary enrichment: ConceptPlanner weak-term detection → feeds `preferred_stock_footage_searches`, `preferred_nasa_searches`, `preferred_wikimedia_searches` into the multi-query pool

### Provider Chain (Non-functional)
| Provider | Status | API Key |
|----------|--------|---------|
| **Pexels** | No key → anonymous → zero results | ❌ |
| **Pixabay** | Blocked by `_is_provider_ready` | ❌ |
| **NASA** | `DEMO_KEY` rate-limited (30 req/hr) → exhausted 1st scene | ❌ |
| **Wikimedia** | Functional but serves image-only results, not video | ❌ |

### Fallback Chain (Always Triggered)
100% of shots go through:
1. ❌ **Primary pipeline** (`_process_shot`) — always returns `None`
2. ➡️ **NASA image + Ken Burns** — still images from NASA API, animated with zoom/pan
3. ➡️ **Wikimedia image + Ken Burns** — CC images, same treatment
4. ❌ **Generated image** — unimplemented (returns `None`)
5. ❌ **Reuse scene** — only available after at least one success
6. ➡️ **Animated placeholder** — gradient overlay, ~14 KB
7. ➡️ **Emergency gradient** — solid color, ~9 KB

### Key Files
| File | Role |
|------|------|
| `render_black_hole.py` | 5-scene black hole script; pass per-scene KnowledgeLibrary queries |
| `src/cinematic/director_integration.py` | BeatDirector — multi-provider collection, AssetRanker, KnowledgeLibrary enrichment |
| `src/cinematic/beat_planner.py` | TimelineBuilder (BeatPlanner → ShotPlanner → CinematicEditor) |
| `src/planner/planner.py` | StoryPlanner — scene-level search term generation and sanitisation |
| `src/models/schemas.py` | Strict Pydantic models with cross-field validation |
| `src/director/quality_gate.py` | SemanticGate, ReuseGate, StyleGate, DiversityGate |
| `src/director/fallback_director.py` | 6-tier degradation chain |
| `src/assets/asset_router.py` | Topic-aware provider routing |

---

## Visual Quality Observations

Since the black hole documentary video was never rendered, this assessment is based on the **Fermi Paradox v3 render** (which shares the identical pipeline), cached file quality metrics, and the benchmark data.

### Captured Visual Quality (from cached assets)

**Primary assets (0% of shots — rare case):**
- `scene_0_b0_s0.mp4`: 42 MB, 15s, 1920×1200 → good resolution, native Pexels stock video
- Bitrate: ~22.8 Mbps — excellent quality

**NASA Ken Burns fallback (majority):**
- Avg size ~1 MB (10s at 0.8 Mbps)
- Still images animated with zoom (1.0→1.15-1.35) + random pan
- **No native motion** — all camera movement is synthetic zoom/pan
- Sharp but static originals; visible pixelation during zoom on low-res source images
- Duration locked at 10s regardless of shot need — creates timing misalignment

**Animated placeholders (14 KB, ~4.4s):**
- Two solid-color layers with opacity overlay (`colorchannelmixer=aa=0.15`)
- No motion, no texture, no content
- Visually empty — a colored rectangle with faint overlay
- Bitrate: ~23 Kbps — near-unwatchable

**Emergency gradients (~9 KB, 3s):**
- Solid-color frame (bright blue/purple/maroon)
- Zero visual content — a blank color card
- Bitrate: ~25 Kbps

### Timeline Pacing (from `timeline.json`)
- 10 voice tracks, 51 video clips
- Shots range from 1.3s cutaways to 4.36s primaries
- All transitions are `fade` or `crossfade`
- Most beats have primary + cutaway + backup shot patterns
- No L-cuts, J-cuts, or match cuts in the output (planning stage generates them but the renderer may not respect them)

### Identifiable Visual Problems (from code + cache analysis)

1. **Static NASA images animated with Ken Burns** dominate — these are still photos with synthetic zoom, not video footage. They lack native motion and appear "dead" compared to real stock video.

2. **Placeholder/emergency clips are visually empty** — a flat colored rectangle with no visual information. These appear when NASA image search also fails (rate-limited or no matching images for the query).

3. **Duration mismatch**: All NASA Ken Burns clips are 10s, all emergency clips are 3s, but shot durations in the timeline vary from 1.37s to 5.02s. The clips are trimmed/extended to fit, creating visible hold-on-last-frame or truncation artifacts.

4. **No overlay graphics**: The `motion_graphics_note` field exists but no text overlays, labels, diagrams, or animations are rendered. The knowledge library has `diagrams_charts_timelines` populated but nothing uses them.

5. **No colour or style coherence**: Each fallback produces independently coloured clips — emergency gradients cycle through random palettes, NASA images are whatever NASA serves, placeholders use fixed palettes. No consistent visual identity.

6. **Zero real stock video** for black hole content: The benchmark found 0 Pexels, 0 Pixabay, 0 NASA video hits, 0 Wikimedia hits. The only "real" content is static images from NASA's media archive.

---

## Algorithm Weaknesses Identified (with code references)

### P0 — Critical

#### 1. Zero API Keys → 100% Fallback Pipeline
**File:** `src/assets/asset_router.py` line 455-461
**File:** `src/director/fallback_director.py` lines 79-130
```python
def _is_provider_ready(provider, name):
    if name == "pixabay":
        key = os.environ.get("PIXABAY_API_KEY", "")
        if not key:
            return False
    return True  # pexels, nasa, wikimedia "work without keys"
```
- `PEXELS_API_KEY` is unset → anonymous requests → rate-limited → zero results
- `PIXABAY_API_KEY` is unset → provider skipped by `_is_provider_ready`
- `NASA_API_KEY` is `DEMO_KEY` → 30 req/hour → exhausted within first scene
- `_asset_router.py` claims pexels "works without a key" but it does not — it returns empty results
- **Impact:** Every single shot falls through the entire provider chain, triggering `FallbackDirector` for every shot. The benchmark confirmed 23/23 shots were fallbacks.

#### 2. Empty Primary Pipeline = No Semantic Gate Access
**File:** `src/director/quality_gate.py` lines 93-98
**File:** `src/cinematic/director_integration.py` lines 200-210
- The semantic gate is the most important quality filter, but it only runs when `_process_shot` returns a result
- Since all shots fall back, the semantic gate **never executes** for any shot
- The fallback merely produces "something visible" with hardcoded scores (0.85 for NASA, 0.80 for Wikimedia, 0.70 for placeholder, 0.50 for emergency) — no semantic validation occurs
- **Impact:** The entire quality assurance system for visual relevance is bypassed

#### 3. `_sanitise_search_terms()` Can Return `[]`
**File:** `src/planner/planner.py` lines 402-429
**Investigation:** `2026-07-14-sanitiser-runtime.md`
- When LLM-generated search terms have >60% word overlap with narration text (common for documentary-style prompts), **all terms are replaced**
- The replacement map only covers concrete visual words (~80 entries); abstract concepts (contradiction, evidence, probability) have no replacement
- If all replacements also fail the overlap check, `sanitised_terms` = `[]`
- `sanitised_terms or ["general"]` evaluates to `["general"]` (see P0.4)
- **Impact:** The sanitisation function, intended to protect search quality, can destroy all valid search terms without providing useful alternatives

#### 4. The "general" Search Term — Root Cause of Irrelevant Assets
**File:** `src/planner/planner.py` line 185 (and 5 secondary insertion points)
**Investigation:** `2026-07-14-search-term-lineage.md`
```python
SearchPlan(asset_search_queries=sanitised_terms or ["general"], ...)
```
- When `_sanitise_search_terms()` returns `[]`, the fallback `["general"]` is empty, generic, and semantically meaningless
- `expand_for_shot("general", "cutaway", ...)` → `"general cutaway shot"` — matches completely irrelevant footage
- Served as the root cause for NASA returning Artemis moon mission footage for a Fermi Paradox query
- Propagation chain: `planner.py:185` → `director_integration.py:108` → `query_expander.py:76` → provider API
- Has 5 insertion points across the codebase (planner, schemas, concept_planner, director) — any one can inject `"general"`

### P1 — Important

#### 5. BeatDirector Query Pool Uses Static Rotation — No Narration Signal
**File:** `src/cinematic/director_integration.py` lines 115-125, 150-155
```python
pool = ConceptQueryPool(self._topic, raw_terms, self._concept_planner)
# ...
shot_query = pool.next_query(shot.shot_type.value)
```
- The query pool is populated once per scene and then round-robins queries across shots
- Per-shot queries NEVER incorporate beat narration text or shot visual purpose
- A shot's search query is identical regardless of what the beat actually says
- The KnowledgeLibrary enrichment (commit `8522d9f`) partially mitigates this by adding `preferred_visual_motifs`, but the core architecture still rotates generic queries

#### 6. Shot Descriptions Are Static Labels
**File:** `src/cinematic/beat_planner.py` lines 202-216
```python
def plan_shots(self, beats):
    shots.append(Shot(
        description=f"Primary shot for beat {beat.index}",  # static
        # OR
        description=f"Cutaway detail",  # generic
    ))
```
- The `description` field is a static template string: `"Primary shot for beat N"` or `"Cutaway detail"`
- Contains ZERO information about what the shot should actually show
- Investigation #3 showed that `shot.description or beat.visual_purpose[:100]` tries to fall back to `beat.visual_purpose` — but that's also a generic string like `"Establish context: ..."` or `"Emphasize intensity: ..."`
- **Impact:** The query expansion engine has no semantic signal about what to search for

#### 7. Fallback Unlimited Duration — All Clips Are 10s
**File:** `src/director/fallback_director.py` lines 240, 305, 370, 450
```python
def _ken_burns_animate(self, image_path, prefix, duration=10.0):
```
- Default duration is hardcoded to 10.0 seconds regardless of the shot's actual need
- `_process_shot` passes `shot.duration` when calling `_collect_from_all_providers`, but the fallback chain creates 10.0s clips unconditionally
- Timeline builder must then trim or pad these to fit the beat timing — creating visible artifacts

#### 8. Downloaded Rejected Assets Are Deleted
**File:** `src/cinematic/director_integration.py` lines 183-186
- Investigation #3: NASA downloaded a 13.5 MB Artemis video, quality gates rejected it (semantic_score 0.0), and the file was deleted
- No caching mechanism for rejected assets — every re-run downloads from scratch
- Missed opportunity: rejected assets could be served via the "reuse" fallback for different scenes

#### 9. No Runtime Health Check at Pipeline Start
**File:** `src/assets/asset_router.py` lines 55-70
**File:** `render_black_hole.py` lines 1-13
- The pipeline eagerly clears cache directories and runs without checking API key availability
- The user gets a 5-minute render that produces 100% fallback visual garbage
- A pre-flight check `check_provider_health()` would save time and provide clear error messages

### P2 — Nice-to-Have

#### 10. Motion Graphics / Overlays Unimplemented
**File:** `src/data/knowledge/black_hole.yaml` — 5 diagram types
**File:** `src/cinematic/beat_planner.py` — `ShotPlan.motion_graphics_note` field
- The Knowledge Library defines `diagrams_charts_timelines`, `manim_templates`, and `camera_suggestions`
- The `ShotPlan` schema has a `motion_graphics_note` field for text overlays
- **Nothing uses them** — no Manim animations, no diagram overlays, no text labels
- Black hole documentary is a PERFECT candidate for diagram overlays (event horizon diagram, Schwarzschild radius, accretion disk, gravitational lensing)

#### 11. BeatPlanner Mapper Functions Return Static Values
**File:** `src/cinematic/beat_planner.py` lines 103-116
```python
def _camera_style_to_motion(style): return CameraMotion.STATIC
def _emotion_to_camera_motion(emotion): return CameraMotion.STATIC
def _motion_to_camera_motion(m): return CameraMotion.NONE
```
- Three mapping functions that all return fixed/default values
- The camera style → camera motion pipeline is completely disengaged
- `BeatPlanner.assign_visual_style()` sets rich camera styles (WIDE, CLOSEUP, LOW_ANGLE, TRACKING) but these are dead-ended by the static mappers

#### 12. Pacing Score Uses Hardcoded Weights
**File:** `src/cinematic/beat_planner.py` lines 309-318
```python
pacing_score = round(
    (len(cameras) / 3.0 * 0.3 +
     len(emotions) / 4.0 * 0.3 +
     len(transitions) / 3.0 * 0.2 +
     min(shot_count / len(bep) / 2.0, 1.0) * 0.2) * 100, 1
)
```
- Hardcoded denominators (3.0 cameras, 4.0 emotions, 3.0 transitions) and equal weights (0.3/0.3/0.2/0.2)
- No configurable weighting, no diversity awareness in the score
- Score is informational only — not used by any downstream decision-making

#### 13. CinematicEditor L/J/Match Cuts May Not Render
**File:** `src/cinematic/beat_planner.py` lines 231-249
- `CinematicEditor.edit_sequence()` assigns L-cuts, J-cuts, and match cuts to shots
- These set `transition = Transition.L_CUT / J_CUT / MATCH_CUT` and negative timestamps
- The timeline builder converts `Transition.L_CUT` → `TransitionType.CROSSFADE` (see mapper at line 121)
- The negative timestamps (-0.5s) are preserved but the renderer may not honour them for L-cut audio splitting
- **Impact:** L/J cut sophistication exists in planning but is lost in rendering

---

## Recommended Changes (Priority Order)

### P0 — Critical (Pipeline won't produce quality video without these)

#### P0.1 — Set Pexels/Pixabay API Keys
**What:** Configure `PEXELS_API_KEY` and `PIXABAY_API_KEY` in `.env`
**Why:** The entire primary asset pipeline is non-functional without this. 100% of shots fall back to NASA still images, animated placeholders, or emergency gradients.
**Expected impact:** Primary pipeline success rate goes from 0% to ~60-80% (depending on query quality). Real stock video motion, colour, and content instead of static Ken Burns slideshows.
**File:** `.env` — add:
```
PEXELS_API_KEY=your_key
PIXABAY_API_KEY=your_key
```

#### P0.2 — Replace `"general"` Fallback With Topic-Relevant Terms
**What:** Change `planner.py:185` from `sanitised_terms or ["general"]` to `sanitised_terms or [f"{topic} documentary stock footage", topic]`
**Why:** The literal search term `"general"` produces irrelevant results (confirmed by Investigation #3 — NASA returned Artemis moon mission footage for a Fermi Paradox query). Even the fallback path should produce meaningful search queries.
**Expected impact:** When the sanitisation function destroys all terms, the replacement will search for topic-relevant rather than generic content. This is the single cheapest code fix with the highest quality impact.
**File:** `src/planner/planner.py`, line 185
**Risk:** Zero — only affects the fallback path when no terms survive sanitisation

#### P0.3 — Add Pre-Flight API Key Health Check
**What:** Before starting the pipeline, verify all configured providers have operational API keys. Skip providers that will return empty results.
**Why:** The pipeline happily runs for 5+ minutes producing garbage. A 50ms key check would tell the user upfront.
**Expected impact:** Clear error messages during development; no silent fallback flood.
**File:** New function in `src/assets/asset_router.py` or `render_black_hole.py`
```python
def check_providers():
    status = {}
    for name in ["pexels", "pixabay", "nasa"]:
        key = os.environ.get(f"{name.upper()}_API_KEY", "")
        status[name] = "configured" if key else "missing"
    return status
```

#### P0.4 — Populate Shot Descriptions From Beat Narration
**What:** In `beat_planner.py`, replace static shot descriptions (`"Primary shot for beat N"`) with descriptions derived from the beat's narration text.
**Why:** The ShotPlanner generates descriptions that carry zero semantic signal. The `_process_shot` method uses `shot.description or beat.visual_purpose[:100]` — both are generic. Rich descriptions would give query expansion engines actual signal.
**Expected impact:** More relevant search queries per-shot when using multi-provider candidate collection.
**File:** `src/cinematic/beat_planner.py`, `ShotPlanner.plan_shots()` — replace:
```python
description=f"Primary shot for beat {beat.index}",
# → with
description=f"Visual for: {beat.text[:80]}",
```

### P1 — Important (Will significantly improve output quality)

#### P1.1 — Incorporate Beat-Specific Narration Into Per-Shot Queries
**What:** After round-robin query selection in `BeatDirector._process_shot`, fuse beat narration text into the query string.
**Why:** Currently all shots within a beat share the same rotating queries regardless of what the beat actually says. Adding beat-specific keywords would dramatically improve search relevance.
**Expected impact:** Shots search for content related to what's being spoken, not just rotating generic terms.
**File:** `src/cinematic/director_integration.py` — in `_process_shot`:
```python
# After getting shot_query from pool:
narration_keywords = ' '.join(beat.text.split()[:5])  # top 5 words
shot_query = f"{shot_query} {narration_keywords}"
```

#### P1.2 — Fix Fallback Duration to Match Shot Duration
**What:** Pass `shot.duration` (not hardcoded 10.0) to `_ken_burns_animate()` and all fallback methods.
**Why:** 10s Ken Burns clips for 1.37s cutaways create timing misalignment and waste bandwidth.
**Expected impact:** Tighter timing, less visible trimming/padding in the final video.
**File:** `src/director/fallback_director.py` — change all `duration=10.0` to use the actual duration from the shot context

#### P1.3 — Keep Rejected Downloads Cached
**What:** Don't delete downloaded assets that fail quality gates. Store them in a `cache/rejected/` directory indexed by hash.
**Why:** A 13.5 MB NASA video was downloaded, rejected, and deleted in Investigation #3. Future re-runs or different narration could use it via the "reuse" fallback.
**Expected impact:** Faster re-runs; reuse fallback has more material.
**File:** `src/cinematic/director_integration.py` — after download succeeds:

```python
if not passed:
    # Move to rejected cache instead of deleting
    rejected_path = os.path.join("cache/rejected", f"rejected_{os.path.basename(vp)}")
    shutil.move(vp, rejected_path)
    continue
```

#### P1.4 — Add Per-Query/Shot Logging to Production `_process_shot`
**What:** Add structured logging (queries attempted, provider responses, which gate rejected, rejection reason) to `_process_shot`.
**Why:** Investigation #3 had to monkey-patch to get a trace. Production has no per-query logging — just a terse `"Shot accepted"` message. Makes diagnosing poor asset matches extremely difficult.
**Expected impact:** Debugging asset failures becomes fast instead of requiring instrumentation.
**File:** `src/cinematic/director_integration.py`

### P2 — Nice-to-Have (Would elevate from "functional" to "polished")

#### P2.1 — Implement Diagram/Text Overlays Using Knowledge Library Data
**What:** Use `diagrams_charts_timelines` and `motion_graphics_note` from the beat plan to overlay labels, arrows, and diagrams onto shots.
**Why:** The black hole Knowledge Library defines 5 diagram types (event horizon, Schwarzschild radius, accretion disk, gravitational lensing, stellar collapse timeline). These would transform a static slide show into a genuinely educational video.
**Expected impact:** Massive visual quality improvement for documentary/educational content.
**Files:** New module `src/renderer/overlay_engine.py`; reference from `TimelineBuilder`

#### P2.2 — Fix Camera Motion Mapper to Reflect Actual Camera Choices
**What:** Replace the three stub mapper functions in `beat_planner.py` with real mappings from `CameraStyle`/`Emotion` → `CameraMotion`.
**Why:** The entire camera style system is a fiction — styles are assigned per beat (WIDE, CLOSEUP, TRACKING, etc.) but every style maps to `CameraMotion.STATIC`. The sophistication exists in planning but is lost in execution.
**Expected impact:** Dynamic camera motions per shot instead of all-static.
**File:** `src/cinematic/beat_planner.py`, functions `_camera_style_to_motion`, `_emotion_to_camera_motion`, `_motion_to_camera_motion`

#### P2.3 — Render L/J/Match Cuts Through Timeline
**What:** Ensure that L-cut (audio leads visual), J-cut (visual leads audio), and match cut (same camera style across beat boundaries) are properly rendered, not just noted in planning.
**Why:** `CinematicEditor` assigns these transitions but the mapper converts them all to `CROSSFADE`. L-cuts in particular (negative timestamp, audio overlap) require actual audio track splitting.
**Expected impact:** Smoother, more cinematic editing — the difference between "documentary" and "slideshow."
**Files:** `src/cinematic/beat_planner.py` (mapper), `src/renderer/timeline_builder.py` (audio track splitting)

#### P2.4 — Make Pacing Score Configurable and Actionable
**What:** Expose pacing score weights via config; use the score to drive actual pacing decisions (beat duration adjustment, shot count) instead of just reporting it.
**Why:** The score is computed and available but no downstream component acts on it. The CinematicEditor has `adjust_pacing()` that takes an `energy_level` parameter — these two could be linked.
**Expected impact:** Data-driven pacing decisions.
**File:** `src/cinematic/beat_planner.py`

---

## Risks & Tradeoffs

### Risk 1: KnowledgeLibrary enrichment may not help without API keys
The KnowledgeLibrary enrichment added in commit `8522d9f` injects curated search terms from `preferred_stock_footage_searches`, `preferred_nasa_searches`, `preferred_wikimedia_searches`, and `preferred_visual_motifs` into the query pool. This is a significant improvement ***if*** provider APIs return results for those queries. Without API keys, even the best-curated queries hit dead provider endpoints. **The enrichment fix improves what you search for; P0.1 — the API key fix — is what makes searching actually work.**

### Risk 2: Sanitisation is still a net negative
The `_sanitise_search_terms()` function with the `"general"` fallback (P0.2 fix) is designed to prevent narration text from leaking into search queries. But as Investigation #3 showed, the sanitisation was *too effective* — it destroyed all search terms and left `"general"` in their place. The P0.2 fix (topic-relevant fallback) mitigates the empty-result case but doesn't address the underlying problem: the overlap-based sanitisation is too aggressive for documentary narration where every search term shares vocabulary with the narration. Consider either: (a) lowering the overlap threshold to 70%, (b) adding a semantic embedding check as a secondary gate, or (c) letting through 1-2 high-overlap terms as "bonus" keywords.

### Risk 3: Beat mode vs scene-level rendering gap
In beat mode, assets live in `beat_plans[*].shots[*].asset_plan.filepath`, **not** in `scene.asset_plan.filepath`. Investigation `2026-07-12` found that `scene.asset_plan` is always `None` in beat mode. The TimelineBuilder handles this correctly (reads from beat_plans), but any code path that reads `scene.asset_plan.filepath` without checking `beat_plans` first will silently see `""`. This is a latent bug waiting for a developer who forgets the beat-mode distinction.

### Risk 4: No current test for full pipeline end-to-end
The benchmark suite (`results/benchmark_suite/`) ran on a 5-scene black hole documentary and captured provider stats (all zeros), semantic scores (all 0.0), and fallback count (23/23). The v3 pipeline has no automated end-to-end test. Every change to the pipeline is validated manually by running `render_black_hole.py` or `olbers_render.py`. Adding an end-to-end integration test would catch regressions in the provider chain, beat planner, timeline builder, and renderer.

### Risk 5: MoviePyRenderer dependency
The final rendering step uses `MoviePyRenderer.render("timeline.json", output_path)`. This is a single-function dependency on MoviePy, which has known issues with long renders, memory leaks, and format compatibility. If MoviePy crashes or produces a corrupt output, there is no fallback renderer, no segmentation approach, and no incremental rendering.

---

## Appendix: File Inventory

| Path | Role |
|------|------|
| `render_black_hole.py` | Entry point script (5 scenes, KnowledgeLibrary queries) |
| `src/cinematic/director_integration.py` | BeatDirector — per-shot multi-provider search, ranking, download |
| `src/cinematic/beat_planner.py` | TimelineBuilder — narration→beats→shots→pydantic models |
| `src/planner/planner.py` | StoryPlanner — scene generation, visual intent, search term sanitisation |
| `src/models/schemas.py` | Strict Pydantic models with cross-field validation |
| `src/director/quality_gate.py` | SemanticGate (0.75 threshold), ReuseGate, StyleGate, DiversityGate |
| `src/director/fallback_director.py` | 6-tier degradation: NASA→Wikimedia→Generated→Reuse→Placeholder→Emergency |
| `src/assets/asset_router.py` | Topic-aware provider routing, `_is_provider_ready` gate |
| `data/knowledge/black_hole.yaml` | Knowledge Library — motifs, searches, diagrams, colours |
| `timeline.json` | Last rendered v3 timeline (Fermi Paradox, 10 scenes, 51 clips) |
| `docs/investigations/investigation3-pipeline-failure-analysis.md` | Root cause: Shot 1 cutaway failure |
| `docs/investigations/2026-07-14-sanitiser-runtime.md` | Root cause: `_sanitise_search_terms()` returns `[]` |
| `docs/investigations/2026-07-14-search-term-lineage.md` | Root cause: `"general"` search term propagation |
| `docs/investigations/2026-07-12-runtime-asset-filepath-investigation.md` | Root cause: empty filepath in beat mode |
| `results/benchmark_suite/black_holes_explained_report.json` | Benchmark: 23/23 shots = fallback, 0 primary assets |
