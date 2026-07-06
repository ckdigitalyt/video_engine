# Cinematic Motion & Transition Engine

## Overview

The cinematic effects layer enhances the visual quality of generated videos
by applying **Ken Burns camera motion** and **configurable scene transitions**.

Both engines are **renderer-agnostic** — they produce plain dict descriptors
that any renderer (MoviePy, FFmpeg, HTML5) can consume.

---

## Motion Engine (`src/effects/motion.py`)

### Motion types

| Type | Description |
|------|-------------|
| `zoom_in` | Slow zoom into the centre of the frame |
| `zoom_out` | Slow zoom out from the centre |
| `pan_left` | Gentle horizontal pan right-to-left |
| `pan_right` | Gentle horizontal pan left-to-right |
| `pan_up` | Gentle vertical pan bottom-to-top |
| `pan_down` | Gentle vertical pan top-to-bottom |
| `none` | No motion — static clip |

### How it works

1. `MotionEngine.generate(clip_count)` returns one descriptor per clip.
2. Each descriptor specifies `zoom_start`, `zoom_end`, and `(pan_x, pan_y)`.
3. The renderer applies time-dependent `resize()` and `set_position()` to
   interpolate between start and end values over the clip's duration.

### Determinism

The engine uses a seeded `random.Random` (seed = `effects.random_seed`).
Each clip gets a unique derived seed (`seed + clip_index * 137`) so results
are reproducible across runs.

### Configuration

```yaml
effects:
  random_seed: 42
  motion:
    enabled: true        # Set false to disable all motion
    strength: 0.08       # Zoom/pan amount (0–1 scale)
    probability: 0.85    # Chance any given clip gets motion
```

---

## Transition Engine (`src/effects/transitions.py`)

### Transition types

| Type | Description |
|------|-------------|
| `cut` | Instant switch — no effect |
| `fade` | Fade to black, then fade into the next clip |
| `crossfade` | Cross dissolve — next clip fades in over the previous |
| `dip_to_black` | Dip through a full-black frame |
| `dissolve` | Opacity-based dissolve overlay |
| `zoom` | Zoom-in transition |

### How it works

1. `TransitionEngine.generate(clip_count)` returns one descriptor per clip.
2. The first descriptor is always a `cut` (nothing precedes clip 0).
3. Subsequent descriptors specify the gap transition from clip i-1 to clip i.
4. Non-cut transitions create **overlapping** clips — Clip B starts `duration`
   seconds before Clip A ends, and a crossfade/dissolve bridges the overlap.
5. `fade` and `dip_to_black` insert a `ColorClip([0,0,0])` bridge between clips.

### Determinism

Same seed-based approach as MotionEngine, using `seed + gap_index * 73`.

### Configuration

```yaml
effects:
  random_seed: 42
  transitions:
    enabled: true              # Set false for plain cuts only
    default_transition: "crossfade"
    transition_duration: 0.5   # Seconds
```

---

## Renderer Integration

The `MoviePyRenderer` applies effects during compositing:

1. **Load** video clips from the timeline.
2. **Generate** motion and transition descriptors (once, at render time).
3. **Apply motion** — wraps each clip with time-dependent resize + position.
4. **Apply transitions** — adjusts clip start times for overlap and adds
   crossfade/fade/dissolve effects via MoviePy's built-in transition methods.
5. **Insert bridge clips** — black frames for `dip_to_black` and `fade`.
6. **Composite** everything (with subtitle overlay) into the final video.

No changes to the `Renderer` ABC were needed — the renderer reads all
configuration from `configs/render.yaml` at render time.

---

## Extension Points

### Adding a new motion type

1. Add the type name to `MOTION_TYPES` in `motion.py`.
2. Add a branch in `MotionEngine.generate()` that populates the descriptor.
3. Update `_apply_motion()` in `moviepy_renderer.py` if the motion type
   requires special rendering.

### Adding a new transition type

1. Add the name to `TRANSITION_TYPES` in `transitions.py`.
2. Add a branch in `TransitionEngine.generate()` that produces descriptors.
3. Update `_apply_transition()` in `moviepy_renderer.py` with the effect.
4. Add bridge-clip logic in `MoviePyRenderer.render()` if needed.

---

## Test Strategy

| Area | What it verifies |
|---|---|
| **Motion** | Correct count, valid types, deterministic output, strength/probability tuning |
| **Transitions** | Correct count, first-is-cut, valid types, deterministic output, duration |
| **Disabled** | All clips get `none`/`cut` descriptors |
| **Edge cases** | 0 clips, 1 clip, zero strength, zero duration |
| **Config** | All keys present in YAML, constructor overrides |
| **Renderer integration** | Import helpers, dispatch functions callable |
