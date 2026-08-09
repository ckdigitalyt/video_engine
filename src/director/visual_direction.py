"""
visual_direction.py — Single source of truth for the channel's VISUAL
DIRECTION (Manim registry, flat-vector beats, Jade style lock).

v13 consolidation (2026-08-06): the video pipeline (mission_run.py) and the
stills-first pipeline (mission_stills.py) had diverged — mission_run still
carried a Voyager-only Manim gate and no vector beats, while mission_stills
had the v12.2 flat-vector direction.  Both runners now import THIS module so
the algorithm can never drift again:

  * MANIM_SCENES / TOPIC_MANIM / _TOPIC_HINTS / _manim_scene_for()
      — which animated explanation clips exist and which scenes may use them
        (topic registry + topic-agnostic generic beats).
  * VECTOR_BEATS / _vector_beat_for()
      — Kurzgesagt-style flat-vector animated beats (cache/vector/*.mp4),
        intent-mapped so every scene gets real motion, never pure Ken Burns.
  * FIXED_JADE_STYLE / STYLE_MODIFIERS / _style_prompt_for()
      — ONE locked art direction + palette for all stylized shots.

Channel direction (2026-08-05, ckdigital): flat-vector Kurzgesagt-style,
locked narrator = Chatterbox kurzgesagt_like.  See configs/voices.yaml.
"""

import os
import subprocess
import time

# ── Manim registry ──────────────────────────────────────────────────────

MANIM_SCENES = {
    "voyager_scale": "cache/manim/voyager_scale.mp4",
    "voyager_timeline": "cache/manim/voyager_timeline.mp4",
    "voyager_trajectory": "cache/manim/voyager_trajectory.mp4",
    "sun_scale": "cache/manim/sun_scale.mp4",
    "sun_layers": "cache/manim/sun_layers.mp4",
    "pulsar_lighthouse": "cache/manim/pulsar_lighthouse.mp4",
    "pulsar_density": "cache/manim/pulsar_density.mp4",
    "black_hole_lensing": "cache/manim/black_hole_lensing.mp4",
    "moon_phases": "cache/manim/moon_phases.mp4",
    # v12: topic-agnostic generic beats — every topic gets motion
    "generic_clock": "cache/manim/generic_ClockSeven.mp4",
    "generic_waves": "cache/manim/generic_BrainWaves.mp4",
    "generic_bars": "cache/manim/generic_GrowingBars.mp4",
    "generic_pulse": "cache/manim/generic_PulseMotif.mp4",
    "generic_figure": "cache/manim/generic_FigureBeat.mp4",
    "generic_cycle": "cache/manim/generic_CycleLoop.mp4",
}

# Topic -> Manim scenes (intent-mapped).  General registry: adding a new
# topic means adding its scenes here; the planner logic stays topic-free.
TOPIC_MANIM = {
    "voyager": {"scale": "voyager_scale", "timeline": "voyager_timeline",
                 "journey": "voyager_trajectory"},
    "sun":     {"scale": "sun_scale", "explanation": "sun_layers",
                 "structure": "sun_layers"},
    "pulsar":  {"explanation": "pulsar_lighthouse", "journey": "pulsar_lighthouse",
                 "scale": "pulsar_density", "emotion": "pulsar_lighthouse"},
    "black_holes": {"explanation": "black_hole_lensing", "structure": "black_hole_lensing",
                 "emotion": "black_hole_lensing", "journey": "black_hole_lensing",
                 "scale": "black_hole_lensing"},
    "moon":    {"explanation": "moon_phases", "journey": "moon_phases",
                 "emotion": "moon_phases", "scale": "moon_phases",
                 "structure": "moon_phases"},
    # v12: generic fallback — topic-agnostic beats mapped by intent.  A
    # fresh topic with no bespoke scenes still gets real animation.
    "__generic__": {
        "hook": "generic_pulse", "emotion": "generic_waves",
        "explanation": "generic_bars", "structure": "generic_cycle",
        "scale": "generic_clock", "journey": "generic_figure",
        "timeline": "generic_clock", "climax": "generic_pulse",
        "context": "generic_figure", "conclusion": "generic_cycle",
        "default": "generic_bars",
    },
}

# Which topic a given text belongs to (keyword hints, general-purpose).
# NOTE: hints must be DISJOINT and avoid physics-unit false positives:
# - "star" is NOT a sun hint (pulsar narration says "this star")
# - "solar" alone is NOT a sun hint ("solar masses" is a unit used for
#   neutron stars) — only compound solar terms trigger the sun topic.
_TOPIC_HINTS = {
    "voyager": ("voyager", "spacecraft", "golden record", "pale blue dot",
                 "jupiter", "saturn", "heliopause"),
    "sun":     ("solar wind", "solar flare", "solar cycle", "solar corona",
                 "solar surface", "sunlight", "photosphere", "chromosphere",
                 "the sun fuses", "the sun's", "sun's core", "sun's surface",
                 "our star"),
    "pulsar":  ("pulsar", "neutron star", "lighthouse", "spins", "rotating",
                 "beam", "dense", "teaspoon", "magnetar", "supernova remnant"),
    "black_holes": ("black hole", "event horizon", "singularity", "accretion",
                 "spacetime", "lensing", "photon ring", "gravitational"),
    "moon":    ("the moon", "lunar", "moon's", "apollo", "craters",
                 "maria", "regolith", "tidal locking", "moon phases",
                 "earth's companion"),
}


def detect_topic(scene_text: str) -> str:
    """Return the registered topic key for *scene_text*, or ""."""
    t = (scene_text or "").lower()
    for topic, hints in _TOPIC_HINTS.items():
        if any(h in t for h in hints):
            return topic
    return ""


def manim_scene_for(scene_text: str, intent: str = "default") -> str:
    """Pick a Manim scene by topic + intent (general, registry-driven).

    v12: falls back to the topic-agnostic generic beat mapped by intent,
    so a fresh topic with no bespoke scenes still gets real animation
    (was: returned "" for any unregistered topic -> manim: 0 in stats).
    """
    topic = detect_topic(scene_text)
    if topic and topic in TOPIC_MANIM:
        mapping = TOPIC_MANIM[topic]
        # intent-priority: scale/explanation beats are the natural Manim beats
        for key in ("scale", "explanation", "timeline", "journey", "structure"):
            if intent == key and key in mapping:
                return MANIM_SCENES[mapping[key]]
            # also trigger on scale words even when intent is generic
            if (key == "scale" and key in mapping and
                    any(k in scene_text.lower() for k in
                        ("how big", "how far", "million", "billion", "fit inside", "size"))):
                return MANIM_SCENES[mapping[key]]
    # v12: generic fallback (any topic, any intent)
    generic = TOPIC_MANIM.get("__generic__", {})
    key = intent if intent in generic else "default"
    clip = generic.get(key, generic.get("default"))
    return MANIM_SCENES.get(clip, "") if clip else ""


def manim_script_for(clip_path: str) -> str:
    """Resolve the .py source for a rendered Manim clip.

    Rendered clips live in cache/manim/<name>.mp4 while their source
    scripts live in src/manim/scenes/<name>.py (or beside the clip when
    generated ad-hoc).  Missing source is NOT a hard failure — the clip
    already exists and is registered; kinetic validation is a bonus."""
    cands = [
        clip_path.replace(".mp4", ".py"),
        os.path.join("src", "manim", "scenes",
                     os.path.basename(clip_path).replace(".mp4", ".py")),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return ""


# ── Flat-vector animated beats (Kurzgesagt-style) ───────────────────────

# v12: flat-vector ANIMATED beats (Blender, Workbench FLAT) — the
# Kurzgesagt-style vector motion the channel direction calls for.  These
# are topic-agnostic; any scene can pull one, so the video never ships
# as pure Ken-Burns stills (sleep episode shipped manim:0 + zero vector
# animation — the two biggest v11 failures).
VECTOR_BEATS = {
    "hook": "cache/vector/vector_pulse.mp4",
    "emotion": "cache/vector/vector_waves.mp4",
    "explanation": "cache/vector/vector_bars.mp4",
    "structure": "cache/vector/vector_clock.mp4",
    "scale": "cache/vector/vector_orbit.mp4",
    "journey": "cache/vector/vector_figure_walk.mp4",
    "timeline": "cache/vector/vector_clock.mp4",
    "climax": "cache/vector/vector_pulse.mp4",
    "context": "cache/vector/vector_figure_walk.mp4",
    "conclusion": "cache/vector/vector_orbit.mp4",
    "default": "cache/vector/vector_pulse.mp4",
}

# v13: template name for each intent (single source — mirrors the
# cache paths above; the renderer and resolver both key off these).
VECTOR_TEMPLATES = {
    "hook": "pulse", "emotion": "waves", "explanation": "bars",
    "structure": "clock", "scale": "orbit", "journey": "figure_walk",
    "timeline": "clock", "climax": "pulse", "context": "figure_walk",
    "conclusion": "orbit", "default": "pulse",
}


def render_vector_beats(vector_dir: str, label: str = "",
                        intents: list | None = None,
                        max_workers: int = 3) -> dict:
    """Render flat-vector beats ALGORITHMICALLY for THIS video.

    v13: the beats are no longer pre-baked once into cache/vector and
    reused forever — every video renders its own set into ``vector_dir``
    (e.g. results/<slug>/vector/) so the motion is fresh per episode and
    carries the episode label.  Renders are parallel (one Blender worker
    per template) and validated with ffprobe before use.

    Returns {template: clip_path} for the templates that rendered OK.
    """
    from tools.vector_clips import render as _render, DURATION as _DUR
    os.makedirs(vector_dir, exist_ok=True)
    needed = set()
    for it in (intents or list(VECTOR_TEMPLATES)):
        t = VECTOR_TEMPLATES.get(it, VECTOR_TEMPLATES["default"])
        needed.add(t)
    needed = sorted(needed)

    def _one(template: str) -> str:
        out = os.path.join(vector_dir, f"vector_{template}.mp4")
        try:
            _render(template, out, duration=_DUR.get(template),
                    label=label)
            return out
        except Exception as e:  # noqa: BLE001
            print(f"  [vector] render failed {template}: {str(e)[:120]}")
            return ""

    from concurrent.futures import ThreadPoolExecutor, as_completed
    made = {}
    t0 = time.monotonic()
    print(f"  [vector] rendering {len(needed)} beats "
          f"(algo, per-video, label={label or 'none'!r}) ...", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(needed)))) as ex:
        futs = {ex.submit(_one, t): t for t in needed}
        for fut in as_completed(futs):
            t = futs[fut]
            out = fut.result()
            if out:
                made[t] = out
    print(f"  [vector] {len(made)}/{len(needed)} beats ready "
          f"({round(time.monotonic()-t0,1)}s)")
    return made


def vector_beat_for(intent: str = "default", vector_dir: str = "") -> str:
    """Return the flat-vector animated beat for an intent, or "".

    v13: ``vector_dir`` (per-video render output) wins when given;
    falls back to the shared cache/vector path for older flows.
    Validates the clip with ffprobe — a partial/corrupt render (e.g.
    failed ffmpeg composite) must never enter the timeline."""
    tpl = VECTOR_TEMPLATES.get(intent, VECTOR_TEMPLATES["default"])
    cands = []
    if vector_dir:
        cands.append(os.path.join(vector_dir, f"vector_{tpl}.mp4"))
    cands.append(VECTOR_BEATS.get(intent, VECTOR_BEATS.get("default", "")))
    clip = next((c for c in cands if c and os.path.exists(c)), "")
    if os.path.getsize(clip) < 200_000:
        return ""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", clip],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0 or not r.stdout.strip():
            print(f"  [vector] rejecting corrupt clip {os.path.basename(clip)}")
            return ""
        dur = float(r.stdout.strip())
        if dur < 1.0:
            return ""
    except Exception:
        return ""
    return clip


# ── Locked art direction ("Jade") ───────────────────────────────────────

# STUDIO DECISION (2026-08-03): consistency over rotation.  ckdigital
# asked for ONE fixed style + ONE color combination used for every
# cartoon/stylized shot, so the video reads as a single art direction
# instead of a mix of unrelated styles.  All non-photoreal AI stills now
# use FIXED_JADE_STYLE (+ its fixed palette) regardless of scene emotion;
# the per-emotion rotation below is kept only as a fallback for scenes
# that carry an explicit visual_style that is NOT in the fixed set.
# 2026-08-05: channel direction — flat-vector Kurzgesagt-style (matches
# style_bible DEFAULT_STYLE_MODIFIER + STYLE_TOKEN="flat-vector").
FIXED_JADE_STYLE = (
    "flat-vector documentary illustration, clean geometric shapes, smooth "
    "curves, bold flat color fills, deep navy background with high-saturation "
    "cyan and orange accents, simple stylized human figures, minimal detail, "
    "no text, no gradients, no photorealism"
)

STYLE_MODIFIERS = {
    "jade": FIXED_JADE_STYLE,
    "ghibli": (
        "Studio Ghibli-inspired hand-drawn animation, painterly backgrounds, "
        "soft warm palette, detailed matte art, no text"),
    "hand_drawn": (
        "hand-drawn cel animation, expressive ink outlines, vibrant colors, "
        "no text"),
    "90s_anime": (
        "1990s anime cel style, detailed background art, film grain, "
        "dramatic lighting, no text"),
    "sepia_cel": (
        "sepia-toned hand-drawn cel animation, vintage documentary look, "
        "aged paper texture, no text"),
    "watercolor": (
        "watercolor illustration, soft washes, delicate detail, no text"),
    "clean_vector": (
        "clean vector infographic illustration, flat modern design, "
        "minimalist, no text"),
    "photorealistic": "photorealistic, cinematic, high detail, no text",
}


def style_prompt_for(scene: dict, fallback: str = "") -> str:
    """Resolve a scene's visual_style into a prompt modifier.

    v8.1 (2026-08-03): consistency override — unless the scene explicitly
    asks for a photorealistic look, return the single fixed Jade style so
    every stylized shot shares one art direction and color palette.
    """
    style = ((scene or {}).get("visual_style") or "").strip().lower()
    if style == "photorealistic":
        return STYLE_MODIFIERS["photorealistic"]
    if style and style in STYLE_MODIFIERS and style in ("jade",):
        return STYLE_MODIFIERS[style]
    # Consistency override: all cartoon shots share the fixed Jade style.
    return FIXED_JADE_STYLE
