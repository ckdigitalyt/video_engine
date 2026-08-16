"""
visual_direction.py — Single source of truth for the channel's VISUAL
DIRECTION (Manim registry, beats, Jade style lock).

v13 consolidation (2026-08-06): the video pipeline (mission_run.py) and the
stills-first pipeline (mission_stills.py) had diverged — mission_run still
carried a Voyager-only Manim gate and no vector beats, while mission_stills
had the v12.2 flat-vector direction.  Both runners now import THIS module so
the algorithm can never drift again:

  * MANIM_SCENES / TOPIC_MANIM / _TOPIC_HINTS / _manim_scene_for()
      — which animated explanation clips exist and which scenes may use them
        (topic registry; generic beats are a last resort).
  * VECTOR_BEATS / _vector_beat_for()
      — Kurzgesagt-style flat-vector animated beats, rendered per-video
        into results/<slug>/vector/ (ENABLED under the cartoon direction).
  * FIXED_JADE_STYLE / STYLE_MODIFIERS / _style_prompt_for()
      — ONE locked art direction + palette for all stylized shots.

Channel direction (2026-08-16, v40/v42, ckdigital): CARTOON ONLY —
hand-drawn 2D cartoon illustration with thick dark outlines, cel shading,
soft gradients, glow, friendly expressive faces + a recurring green-alien
mascot (see style_bible.STYLE_SUFFIX — the single brand string both runners
append to every styled prompt).  Flat-vector beats are enabled again (they
match the cartoon look and guarantee motion on fresh topics); generic Manim
beats remain available only when their clip files exist.
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
    # 2026-08-16: TRUE 3D Gabriel's Horn (surface of revolution) — fixes
    # the #1 review blocker ("flat 2D curve kills the paradox") for
    # paradox / surface-of-revolution / infinite-vs-finite math topics.
    "horn_revolution": "cache/manim/horn_revolution.mp4",
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
    "paradox": {"explanation": "horn_revolution", "structure": "horn_revolution",
                 "emotion": "horn_revolution", "climax": "horn_revolution",
                 "scale": "horn_revolution", "journey": "horn_revolution",
                 "context": "horn_revolution", "timeline": "horn_revolution",
                 "default": "horn_revolution"},
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
                 "photon ring"),
    "moon":    ("the moon", "lunar", "moon's", "apollo", "craters",
                 "maria", "regolith", "tidal locking", "moon phases",
                 "earth's companion"),
    "paradox": ("gabriel's horn", "gabriels horn", "surface of revolution",
                 "infinite surface", "finite volume, infinite", "infinite area",
                 "painter's paradox", "paint the surface", "tapers forever",
                 "taper forever", "rotat.*curve.*1/x", "torricelli"),
}

# Distinctive CORE subject terms per topic.  A scene must contain at least
# one of these (not merely any loose hint) to qualify for that topic's
# Manim clip.  Prevents generic physics wording in an unrelated scene from
# pulling a topic's diagram — Andromeda v5 review finding: scene 7's
# "orchestrated by immense gravitational forces" (a galaxy-MERGER scale
# beat) triggered the black_holes topic and placed the black-hole lensing
# diagram there; scene 8 (actual black-hole merger) is where it belongs.
_TOPIC_CORE = {
    "voyager": ("voyager", "spacecraft", "golden record"),
    "sun":     ("sun", "solar", "photosphere"),
    "pulsar":  ("pulsar", "neutron star", "magnetar"),
    "black_holes": ("black hole", "event horizon", "singularity",
                     "accretion", "photon ring"),
    "moon":    ("moon", "lunar", "apollo", "craters"),
    # 2026-08-16: Gabriel's Horn / surface-of-revolution / infinite-area
    # paradox topics.  Distinctive core terms so an unrelated "surface"
    # word can't falsely pull the horn into a wrong scene.
    "paradox": ("gabriel's horn", "surface of revolution", "infinite surface",
                 "finite volume", "finite volume infinite surface", "horn",
                 "infinite area", "painter's paradox"),
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
    v19l (2026-08-10): a scene must contain a CORE subject term for the
    topic (not just any loose hint) — Andromeda v5 review finding: a
    galaxy-merger-scale beat mentioning "gravitational forces" pulled the
    black-hole lensing diagram into the wrong scene.
    """
    t = (scene_text or "").lower()
    topic = detect_topic(t)
    if topic and topic in TOPIC_MANIM:
        core = _TOPIC_CORE.get(topic, ())
        if core and not any(k in t for k in core):
            topic = ""  # loose hint only ("gravitational", "spacetime") —
            # not actually about this topic's subject; skip its Manim.
    if topic and topic in TOPIC_MANIM:
        mapping = TOPIC_MANIM[topic]
        # v36 fix (2026-08-16): the intent-priority loop only returned a
        # topic's OWN scene for 5 hardcoded intents (scale/explanation/
        # timeline/journey/structure); any other intent (default, emotion,
        # context, climax, hook) fell through to the generic fallback and
        # returned generic_GrowingBars even when the topic registered a
        # scene for it.  That's why the Gabriel's Horn paradox run shipped
        # 4 Ken-Burns stills and ZERO horn clips.  Now a topic's own
        # mapping wins for ANY intent it defines (incl. default), and the
        # scale-word trigger still works.  Generic beats are only a LAST
        # resort for intents the topic genuinely lacks.
        beat = mapping.get(intent) or mapping.get("default")
        if beat:
            return MANIM_SCENES.get(beat, "") or ""
        # scale-word trigger even when intent is generic/unknown
        if "scale" in mapping and any(
            k in scene_text.lower() for k in
            ("how big", "how far", "million", "billion", "fit inside", "size")
        ):
            return MANIM_SCENES.get(mapping["scale"], "") or ""
    # v12 generic fallback (any topic, any intent).  v42: ENABLED again
    # under the cartoon direction — but only fires when the generic clip
    # file actually exists in cache/manim (unregistered topics otherwise
    # get Ken Burns on cartoon AI stills + vector beats).
    if not GENERIC_MANIM_BEATS_ENABLED:
        return ""
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

# 2026-08-10: channel direction REVERSED by ckdigital — realistic images
# only, NO flat-vector illustrations or Kurzgesagt-style vector motion.
# 2026-08-16 (v40/v42): ckdigital RE-REVERSED to the cartoon direction;
# the flat-vector beats are ENABLED again (flags True) — they match the
# locked cartoon look and guarantee motion on fresh topics that have no
# bespoke Manim scene.  Beats are rendered per-video into
# results/<slug>/vector/; generic (topic-agnostic) Manim beats are only
# placed when their clip file actually exists in cache/manim.
FLAT_VECTOR_BEATS_ENABLED = True
GENERIC_MANIM_BEATS_ENABLED = True

# v12: flat-vector ANIMATED beats (Blender, Workbench FLAT) — the
# Kurzgesagt-style vector motion the OLD channel direction called for.
# These are topic-agnostic; any scene can pull one, so the video never
# ships as pure Ken-Burns stills (sleep episode shipped manim:0 + zero
# vector animation — the two biggest v11 failures).
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

    2026-08-10: DISABLED by default (realistic direction, no flat-vector
    beats) — returns {} immediately unless FLAT_VECTOR_BEATS_ENABLED.
    2026-08-16 (v40/v42): ENABLED under the cartoon direction (see the
    flag comment) — per-video Kurzgesagt-style motion for fresh topics.

    Returns {template: clip_path} for the templates that rendered OK.
    """
    if not FLAT_VECTOR_BEATS_ENABLED:
        return {}
    from tools.vector_clips import render as _render, DURATION as _DUR
    os.makedirs(vector_dir, exist_ok=True)
    needed = set()
    for it in (intents or list(VECTOR_TEMPLATES)):
        t = VECTOR_TEMPLATES.get(it, VECTOR_TEMPLATES["default"])
        needed.add(t)
    needed = sorted(needed)

    def _one(template: str) -> str:
        out = os.path.join(vector_dir, f"vector_{template}.mp4")
        # v42: idempotent — a beat already rendered for THIS video (e.g. a
        # resume/fix rerun after a crash) is reused as-is: the placement
        # gate (vector_beat_for: size + ffprobe) validates it and falls
        # back to Ken Burns stills when invalid, and re-rendering here
        # would only reproduce the same result at 2-5 min per template.
        if os.path.exists(out):
            return out
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
    failed ffmpeg composite) must never enter the timeline.

    2026-08-10: DISABLED by default (realistic direction) — returns ""
    unless FLAT_VECTOR_BEATS_ENABLED.
    2026-08-16 (v40/v42): ENABLED under the cartoon direction."""
    if not FLAT_VECTOR_BEATS_ENABLED:
        return ""
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
# 2026-08-05: channel direction — flat-vector Kurzgesagt-style.
# 2026-08-10: ckdigital reversed it — realistic images only.
# 2026-08-16: ckdigital re-reversed — match flat-2D cartoon explainer
# reference (JEE rank video).  Matches style_bible DEFAULT_STYLE_MODIFIER
# + STYLE_TOKEN="cartoon illustration".
# 2026-08-16 (v40): cartoon methodology locked — thick dark outlines,
# cel shading, soft gradients, glow, friendly expressive faces + recurring
# mascot.  Same locked identity as style_bible (channel brand).
FIXED_JADE_STYLE = (
    "hand-drawn 2D cartoon illustration, thick dark outlines, cel shading, "
    "soft gradients, glow, friendly expressive cartoon faces, bold clean "
    "shapes, scientific explainer art, no text, 16:9 composition"
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
