#!/usr/bin/env python3
"""
mission_stills.py — Stills-first documentary runner (images + Manim).

Visual strategy: NASA/Wikimedia/AI stills with Ken Burns motion + Manim
explanation clips as the PRIMARY visual language; stock video only as a
last resort.  Reuses mission_run stages for research / script / script
review / narration / music / Gemini review / improvement / postmortem.

Usage:
    ./venv/bin/python mission_stills.py --topic "Voyager 1" \
        --out results/voyager_stills/voyager_stills.mp4
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
# v23.1: override=True — the OpenClaw runtime injects a placeholder
# DEEPSEEK_API_KEY into the process env; without override the real
# .env key never replaces it and DeepSeek (the cost-chain last resort)
# 401s, killing runs when Gemini/Groq are quota-limited (Venus v2 crash).
load_dotenv(override=True)

import mission_run as M

from src.pipeline.manifest import Manifest, parse_shot_id, hash_text

# v21: motion continuity — every camera move is validated against the
# previous shot so cuts never flip direction jarringly (push_in→pull_out,
# zoom_in→zoom_out).  The grammar existed but was never wired into the
# stills planner (Andromeda v5 review: "transition feels slightly abrupt",
# "breaks visual continuity").
from src.director.motion_grammar import (
    validate_motion_sequence,
    get_safe_motion_fallback,
)

# Moves to try when the proposed move would jar against the previous shot.
# Lateral/static moves are always safe; inward/outward alternation is the
# failure mode we're avoiding.
_SAFE_MOVE_FALLBACKS = ("pan_right", "pan_left", "static", "tilt_up")


def _compatible_camera_move(prev_move: Optional[str], proposed: str) -> str:
    """Return a camera move compatible with the previous shot's move.

    Uses the motion grammar: INWARD→OUTWARD / OUTWARD→INWARD reversals
    are forbidden (they read as a visible jar between clips).  If the
    proposed move is incompatible, tries safe alternatives; never returns
    a move that flips direction against *prev_move*.
    """
    if prev_move is None or prev_move == proposed:
        return proposed
    if validate_motion_sequence(prev_move, proposed):
        return proposed
    for alt in _SAFE_MOVE_FALLBACKS:
        if validate_motion_sequence(prev_move, alt):
            return alt
    return "static"

# v13 consolidation: visual direction (Manim registry, beats, Jade style
# lock) lives in ONE module shared with mission_run
# so the two runners can never drift apart again.
from src.director.visual_direction import (
    MANIM_SCENES,
    TOPIC_MANIM,
    _TOPIC_HINTS,
    detect_topic as _detect_topic,
    manim_scene_for as _manim_scene_for,
    manim_script_for as _manim_script_for,
    VECTOR_BEATS,
    vector_beat_for as _vector_beat_for,
    render_vector_beats as _render_vector_beats,
    FIXED_JADE_STYLE,
    STYLE_MODIFIERS,
    style_prompt_for as _style_prompt_for,
)

# v11 recalibration: shot-hold / dead-air / hook constants live in the
# QA gates module — import them here so build_stills_timeline enforces
# the SAME caps the gates check (single source of truth).
try:
    from src.qa.jade_gates import (
        MAX_SHOT_HOLD_S,
        MAX_DEAD_AIR_S,
        SILENCE_GAP_S,
        HOOK_MIN_SHOTS,
    )
except Exception:  # pragma: no cover — defensive fallback
    MAX_SHOT_HOLD_S = 4.0
    MAX_DEAD_AIR_S = 0.5
    SILENCE_GAP_S = 0.8
    HOOK_MIN_SHOTS = 5


# ═══════════════════════════════════════════════════════════════════════ #
# Still finders (public domain: NASA / Wikimedia) + AI fallback
# ═══════════════════════════════════════════════════════════════════════ #

# Wikimedia titles to skip outright (off-topic / amusement-park assets that
# collide with astronomy entity terms, e.g. "File:Pulsar Walibi Belgium
# overzicht.jpg" is a roller coaster at Walibi Belgium).  Same spirit as
# the verifier's OFF_TOPIC_SIGNALS but applied at fetch time so we never
# even download the wrong subject.
_WIKI_SKIP_TITLE = (
    "roller coaster", "rollercoaster", "amusement", "theme park",
    "walibi", "water park", "fairground", "ferris wheel", "carousel",
    "bumper car", "fun park", "pleasure park", "trampoline",
    "playground", "kiddie", "festival", "concert", "stadium",
)

# Bare entity queries get disambiguated with domain context before hitting
# the search APIs (e.g. "pulsar" -> "pulsar astronomy"); queries that
# already carry context pass through untouched.
_QUERY_CONTEXT_WORDS = (
    "astronomy", "astronomical", "star", "space", "galaxy", "cosmic",
    "universe", "nebula", "solar", "planet", "astrophysics", "deep sky",
)

def _disambiguate_query(query: str) -> str:
    """Add domain context to bare entity queries to avoid homonym hits."""
    q = (query or "").strip()
    if not q:
        return q
    low = q.lower()
    if any(w in low for w in _QUERY_CONTEXT_WORDS):
        return q
    # bare term (1-2 words, no context): append a domain qualifier
    if len(q.split()) <= 2:
        return f"{q} astronomy"
    return q

def _nasa_still(query: str, out_path: str) -> str:
    got, _ = _nasa_still_title(query, out_path)
    return got


def _nasa_still_title(query: str, out_path: str) -> tuple[str, str]:
    """Fetch a NASA still; returns (path, title)."""
    import requests
    headers = {"User-Agent": "JadeStudio/1.0 (documentary pipeline)"}
    try:
        r = requests.get("https://images-api.nasa.gov/search",
                         params={"q": query, "media_type": "image", "page_size": 4},
                         headers=headers, timeout=25)
        if r.status_code != 200:
            return "", ""
        items = r.json().get("collection", {}).get("items", [])
    except Exception:
        return "", ""
    for it in items:
        title = (it.get("data") or [{}])[0].get("title", "")
        try:
            col = requests.get(it.get("href"), headers=headers, timeout=20)
            if col.status_code != 200:
                continue
            assets = col.json()  # plain list of asset URLs
            picks = [a for a in assets if "~orig" in a] or [a for a in assets if a.endswith((".jpg", ".jpeg", ".png"))]
            if not picks:
                continue
            url = picks[0]
            img = requests.get(url, headers=headers, timeout=40)
            if img.status_code == 200 and len(img.content) > 20000:
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(img.content)
                print(f"  [NASA] {query!r} → {os.path.basename(out_path)} ({len(img.content)//1024} KB) | {title[:60]}")
                return out_path, title
        except Exception:
            continue
    return "", ""


def _wikimedia_still(query: str, out_path: str) -> str:
    got, _ = _wikimedia_still_title(query, out_path)
    return got


def _wikimedia_still_title(query: str, out_path: str) -> tuple[str, str]:
    """Fetch a Wikimedia still; returns (path, title)."""
    import requests
    headers = {"User-Agent": "JadeStudio/1.0 (documentary pipeline; contact: studio@localhost)"}
    search = _disambiguate_query(query)
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "generator": "search",
            "gsrsearch": f"{search} filetype:bitmap", "gsrnamespace": 6,
            "gsrlimit": 12, "prop": "imageinfo", "iiprop": "url|size|extmetadata",
            "iiurlwidth": 1920, "format": "json",
        }, headers=headers, timeout=25)
        if r.status_code != 200:
            print(f"  [Wiki] !! HTTP {r.status_code} for {query!r}")
            return "", ""
        data = r.json()
    except Exception as e:
        print(f"  [Wiki] !! API error for {query!r}: {str(e)[:80]}")
        return "", ""
    pages = data.get("query", {}).get("pages", {})
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        title = p.get("title", "") or ""
        # Off-topic guard at fetch time: skip amusement/entertainment assets
        # whose titles collide with astronomy entity terms.
        tlow = title.lower()
        if any(sig in tlow for sig in _WIKI_SKIP_TITLE):
            print(f"  [Wiki] skip off-topic {title[:70]!r} (amusement/entertainment signal)")
            continue
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        if not url or ii.get("width", 0) < 800:
            continue
        meta = ii.get("extmetadata", {})
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "").upper()
        if lic and not any(k in lic for k in ("CC", "PUBLIC DOMAIN", "PD")):
            continue
        try:
            img = requests.get(url, headers=headers, timeout=40)
            if img.status_code == 200 and len(img.content) > 20000:
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(img.content)
                print(f"  [Wiki] {query!r} → {os.path.basename(out_path)} ({len(img.content)//1024} KB) | {title[:60]} | {lic[:30]}")
                return out_path, title
        except Exception:
            continue
    return "", ""


# v25 (Gemini/DeepSeek review CRITICAL — 'AI-generated female faces',
# 'man with a microchip'): subject guards for AI still prompts.  Generic
# prompts let the generator invent people/faces for spacecraft scenes;
# append a hard no-people/no-text guard unless the scene is explicitly
# about humans (astronaut, people, woman, man, crew, human).
_PEOPLE_RE = re.compile(
    r"\b(astronaut|people|person|woman|man|crew|human|face|portrait)\b",
    re.IGNORECASE)


def _guarded_ai_prompt(base: str, scene_text: str, style_mod: str = "") -> str:
    """v25: append a subject guard to an AI still prompt.

    Planetary/spacecraft documentary stills must not contain people or
    text (both reviewers flagged AI-generated faces in the DAVINCI+/EnVision
    scene and a man-with-microchip stock photo in the Venera scene).  The
    guard is skipped only when the narration itself is about humans.
    """
    base = (base or "").strip()
    if not base:
        return base
    if _PEOPLE_RE.search(scene_text or ""):
        return base + ((". " + style_mod) if style_mod else "")
    guard = (", photorealistic documentary still, no people, no human faces, "
             "no text, no watermarks, no logos")
    return base + guard + ((". " + style_mod) if style_mod else "")


def _ai_still(prompt: str, out_path: str) -> str:
    from src.providers.image_gen import NvidiaNimProvider, PollinationsProvider
    # v25 (Gemini/DeepSeek review CRITICAL — 'AI-generated female faces',
    # 'man with a microchip'): subject guards for documentary stills.
    # Generic prompts let the generator invent people; keep people OUT of
    # planetary/spacecraft scenes unless the narration is explicitly about
    # humans.
    prompt = _guarded_ai_prompt(prompt, prompt, "").strip() or prompt
    for prov in (NvidiaNimProvider(), PollinationsProvider()):
        try:
            prov.generate(prompt, out_path, width=2560, height=1440)
            print(f"  [AI] {prov.name}: {os.path.basename(out_path)} ({os.path.getsize(out_path)//1024} KB)")
            return out_path
        except Exception as e:
            print(f"  [AI] !! {prov.name} failed: {str(e)[:80]}")
    return ""


# ═══════════════════════════════════════════════════════════════════════ #
# Stills-first visual planner
# ═══════════════════════════════════════════════════════════════════════ #

# Pinned stills: real NASA assets that must NOT be overwritten by the
# fetch planner (human-approved swaps from refine_stills).  Keyed by
# the local still path; value is a label for logging.
# Pinned stills per topic: real NASA assets that must NOT be overwritten
# by the fetch planner (human-approved swaps from refine_stills).  Keyed by
# topic slug, then by the topic-scoped still path.
PINNED_STILLS_BY_TOPIC = {
    "voyager_1_the_farthest_human_made_object": {
        "scene0_0.jpg": "PIA14111 Model of Voyager",
        "scene0_1.jpg": "PIA22915 Voyager Spacecraft Instruments",
        "scene1_0.jpg": "PIA17464 Voyager 1 Launch 1977",
        "scene3_0.jpg": "PIA23645 Pale Blue Dot Revisited",
        "scene3_1.jpg": "PIA00452 Solar System Portrait/Pale Blue Dot",
        "scene4_0.jpg": "PIA16362 Preparing the Golden Record",
    },
}

AI_PROMPTS = {
    "spacecraft": ("Photorealistic documentary image of the Voyager 1 spacecraft, "
                   "large dish antenna, golden record attached, deep interstellar "
                   "space, cinematic NASA style"),
    "golden_record": ("Close-up of the Voyager Golden Record, gold-plated copper "
                      "phonograph record with cover, floating in space, cinematic"),
    "interstellar": ("Voyager spacecraft tiny against a vast starfield, pale blue "
                     "dot Earth in the distance, cinematic, photorealistic"),
    "launch": ("Voyager spacecraft atop a Titan IIIE-Centaur rocket on the "
               "launch pad at night, floodlights, 1970s archival documentary "
               "style, historical NASA photograph"),
    "jupiter": ("The planet Jupiter with the Great Red Spot as seen from deep "
                "space, photorealistic, documentary style"),
    "saturn": ("The planet Saturn with rings as seen from deep space, "
               "photorealistic, documentary style"),
}


def _auto_crop_borders(image_path: str, out_path: str) -> str:
    """Auto-crop empty/jagged black border bands from extreme-aspect mosaics.

    DeepSeek pro 88 review (CRITICAL): the Andromeda Hubble M31 mosaic
    (wikimedia 42208x9870) showed jagged black edges when the Ken Burns pan
    moved into empty border territory.  Wide mosaics/panoramas often carry
    large near-black border bands; crop to the content bounding box so the
    pan never reveals them.

    Returns the (possibly new) cropped file path, or "" when the asset is
    mostly empty border (reject), or the ORIGINAL path unchanged when no
    meaningful border exists (fail-open on any error).
    """
    try:
        from PIL import Image
        import numpy as np
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w <= 0 or h <= 0:
                return ""
            aspect = w / h
            # Only extreme-aspect assets (mosaics/panoramas) need this;
            # normal near-16:9 stills are fine.
            if 0.4 <= aspect <= 2.5:
                return image_path
            # Downscale for speed on huge mosaics (42208x9870).
            scale = min(1.0, 2000.0 / max(w, h))
            small = im.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS
            )
            arr = np.asarray(small.convert("L"), dtype=np.float32)
            mask = arr > 10  # content = brighter than ~4% of full scale
            rows = mask.any(axis=1)
            cols = mask.any(axis=0)
            if not rows.any() or not cols.any():
                return ""  # fully black — reject
            r0, r1 = int(np.argmax(rows)), len(rows) - int(np.argmax(rows[::-1]))
            c0, c1 = int(np.argmax(cols)), len(cols) - int(np.argmax(cols[::-1]))
            y0, y1 = int(r0 / scale), int(r1 / scale)
            x0, x1 = int(c0 / scale), int(c1 / scale)
            content_area = (x1 - x0) * (y1 - y0)
            if content_area < 0.35 * w * h:
                return ""  # content is a tiny sliver — reject
            margin_w = 0.015 * w
            margin_h = 0.015 * h
            if (x0 <= margin_w and x1 >= w - margin_w
                    and y0 <= margin_h and y1 >= h - margin_h):
                return image_path  # no real border — keep as-is
            box = (x0, y0, x1, y1)
            im.crop(box).save(out_path, quality=95)
            print(f"  [border] auto-cropped {os.path.basename(image_path)} "
                  f"{w}x{h} -> {x1 - x0}x{y1 - y0}")
            return out_path
    except Exception as e:
        print(f"  [border] !! {os.path.basename(image_path)}: {str(e)[:80]}")
        return image_path  # fail open — keep original


def _kenburns(image_path: str, out_path: str, duration: float = 6.0,
              zoom_in: bool = True, camera: Optional[dict] = None) -> str:
    """Ken Burns motion with LINEAR zoom across the full shot duration.

    v2 fix (from motion review): the old expression ``min(z_end, zoom+0.004)``
    hit max zoom after ~2.3s then went static — perceived as non-smooth.
    New version interpolates zoom linearly over every frame, renders at 2x
    internal resolution, and applies intent-driven camera params when given
    (zoom_start/zoom_end/pan_x/pan_y from CameraDirector).
    """
    frames = int(duration * 30)
    cam = camera or {}
    # v22 (Gemini root-cause review): keep zoom strictly inside [1.03, 1.25].
    # A zoom-out ending at exactly 1.0 makes the crop window touch the source
    # boundary; with pan or sub-pixel float error ffmpeg pads with mirrored/
    # smeared edge pixels (the mirrored_edges blocker).  The 3% safety margin
    # guarantees the crop window never reaches the physical edge.
    _ZMIN, _ZMAX = 1.03, 1.25
    if zoom_in:
        z_start = min(_ZMAX, max(_ZMIN, float(cam.get("zoom_start", _ZMIN))))
        z_end = min(_ZMAX, max(_ZMIN, float(cam.get("zoom_end", 1.22))))
        if z_end <= z_start:
            z_end = min(_ZMAX, z_start + 0.10)
    else:
        z_start = min(_ZMAX, max(_ZMIN, float(cam.get("zoom_start", 1.22))))
        z_end = min(_ZMAX, max(_ZMIN, float(cam.get("zoom_end", _ZMIN))))
        if z_end >= z_start:
            z_end = max(_ZMIN, z_start - 0.10)
    pan_x = float(cam.get("pan_x", 0))
    pan_y = float(cam.get("pan_y", 0))
    # linear zoom: z = z_start + (z_end - z_start) * on/frames
    z_expr = f"{z_start}+({z_end}-{z_start})*on/{frames}"
    # pan: drift by pan_x/pan_y pixels (in 2x space) across the shot.
    # CLAMP to the zoompan-valid window [0, iw-iw/zoom] — without the
    # clamp, pan+zoom can push the crop window past the source edge and
    # ffmpeg pads with mirrored edge pixels -> mirrored_edges/smear
    # artifacts on the final master (Andromeda v4 blocker).
    px = (f"min(max((iw-iw/zoom)/2+({pan_x}*2)*on/{frames},0),"
          f"max(iw-iw/zoom,0))")
    py = (f"min(max((ih-ih/zoom)/2+({pan_y}*2)*on/{frames},0),"
          f"max(ih-ih/zoom,0))")
    vf = (
        f"scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,"
        f"zoompan=z='{z_expr}':x='{px}':y='{py}':"
        f"d={frames}:s=1920x1080:fps=30"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", image_path, "-vf", vf,
         "-c:v", "libx264", "-preset", "fast", "-t", str(duration),
         "-pix_fmt", "yuv420p", "-r", "30", out_path],
        capture_output=True, text=True, timeout=120,
    )
    return out_path if os.path.exists(out_path) else ""


def _still_plan_for(scene_text: str, spec=None, scene=None) -> list:
    """Ordered candidate prompts/queries for still imagery.

    Priority: the script's curated ``search_queries`` (specific, topic-
    correct, e.g. "Jocelyn Bell Burnell 1967") → EntitySpec required
    entities → topic-aware keyword hints.  Bare entity terms are the
    LEAST preferred because they collide with homonyms (a Wikimedia
    search for "pulsar" returns a roller coaster at Walibi Belgium).
    AI fallback stills use the scene's Jade visual style.

    v12.2 (SUPERSEDED): the old flat-vector direction dropped stock photo
    sources.  2026-08-10: ckdigital reversed the channel direction —
    REALISTIC images only.  Real photos (NASA/Wikimedia) are correct for
    the locked photorealistic style and stay in the plan; AI fallback
    stills carry the photorealistic Jade modifier.
    """
    t = scene_text.lower()
    topic = _detect_topic(scene_text)
    plan = []
    style_mod = _style_prompt_for(scene)
    style = ((scene or {}).get("visual_style") or "").strip().lower()
    vector_direction = style and style != "photorealistic"

    # 1) Script-authored search queries (most specific, least ambiguous)
    for q in (scene or {}).get("search_queries", []) or []:
        q = (q or "").strip()
        if q:
            # (2026-08-10 realistic direction: the query is the SUBJECT of
            # a photorealistic AI still, not a stock-photo search.)
            # v25: subject guard keeps people/faces out of AI stills.
            if vector_direction:
                plan += [("ai", _guarded_ai_prompt(q, scene_text, style_mod))]
            else:
                plan += [("nasa", q), ("wiki", q)]

    # 2) EntitySpec-driven: search NASA/Wikimedia for each required entity
    if spec is not None and spec.required_entities:
        for ent in spec.required_entities[:2]:
            if vector_direction:
                plan += [("ai", _guarded_ai_prompt(ent, scene_text, style_mod))]
            else:
                plan += [("nasa", ent), ("wiki", ent)]
        obj = spec.visual_objective or f"{topic} documentary scene"
        # Stylized "Jade" shot FIRST when the scene requests a non-photoreal
        # art direction — otherwise NASA/Wikimedia real photos fill every
        # slot and the stylization never renders (reviewer: "no cartoon /
        # animation / hand-drawn images in the video").
        if vector_direction:
            plan.insert(0, ("ai", _guarded_ai_prompt(obj, scene_text, style_mod)))
        else:
            plan.append(("ai", _guarded_ai_prompt(obj, scene_text, style_mod)))
    else:
        # topic-aware keyword fallback (still general, not per-topic lists)
        if vector_direction:
            plan += [("ai", _guarded_ai_prompt(f"Scene of {topic}", scene_text, style_mod))]
        else:
            plan += [("nasa", topic), ("wiki", topic),
                     ("ai", _guarded_ai_prompt(f"Scene of {topic}", scene_text, style_mod))]

    # dedupe keeping order
    seen, out = set(), []
    for p in plan:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def stage_stills_visuals(scenes_data: list[dict], out_dir: str,
                         gates=None, specs: Optional[dict] = None,
                         topic_slug: str = "",
                         style_bible=None,
                         fresh_scenes: Optional[set] = None) -> dict:
    """Build per-scene shot lists: Manim clips + Ken Burns stills.

    When *gates* is provided, every candidate still is verified against
    its scene's EntitySpec (multi-signal + vision fallback) before it may
    enter the timeline, and camera moves come from the intent-driven
    CameraDirector instead of alternating zoom_in flags.

    Stills are cached topic-scoped (``cache/stills/<topic_slug>/``) so a
    fresh topic never reuses another topic's pinned assets.

    v9 (Jade spec §2/§3): *style_bible* records which locked style token
    each placed AI still was generated with (style-drift QA), and Manim
    clips are kinetic-validated before entering the timeline.

    Returns {scene_id: [{"file": clip, "duration": s}, ...]} and stats.
    """
    print("\n[5-9/16] STILLS-FIRST VISUAL PLANNING (NASA/Wikimedia/AI + Manim)", flush=True)
    t0 = time.time()
    os.makedirs(os.path.join(out_dir, "shots"), exist_ok=True)
    still_root = os.path.join("cache", "stills", topic_slug or "default")
    os.makedirs(still_root, exist_ok=True)
    # v13 fix: per-video vector beats must render into THIS run's vector
    # dir before any scene requests one (mission_run does this; the stills
    # runner referenced ``vector_dir`` without ever defining it → NameError
    # on the first non-Manim scene).
    vector_dir = os.path.join(out_dir, "vector")
    os.makedirs(vector_dir, exist_ok=True)
    _vi_intents = []
    for _vi, _scene in enumerate(scenes_data):
        _vs = (specs or {}).get(_vi)
        _vi_intents.append(getattr(_vs, "scene_intent", "default") or "default")
    _render_vector_beats(vector_dir, label=topic_slug or "stills",
                         intents=_vi_intents)
    pinned = PINNED_STILLS_BY_TOPIC.get(topic_slug, {})

    plan = {}
    stats = {"manim": 0, "nasa": 0, "wikimedia": 0, "ai": 0, "video_fallback": 0,
             "rejected": 0, "vision_checked": 0, "deduped": 0}
    manim_used = set()
    # v21: global camera-move continuity — jarring flips (push_in→pull_out)
    # are forbidden across ALL shots, not just within a scene.
    last_camera_move: Optional[str] = None
    # v12.2: stills REJECTED by the asset gate this run must never be
    # re-admitted via the [CACHE] branch — the gate `continue`s but leaves
    # the file on disk, and the cache-reuse check only tests existence/size,
    # so a rejected photo (e.g. a motorcycle or ancient ruins) came right
    # back into the timeline on the next plan iteration.
    rejected_this_run: set[str] = set()
    # Content-based dedup: dHash of every placed still (Priority 6 — no
    # consecutive near-identical assets, including same-content files with
    # different names).
    placed_hashes: list[str] = []

    def _is_dup(jpg_path: str) -> bool:
        try:
            from src.qa.deterministic_qa import dhash, hamming
            from PIL import Image
            with Image.open(jpg_path) as im:
                h = dhash(im)
            return any(hamming(h, ph) < 6 for ph in placed_hashes)
        except Exception:
            return False

    for i, scene in enumerate(scenes_data):
        text = scene.get("narration", "")
        spec = (specs or {}).get(i)
        intent = spec.scene_intent if spec else "default"
        shots = []
        # 1) Manim explanation clip if scene calls for it (v9 kinetic gate)
        manim = _manim_scene_for(text, intent)
        if manim and os.path.exists(manim) and manim not in manim_used:
            from src.manim.validate import validate_manim_script
            script = _manim_script_for(manim)
            mv = validate_manim_script(script) if script else None
            if mv is None or (mv.valid and mv.kinetic):
                manim_used.add(manim)
                shots.append({"file": manim, "duration": min(10.0, M._probe_duration(manim)),
                              "kind": "manim"})
                stats["manim"] += 1
            else:
                stats["rejected"] += 1
                print(f"  [manim-gate] rejected {os.path.basename(manim)} "
                      f"({(mv.errors or ['not kinetic'])[:1]})")
        # 1b) v13: ANIMATED beat (Kurzgesagt-style motion) — DISABLED under
        #     the 2026-08-10 realistic direction (flat-vector beats off);
        #     scenes use Ken Burns on photorealistic stills + topic manim.
        if not shots or shots[0].get("kind") != "manim":
            vbeat = _vector_beat_for(intent, vector_dir=vector_dir)
            if vbeat and vbeat not in manim_used:
                manim_used.add(vbeat)
                shots.insert(0, {"file": vbeat,
                                 "duration": min(8.0, M._probe_duration(vbeat)),
                                 "kind": "vector"})
                stats["manim"] += 1  # counts as animated coverage
                print(f"  [vector] {os.path.basename(vbeat)} (intent={intent})")
        # 2) Stills with Ken Burns (2 per scene typically)
        still_count = 0
        for kind, query in _still_plan_for(text, spec, scene):
            if still_count >= 2:
                break
            fname = f"scene{i}_{still_count}.jpg"
            out = os.path.join(still_root, fname)
            got, src, title = "", "", ""
            # v9.1: reuse topic-scoped cached stills from an interrupted run
            # (same safety bar as pinned: existing file > 15 KB).  Avoids
            # re-downloading every still after a crash/rerun.
            if (os.path.exists(out) and os.path.getsize(out) > 15000
                    and fname not in rejected_this_run
                    and (fresh_scenes is None or i not in fresh_scenes)):
                got, src, title = out, "cached", "cached still"
                print(f"  [CACHE] {fname} reused from topic cache")
            elif fname in pinned and os.path.exists(out) and os.path.getsize(out) > 15000:
                got, src = out, "nasa_pinned"
                title = pinned[fname]
                print(f"  [PIN] {fname} kept ({pinned[fname]})")
            elif kind == "nasa":
                got, title = _nasa_still_title(query, out)
                src = "nasa"
            elif kind == "wiki":
                got, title = _wikimedia_still_title(query, out)
                src = "wikimedia"
            else:
                got = _ai_still(query, out)
                src = "ai"
                # v9: record locked style token for drift QA (spec §2)
                if got and style_bible is not None:
                    style_bible.placed_style_tokens[os.path.basename(got)] = query
            if not got:
                continue
            # ── BORDER GATE (v19n, DeepSeek 88 CRITICAL) ─────────────
            # Wide mosaics/panoramas (e.g. the 42208x9870 Andromeda Hubble
            # M31 mosaic) carry jagged empty borders that the Ken Burns pan
            # exposes as black edges.  Auto-crop to the content bbox before
            # dedup/gate/Ken Burns; reject freshly-fetched assets that are
            # mostly empty border.  Generated/cached/pinned assets fail open
            # (keep original) — they were already accepted upstream.
            if os.path.exists(got):
                crop_out = os.path.join(
                    still_root, fname.replace(".jpg", "_crop.jpg"))
                cropped = _auto_crop_borders(got, crop_out)
                if not cropped and src not in ("ai", "cached") and fname not in pinned:
                    stats["rejected"] += 1
                    rejected_this_run.add(fname)
                    print(f"  [border] rejected {fname} (mostly empty border)")
                    continue
                elif cropped and cropped != got:
                    got = cropped
                    print(f"  [border] using cropped {os.path.basename(got)}")
            # Content-based dedup: skip near-identical stills already placed
            if os.path.exists(got) and _is_dup(got):
                stats["deduped"] += 1
                print(f"  [dedup] skipped {fname} (perceptually identical to a placed still)")
                continue
            # ── ASSET-GATE: verify against scene EntitySpec ────────────
            if gates is not None and spec is not None:
                # AI stills are generated FROM this scene's visual objective
                # (the prompt is spec.visual_objective), so they are the
                # safest assets by construction — pre-verified like pinned
                # human-approved images.  Without this, the metadata gate
                # rejects every AI still when vision is down (score ~0.33).
                # Cached stills were already verified against this topic's
                # EntitySpecs on their first fetch — treat as pre-verified
                # too (otherwise a rerun re-rejects them with a placeholder
                # title and the scene stalls).  NOTE: check ``src`` not
                # ``kind`` — the cache-reuse branch sets src="cached" while
                # kind still reflects the plan tuple ("nasa"/"wiki"/"ai").
                pre_verified = fname in pinned or src in ("ai", "cached")
                ver = gates.verify_asset(
                    spec, asset_path=got, title=title, filename=fname,
                    provider=src, query_used=query, pre_verified=pre_verified,
                )
                stats["vision_checked"] += int(bool(ver.get("vision_check")))
                if not ver.get("passed"):
                    stats["rejected"] += 1
                    rejected_this_run.add(fname)
                    print(f"  [gate] rejected {fname} "
                          f"({ver.get('reasons', ['?'])[:1]})")
                    continue
            # ── CAMERA: intent-driven motion (diversity-aware) ─────────
            clip = os.path.join(out_dir, "shots", fname.replace(".jpg", ".mp4"))
            # v10 (rec 5) + 2026 micro-beat recalibration: the HOOK window (scene 0)
            # cuts fastest — 3.0-3.5s holds, maximum visual turnover; later
            # scenes stay in the micro-beat band (3.5-4.0s) so no shot ever
            # approaches the 4s hold cap (mobile-first retention).
            if i == 0:
                dur = 3.5 if len(shots) < 3 else 3.0
            else:
                dur = 4.0 if len(shots) < 3 else 3.5
            cam = gates.camera_decision(intent) if gates is not None else {
                "move": "push_in" if still_count % 2 == 0 else "pull_out",
                "params": {},
            }
            # v21: never cut INTO a direction flip (jarred effect).  If the
            # intent-driven move would reverse the previous shot's direction,
            # substitute a safe compatible move instead.
            move = cam.get("move", "push_in")
            safe_move = _compatible_camera_move(last_camera_move, move)
            if safe_move != move:
                from src.cinematic.camera_language import CAMERA_MOVES
                _m = CAMERA_MOVES.get(safe_move)
                cam = {"move": safe_move, "intent": intent,
                       "params": dict(_m) if _m else {"zoom_start": 1.0, "zoom_end": 1.0,
                                                      "pan_x": 0, "pan_y": 0}}
            cam_params = cam.get("params", {}) or {}
            zoom_in = cam_params.get("zoom_end", 1.2) > cam_params.get("zoom_start", 1.0)
            kb = _kenburns(got, clip, duration=dur, zoom_in=zoom_in,
                           camera=cam_params)
            if kb:
                shots.append({"file": clip, "duration": dur, "kind": src,
                              "camera": cam.get("move", "push_in"),
                              "motion_params": cam_params,
                              "verification": ver if (gates is not None and spec is not None) else None,
                              "title": title, "query": query,
                              "asset": got})
                last_camera_move = cam.get("move", "push_in")
                stats[src] = stats.get(src, 0) + 1
                still_count += 1
                # record hash for dedup (content-based, not path-based)
                try:
                    from src.qa.deterministic_qa import dhash
                    from PIL import Image
                    with Image.open(got) as im:
                        placed_hashes.append(dhash(im))
                except Exception:
                    pass

        # ── Coverage guard: long scenes must never hold a single visual ──
        # A scene whose narration runs > 8s needs >= 2 distinct visuals.
        # If the placed shots' TOTAL duration is shorter than the narration
        # estimate (e.g. hook scene: 3x 3.0-3.5s shots vs 15.8s narration),
        # add Ken Burns variant(s) with the OPPOSITE camera move so the
        # timeline never stretches one shot into a long frozen hold
        # (v10 fix: Europa run froze 15s at 45s).
        est = max(4.0, len(text.split()) / 2.6)
        placed_total = sum(sh.get("duration", 0) for sh in shots)
        # Add variants (opposite camera) until the scene is visually
        # covered or we hit 4 shots — prevents one-shot freeze stretches.
        var_i = 0
        while shots and est > placed_total + 1.5 and est > 8.0 and len(shots) < 4:
            # estimate narration duration: ~2.6 words/sec spoken
            last = shots[-1]
            # v23: coverage variants must NOT re-render the same still as the
            # previous shot when the scene already has another distinct still
            # (the "same image again and again" defect — Andromeda v5, Venus
            # v1 both flagged these as perceptual repeats).  Prefer a shot
            # whose asset differs from the last shot's.
            src_img = ""
            _alt = next((sh for sh in shots
                         if sh.get("asset") and sh.get("asset") != last.get("asset")
                         and os.path.exists(sh["asset"])), None)
            if _alt:
                src_img = _alt["asset"]
                print(f"  [coverage] scene{i}: variant uses DIFFERENT still "
                      f"({os.path.basename(src_img)})")
            if not src_img:
                src_img = os.path.join(still_root, os.path.basename(
                    last.get("file", "").replace(".mp4", ".jpg")))
            if last.get("kind") == "manim" and not os.path.exists(src_img):
                # manim-only scene: pull a frame out of the clip
                src_img = os.path.join(out_dir, "shots", f"scene{i}_frame.jpg")
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-ss", "1.5",
                     "-i", last.get("file", ""), "-frames:v", "1", src_img],
                    capture_output=True, text=True, timeout=30)
                src = last.get("kind", "manim")
            if os.path.exists(src_img):
                # v12.2: unique filename PER VARIANT — the old code reused
                # `still_count` which is frozen at 0 for manim scenes, so
                # every variant overwrote scene{i}_variant_0.mp4 and the
                # timeline repeated the same file 3x → repeated_assets gate.
                var_i += 1
                variant = os.path.join(
                    out_dir, "shots", f"scene{i}_variant_cov{var_i}.mp4")
                vcam = cam_params if still_count else {}
                vcam = dict(vcam)
                # invert the camera move for visual novelty
                if vcam.get("zoom_end", 1.2) > vcam.get("zoom_start", 1.0):
                    vcam["zoom_start"], vcam["zoom_end"] = vcam.get("zoom_end", 1.22), vcam.get("zoom_start", 1.0)
                    vmove = "pull_out"
                else:
                    vcam["zoom_start"], vcam["zoom_end"] = vcam.get("zoom_start", 1.0) or 1.0, 1.22
                    vmove = "push_in"
                # v22 (DeepSeek root-cause review): resolve a compatible move
                # BEFORE rendering — the clip must be rendered with the
                # corrected camera params.  v21 computed safe_v AFTER
                # _kenburns(), so the rendered clip kept the jarring move and
                # only the timeline label changed (motion_continuity failed).
                safe_v = _compatible_camera_move(last_camera_move, vmove)
                if safe_v != vmove:
                    from src.cinematic.camera_language import CAMERA_MOVES
                    _m = CAMERA_MOVES.get(safe_v)
                    vcam = dict(_m) if _m else {"zoom_start": 1.03, "zoom_end": 1.03,
                                                "pan_x": 0, "pan_y": 0}
                    vmove = safe_v
                if _kenburns(src_img, variant, duration=4.0,
                             zoom_in=vmove == "push_in", camera=vcam):
                    shots.append({"file": variant, "duration": 4.0, "kind": src,
                                  "camera": vmove, "motion_params": vcam,
                                  "verification": last.get("verification"),
                                  "title": last.get("title", ""),
                                  "query": last.get("query", ""),
                                  "asset": src_img,
                                  "shot_type": "variant"})
                    last_camera_move = vmove
                    placed_total += 4.0
                    print(f"  [coverage] scene{i}: narration ~{est:.0f}s, "
                          f"added {vmove} variant (total {placed_total:.1f}s)")
            else:
                break
        plan[i] = shots

    # Guaranteed fill: any scene with zero stills after gate/dedup gets a
    # topic-generic fallback (never leave a black gap in the timeline).
    for i, scene in enumerate(scenes_data):
        if plan.get(i):
            continue
        text = scene.get("narration", "")
        spec = (specs or {}).get(i)
        intent = spec.scene_intent if spec else "default"
        manim = _manim_scene_for(text, intent)
        if manim and os.path.exists(manim) and manim not in manim_used:
            from src.manim.validate import validate_manim_script
            script = _manim_script_for(manim)
            mv = validate_manim_script(script) if script else None
            if mv is None or (mv.valid and mv.kinetic):
                manim_used.add(manim)
                plan[i] = [{"file": manim,
                            "duration": min(4.0, M._probe_duration(manim)),
                            "kind": "manim"}]
                stats["manim"] += 1
                print(f"  [fill] scene{i} filled with Manim {os.path.basename(manim)}")
                continue
        # v10.1 (rec 7): fill MUST use the scene's own curated queries —
        # _detect_topic() matched "voyager" for a Europa scene (hint:
        # "spacecraft"), placing a wrong-subject Voyager model image.
        # Subject accuracy beats generic fill: a simple correct image is
        # better than a cinematic wrong one.
        fill_queries = (scene or {}).get("search_queries") or []
        fill_q = next((q for q in fill_queries if isinstance(q, str) and q.strip()),
                      None) or (topic_slug.replace("_", " "))
        fname = f"scene{i}_fill.jpg"
        out = os.path.join(still_root, fname)
        got, title = _nasa_still_title(fill_q, out)
        src = "nasa"
        if not got:
            got = _ai_still(
                f"Photorealistic documentary image of {fill_q}, cinematic", out)
            src, title = "ai", ""
        if got and os.path.exists(got):
            clip = os.path.join(out_dir, "shots", fname.replace(".jpg", ".mp4"))
            cam = gates.camera_decision(intent) if gates is not None else {"move": "push_in", "params": {}}
            move = cam.get("move", "push_in")
            safe_move = _compatible_camera_move(last_camera_move, move)
            if safe_move != move:
                from src.cinematic.camera_language import CAMERA_MOVES
                _m = CAMERA_MOVES.get(safe_move)
                cam = {"move": safe_move, "intent": intent,
                       "params": dict(_m) if _m else {"zoom_start": 1.0, "zoom_end": 1.0,
                                                      "pan_x": 0, "pan_y": 0}}
            cam_params = cam.get("params", {}) or {}
            zoom_in = cam_params.get("zoom_end", 1.2) > cam_params.get("zoom_start", 1.0)
            if _kenburns(got, clip, duration=4.0, zoom_in=zoom_in, camera=cam_params):
                fill_shots = [{"file": clip, "duration": 4.0, "kind": src,
                               "camera": cam.get("move", "push_in"),
                               "motion_params": cam_params, "title": title,
                               "query": fill_q, "asset": got}]
                last_camera_move = cam.get("move", "push_in")
                # v10.4 + 2026 recalibration: fill scenes must also satisfy the
                # coverage guard AND the 4s micro-beat hold cap.
                fest = max(4.0, len(text.split()) / 2.6)
                fplaced = 4.0
                fcount = 1
                while fest > fplaced + 1.5 and fest > 8.0 and fcount < 4:
                    vcam = dict(cam_params) if cam_params else {}
                    if vcam.get("zoom_end", 1.2) > vcam.get("zoom_start", 1.0):
                        vcam["zoom_start"], vcam["zoom_end"] = vcam.get("zoom_end", 1.22), vcam.get("zoom_start", 1.0)
                        vmove = "pull_out"
                    else:
                        vcam["zoom_start"], vcam["zoom_end"] = vcam.get("zoom_start", 1.0) or 1.0, 1.22
                        vmove = "push_in"
                    variant = os.path.join(out_dir, "shots", f"scene{i}_variant_{fcount}.mp4")
                    safe_v = _compatible_camera_move(last_camera_move, vmove)
                    if safe_v != vmove:
                        from src.cinematic.camera_language import CAMERA_MOVES
                        _m = CAMERA_MOVES.get(safe_v)
                        vcam = dict(_m) if _m else {"zoom_start": 1.0, "zoom_end": 1.0,
                                                    "pan_x": 0, "pan_y": 0}
                        vmove = safe_v
                    if _kenburns(got, variant, duration=4.0, zoom_in=vmove == "push_in", camera=vcam):
                        fill_shots.append({"file": variant, "duration": 4.0, "kind": src,
                                           "camera": vmove, "motion_params": vcam,
                                           "title": title, "query": fill_q,
                                           "asset": got})
                        last_camera_move = vmove
                        fplaced += 4.0
                        fcount += 1
                    else:
                        break
                plan[i] = fill_shots
                stats[src] = stats.get(src, 0) + 1
                print(f"  [fill] scene{i} filled with {src} still ({fill_q}) "
                      f"({len(fill_shots)} shot(s))")

    print(f"  Shots planned: " + ", ".join(f"scene{i}: {len(v)}" for i, v in plan.items()))
    print(f"  Sources: {stats} ({(time.time()-t0):.1f}s)")
    return plan, stats


# ═══════════════════════════════════════════════════════════════════════ #
# Pacing padding (v10 rec 1/11)
# ═══════════════════════════════════════════════════════════════════════ #

def _pace_pad_scenes(scenes_data: list[dict], audio_dir: str,
                     audio_durations: list[float]) -> list[float]:
    """Insert pauses at sentence boundaries so delivered narration lands
    inside its role's comprehension band (expert rec 1/11: pacing is a
    quality metric; leave space after key facts).

    Chatterbox speaks ~195-205 wpm natively vs the ~150 wpm documentary
    pace the word budget assumes, so scenes come out rushed (Europa run:
    every scene 171-243 wpm).  This deterministically adds distributed
    silence at sentence gaps to bring WPM into band — no re-synthesis.

    v10.3: iterates (pad -> re-measure -> pad) so very rushed scenes
    converge into band instead of being capped short by one pass
    (Europa v12 scene 7: 236 -> 163 wpm, still 3 over the 160 band).
    Single-sentence scenes fall back to clause splits, then one mid-
    scene pause.
    """
    import re as _re
    import numpy as _np
    import soundfile as _sf
    from src.cinematic.pacing_engine import (
        measure_speech_rate, role_for, ROLE_PACING,
    )
    updated = []
    for i, sc in enumerate(scenes_data):
        text = sc.get("narration") or ""
        ap = os.path.join(audio_dir, f"scene_{i}.wav")
        if not os.path.exists(ap):
            continue
        role = role_for(sc.get("intent") or sc.get("scene_intent") or "")
        band = ROLE_PACING[role]
        words = len(text.split())
        if words == 0:
            continue
        # v25 (Gemini/DeepSeek review CRITICAL — 'voice jitter / abrupt
        # stutter'): anchor pauses to the ORIGINAL file.  The old code
        # re-read the already-padded file every pass and recomputed
        # ``idx = n * frac`` on the GROWN length, so pass 2+ drifted past
        # the real sentence ends and dropped 1.3-1.4s of dead air
        # MID-sentence (Venus v3 scene_2: gaps at 4.13s near 'seven' and
        # 12.77s near 'the' — neither is a sentence boundary).
        sents = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sents) < 2:
            sents = [s.strip() for s in _re.split(r"(?<=[,;:])\s+", text) if s.strip()]
        try:
            data0, sr = _sf.read(ap, dtype="float32")
        except Exception as e:  # noqa: BLE001
            print(f"  [pacing] !! read failed scene {i}: {str(e)[:60]}")
            continue
        n0 = len(data0)
        total_words = words or 1
        boundaries = []
        cum = 0
        for s in sents[:-1]:
            cum += len(s.split())
            boundaries.append(min(0.98, cum / total_words))
        if not boundaries:
            boundaries = [0.55]  # single-clause scene: one mid-scene pause
        # Unique, in-bounds anchor positions on the ORIGINAL audio.
        anchor_idx = sorted({int(n0 * f) for f in boundaries})
        anchor_idx = [a for a in anchor_idx if 0 < a < n0]
        if not anchor_idx:
            continue
        inserted = [0] * len(anchor_idx)   # cumulative samples per anchor
        max_gap_n = int(0.7 * sr)          # v12 cap: TOTAL per boundary
        dur = n0 / sr
        for _pass in range(3):  # iterate until in band or no progress
            wpm = measure_speech_rate(text, dur)
            if wpm <= band["max_wpm"] or dur <= 0:
                break
            target_dur = words / (band["target_wpm"] / 60.0)
            pad_s = max(0.0, target_dur - dur)
            pad_s = min(pad_s, dur * 0.45)  # cap per pass: +45% length
            if pad_s < 0.3:
                break
            gap_s = min(pad_s / len(anchor_idx), 0.7)
            gap_n = int(sr * gap_s)
            for b in range(len(anchor_idx)):
                inserted[b] = min(inserted[b] + gap_n, max_gap_n)
            if all(v == 0 for v in inserted):
                break
            # Rebuild from ORIGINAL audio: pads sit at anchored sentence
            # ends, so positions never drift across passes.
            chunks = []
            prev = 0
            for b, idx in enumerate(anchor_idx):
                chunks.append(data0[prev:idx])
                if inserted[b] > 0:
                    # v19g: keep channel count when padding — 1D zeros
                    # would collapse stereo narration back to mono.
                    if data0.ndim > 1:
                        chunks.append(_np.zeros(
                            (inserted[b], data0.shape[1]), dtype="float32"))
                    else:
                        chunks.append(_np.zeros(inserted[b], dtype="float32"))
                prev = idx
            chunks.append(data0[prev:])
            out = _np.concatenate(chunks) if chunks else data0
            dur = len(out) / sr
        if any(inserted):
            try:
                _sf.write(ap, out, sr)
            except Exception as e:  # noqa: BLE001
                print(f"  [pacing] !! write failed scene {i}: {str(e)[:60]}")
                continue
            if i < len(audio_durations):
                audio_durations[i] = dur
        if i < len(audio_durations):
            dur = audio_durations[i]
            wpm = measure_speech_rate(text, dur)
            if wpm > band["max_wpm"]:
                print(f"  [pacing] scene {i} still {wpm:.0f} wpm > {band['max_wpm']:.0f} "
                      f"({role}) after {_pass+1} pass(es)")
            elif _pass > 0 or wpm < 200:
                pass
        # record outcome once
        dur = audio_durations[i] if i < len(audio_durations) else M._probe_duration(ap)
        wpm = measure_speech_rate(text, dur)
        if wpm > 0 and _pass > 0:
            updated.append({"scene": i, "role": role,
                            "wpm_after": round(wpm, 1)})
    if updated:
        print("  [pacing] " + ", ".join(
            f"s{r['scene']}:{r['wpm_after']:.0f}wpm({r['role']})"
            for r in updated))
    return audio_durations


def _smooth_stem_audio(audio_dir: str, scenes_data: list[dict],
                       audio_durations: list[float]) -> list[float]:
    """v25: gentle amplitude smoothing on narration stems.

    Gemini/DeepSeek review (Venus v3): \"voice is jittery and abruptly
    stuttering\" — amplitude jitter (sharp RMS transitions) inside Fish
    TTS stems, flagged at 38.8-54.3s in the mix.  Deterministic fix:
    light 2:1 compressor with fast attack / slow release evens the
    loudness spikes without re-synthesis.  Duration-preserving and
    channel-preserving (runs per-stem via ffmpeg, in place).
    """
    updated = []
    for i in range(len(scenes_data)):
        ap = os.path.join(audio_dir, f"scene_{i}.wav")
        if not os.path.exists(ap):
            continue
        tmp = ap + ".smooth.wav"
        # threshold -30 dBFS (0.0316), 2:1, attack 10ms, release 150ms —
        # evens loudness spikes that read as stutter; limiter as safety.
        filt = ("acompressor=threshold=0.0316:ratio=2:attack=10:release=150:"
                "makeup=1,alimiter=limit=0.95")
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", ap,
             "-af", filt, "-c:a", "pcm_s16le", tmp],
            capture_output=True, text=True, timeout=120)
        if (r.returncode == 0 and os.path.exists(tmp)
                and os.path.getsize(tmp) > 0):
            os.replace(tmp, ap)
            new_dur = M._probe_duration(ap)
            if i < len(audio_durations):
                audio_durations[i] = new_dur
            updated.append(i)
        else:
            print(f"  [smooth] !! ffmpeg failed scene {i}: {r.stderr[:120]}")
            if os.path.exists(tmp):
                os.remove(tmp)
    if updated:
        print(f"  [smooth] amplitude-smoothed scenes: {updated}")
    return audio_durations


def _trim_scene_edges(audio_dir: str, scenes_data: list[dict],
                      audio_durations: list[float],
                      keep_tail_s: float = 0.12) -> list[float]:
    """Trim leading/trailing silence from every scene track (v12).

    Root cause of "voice abruptly stops at points": Chatterbox appends
    0.4-0.5s of trailing silence per scene; concatenated back-to-back
    that reads as dead air / cut-off narration.  Deterministic fix:
    cut silence below -38 dB at both edges, keep a short natural tail
    so sentences don't sound clipped, then re-probe durations.
    """
    import numpy as _np
    import soundfile as _sf
    updated = []
    for i in range(len(scenes_data)):
        ap = os.path.join(audio_dir, f"scene_{i}.wav")
        if not os.path.exists(ap):
            continue
        try:
            data, sr = _sf.read(ap, dtype="float32")
        except Exception as e:  # noqa: BLE001
            print(f"  [trim] !! read failed scene {i}: {str(e)[:60]}")
            continue
        # v19g: PRESERVE channels — the old data.mean(axis=1) downmixed
        # Fish's stereo narration to mono, making it sound thin/flat.
        # Envelope uses max across channels; slicing keeps both channels.
        env = _np.abs(data)
        if env.ndim > 1:
            env = env.max(axis=1)
        if len(data) < sr:  # sub-1s: leave alone
            continue
        threshold = 10 ** (-38 / 20.0)
        nz = _np.nonzero(env > threshold)[0]
        if len(nz) == 0:
            continue
        start, end = int(nz[0]), int(nz[-1])
        # leading silence: cut to first speech, keep 30 ms
        lead_cut = max(0, start - int(0.03 * sr))
        # trailing silence: cut to last speech, keep natural tail
        tail_keep = int(keep_tail_s * sr)
        end_cut = min(len(data), end + tail_keep)
        if lead_cut >= end_cut or (lead_cut == 0 and end_cut == len(data)):
            continue
        trimmed = data[lead_cut:end_cut]
        try:
            _sf.write(ap, trimmed, sr)
        except Exception as e:  # noqa: BLE001
            print(f"  [trim] !! write failed scene {i}: {str(e)[:60]}")
            continue
        new_dur = len(trimmed) / sr
        old_dur = audio_durations[i] if i < len(audio_durations) else None
        if i < len(audio_durations):
            audio_durations[i] = new_dur
        if old_dur is not None and old_dur - new_dur > 0.15:
            updated.append({"scene": i, "cut_s": round(old_dur - new_dur, 2)})
    if updated:
        print("  [trim] " + ", ".join(
            f"s{u['scene']}:-{u['cut_s']}s" for u in updated))
    return audio_durations


# ═══════════════════════════════════════════════════════════════════════ #
# Timeline + render
# ═══════════════════════════════════════════════════════════════════════ #

def _append_coverage_variant(tl: dict, last: dict, scene_end: float,
                              scene_id: int, out_path: str) -> None:
    """Cover narration remainder past MAX_SHOT_HOLD_S with an opposite-
    camera Ken Burns variant built from the same source still (fallback:
    extract a frame from the clip itself).  Keeps the timeline free of
    both black gaps (frozen/static) and over-long holds (shot_hold)."""
    import subprocess as _sp
    out_dir = os.path.dirname(out_path)
    fname = os.path.basename(last.get("file", ""))
    stem = os.path.splitext(fname)[0]
    src_img = os.path.join(out_dir, "stills", stem + ".jpg")
    if not os.path.exists(src_img):
        src_img = os.path.join(out_dir, "shots", stem + ".jpg")
    if not os.path.exists(src_img) and os.path.exists(last.get("file", "")):
        src_img = os.path.join(out_dir, "shots", f"scene{scene_id}_covframe.jpg")
        _sp.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0",
                 "-i", last.get("file", ""), "-frames:v", "1", src_img],
                capture_output=True, text=True, timeout=30)
    # v22: prefer a DIFFERENT still already placed in this scene for the
    # coverage variant, so the viewer never sees the exact same image twice
    # in a row (the "same image again and again" complaint).  Fall back to
    # the previous shot's source only when no other asset exists in the scene.
    alt_src = ""
    for _e in tl.get("video_timeline", []):
        if (_e.get("scene_id") == scene_id and _e.get("asset")
                and os.path.exists(_e["asset"]) and _e.get("asset") != last.get("asset")):
            alt_src = _e["asset"]
            break
    if alt_src:
        src_img = alt_src
        print(f"  [variant] scene{scene_id} coverage uses different still "
              f"({os.path.basename(alt_src)})")
    if not os.path.exists(src_img):
        return  # cannot build a variant; keep capped shot (gate reports it)
    variant = os.path.join(out_dir, "shots", f"scene{scene_id}_covvar.mp4")
    mp = dict(last.get("motion_params") or {})
    if mp.get("zoom_end", 1.2) > mp.get("zoom_start", 1.0):
        mp["zoom_start"], mp["zoom_end"] = mp.get("zoom_end", 1.22), mp.get("zoom_start", 1.0)
        vmove = "pull_out"
    else:
        mp["zoom_start"], mp["zoom_end"] = mp.get("zoom_start", 1.0) or 1.0, 1.22
        vmove = "push_in"
    # v21: coverage variants must not jar against the previous shot's move.
    prev_move = last.get("camera_move") or last.get("camera") or None
    safe_v = _compatible_camera_move(prev_move, vmove)
    if safe_v != vmove:
        from src.cinematic.camera_language import CAMERA_MOVES
        _m = CAMERA_MOVES.get(safe_v)
        mp = dict(_m) if _m else {"zoom_start": 1.0, "zoom_end": 1.0, "pan_x": 0, "pan_y": 0}
        vmove = safe_v
    # Cap EVERY variant chunk at MAX_SHOT_HOLD_S: the narration remainder
    # can exceed the hold limit (e.g. 11s scene → 4s primary + 4.48s
    # remainder), and an uncapped single variant fails the shot_hold gate.
    # Emit multiple capped chunks from the same source still.
    remain = round(scene_end - last["end_time"], 3)
    if remain <= 0.3:
        return
    chunk_i = 0
    cursor = last["end_time"]
    while remain > 0.3:
        dur = min(MAX_SHOT_HOLD_S, remain)
        chunk_i += 1
        vfile = os.path.join(out_dir, "shots",
                             f"scene{scene_id}_covvar{chunk_i}.mp4")
        if not _kenburns(src_img, vfile, duration=dur,
                         zoom_in=mp["zoom_end"] > mp["zoom_start"], camera=mp):
            return  # cannot build; keep capped primary (gate reports it)
        tl["video_timeline"].append({
            "layer": 1, "file": vfile,
            "start_time": round(cursor, 3),
            "end_time": round(cursor + dur, 3),
            "transition": "crossfade", "motion": "none",
            "camera": "ken_burns", "beat_index": 1, "shot_type": "variant",
            "camera_move": vmove,
            "motion_params": mp,
            "asset_source": last.get("asset_source", ""),
            "asset_title": last.get("asset_title", ""),
            "query_used": last.get("query_used", ""),
            "asset": last.get("asset", ""),  # v21: source still path
            "scene_id": scene_id,
            "verification_passed": last.get("verification_passed", True),
            "verification_reasons": last.get("verification_reasons", []),
            "pre_verified": last.get("pre_verified", False),
        })
        cursor = round(cursor + dur, 3)
        remain = round(scene_end - cursor, 3)


def build_stills_timeline(scenes_data: list[dict], shot_plan: dict,
                          audio_durations: list[float], out_path: str) -> str:
    """Build a timeline.json from stills/manim shots + per-scene voice."""
    tl = {"render_settings": {"resolution": [1920, 1080], "fps": 30},
          "audio_timeline": [], "video_timeline": []}
    cursor = 0.0
    for i, scene in enumerate(scenes_data):
        audio_path = os.path.join("cache", "audio", f"scene_{i}.wav")
        adur = audio_durations[i] if i < len(audio_durations) else M._probe_duration(audio_path)
        # audio entry
        tl["audio_timeline"].append({
            "track": "voice", "file": audio_path,
            "start_time": round(cursor, 3), "end_time": round(cursor + adur, 3),
        })
        # video shots covering the scene window
        shots = shot_plan.get(i, [])
        if not shots:
            # emergency: black clip
            black = os.path.join("cache", "video", f"scene{i}_black.mp4")
            if not os.path.exists(black):
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                                f"color=c=black:s=1920x1080:r=30:d={adur:.1f}",
                                "-c:v", "libx264", "-preset", "fast", black],
                               capture_output=True, text=True, timeout=60)
            shots = [{"file": black, "duration": adur, "kind": "fallback"}]
        t = cursor
        for si, shot in enumerate(shots):
            dur = shot["duration"]
            entry = {
                "layer": 1,
                "file": shot["file"],
                "start_time": round(t, 3),
                "end_time": round(t + dur, 3),
                "transition": "crossfade" if si > 0 else "fade",
                "motion": "none",
                "camera": "ken_burns" if shot["kind"] not in ("manim", "vector") else "static",
                "beat_index": si,
                "shot_type": shot.get("shot_type", "primary"),
            }
            # ── Semantic identity (iteration guidance: any frame traceable
            #    from the timeline alone, not just diagnostics) ──
            entry["camera_move"] = shot.get("camera", "static")
            entry["motion_params"] = shot.get("motion_params", {})
            entry["asset_source"] = shot.get("kind", "")
            entry["asset_title"] = shot.get("title", "")
            entry["query_used"] = shot.get("query", "")
            entry["asset"] = shot.get("asset", "")  # v21: source still path
            entry["scene_id"] = i
            ver = shot.get("verification") or {}
            entry["verification_passed"] = bool(ver.get("passed", True))
            entry["verification_reasons"] = ver.get("reasons", [])
            entry["pre_verified"] = bool(ver.get("pre_verified", False))
            tl["video_timeline"].append(entry)
            t += dur
        # Per-scene coverage: cover the full narration window.  Never hold
        # a single shot beyond MAX_SHOT_HOLD_S — cap it and add an
        # opposite-camera Ken Burns variant to cover the remainder
        # (v10.4: v14 stretched scene3_fill to 10.7s > 10s cap).
        scene_end = cursor + adur
        if tl["video_timeline"] and t < scene_end:
            last = tl["video_timeline"][-1]
            max_end = round(last["start_time"] + MAX_SHOT_HOLD_S, 3)
            if scene_end <= max_end:
                last["end_time"] = round(scene_end, 3)
            else:
                last["end_time"] = max_end
                _append_coverage_variant(tl, last, scene_end, i, out_path)
        cursor += adur

    # extend final shot to cover any trailing audio
    total_audio = sum(audio_durations)
    last_video_end = tl["video_timeline"][-1]["end_time"] if tl["video_timeline"] else 0
    if last_video_end < total_audio:
        tl["video_timeline"][-1]["end_time"] = round(total_audio, 3)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(tl, f, indent=2)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Stills-first documentary runner")
    ap.add_argument("--topic", default="Voyager 1: the farthest human-made object")
    ap.add_argument("--out", default=None)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--target-seconds", type=float, default=None,
                    help="Target narration runtime in seconds (scales scenes+words; default 60)")
    ap.add_argument("--reuse", action="store_true",
                    help="Reuse cached script/stills/audio from a previous run (A/B motion re-render)")
    ap.add_argument("--scenes", default="",
                    help="Comma list of scene indices to force-regenerate (e.g. 3,7) — operates through the manifest dependency graph")
    ap.add_argument("--assets", default="",
                    help="Comma list of shot ids to force-regenerate (e.g. s03_sh01,s06_sh02) — asset-level repair")
    args = ap.parse_args()

    if args.target_seconds:
        M.set_target_duration(args.target_seconds)

    topic = args.topic
    slug = "".join(c if c.isalnum() else "_" for c in topic.lower())[:40].strip("_")
    out_dir = os.path.join("results", slug)
    os.makedirs(out_dir, exist_ok=True)
    manifest = Manifest(out_dir).load()
    forced_scenes = {int(x) for x in args.scenes.split(",") if x.strip().isdigit()}
    forced_assets = set()
    for _a in (args.assets or "").split(","):
        _pid = parse_shot_id(_a.strip())
        if _pid:
            forced_assets.add(_pid)
    output_path = args.out or os.path.join(out_dir, f"{slug}.mp4")
    mixed_path = os.path.join(out_dir, f"{slug}_mixed.mp4")
    timeline_path = os.path.join(out_dir, "timeline.json")
    run_report = {"topic": topic, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "strategy": "stills_first", "stages": {}, "errors": []}

    # v26 experiment telemetry: tag this run, record routing mode.
    import os as _os
    from src.providers import llm_telemetry
    llm_telemetry.reset()
    llm_telemetry.set_run(f"{slug}_{time.strftime('%Y%m%d_%H%M%S')}")
    run_report["experiment_routing"] = _os.environ.get("LLM_ROUTING_EXPERIMENT", "") or "production"

    mods = M._imports()
    factory = mods["ProviderFactory"]()
    from src.utils.config import get_config
    provider_name = args.provider or get_config("pipeline.roles.default", "gemini")
    # v19 (ckdigital direction): cost chain — primary -> gemini/grok/mistral
    # (keys present) -> deepseek LAST.  Gemini/Grok leveraged first;
    # DeepSeek stays the paid last resort.  ChainLLMProvider falls through
    # per-call on quota/errors so a Gemini 429 can't kill the run.
    llm = factory.get_cost_chain_llm_provider(provider_name)
    run_report["provider"] = provider_name
    run_report["provider_chain"] = [
        p.__class__.__name__ for p in getattr(llm, "_providers", [llm])
    ]
    # v19g: per-call attribution — which provider actually answered each
    # stage (ChainLLMProvider records usage as it goes).
    run_report["stages"]["provider_usage"] = (
        llm.usage() if hasattr(llm, "usage") else {}
    )

    if (args.reuse or args.scenes or args.assets) and os.path.exists(os.path.join(out_dir, "script_final.json")):
        print("  [reuse] Loading cached script_final.json + cached stills/audio")
        with open(os.path.join(out_dir, "script_final.json")) as f:
            scenes_data = json.load(f)
        with open(os.path.join(out_dir, "research.json")) as f:
            research = json.load(f)
        review_report = {"reused": True}
    else:
        # ── Research + verify ──────────────────────────────────────────────
        research = M.stage_research(topic, llm)
        research = M.stage_fact_verification(research, llm)
        # v19 (ckdigital direction): Kaggle datasets as bonus research source
        _kaggle = M.stage_kaggle_research(topic)
        if _kaggle:
            research["kaggle_datasets"] = _kaggle
            _ks = research.setdefault("key_sources", [])
            for _d in _kaggle.get("datasets", []):
                _ks.append(f"Kaggle dataset: {_d.get('title','')} ({_d.get('url','')})")
            run_report["stages"]["kaggle_research"] = {
                "datasets": len(_kaggle.get("datasets", [])),
                "elapsed_s": _kaggle.get("elapsed_s"),
            }
        M._write_json(os.path.join(out_dir, "research.json"), research)

        # ── Script + review ────────────────────────────────────────────────
        scenes_data = M.stage_script(topic, research, llm)
        M._write_json(os.path.join(out_dir, "script_draft.json"), scenes_data)
        scenes_data, review_report = M.stage_script_review(scenes_data, research, provider_name)
        # Post-review word-budget enforcement (reviewers expand the script;
        # compress back to the ~60s target).  Same fix as mission_run v1.1.
        total_words = sum(len(s.get("narration", "").split()) for s in scenes_data)
        if total_words > M.MAX_SCRIPT_WORDS:
            print(f"  !! Post-review over budget ({total_words} words) — compressing")
            compress = llm.generate_json(
                "Condense this script to between " + str(M.MIN_SCRIPT_WORDS) +
                " and " + str(M.MAX_SCRIPT_WORDS) +
                " words total (target ~" + str(int((M.MIN_SCRIPT_WORDS + M.MAX_SCRIPT_WORDS) / 2)) +
                "), keeping all facts and the " + str(M.SCENE_COUNT) + "-scene structure. "
                "Return ONLY the JSON array of scenes with title/narration/visual_goal/search_queries.\n" +
                json.dumps({"scenes": scenes_data})[:6000]
            )
            compressed_ok = False
            try:
                data2 = json.loads(compress)
                scenes2 = data2.get("scenes", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
                w2 = sum(len(s.get("narration", "").split()) for s in scenes2)
                # Must stay inside the target word band (not just under the
                # max — over-compressing to ~180 words yields an ~85s video
                # when the target is 120s).
                if len(scenes2) == M.SCENE_COUNT and M.MIN_SCRIPT_WORDS - 10 <= w2 <= M.MAX_SCRIPT_WORDS + 10:
                    scenes_data = M._merge_scene_meta(scenes_data, scenes2)
                    print(f"  Compressed to {w2} words (in target band)")
                    compressed_ok = True
                else:
                    print(f"  !! Compression output out of band (scenes={len(scenes2)}, words={w2}) — deterministic trim")
            except json.JSONDecodeError:
                print("  !! Post-review compression JSON failed — deterministic trim")
            # Deterministic hard-trim fallback (never silently keep an
            # over-budget script): truncate each scene's narration to a
            # proportional word budget, cutting at sentence boundaries.
            # Target the TOP of the band (MAX words / scene count) so the
            # trimmed script lands inside [MIN, MAX] — cutting to 0.9*MAX
            # per-scene undershot to ~248 words (~99s) when target was 120s.
            if not compressed_ok:
                per_scene = max(8, int(M.MAX_SCRIPT_WORDS / max(1, len(scenes_data))))
                for s in scenes_data:
                    n = s.get("narration", "")
                    words = n.split()
                    if len(words) > per_scene:
                        # cut at sentence boundary near the limit
                        truncated = words[:per_scene]
                        text = " ".join(truncated)
                        cut = text.rfind(". ")
                        if cut > len(text) * 0.5:
                            text = text[:cut + 1]
                        else:
                            cut = text.rfind(", ")
                            text = text[:cut] + "." if cut > 0 else text + "."
                        s["narration"] = text
                tw = sum(len(s.get("narration", "").split()) for s in scenes_data)
                print(f"  Deterministic trim → {tw} words")
        from src.utils.tts_normalize import normalize_narration, apply_prosody
        for s in scenes_data:
            s["narration"] = normalize_narration(s.get("narration", ""))
            # Wave-1 prosody: dramatic breath-pause before final sentence
            # for hook/emotion/conclusion intents
            s["narration"] = apply_prosody(s.get("narration", ""),
                                            intent=s.get("intent", "default"))
        M._write_json(os.path.join(out_dir, "script_review_report.json"), review_report)
        M._write_json(os.path.join(out_dir, "script_final.json"), scenes_data)

    # ── v13 (expert review rec #1/#9): FACTUAL CLAIM GATE ─────────────
    # Same hard gate as mission_run: extract + disambiguate + verify every
    # quantitative claim and named phenomenon BEFORE visuals.  A blocked
    # gate after one targeted rewrite aborts the run (never render a
    # factually broken script — the Bloop/52Hz conflation is exactly the
    # failure class this exists to prevent).
    #
    # v24 FAILSAFE (user directive): the gate must never die on its own
    # extraction artifact.  When claims fail we now: (1) iterate TARGETED
    # rewrites of the offending passages (up to MAX_CLAIM_FIX_ATTEMPTS),
    # (2) re-run the verifier after each rewrite, (3) if the SAME claims
    # survive every attempt, adjudicate whether they are extraction
    # artifacts of a distributed research-pack span (e.g. "DAVINCI+ and
    # VERITAS launch late 2020s and early 2030s" split into two
    # self-contradicting window claims).  All-artifact failures are
    # auto-overridden to advisory and the run CONTINUES with a loud
    # run_report entry.  Genuine, pack-unsupported contradictions still
    # hard-block — the expert's Bloop/52-Hz class must never render.
    try:
        from src.qa.claim_verifier import ClaimVerifier
        # v26 (ckdigital directive): claim verification is the high-confidence
        # final gate — ALWAYS DeepSeek, never the experiment head (free/cheap
        # models false-negative on claims; audit bench 4/10).
        _verifier = ClaimVerifier(llm=factory.get_final_gate_llm(), research_pack=research)
        _claim_gate = _verifier.run(scenes_data, out_dir=out_dir)
        run_report["claim_gate"] = _claim_gate
        run_report["stages"]["claim_gate"] = {
            "passed": _claim_gate["passed"],
            "blocking": _claim_gate["blocking_failures"],
        }
        MAX_CLAIM_FIX_ATTEMPTS = 3
        _attempt = 0
        while _claim_gate.get("blocking_failures") and _attempt < MAX_CLAIM_FIX_ATTEMPTS:
            _attempt += 1
            _blocking = list(_claim_gate.get("blocking_failures") or [])
            _failing = [c for c in (_claim_gate.get("claims") or [])
                        if c.get("status") == "contradicted"]
            _crit = [r for r in (_claim_gate.get("conflation_risks") or [])
                     if r.get("severity") == "critical"]
            print(f"  !! CLAIM GATE BLOCKED (attempt {_attempt}/{MAX_CLAIM_FIX_ATTEMPTS}): "
                  + str(_blocking))
            run_report["errors"].append(
                f"claim gate blocked (attempt {_attempt}): {_blocking}")
            _fix = llm.generate_json(
                "The narration below contains factual issues flagged by a "
                "fact-check gate.  Rewrite ONLY the sentences that carry the "
                "flagged claims — minimal edit, fix the factual problem in "
                "place (attribute the correct value/window to each entity, "
                "separate conjoined phenomena, remove wrong numbers).  Keep "
                "every OTHER sentence verbatim.  Keep tone, scene count and "
                "narration length.  Return STRICT JSON array of scenes with "
                "title/narration/visual_goal/search_queries.\n\n" +
                "Flagged claims (text | value | unit | reason):\n" +
                json.dumps(_failing, indent=1)[:4000] + "\n\n" +
                "Critical conflation risks:\n" +
                json.dumps(_crit, indent=1)[:2000] + "\n\n" +
                json.dumps({"scenes": scenes_data})[:6000])
            try:
                _fx = json.loads(_fix)
                _fx_scenes = _fx.get("scenes", []) if isinstance(_fx, dict) else (
                    _fx if isinstance(_fx, list) else [])
                if len(_fx_scenes) == len(scenes_data):
                    scenes_data = M._merge_scene_meta(scenes_data, _fx_scenes)
                    from src.utils.tts_normalize import normalize_narration
                    for _s in scenes_data:
                        _s["narration"] = normalize_narration(_s.get("narration", ""))
                    _claim_gate = _verifier.run(scenes_data, out_dir=out_dir)
                    # v22 (Gemini root-cause review): overwrite the stale FAILED
                    # claim_gate report with the FIXED result.  Previously only
                    # stages.claim_gate_fix was updated; resolve_status() reads
                    # run_report["claim_gate"] at the end, so every run stayed
                    # REVISION_REQUIRED on claims even after a successful rewrite.
                    run_report["claim_gate"] = _claim_gate
                    run_report["stages"][f"claim_gate_fix_{_attempt}"] = {
                        "passed": _claim_gate["passed"],
                        "blocking": _claim_gate["blocking_failures"],
                    }
                    if not _claim_gate["passed"]:
                        run_report["errors"].append(
                            f"claim gate still blocked after rewrite {_attempt}")
                    M._write_json(os.path.join(out_dir, "script_final.json"), scenes_data)
                else:
                    print(f"  !! claim-fix rewrite shape mismatch "
                          f"({len(_fx_scenes)} != {len(scenes_data)}) — retrying")
            except Exception as _e:
                print(f"  !! claim-fix rewrite failed: {str(_e)[:80]} — retrying")
        # v24 failsafe adjudication: claims that survived every targeted
        # rewrite AND are extraction artifacts of a pack-supported span are
        # auto-overridden (advisory, run continues).  Genuine contradictions
        # (no pack support) still hard-block below.
        if _claim_gate.get("blocking_failures"):
            _adj = _verifier.adjudicate_artifacts(_claim_gate)
            _blocking = list(_claim_gate.get("blocking_failures") or [])
            if _adj.get("all_artifacts") and set(_blocking) <= {"claim_contradictions"}:
                run_report["claim_gate_auto_overridden"] = {
                    "reason": ("all surviving contradicted claims are extraction "
                               "artifacts of a distributed research-pack span "
                               "(value+window supported by the pack; the claim "
                               "was split into self-contradicting pieces)"),
                    "attempts": _attempt,
                    "claims": _adj["artifacts"],
                }
                # Downgrade the check to advisory so the run continues, but
                # keep the report loud for the reviewer.
                _claim_gate["blocking_failures"] = [
                    b for b in _blocking if b != "claim_contradictions"]
                _claim_gate["passed"] = not _claim_gate["blocking_failures"]
                for _ck in (_claim_gate.get("checks") or []):
                    if _ck.get("name") == "claim_contradictions":
                        _ck["passed"] = True
                        _ck["detail"] = ("AUTO-OVERRIDDEN (span artifact): " +
                                         "; ".join(
                                             c.get("text", "")[:60]
                                             for c in _adj["artifacts"][:5]))
                print("  ⚠ CLAIM GATE AUTO-OVERRIDE — surviving failures are "
                      "extraction artifacts of a pack-supported span; "
                      "continuing (see run_report.claim_gate_auto_overridden).")
            else:
                from src.qa.publish_status import resolve_status, write_status
                _st = resolve_status(claim_gate=_claim_gate,
                                     fatal_errors=["claim gate blocked after rewrite"],
                                     artifacts=[os.path.join(out_dir, "claim_report.json")])
                write_status(out_dir, _st)
                run_report["status"] = _st
                M._write_json(os.path.join(out_dir, "run_report.json"), run_report)
                print("\n  ⛔ CLAIM GATE HARD BLOCK — script is factually unsafe.\n"
                      f"  {_st['summary']}\n"
                      "  Fix the script (see claim_report.json) and re-run.")
                sys.exit(3)
    except Exception as _e:
        print(f"  !! claim gate error (non-fatal): {str(_e)[:100]}")
        run_report["stages"]["claim_gate"] = {"error": str(_e)[:120]}
    # v20: record per-scene script hashes (dependency graph root) so the
    # manifest can decide per-scene voice/visual invalidation on reruns.
    # Recorded AFTER the claim gate (which may rewrite scenes_data).
    for _i, _s in enumerate(scenes_data):
        manifest.set_script(_i, _s.get("narration", ""))

    # Clear v2 motion clips so they regenerate with the fixed Ken Burns
    if os.path.isdir(os.path.join(out_dir, "shots")):
        shutil.rmtree(os.path.join(out_dir, "shots"))

    # ── v9 (Jade spec §1/§2): lock narrator voice + visual identity ──
    # Single voice + single style for the WHOLE episode, decided once
    # here and persisted so re-renders/improvement passes cannot drift.
    # Primary narrator = Fish Audio S2.1 Pro Free (2026-08-09 direction):
    # "Narrator" by Max N, one voice per video; Chatterbox fallback if
    # the Fish API fails; edge/kokoro remain exception-only fallbacks
    # inside stage_narration_dynamic.
    from src.qa.voice_lock import lock_voice
    from src.director.style_bible import create_style_bible
    from src.utils.config import get_config
    _voice_provider = get_config("voices.provider", "fish")
    try:
        if _voice_provider == "fish":
            from src.providers.tts_provider import FishAudioProvider
            _fish = FishAudioProvider()  # verifies key + model + voice
            _voice_id = _fish._voice_id
        elif _voice_provider == "elevenlabs":
            from src.providers.tts_provider import ElevenLabsProvider
            _el = ElevenLabsProvider()
            _voice_id = _el.voice_id
        else:
            _voice_id = get_config("voices.chatterbox.voice_id", "kurzgesagt_like")
    except Exception as _e:
        print(f"  !! narrator unavailable ({str(_e)[:100]}) — "
              f"locking chatterbox fallback for the WHOLE video")
        _voice_provider = "chatterbox"
        _voice_id = get_config("voices.chatterbox.voice_id", "kurzgesagt_like")
    voice_lock = lock_voice(provider=_voice_provider,
                            voice_id=_voice_id,
                            speaker_id="jade-narrator-001").reset_episode()
    style_bible = create_style_bible("jade").reset_episode()
    run_report["voice_lock"] = voice_lock.to_dict()
    run_report["style_bible"] = style_bible.to_dict()

    # ── Stills-first visual planning (with Wave-1 gates) ──────────────
    gates = None
    specs = None
    try:
        from src.pipeline.engine_gates import EngineGates
        from src.providers.llm_provider import set_usage_stage
        set_usage_stage("spec_build")
        gates = EngineGates(llm_provider=llm, vision_enabled=True)
        specs = gates.build_scene_specs(scenes_data, research.get("facts", []))
        run_report["entity_specs"] = {str(k): v.to_dict() for k, v in specs.items()}
        run_report["camera_diversity"] = gates.camera_diversity()
        # v10.2: stamp per-scene intent from the EntitySpec onto the scene
        # dicts so pace-padding, pacing audit and the pre-render gate all
        # score the SAME role band.  (v12 run: padding used 'default' band
        # (max 172) while the gate scored explanation scenes at max 160 —
        # scenes 2/4/5/6/7 were left rushed and the gate correctly aborted.)
        for _i, _s in enumerate(scenes_data):
            _spec = (specs or {}).get(_i)
            if _spec is not None and getattr(_spec, "scene_intent", None):
                _s["intent"] = _spec.scene_intent
    except Exception as e:
        print(f"  !! gates init failed (continuing un-gated): {str(e)[:100]}")
    # v20: --assets forces asset-level regeneration — delete the cached
    # still file(s) for the targeted shot ids so the fetch/cache-reuse
    # branch re-downloads and re-gates them (asset-level repair, not
    # scene-level: one bad image never forces the whole scene to rebuild).
    if forced_assets:
        _still_root = os.path.join("cache", "stills", slug)
        for _sc, _ix in sorted(forced_assets):
            _sid = f"s{_sc:02d}_sh{_ix:02d}"
            _asset = ""
            _prev_shots = (manifest._prev.get("scenes", {})
                           .get(str(_sc), {}).get("shots", []))
            for _sh in _prev_shots:
                if _sh.get("id") == _sid:
                    _asset = _sh.get("asset", "")
                    break
            _cands = []
            if _asset:
                _cands.append(_asset)
                _cands.append(_asset.replace(".jpg", "_crop.jpg"))
            _cands.append(os.path.join(_still_root, f"scene{_sc}_{_ix}.jpg"))
            for _c in _cands:
                if os.path.exists(_c):
                    os.remove(_c)
                    print(f"  [assets] removed {os.path.basename(_c)} for {_sid}")

    # v22 (Gemini root-cause review): narration-change cache invalidation.
    # The topic cache-reuse branch used to accept ANY still file > 15 KB on
    # disk, so after the claim gate rewrote a scene's narration the OLD stills
    # were silently reused (v6 run: cached=20, fresh=0 — the "same issue again
    # and again" pattern).  Scenes whose script hash changed vs the previous
    # manifest now bypass the cache-reuse branch entirely and re-fetch + re-gate.
    fresh_scenes: set[int] = set()
    try:
        _mdiff = manifest.diff()
        for _c in _mdiff:
            if _c.get("scene") is not None and "script" in _c.get("changed", []):
                fresh_scenes.add(int(_c["scene"]))
        if fresh_scenes:
            print(f"  [cache-invalidate] narration changed for scenes "
                  f"{sorted(fresh_scenes)} — bypassing still cache")
    except Exception as _e:
        print(f"  !! manifest diff for cache invalidation failed: {str(_e)[:80]}")

    shot_plan, stills_stats = stage_stills_visuals(scenes_data, out_dir, gates, specs,
                                                  topic_slug=slug,
                                                  style_bible=style_bible,
                                                  fresh_scenes=fresh_scenes)
    # v20: record per-shot asset hashes (asset-level dependency graph).
    # Each shot carries its durable still asset path; Ken Burns clips are
    # derived and cheap to regenerate, so only the still drives visual
    # change detection (clip files are cleaned up at run end anyway).
    for _i, _shots in (shot_plan or {}).items():
        for _si, _sh in enumerate(_shots):
            manifest.add_shot(
                _i, _si,
                file=_sh.get("file", ""),
                asset=_sh.get("asset", ""),
                kind=_sh.get("kind", ""),
                verification_passed=bool(
                    (_sh.get("verification") or {}).get("passed", True)),
                camera=_sh.get("camera", ""),
                query=_sh.get("query", ""),
            )
    style_bible.save()
    run_report["stages"]["visuals"] = stills_stats

    # ── Narration (dynamic, emotion-modulated; per-scene hash reuse) ────
    # v20: the manifest decides per-scene voice reuse.  A scene's cached
    # wav is reused ONLY when its script hash AND wav hash match the
    # manifest (replaces the old all-or-nothing --reuse, which could
    # silently reuse ANOTHER topic's narration from the global cache/audio
    # dir when scene counts matched).  --scenes forces specific scenes.
    os.makedirs("cache/audio", exist_ok=True)
    audio_durations = []
    narration_stats = {}
    regen_scenes = set()
    for i, s in enumerate(scenes_data):
        ap = os.path.join("cache", "audio", f"scene_{i}.wav")
        if not manifest.voice_reusable(i, ap, s.get("narration", "")):
            regen_scenes.add(i)
    regen_scenes |= forced_scenes
    if regen_scenes:
        print(f"  [voice] regenerating scenes: {sorted(regen_scenes)}", flush=True)
        audio_durations, narration_stats = M.stage_narration_dynamic(
            scenes_data, "cache/audio", provider=_voice_provider,
            voice_lock=voice_lock, scene_ids=regen_scenes)
    else:
        # every scene hash-verified → probe durations + record lock identity
        for i, s in enumerate(scenes_data):
            ap = os.path.join("cache", "audio", f"scene_{i}.wav")
            audio_durations.append(M._probe_duration(ap))
            if voice_lock is not None:
                voice_lock.record_scene(
                    i, voice_lock.provider, voice_lock.voice_id,
                )
        if voice_lock is not None:
            voice_lock.save()
        narration_stats = {
            "provider": f"cached({voice_lock.provider if voice_lock else 'unknown'})",
        }
    print(f"  Voice tracks: {len(scenes_data)} (total {sum(audio_durations):.1f}s) "
          f"[{narration_stats.get('provider')}]")

    # ── v12: TRIM EDGE SILENCE FIRST (root cause of voice stops: 0.4-0.6s
    # trailing silence per scene) — THEN pace-pad.  Trimming AFTER pacing
    # shortens the track and re-inflates WPM past the band, which failed
    # the pacing gate (scene 4: 153 -> 161 wpm after trim).
    audio_durations = _trim_scene_edges("cache/audio", scenes_data, audio_durations)

    # ── v10 (rec 1/11): PACING PADDING — if Chatterbox delivered a scene
    # faster than its role's comprehension band, insert pauses at sentence
    # boundaries so narration lands inside the band (space after key
    # facts).  Deterministic fix for "narration feels too fast".
    audio_durations = _pace_pad_scenes(scenes_data, "cache/audio", audio_durations)

    # v25 (Gemini/DeepSeek review: "voice jittery / abruptly stuttering"):
    # gentle amplitude smoothing on the narration stems AFTER pacing (so
    # the compressor evens the TTS loudness spikes without fighting the
    # inserted pauses), then record final voice hashes on the bytes that
    # actually ship.
    audio_durations = _smooth_stem_audio("cache/audio", scenes_data, audio_durations)

    # v20: record FINAL voice hashes (after trim + pace-pad rewrote the
    # wavs) so the manifest's voice hash matches the bytes on disk — a
    # reused track must hash-verify against exactly what the timeline uses.
    for _i in range(len(scenes_data)):
        _ap = os.path.join("cache", "audio", f"scene_{_i}.wav")
        manifest.set_voice(_i, _ap,
                           audio_durations[_i] if _i < len(audio_durations) else 0)

    # ── Timeline + render ──────────────────────────────────────────────
    build_stills_timeline(scenes_data, shot_plan, audio_durations, timeline_path)

    # ── v9 (Jade spec §9): DETERMINISTIC PRE-RENDER GATE ─────────────
    # Blocks render on objective plan failures: voice switching, style
    # drift, off-topic assets, invalid/non-kinetic Manim, long holds,
    # dead air, missing audio.  v10 adds pacing + semantic-alignment.
    from src.qa.jade_gates import PreRenderGate
    pre_gate = PreRenderGate().run(
        timeline_path=timeline_path,
        audio_dir="cache/audio",
        voice_lock=voice_lock,
        style_bible=style_bible,
        scenes_data=scenes_data,
        audio_durations=audio_durations,
    )
    run_report["stages"]["pre_render_gate"] = pre_gate
    _pre_blockers = pre_gate.get("blocking_failures", [])
    if _pre_blockers:
        print("  !! PRE-RENDER GATE BLOCKED: " + str(_pre_blockers))
        run_report["errors"].append(f"pre-render gate blocked: {_pre_blockers}")
        # v10.1 (rec 10): gates are fail-closed — never ship a video the
        # deterministic gates rejected.  Hard-abort instead of rendering
        # a blocked plan (Europa run exposed: gates logged, pipeline
        # rendered anyway -> 84s rushed video shipped as 'publish-ready').
        run_report["final"] = {
            "output": None, "iterations": 0,
            "error": f"pre-render gate blocked: {_pre_blockers}",
            "duration_s": 0,
        }
        M._write_json(os.path.join(out_dir, "run_report.json"), run_report)
        print("  ABORT: no render — fix plan failures and re-run.")
        sys.exit(2)
    else:
        print("  [gate] pre-render deterministic gate PASSED (render allowed)")

    print(f"\n[12/16] RENDERING → {output_path}", flush=True)
    t0 = time.time()
    if gates is not None:
        gates._instrumenter.start_render()
    # v12.4: coverage gate — heal or block before rendering (no black frames).
    _cov = M._ensure_timeline_coverage(scenes_data, timeline_path)
    if _cov.get("blocked"):
        print(f"  !! COVERAGE GATE BLOCKED: {_cov['blocked']}")
        run_report["errors"].append(f"coverage gate blocked: {_cov['blocked']}")
        run_report["final"] = {"output": None, "iterations": 0,
                               "error": f"coverage gate blocked: {_cov['blocked']}"}
        M._write_json(os.path.join(out_dir, "run_report.json"), run_report)
        print("  ABORT: no render — fix missing assets and re-run.")
        sys.exit(2)
    _subs = M._build_subtitle_clips(scenes_data, timeline_path)
    mods["MoviePyRenderer"]().render(timeline_path, output_path, subtitles=_subs)
    render_s = time.time() - t0
    run_report["stages"]["render_v1"] = {
        "duration_s": M._probe_duration(output_path),
        "size_mb": round(os.path.getsize(output_path) / 1e6, 1),
        "render_s": round(render_s, 1),
    }

    # ── Organic texture pass (v8): film grain + chromatic aberration +    ──
    #    unified grade, applied to the master before the audio mix so the    ──
    #    final upload carries the cinematic look.  Masks the AI 'too clean'  ──
    #    aesthetic; subtle enough to keep QA passing.                        ──
    graded_path = output_path
    try:
        graded_path = os.path.join(out_dir, f"{slug}_graded.mp4")
        grade_stats = M.stage_cinematic_grade(output_path, graded_path,
                                              grain=8, strength=1.0)
        run_report["stages"]["grade_v1"] = grade_stats
        if grade_stats.get("graded"):
            output_path = graded_path
    except Exception as e:
        print(f"  !! grade pass failed (non-fatal, using ungraded): {str(e)[:100]}")

    # ── Wave-1: instrument shots with timeline placement ──────────────
    if gates is not None:
        try:
            with open(timeline_path) as f:
                tl = json.load(f)
            # map shot files to their timeline placement
            placement = {}
            for v in tl.get("video_timeline", []):
                placement.setdefault(os.path.basename(v.get("file", "")), []).append(v)
            for i, shots in shot_plan.items():
                adur = audio_durations[i] if i < len(audio_durations) else 0
                for si, sh in enumerate(shots):
                    base = os.path.basename(sh.get("file", ""))
                    pl = (placement.get(base) or [{}])[0]
                    gates.record_shot(
                        scene_id=i, beat_index=0, shot_index=si,
                        asset_path=sh.get("file", ""),
                        asset_source=sh.get("kind", ""),
                        asset_title=sh.get("title", ""),
                        query_used=sh.get("query", ""),
                        shot_duration_s=sh.get("duration", 0),
                        narration_duration_s=adur,
                        camera_motion=sh.get("camera", "static"),
                        motion_params=sh.get("motion_params", {}),
                        transition=pl.get("transition", ""),
                        timeline_start_s=pl.get("start_time", 0),
                        timeline_end_s=pl.get("end_time", 0),
                        verification=sh.get("verification"),
                        entity_spec=(specs or {}).get(i).to_dict() if (specs or {}).get(i) else None,
                    )
            gates.write_diagnostics(out_dir, render_s)
            run_report["diversity"] = gates._diversity.metrics()
            run_report["camera_diversity"] = gates.camera_diversity()
        except Exception as e:
            print(f"  !! instrumentation failed (non-fatal): {str(e)[:100]}")

    # ── Wave-1: deterministic QA gate (block only objective failures) ──
    if gates is not None:
        allow, qa_report = gates.qa_gate(output_path, timeline_path, out_dir)
        run_report["stages"]["qa_v1"] = qa_report
        if not allow:
            print("  !! QA BLOCKED: objective failures → " +
                  str(qa_report["blocking_failures"]))
        else:
            print("  [qa] deterministic QA passed (no objective failures)")

    # ── Retention diagnostic (v8): novelty density + dead-air audit ────
    # Pre-upload check per 2026 AVD benchmarks: every few seconds must
    # introduce new visual/audio stimulus; dead air and long static holds
    # are the top drop-off risks.  Emits a report + auto-splits long holds.
    try:
        tl_now = json.load(open(timeline_path))
        vt = tl_now.get("video_timeline", [])
        total_dur = max(0.1, vt[-1].get("end_time", 0) if vt else 0)
        # novelty density = distinct visual assets per 10s
        shots = len(vt)
        novelty_per_10s = round(shots / max(1, total_dur / 10.0), 2)
        # longest single-hold (same asset without a cut)
        longest_hold = 0.0
        for v in vt:
            hold = v.get("end_time", 0) - v.get("start_time", 0)
            longest_hold = max(longest_hold, hold)
        # dead air: audio gaps > 1.5s between narration tracks
        at = tl_now.get("audio_timeline", [])
        dead_air = 0.0
        for a, b in zip(at, at[1:]):
            gap = b.get("start_time", 0) - a.get("end_time", 0)
            if gap > 1.5:
                dead_air += gap
        retention_diag = {
            "novelty_density_per_10s": novelty_per_10s,
            "longest_hold_s": round(longest_hold, 1),
            "dead_air_s": round(dead_air, 1),
            "shots": shots,
            "benchmark": {"hook_window_s": 15, "max_hold_s": 4.0,
                           "target_novelty_per_10s": 1.5},
            "flags": [],
        }
        if longest_hold > 4.0:
            retention_diag["flags"].append(
                f"longest hold {longest_hold:.1f}s > 4s (drop-off risk)")
        if novelty_per_10s < 1.2:
            retention_diag["flags"].append(
                f"novelty density {novelty_per_10s}/10s below 1.2")
        if dead_air > 2.0:
            retention_diag["flags"].append(
                f"{dead_air:.1f}s dead air detected (trim recommended)")
        run_report["retention_diagnostic"] = retention_diag
        print(f"  [retention] novelty={novelty_per_10s}/10s hold={longest_hold:.1f}s "
              f"dead_air={dead_air:.1f}s flags={len(retention_diag['flags'])}")
    except Exception as e:
        print(f"  !! retention diagnostic failed (non-fatal): {str(e)[:80]}")

    # ── Disclosure metadata (v8): synthetic-content compliance ──────────
    # 2026 platforms require transparent synthetic-media labeling; the
    # pipeline emits a sidecar so uploads can carry the required metadata.
    try:
        disclosure = {
            "synthetic_content": True,
            "disclosure_label": "AI-generated content: synthetic narration, "
                                 "AI-assisted visuals and sound design",
            "no_fakes_compliant": True,  # no real human likeness/voice cloning
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pipeline": "jade-studio/v8",
        }
        run_report["disclosure"] = disclosure
        import json as _json
        with open(os.path.join(out_dir, "synthetic_disclosure.json"), "w") as f:
            _json.dump(disclosure, f, indent=2)
    except Exception as e:
        print(f"  !! disclosure metadata failed (non-fatal): {str(e)[:80]}")

    # ── Music (event-driven SFX timeline + ducked bed) ──────────────────
    sfx_path = ""
    sfx_events_placed = []
    try:
        sfx_path = os.path.join("cache", "music", "sfx_timeline.wav")
        # §4.1 (2026): anchor SFX to VISUAL CUT timecodes from timeline.json
        # instead of narration phrase positions — SFX must mark on-screen
        # state changes, not commas in the script.
        _cut_times = {}
        _manim_times: list[float] = []
        if os.path.exists(timeline_path):
            try:
                with open(timeline_path) as _f:
                    _tl = json.load(_f)
                for _e in _tl.get("video_timeline", []):
                    _sid = _e.get("scene_id")
                    if _sid is not None:
                        _cut_times.setdefault(_sid, []).append(
                            float(_e.get("start_time", 0)))
                    # v19l: auto-whoosh when a Manim/vector clip enters
                    _fp = (_e.get("file") or "").replace("\\", "/")
                    if "/manim/" in _fp or "/vector/" in _fp:
                        _manim_times.append(float(_e.get("start_time", 0)))
            except Exception:
                _cut_times = {}
        sfx_path, sfx_events_placed = M.build_sfx_timeline(
            scenes_data, audio_durations, sfx_path, cut_times=_cut_times,
            manim_times=_manim_times)
        if not sfx_events_placed:
            sfx_path = ""
    except Exception as e:
        print(f"  !! SFX timeline build failed (non-fatal): {str(e)[:100]}")
        sfx_path = ""
    mix = M.stage_music_mix(output_path, "cache/music/cinematic.mp3", mixed_path,
                            sfx_path=sfx_path, scenes=scenes_data,
                            audio_durations=audio_durations)
    mix["sfx_events"] = sfx_events_placed
    run_report["stages"]["music_v1"] = mix
    review_target = mixed_path if mix.get("mixed") else output_path

    # ── Gemini review + improvement passes ─────────────────────────────
    review = None
    try:
        review = M.stage_video_review(review_target, scenes_data,
                                      os.path.join(out_dir, "review_v1.json"))
        run_report["stages"]["review_v1"] = {
            "score": (review or {}).get("quality_score"),
            "confidence": (review or {}).get("confidence"),
            "model_used": (review or {}).get("_meta", {}).get("model_used"),
        }
    except Exception as e:
        print(f"  !! video review failed (non-fatal, continuing): {str(e)[:120]}")
        run_report["stages"]["review_v1"] = {"error": str(e)[:200]}
    iteration = 1
    # v12.5 cost guardrails: 1 improvement pass max; only when the review
    # score is below improve_score_threshold. Hard stop at 2 (1 rerender).
    from src.utils.config import get_config as _gc2
    _thr = _gc2("pipeline.improve_score_threshold", 70)
    _score = (review or {}).get("quality_score") or 0
    max_iter = 1 if (review is None or _score >= _thr) else 2
    if max_iter > 1:
        print(f"  Score {_score} < {_thr} → improvement loop active (max {max_iter} renders)", flush=True)
    while iteration < max_iter:
        plan_dict = M.stage_improvement_plan(review, iteration + 1, out_dir, max_total=max_iter)
        run_report["stages"][f"improve_pass_{iteration}"] = plan_dict
        if plan_dict.get("stopped_early") or not plan_dict.get("applied"):
            break
        applied = M.stage_apply_improvements(plan_dict, timeline_path)
        if not applied:
            break
        t0 = time.time()
        # Render to the RAW path first (never into graded_path — the grade
        # pass needs distinct input/output files; rendering into graded.mp4
        # then grading it onto itself makes ffmpeg exit "same as Input #0").
        raw_render = os.path.join(out_dir, f"{slug}.mp4")
        # v12.4: coverage gate + burned-in subtitles on every re-render.
        _cov = M._ensure_timeline_coverage(scenes_data, timeline_path)
        if _cov.get("blocked"):
            print(f"  !! COVERAGE GATE BLOCKED on re-render: {_cov['blocked']}")
            run_report["errors"].append(f"coverage gate blocked: {_cov['blocked']}")
            break
        _subs = M._build_subtitle_clips(scenes_data, timeline_path)
        mods["MoviePyRenderer"]().render(timeline_path, raw_render, subtitles=_subs)
        # re-apply organic texture pass so the improved render keeps the look
        try:
            graded_path = os.path.join(out_dir, f"{slug}_graded.mp4")
            gs = M.stage_cinematic_grade(raw_render, graded_path,
                                         grain=8, strength=1.0)
            if gs.get("graded"):
                output_path = graded_path
            else:
                output_path = raw_render
        except Exception as e:
            print(f"  !! grade pass failed on re-render (non-fatal): {str(e)[:80]}")
            output_path = raw_render
        run_report["stages"][f"render_v{iteration+1}"] = {
            "duration_s": M._probe_duration(output_path),
            "render_s": round(time.time() - t0, 1),
        }
        mix = M.stage_music_mix(output_path, "cache/music/cinematic.mp3", mixed_path,
                                sfx_path=sfx_path, scenes=scenes_data,
                                audio_durations=audio_durations)
        review_target = mixed_path if mix.get("mixed") else output_path
        try:
            review = M.stage_video_review(review_target, scenes_data,
                                          os.path.join(out_dir, f"review_v{iteration+1}.json"))
            run_report["stages"][f"review_v{iteration+1}"] = {
                "score": (review or {}).get("quality_score"),
                "confidence": (review or {}).get("confidence"),
                "model_used": (review or {}).get("_meta", {}).get("model_used"),
            }
        except Exception as e:
            print(f"  !! re-review failed (non-fatal): {str(e)[:120]}")
            run_report["stages"][f"review_v{iteration+1}"] = {"error": str(e)[:200]}
            break
        iteration += 1

    # ── v27 (Oumuamua feedback req 4): DUAL-MODEL REVIEW ─────────────
    # The per-iteration review above is Gemini Flash only.  Oumuamua
    # feedback: "get the video reviewed by Gemini AND DeepSeek Pro".
    # Run the detailed dual review (Gemini vision on sampled frames +
    # DeepSeek Pro on script + visual transcript) once on the FINAL
    # video, save review_gemini.json / review_deepseek.json into out_dir,
    # and surface DeepSeek's critical defects as degradations.
    dual_review = {}
    try:
        dual_review = M.stage_video_review_dual(
            review_target, scenes_data, out_dir,
            timeline_path=timeline_path,
            script_path=os.path.join(out_dir, "script_final.json"),
        )
        run_report["stages"]["review_dual"] = {
            "gemini_score": (dual_review.get("gemini") or {}).get("score"),
            "deepseek_score": (dual_review.get("deepseek") or {}).get("score"),
            "gemini_model": (dual_review.get("gemini") or {}).get("model"),
            "deepseek_model": (dual_review.get("deepseek") or {}).get("model"),
            "frames": dual_review.get("frames"),
            "error": dual_review.get("error"),
        }
    except Exception as e:
        print(f"  !! dual review failed (non-fatal): {str(e)[:120]}")
        run_report["stages"]["review_dual"] = {"error": str(e)[:200]}

    # ── v9 (Jade spec §10): PUBLISH-READINESS GATE on the final video ──
    # Deterministic: hook strength in the opening seconds, voice
    # consistency, style lock, dead-air/clipping on the mastered audio,
    # no black opening.  ``publish_ready`` must be true to ship.
    try:
        from src.qa.jade_gates import PublishGate
        publish = PublishGate().run(
            video_path=review_target,
            timeline_path=timeline_path,
            voice_lock=voice_lock,
            style_bible=style_bible,
        )
        run_report["publish_gate"] = publish
        _pub_blockers = publish.get("blocking_failures", [])
        if publish.get("publish_ready"):
            print("  [gate] PUBLISH-READY ✓ (all deterministic gates passed)")
        else:
            print("  !! PUBLISH GATE: not publish-ready → " + str(_pub_blockers))
            run_report["errors"].append(f"publish gate: {_pub_blockers}")
        with open(os.path.join(out_dir, "publish_gate.json"), "w") as _f:
            json.dump(publish, _f, indent=2)
    except Exception as e:
        print(f"  !! publish gate failed (non-fatal): {str(e)[:100]}")
        run_report["publish_gate"] = {"error": str(e)[:200]}

    # ── v13 (expert review rec #10): RUN-LEVEL PUBLISH STATUS ─────────
    # Same PUBLISH_READY / REVISION_REQUIRED / BLOCKED state machine as
    # mission_run — the cron-driven daily pipeline uploads ONLY when
    # PUBLISH_READY (see tools/daily_video.sh).
    try:
        from src.qa.publish_status import resolve_status, write_status
        _status = resolve_status(
            publish_gate=run_report.get("publish_gate"),
            pre_render_gate=run_report.get("stages", {}).get("pre_render_gate"),
            claim_gate=run_report.get("claim_gate"),
            fatal_errors=[] if os.path.exists(review_target)
                          else ["final video artifact missing"],
            artifacts=[review_target],
        )
        run_report["status"] = _status
        write_status(out_dir, _status)
        print(f"\n  [status] {_status['status']}" +
              (f" — blocked by: {_status['blocked_by']}"
               if _status.get("blocked_by") else " — all gates passed"))
    except Exception as e:
        print(f"  !! status resolution failed (non-fatal): {str(e)[:100]}")
        run_report["status"] = {"error": str(e)[:160]}
    # ── Interim-asset cleanup (studio policy: keep only the final video) ──
    # Every run produces several mp4s (raw render, graded master, final mix)
    # plus a shots/ dir of Ken Burns clips.  Only the final _mixed master is
    # a deliverable — remove the rest so results/<slug>/ stays clean.
    try:
        import glob as _glob
        kept = None
        for f in _glob.glob(os.path.join(out_dir, "*.mp4")):
            if f == mixed_path:
                kept = f
                continue
            os.remove(f)
            print(f"  [cleanup] removed interim {os.path.basename(f)}")
        shots_dir = os.path.join(out_dir, "shots")
        if os.path.isdir(shots_dir):
            shutil.rmtree(shots_dir, ignore_errors=True)
            print("  [cleanup] removed interim shots/ dir")
        run_report["cleanup"] = {
            "policy": "keep-final-only",
            "kept": os.path.basename(kept) if kept else None,
        }
    except Exception as e:
        print(f"  !! interim cleanup failed (non-fatal): {str(e)[:100]}")

    # ── Final + postmortem ─────────────────────────────────────────────
    # ── Degradations report (iteration guidance #3: no silent degradation) ──
    degradations = []
    if research.get("_verification_failed"):
        degradations.append({
            "stage": "fact_verification",
            "severity": "warning",
            "detail": research.get("_verification_error", "verification pass failed"),
        })
    if stills_stats.get("rejected", 0):
        degradations.append({
            "stage": "asset_gate",
            "severity": "info",
            "detail": f"{stills_stats['rejected']} assets rejected by Entity-Asset verification (correct behavior)",
        })
    if stills_stats.get("deduped", 0):
        degradations.append({
            "stage": "asset_dedup",
            "severity": "info",
            "detail": f"{stills_stats['deduped']} near-identical assets skipped (perceptual dedup)",
        })
    qa_block = run_report.get("stages", {}).get("qa_v1", {}).get("blocking_failures", [])
    if qa_block:
        degradations.append({
            "stage": "deterministic_qa",
            "severity": "error",
            "detail": f"blocking failures: {qa_block}",
        })
    if run_report.get("stages", {}).get("music_v1", {}).get("mixed") is False:
        degradations.append({
            "stage": "music", "severity": "warning",
            "detail": "music mix failed or no bed available",
        })
    # v27 (Oumuamua feedback req 4): surface the dual-model review outcome —
    # DeepSeek Pro critical defects and low scores must not ship silently.
    _dual = run_report.get("stages", {}).get("review_dual", {}) or {}
    if _dual.get("error"):
        degradations.append({
            "stage": "dual_review", "severity": "warning",
            "detail": f"dual-model review incomplete: {_dual['error'][:120]}",
        })
    _ds_score = _dual.get("deepseek_score")
    if _ds_score is not None and _ds_score < int(_thr or 70):
        degradations.append({
            "stage": "dual_review", "severity": "warning",
            "detail": f"DeepSeek Pro score {_ds_score}/100 below "
                      f"improve threshold {_thr} (Gemini "
                      f"{_dual.get('gemini_score')}/100)",
        })
    # ── v10 (rec 10/11): pacing failures are exposed, never silent ────
    from src.cinematic.pacing_engine import audit_pacing
    pacing_audit = audit_pacing(scenes_data, audio_durations)
    run_report["pacing"] = pacing_audit
    for row in pacing_audit["high_risk_scenes"]:
        degradations.append({
            "stage": "pacing", "severity": "warning",
            "detail": f"scene {row['scene']}: {'; '.join(row['flags'])}",
        })
    if run_report.get("stages", {}).get("pre_render_gate", {}).get("blocking_failures"):
        degradations.append({
            "stage": "pre_render_gate", "severity": "error",
            "detail": "blocking failures: " + str(
                run_report["stages"]["pre_render_gate"]["blocking_failures"]),
        })
    run_report["degradations"] = degradations

    run_report["final"] = {
        "output": review_target, "iterations": iteration,
        "final_score": (review or {}).get("quality_score"),
        "duration_s": M._probe_duration(review_target),
        "visual_stats": stills_stats,
    }
    # ── v20: persist the content-addressed manifest ─────────────────────
    # Dependency-graph record of every artifact (script/voice/visual
    # hashes per scene).  Next run diffs against it to regenerate ONLY
    # what changed; --scenes/--assets operate through this graph.
    for _i, _s in enumerate(scenes_data):
        manifest.set_subtitles_hash(_i, hash_text(_s.get("narration", "")))
    manifest.set_global("topic", topic)
    manifest.set_global("target_seconds", args.target_seconds)
    manifest.set_final(
        output=os.path.basename(review_target) if os.path.exists(review_target) else None,
        status=run_report.get("status", {}).get("status"),
        quality_score=(review or {}).get("quality_score"),
        duration_s=M._probe_duration(review_target) if os.path.exists(review_target) else 0,
    )
    manifest.save()
    _mdiff = manifest.diff()
    if _mdiff:
        print(f"  [manifest] {len(_mdiff)} change(s) vs previous run:")
        for _c in _mdiff:
            _who = f"scene {_c['scene']}" if _c["scene"] is not None else "global"
            print(f"    {_who}: {', '.join(_c['changed'])} → {', '.join(_c['actions'])}")
    else:
        print("  [manifest] no changes vs previous run (full reuse)")
    # ── DeepSeek usage + cost report (per-stage, whole run) ────────────
    try:
        from src.providers.llm_provider import DeepSeekUsage
        usage = DeepSeekUsage.summary()
        run_report["llm_usage_deepseek"] = usage
        # v26 experiment telemetry: per-provider metrics + JSONL evidence.
        from src.providers import llm_telemetry
        run_report["llm_experiment"] = llm_telemetry.summary()
        run_report["llm_telemetry_file"] = llm_telemetry.save()
        tot = usage["total"]
        print("\n[DEEPSEEK USAGE — this run]")
        print(f"  calls: {tot['calls']} | input: {tot['input']:,} tok "
              f"(cached {tot['cached']:,}) | output: {tot['output']:,} tok")
        print(f"  estimated cost: ${tot['cost_usd']:.4f}")
        for stage, row in usage["stages"].items():
            print(f"    {stage:20s} calls={row['calls']:3d} in={row['input']:>7,} "
                  f"out={row['output']:>6,} cost=${row['cost_usd']:.4f}")
    except Exception as e:
        print(f"  !! usage report failed (non-fatal): {str(e)[:80]}")
    M._write_json(os.path.join(out_dir, "run_report.json"), run_report)

    _score = (review or {}).get("quality_score")
    recorder = mods["PostmortemRecorder"]()
    pm_path = recorder.record(
        topic + " (stills-first)",
        techniques_succeeded=[
            "stills-first visual strategy: NASA/Wikimedia/AI Ken Burns + Manim beats",
            f"manim scenes: {stills_stats.get('manim', 0)}, nasa: {stills_stats.get('nasa', 0)}, "
            f"wikimedia: {stills_stats.get('wikimedia', 0)}, ai: {stills_stats.get('ai', 0)}",
            f"Gemini review score {_score}/100",
        ],
        techniques_failed=[
            "stock-video director (pexels) deprioritized by design in stills mode",
        ],
        metrics={"final_score": _score,
                 "duration_s": M._probe_duration(review_target),
                 "avg_wpm": pacing_audit.get("avg_wpm"),
                 "rushed_scene_count": pacing_audit.get("rushed_scene_count"),
                 **stills_stats},
        artifacts={"video": review_target, "report": os.path.join(out_dir, "run_report.json")},
    )
    run_report["postmortem"] = pm_path
    M._write_json(os.path.join(out_dir, "run_report.json"), run_report)

    print(f"\n{'=' * 64}")
    print(f"STILLS-FIRST RUN COMPLETE — {topic}")
    print(f"  Video:  {review_target}")
    print(f"  Score:  {_score}/100 | Dur: {M._probe_duration(review_target):.1f}s")
    print(f"  Sources: {stills_stats}")
    print("=" * 64)


if __name__ == "__main__":
    main()
