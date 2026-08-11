# Code review (deepseek) — model: deepseek-chat

_Generated: 2026-08-11 11:31:27 UTC_

# Root-Cause Code Review: Documentary Video Production Pipeline

## Executive Summary

The pipeline exhibits **systemic architectural failures** where fixes are applied at detection-time rather than generation-time, and where cache-reuse paths bypass generation-time validation. The five recurring defects share three root causes:

1. **Cache-reuse bypasses generation-time gates** — cached assets skip dedup, camera compatibility, and border checks
2. **Fix loops are gate-gaming** — the claim fix loop rewrites until the gate passes without verifying semantic correctness
3. **Camera-move compatibility is applied inconsistently** — multiple code paths (coverage variants, fill scenes, cache reuse) don't enforce the same grammar

---

## Defect 1: `repeated_assets`

### A. Root Cause

**Primary path**: `mission_stills.py:stage_stills_visuals()` lines ~470-490

The cache-reuse branch at line ~470:
```python
if (os.path.exists(out) and os.path.getsize(out) > 15000
        and fname not in rejected_this_run):
    got, src, title = out, "cached", "cached still"
```

This branch **completely bypasses** the content-based dedup check (`_is_dup()`) that runs at line ~500 for fresh assets. The dedup check only runs after the cache-reuse branch, so cached stills are never compared against `placed_hashes`.

**Secondary path**: `mission_stills.py:_append_coverage_variant()` lines ~700-760

Coverage variants re-render the **same source still** with different camera moves. The `_check_repeated_assets()` in `deterministic_qa.py` (lines ~150-190) correctly detects these as perceptual duplicates, but the generation-time code doesn't prevent them.

**Detection-time**: `deterministic_qa.py:_check_repeated_assets()` lines ~150-190 correctly identifies the issue but only after rendering.

### B. Why Previous Fixes Failed

- **v21 fix** added perceptual dedup to `_check_repeated_assets()` but only at detection-time
- The generation-time `_is_dup()` check at line ~500 only runs for **fresh** assets, not cached ones
- Coverage variants (line ~700) deliberately re-use the same source still, creating guaranteed perceptual duplicates

### C. Concrete Fix Design

**Change**: `mission_stills.py:stage_stills_visuals()` — move the dedup check **before** the cache-reuse branch:

```python
# Move this block BEFORE the cache-reuse check
if os.path.exists(out) and _is_dup(out):
    stats["deduped"] += 1
    print(f"  [dedup] skipped {fname} (perceptually identical to a placed still)")
    continue
```

**Change**: `mission_stills.py:_append_coverage_variant()` — add a `placed_hashes` parameter and check before creating variants:

```python
def _append_coverage_variant(tl, last, scene_end, scene_id, out_path, placed_hashes=None):
    # ... existing code ...
    if placed_hashes and _is_dup(src_img, placed_hashes):
        return  # don't create a variant that's perceptually identical
```

**Change**: `mission_stills.py:build_stills_timeline()` — pass `placed_hashes` to `_append_coverage_variant()`.

### D. Verification

- **Gate**: `deterministic_qa.py:_check_repeated_assets()` — must show `perceptual_repeats: 0`
- **Metric**: `stats["deduped"]` should increase as cached duplicates are now caught

---

## Defect 2: `motion_continuity`

### A. Root Cause

**Primary path**: `mission_stills.py:stage_stills_visuals()` lines ~560-600

The `_compatible_camera_move()` function is called correctly for primary shots, but **coverage variants** at lines ~620-660 have a critical bug:

```python
# v21: variant must not jar against the previous shot either
safe_v = _compatible_camera_move(last_camera_move, vmove)
if safe_v != vmove:
    # ... adjust vcam ...
    vmove = safe_v
```

This check happens **AFTER** `_kenburns()` is called at line ~630:
```python
if _kenburns(src_img, variant, duration=4.0,
             zoom_in=vmove == "push_in", camera=vcam):
```

The `_kenburns()` call uses the **original** `vcam` (with the jarring move), but the timeline entry uses the corrected `vmove`. This means the rendered clip has the wrong camera move.

**Secondary path**: `mission_stills.py:_append_coverage_variant()` lines ~700-760

Same bug pattern — `_kenburns()` is called with the original `mp` before the compatibility check.

**Tertiary path**: `mission_stills.py` fill scenes (lines ~680-720)

The fill scene loop has the same issue — `_kenburns()` is called before `_compatible_camera_move()`.

### B. Why Previous Fixes Failed

- **v21 fix** added `_compatible_camera_move()` but placed it **after** the `_kenburns()` call in coverage variant paths
- The fix only corrected the timeline metadata, not the actual rendered clip
- The `last_camera_move` tracking is inconsistent — it's updated in some paths but not others

### C. Concrete Fix Design

**Change**: `mission_stills.py:stage_stills_visuals()` — reorder the coverage variant logic:

```python
# Compute safe move FIRST
safe_v = _compatible_camera_move(last_camera_move, vmove)
if safe_v != vmove:
    from src.cinematic.camera_language import CAMERA_MOVES
    _m = CAMERA_MOVES.get(safe_v)
    vcam = dict(_m) if _m else {"zoom_start": 1.0, "zoom_end": 1.0,
                                "pan_x": 0, "pan_y": 0}
    vmove = safe_v
# THEN render with the corrected camera
if _kenburns(src_img, variant, duration=4.0,
             zoom_in=vmove == "push_in", camera=vcam):
    # ... append to shots ...
```

**Change**: `mission_stills.py:_append_coverage_variant()` — same reorder:

```python
# Compute safe move FIRST
safe_v = _compatible_camera_move(prev_move, vmove)
if safe_v != vmove:
    from src.cinematic.camera_language import CAMERA_MOVES
    _m = CAMERA_MOVES.get(safe_v)
    mp = dict(_m) if _m else {"zoom_start": 1.0, "zoom_end": 1.0, "pan_x": 0, "pan_y": 0}
    vmove = safe_v
# THEN render
if not _kenburns(src_img, vfile, duration=dur,
                 zoom_in=mp["zoom_end"] > mp["zoom_start"], camera=mp):
    return
```

**Change**: `mission_stills.py` fill scene loop (lines ~680-720) — same reorder.

### D. Verification

- **Gate**: `deterministic_qa.py:_check_motion_continuity()` — must show `flips: []`
- **Metric**: Timeline entries must have `camera_move` matching the actual rendered clip's motion

---

## Defect 3: `mirrored_edges`

### A. Root Cause

**Primary path**: `mission_stills.py:_kenburns()` lines ~330-370

The zoompan filter clamps pan coordinates, but the **source image** may still have borders that get exposed. The `_auto_crop_borders()` function at line ~280 is only called for **fresh** assets:

```python
if os.path.exists(got):
    crop_out = os.path.join(
        still_root, fname.replace(".jpg", "_crop.jpg"))
    cropped = _auto_crop_borders(got, crop_out)
```

**Cache-reuse bypass**: At line ~470, cached assets skip the border check entirely:
```python
if (os.path.exists(out) and os.path.getsize(out) > 15000
        and fname not in rejected_this_run):
    got, src, title = out, "cached", "cached still"
```

**Secondary path**: `mission_stills.py:_kenburns()` lines ~340-360

The zoompan expression clamps to `[0, iw-iw/zoom]` but doesn't account for the **source image's own borders**. If the source has black borders (common in NASA/Wikimedia assets), the pan can expose them even with clamping.

### B. Why Previous Fixes Failed

- **v19n fix** added `_auto_crop_borders()` but only for fresh assets
- **v19l fix** added zoompan clamping but doesn't handle source-image borders
- Cached assets from before the fix are never re-processed

### C. Concrete Fix Design

**Change**: `mission_stills.py:stage_stills_visuals()` — apply border check to cached assets too:

```python
if (os.path.exists(out) and os.path.getsize(out) > 15000
        and fname not in rejected_this_run):
    got, src, title = out, "cached", "cached still"
    # Apply border check to cached assets too
    crop_out = os.path.join(
        still_root, fname.replace(".jpg", "_crop.jpg"))
    cropped = _auto_crop_borders(got, crop_out)
    if cropped and cropped != got:
        got = cropped
        print(f"  [border] using cropped {os.path.basename(got)}")
```

**Change**: `mission_stills.py:_kenburns()` — add a pre-render border check:

```python
def _kenburns(image_path, out_path, duration=6.0, zoom_in=True, camera=None):
    # Check for borders before rendering
    crop_out = image_path.replace(".jpg", "_kb_crop.jpg")
    cropped = _auto_crop_borders(image_path, crop_out)
    if cropped and cropped != image_path:
        image_path = cropped
    # ... rest of function ...
```

### D. Verification

- **Gate**: `PublishGate` — `mirrored_edges` must not appear in `blocking_failures`
- **Metric**: `_auto_crop_borders()` should report crops for cached assets

---

## Defect 4: `claim_contradictions`

### A. Root Cause

**Primary path**: `mission_stills.py:main()` lines ~850-900

The claim fix loop is **gate-gaming**:

```python
if _claim_gate["blocking_failures"]:
    _fix = llm.generate_json(
        "The narration below contains factual errors flagged by a "
        "fact-check gate.  Rewrite the scenes to fix ONLY the errors "
        "(remove wrong numbers, separate conflated phenomena, keep "
        "tone and scene count).  Return STRICT JSON array of scenes "
        "with title/narration/visual_goal/search_queries.\n\n" +
        "Issues: " + json.dumps(_claim_gate["blocking_failures"]) + "\n\n" +
        json.dumps({"scenes": scenes_data})[:6000])
```

The LLM is told to "fix ONLY the errors" but is given the **gate's output** (which may be vague) rather than the **specific claims** that failed. The LLM can:
1. Remove the problematic claim entirely (gaming the gate)
2. Reword to avoid the regex/LLM detection
3. Change numbers to match the research pack without verifying correctness

**Secondary path**: `claim_verifier.py:verify()` lines ~250-300

The verification logic has a critical flaw:
```python
if v in ft or (u and u in ft and v in ft):
    hit = ft
    break
```

This matches if the **number appears anywhere** in the fact text, even in a different context. E.g., "52" in "52-Hz whale" would match a claim about "52 kilometers."

### B. Why Previous Fixes Failed

- **v13 fix** added the claim gate but the fix loop is a single LLM call with no verification of the rewrite
- The fix loop re-runs the gate but doesn't check if the **original** claims were actually resolved vs. removed
- No semantic comparison between pre-fix and post-fix claims

### C. Concrete Fix Design

**Change**: `mission_stills.py:main()` — replace the fix loop with a **claim-preserving rewrite**:

```python
if _claim_gate["blocking_failures"]:
    # Extract the specific failing claims
    failing_claims = [
        c for c in _claim_gate.get("claims", [])
        if c["status"] in ("contradicted", "unsupported")
    ]
    _fix = llm.generate_json(
        "The following claims in the narration are factually incorrect:\n" +
        json.dumps(failing_claims) + "\n\n" +
        "For EACH claim, provide a corrected version that:\n" +
        "1. Keeps the claim's subject and context\n" +
        "2. Uses the correct value from the research pack\n" +
        "3. Does NOT remove or reword the claim to avoid detection\n\n" +
        "Return STRICT JSON: {\"corrections\": [{\"original\": \"...\", "
        "\"corrected\": \"...\"}]}\n\n" +
        "Narration:\n" + json.dumps({"scenes": scenes_data})[:6000])
    # Apply corrections to scenes_data
    # ... apply corrections ...
```

**Change**: `claim_verifier.py:verify()` — improve fact matching:

```python
def _fact_matches_claim(self, fact_text: str, claim: Claim) -> bool:
    """Check if a research fact actually supports a claim."""
    # Extract the number and unit from the fact
    fact_numbers = re.findall(r'\d[\d,\.]*', fact_text)
    if claim.value not in fact_numbers:
        return False
    # Check unit context
    if claim.unit:
        unit_pattern = r'\b' + re.escape(claim.unit) + r'\b'
        if not re.search(unit_pattern, fact_text):
            return False
    # Check the claim's entity appears in the fact
    if claim.entity and claim.entity.lower() not in fact_text.lower():
        return False
    return True
```

### D. Verification

- **Gate**: `claim_verifier.py:run()` — `claim_contradictions` must pass with **all original claims preserved** (corrected, not removed)
- **Metric**: Compare pre-fix and post-fix claim sets — no claims should disappear

---

## Defect 5: `entity_disambiguation`

### A. Root Cause

**Primary path**: `claim_verifier.py:disambiguate()` lines ~180-240

The disambiguation logic has a critical flaw in the **LLM risk corroboration**:

```python
if sev == "critical":
    _co = any(a in s and b in s for s in sentences_l)
    if not _co:
        sev = "major"  # no transfer evidence
```

This **downgrades** critical risks to major when the entities don't co-occur in a single sentence. But the expert's original finding (Bloop vs 52-Hz whale) involved **adjacent sentences**, not same-sentence co-occurrence. The code at lines ~200-230 tries to handle this for the known Bloop case but only for that specific pair.

**Secondary path**: `claim_verifier.py:disambiguate()` lines ~240-260

The LLM disambiguation prompt asks for "pairs of DISTINCT phenomena" but doesn't provide the **research pack** context. The LLM may not know which entities are actually distinct in the documentary's domain.

### B. Why Previous Fixes Failed

- **v13 fix** added the disambiguation step but the corroboration logic is too strict
- The `_is_nickname_pair()` filter (lines ~300-320) may incorrectly drop legitimate risks
- The LLM prompt doesn't include research context, so it can't distinguish between genuine conflation and legitimate comparison

### C. Concrete Fix Design

**Change**: `claim_verifier.py:disambiguate()` — fix the corroboration logic:

```python
# Corroboration: a risk is BLOCKING when the entities appear within
# 2 sentences of each other (adjacent-sentence transfer is the
# expert's documented failure mode)
for h in (res.get("risks", []) or []):
    a = str(h.get("a", "")).strip().lower()
    b = str(h.get("b", "")).strip().lower()
    sev = str(h.get("severity", "major"))
    if _is_nickname_pair(a, b):
        continue
    if sev == "critical":
        # Check for co-occurrence within 2 sentences
        _co = False
        for i, s in enumerate(sentences_l):
            if a in s:
                # Check next sentence
                if i + 1 < len(sentences_l) and b in sentences_l[i + 1]:
                    _co = True
                    break
                # Check previous sentence
                if i > 0 and b in sentences_l[i - 1]:
                    _co = True
                    break
        if not _co:
            sev = "major"
```

**Change**: `claim_verifier.py:disambiguate()` — include research context in the LLM prompt:

```python
_DISAMBIGUATE_PROMPT = """... 
Research context (use this to determine which entities are genuinely distinct):
{research_context}
..."""
```

### D. Verification

- **Gate**: `claim_verifier.py:run()` — `entity_disambiguation` must pass
- **Metric**: The Bloop/52-Hz whale case must be caught even with adjacent-sentence attribution

---

## Prioritized Implementation Plan

### P0 — Critical (Blocking Defects)

| # | File | Change | Effort |
|---|------|--------|--------|
| 1 | `mission_stills.py` | Move dedup check before cache-reuse branch (line ~470) | 30 min |
| 2 | `mission_stills.py` | Reorder coverage variant logic — compute safe camera move BEFORE `_kenburns()` (lines ~620-660) | 1 hr |
| 3 | `mission_stills.py` | Apply border check to cached assets (line ~470) | 30 min |
| 4 | `mission_stills.py` | Reorder fill scene camera logic (lines ~680-720) | 1 hr |

### P1 — High (Recurring Defects)

| # | File | Change | Effort |
|---|------|--------|--------|
| 5 | `mission_stills.py` | Add `placed_hashes` parameter to `_append_coverage_variant()` and check before creating variants | 1 hr |
| 6 | `mission_stills.py` | Replace claim fix loop with claim-preserving rewrite (lines ~850-900) | 2 hrs |
| 7 | `claim_verifier.py` | Fix fact matching logic in `verify()` (lines ~250-300) | 1 hr |
| 8 | `claim_verifier.py` | Fix disambiguation corroboration to check adjacent sentences (lines ~240-260) | 1 hr |

### P2 — Medium (Preventive)

| # | File | Change | Effort |
|---|------|--------|--------|
| 9 | `mission_stills.py` | Add border check to `_kenburns()` as a safety net | 30 min |
| 10 | `claim_verifier.py` | Include research context in disambiguation LLM prompt | 30 min |
| 11 | `deterministic_qa.py` | Add a check that timeline `camera_move` matches actual rendered clip motion | 1 hr |

---

## Systemic Fixes (Beyond Individual Defects)

1. **Cache Invalidation**: The topic cache should store metadata (dHash, camera move, border status) alongside the image. On reuse, validate against current gates before accepting.

2. **Single Source of Truth for Camera Moves**: Create a `CameraMove` class that encapsulates the move name, params, and validation. All code paths (primary, coverage, fill) must use this class.

3. **Fix-Loop Verification**: After any LLM-based fix, verify that:
   - The original claims are preserved (corrected, not removed)
   - The fix addresses the specific failure, not just the gate output
   - The fix is applied to the actual rendered output, not just the script

4. **Gate Consistency**: The `PreRenderGate` and `PublishGate` should share the same validation logic as the generation-time code. If a gate can detect a defect, the generation-time code should prevent it.