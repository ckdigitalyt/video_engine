"""Decision #13 item 5 — closes the gap v16_batch.py's own docstring/CLI
flagged ("turning a freshly ideated topic into a renderable
stories/<id>/story.json needs the research+script engine wired live, which
it is not yet"): a freshly-selected topic candidate (engine.v16_topics
select_topics output) -> real Wikipedia sources -> engine.v16_research.
build_facts -> engine.v16_script.write_story -> a v15_pipeline-shaped
story.json, written under illustrated_engine/stories/.

Every stage can HOLD (too few sources, a failed research quote-check, a
script that never clears its own code/critic/fact-check gates) -- this
module never invents a story around a stage that didn't pass; `generate_story`
returns {"status": "hold", "reason": ...} instead, same "HOLD, never fake a
pass" convention as v15_gate/v16_gate.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.v16_research import ResearchHold, build_facts
from engine.v16_script import write_story
from engine.v16_sources import wikipedia_sources
from engine.v16_topics import STORIES_DIR, slugify

MIN_SOURCES = 2
ROLE_FUNCTION = {"hook": "HOOK", "payoff": "PAYOFF"}


def script_to_story(candidate: dict, story_engine: dict) -> dict:
    """v16_script's sentence-level script -> v15_pipeline's beat-level
    story.json. Deliberately minimal: hook_plan/payoff_image/
    visual_contradiction/concepts are schema-optional everywhere they're
    read (v15_plan.planv9, v16_gate, engine.subject_bible all `.get(...)
    or {}`/`or None`) and are left unset here rather than guessed at --
    those are the hand-authored editorial judgment calls prior samples
    (t_figure_skater_spin, t_humans_closer_trex) made by hand, not
    something this adapter should fabricate."""
    script = story_engine["script"]
    meta = story_engine["metadata"] or {}
    title = meta.get("title") or candidate["title"]
    beats = []
    for i, s in enumerate(script["sentences"], 1):
        beats.append({
            "beat_id": f"B{i}",
            "function": ROLE_FUNCTION.get(s.get("role"), "NORMAL"),
            "narration": s["text"],
            "claim": s["text"],
            "fact_ids": list(s.get("fact_ids") or []),
        })
    return {"story_id": slugify(title), "title": title,
           "subject": candidate.get("cluster", ""), "beats": beats,
           "topic_id": candidate.get("id")}


def generate_story(candidate: dict, *, ask=None, fetch_sources=None) -> dict:
    """-> {"status": "ok", "story": {...}, "facts": {...}, "script_engine": {...}}
    or {"status": "hold", "reason": "..."}. Never raises for a research/
    script failure (those are expected outcomes, not bugs); an LLM call
    this makes no attempt to swallow beyond what build_facts/write_story
    already handle (LLMUnavailable inside write_story is itself a HOLD, not
    an exception — see v16_script.write_story)."""
    fetch_sources = fetch_sources or wikipedia_sources
    title = candidate["title"]
    sources = fetch_sources(title, 3)
    if len(sources) < MIN_SOURCES:
        return {"status": "hold",
               "reason": f"only {len(sources)} usable source(s) for "
                         f"{title!r} (need >= {MIN_SOURCES})"}
    try:
        facts = build_facts(title, sources, ask=ask)
    except ResearchHold as e:
        return {"status": "hold", "reason": f"research: {e}"}
    story_engine = write_story(title, facts, ask=ask)
    if story_engine["verdict"] != "PASS":
        return {"status": "hold",
               "reason": "script: " + "; ".join(story_engine["holds"]),
               "facts": facts, "script_engine": story_engine}
    story = script_to_story(candidate, story_engine)
    return {"status": "ok", "story": story, "facts": facts,
           "script_engine": story_engine}


def write_story_dir(story: dict, stories_dir: Path | None = None) -> Path:
    d = Path(stories_dir or STORIES_DIR) / story["story_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "story.json").write_text(json.dumps(story, indent=1))
    return d
