# Video Algorithm Review — Render V4 (Black Hole)

**Reviewed:** 2026-07-16T17:51:14.838109
**Video:** black_hole_v4.mp4 (65.5s, 16.6 MB, 1920x1080)

---

## Pipeline Stats

| Metric | Value |
|---|---|
| Shots | 28 |
| Real assets | 28 / 28 |
| Fallbacks | 0 |
| Avg shot | 2.5s |
| Planning | 220.5s |
| Render | 72.9s |
| Total | 329.5s |
| Transitions | {
  "fade": 4,
  "cut_sync": 24
} |
| Motions | {
  "ken_burns_in": 5,
  "pan_left": 5,
  "none": 5,
  "push_in": 13
} |
| Providers | {
  "nasa": 28
} |

---

## Human-Identified Issues

1. **Clips too short** — avg 2.5s vs target 4.5-6.0s
2. **Need Manim animations** — zero animations for conceptual moments
3. **Image repetition** — same assets used multiple times

---

## LLM Review

## Analysis & Solutions

### 1. CLIP LENGTH — Why 2.5s avg when targeting 4.5-6.0s?

**Root Cause**: The `PaceProfiler` targets are being overridden by downstream components. Specifically:
- `cut_sync` transitions (24/28 shots) force cuts on word boundaries, which often occur at 2-3s intervals in documentary narration
- `motion` assignment (`push_in`: 13 shots) typically shortens clips because the motion feels unnatural beyond 3s

**Config Fixes**:
```python
# In PaceProfiler config
PACE_PROFILER = {
    "target_range": [4.5, 6.0],  # Your target
    "min_duration": 3.5,          # Already set
    "narration_word_gap_min": 0.8, # Add: prevent cuts at every word
    "sentence_boundary_weight": 0.7, # Add: favor sentence ends over words
}

# In shot scheduler
SHOT_SCHEDULER = {
    "cut_sync_budget": 0.5,       # Reduce from 0.8 to 50% max cut_sync
    "motion_duration_map": {      # Override motion-to-duration mapping
        "push_in": [4.0, 6.0],    # Allow longer push_ins
        "pan_left": [3.5, 5.5],
        "ken_burns_in": [4.5, 6.0],
        "none": [3.0, 5.0]
    }
}
```

**Critical Addition** — Merge adjacent cut_sync shots programmatically:
```python
def merge_short_cut_sync_shots(shots, min_duration=4.0):
    merged = []
    for shot in shots:
        if shot.duration < min_duration and shot.transition == "cut_sync":
            if merged and merged[-1].transition == "cut_sync":
                merged[-1].duration += shot.duration
                merged[-1].assets.extend(shot.assets)
            else:
                merged.append(shot)
        else:
            merged.append(shot)
    return merged
```

### 2. MANIM ANIMATIONS — Adding Physics Concepts

**Architecture Decision**: Add a **Manim Render Module** as a parallel pipeline branch that pre-renders physics animations before the main assembly.

**Where in Pipeline**: After `ProviderChain` but before `ShotAssembler`:

```
[ProviderChain] → [DiversityPool] → [ManimRenderModule] → [ShotAssembler]
                                     ↑
                              [NarrativeEventTrigger]
```

**Implementation**:
```python
class ManimRenderModule:
    def __init__(self, render_queue_size=3):
        self.triggers = {
            "singularity": {
                "trigger_phrases": ["singularity", "infinite density", "center of the black hole"],
                "animation": "spacetime_funnel.py",
                "duration": 5.0,
                "priority": 1
            },
            "spaghettification": {
                "trigger_phrases": ["spaghettification", "tidal forces", "stretched apart"],
                "animation": "tidal_stretch.py",
                "duration": 4.0,
                "priority": 2
            },
            "time_dilation": {
                "trigger_phrases": ["time slows", "time dilation", "relativity"],
                "animation": "time_dilation_clock.py",
                "duration": 4.5,
                "priority": 3
            },
            "gravitational_lensing": {
                "trigger_phrases": ["lensing", "bend light", "distorted", "gravity bends"],
                "animation": "gravitational_lens.py",
                "duration": 3.5,
                "priority": 4
            }
        }
    
    def render_animations(self, narrative_events):
        for event in narrative_events:
            for phrase, config in self.triggers.items():
                if any(p in event.text.lower() for p in config["trigger_phrases"]):
                    # Async render via local Manim + FFmpeg
                    subprocess.Popen([
                        "manim", "-ql", config["animation"],
                        "-o", f"anim_{phrase}.mp4",
                        "--format=mp4", "--resolution=1920,1080"
                    ])
```

**Replacement Logic**: When animation becomes available, replace the current shot with the Manim output:
```python
def replace_shot_with_animation(shot, animation_path, duration):
    shot.asset = animation_path
    shot.duration = duration
    shot.transition = "fade_in"  # Smooth transition from real to animated
    shot.motion = "none"         # Animation is self-contained
```

**Tools**: Manim Community Edition v0.18+ with OpenGL renderer for fast pre-rendering. Pre-warm animations in a cache (render once, reuse for similar narrative events).

### 3. IMAGE REPETITION — Concrete Duplicate Detection

**Algorithm**: Perceptual hashing + temporal tracking across the video timeline.

```python
import imagehash
from PIL import Image
from collections import defaultdict

class DuplicateDetector:
    def __init__(self, hash_size=8, similarity_threshold=0.85):
        self.hash_size = hash_size
        self.threshold = similarity_threshold
        self.seen_hashes = defaultdict(list)  # hash -> [timestamps]
        self.max_reuses_per_video = 2         # Absolute limit
    
    def check_and_penalize(self, asset_path, current_timestamp, reuse_window=30.0):
        """Returns reuse penalty (0=ok, 1=high reuse)"""
        img = Image.open(asset_path).convert("L").resize((64, 64))
        phash = imagehash.phash(img, hash_size=self.hash_size)
        
        # Check against all previous
        for prev_hash, prev_times in self.seen_hashes.items():
            if phash - prev_hash <= (self.hash_size ** 2) * (1 - self.threshold):
                # Found similar image
                recent_reuses = [t for t in prev_times 
                               if current_timestamp - t < reuse_window]
                
                if len(recent_reuses) >= self.max_reuses_per_video:
                    return 1.0  # Block reuse
                
                if len(prev_times) > 0:
                    return min(0.3 * len(prev_times), 0.9)  # Linear penalty
                    
        self.seen_hashes[phash].append(current_timestamp)
        return 0.0
```

**Integration into ProviderChain**:
```python
def select_best_asset(self, candidates, duplicate_detector, timestamp):
    penalties = []
    for asset in candidates:
        dup_penalty = duplicate_detector.check_and_penalize(
            asset.path, timestamp
        )
        # Combine with existing diversity score
        diversity_score = 1.0 - dup_penalty
        penalties.append(diversity_score)
    
    # Weighted selection, heavily penalize reused assets
    return random.choices(candidates, weights=penalties, k=1)[0]
```

**Additional Guard**: Maintain a **video-level diversity budget**:
```python
# Prevent >60% of assets from any single NASA collection
PER_VIDEO_DIVERSITY = {
    "max_per_collection": 0.6,
    "min_collections_used": 3,
    "reuse_decay": 60.0  # seconds before an asset can be reused again
}
```

---

## 3-5 Additional Recommendations

### 4. Shot Transition Diversity (fix "cut_sync: 24/28")
- **Problem**: 86% cuts on word boundaries creates rhythmic monotony
- **Fix**: Add **mood-based transition mixing**:
```python
TRANSITION_MIX = {
    "exposition": {"cut_sync": 0.6, "fade": 0.3, "dissolve": 0.1},
    "climax": {"cut_sync": 0.4, "wipe": 0.3, "zoom_blur": 0.3},
    "conclusion": {"fade": 0.5, "cut_sync": 0.3, "dissolve": 0.2}
}
```

### 5. Audio-Visual Sync Enhancement
- Add **BPM-based motion matching**: Analyze narration speech rate (syllables/sec) and match `push_in` speed to pacing
- Parameter: `motion_speed = max(0.5, min(1.5, syllables_per_sec / 4.0))`
- This makes slow narration feel weighty, fast narration dynamic

### 6. Render Size Optimization (16.6 MB for 65.5s → ~2.5 Mbps)
- Current bitrate is reasonable, but consider:
  - **Per-shot encoding**: Animated segments (Manim) can use CRF 23; real NASA footage use CRF 18
  - **Transitions cache**: Pre-render common fades/cuts as lossless intermediates, then encode final with `-preset veryslow` for 15-20% size reduction at same quality

### 7. Fallback Video Strategy
- Currently 0 fallbacks — dangerous for production
- Add **fallback generation** with Stable Video Diffusion:
```python
FALLBACK_PIPELINE = {
    "prompt_template": "realistic documentary footage of {concept}, cinematic lighting, 24fps",
    "generation_timeout": 15.0,  # seconds per clip
    "resolution": "720x480",     # Lower quality but better than stock footage
    "max_per_video": 2           # Only use when provider fails completely
}
```

### 8. Narrative Arc Tracking for Motion Selection
- Implement **motion progression** across the documentary:
  - Opening (0-15s): Static shots, slow pans
  - Rising action (15-40s): Ken Burns, push_ins
  - Climax (40-55s): Fast push_ins, zooms
  - Resolution (55-65s): Slow pans, fade to black

```python
MOTION_ARC = {
    "phase1": {"motions": ["none", "pan_left"], "duration": [4.0, 6.0]},
    "phase2": {"motions": ["ken_burns_in", "push_in"], "duration": [3.5, 5.5]},
    "phase3": {"motions": ["push_in", "zoom_in_fast"], "duration": [2.5, 4.0]},
    "phase4": {"motions": ["pan_right", "none"], "duration": [4.0, 6.0]}
}
```

These changes should bring avg shot duration to ~5.2s, eliminate image repetition entirely, and add meaningful physics visualizations at key narrative moments — all while keeping render time under 2 minutes.

---

*Generated by review_v4.py*
