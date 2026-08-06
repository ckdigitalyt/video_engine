#!/usr/bin/env python3
"""
mission_run.py — Jade Studio mission pipeline runner (v1.1).

Executes the 16-stage documentary production pipeline for a topic:

  research → fact verification → story development → script review →
  storyboard → visual planning → asset routing → asset generation →
  animation planning → narration → music → rendering → video review →
  improvement pass → final output → postmortem

v1.1 fixes (from v1 review):
  - Music bed + sidechain ducking via ffmpeg post-render mix (v1 had voice only)
  - Script duration budget (target ~60s, hard cap)
  - Gemini video review uses Part.from_uri (SDK fix)
  - Improvement pass actually mutates timeline.json and re-renders

Usage:
    ./venv/bin/python mission_run.py --topic "Voyager 1" \
        --out results/voyager/voyager_v1.mp4
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.providers.llm_provider import set_usage_stage, DeepSeekUsage
from src.providers.tts_provider import strip_paralinguistic_tags
from src.providers.tts_provider import CHATTERBOX_EMOTION_PARAMS  # noqa: E402 — module-level for _voice_params()

TARGET_DURATION_S = 60.0
MAX_SCRIPT_WORDS = 165
# Minimum narration words for the ~60s target (~150-165 wpm spoken).
# Scripts that come in well under this (e.g. a 106-word draft -> 37s video)
# are expanded once to hit the target runtime.
MIN_SCRIPT_WORDS = 140
# Scene count scales with target duration: 5 scenes per 60s.
SCENE_COUNT = 5


def set_target_duration(seconds: float):
    """Scale scene count + word budget with the requested runtime.
    Called by both runners (mission_run / mission_stills) so a 2-minute
    video gets ~10 scenes and a proportional narration word budget."""
    global TARGET_DURATION_S, MAX_SCRIPT_WORDS, MIN_SCRIPT_WORDS, SCENE_COUNT
    TARGET_DURATION_S = max(30.0, float(seconds))
    SCENE_COUNT = max(3, int(round(TARGET_DURATION_S / 12.0)))  # ~12s per scene
    MAX_SCRIPT_WORDS = int(TARGET_DURATION_S * 2.75)   # ~165 wpm
    MIN_SCRIPT_WORDS = int(TARGET_DURATION_S * 2.35)   # ~140 wpm
    print(f"[duration] target={TARGET_DURATION_S:.0f}s scenes={SCENE_COUNT} "
          f"words {MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS}")

# Metadata fields the script stage emits per scene (v8: emotion for vocal
# modulation, visual_style for the Jade imagery layer, sfx_events for the
# event-driven sound-design timeline).  Expansion/compression rewrites must
# preserve these — LLM rewrites only return title/narration/visual_goal/
# search_queries, so we merge the originals back in.
_SCENE_META_FIELDS = ("emotion", "visual_style", "sfx_events", "para_tags")


def _merge_scene_meta(original: list[dict], replacement: list[dict]) -> list[dict]:
    """Carry per-scene metadata from *original* onto *replacement* scenes
    (matched by index).  Keeps emotion/visual_style/sfx_events alive across
    LLM rewrite steps that only emit narration + search fields."""
    out = []
    for i, s in enumerate(replacement or []):
        s = dict(s)
        if i < len(original):
            for k in _SCENE_META_FIELDS:
                if k not in s or s.get(k) in (None, [], ""):
                    v = (original[i] or {}).get(k)
                    if v not in (None, [], ""):
                        s[k] = v
        out.append(s)
    return out

# ═══════════════════════════════════════════════════════════════════════ #
# Stage imports (lazy where heavy)
# ═══════════════════════════════════════════════════════════════════════ #

def _imports():
    global Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan, AudioPlan, MusicStyle, ProviderType
    global VisualDirector, MoviePyRenderer, TimelineBuilder, EditorialPlanner
    global VisualKnowledgeLibrary, analyze_vo_narration, generate_voice
    global ProviderFactory, ScriptReviewer, ImprovementPass, PostmortemRecorder

    from src.models.schemas import (
        Scene, SceneNarration, VisualPlan, SearchPlan, EditingPlan,
        AudioPlan, MusicStyle, ProviderType,
    )
    from src.director import VisualDirector
    from src.renderer.moviepy_renderer import MoviePyRenderer
    from src.renderer.timeline_builder import TimelineBuilder
    from src.planner.editorial_planner import EditorialPlanner
    from src.knowledge.visual_knowledge_library import VisualKnowledgeLibrary
    from src.cinematic.pace_profiler import analyze_vo_narration
    from audio_engine import generate_voice
    from src.providers.factory import ProviderFactory
    from src.review.script_review import ScriptReviewer
    from src.review.improvement_pass import ImprovementPass
    from src.memory.postmortem import PostmortemRecorder
    from src.providers.llm_provider import set_usage_stage, DeepSeekUsage

    return {
        "Scene": Scene, "SceneNarration": SceneNarration, "VisualPlan": VisualPlan,
        "SearchPlan": SearchPlan, "EditingPlan": EditingPlan, "AudioPlan": AudioPlan,
        "MusicStyle": MusicStyle, "ProviderType": ProviderType, "VisualDirector": VisualDirector,
        "MoviePyRenderer": MoviePyRenderer, "TimelineBuilder": TimelineBuilder,
        "EditorialPlanner": EditorialPlanner, "VisualKnowledgeLibrary": VisualKnowledgeLibrary,
        "analyze_vo_narration": analyze_vo_narration, "generate_voice": generate_voice,
        "ProviderFactory": ProviderFactory,
        "ScriptReviewer": ScriptReviewer, "ImprovementPass": ImprovementPass,
        "PostmortemRecorder": PostmortemRecorder,
    }


# ═══════════════════════════════════════════════════════════════════════ #
# Research stage
# ═══════════════════════════════════════════════════════════════════════ #

RESEARCH_PROMPT = """You are a documentary research lead. Produce a rigorous fact pack for a
one-minute documentary.

Requirements:
- 8-15 verified facts, each with: claim, value (number), unit, source (organisation, e.g. NASA/ESA/Wikipedia), year
- Include: key dates, key numbers, key people/missions, 1-2 controversies or common misconceptions
- Facts must be CURRENT as of 2026 and widely accepted
- No speculation, no invented numbers

Respond in STRICT JSON (no markdown):
{{
  "facts": [
    {{"claim": "...", "value": <number or null>, "unit": "...", "source": "...", "year": <int or null>, "confidence": <0-1>}}
  ],
  "hook_ideas": ["..."],
  "misconceptions": ["..."],
  "key_sources": ["..."]
}}

TOPIC: {topic}"""


def stage_research(topic: str, provider) -> dict:
    set_usage_stage("research")
    print("\n[1/16] RESEARCH", flush=True)
    t0 = time.time()
    raw = provider.generate_json(RESEARCH_PROMPT.format(topic=topic))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("  !! Research JSON parse failed — retrying once")
        raw = provider.generate_json(RESEARCH_PROMPT.format(topic=topic) + "\nReturn ONLY valid JSON.")
        data = json.loads(raw)
    data["_elapsed_s"] = round(time.time() - t0, 1)
    print(f"  {len(data.get('facts', []))} facts, {len(data.get('key_sources', []))} sources ({data['_elapsed_s']}s)")
    return data


def stage_fact_verification(research: dict, provider) -> dict:
    set_usage_stage("fact_verification")
    print("\n[2/16] FACT VERIFICATION", flush=True)
    t0 = time.time()
    facts = research.get("facts", [])
    if not facts:
        print("  No facts to verify.")
        return research
    check_prompt = """You are a fact-checker. Verify each claim independently. For each fact, respond with:
{{"fact": "<claim>", "verified": true/false, "notes": "<why>", "adjusted_confidence": <0-1>}}
STRICT JSON array only.

FACTS:
{facts}"""
    try:
        raw = provider.generate_json(check_prompt.format(facts=json.dumps(facts, indent=1)[:6000]))
        checks = _robust_json_array(raw)
        by_claim = {}
        for c in checks:
            if not isinstance(c, dict):
                continue
            claim_key = next((k for k in ("fact", "claim", "statement", "text") if c.get(k)), None)
            if claim_key:
                by_claim[str(c.get(claim_key, "")).strip().lower()] = c
        n_checked = 0
        for f in facts:
            c = by_claim.get(str(f.get("claim", "")).strip().lower())
            if c:
                n_checked += 1
                f["verified"] = bool(c.get("verified", False))
                f["verification_notes"] = c.get("notes", "")
                f["confidence"] = c.get("adjusted_confidence", f.get("confidence", 0.5))
        if n_checked == 0:
            raise ValueError("verification output did not match any claims")
        research["_verification_failed"] = False
    except Exception as e:
        # Never silently degrade: expose the failure, classify severity.
        research["_verification_failed"] = True
        research["_verification_error"] = str(e)[:200]
        research["_verification_severity"] = "warning"
        print(f"  !! Verification pass failed ({e}) — fallback confidence used. "
              f"[degradation exposed in run_report]")
        for f in facts:
            f["verified"] = f.get("confidence", 0.5) >= 0.7
    research["_verification_elapsed_s"] = round(time.time() - t0, 1)
    n_verified = sum(1 for f in facts if f.get("verified"))
    print(f"  Verified {n_verified}/{len(facts)} facts")
    return research


# ═══════════════════════════════════════════════════════════════════════ #
# Script development stage
# ═══════════════════════════════════════════════════════════════════════ #

SCRIPT_PROMPT = """You are a world-class documentary scriptwriter. Write a documentary script
of EXACTLY {SCENES} scenes for a video with a TOTAL spoken runtime of about
{TARGET} seconds ({MAX_WORDS} words maximum, spoken pace ~150 wpm).

Use the verified facts below — every number must come from them. Do NOT invent facts.

RETENTION RULES (2026 platform benchmarks — mobile-first, micro-window):
- MICRO-WINDOW HOOK: the single most striking fact or image must land within
  the first 3-5 SECONDS (Indian mobile market: 15s is too slow — the decision
  window is 3-5s). Start mid-action with a pattern interrupt. Never open with
  greetings, channel branding, or slow preamble ("Welcome back… today we will
  discuss…").
- HOOK-DELIVER CYCLE: each scene opens with a micro-hook (question, tension,
  contrast, stakes) then delivers value fast; no scene is a flat recital.
- OPEN LOOPS: scene 0 plants an open question/mystery; it must be answered
  only in a later scene, keeping viewers watching.
- RE-ENGAGEMENT MICRO-HOOKS (2026): plant explicit micro-hooks at ~25% and
  ~65% of the runtime (viewer fatigue milestones) — a fresh question or
  stakes beat that pulls attention back.
- MICRO-BEATS: every scene must be 3-5 seconds of screen time worth of
  ideas — no scene holds one idea longer than ~5s. Short punchy sentences
  (~30 words per scene). Visual holds of 3-5s per shot.
- PACING IS A QUALITY METRIC (v10): match delivery to content. Hook scene:
  energetic but still easy to follow. Explanatory/technical scenes: slower,
  shorter sentences, leave space after key facts, numbers, dates and units.
  Vary sentence rhythm — never a flat wall of equally-long sentences.
- CULTURAL TUNING: use high-context analogies and universally relatable
  metaphors; prefer direct, vivid imagery over abstract descriptors. Where
  natural for the niche, let sentence rhythm feel conversational and
  energetic (mobile-native pacing) — not academic.
- No filler, no repetition, no generic AI phrasing (no "delve", "unlock the
  secrets", "vast tapestry"). Memorable closing line.
- SEMANTIC PARITY: opening narration must mirror the video title/thumbnail
  promise exactly (no bait).

OUTPUT FORMAT: STRICT JSON with per-scene metadata the pipeline uses for
visual style, vocal emotion and sound design:
{{
  "scenes": [
    {{
      "title": "...",
      "narration": "...",
      "visual_goal": "<what the viewer should see>",
      "search_queries": ["3-5 stock search terms"],
      "emotion": "<wonder|tension|revelation|awe|nostalgia|hopeful|somber>",
      "visual_style": "<ghibli|hand_drawn|90s_anime|sepia_cel|watercolor|clean_vector|photorealistic>",
      "sfx_events": [{{"trigger": "<sound id>", "at": "<after: word/phrase from narration>"}}],
      "para_tags": ["<optional: [laugh] | [sigh] | [chuckle] | [gasp] | [whisper] — insert 0-2 organically>"]
    }}
  ]
}}
Use sfx_events sparingly (0-2 per scene) at true dramatic beats (launch,
impact, reveal, whoosh, heartbeat, sparkle, boom, riser). `at` must reference
a real phrase in that scene's narration.

PARALINGUISTIC TAGS (v9, for the expressive narrator): add 0-2 natural human
tags like [chuckle], [sigh], [laugh], [gasp] per scene where a real presenter
would react — never forced, never more than 2. Leave the array empty for
straightforward factual scenes. The tags are spoken by the narrator engine.

FACTS:
{facts}

TOPIC: {topic}"""


def stage_script(topic: str, research: dict, provider) -> list[dict]:
    set_usage_stage("script")
    print("\n[3/16] SCRIPT DEVELOPMENT", flush=True)
    t0 = time.time()
    facts_text = json.dumps(research.get("facts", []), indent=1)[:7000]
    prompt = SCRIPT_PROMPT.format(
        topic=topic, facts=facts_text,
        TARGET=int(TARGET_DURATION_S), MAX_WORDS=MAX_SCRIPT_WORDS,
        SCENES=SCENE_COUNT,
    )
    raw = provider.generate_json(prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("  !! Script JSON parse failed — retrying once")
        raw = provider.generate_json(prompt + "\nReturn ONLY valid JSON.")
        data = json.loads(raw)
    scenes = data.get("scenes", [])
    total_words = sum(len(s.get("narration", "").split()) for s in scenes)
    print(f"  {len(scenes)} scenes drafted, {total_words} words "
          f"(~{total_words * 0.4:.0f}s at 150wpm)")
    if total_words < MIN_SCRIPT_WORDS and len(scenes) == SCENE_COUNT:
        # Expand under-budget scripts once so the video hits the target
        # runtime instead of delivering a 35-40s short (reviewer feedback: pacing).
        print(f"  !! Under word budget ({total_words} < {MIN_SCRIPT_WORDS}) — expanding once")
        expand = provider.generate_json(
            "Expand this documentary script to at least " + str(MIN_SCRIPT_WORDS) +
            " words total (target ~" + str(MAX_SCRIPT_WORDS) + "), keeping all facts, "
            "the " + str(SCENE_COUNT) + "-scene structure and every search query. Add depth, not filler — "
            "one extra concrete detail or vivid sentence per scene. "
            "Return ONLY the JSON array of scenes with title/narration/visual_goal/search_queries.\n" +
            json.dumps({"scenes": scenes})[:6000]
        )
        try:
            data2 = json.loads(expand)
            scenes2 = data2.get("scenes", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
            w2 = sum(len(s.get("narration", "").split()) for s in scenes2)
            if len(scenes2) == SCENE_COUNT and w2 >= MIN_SCRIPT_WORDS and w2 <= MAX_SCRIPT_WORDS + 15:
                scenes = _merge_scene_meta(scenes, scenes2)
                total_words = w2
                print(f"  Expanded to {total_words} words (~{total_words * 0.4:.0f}s)")
        except json.JSONDecodeError:
            # Retry once with an explicit fence-stripping prompt (same
            # pattern as research/script stages).
            print("  !! Expansion JSON failed — retrying once")
            expand = provider.generate_json(
                "Return ONLY valid JSON (no markdown fences): the array of " +
                str(SCENE_COUNT) +
                " scenes with title/narration/visual_goal/search_queries, "
                "expanded to at least " + str(MIN_SCRIPT_WORDS) + " words total.\n" +
                json.dumps({"scenes": scenes})[:6000]
            )
            try:
                data2 = json.loads(expand)
                scenes2 = data2.get("scenes", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
                w2 = sum(len(s.get("narration", "").split()) for s in scenes2)
                if len(scenes2) == SCENE_COUNT and w2 >= MIN_SCRIPT_WORDS and w2 <= MAX_SCRIPT_WORDS + 15:
                    scenes = _merge_scene_meta(scenes, scenes2)
                    total_words = w2
                    print(f"  Expanded to {total_words} words (~{total_words * 0.4:.0f}s)")
            except json.JSONDecodeError:
                print("  !! Expansion JSON failed again — keeping draft")
    if total_words > MAX_SCRIPT_WORDS:
        print(f"  !! Over word budget ({total_words} > {MAX_SCRIPT_WORDS}) — compressing once")
        compress = provider.generate_json(
            "Condense this script to at most " + str(MAX_SCRIPT_WORDS) +
            " words total, keeping all facts and the " + str(SCENE_COUNT) + "-scene structure. "
            "Return ONLY the JSON array of scenes with title/narration/visual_goal/search_queries.\n" +
            json.dumps({"scenes": scenes})[:6000]
        )
        try:
            data2 = json.loads(compress)
            scenes2 = data2.get("scenes", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
            if len(scenes2) == SCENE_COUNT and sum(len(s.get("narration", "").split()) for s in scenes2) <= MAX_SCRIPT_WORDS + 10:
                scenes = _merge_scene_meta(scenes, scenes2)
                print(f"  Compressed to {sum(len(s.get('narration','').split()) for s in scenes)} words")
        except json.JSONDecodeError:
            print("  !! Compression failed — keeping draft")
    return scenes


# ═══════════════════════════════════════════════════════════════════════ #
# Script review stage (mission-critical)
# ═══════════════════════════════════════════════════════════════════════ #

def stage_script_review(scenes: list[dict], research: dict, provider_name: str) -> tuple[list[dict], dict]:
    set_usage_stage("script_review")
    from src.utils.config import get_config as _gc
    _personas = _gc("pipeline.script_review.personas",
                    ["fact_reviewer", "storytelling_reviewer"])
    _n_p = len(_personas) if isinstance(_personas, list) else 4
    _mp = _gc("pipeline.script_review.max_passes", 2)
    print(f"\n[4/16] SCRIPT REVIEW ({_n_p} reviewers, ≤{_mp} passes)", flush=True)
    t0 = time.time()
    reviewer = ScriptReviewer(provider_name=provider_name)
    narrations = [s["narration"] for s in scenes]
    final_narrations, results = reviewer.review(
        narrations,
        facts=research.get("facts", []),
        topic="",
    )
    for s, n in zip(scenes, final_narrations):
        s["narration"] = n
    report = {
        "passes": [
            {
                "pass": r.pass_number,
                "passed": r.passed,
                "scores": {k: v.score for k, v in r.scores.items()},
                "issue_counts": {
                    "critical": sum(1 for p in r.scores.values() for i in p.issues if i.severity == "critical"),
                    "major": sum(1 for p in r.scores.values() for i in p.issues if i.severity == "major"),
                    "minor": sum(1 for p in r.scores.values() for i in p.issues if i.severity == "minor"),
                },
            }
            for r in results
        ],
        "final_gate_passed": results[-1].passed if results else False,
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(f"  Gate passed: {report['final_gate_passed']} after {len(results)} pass(es) "
          f"(scores: {report['passes'][-1]['scores'] if report['passes'] else 'n/a'})")
    return scenes, report


# ═══════════════════════════════════════════════════════════════════════ #
# Storyboard + visual planning + asset routing (engine stages 5-9)
# ═══════════════════════════════════════════════════════════════════════ #

def stage_storyboard_and_direct(
    topic: str, scenes_data: list[dict], lib, ep, llm,
) -> tuple[list, dict]:
    set_usage_stage("storyboard_director")
    print("\n[5-9/16] STORYBOARD → VISUAL PLANNING → ASSET ROUTING → GENERATION → ANIMATION", flush=True)
    t0 = time.time()

    editorial_plans = ep.plan_all(
        scenes_with_narration=[
            {"scene_id": i, "title": s["title"], "narration": s["narration"]}
            for i, s in enumerate(scenes_data)
        ],
        topic=topic,
    )

    scenes = []
    for i, sd in enumerate(scenes_data):
        role = ("hook" if i == 0 else
                "climax" if i == len(scenes_data) - 2 else
                "conclusion" if i == len(scenes_data) - 1 else "exploration")
        profile = analyze_vo_narration(sd["narration"], narrative_role=role)
        visual_goal = ""
        if i < len(editorial_plans):
            visual_goal = editorial_plans[i].editorial_objective.visual_goal
        queries = sd.get("search_queries") or [visual_goal] or [f"{topic} {sd['title']}"]
        scene = Scene(
            scene_id=i, title=sd["title"],
            expected_duration=float(sd.get("duration", 13.0)),
            topic=topic,
            narration=SceneNarration(spoken_narration=sd["narration"]),
            visual_plan=VisualPlan(visual_description=visual_goal or f"Visuals for: {sd['title']}"),
            search_plan=SearchPlan(asset_search_queries=queries),
            editing_plan=EditingPlan(editing_instructions="cinematic documentary with varied pacing"),
            metadata={"title": sd["title"]},
        )
        scenes.append(scene)

    director = VisualDirector(use_beats=True, topic=topic, llm_provider=llm, scene_data=scenes)
    result_scenes = director.run()

    # ── Manim injection (v2): scale-comparison scenes get a Manim clip ──
    # Mission: Manim is first-class for scale comparisons / orbital mechanics.
    # If any scene's narration references distance/light-time, replace its
    # first primary shot's asset with the pre-rendered Manim clip.
    manim_clip = os.path.join("cache", "manim", "voyager_scale.mp4")
    if os.path.exists(manim_clip):
        for scene in result_scenes:
            text = (scene.narration.spoken_narration or "").lower()
            # Broad trigger set: any scene about distance/scale/light-time
            # (v3: v2's reviewed script didn't contain the v1 keywords)
            triggers = (
                "light-hour", "light hour", "22.9", "24 billion", "distance",
                "light-years away", "billion kilometers", "billion kilometres",
                "how far", "farthest", "far from earth", "reach earth",
                "hours to reach", "scale", "journey so far",
            )
            if any(k in text for k in triggers):
                for beat in (scene.beat_plans or []):
                    for shot in beat.shots:
                        if shot.shot_type.value == "primary" and shot.asset_plan:
                            shot.asset_plan.filepath = manim_clip
                            shot.asset_plan.provider = ProviderType.MANIM
                            shot.asset_plan.video_url = "manim://voyager_scale"
                            shot.asset_plan.query_used = "voyager distance light scale"
                            shot.asset_plan.score = 0.95
                            shot.motion = "none"  # animation is self-contained
                            shot.duration = min(9.0, max(shot.duration, 7.0))
                            print(f"  [Manim] Injected voyager_scale clip into scene {scene.scene_id} "
                                  f"({shot.duration:.1f}s)")
                            break
                    else:
                        continue
                    break

    provider_stats, fallback_count, total_shots = {}, 0, 0
    shot_durations, transitions_used, motions_used = [], {}, {}
    for scene in result_scenes:
        for beat in (scene.beat_plans or []):
            for shot in beat.shots:
                total_shots += 1
                shot_durations.append(shot.duration)
                transitions_used[shot.transition.value] = transitions_used.get(shot.transition.value, 0) + 1
                motions_used[shot.motion] = motions_used.get(shot.motion, 0) + 1
                if shot.asset_plan:
                    p = shot.asset_plan.provider.value
                    provider_stats[p] = provider_stats.get(p, 0) + 1
                    if p in ("placeholder", "emergency"):
                        fallback_count += 1

    stats = {
        "shots": total_shots,
        "avg_shot_s": round(sum(shot_durations) / len(shot_durations), 1) if shot_durations else 0,
        "providers": provider_stats,
        "fallbacks": fallback_count,
        "transitions": transitions_used,
        "motions": motions_used,
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(f"  Shots: {total_shots} | Avg {stats['avg_shot_s']}s | Providers: {provider_stats} | Fallbacks: {fallback_count}")
    return result_scenes, stats


# ═══════════════════════════════════════════════════════════════════════ #
# AI image generation (stage 8b) — NVIDIA NIM (benchmarked default)
# ═══════════════════════════════════════════════════════════════════════ #

AI_IMAGE_PROMPTS = {
    "spacecraft": (
        "Photorealistic documentary image of the Voyager 1 spacecraft, "
        "large dish antenna, golden record attached, deep interstellar "
        "space with faint stars, cinematic NASA style, high detail"
    ),
    "golden_record": (
        "Close-up of the Voyager Golden Record, gold-plated copper "
        "phonograph record with its cover and stylus, floating in space, "
        "cinematic lighting, photorealistic"
    ),
    "interstellar": (
        "Voyager 1 spacecraft receding into interstellar space, tiny "
        "silhouette against vast starfield, pale blue dot earth in distance, "
        "cinematic, photorealistic, documentary style"
    ),
}

# Unified style suffix appended to EVERY generated still.  Fixes the
# v12 review finding "inconsistent visual style / saturation varies":
# without a locked style token each provider call drifts.  The grade pass
# (stage_cinematic_grade) then unifies color further at render time.
_AI_STYLE_SUFFIX = (
    ", cinematic documentary still, consistent color palette, "
    "soft natural lighting, high detail, 16:9 composition"
)


def _still_to_kenburns(image_path: str, out_path: str, duration: float = 9.0) -> str:
    """Convert a still image to a Ken Burns motion clip (1920x1080@30)."""
    frames = int(duration * 30)
    vf = (
        f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
        f"zoompan=z='if(eq(on,1),1.0,min(1.25,zoom+0.004))':"
        f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={frames}:s=1920x1080:fps=30"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", image_path,
         "-vf", vf, "-c:v", "libx264", "-preset", "fast",
         "-t", str(duration), "-pix_fmt", "yuv420p", "-r", "30", out_path],
        capture_output=True, text=True, timeout=120,
    )
    return out_path if os.path.exists(out_path) else ""


def stage_ai_imagery(result_scenes, out_dir: str) -> dict:
    """Generate AI stills for scenes that need specific subject imagery
    (spacecraft, golden record) and inject them as Ken Burns clips.

    Uses the benchmarked default provider (NVIDIA NIM flux.1-dev).
    Cached in cache/generated — only generates once per prompt.
    """
    print("\n[8b/16] AI IMAGE GENERATION (NIM primary → Pollinations fallback)", flush=True)
    t0 = time.time()
    os.makedirs("cache/generated", exist_ok=True)
    from src.providers.image_gen import NvidiaNimProvider, PollinationsProvider

    prov = NvidiaNimProvider()
    fallback = PollinationsProvider()
    if not prov.is_available():
        print("  !! No NVIDIA_API_KEY — falling back to Pollinations only")
        prov = None

    def _gen(prompt: str, out_path: str) -> bool:
        """Try NIM, then Pollinations. Returns True on success."""
        attempts = []
        if prov is not None:
            attempts.append(("nim", prov))
        if fallback.is_available():
            attempts.append(("pollinations", fallback))
        for name, p in attempts:
            try:
                p.generate(prompt, out_path, width=1024, height=576)
                print(f"  [AI] {name}: generated {os.path.basename(out_path)} ({os.path.getsize(out_path)//1024} KB)")
                return True
            except Exception as e:
                print(f"  [AI] !! {name} failed: {str(e)[:90]}")
        return False

    generated, injected, sem_injected = 0, 0, 0
    for scene in result_scenes:
        text = (scene.narration.spoken_narration or "").lower()
        kind = None
        if any(k in text for k in ("golden record", "record", "disc", "sounds of earth")):
            kind = "golden_record"
        elif any(k in text for k in ("spacecraft", "probe", "antenna", "voyager", "machine")):
            kind = "spacecraft"
        elif any(k in text for k in ("interstellar", "leaving", "beyond", "void", "lonely")):
            kind = "interstellar"

        if kind:
            img_path = os.path.join("cache", "generated", f"ai_{kind}.png")
            if not os.path.exists(img_path):
                if _gen(AI_IMAGE_PROMPTS[kind] + _AI_STYLE_SUFFIX, img_path):
                    generated += 1
                else:
                    print(f"  [AI] !! {kind} generation failed on all providers")
                    continue

            clip_path = os.path.join("cache", "generated", f"ai_{kind}_kb.mp4")
            if not os.path.exists(clip_path):
                clip_path = _still_to_kenburns(img_path, clip_path, duration=9.0)
            if not clip_path:
                continue

            # Inject into the scene's last primary shot (replacing weak stock)
            for beat in (scene.beat_plans or []):
                for shot in beat.shots:
                    if shot.shot_type.value == "primary" and shot.asset_plan:
                        shot.asset_plan.filepath = clip_path
                        shot.asset_plan.provider = ProviderType.GENERATED
                        shot.asset_plan.video_url = f"ai://{kind}"
                        shot.asset_plan.query_used = f"ai_generated_{kind}"
                        shot.asset_plan.score = 0.9
                        shot.asset_plan.semantic_score = max(shot.asset_plan.semantic_score or 0.0, 0.9)
                        shot.motion = "none"
                        shot.duration = min(9.0, max(shot.duration, 6.0))
                        injected += 1
                        print(f"  [AI] injected {kind} into scene {scene.scene_id} ({shot.duration:.1f}s)")
                        break
                else:
                    continue
                break
            continue

        # ── Narration-driven semantic stills (v12.4) ──────────────────
        # Fixes the v12 review finding "generic bar chart used instead of
        # depicting the 1953 lab discovery": scenes whose best asset is
        # semantically weak / fell back to stock now get a scene-specific
        # AI still generated FROM THE NARRATION, so the visuals track the
        # script instead of a generic stock query.
        primary = None
        for beat in (scene.beat_plans or []):
            for shot in beat.shots:
                if shot.shot_type.value == "primary":
                    primary = shot
                    break
            if primary:
                break
        if not primary or not primary.asset_plan:
            continue
        sem = primary.asset_plan.semantic_score or primary.semantic_score or 0.0
        prov = primary.asset_plan.provider.value if primary.asset_plan.provider else ""
        weak = sem < 0.65 or prov in ("placeholder", "emergency", "stock")
        if not weak:
            continue
        # Build a prompt from the scene's actual narration + visual goal.
        visual_goal = ""
        if scene.visual_plan and scene.visual_plan.visual_description:
            visual_goal = scene.visual_plan.visual_description
        narration_snip = (scene.narration.spoken_narration or "")[:160].strip()
        prompt = (
            f"{visual_goal or ('A scene about: ' + narration_snip)}"
            + _AI_STYLE_SUFFIX
        )
        prompt_hash = abs(hash((prompt, scene.scene_id))) % 100000
        img_path = os.path.join("cache", "generated", f"ai_sem_{scene.scene_id}_{prompt_hash}.png")
        if not os.path.exists(img_path):
            if not _gen(prompt, img_path):
                print(f"  [AI] !! semantic still for scene {scene.scene_id} failed — keeping stock")
                continue
            generated += 1
        clip_path = os.path.join("cache", "generated", f"ai_sem_{scene.scene_id}_{prompt_hash}_kb.mp4")
        if not os.path.exists(clip_path):
            clip_path = _still_to_kenburns(img_path, clip_path, duration=9.0)
        if not clip_path:
            continue
        primary.asset_plan.filepath = clip_path
        primary.asset_plan.provider = ProviderType.GENERATED
        primary.asset_plan.video_url = f"ai://semantic_{scene.scene_id}"
        primary.asset_plan.query_used = f"ai_generated_semantic_{scene.scene_id}"
        primary.asset_plan.score = 0.9
        primary.asset_plan.semantic_score = 0.9
        primary.motion = "none"
        primary.duration = min(9.0, max(primary.duration, 6.0))
        sem_injected += 1
        print(f"  [AI] semantic still injected into scene {scene.scene_id} "
              f"(sem_score {sem:.2f} → 0.90, {primary.duration:.1f}s)")

    print(f"  Generated {generated}, injected {injected}, semantic-injected {sem_injected} "
          f"({(time.time()-t0):.1f}s)")
    return {"generated": generated, "injected": injected,
            "semantic_injected": sem_injected,
            "elapsed_s": round(time.time() - t0, 1)}


# ═══════════════════════════════════════════════════════════════════════ #
# Narration stage (10)
# ═══════════════════════════════════════════════════════════════════════ #

def stage_narration(result_scenes, cache_audio: str, voice_lock=None) -> dict:
    print("\n[10/16] NARRATION (Kokoro George)", flush=True)
    t0 = time.time()
    for scene in result_scenes:
        ap = os.path.join(cache_audio, f"scene_{scene.scene_id}.wav")
        generate_voice(scene.narration.spoken_narration, ap)
        if voice_lock is not None:
            voice_lock.record_scene(scene.scene_id, "kokoro", "bm_george")
        scene.audio_plan = AudioPlan(
            narration_audio_path=ap,
            music_style=MusicStyle.CINEMATIC,
            ducking_enabled=True,
            ducking_reduction_db=8.0,
        )
    if voice_lock is not None:
        voice_lock.save()
    print(f"  Voice tracks: {len(result_scenes)} ({round(time.time()-t0,1)}s)")
    return {"voice_scenes": len(result_scenes), "elapsed_s": round(time.time() - t0, 1)}


# ═══════════════════════════════════════════════════════════════════════ #
# Rendering (12) + music mix (11, post-render ffmpeg sidechain)
# ═══════════════════════════════════════════════════════════════════════ #

def _ensure_timeline_coverage(result_scenes, timeline_path: str) -> dict:
    """v12.4 coverage gate: every video_timeline entry MUST reference an
    existing file before render.  Missing entries (v12 review finding: black
    screen 0:26-0:35 because the renderer silently skipped absent shot files)
    are healed with a Ken Burns still generated from that scene's own visual
    description / narration.  If healing is impossible, the render is BLOCKED
    loudly instead of producing black frames.
    """
    if not os.path.exists(timeline_path):
        return {"missing": 0, "healed": 0, "blocked": "no timeline to check"}
    with open(timeline_path) as f:
        tl = json.load(f)
    vt = tl.get("video_timeline", [])
    at = tl.get("audio_timeline", [])
    missing = [e for e in vt if not e.get("file") or not os.path.exists(e.get("file", ""))]
    if not missing:
        return {"missing": 0, "healed": 0, "blocked": False}

    print(f"  [coverage] !! {len(missing)}/{len(vt)} video entries reference missing files — healing")

    # Scene spans from the audio timeline (ordered by scene).
    spans = sorted([(e.get("start_time", 0), e.get("end_time", 0))
                    for e in at if e.get("track") == "voice"])

    def _scene_for(t: float):
        for i, (s, e) in enumerate(spans):
            if s - 0.05 <= t < e + 0.05:
                return i if i < len(result_scenes) else None
        return None

    # Reusable image providers (same as stage_ai_imagery).
    from src.providers.image_gen import NvidiaNimProvider, PollinationsProvider
    prov = NvidiaNimProvider() if NvidiaNimProvider().is_available() else None
    fallback = PollinationsProvider()

    def _gen_still(prompt: str, out_path: str) -> bool:
        attempts = []
        if prov is not None:
            attempts.append(prov)
        if fallback.is_available():
            attempts.append(fallback)
        for p in attempts:
            try:
                p.generate(prompt, out_path, width=1024, height=576)
                if os.path.exists(out_path):
                    return True
            except Exception as e:
                print(f"    !! heal gen failed: {str(e)[:80]}")
        return False

    healed = 0
    os.makedirs("cache/generated", exist_ok=True)
    for entry in missing:
        sidx = _scene_for(entry.get("start_time", 0))
        scene = result_scenes[sidx] if sidx is not None else None
        # Prefer any valid asset already attached to this scene.
        valid = ""
        if scene is not None:
            for beat in (scene.beat_plans or []):
                for shot in beat.shots:
                    if shot.asset_plan and shot.asset_plan.filepath and \
                            os.path.exists(shot.asset_plan.filepath):
                        valid = shot.asset_plan.filepath
                        break
                if valid:
                    break
        if not valid and scene is not None:
            desc = ""
            if scene.visual_plan and scene.visual_plan.visual_description:
                desc = scene.visual_plan.visual_description
            if not desc:
                desc = (scene.narration.spoken_narration or "")[:140]
            if not desc:
                desc = scene.title
            h = abs(hash((desc, entry.get("start_time", 0)))) % 100000
            img = os.path.join("cache", "generated", f"cov_heal_{h}.png")
            if not os.path.exists(img) and not _gen_still(
                    desc + _AI_STYLE_SUFFIX, img):
                print(f"  [coverage] !! cannot heal missing asset at "
                      f"{entry.get('start_time', 0):.1f}s — provider unavailable")
                continue
            dur = max(3.0, min(entry.get("end_time", 0) - entry.get("start_time", 0), 9.0))
            clip = os.path.join("cache", "generated", f"cov_heal_{h}_kb.mp4")
            if not os.path.exists(clip):
                clip = _still_to_kenburns(img, clip, duration=dur)
            valid = clip if clip and os.path.exists(clip) else ""
        if valid:
            entry["file"] = valid
            entry["transition"] = "crossfade"
            entry["motion"] = "ken_burns_in"
            entry["shot_type"] = "coverage_heal"
            healed += 1
            print(f"  [coverage] healed entry at {entry.get('start_time', 0):.1f}s → {os.path.basename(valid)}")

    still_missing = [e for e in vt if not e.get("file") or not os.path.exists(e.get("file", ""))]
    blocked = False
    if still_missing:
        blocked = (
            f"{len(still_missing)} video entries still missing after heal "
            f"(times: {[round(e.get('start_time', 0), 1) for e in still_missing][:6]}) — "
            f"refusing to render black frames"
        )
        print(f"  [coverage] !! BLOCKED: {blocked}")

    if healed:
        with open(timeline_path, "w") as f:
            json.dump(tl, f, indent=2)
    return {"missing": len(missing), "healed": healed, "blocked": blocked}


def _build_subtitle_clips(result_scenes, timeline_path: str) -> list[dict]:
    """v12.4: generate burned-in word subtitles for the whole timeline.
    Fixes the v12 review finding 'add subtitles': the SubtitleEngine and
    renderer support existed but stage_render never generated or passed
    subtitle clips, so every video shipped without them.
    """
    from src.utils.config import get_config
    if not get_config("subtitles.enabled", True):
        return []
    if not os.path.exists(timeline_path):
        return []
    with open(timeline_path) as f:
        tl = json.load(f)
    # Scene start offsets from the audio timeline.
    starts = [e.get("start_time", 0) for e in tl.get("audio_timeline", [])
              if e.get("track") == "voice"]
    from src.subtitles.engine import SubtitleEngine
    engine = SubtitleEngine()
    all_clips: list[dict] = []
    for i, scene in enumerate(result_scenes):
        ap = scene.audio_plan
        if ap is None or not ap.narration_audio_path:
            continue
        text = scene.narration.spoken_narration if scene.narration else ""
        if not text.strip() or not os.path.exists(ap.narration_audio_path):
            continue
        try:
            timing = engine.generate(ap.narration_audio_path, text)
        except Exception as e:
            print(f"  [subs] !! scene {scene.scene_id} timing failed: {str(e)[:80]}")
            continue
        offset_ms = (starts[i] if i < len(starts) else 0.0) * 1000.0
        for clip in engine.to_renderer_clips(timing):
            clip["start_ms"] = clip.get("start_ms", 0) + offset_ms
            clip["end_ms"] = clip.get("end_ms", 0) + offset_ms
            all_clips.append(clip)
    if all_clips:
        print(f"  [subs] {len(all_clips)} subtitle clips ({len(result_scenes)} scenes)")
    return all_clips


def stage_render(result_scenes, timeline_path: str, output_path: str,
                 build_timeline: bool = True) -> dict:
    print(f"\n[12/16] RENDERING → {output_path}", flush=True)
    t0 = time.time()
    if build_timeline:
        TimelineBuilder().build_and_write(result_scenes, timeline_path)
    # v12.4: coverage gate — heal or block before rendering (no black frames).
    cov = _ensure_timeline_coverage(result_scenes, timeline_path)
    if cov.get("blocked"):
        raise RuntimeError(f"Coverage gate blocked render: {cov['blocked']}")
    subtitles = _build_subtitle_clips(result_scenes, timeline_path)
    MoviePyRenderer().render(timeline_path, output_path, subtitles=subtitles)
    size_mb = os.path.getsize(output_path) / 1e6 if os.path.exists(output_path) else 0
    dur = _probe_duration(output_path)
    print(f"  Rendered {dur:.1f}s, {size_mb:.1f} MB ({round(time.time()-t0,1)}s)")
    return {"duration_s": round(dur, 1), "size_mb": round(size_mb, 1),
            "render_s": round(time.time() - t0, 1), "output": output_path,
            "coverage": cov, "subtitle_clips": len(subtitles)}


def stage_cinematic_grade(video_path: str, out_path: str,
                          grain: int = 8, strength: float = 1.0) -> dict:
    """Organic texture pass (v8): simulate physical optics over the pristine
    AI render — fine film grain + subtle chromatic aberration + unified
    cinematic color grade.  Masks the synthetic 'too clean' look while
    keeping detail (grain is intentionally subtle; QA unaffected)."""
    print(f"  [grade] organic texture pass (grain={grain}, strength={strength})", flush=True)
    t0 = time.time()
    dur = _probe_duration(video_path)
    # noise: temporal+spatial film grain; rgbashift: chromatic aberration
    # CONSTRAINED TO THE PERIPHERY (§5.3, 2026 recalibration): the CA shift
    # is applied only outside the central 45%-radius circle (mobile-first
    # sharpness — text and subject focus stay crisp); eq/curves: cinematic
    # grade; vignette: lens falloff.
    vf = (
        f"noise=alls={grain}:allf=t+u,"
        f"split=2[base][ca];"
        f"[ca]rgbashift=rh=3:bh=-3[ca2];"
        f"[base][ca2]blend=all_expr='if(lte(hypot(X-W/2,Y-H/2),H*0.45),A,B)'[sharp];"
        f"[sharp]eq=contrast={1.0 + 0.04 * strength}:saturation={1.0 + 0.06 * strength}:"
        f"brightness={0.01 * strength},"
        f"vignette=PI/5[out]"
    )
    cmd = ["ffmpeg", "-y", "-i", video_path, "-filter_complex", vf,
           "-map", "[out]",
           # Preserve the master's audio stream — mapping only [out] drops
           # it, and the later music-mix stage then fails with
           # "matches no streams" on [0:a] (graded master had NO audio).
           "-map", "0:a?",
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-c:a", "copy", "-movflags", "+faststart", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out_path):
        print(f"  !! grade pass failed: {r.stderr[-300:]}")
        return {"graded": False, "reason": r.stderr[-200:]}
    print(f"  Graded {_probe_duration(out_path):.1f}s ({round(time.time()-t0,1)}s)")
    return {"graded": True, "grain": grain, "elapsed_s": round(time.time() - t0, 1),
            "size_mb": round(os.path.getsize(out_path) / 1e6, 1)}


def _synth_bed(duration: float, out_path: str, seed: int = 7,
               scenes: list | None = None,
               audio_durations: list | None = None) -> str:
    """Synthesize an audible ambient pad bed (fallback when the configured
    music file is dead/silent).  Layered detuned sines + slow tremolo +
    faint pink noise — clearly audible, no silence risk.

    §4.2 (2026 recalibration): the bed now EVOLVES with the narrative arc —
    per-scene volume automation driven by emotion metadata (tension/somber
    pull the bed down so the viewer leans in; revelation/climax push it up
    on payoff), plus a subtle high-BPM percussive pulse layer beneath the
    pad (Indian short-form energy, low enough to never compete with voice)."""
    import random
    rnd = random.Random(seed)
    freqs = [110.0, 164.81, 220.0, 277.18]  # A2 E3 A3 C#4 (A major-ish pad)
    parts = []
    for i, f in enumerate(freqs):
        detune = 1.0 + rnd.uniform(-0.004, 0.004)
        parts.append(
            f"sine=frequency={f * detune:.2f}:duration={duration:.2f}:sample_rate=44100"
        )
    # one lowpass-filtered pink noise layer for warmth
    noise = (
        f"anoisesrc=color=pink:duration={duration:.2f}:sample_rate=44100:amplitude=0.06,"
        f"lowpass=f=500,volume=0.35"
    )
    # §4.2: rhythmic pulse layer — 55 Hz thump gated at ~120 BPM, very quiet
    pulse = f"sine=frequency=55:duration={duration:.2f}:sample_rate=44100"
    # NOTE: this ffmpeg build rejects a `+`-joined multi-source lavfi input
    # ("Error opening input file") — use one -f lavfi -i per source instead.
    cmd = ["ffmpeg", "-y"]
    for f in freqs:
        cmd += ["-f", "lavfi", "-i",
                f"sine=frequency={f:.2f}:duration={duration:.2f}:sample_rate=44100"]
    cmd += ["-f", "lavfi", "-i", noise]
    cmd += ["-f", "lavfi", "-i", pulse]
    n_sines = len(freqs)  # inputs: 0..n_sines-1 = pad sines, n = noise, n+1 = pulse
    # Emotion -> bed intensity (1.0 = neutral).  Tension/somber duck the bed
    # (auditory vacuum, viewer leans in); revelation/awe/climax surge it.
    _EMO_GAIN = {"wonder": 1.0, "awe": 1.1, "revelation": 1.15,
                 "tension": 0.82, "climax": 1.2, "hopeful": 1.0,
                 "nostalgia": 0.9, "somber": 0.78, "default": 1.0}
    automation = ""
    if scenes:
        cursor = 0.0
        clauses = []
        for i, sc in enumerate(scenes):
            d = (audio_durations or [])[i] if i < len(audio_durations or []) else 5.0
            g = _EMO_GAIN.get((sc.get("emotion") or "default").strip().lower(), 1.0)
            clauses.append(f"between(t,{cursor:.2f},{cursor + d:.2f})*{g:.2f}")
            cursor += d
        if clauses:
            expr = "+".join(clauses)
            automation = f",volume=volume='{expr}':eval=frame"
    pad_in = "".join(f"[{i}:a]" for i in range(n_sines))
    graph = (
        f"{pad_in}amix=inputs={n_sines}:normalize=0,volume=0.35[pad];"
        f"[pad][{n_sines}:a]amix=inputs=2:normalize=0[pad_n];"
        f"[{n_sines + 1}:a]tremolo=f=2.0:d=1.0,volume=0.10[pulse_g];"
        f"[pad_n][pulse_g]amix=inputs=2:normalize=0{automation},"
        "tremolo=f=0.15:d=0.7,afade=t=in:d=2,afade=t=out:st="
        f"{max(0.0, duration - 3):.2f}:d=3[aout]"
    )
    cmd += ["-filter_complex", graph, "-map", "[aout]", "-c:a", "pcm_s16le", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(out_path):
        print(f"  !! synth bed generation failed: {r.stderr[-300:]}")
        return ""
    return out_path


def _synth_pulsar_sfx(duration: float, out_path: str, period_s: float = 1.337) -> str:
    """Synthesize a pulsar 'heartbeat' SFX track: rhythmic radio blips at
    the classic PSR B1919+21 cadence (~1.337 s), with a soft static bed.
    This is the thematic SFX layer reviewers asked for (ambient effects,
    not just voice + music).  Output is a quiet WAV to be ducked under
    narration."""
    import math
    import random
    import array
    import wave
    sr = 44100
    n = int(duration * sr)
    samples = [0.0] * n
    rnd = random.Random(42)
    for i in range(n):
        samples[i] = rnd.uniform(-1, 1) * 0.006
    blip_dur = 0.09
    blip_freq = 1215.0  # radio-ish tone
    t0 = 0.3
    while t0 < duration:
        start = int(t0 * sr)
        for j in range(int(blip_dur * sr)):
            idx = start + j
            if idx >= n:
                break
            env = math.exp(-j / (0.028 * sr)) * 0.5
            samples[idx] += math.sin(2 * math.pi * blip_freq * j / sr) * env * 0.22
        t0 += period_s
    peak = max(1e-9, max(abs(s) for s in samples))
    scale = 0.7 / peak
    buf = array.array("h", (int(max(-1.0, min(1.0, s * scale)) * 32767) for s in samples))
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())
    return out_path


def _check_bed_audible(bed_path: str, min_mean_db: float = -40.0) -> bool:
    """Return True if the music bed has real audible content."""
    import re as _re
    probe = subprocess.run(
        ["ffmpeg", "-i", bed_path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    m = _re.search(r"mean_volume: ([-.\d]+) dB", probe.stderr)
    mean_db = float(m.group(1)) if m else -99.0
    return mean_db > min_mean_db


# ═══════════════════════════════════════════════════════════════════════ #
# Event-driven sound design (v8)
# ═══════════════════════════════════════════════════════════════════════ #
# The script stage now emits `sfx_events` per scene (trigger + "at" phrase).
# This stage synthesizes a localized SFX library (no external assets, works
# offline on CPU) and splices hits at timestamps derived from narration
# timing.  Combined with the voice-EQ + refined-ducking mix below this
# replaces the old "single voice + looping bed" monotony.

_SFX_SYNTH_PARAMS = {
    "whoosh":    {"kind": "noise_sweep", "f0": 300, "f1": 3800, "dur": 0.7, "gain": 0.30},
    "boom":      {"kind": "impact",     "f0": 70,  "f1": 45,   "dur": 1.6, "gain": 0.42},
    "impact":    {"kind": "impact",     "f0": 120, "f1": 60,   "dur": 0.9, "gain": 0.35},
    "sparkle":   {"kind": "sparkle",    "f0": 2600, "f1": 4200, "dur": 1.1, "gain": 0.16},
    "riser":     {"kind": "riser",      "f0": 200, "f1": 2400, "dur": 1.6, "gain": 0.22},
    "tick":      {"kind": "tick",       "f0": 1800, "f1": 1800, "dur": 0.08, "gain": 0.30},
    "heartbeat": {"kind": "heartbeat",  "f0": 65,  "f1": 50,   "dur": 1.2, "gain": 0.30},
    "launch":    {"kind": "launch",     "f0": 40,  "f1": 120,  "dur": 3.0, "gain": 0.38},
    "reveal":    {"kind": "riser",      "f0": 300, "f1": 3200, "dur": 2.2, "gain": 0.26},
    "drone":     {"kind": "drone",      "f0": 55,  "f1": 55,   "dur": 2.0, "gain": 0.18},
}


def _synth_sfx_event(trigger: str, duration: float = None, sr: int = 44100) -> tuple[list, float]:
    """Synthesize one SFX hit as (samples, sr).  Deterministic, offline,
    CPU-only.  Unrecognized triggers fall back to a neutral tick."""
    import math
    import random
    p = _SFX_SYNTH_PARAMS.get(trigger, _SFX_SYNTH_PARAMS["tick"])
    d = p["dur"] if duration is None else min(duration, p["dur"] + 0.5)
    n = int(d * sr)
    kind = p["kind"]
    rnd = random.Random(hash(trigger) & 0xFFFF)
    out = [0.0] * n
    f0, f1 = p["f0"], p["f1"]

    if kind == "noise_sweep":
        # band-passed noise with rising center frequency
        for i in range(n):
            t = i / sr
            f = f0 + (f1 - f0) * (i / n)
            phase = 2 * math.pi * f * t
            out[i] = (rnd.uniform(-1, 1) * 0.6 + 0.4 * math.sin(phase)) * math.sin(math.pi * i / n)
    elif kind == "impact":
        for i in range(n):
            t = i / sr
            f = f0 + (f1 - f0) * (i / n)
            env = math.exp(-4.5 * i / n)
            out[i] = (math.sin(2 * math.pi * f * t) * 0.7 + rnd.uniform(-1, 1) * 0.3) * env
    elif kind == "sparkle":
        for i in range(n):
            t = i / sr
            env = math.exp(-2.2 * i / n)
            out[i] = (math.sin(2 * math.pi * f0 * t) * 0.5 +
                      math.sin(2 * math.pi * f1 * t) * 0.3) * env * (0.6 + 0.4 * math.sin(2 * math.pi * 6 * t))
    elif kind == "riser":
        for i in range(n):
            t = i / sr
            f = f0 + (f1 - f0) * (i / n) ** 2
            env = (i / n) ** 1.5
            out[i] = math.sin(2 * math.pi * f * t) * env
    elif kind == "tick":
        for i in range(n):
            env = math.exp(-14 * i / n)
            out[i] = math.sin(2 * math.pi * f0 * i / sr) * env
    elif kind == "heartbeat":
        # lub-dub double thump
        for i in range(n):
            t = i / sr
            env = math.exp(-10 * ((t % 0.55) / 0.55)) if (t % 0.55) < 0.55 else 0
            out[i] = math.sin(2 * math.pi * f0 * t) * env * (1.2 if (t % 0.55) < 0.2 else 0.7)
    elif kind == "launch":
        for i in range(n):
            t = i / sr
            f = f0 + (f1 - f0) * (i / n)
            env = 0.35 + 0.65 * (i / n)
            out[i] = (math.sin(2 * math.pi * f * t) * 0.6 + rnd.uniform(-1, 1) * 0.4) * env * math.exp(-0.3 * i / n)
    elif kind == "drone":
        for i in range(n):
            t = i / sr
            out[i] = (math.sin(2 * math.pi * f0 * t) * 0.7 +
                      math.sin(2 * math.pi * f0 * 1.5 * t) * 0.3) * 0.8
    else:
        for i in range(n):
            out[i] = math.sin(2 * math.pi * f0 * i / sr) * math.exp(-10 * i / n)

    gain = p["gain"]
    # 8ms fade in/out to avoid clicks
    fade = int(0.008 * sr)
    for i in range(min(fade, n)):
        out[i] *= i / fade
        out[n - 1 - i] *= i / fade
    return [s * gain for s in out], sr


def build_sfx_timeline(scenes: list[dict], audio_durations: list[float],
                       out_path: str,
                       cut_times: dict | None = None) -> tuple[str, list[dict]]:
    """Place scripted SFX events onto a timeline by matching each event's
    `at` phrase to its word position within the scene narration.

    §4.1 (2026 recalibration): when `cut_times` (dict scene_id -> list of
    ABSOLUTE visual cut seconds from timeline.json) is provided, events are
    snapped to the nearest visual cut — SFX become spatial/temporal anchors
    for visual state changes, never punctuation for text.  Falls back to
    phrase-fraction placement when no cut times exist.

    Returns (wav_path, events_placed) where events_placed is a list of
    {scene, trigger, at_s} for the run report."""
    import wave
    import array as _array
    sr = 44100
    total = max(0.5, sum(audio_durations))
    n = int(total * sr)
    bed = [0.0] * n
    events_placed = []
    cursor = 0.0
    for i, sc in enumerate(scenes):
        dur = audio_durations[i] if i < len(audio_durations) else 5.0
        words = (sc.get("narration") or "").split()
        scene_cuts = sorted((cut_times or {}).get(i, []))
        for ev in (sc.get("sfx_events") or [])[:2]:
            trig = (ev.get("trigger") or "tick").strip().lower()
            at = (ev.get("at") or "").lower()
            # map phrase -> fractional position in narration
            frac = 0.5
            if at and words:
                atw = [w for w in at.replace("after", "").replace(":", "").split() if w]
                if atw:
                    joined = " ".join(words).lower()
                    idx = joined.find(" ".join(atw[:3]).lower())
                    if idx >= 0:
                        frac = min(0.92, max(0.05, idx / max(1, len(joined))))
            t_at = cursor + frac * dur
            # §4.1: snap to nearest visual cut when the timeline is known
            if scene_cuts:
                in_scene = [c for c in scene_cuts if cursor - 0.25 <= c <= cursor + dur + 0.25]
                if in_scene:
                    t_at = min(in_scene, key=lambda c: abs(c - t_at))
            samples, _ = _synth_sfx_event(trig)
            start = int(t_at * sr)
            for j, s in enumerate(samples):
                k = start + j
                if 0 <= k < n:
                    bed[k] += s
            events_placed.append({"scene": i, "trigger": trig,
                                  "at_s": round(t_at, 2)})
        cursor += dur
    # normalize to avoid clipping
    peak = max(1e-9, max(abs(s) for s in bed))
    scale = min(1.0, 0.85 / peak) if peak > 0.85 else 1.0
    buf = _array.array("h", (int(max(-1.0, min(1.0, s * scale)) * 32767) for s in bed))
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())
    return out_path, events_placed


def stage_narration_dynamic(scenes: list[dict], cache_audio: str,
                            provider: str = "edge",
                            voice_lock=None) -> tuple[list[float], dict]:
    """Dynamic narration: sentence-level rate/pitch modulation by scene
    emotion (edge-tts supports per-sentence rate/pitch), falling back to
    flat Kokoro when edge is unavailable.  Returns (durations, stats).

    v8: replaces the flat single-call TTS so delivery isn't monotone.
    v9 (Jade spec §1): every scene is voiced with the LOCKED narrator
    (voice_lock); any fallback to a different engine/voice is recorded as
    an EXPLICIT override on the lock (never silent) so the pre-render QA
    gate can reject voice switching."""
    import re as _re
    os.makedirs(cache_audio, exist_ok=True)
    durations = []
    stats = {"provider": provider, "modulated_sentences": 0, "fallbacks": 0,
             "emotion_params": {}}
    # Locked narrator identity (single voice per episode).
    locked_voice = "en-US-ChristopherNeural"  # Edge default (matches lock)
    if voice_lock is not None:
        locked_voice = voice_lock.voice_id
    _EMO_RATE = {"wonder": "+8%", "tension": "+4%", "revelation": "+10%",
                 "awe": "+6%", "nostalgia": "-4%", "hopeful": "+4%",
                 "somber": "-8%"}
    _EMO_PITCH = {"wonder": "+2Hz", "tension": "-1Hz", "revelation": "+4Hz",
                  "awe": "+3Hz", "nostalgia": "-2Hz", "hopeful": "+1Hz",
                  "somber": "-4Hz"}

    def _sentences(text: str) -> list[str]:
        parts = _re.split(r"(?<=[.!?])\s+", (text or "").strip())
        return [p for p in parts if p.strip()]

    # One Chatterbox model for the whole run (loaded once, reused across
    # scenes — CPU load ~17s once, not per scene).  Falls back to edge on
    # any failure; provider switch is recorded on the voice lock.
    cb = None
    if provider == "chatterbox":
        try:
            from src.providers.tts_provider import (
                ChatterboxProvider,
                CHATTERBOX_EMOTION_PARAMS,
            )
            cb = ChatterboxProvider()
        except Exception as e:  # noqa: BLE001
            print(f"  !! chatterbox init failed ({str(e)[:80]}) — edge fallback")
            provider = "edge"
            stats["provider"] = "edge"

    for i, sc in enumerate(scenes):
        ap = os.path.join(cache_audio, f"scene_{i}.wav")
        emo = (sc.get("emotion") or "wonder").strip().lower()
        role = _role_for_scene(i, len(scenes), sc.get("narration"))
        sents = _sentences(sc.get("narration"))
        # Chatterbox speaks the scripted paralinguistic tags; edge/kokoro
        # must NEVER see them (they would read "[chuckle]" literally).
        sents_clean = [strip_paralinguistic_tags(s) for s in sents]
        # ── Chatterbox (primary, per expert doc §1.3) ──────────────
        # Whole-scene semantic chunk (NOT sentence-by-sentence — the
        # root cause of the old prosody/fallback bug, expert §1.2);
        # emotion + role drive exaggeration/cfg_weight (v10 rec 2:
        # adaptive dynamics — hook energetic, explanation clear/slower);
        # paralinguistic tags ([chuckle], [sigh]...) pass through natively.
        # v9.1: ONE ChatterboxProvider for the whole run (model stays
        # loaded across scenes — no 17s reload per scene).
        if provider == "chatterbox":
            try:
                ex, cfg = _voice_params(emo, role)
                # Inject the scriptwriter's organic tags at natural
                # sentence boundaries (expert doc §1.3).
                tagged = _inject_para_tags(
                    sc.get("narration"), sc.get("para_tags") or [])
                # v10 (rec 1/3): language-aware pauses before TTS so
                # technical scenes breathe — space after key facts.
                from src.utils.tts_normalize import apply_pacing_pauses
                pause_density = {
                    "hook": "light", "exploration": "medium",
                    "explanation": "heavy", "climax": "medium",
                    "conclusion": "heavy",
                }.get(role, "medium")
                tagged = apply_pacing_pauses(tagged, pause_density)
                # Optional voice cloning (2026): a reference clip at
                # voices.chatterbox.audio_prompt clones that voice's timbre
                # + pacing for every scene (None = built-in default voice).
                from src.utils.config import get_config
                audio_prompt = get_config("voices.chatterbox.audio_prompt", None)
                cb.generate_voice(tagged, ap, exaggeration=ex, cfg_weight=cfg,
                                  audio_prompt=audio_prompt)
                stats["provider"] = "chatterbox"
                stats["emotion_params"][f"{emo}/{role}"] = (ex, cfg)
                stats["para_tags_used"] = stats.get("para_tags_used", 0) + \
                    len(sc.get("para_tags") or [])
                if voice_lock is not None:
                    voice_lock.record_scene(i, "chatterbox",
                                            get_config("voices.chatterbox.voice_id",
                                                       "kurzgesagt_like"))
                if audio_prompt:
                    stats["cloned_voice"] = os.path.basename(audio_prompt)
            except Exception as e:  # noqa: BLE001
                print(f"  !! chatterbox failed for scene {i} ({str(e)[:80]}) — edge fallback")
                stats["fallbacks"] += 1
                provider = "edge"
                _edge_gen(i, ap, sents_clean, emo, voice_lock, stats, cache_audio)
            durations.append(_probe_duration(ap) if os.path.exists(ap) else 5.0)
            continue
        if provider == "edge":
            _edge_gen(i, ap, sents_clean, emo, voice_lock, stats, cache_audio)
        else:
            from audio_engine import generate_voice
            generate_voice(strip_paralinguistic_tags(sc.get("narration")), ap)
            stats["provider"] = "kokoro"
            if voice_lock is not None:
                voice_lock.record_scene(i, "kokoro", "bm_george")
        durations.append(_probe_duration(ap) if os.path.exists(ap) else 5.0)
    if cb is not None:
        try:
            cb.shutdown()
        except Exception:
            pass
    if voice_lock is not None:
        voice_lock.save()
    return durations, stats


def _role_for_scene(i: int, total: int, text: str) -> str:
    """Assign a pacing role per scene position + content (v10, rec 1/2).
    Scene 0 is the hook; the finale is the conclusion; dense technical
    scenes become 'explanation' (slower, clearer); the rest explore."""
    if total <= 1:
        return "default"
    if i == 0:
        return "hook"
    if i == total - 1:
        return "conclusion"
    if i == total - 2:
        return "climax"
    from src.cinematic.pacing_engine import technical_density
    if technical_density(text or "") > 0.5:
        return "explanation"
    return "exploration"


def _voice_params(emo: str, role: str) -> tuple[float, float]:
    """Blend emotion + role into (exaggeration, cfg_weight) for the calm
    documentary profile (channel direction 2026-08-05): warm-authoritative,
    measured.  Exaggeration stays in the 0.34-0.50 band and cfg_weight in
    the 0.28-0.42 band — hook gets a hair more energy, explanation/
    conclusion settle slightly for clarity; never theatrical."""
    ex, cfg = CHATTERBOX_EMOTION_PARAMS.get(emo, CHATTERBOX_EMOTION_PARAMS["default"])
    if role == "hook":
        ex = min(0.50, ex + 0.04)
        cfg = max(0.28, cfg - 0.03)
    elif role == "explanation":
        ex = max(0.34, ex - 0.04)
        cfg = min(0.42, cfg + 0.03)
    elif role == "conclusion":
        ex = max(0.34, ex - 0.02)
        cfg = min(0.42, cfg + 0.02)
    elif role == "climax":
        ex = min(0.48, ex + 0.03)
    return round(ex, 2), round(cfg, 2)


def _inject_para_tags(text: str, tags: list) -> str:
    """Insert scripted paralinguistic tags at natural sentence boundaries.
    Tags alternate between the first and last sentence so delivery feels
    organic, never mechanical.  Unknown/empty tags are ignored."""
    import re as _re
    tags = [t.strip() for t in (tags or []) if isinstance(t, str) and t.strip()]
    if not tags or not text:
        return text
    sents = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", (text or "").strip())
             if s.strip()]
    if not sents:
        return text
    out = list(sents)
    for idx, tag in enumerate(tags):
        if not _re.fullmatch(r"\[[A-Za-z ]+\]", tag):
            continue
        if idx % 2 == 0 and len(out) > 1:
            out[0] = f"{out[0]} {tag}"
        elif len(out) > 1:
            out[-1] = f"{tag} {out[-1]}"
        else:
            out[0] = f"{out[0]} {tag}"
    return " ".join(out)


def _edge_gen(i, ap, sents, emo, voice_lock, stats, cache_audio):
    """Edge TTS per-sentence emotion-modulated generation (v8 path)."""
    import asyncio
    import edge_tts
    import os
    _EMO_RATE = {"wonder": "+8%", "tension": "+4%", "revelation": "+10%",
                 "awe": "+6%", "nostalgia": "-4%", "hopeful": "+4%",
                 "somber": "-8%"}
    _EMO_PITCH = {"wonder": "+2Hz", "tension": "-1Hz", "revelation": "+4Hz",
                  "awe": "+3Hz", "nostalgia": "-2Hz", "hopeful": "+1Hz",
                  "somber": "-4Hz"}
    rate = _EMO_RATE.get(emo, "+0%")
    pitch = _EMO_PITCH.get(emo, "+0Hz")
    locked_voice = voice_lock.voice_id if voice_lock is not None \
        else "en-US-ChristopherNeural"
    # v12: the locked voice is a Chatterbox identity ("kurzgesagt_like"),
    # NOT a valid edge-tts voice — the fallback chain must never feed it
    # to edge (would raise "Invalid voice" and cascade to Kokoro, which
    # then trips the voice_switching gate).  Map to a real edge voice.
    if not locked_voice.startswith("en-") or locked_voice == "kurzgesagt_like":
        locked_voice = "en-US-ChristopherNeural"

    async def _gen():
        chunks = []
        for s in sents:
            comm = edge_tts.Communicate(s, locked_voice, rate=rate, pitch=pitch)
            tmp = ap + f".{len(chunks)}.mp3"
            await comm.save(tmp)
            chunks.append(tmp)
        lst = os.path.join(cache_audio, f"scene_{i}.lst")
        with open(lst, "w") as f:
            for c in chunks:
                f.write(f"file '{os.path.abspath(c)}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", lst, "-ar", "44100", "-ac", "2",
             "-c:a", "pcm_s16le", ap],
            capture_output=True, text=True, timeout=120)
        for c in chunks:
            if os.path.exists(c):
                os.remove(c)
        if os.path.exists(lst):
            os.remove(lst)

    try:
        asyncio.run(_gen())
        stats["modulated_sentences"] += len(sents)
        if voice_lock is not None:
            voice_lock.record_scene(i, "edge", locked_voice)
    except Exception as e:  # noqa: BLE001
        print(f"  !! edge narration failed for scene {i} ({str(e)[:80]}) — Kokoro fallback")
        stats["fallbacks"] += 1
        from audio_engine import generate_voice
        generate_voice(" ".join(sents), ap)
        stats["provider"] = "kokoro"
        if voice_lock is not None:
            voice_lock.record_scene(i, "kokoro", "bm_george",
                                    override=True, reason=str(e)[:60])


def stage_music_mix(video_path: str, music_path: str, out_path: str,
                    music_volume_db: float = -6.0, sfx_path: str = "",
                    scenes: list | None = None,
                    audio_durations: list | None = None) -> dict:
    """Stage 11: mix a music bed + optional SFX under narration with
    sidechain ducking.

    Fixes (v7):
      - silent music bed detection (dead mp3 -> synth ambient pad)
      - optional thematic SFX layer (pulsar heartbeat blips) as a 3rd track
      - amix normalize=0 (was halving the voice, making audio near-inaudible)
      - loudnorm to streaming standard (-14 LUFS, TP -1.5 dB)
      - post-mix verification that the bed is actually audible

    2026 (§4.2): the synth bed fallback now receives scene emotion metadata
    so the pad intensity follows the narrative arc (tension drops, payoff
    surges) and carries a subtle rhythmic pulse layer."""
    print(f"\n[11/16] MUSIC & SOUND (ffmpeg sidechain ducking, bed={os.path.basename(music_path)})", flush=True)
    t0 = time.time()
    if not os.path.exists(music_path):
        print("  !! No music bed found — skipping music mix")
        return {"mixed": False, "reason": "no music bed"}

    # Detect silent/dead bed (e.g. old cinematic.mp3 was -91 dB silence)
    probe = subprocess.run(
        ["ffmpeg", "-i", music_path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    import re as _re
    m = _re.search(r"max_volume: ([-.\d]+) dB", probe.stderr)
    max_db = float(m.group(1)) if m else 0.0
    alt = os.path.join(os.path.dirname(music_path), "cinematic_bed.wav")
    if max_db < -60.0:
        if os.path.exists(alt) and _check_bed_audible(alt):
            print(f"  !! {os.path.basename(music_path)} is silent ({max_db:.0f} dB) — using synth bed")
            music_path = alt
        else:
            print(f"  !! {os.path.basename(music_path)} is silent ({max_db:.0f} dB) — generating audible synth pad")
            dur_est = _probe_duration(video_path)
            music_path = _synth_bed(dur_est, alt, scenes=scenes,
                                    audio_durations=audio_durations)
            if not music_path:
                return {"mixed": False, "reason": "silent bed, synth failed"}

    dur = _probe_duration(video_path)
    vol = 10 ** (music_volume_db / 20.0) if music_volume_db else 1.0
    # Voice EQ (2026 recalibration, expert review §3.1): a rigid 100 Hz
    # high-pass thins out the low-mid breathiness (200-500 Hz) that makes
    # the synthetic voice feel human (sighs, laughter).  Replace the static
    # cut with a GENTLE roll-off (subtle shelf) + keep the 3 kHz presence
    # boost so the voice still cuts through the bed + SFX without clipping.
    VOICE_EQ = "highpass=f=55,equalizer=f=3000:t=q:w=1:g=2"
    # Sidechain params (2026 recalibration, expert review §3.2): duck ONLY
    # the mid-range of the bed (500 Hz - 4 kHz, the voice's frequency home)
    # with a fast attack (10-30 ms) and medium release (50-100 ms) so the
    # bed "breathes" around speech instead of broadband pumping.  Ratio 3-4:1.
    # NOTE: sidechaincompress in this ffmpeg build refuses a LABELED pad as
    # its sidechain input ("matches no streams") — always feed it the raw
    # [0:a] voice stream; band-split pads are the MAIN input only.
    SIDECHAIN = "threshold=0.0625:ratio=3.5:attack=20:release=250"
    # Jade spec §4: never allow abrupt music starts/stops — fade the bed
    # in over 1s and out over the final 1.5s (unless the video is shorter).
    fade_in = min(1.0, dur / 4)
    fade_out_start = max(0.0, dur - 1.5)
    FADES = f",afade=t=in:st=0:d={fade_in:.2f},afade=t=out:st={fade_out_start:.2f}:d=1.5"
    # SFX layer (optional): event-driven timeline built from script sfx_events
    sfx_used = ""
    if sfx_path and os.path.exists(sfx_path):
        sfx_used = sfx_path
        print(f"  [sfx] event-driven SFX timeline: {os.path.basename(sfx_path)}")

    if sfx_used:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", music_path,
            "-i", sfx_used,
            "-filter_complex",
            (
                f"[0:a]{VOICE_EQ}[voice];"
                f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{dur:.3f},volume={vol:.3f}{FADES}[bed];"
                # Multiband ducking (§3.2): split the bed into low/mid/high,
                # sidechain-compress ONLY the mid band (500 Hz - 4 kHz) against
                # the voice; bass + air pass untouched so the bed never pumps.
                f"[bed]asplit=3[low_in][mid_in][high_in];"
                f"[low_in]lowpass=f=500[low];"
                f"[mid_in]bandpass=f=2250:w=3500[mid_raw];"
                f"[high_in]highpass=f=4000[high];"
                f"[mid_raw][0:a]sidechaincompress={SIDECHAIN}[mid];"
                f"[low][mid][high]amix=inputs=3:normalize=0[bed_duck];"
                f"[2:a]aloop=loop=-1:size=2e9,atrim=0:{dur:.3f},volume=0.8[sfx];"
                f"[bed_duck][sfx]amix=inputs=2:duration=first:normalize=0[bedmix];"
                f"[voice][bedmix]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", music_path,
            "-filter_complex",
            (
                f"[0:a]{VOICE_EQ}[voice];"
                f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{dur:.3f},volume={vol:.3f}{FADES}[bed];"
                f"[bed]asplit=3[low_in][mid_in][high_in];"
                f"[low_in]lowpass=f=500[low];"
                f"[mid_in]bandpass=f=2250:w=3500[mid_raw];"
                f"[high_in]highpass=f=4000[high];"
                f"[mid_raw][0:a]sidechaincompress={SIDECHAIN}[mid];"
                f"[low][mid][high]amix=inputs=3:normalize=0[bed_duck];"
                f"[voice][bed_duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            out_path,
        ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"  !! ffmpeg music mix failed: {r.stderr[-400:]}")
        return {"mixed": False, "reason": r.stderr[-200:]}
    size_mb = os.path.getsize(out_path) / 1e6 if os.path.exists(out_path) else 0
    # Post-mix verification: loudness sanity (mix should NOT be voice-only)
    ver = subprocess.run(
        ["ffmpeg", "-i", out_path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    m2 = _re.search(r"mean_volume: ([-.\d]+) dB", ver.stderr)
    mean_db = float(m2.group(1)) if m2 else None
    ok = mean_db is not None and -30.0 < mean_db < -5.0
    print(f"  Music mixed (ducked under narration): {_probe_duration(out_path):.1f}s, {size_mb:.1f} MB, "
          f"mean={mean_db} dB {'✓' if ok else '⚠ check mix'}")
    return {"mixed": True, "elapsed_s": round(time.time() - t0, 1), "size_mb": round(size_mb, 1),
            "mean_db": mean_db, "sfx": os.path.basename(sfx_used) if sfx_used else None}


# ═══════════════════════════════════════════════════════════════════════ #
# Video review (13)
# ═══════════════════════════════════════════════════════════════════════ #

def stage_video_review(video_path: str, scenes: list[dict], out_path: str) -> dict:
    print("\n[13/16] VIDEO REVIEW (Gemini Flash, end-to-end)", flush=True)
    t0 = time.time()
    from review_video import _upload_and_review
    script_text = "\n".join(f"SCENE {i}: {s['narration']}" for i, s in enumerate(scenes))
    review = _upload_and_review(video_path, script_text, model="gemini-3.5-flash")
    review["_meta"] = {"video": video_path, "model": "gemini-3.5-flash",
                       "elapsed_s": round(time.time() - t0, 1)}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(review, f, indent=2)
    print(f"  Score: {review.get('quality_score')}/100 (conf {review.get('confidence')}) | "
          f"recs: {len(review.get('prioritized_recommendations', []))}")
    return review


# ═══════════════════════════════════════════════════════════════════════ #
# Improvement pass (14) — applies timeline mutations, then re-render
# ═══════════════════════════════════════════════════════════════════════ #

def stage_improvement_plan(review: dict, iteration: int, out_dir: str,
                           max_total: int = 3, quality_target: int = 85) -> dict:
    set_usage_stage("improvement_plan")
    print(f"\n[14/16] IMPROVEMENT PASS planning (iteration {iteration}/{max_total})", flush=True)
    t0 = time.time()
    imp = ImprovementPass(work_dir=out_dir, max_total_iterations=max_total,
                          quality_target=quality_target)
    plan = imp.plan(review, iteration)
    for a in plan.applied:
        print(f"    APPLY  [{a.category}] {a.detail[:110]}")
    for f in plan.flagged[:5]:
        print(f"    FLAG   {f[:110]}")
    return {**plan.to_dict(), "elapsed_s": round(time.time() - t0, 1)}


def stage_apply_improvements(plan: dict, timeline_path: str) -> list[str]:
    """Actually mutate timeline.json per the applied plan categories.

    Supported mutations:
      pacing        → scale all shot durations (e.g. +8% if 'too fast')
      transitions   → switch cut/cut_sync to fade (or fade→cut) per review
      color         → recorded only (ffmpeg grade handled at render, out of scope v1.1)
    Returns list of human-readable applied changes.
    """
    applied: list[str] = []
    if not os.path.exists(timeline_path):
        return applied
    with open(timeline_path) as f:
        tl = json.load(f)
    shots = tl.get("video_timeline", [])

    for change in plan.get("applied", []):
        cat = change.get("category")
        detail = change.get("detail", "").lower()
        if cat == "pacing" and shots:
            factor = 1.0
            if any(k in detail for k in ("too fast", "rushed", "quickly", "fast-paced", "faster")):
                factor = 0.92
            elif any(k in detail for k in ("too slow", "slowly", "drag", "drags", "slower")):
                factor = 1.08
            if factor != 1.0:
                for s in shots:
                    dur = s.get("end_time", 0) - s.get("start_time", 0)
                    s["end_time"] = round(s.get("start_time", 0) + dur * factor, 3)
                applied.append(f"pacing: scaled shot durations ×{factor}")
        elif cat == "transitions" and shots:
            if any(k in detail for k in ("cut", "jarring", "abrupt")):
                n = 0
                for s in shots:
                    if s.get("transition") in ("cut", "cut_sync", "hard_cut"):
                        s["transition"] = "fade"
                        n += 1
                applied.append(f"transitions: {n} cuts → fades")
            elif "fade" in detail and "too" in detail:
                n = 0
                for s in shots:
                    if s.get("transition") == "fade":
                        s["transition"] = "cut"
                        n += 1
                applied.append(f"transitions: {n} fades → cuts (pacing)")
        elif cat in ("music", "audio_balance"):
            applied.append(f"{cat}: flagged for mix re-render (music_volume_db)")

    if applied:
        with open(timeline_path, "w") as f:
            json.dump(tl, f, indent=2)
        print(f"  Timeline mutated: {applied}")
    return applied


# ═══════════════════════════════════════════════════════════════════════ #
# Helpers
# ═══════════════════════════════════════════════════════════════════════ #

def _robust_json_array(raw: str) -> list:
    """Parse a JSON array from LLM output, tolerating fences and object wraps."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                data = None
        else:
            data = None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("checks", "results", "verifications", "facts", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except Exception:
        return 0.0


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def main():
    ap = argparse.ArgumentParser(description="Jade Studio mission pipeline")
    ap.add_argument("--topic", default="Voyager 1: the farthest human-made object")
    ap.add_argument("--out", default=None, help="Output video path")
    ap.add_argument("--provider", default=None, help="LLM provider (deepseek|gemini); default gemini (flash)")
    ap.add_argument("--target-seconds", type=float, default=TARGET_DURATION_S,
                    help="Target narration runtime in seconds (scales scenes+words)")
    ap.add_argument("--max-render-iterations", type=int, default=2,
                    help="Max total renders (1=no improvement pass, 2=one rerender; default 2)")
    ap.add_argument("--music", default="cache/music/cinematic.mp3")
    ap.add_argument("--music-db", type=float, default=-6.0)
    args = ap.parse_args()

    # v9.1: scale scene count + word budget with the requested duration
    set_target_duration(args.target_seconds)

    mods = _imports()
    topic = args.topic
    slug = "".join(c if c.isalnum() else "_" for c in topic.lower())[:44].strip("_")
    out_dir = os.path.join("results", slug)
    os.makedirs(out_dir, exist_ok=True)
    output_path = args.out or os.path.join(out_dir, f"{slug}_v1.mp4")
    mixed_path = os.path.join(out_dir, f"{slug}_v1_mixed.mp4")
    timeline_path = os.path.join(out_dir, "timeline.json")
    run_report = {"topic": topic, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "stages": {}, "errors": []}

    factory = mods["ProviderFactory"]()
    provider_name = args.provider or "gemini"
    llm = factory.get_llm_provider(provider_name)
    run_report["provider"] = provider_name

    lib = mods["VisualKnowledgeLibrary"]()
    lib.load_all()
    ep = mods["EditorialPlanner"](knowledge_library=lib)

    # ── Stage 1-2: Research + verification ────────────────────────────
    research = stage_research(topic, llm)
    research = stage_fact_verification(research, llm)
    _write_json(os.path.join(out_dir, "research.json"), research)
    run_report["stages"]["research"] = {"facts": len(research.get("facts", [])),
                                        "elapsed_s": research.get("_elapsed_s")}

    # ── Stage 3: Script ───────────────────────────────────────────────
    scenes_data = stage_script(topic, research, llm)
    _write_json(os.path.join(out_dir, "script_draft.json"), scenes_data)

    # ── Stage 4: Script review ────────────────────────────────────────
    scenes_data, review_report = stage_script_review(scenes_data, research, provider_name)
    # Post-review word-budget enforcement (reviewers can expand the script;
    # re-compress to keep the runtime near the target).  Learned from v1 run.
    total_words = sum(len(s.get("narration", "").split()) for s in scenes_data)
    if total_words > MAX_SCRIPT_WORDS:
        print(f"  !! Post-review over budget ({total_words} words) — compressing")
        compress = llm.generate_json(
            "Condense this script to at most " + str(MAX_SCRIPT_WORDS) +
            " words total, keeping all facts and the " + str(SCENE_COUNT) + "-scene structure. "
            "Return ONLY the JSON array of scenes with title/narration/visual_goal/search_queries.\n" +
            json.dumps({"scenes": scenes_data})[:6000]
        )
        try:
            data2 = json.loads(compress)
            scenes2 = data2.get("scenes", []) if isinstance(data2, dict) else (data2 if isinstance(data2, list) else [])
            if len(scenes2) == SCENE_COUNT and sum(len(s.get("narration", "").split()) for s in scenes2) <= MAX_SCRIPT_WORDS + 10:
                scenes_data = _merge_scene_meta(scenes_data, scenes2)
                print(f"  Compressed to {sum(len(s.get('narration','').split()) for s in scenes_data)} words")
        except json.JSONDecodeError:
            print("  !! Post-review compression failed — keeping reviewed script")

    # Post-review TTS normalization (v3): expand abbreviations, spell out
    # dates/numbers so Kokoro narrates "September fifth, nineteen seventy-
    # seven" instead of "Sept five".  Fixes v2 review finding.
    from src.utils.tts_normalize import normalize_narration
    for s in scenes_data:
        s["narration"] = normalize_narration(s.get("narration", ""))
        s["search_queries"] = [
            q for q in s.get("search_queries", []) if not any(
                bad in q.lower() for bad in ("alien", "ufo", "extraterrestrial",
                                             "3d render", "fictional", "sci-fi creature")
            )
        ] or s.get("search_queries", ["space documentary footage"])
    _write_json(os.path.join(out_dir, "script_review_report.json"), review_report)
    _write_json(os.path.join(out_dir, "script_final.json"), scenes_data)

    # ── Stages 5-9: Storyboard + director ─────────────────────────────
    result_scenes, director_stats = stage_storyboard_and_direct(topic, scenes_data, lib, ep, llm)
    run_report["stages"]["director"] = director_stats

    # ── Stage 8b: AI imagery (NVIDIA NIM, benchmarked default) ────────
    ai_stats = stage_ai_imagery(result_scenes, out_dir)
    run_report["stages"]["ai_imagery"] = ai_stats

    # ── Stage 10: Narration ───────────────────────────────────────────
    cache_audio = "cache/audio"
    os.makedirs(cache_audio, exist_ok=True)
    # v9 (Jade spec §1): lock the narrator voice once at project start.
    from src.qa.voice_lock import lock_voice
    from src.director.style_bible import create_style_bible
    voice_lock = lock_voice(provider="kokoro", voice_id="bm_george",
                            speaker_id="jade-narrator-001").reset_episode()
    style_bible = create_style_bible("jade").reset_episode()
    run_report["voice_lock"] = voice_lock.to_dict()
    run_report["style_bible"] = style_bible.to_dict()
    audio_stats = stage_narration(result_scenes, cache_audio, voice_lock=voice_lock)
    run_report["stages"]["narration"] = audio_stats

    # ── v9 (Jade spec §9): DETERMINISTIC PRE-RENDER GATE ─────────────
    from src.qa.jade_gates import PreRenderGate
    # v10: pacing + semantic-alignment gates need per-scene narration
    # durations — probe the generated voice tracks.
    _audio_durs = []
    for _s in scenes_data:
        _ap = os.path.join(cache_audio, f"scene_{_s.get('scene_id', len(_audio_durs))}.wav")
        _audio_durs.append(_probe_duration(_ap) if os.path.exists(_ap) else 0.0)
    _pre_gate = PreRenderGate().run(
        timeline_path=timeline_path, audio_dir=cache_audio,
        voice_lock=voice_lock, style_bible=style_bible,
        scenes_data=scenes_data, audio_durations=_audio_durs)
    run_report["stages"]["pre_render_gate"] = _pre_gate
    if _pre_gate.get("blocking_failures"):
        print("  !! PRE-RENDER GATE BLOCKED: " +
              str(_pre_gate["blocking_failures"]))
        run_report["errors"].append(
            f"pre-render gate blocked: {_pre_gate['blocking_failures']}")
    else:
        print("  [gate] pre-render deterministic gate PASSED (render allowed)")

    # ── Stage 12: Render (initial, voice only) ────────────────────────
    render_stats = stage_render(result_scenes, timeline_path, output_path)
    run_report["stages"]["render_v1"] = render_stats

    # ── v12.4: unified cinematic grade (was dead code — never called) ──
    # The v12 review flagged "color grade the AI-generated segments …
    # saturation levels vary significantly".  stage_cinematic_grade existed
    # but no call site existed, so style drifted across shots.  Apply the
    # organic texture + unified grade pass to EVERY render before mixing.
    graded_path = os.path.join(out_dir, f"{slug}_v1_graded.mp4")
    grade_stats = stage_cinematic_grade(output_path, graded_path)
    run_report["stages"]["grade_v1"] = grade_stats
    grade_src = graded_path if grade_stats.get("graded") else output_path

    # ── Stage 11: Music mix (sidechain ducking) ───────────────────────
    mix_stats = stage_music_mix(grade_src, args.music, mixed_path,
                                music_volume_db=args.music_db)
    run_report["stages"]["music_v1"] = mix_stats
    review_target = mixed_path if mix_stats.get("mixed") else grade_src

    # ── Stages 13-14: Review + improvement (bounded loop) ─────────────
    review = stage_video_review(review_target, scenes_data,
                                os.path.join(out_dir, "review_v1.json"))
    run_report["stages"]["review_v1"] = {
        "score": review.get("quality_score"), "confidence": review.get("confidence"),
        "elapsed_s": review.get("_meta", {}).get("elapsed_s"),
    }

    iteration = 1
    # v12.5 cost guardrails: 1 improvement pass by default; a 2nd pass runs
    # ONLY when the review score is below improve_score_threshold. Hard stop
    # at 3 total renders (max 2 rerenders) regardless of the flag.
    from src.utils.config import get_config as _gc2
    _thr = _gc2("pipeline.improve_score_threshold", 70)
    _score = review.get("quality_score") or 0
    max_iter = 1 if _score >= _thr else min(max(1, args.max_render_iterations), 3)
    if max_iter > 1:
        print(f"  Score {_score} < {_thr} → improvement loop active (max {max_iter} renders)", flush=True)
    while iteration < max_iter:
        plan_dict = stage_improvement_plan(review, iteration + 1, out_dir, max_total=max_iter)
        run_report["stages"][f"improve_pass_{iteration}"] = plan_dict
        if plan_dict.get("stopped_early") or not plan_dict.get("applied"):
            print("  → No auto-applicable changes; stopping improvement loop.")
            break
        # Apply timeline mutations and re-render (no timeline rebuild!)
        applied = stage_apply_improvements(plan_dict, timeline_path)
        if not applied:
            print("  → No timeline mutations possible; stopping improvement loop.")
            break
        render_stats = stage_render(result_scenes, timeline_path, output_path,
                                    build_timeline=False)
        run_report["stages"][f"render_v{iteration+1}"] = render_stats
        # v12.4: grade every improvement-pass render too (style consistency).
        _gpath = os.path.join(out_dir, f"{slug}_v{iteration+1}_graded.mp4")
        _gstats = stage_cinematic_grade(output_path, _gpath)
        run_report["stages"][f"grade_v{iteration+1}"] = _gstats
        _gsrc = _gpath if _gstats.get("graded") else output_path
        # Re-mix music on the improved render
        mix_stats = stage_music_mix(_gsrc, args.music, mixed_path,
                                    music_volume_db=args.music_db)
        run_report["stages"][f"music_v{iteration+1}"] = mix_stats
        review_target = mixed_path if mix_stats.get("mixed") else _gsrc
        review = stage_video_review(review_target, scenes_data,
                                    os.path.join(out_dir, f"review_v{iteration+1}.json"))
        run_report["stages"][f"review_v{iteration+1}"] = {
            "score": review.get("quality_score"), "confidence": review.get("confidence"),
            "elapsed_s": review.get("_meta", {}).get("elapsed_s"),
        }
        iteration += 1

    final_video = review_target
    # ── v9 (Jade spec §10): PUBLISH-READINESS GATE on the final video ──
    try:
        from src.qa.jade_gates import PublishGate
        _publish = PublishGate().run(
            video_path=final_video, timeline_path=timeline_path,
            voice_lock=voice_lock, style_bible=style_bible)
        run_report["publish_gate"] = _publish
        if _publish.get("publish_ready"):
            print("  [gate] PUBLISH-READY ✓ (all deterministic gates passed)")
        else:
            print("  !! PUBLISH GATE: not publish-ready → " +
                  str(_publish.get("blocking_failures", [])))
            run_report["errors"].append(
                f"publish gate: {_publish.get('blocking_failures', [])}")
        with open(os.path.join(out_dir, "publish_gate.json"), "w") as _f:
            json.dump(_publish, _f, indent=2)
    except Exception as e:
        print(f"  !! publish gate failed (non-fatal): {str(e)[:100]}")
        run_report["publish_gate"] = {"error": str(e)[:200]}
    # ── Stage 15-16: Final output + postmortem ────────────────────────
    print("\n[15-16/16] FINAL OUTPUT + POSTMORTEM", flush=True)
    run_report["final"] = {
        "output": final_video,
        "iterations": iteration,
        "final_score": review.get("quality_score"),
        "duration_s": _probe_duration(final_video),
    }
    # ── DeepSeek usage + cache-hit report (per-stage, whole run) ──────
    try:
        from src.providers.llm_provider import DeepSeekUsage
        usage = DeepSeekUsage.summary()
        run_report["llm_usage_deepseek"] = usage
        tot = usage["total"]
        print("\n[DEEPSEEK USAGE — this run]")
        print(f"  calls: {tot['calls']} | input: {tot['input']:,} tok "
              f"(cached {tot['cached']:,} → hit {tot.get('hit_rate', 0):.0%}) | "
              f"output: {tot['output']:,} tok")
        print(f"  estimated cost: ${tot['cost_usd']:.4f}")
        for stage, row in usage["stages"].items():
            print(f"    {stage:20s} calls={row['calls']:3d} in={row['input']:>7,} "
                  f"cached={row['cached']:>6,} out={row['output']:>6,} "
                  f"cost=${row['cost_usd']:.4f}")
    except Exception as e:
        print(f"  !! usage report failed (non-fatal): {str(e)[:80]}")
    _write_json(os.path.join(out_dir, "run_report.json"), run_report)

    recorder = mods["PostmortemRecorder"]()
    pm_path = recorder.record(
        topic,
        techniques_succeeded=[
            f"multi-reviewer script review ({len(review_report.get('passes', []))} passes, gate={review_report.get('final_gate_passed')})",
            f"director beat mode: {director_stats.get('shots')} shots, providers={director_stats.get('providers')}",
            f"ffmpeg sidechain music ducking (bed={os.path.basename(args.music)})",
            f"Gemini Flash end-to-end review score {review.get('quality_score')}/100",
        ],
        techniques_failed=[
            "web search in research agent (no API key — used DeepSeek knowledge base)",
            "NVIDIA NIM FLUX image-gen endpoint 404 (needs endpoint refresh)",
        ],
        prompt_improvements=[
            "research prompt now requests strict JSON with value/unit/source/year schema",
            "script prompt enforces ~60s word budget + bans generic AI phrasing",
            "script review uses 4 independent personas with quality gate",
        ],
        review_feedback=[
            f"{r.get('recommendation', '')[:120]}"
            for r in review.get("prioritized_recommendations", [])[:5]
        ],
        benchmark_results={"llm": provider_name, "renderer": "moviepy+ffmpeg",
                            "tts": "kokoro bm_george", "video_review_model": "gemini-3.5-flash",
                            "music_mix": "ffmpeg sidechaincompress"},
        metrics={"final_score": review.get("quality_score"),
                 "render_iterations": iteration,
                 "shots": director_stats.get("shots"),
                 "fallbacks": director_stats.get("fallbacks"),
                 "duration_s": _probe_duration(final_video)},
        artifacts={"video": final_video, "report": os.path.join(out_dir, "run_report.json")},
    )
    run_report["postmortem"] = pm_path
    _write_json(os.path.join(out_dir, "run_report.json"), run_report)

    print("\n" + "=" * 64)
    print(f"MISSION RUN COMPLETE — {topic}")
    print(f"  Video:  {final_video}")
    print(f"  Report: {os.path.join(out_dir, 'run_report.json')}")
    print(f"  Postmortem: {pm_path}")
    print(f"  Final review score: {review.get('quality_score')}/100")
    print("=" * 64)


if __name__ == "__main__":
    main()
