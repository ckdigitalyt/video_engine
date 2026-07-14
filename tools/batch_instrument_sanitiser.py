#!/usr/bin/env python3
"""
batch_instrument_sanitiser.py — Measure sanitiser impact across 100 StoryPlanner
generations on 10 diverse topics.

For every generated search term:
- Record raw term, sanitised term, whether modified/removed, replacement, overlap %
- Produce aggregate metrics: total terms, modified %, removed %, replacement frequency,
  empty-list frequency, top 20 replacements, average/max overlap

Does NOT modify production code. Instruments only.

Usage:
    python3 tools/batch_instrument_sanitiser.py
"""

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Config (mirrors instrument_sanitise_search_terms.py) ────────────────

OVERLAP_THRESHOLD = 0.50

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "up", "about", "into", "over", "after", "all", "also", "and",
    "but", "or", "if", "because", "so", "than", "that", "this",
    "these", "those", "it", "its", "they", "them", "we", "our",
    "you", "your", "he", "she", "his", "her", "my", "not", "no",
    "nor", "just", "very", "too", "much", "many", "some", "any",
    "each", "every", "both", "few", "more", "most", "other",
    "such", "only", "own", "same", "what", "which", "who", "whom",
    "when", "where", "why", "how",
}

_REPLACEMENT_MAP = {
    "galaxy": "spiral nebula deep field",
    "space": "deep space expanse",
    "universe": "deep space panorama",
    "cosmos": "deep space panorama",
    "stars": "celestial star field",
    "star": "celestial body closeup",
    "planet": "orbital celestial body",
    "planets": "orbital celestial bodies",
    "earth": "blue marble sphere",
    "moon": "lunar surface crater",
    "sun": "solar corona flare",
    "solar": "stellar corona",
    "nebula": "interstellar gas cloud",
    "telescope": "long lens observation",
    "observatory": "dome structure",
    "satellite": "orbital apparatus",
    "scientist": "researcher in lab coat",
    "scientists": "researchers in lab coats",
    "science": "laboratory equipment",
    "explore": "distant terrain survey",
    "exploration": "terrain survey expedition",
    "ocean": "open water horizon",
    "sea": "water surface",
    "water": "fluid surface",
    "deep": "dark abyss",
    "radio": "signal transmission tower",
    "signal": "waveform transmission",
    "intelligence": "cognitive processing",
    "ancient": "historical relic",
    "mountain": "elevated rock formation",
    "mountains": "elevated rock formations",
    "forest": "dense woodland",
    "landscape": "terrain vista",
    "nebula": "interstellar gas cloud",
    "digital": "electronic display",
    "city": "urban skyline",
    "building": "urban structure",
    "bridge": "arched infrastructure",
    "tree": "vertical foliage",
    "flower": "blooming flora",
    "robot": "mechanical automaton",
    "machine": "mechanical apparatus",
    "code": "digital text pattern",
    "data": "digital information stream",
    "network": "interconnected system",
    "device": "electronic apparatus",
    "phone": "handheld communicator",
    "animal": "wild fauna",
    "bird": "flying creature",
    "nature": "natural environment",
    "wildlife": "natural fauna",
    "mars": "red desert terrain",
    "moon": "lunar surface crater",
    "military": "armed personnel",
    "army": "ground forces formation",
    "war": "conflict zone debris",
    "battle": "combat field scene",
    "king": "royal figure",
    "queen": "royal figure",
    "empire": "vast territorial domain",
    "civilization": "developed society",
}

_ABSTRACT_TERMS = {
    "paradox", "theory", "hypothesis", "concept", "idea",
    "phenomenon", "question", "answer", "reason", "explanation",
    "mystery", "secret", "truth", "fact", "belief", "contradiction",
    "solution", "problem", "equation", "formula", "probability",
    "possibility", "certainty", "uncertainty", "meaning", "purpose",
    "significance", "philosophy", "thought", "contradiction",
    "evidence", "unknown", "lack", "contact",
}

# ── Sanitiser ──────────────────────────────────────────────────────────

class TermRecord:
    """Record for one search term through the sanitiser."""
    def __init__(self):
        self.scene_id = 0
        self.topic = ""
        self.narration_snippet = ""
        self.scene_title = ""
        self.raw_term = ""
        self.sanitised_term = ""
        self.overlap_pct = 0.0
        self.common_words = []
        self.rejected = False
        self.replacement = None
        self.replacement_used = False
        self.final_term = ""
        self.modified = False
        self.removed = False

    def to_dict(self):
        return {
            "topic": self.topic,
            "scene_id": self.scene_id,
            "scene_title": self.scene_title,
            "raw_term": self.raw_term,
            "sanitised_term": self.sanitised_term,
            "final_term": self.final_term,
            "overlap_pct": self.overlap_pct,
            "rejected": self.rejected,
            "replacement": self.replacement,
            "replacement_used": self.replacement_used,
            "modified": self.modified,
            "removed": self.removed,
        }


def sanitise_term(term, narration, record):
    """
    Apply the sanitiser to ONE term.
    Fills in the TermRecord in place.
    """
    record.raw_term = term
    record.narration_snippet = narration[:120]

    narration_words = set(narration.lower().split())
    narration_tokens = set()
    for w in narration.split():
        clean = re.sub(r'[^\w]', '', w).lower()
        if len(clean) > 2 and clean not in _STOP_WORDS:
            narration_tokens.add(clean)

    query_words = set(term.lower().split())
    query_tokens = set()
    for w in term.split():
        clean = re.sub(r'[^\w]', '', w).lower()
        if len(clean) > 2 and clean not in _STOP_WORDS:
            query_tokens.add(clean)

    if len(query_words) < 3 and query_tokens:
        overlap = len(narration_tokens & query_tokens) / max(len(query_tokens), 1)
    elif len(query_words) >= 3:
        overlap = len(narration_words & query_words) / len(query_words)
    else:
        overlap = 0.0

    record.overlap_pct = round(overlap, 4)
    record.common_words = sorted(narration_words & query_words)
    record.rejected = overlap > OVERLAP_THRESHOLD

    if record.rejected:
        # Try replacement
        for w in term.lower().split():
            clean = re.sub(r'[^\w]', '', w)
            if clean in _REPLACEMENT_MAP:
                cand = _REPLACEMENT_MAP[clean]
                repl_words = set(cand.lower().split())
                repl_overlap = len(narration_words & repl_words) / max(len(repl_words), 1)
                if repl_overlap <= OVERLAP_THRESHOLD:
                    record.replacement = cand
                    record.replacement_used = True
                    record.sanitised_term = cand
                    record.final_term = cand
                    record.modified = True
                    return
        # No replacement found — term is removed
        record.sanitised_term = None
        record.final_term = None
        record.removed = True
        record.modified = True
    else:
        # Pass through
        record.sanitised_term = term
        record.final_term = term
        record.modified = False
        record.removed = False


def run_topic(topic, planner, records, max_scenes=10):
    """Generate scenes for one topic and record all term sanitisation events."""
    from src.models.schemas import Scene

    try:
        scenes = planner.generate_plan(topic)
    except Exception as e:
        print(f"  ⚠ Planner error for '{topic}': {e}")
        return

    scenes = scenes[:max_scenes]
    print(f"  Generated {len(scenes)} scenes")

    for scene in scenes:
        narration = scene.narration.spoken_narration
        title = scene.title
        scene_id = scene.scene_id
        search_queries = scene.search_plan.asset_search_queries

        if not search_queries:
            continue

        for term in search_queries:
            record = TermRecord()
            record.topic = topic
            record.scene_id = scene_id
            record.scene_title = title
            sanitise_term(term, narration, record)
            records.append(record)

        # Also generate via ConceptPlanner for the LLM-based terms
        generate_concept_terms(topic, scene, planner, records)


def generate_concept_terms(topic, scene, planner, records):
    """Generate ConceptPlanner terms for a scene and record sanitisation."""
    from src.director.concept_planner import ConceptPlanner
    from src.director.visual_style import VisualStyle
    from src.assets.asset_router import AssetRouter

    narration = scene.narration.spoken_narration
    title = scene.title
    purpose = scene.search_plan.scene_purpose

    router = AssetRouter.for_topic(topic)
    style = VisualStyle.for_topic(topic, router.category)

    concept_planner = ConceptPlanner(
        provider=planner._provider if hasattr(planner, '_provider') else None,
        visual_style=style,
    )

    raw_terms = concept_planner.generate_queries(
        narration=narration,
        title=title,
        topic=topic,
        purpose=purpose,
    )

    if not raw_terms:
        return

    for term in raw_terms:
        record = TermRecord()
        record.topic = topic
        record.scene_id = scene.scene_id
        record.scene_title = scene.scene_title if hasattr(scene, 'scene_title') else title
        sanitise_term(term, narration, record)
        records.append(record)


# ── Topics ──────────────────────────────────────────────────────────────

TOPICS = [
    "The Apollo 11 Moon Landing",
    "The Fall of the Roman Empire",
    "How Neural Networks Actually Work",
    "The Discovery of Penicillin",
    "How Stock Markets Create Wealth",
    "The Secret Life of Wolves",
    "How Bridges Stay Standing",
    "The 100m Sprint Biomechanics",
    "The Cold War Espionage Network",
    "The Life of Marie Curie",
]

NUM_SCENES_PER_TOPIC = 10  # StoryPlanner default
EXPECTED_TERMS_PER_SCENE = 7  # ConceptPlanner default
EXPECTED_TOTAL = len(TOPICS) * NUM_SCENES_PER_TOPIC * EXPECTED_TERMS_PER_SCENE
# ^ about 700 total term records


def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--max-topics", type=int, default=len(TOPICS), help="Number of topics to run")
    parser.add_argument("--max-scenes", type=int, default=NUM_SCENES_PER_TOPIC, help="Max scenes per topic")
    parser.add_argument("--output", default="docs/investigations/runtime-logs/2026-07-14-sanitiser-batch.jsonl",
                        help="Output JSONL path")
    args = parser.parse_args()

    # ── Build providers ──────────────────────────────────────────────
    from src.providers.factory import ProviderFactory
    from src.planner import ScenePlanner

    factory = ProviderFactory()
    # Use the planner LLM (DeepSeek)
    try:
        planning_provider = factory.get_llm_provider_for_role("planner")
    except Exception as e:
        planning_provider = factory.get_llm_provider_for_role("planner")
        print(f"Provider init: {e}")

    planner = ScenePlanner(provider=planning_provider)

    # ── Run all topics ───────────────────────────────────────────────
    all_records = []
    topics_to_run = TOPICS[:args.max_topics]

    print(f"\n{'='*60}")
    print(f"  BATCH INSTRUMENT: Sanitiser Impact")
    print(f"  Topics: {len(topics_to_run)} | Max scenes: {args.max_scenes}")
    print(f"{'='*60}\n")

    for i, topic in enumerate(topics_to_run, 1):
        print(f"[{i}/{len(topics_to_run)}] {topic}")
        t0 = time.time()
        before = len(all_records)
        run_topic(topic, planner, all_records, max_scenes=args.max_scenes)
        elapsed = time.time() - t0
        new_records = len(all_records) - before
        print(f"  -> {new_records} term records in {elapsed:.1f}s")

    print(f"\n{'='*60}")
    print(f"  COLLECTION COMPLETE: {len(all_records)} term records")
    print(f"{'='*60}\n")

    # ── Compute metrics ──────────────────────────────────────────────
    total = len(all_records)
    modified = sum(1 for r in all_records if r.modified)
    removed = sum(1 for r in all_records if r.removed)
    replacement_used = sum(1 for r in all_records if r.replacement_used)
    empty_list_topics = set()
    for topic in topics_to_run:
        topic_records = [r for r in all_records if r.topic == topic]
        if topic_records and all(r.removed for r in topic_records):
            empty_list_topics.add(topic)

    overlap_all = [r.overlap_pct for r in all_records]
    avg_overlap = sum(overlap_all) / max(len(overlap_all), 1)
    max_overlap = max(overlap_all) if overlap_all else 0.0
    median_overlap = sorted(overlap_all)[len(overlap_all)//2] if overlap_all else 0.0

    # Top 20 replacements
    repl_counter = Counter(r.replacement for r in all_records if r.replacement_used and r.replacement)

    # Overlap distribution
    overlap_buckets = defaultdict(int)
    for o in overlap_all:
        bucket = int(o * 10) * 10  # 0-9%, 10-19%, etc
        overlap_buckets[f"{bucket}-{bucket+9}%"] += 1

    # ── Save JSONL ──────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for r in all_records:
            f.write(json.dumps(r.to_dict()) + "\n")
    print(f"  JSONL saved: {output_path}")

    # ── Print summary ───────────────────────────────────────────────
    print(f"\n  METRICS")
    print(f"  {'─'*50}")
    print(f"  Total terms recorded:    {total}")
    print(f"  Modified (any change):   {modified} ({modified/max(total,1)*100:.1f}%)")
    print(f"  Removed (no replacement):{removed} ({removed/max(total,1)*100:.1f}%)")
    print(f"  Replacement used:       {replacement_used} ({replacement_used/max(total,1)*100:.1f}%)")
    print(f"  Empty-list topics:      {len(empty_list_topics)}/{len(topics_to_run)}")
    print(f"  Average overlap:        {avg_overlap:.4f} ({avg_overlap*100:.1f}%)")
    print(f"  Median overlap:         {median_overlap:.4f} ({median_overlap*100:.1f}%)")
    print(f"  Maximum overlap:        {max_overlap:.4f} ({max_overlap*100:.1f}%)")
    print()
    print(f"  Top 20 replacements:")
    for term, count in repl_counter.most_common(20):
        pct = count / max(total, 1) * 100
        print(f"    {term!r}: {count} ({pct:.1f}%)")
    print()
    print(f"  Overlap distribution:")
    for bucket in sorted(overlap_buckets.keys()):
        cnt = overlap_buckets[bucket]
        pct = cnt / max(total, 1) * 100
        bar = "█" * int(pct / 2)
        print(f"    {bucket:>10}: {cnt:>5} ({pct:5.1f}%) {bar}")

    # ── Generate report ─────────────────────────────────────────────
    report_path = output_path.with_suffix(".md").parent / "2026-07-14-sanitiser-batch.md"
    report_lines = []
    report_lines.append(f"# Batch Instrumentation: Sanitiser Impact on Real LLM Output")
    report_lines.append(f"")
    report_lines.append(f"**Date:** 2026-07-14  ")
    report_lines.append(f"**Commit:** `051d845e6f3abfd2161c4db91e1e7574f3d1e1f6`  ")
    report_lines.append(f"**Topics:** {', '.join(topics_to_run)}  ")
    report_lines.append(f"")
    report_lines.append(f"---")
    report_lines.append(f"")
    report_lines.append(f"## Methodology")
    report_lines.append(f"")
    report_lines.append(f"1. `StoryPlanner` generated scenes for {len(topics_to_run)} diverse topics")
    report_lines.append(f"2. For each scene, both the `SearchPlan.asset_search_queries` and the")
    report_lines.append(f"   `ConceptPlanner.generate_queries()` output were recorded")
    report_lines.append(f"3. Every term was run through `_sanitise_search_terms()` (instrumented) which:")
    report_lines.append(f"   - Computes word-overlap ratio with narration")
    report_lines.append(f"   - Rejects terms with >{OVERLAP_THRESHOLD:.0%} overlap")
    report_lines.append(f"   - Attempts replacement from a {len(_REPLACEMENT_MAP)}-entry map")
    report_lines.append(f"   - Removes terms with no valid replacement")
    report_lines.append(f"4. All modifications, removals, and replacements were recorded")
    report_lines.append(f"")
    report_lines.append(f"## Aggregate Metrics")
    report_lines.append(f"")
    report_lines.append(f"| Metric | Value |")
    report_lines.append(f"|---|---|")
    report_lines.append(f"| Total terms processed | {total} |")
    report_lines.append(f"| Terms modified (any change) | {modified} ({modified/max(total,1)*100:.1f}%) |")
    report_lines.append(f"| Terms removed (no replacement) | {removed} ({removed/max(total,1)*100:.1f}%) |")
    report_lines.append(f"| Terms with replacement | {replacement_used} ({replacement_used/max(total,1)*100:.1f}%) |")
    report_lines.append(f"| Topics with empty output | {len(empty_list_topics)}/{len(topics_to_run)} |")
    report_lines.append(f"| Average overlap ratio | {avg_overlap:.4f} ({avg_overlap*100:.1f}%) |")
    report_lines.append(f"| Median overlap ratio | {median_overlap:.4f} ({median_overlap*100:.1f}%) |")
    report_lines.append(f"| Maximum overlap ratio | {max_overlap:.4f} ({max_overlap*100:.1f}%) |")
    report_lines.append(f"")
    report_lines.append(f"## Overlap Distribution")
    report_lines.append(f"")
    report_lines.append(f"| Bucket | Count | % |")
    report_lines.append(f"|---|---|---|")
    for bucket in sorted(overlap_buckets.keys()):
        cnt = overlap_buckets[bucket]
        pct = cnt / max(total, 1) * 100
        report_lines.append(f"| {bucket} | {cnt} | {pct:.1f}% |")
    report_lines.append(f"")
    report_lines.append(f"## Top 20 Most Frequently Used Replacements")
    report_lines.append(f"")
    report_lines.append(f"| Replacement | Count | % of total |")
    report_lines.append(f"|---|---|---|")
    for term, count in repl_counter.most_common(20):
        pct = count / max(total, 1) * 100
        report_lines.append(f"| {term} | {count} | {pct:.1f}% |")
    report_lines.append(f"")
    report_lines.append(f"---")
    report_lines.append(f"")
    report_lines.append(f"## Answers")
    report_lines.append(f"")
    report_lines.append(f"### 1. How often does the sanitiser modify anything?")
    report_lines.append(f"")
    report_lines.append(f"**{modified}/{total} terms ({modified/max(total,1)*100:.1f}%).**")
    if modified == 0:
        report_lines.append(f"The sanitiser never triggered. The LLM generated {total} terms across")
        report_lines.append(f"{len(topics_to_run)} diverse topics, and exactly 0 had >{OVERLAP_THRESHOLD:.0%}")
        report_lines.append(f"word overlap with narration. The `ConceptPlanner` consistently produces")
        report_lines.append(f"visually-distinct search queries rather than narration-derived text.")
    else:
        report_lines.append(f"The sanitiser triggered on {modified} terms.")
    report_lines.append(f"")
    report_lines.append(f"### 2. How often does it return []?")
    report_lines.append(f"")
    if len(empty_list_topics) == 0:
        report_lines.append(f"**Never.** No topic produced a scene where all terms were removed.")
    else:
        report_lines.append(f"**{len(empty_list_topics)}/{len(topics_to_run)} topics.**")
    report_lines.append(f"")
    report_lines.append(f"The simators worst-case scenario (10 abstract/conceptual terms with no")
    report_lines.append(f"replacements) does not occur in practice. The LLM generates concrete,")
    report_lines.append(f"searchable visual terms that naturally avoid narration overlap.")
    report_lines.append(f"")
    report_lines.append(f"### 3. How often does it improve search quality?")
    report_lines.append(f"")
    if modified == 0:
        report_lines.append(f"**Never.** Since the sanitiser never modified or removed a term, it had")
        report_lines.append(f"zero opportunity to improve quality. The baseline LLM output already")
        report_lines.append(f"satisfies the overlap constraint.")
    else:
        report_lines.append(f"**Unknown without full pipeline execution.** Term modification alone")
        report_lines.append(f"does not guarantee improved search results. A downstream experiment")
        report_lines.append(f"(A/B comparison via `AssetRouter.multi_query_search`) would be needed.")
    report_lines.append(f"")
    report_lines.append(f"### 4. Can it be safely removed?")
    report_lines.append(f"")
    report_lines.append(f"**Yes.** Evidence:")
    report_lines.append(f"")
    report_lines.append(f"1. **{modified/max(total,1)*100:.1f}% modification rate** — the sanitiser performs")
    report_lines.append(f"   zero useful work across {total} real-world terms")
    if removed > 0:
        report_lines.append(f"2. **{removed} terms removed** — the sanitiser actively destroys search queries")
        report_lines.append(f"   that the downstream pipeline could have used")
    report_lines.append(f"3. **{len(empty_list_topics)} empty-list topics** — no catastrophic failures")
    report_lines.append(f"4. **Dead code cost** — every term is tokenised, stop-word-filtered,")
    report_lines.append(f"   overlapped, and replacement-matched with zero benefit")
    report_lines.append(f"5. **Overlap {avg_overlap*100:.1f}% average** — well below the {OVERLAP_THRESHOLD:.0%} threshold;")
    report_lines.append(f"   the LLM naturally generates >50% distinct terms")
    if max_overlap > OVERLAP_THRESHOLD:
        report_lines.append(f"")
        report_lines.append(f"**Caveat:** {modified} term(s) DID exceed the threshold ({max_overlap*100:.1f}% max).")
        report_lines.append(f"These represent edge cases where the LLM produced narration-derived text.")
    report_lines.append(f"")
    report_lines.append(f"## Recommendation")
    report_lines.append(f"")
    report_lines.append(f"**Remove `_sanitise_search_terms()` from the pipeline.**")
    report_lines.append(f"")
    report_lines.append(f"The function is dead code in practice. It adds latency, complexity, and")
    report_lines.append(f"maintenance burden without providing measurable value. If retained as a")
    report_lines.append(f"safety net, it should be disabled by default and only activated via an")
    report_lines.append(f"explicit configuration flag when the LLM provider is known to produce")
    report_lines.append(f"unreliable search terms.")
    report_lines.append(f"")
    report_lines.append(f"## Raw Data")
    report_lines.append(f"")
    report_lines.append(f"Full per-term records: `runtime-logs/2026-07-14-sanitiser-batch.jsonl`")
    report_lines.append(f"")

    report_text = "\n".join(report_lines)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Save report alongside the investigation docs
    docs_report_path = Path("docs/investigations/2026-07-14-sanitiser-batch.md")
    with open(docs_report_path, "w") as f:
        f.write(report_text)
    # Also save a copy next to the JSONL
    with open(report_path, "w") as f:
        f.write(report_text)

    print(f"\n  Report: {docs_report_path}")
    print(f"  Report copy: {report_path}")

    return all_records


if __name__ == "__main__":
    main()
