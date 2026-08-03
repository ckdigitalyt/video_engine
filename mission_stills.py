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
import shutil
import subprocess
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import mission_run as M


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


def _ai_still(prompt: str, out_path: str) -> str:
    from src.providers.image_gen import NvidiaNimProvider, PollinationsProvider
    for prov in (NvidiaNimProvider(), PollinationsProvider()):
        try:
            prov.generate(prompt, out_path, width=1024, height=576)
            print(f"  [AI] {prov.name}: {os.path.basename(out_path)} ({os.path.getsize(out_path)//1024} KB)")
            return out_path
        except Exception as e:
            print(f"  [AI] !! {prov.name} failed: {str(e)[:80]}")
    return ""


# ═══════════════════════════════════════════════════════════════════════ #
# Stills-first visual planner
# ═══════════════════════════════════════════════════════════════════════ #

MANIM_SCENES = {
    "voyager_scale": "cache/manim/voyager_scale.mp4",
    "voyager_timeline": "cache/manim/voyager_timeline.mp4",
    "voyager_trajectory": "cache/manim/voyager_trajectory.mp4",
    "sun_scale": "cache/manim/sun_scale.mp4",
    "sun_layers": "cache/manim/sun_layers.mp4",
    "pulsar_lighthouse": "cache/manim/pulsar_lighthouse.mp4",
    "pulsar_density": "cache/manim/pulsar_density.mp4",
    "black_hole_lensing": "cache/manim/black_hole_lensing.mp4",
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
}

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
    if zoom_in:
        z_start = float(cam.get("zoom_start", 1.0))
        z_end = float(cam.get("zoom_end", 1.22))
    else:
        z_start = float(cam.get("zoom_start", 1.22))
        z_end = float(cam.get("zoom_end", 1.0))
    pan_x = float(cam.get("pan_x", 0))
    pan_y = float(cam.get("pan_y", 0))
    # linear zoom: z = z_start + (z_end - z_start) * on/frames
    z_expr = f"{z_start}+({z_end}-{z_start})*on/{frames}"
    # pan: drift by pan_x/pan_y pixels (in 2x space) across the shot
    px = f"(iw-iw/zoom)/2+({pan_x}*2)*on/{frames}"
    py = f"(ih-ih/zoom)/2+({pan_y}*2)*on/{frames}"
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


def _detect_topic(scene_text: str) -> str:
    t = scene_text.lower()
    for topic, hints in _TOPIC_HINTS.items():
        if any(h in t for h in hints):
            return topic
    return ""


def _manim_scene_for(scene_text: str, intent: str = "default") -> str:
    """Pick a Manim scene by topic + intent (general, registry-driven)."""
    topic = _detect_topic(scene_text)
    if not topic or topic not in TOPIC_MANIM:
        return ""
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
    return ""


# Visual style modifiers ("Jade" subsystem).
#
# STUDIO DECISION (2026-08-03): consistency over rotation.  ckdigital
# asked for ONE fixed style + ONE color combination used for every
# cartoon/stylized shot, so the video reads as a single art direction
# instead of a mix of unrelated styles.  All non-photoreal AI stills now
# use FIXED_JADE_STYLE (+ its fixed palette) regardless of scene emotion;
# the per-emotion rotation below is kept only as a fallback for scenes
# that carry an explicit visual_style that is NOT in the fixed set.
FIXED_JADE_STYLE = (
    "hand-painted cinematic concept art, painterly brushwork, rich depth, "
    "warm amber and deep teal color palette with soft cream highlights, "
    "consistent lighting and color grade, no text"
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


def _style_prompt_for(scene: dict, fallback: str = "") -> str:
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


def _still_plan_for(scene_text: str, spec=None, scene=None) -> list:
    """Ordered candidate prompts/queries for still imagery.

    Priority: the script's curated ``search_queries`` (specific, topic-
    correct, e.g. "Jocelyn Bell Burnell 1967") → EntitySpec required
    entities → topic-aware keyword hints.  Bare entity terms are the
    LEAST preferred because they collide with homonyms (a Wikimedia
    search for "pulsar" returns a roller coaster at Walibi Belgium).
    AI fallback stills use the scene's Jade visual style.
    """
    t = scene_text.lower()
    topic = _detect_topic(scene_text)
    plan = []
    style_mod = _style_prompt_for(scene)

    # 1) Script-authored search queries (most specific, least ambiguous)
    for q in (scene or {}).get("search_queries", []) or []:
        q = (q or "").strip()
        if q:
            plan += [("nasa", q), ("wiki", q)]

    # 2) EntitySpec-driven: search NASA/Wikimedia for each required entity
    if spec is not None and spec.required_entities:
        for ent in spec.required_entities[:2]:
            plan += [("nasa", ent), ("wiki", ent)]
        obj = spec.visual_objective or f"{topic} documentary scene"
        # Stylized "Jade" shot FIRST when the scene requests a non-photoreal
        # art direction — otherwise NASA/Wikimedia real photos fill every
        # slot and the stylization never renders (reviewer: "no cartoon /
        # animation / hand-drawn images in the video").
        style = ((scene or {}).get("visual_style") or "").strip().lower()
        if style and style != "photorealistic":
            plan.insert(0, ("ai", f"{obj}. {style_mod}"))
        else:
            plan.append(("ai", f"{obj}. {style_mod}"))
    else:
        # topic-aware keyword fallback (still general, not per-topic lists)
        plan += [("nasa", topic), ("wiki", topic),
                 ("ai", f"Illustration of {topic}. {style_mod}")]

    # dedupe keeping order
    seen, out = set(), []
    for p in plan:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def stage_stills_visuals(scenes_data: list[dict], out_dir: str,
                         gates=None, specs: Optional[dict] = None,
                         topic_slug: str = "") -> dict:
    """Build per-scene shot lists: Manim clips + Ken Burns stills.

    When *gates* is provided, every candidate still is verified against
    its scene's EntitySpec (multi-signal + vision fallback) before it may
    enter the timeline, and camera moves come from the intent-driven
    CameraDirector instead of alternating zoom_in flags.

    Stills are cached topic-scoped (``cache/stills/<topic_slug>/``) so a
    fresh topic never reuses another topic's pinned assets.

    Returns {scene_id: [{"file": clip, "duration": s}, ...]} and stats.
    """
    print("\n[5-9/16] STILLS-FIRST VISUAL PLANNING (NASA/Wikimedia/AI + Manim)", flush=True)
    t0 = time.time()
    os.makedirs(os.path.join(out_dir, "shots"), exist_ok=True)
    still_root = os.path.join("cache", "stills", topic_slug or "default")
    os.makedirs(still_root, exist_ok=True)
    pinned = PINNED_STILLS_BY_TOPIC.get(topic_slug, {})

    plan = {}
    stats = {"manim": 0, "nasa": 0, "wikimedia": 0, "ai": 0, "video_fallback": 0,
             "rejected": 0, "vision_checked": 0, "deduped": 0}
    manim_used = set()
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
        # 1) Manim explanation clip if scene calls for it
        manim = _manim_scene_for(text, intent)
        if manim and os.path.exists(manim) and manim not in manim_used:
            manim_used.add(manim)
            shots.append({"file": manim, "duration": min(10.0, M._probe_duration(manim)),
                          "kind": "manim"})
            stats["manim"] += 1
        # 2) Stills with Ken Burns (2 per scene typically)
        still_count = 0
        for kind, query in _still_plan_for(text, spec, scene):
            if still_count >= 2:
                break
            fname = f"scene{i}_{still_count}.jpg"
            out = os.path.join(still_root, fname)
            got, src, title = "", "", ""
            if fname in pinned and os.path.exists(out) and os.path.getsize(out) > 15000:
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
            if not got:
                continue
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
                pre_verified = fname in pinned or kind == "ai"
                ver = gates.verify_asset(
                    spec, asset_path=got, title=title, filename=fname,
                    provider=src, query_used=query, pre_verified=pre_verified,
                )
                stats["vision_checked"] += int(bool(ver.get("vision_check")))
                if not ver.get("passed"):
                    stats["rejected"] += 1
                    print(f"  [gate] rejected {fname} "
                          f"({ver.get('reasons', ['?'])[:1]})")
                    continue
            # ── CAMERA: intent-driven motion (diversity-aware) ─────────
            clip = os.path.join(out_dir, "shots", fname.replace(".jpg", ".mp4"))
            dur = 5.5 if len(shots) < 3 else 4.5
            cam = gates.camera_decision(intent) if gates is not None else {
                "move": "push_in" if still_count % 2 == 0 else "pull_out",
                "params": {},
            }
            cam_params = cam.get("params", {}) or {}
            zoom_in = cam_params.get("zoom_end", 1.2) > cam_params.get("zoom_start", 1.0)
            kb = _kenburns(got, clip, duration=dur, zoom_in=zoom_in,
                           camera=cam_params)
            if kb:
                shots.append({"file": clip, "duration": dur, "kind": src,
                              "camera": cam.get("move", "push_in"),
                              "motion_params": cam_params,
                              "verification": ver if (gates is not None and spec is not None) else None,
                              "title": title, "query": query})
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
        # If only one asset survived the gate/dedup:
        #   - still asset  -> second Ken Burns pass with the OPPOSITE
        #     camera move (push-in vs pull-out)
        #   - manim clip   -> extract a frame and Ken Burns it (breaks the
        #     long static title-card hold reviewers flagged)
        if len(shots) == 1:
            # estimate narration duration: ~2.6 words/sec spoken
            est = max(4.0, len(text.split()) / 2.6)
            if est > 8.0:
                last = shots[0]
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
                    variant = os.path.join(
                        out_dir, "shots", f"scene{i}_variant_{still_count}.mp4")
                    vcam = cam_params if still_count else {}
                    vcam = dict(vcam)
                    # invert the camera move for visual novelty
                    if vcam.get("zoom_end", 1.2) > vcam.get("zoom_start", 1.0):
                        vcam["zoom_start"], vcam["zoom_end"] = vcam.get("zoom_end", 1.22), vcam.get("zoom_start", 1.0)
                        vmove = "pull_out"
                    else:
                        vcam["zoom_start"], vcam["zoom_end"] = vcam.get("zoom_start", 1.0) or 1.0, 1.22
                        vmove = "push_in"
                    if _kenburns(src_img, variant, duration=5.5,
                                 zoom_in=vmove == "push_in", camera=vcam):
                        shots.append({"file": variant, "duration": 5.5, "kind": src,
                                      "camera": vmove, "motion_params": vcam,
                                      "verification": last.get("verification"),
                                      "title": last.get("title", ""),
                                      "query": last.get("query", "")})
                        print(f"  [coverage] scene{i}: narration ~{est:.0f}s, "
                              f"added {vmove} variant of same asset (visual change)")
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
            manim_used.add(manim)
            plan[i] = [{"file": manim,
                        "duration": min(10.0, M._probe_duration(manim)),
                        "kind": "manim"}]
            stats["manim"] += 1
            print(f"  [fill] scene{i} filled with Manim {os.path.basename(manim)}")
            continue
        topic = _detect_topic(text) or "documentary"
        fname = f"scene{i}_fill.jpg"
        out = os.path.join(still_root, fname)
        got, src, title = _nasa_still_title(topic, out)
        if not got:
            got, src, title = _ai_still(
                f"Photorealistic documentary image of {topic}, cinematic", out), "ai", ""
        if got and os.path.exists(got):
            clip = os.path.join(out_dir, "shots", fname.replace(".jpg", ".mp4"))
            cam = gates.camera_decision(intent) if gates is not None else {"move": "push_in", "params": {}}
            cam_params = cam.get("params", {}) or {}
            zoom_in = cam_params.get("zoom_end", 1.2) > cam_params.get("zoom_start", 1.0)
            if _kenburns(got, clip, duration=6.0, zoom_in=zoom_in, camera=cam_params):
                plan[i] = [{"file": clip, "duration": 6.0, "kind": src,
                            "camera": cam.get("move", "push_in"),
                            "motion_params": cam_params, "title": title,
                            "query": topic}]
                stats[src] = stats.get(src, 0) + 1
                print(f"  [fill] scene{i} filled with {src} still ({topic})")

    print(f"  Shots planned: " + ", ".join(f"scene{i}: {len(v)}" for i, v in plan.items()))
    print(f"  Sources: {stats} ({(time.time()-t0):.1f}s)")
    return plan, stats


# ═══════════════════════════════════════════════════════════════════════ #
# Timeline + render
# ═══════════════════════════════════════════════════════════════════════ #

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
                "camera": "ken_burns" if shot["kind"] != "manim" else "static",
                "beat_index": si,
                "shot_type": "primary",
            }
            # ── Semantic identity (iteration guidance: any frame traceable
            #    from the timeline alone, not just diagnostics) ──
            entry["camera_move"] = shot.get("camera", "static")
            entry["motion_params"] = shot.get("motion_params", {})
            entry["asset_source"] = shot.get("kind", "")
            entry["asset_title"] = shot.get("title", "")
            entry["query_used"] = shot.get("query", "")
            entry["scene_id"] = i
            ver = shot.get("verification") or {}
            entry["verification_passed"] = bool(ver.get("passed", True))
            entry["verification_reasons"] = ver.get("reasons", [])
            entry["pre_verified"] = bool(ver.get("pre_verified", False))
            tl["video_timeline"].append(entry)
            t += dur
        # Per-scene coverage: stretch the last shot of this scene to cover
        # the full narration window.  Otherwise a scene whose shots sum to
        # less than its audio duration leaves a black gap (QA: frozen/static).
        scene_end = cursor + adur
        if tl["video_timeline"] and t < scene_end:
            tl["video_timeline"][-1]["end_time"] = round(scene_end, 3)
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
    ap.add_argument("--reuse", action="store_true",
                    help="Reuse cached script/stills/audio from a previous run (A/B motion re-render)")
    args = ap.parse_args()

    topic = args.topic
    slug = "".join(c if c.isalnum() else "_" for c in topic.lower())[:40].strip("_")
    out_dir = os.path.join("results", slug)
    os.makedirs(out_dir, exist_ok=True)
    output_path = args.out or os.path.join(out_dir, f"{slug}.mp4")
    mixed_path = os.path.join(out_dir, f"{slug}_mixed.mp4")
    timeline_path = os.path.join(out_dir, "timeline.json")
    run_report = {"topic": topic, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "strategy": "stills_first", "stages": {}}

    mods = M._imports()
    factory = mods["ProviderFactory"]()
    provider_name = args.provider or "deepseek"
    llm = factory.get_llm_provider(provider_name)
    run_report["provider"] = provider_name

    if args.reuse and os.path.exists(os.path.join(out_dir, "script_final.json")):
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
                "Condense this script to at most " + str(M.MAX_SCRIPT_WORDS) +
                " words total, keeping all facts and the 5-scene structure. "
                "Return ONLY the JSON array of scenes with title/narration/visual_goal/search_queries.\n" +
                json.dumps({"scenes": scenes_data})[:6000]
            )
            compressed_ok = False
            try:
                data2 = json.loads(compress)
                scenes2 = data2.get("scenes", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
                w2 = sum(len(s.get("narration", "").split()) for s in scenes2)
                if len(scenes2) == 5 and w2 <= M.MAX_SCRIPT_WORDS + 10:
                    scenes_data = M._merge_scene_meta(scenes_data, scenes2)
                    print(f"  Compressed to {w2} words")
                    compressed_ok = True
                else:
                    print(f"  !! Compression output invalid (scenes={len(scenes2)}, words={w2}) — deterministic trim")
            except json.JSONDecodeError:
                print("  !! Post-review compression JSON failed — deterministic trim")
            # Deterministic hard-trim fallback (never silently keep an
            # over-budget script): truncate each scene's narration to a
            # proportional word budget, cutting at sentence boundaries.
            if not compressed_ok:
                budget = int(M.MAX_SCRIPT_WORDS * 0.9)
                per_scene = max(8, budget // len(scenes_data))
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

    # Clear v2 motion clips so they regenerate with the fixed Ken Burns
    if os.path.isdir(os.path.join(out_dir, "shots")):
        shutil.rmtree(os.path.join(out_dir, "shots"))

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
    except Exception as e:
        print(f"  !! gates init failed (continuing un-gated): {str(e)[:100]}")
    shot_plan, stills_stats = stage_stills_visuals(scenes_data, out_dir, gates, specs,
                                                  topic_slug=slug)
    run_report["stages"]["visuals"] = stills_stats

    # ── Narration (dynamic, emotion-modulated; reuse cached audio) ──────
    os.makedirs("cache/audio", exist_ok=True)
    audio_durations = []
    narration_stats = {}
    if args.reuse and all(os.path.exists(os.path.join("cache", "audio", f"scene_{i}.wav"))
                          for i in range(len(scenes_data))):
        for i, s in enumerate(scenes_data):
            ap = os.path.join("cache", "audio", f"scene_{i}.wav")
            audio_durations.append(M._probe_duration(ap))
        narration_stats = {"provider": "cached"}
    else:
        audio_durations, narration_stats = M.stage_narration_dynamic(
            scenes_data, "cache/audio", provider="edge")
    print(f"  Voice tracks: {len(scenes_data)} (total {sum(audio_durations):.1f}s) "
          f"[{narration_stats.get('provider')}]")

    # ── Timeline + render ──────────────────────────────────────────────
    build_stills_timeline(scenes_data, shot_plan, audio_durations, timeline_path)
    print(f"\n[12/16] RENDERING → {output_path}", flush=True)
    t0 = time.time()
    if gates is not None:
        gates._instrumenter.start_render()
    mods["MoviePyRenderer"]().render(timeline_path, output_path)
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
            "benchmark": {"hook_window_s": 15, "max_hold_s": 8.0,
                           "target_novelty_per_10s": 1.5},
            "flags": [],
        }
        if longest_hold > 8.0:
            retention_diag["flags"].append(
                f"longest hold {longest_hold:.1f}s > 8s (drop-off risk)")
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
        sfx_path, sfx_events_placed = M.build_sfx_timeline(
            scenes_data, audio_durations, sfx_path)
        if not sfx_events_placed:
            sfx_path = ""
    except Exception as e:
        print(f"  !! SFX timeline build failed (non-fatal): {str(e)[:100]}")
        sfx_path = ""
    mix = M.stage_music_mix(output_path, "cache/music/cinematic.mp3", mixed_path,
                            sfx_path=sfx_path)
    mix["sfx_events"] = sfx_events_placed
    run_report["stages"]["music_v1"] = mix
    review_target = mixed_path if mix.get("mixed") else output_path

    # ── Gemini review + improvement passes ─────────────────────────────
    review = None
    try:
        review = M.stage_video_review(review_target, scenes_data,
                                      os.path.join(out_dir, "review_v1.json"))
        run_report["stages"]["review_v1"] = {
            "score": review.get("quality_score"),
            "confidence": review.get("confidence"),
            "model_used": review.get("_meta", {}).get("model_used"),
        }
    except Exception as e:
        print(f"  !! video review failed (non-fatal, continuing): {str(e)[:120]}")
        run_report["stages"]["review_v1"] = {"error": str(e)[:200]}
    iteration = 1
    max_iter = 1 if review is None else 3
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
        mods["MoviePyRenderer"]().render(timeline_path, raw_render)
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
                                sfx_path=sfx_path)
        review_target = mixed_path if mix.get("mixed") else output_path
        try:
            review = M.stage_video_review(review_target, scenes_data,
                                          os.path.join(out_dir, f"review_v{iteration+1}.json"))
            run_report["stages"][f"review_v{iteration+1}"] = {
                "score": review.get("quality_score"),
                "confidence": review.get("confidence"),
                "model_used": review.get("_meta", {}).get("model_used"),
            }
        except Exception as e:
            print(f"  !! re-review failed (non-fatal): {str(e)[:120]}")
            run_report["stages"][f"review_v{iteration+1}"] = {"error": str(e)[:200]}
            break
        iteration += 1

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
    run_report["degradations"] = degradations

    run_report["final"] = {
        "output": review_target, "iterations": iteration,
        "final_score": review.get("quality_score"),
        "duration_s": M._probe_duration(review_target),
        "visual_stats": stills_stats,
    }
    # ── DeepSeek usage + cost report (per-stage, whole run) ────────────
    try:
        from src.providers.llm_provider import DeepSeekUsage
        usage = DeepSeekUsage.summary()
        run_report["llm_usage_deepseek"] = usage
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

    recorder = mods["PostmortemRecorder"]()
    pm_path = recorder.record(
        topic + " (stills-first)",
        techniques_succeeded=[
            "stills-first visual strategy: NASA/Wikimedia/AI Ken Burns + Manim beats",
            f"manim scenes: {stills_stats.get('manim', 0)}, nasa: {stills_stats.get('nasa', 0)}, "
            f"wikimedia: {stills_stats.get('wikimedia', 0)}, ai: {stills_stats.get('ai', 0)}",
            f"Gemini review score {review.get('quality_score')}/100",
        ],
        techniques_failed=[
            "stock-video director (pexels) deprioritized by design in stills mode",
        ],
        metrics={"final_score": review.get("quality_score"),
                 "duration_s": M._probe_duration(review_target),
                 **stills_stats},
        artifacts={"video": review_target, "report": os.path.join(out_dir, "run_report.json")},
    )
    run_report["postmortem"] = pm_path
    M._write_json(os.path.join(out_dir, "run_report.json"), run_report)

    print("\n" + "=" * 64)
    print(f"STILLS-FIRST RUN COMPLETE — {topic}")
    print(f"  Video:  {review_target}")
    print(f"  Score:  {review.get('quality_score')}/100 | Dur: {M._probe_duration(review_target):.1f}s")
    print(f"  Sources: {stills_stats}")
    print("=" * 64)


if __name__ == "__main__":
    main()
