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


def script_to_story(candidate: dict, story_engine: dict,
                    facts_pack: dict | None = None) -> dict:
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
    # 2026-10-15 review: era/place specifics ("1933", "Space Shuttle
    # Challenger", "University of Bristol") lived only in the research facts,
    # which never reached the visual planner -> generic lab/room plates.
    # Each beat now carries its cited facts' claim text as `context`
    # (engine.v15_plan shows it to the planner), plus the facts' sources.
    facts = {f["id"]: f for f in (facts_pack or {}).get("claims") or []}
    beats = []
    for i, s in enumerate(script["sentences"], 1):
        fids = list(s.get("fact_ids") or [])
        beat = {
            "beat_id": f"B{i}",
            "function": ROLE_FUNCTION.get(s.get("role"), "NORMAL"),
            "narration": s["text"],
            "claim": s["text"],
            "fact_ids": fids,
        }
        ctx = "; ".join(facts[f]["claim"] for f in fids
                        if f in facts and facts[f].get("claim"))
        if ctx:
            beat["context"] = ctx[:400]
        beats.append(beat)
    story = {"story_id": slugify(title), "title": title,
             "subject": candidate.get("cluster", ""), "beats": beats,
             "topic_id": candidate.get("id")}
    # 2026-10-15 review: the real script_critic rubric scores were dropped
    # here, so v16_gate._score_story could only fall back to a structural
    # proxy (which scored every auto story 0). Carry them through.
    cited = [f for b in beats for f in b["fact_ids"]]
    srcs = list(dict.fromkeys(facts[f].get("source_url") for f in cited
                              if f in facts and facts[f].get("source_url")))
    if srcs:
        story["sources"] = srcs
    crit = story_engine.get("critic") or {}
    if crit.get("scores"):
        story["critic"] = {"scores": dict(crit["scores"]),
                           "critique": crit.get("critique", "")}
    return story


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
    story = script_to_story(candidate, story_engine, facts)
    return {"status": "ok", "story": story, "facts": facts,
           "script_engine": story_engine}


def generate_story_ranked(candidates: list, *, ask=None, fetch_sources=None,
                          series_note: str = "", batch_titles: list = ()) -> dict:
    """decision #15 item 2 (rank-not-block): takes up to 3 topic `candidates`
    for ONE render slot, runs the research stage for each (same
    source/quote-check HOLD rules as `generate_story`), then hands every
    topic that reached a `facts` pack to `engine.v16_script.rank_write_story`
    so scripts for all of them are generated up front, scored by the real
    critic, and the single highest-scoring one is finalized and returned --
    replacing the old "try one topic, fall back to the next only on a HOLD"
    chain. Decision #17: the critic score is a pure ranker now, not a gate --
    whichever candidate scores highest is always the one finalized and
    returned, with no mean or per-dimension floor. The overall slot can only
    HOLD if every one of the (up to 3) topics fails a hard check first: a
    research-stage hold (too few sources, failed quote-check), a script-rule
    code-check failure (`code_checks` -- facts, digits, absolute-claims, ...)
    surviving its rewrite budget, or an LLM failure during finalize. A topic
    that HOLDs at the research stage is recorded in "candidates" too, even
    though it never reaches the critic.

    -> {"status": "ok", "story": {...}, "script_engine": {...}, "picked_topic": str,
        "candidates": [...]} or {"status": "hold", "reason": "...", "candidates": [...]}
    """
    from engine.v16_script import rank_write_story
    fetch_sources = fetch_sources or wikipedia_sources
    by_title, topics_facts, research_holds = {}, [], []
    for c in candidates[:3]:
        by_title[c["title"]] = c
        sources = fetch_sources(c["title"], 3)
        if len(sources) < MIN_SOURCES:
            research_holds.append({"topic": c["title"], "status": "hold",
                                   "reason": f"only {len(sources)} usable source(s) for "
                                             f"{c['title']!r} (need >= {MIN_SOURCES})"})
            continue
        try:
            facts = build_facts(c["title"], sources, ask=ask)
        except ResearchHold as e:
            research_holds.append({"topic": c["title"], "status": "hold",
                                   "reason": f"research: {e}"})
            continue
        topics_facts.append((c["title"], facts))

    if not topics_facts:
        return {"status": "hold",
               "reason": "no candidate reached script generation: "
                         + "; ".join(h["reason"] for h in research_holds),
               "candidates": research_holds}

    result = rank_write_story(topics_facts, series_note=series_note,
                              batch_titles=batch_titles, ask=ask)
    all_candidates = research_holds + result["candidates"]
    if result["verdict"] == "PASS":
        story = script_to_story(by_title[result["picked_topic"]], result["story"],
                                dict(topics_facts).get(result["picked_topic"]))
        return {"status": "ok", "story": story, "script_engine": result["story"],
               "picked_topic": result["picked_topic"], "candidates": all_candidates}

    reasons = []
    for c in result["candidates"]:
        if c["status"] == "hold":
            reasons.append(f"{c['topic']}: {c['reason']}")
        elif result.get("picked_topic") == c["topic"] and result.get("story"):
            reasons.append(f"{c['topic']}: mean {c['mean']:.2f} min {c['min']} picked but "
                           f"finalize held: {'; '.join(result['story']['holds'])}")
    return {"status": "hold",
           "reason": "rank-not-block: all candidates failed a hard check: " + "; ".join(reasons),
           "candidates": all_candidates}


def write_story_dir(story: dict, stories_dir: Path | None = None) -> Path:
    d = Path(stories_dir or STORIES_DIR) / story["story_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "story.json").write_text(json.dumps(story, indent=1))
    return d
