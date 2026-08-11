# Code review (gemini) — model: gemini-3.5-flash

_Generated: 2026-08-11 11:30:52 UTC_

# DOCUMENTARY VIDEO PRODUCTION PIPELINE: SYSTEMIC ROOT-CAUSE REVIEW

**To:** Engineering Leadership & Pipeline Core Team  
**From:** Principal Software Engineer  
**Status:** BLOCKER INVESTIGATION & RESOLUTION PLAN  

---

## EXECUTIVE SUMMARY

Despite repeated point-fixes (up to v21), our documentary production pipeline continues to fail on **the same 5 core defects** (`repeated_assets`, `motion_continuity`, `mirrored_edges`, `claim_contradictions`, `entity_disambiguation`). 

A rigorous, code-level analysis of the pipeline source files reveals that **the previous fixes failed because they targeted the symptoms at generation-time rather than enforcing strict invariants at the rendering/timeline bottlenecks.** Furthermore, our caching mechanisms suffer from state-drift and decouple script updates from visual asset updates, resulting in "gate-gaming" and stale visual assets.

---

## SYSTEMIC ROOT-CAUSE ANALYSIS

```
                       ┌───────────────────────────────────────┐
                       │   1. Script Rewrite (Claim Verifier)  │
                       └───────────────────┬───────────────────┘
                                           │ (Alters Narration / Entities)
                                           ▼
                       ┌───────────────────────────────────────┐
                       │    2. STILLS CACHE REUSE BYPASS       │◀─── [BUG 1]
                       │ (Stale scene0_0.jpg blindly reused)   │     Stills Cache
                       └───────────────────┬───────────────────┘     Not Invalidated
                                           │
                                           ▼
                       ┌───────────────────────────────────────┐
                       │   3. TIMELINE ASSEMBLY & EXPANSION    │
                       │ (Injects scene0_covvar.mp4 variants)  │◀─── [BUG 2]
                       └───────────────────┬───────────────────┘     Bypasses Motion Grammar
                                           │
                                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       4. RENDER & TIMELINE BOTTLENECKS                      │
├──────────────────────────────────────┬──────────────────────────────────────┤
│    [BUG 3] FFmpeg Zoompan Filter     │    [BUG 4] State Tracking Defect     │
│  Zoom goes to 1.0 -> Out of Bounds   │  Stale claim_gate in run_report.json │
│  Mirrored/Smeared Edges Rendered     │  Always flags REVISION_REQUIRED      │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

---

## DETAILED DEFECT DIAGNOSTIC

### Defect 1: `repeated_assets` (Perceptual Repeats)

#### A. Root Cause Trace
* **File:** `src/qa/deterministic_qa.py`  
* **Function:** `_check_repeated_assets` (Lines 185–234)  
* **Trace:** The pipeline calculates the `dhash` of each timeline item's mid-frame or source asset. It flags a perceptual repeat if any two hashes have a Hamming distance of `< self._dup_th + 4` (evaluates to `< 10`, which is extremely loose).
* **The Conflict:** To satisfy the strict pacing/retention gate (`MAX_SHOT_HOLD_S = 4.0`), `mission_stills.py` (inside `build_stills_timeline` -> `_append_coverage_variant` at line 603 and the coverage loop in `stage_stills_visuals` at line 501) programmatically duplicates the primary image and splits it into multiple contiguous sub-segments (variants) with inverted camera directions. 
* Because these sub-segments use the same source image, their perceptual hashes are identical. `_check_repeated_assets` is blind to the context that these are intentional, contiguous coverage shots within the same scene and flags them as a fatal repeated asset error.

#### B. Why Previous Fixes Failed
* **v21 (Commit `879a8cc`):** Introduced a content-based deduplication gate (`_is_dup`) during the *planning* phase. This successfully prevented placing distinct files with identical visual content across scenes. 
* However, it failed because the coverage-padding engine explicitly generates variants *after* this step. The QA gate runs on the completed timeline and makes no exception for intentional contiguous coverage padding (`shot_type == "variant"` or same `scene_id`).

#### C. Concrete Fix Design
We must update `src/qa/deterministic_qa.py` -> `_check_repeated_assets` to ignore perceptual duplicates if they belong to the same `scene_id` and are contiguous timeline events.

```python
# Location: src/qa/deterministic_qa.py -> _check_repeated_assets()
# Replace the hash comparison loop with scene-aware continuity logic:

per_dups = []
seen = []  # List of dicts: {"mid": float, "file": str, "hash": str, "scene_id": int, "type": str}

for i, v in enumerate(entries):
    # ... [existing extraction code] ...
    scene_id = v.get("scene_id")
    shot_type = v.get("shot_type", "primary")
    
    try:
        with Image.open(frame) as im:
            h = dhash(im)
    except Exception:
        continue
        
    for prev in seen:
        # Strict check: only flag if Hamming distance is close (< 6)
        # AND it's either in a different scene, or separated by another asset in the same scene
        if hamming(h, prev["hash"]) < 6:
            is_allowed_padding = (
                scene_id == prev["scene_id"] and 
                (shot_type == "variant" or prev["type"] == "variant") and
                abs(mid - prev["mid"]) < (v.get("duration", 4.0) + 5.0)
            )
            if not is_allowed_padding:
                per_dups.append({
                    "at": [round(prev["mid"], 1), round(mid, 1)],
                    "files": [prev["file"], f],
                    "hamming": hamming(h, prev["hash"]),
                })
    seen.append({"mid": mid, "file": f, "hash": h, "scene_id": scene_id, "type": shot_type})
```

#### D. Verification
* **Gate:** Pre-Render Gate / Publish Gate (`repeated_assets` check).
* **Metric:** `perceptual_repeats` must equal `0` for non-contiguous/cross-scene assets, while allowing continuous coverage padding of the same asset inside a single scene.

---

### Defect 2: `motion_continuity` (Jarring Camera Flips)

#### A. Root Cause Trace
* **File:** `mission_stills.py`  
* **Function:** `_append_coverage_variant` (Line 594) and `build_stills_timeline` (Line 635).
* **Trace:** Camera moves are planned in `stage_stills_visuals` using `_compatible_camera_move()`. However, `build_stills_timeline` dynamically injects coverage variants *after* planning has finished. 
* Within `_append_coverage_variant` (Line 618), the written `"camera_move"` is hardcoded to evaluate zoom direction directly:
  `"camera_move": "pull_out" if mp["zoom_end"] < mp["zoom_start"] else "push_in"`
  This completely ignores the computed `safe_v` fallback (which might be `static` or lateral).
* Because the next scene's camera moves were pre-calculated during the planning phase, they are completely unaware of these dynamically injected variants. This creates jarring direction flips on transition cuts (e.g., Scene 0 ends with an injected `pull_out` and Scene 1 cuts directly into a pre-planned `push_in`).

#### B. Why Previous Fixes Failed
* **v21:** Attempted to call `_compatible_camera_move` inside both `stage_stills_visuals` and `_append_coverage_variant`. 
* It failed because the two stages are decoupled. The planner cannot anticipate timeline-expansion adjustments, and the timeline builder writes the hardcoded zoom direction instead of the validated `safe_v` output.

#### C. Concrete Fix Design
We must implement a **deterministic sequential normalization pass** on the completed timeline right before writing the JSON file. This acts as an absolute bottleneck constraint.

```python
# Location: mission_stills.py -> build_stills_timeline()
# Inject before saving to timeline_path (Line 661):

# --- SEQUENTIAL MOTION CONTINUITY NORMALIZATION PASS ---
prev_move = None
for idx, entry in enumerate(tl["video_timeline"]):
    move = entry.get("camera_move") or entry.get("camera") or "static"
    if idx > 0 and prev_move is not None:
        # Enforce lateral and zoom continuity
        if not validate_motion_sequence(prev_move, move) or (prev_move in ("pan_left", "pan_right") and move in ("pan_left", "pan_right") and prev_move != move):
            # Resolve safe fallback
            fallback_move = "static"
            for alt in _SAFE_MOVE_FALLBACKS:
                if validate_motion_sequence(prev_move, alt):
                    if not (prev_move in ("pan_left", "pan_right") and alt in ("pan_left", "pan_right") and prev_move != alt):
                        fallback_move = alt
                        break
            
            # Heal the entry
            entry["camera_move"] = fallback_move
            mp = dict(entry.get("motion_params") or {"zoom_start": 1.0, "zoom_end": 1.0, "pan_x": 0, "pan_y": 0})
            if fallback_move == "static":
                mp["zoom_start"] = mp["zoom_end"] = 1.05
                mp["pan_x"] = mp["pan_y"] = 0
            elif fallback_move in ("pan_left", "pan_right"):
                mp["zoom_start"] = mp["zoom_end"] = 1.05
                mp["pan_x"] = -15 if fallback_move == "pan_left" else 15
                mp["pan_y"] = 0
            elif fallback_move == "tilt_up":
                mp["zoom_start"] = mp["zoom_end"] = 1.05
                mp["pan_x"] = 0
                mp["pan_y"] = 10
            entry["motion_params"] = mp
            move = fallback_move
            print(f"  [continuity-healed] Adjusted entry {idx} (scene {entry.get('scene_id')}) from {entry.get('camera_move')} to {move} to prevent cut-jar.")
    prev_move = move
```

#### D. Verification
* **Gate:** Deterministic QA Gate (`motion_continuity` check).
* **Metric:** `flips` list in `motion_continuity` metrics must be empty (`len(flips) == 0`).

---

### Defect 3: `mirrored_edges`

#### A. Root Cause Trace
* **File:** `mission_stills.py`  
* **Function:** `_kenburns` (Lines 334–368)  
* **Trace:** When performing a zoom-out, `z_expr` interpolates from `1.22` down to exactly `1.0`. At `zoom = 1.0`, the crop window requested from FFmpeg's `zoompan` filter is exactly the input scale size `3840x2160` (since `iw/1.0 = iw` and `ih/1.0 = ih`).
* When panning parameters (`pan_x` / `pan_y`) are non-zero, or when sub-pixel floating-point rounding errors occur inside FFmpeg's C implementation, the boundary clamp `max(iw-iw/zoom, 0)` evaluates to `0`. 
* Any sub-pixel offset calculation pushes the crop window coordinates slightly negative or outside the bounds of `[0, 3840]`, forcing FFmpeg to pad the missing area with mirrored or smeared edge pixels.

#### B. Why Previous Fixes Failed
* **v19l (Commit `321a56e`):** Clamped the pan expressions using `min(max(...,0), max(iw-iw/zoom,0))`.
* This failed because when zoom reaches exactly `1.0`, the range is exactly `0`. High-resolution inputs combined with float precision errors bypass this clamp inside the compiled filter, causing sub-pixel boundary violations.

#### C. Concrete Fix Design
We must enforce a **mandatory safety margin of 3% zoom** so the crop window never touches the physical image boundary. This provides a safety cushion for panning and sub-pixel float math.

```python
# Location: mission_stills.py -> _kenburns()
# Refactor the zoom boundary assignments (Lines 339-346):

# Clamp zoom values strictly between 1.03 and 1.25 to maintain a 3% boundary margin
if zoom_in:
    z_start = max(1.03, float(cam.get("zoom_start", 1.03)))
    z_end = min(1.25, float(cam.get("zoom_end", 1.22)))
else:
    z_start = min(1.25, float(cam.get("zoom_start", 1.22)))
    z_end = max(1.03, float(cam.get("zoom_end", 1.03)))

# Ensure z_expr handles division safety
z_expr = f"{z_start}+({z_end}-{z_start})*on/{frames}"
```

#### D. Verification
* **Gate:** Publish Gate / Pre-Render Visual Verification.
* **Metric:** Zero occurrences of edge mirroring or pixel smearing artifacts on zoom-out endings.

---

### Defect 4 & 5: `claim_contradictions` & `entity_disambiguation`

#### A. Root Cause Trace
* **File:** `mission_stills.py`  
* **Line Numbers:** Lines 707–759 (Claim verification block), Lines 384–391 (Still cache reuse loop).
* **The State Bug:** The pipeline runs the initial `ClaimVerifier`. It records the results in `run_report["claim_gate"]` at Line 710. If this run fails, it triggers the rewrite loop, parses the corrected scenes, and re-runs the verifier:
  `_claim_gate = ClaimVerifier(llm=llm, research_pack=research).run(scenes_data, out_dir=out_dir)`
  **However, the code never updates `run_report["claim_gate"]` with the new successful report.** 
  As a result, `resolve_status` reads the stale, failed report at the end of execution, forcing the final video status to `REVISION_REQUIRED`.

```
[Initial Claim Check]  ──► Writes run_report["claim_gate"] (FAILED)
                                │
                                ▼
                       [Rewrite Loop Runs]
                                │
                                ▼
[Second Claim Check]   ──► Reports "passed" but NEVER updates run_report["claim_gate"]!
                                │
                                ▼
[Run Complete]         ──► resolve_status() reads Stale Failed Report ──► BLOCKS RELEASE!
```

* **The Cache Bypass (Systemic Pattern A):** When a script is rewritten to fix a claim (e.g. changing "The Bloop is 52 Hz" to "The Bloop is an ultra-low-frequency icequake"), the narration changes. However, the stills cache selection loop at Line 384 blindly reuses cached image files (`sceneX_Y.jpg`) based on file existence on disk:
  `if (os.path.exists(out) and os.path.getsize(out) > 15000 ...)`
  This bypasses the asset gate and allows stale, incorrect visual assets (like images of a 52-Hz whale model) to be rendered alongside the corrected script narration, triggering entity-disambiguation failures in visual QA.

#### B. Why Previous Fixes Failed
* **v14/v19:** Focused on tuning LLM prompts. They failed because they did not address the state-tracking reference bug and the cache bypass, leaving the old failures active in the final status payload and leaving stale visuals on disk.

#### C. Concrete Fix Design
We must resolve the state reference bug, **force invalidation of cached stills on narration hash mismatches**, and make the rewrite loop deterministic.

```python
# Location: mission_stills.py -> main() / Stills Execution Flow
# 1. FIX STATE TRACKING BUG (Update run_report["claim_gate"]):
# Line 733: Inside the try/except block for the claim-fix loop, update the report object:
_claim_gate = ClaimVerifier(llm=llm, research_pack=research).run(scenes_data, out_dir=out_dir)
run_report["claim_gate"] = _claim_gate  # <-- FIX: Actually update the gate reference!
run_report["stages"]["claim_gate_fix"] = {
    "passed": _claim_gate["passed"],
    "blocking": _claim_gate["blocking_failures"],
}

# 2. IMPLEMENT CACHE INVALIDATION FOR STILLS:
# Location: mission_stills.py -> stage_stills_visuals()
# Pass the manifest into stage_stills_visuals() or verify hashes:

# Before planning stills for scene i, check if the narration has changed:
for i, scene in enumerate(scenes_data):
    # Detect if manifest shows narration text changed:
    if not manifest.voice_reusable(i, os.path.join("cache", "audio", f"scene_{i}.wav"), scene.get("narration", "")):
        print(f"  [cache-invalidation] Narration changed for scene {i}. Deleting cached stills to prevent stale assets.")
        for count in range(5):
            cache_file = os.path.join(still_root, f"scene{i}_{count}.jpg")
            crop_file = os.path.join(still_root, f"scene{i}_{count}_crop.jpg")
            if os.path.exists(cache_file):
                os.remove(cache_file)
            if os.path.exists(crop_file):
                os.remove(crop_file)
```

#### D. Verification
* **Gate:** Factual Claim Gate / Publish Gate status resolution.
* **Metric:** `claim_gate_fix` output must overwrite `run_report["claim_gate"]`. `STATUS.json` must resolve to `PUBLISH_READY: true` when the fix loop passes. Stale files must be purged from `/cache/stills/` on narration rewrites.

---

## PRIORITIZED IMPLEMENTATION PLAN

We will execute this structural cleanup across three phases (P0 to P2):

```
┌────────────────────────────────────────────────────────┐
│ P0: STATE-TRACKING & RENDER CONTRAINTS (Critical)      │
├────────────────────────────────────────────────────────┤
│ • Fix the state reference leak for claim_gate.         │
│ • Inject 3% Zoompan safety buffer into _kenburns.      │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ P1: TIMELINE RESOLUTION PASS (Continuity)              │
├────────────────────────────────────────────────────────┤
│ • Enforce sequential normalization in timeline render. │
│ • Update repeated_assets QA rules for padding.         │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ P2: CACHE SYNC & INVALIDATION (Prevent Drift)          │
├────────────────────────────────────────────────────────┤
│ • Implement narration-hash aware stills deletion.      │
└────────────────────────────────────────────────────────┘
```

### P0: Critical State Tracking & Render Constraints
* **Files to Touch:** `mission_stills.py`
* **Changes:** 
  1. Update `run_report["claim_gate"] = _claim_gate` inside the claim-fix block.
  2. Implement the `1.03` minimum zoom clamp inside `_kenburns`.

### P1: Timeline Resolution Pass & QA Update
* **Files to Touch:** `mission_stills.py`, `src/qa/deterministic_qa.py`
* **Changes:**
  1. Add the sequential motion continuity pass at the end of `build_stills_timeline`.
  2. Update `_check_repeated_assets` to support contiguous coverage variants.

### P2: Cache Invalidation Sync
* **Files to Touch:** `mission_stills.py`
* **Changes:**
  1. Implement narration-hash based cache deletion for stills inside `stage_stills_visuals`.