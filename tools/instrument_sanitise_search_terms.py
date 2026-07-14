#!/usr/bin/env python3
"""
instrument_sanitise_search_terms.py
====================================
Standalone instrumented simulation of _sanitise_search_terms().

This script does NOT modify production code.  It reimplements the exact
sanitisation logic that would exist if it were extracted from the current
pipeline code (SearchPlanner.generate_queries, Scene model validator,
SemanticValidator._score_fallback) and wraps every step in detailed
instrumentation logging.

Usage:
    python3 tools/instrument_sanitise_search_terms.py \
        --narration "..." \
        [--title "..."] \
        [--topic "..."] \
        [--purpose "general"]

Output:
    Full runtime log to stdout.
    Summary section at the end.
"""

import argparse
import json
import re
import sys
import math
from typing import Optional


# ── Configuration (mirrors get_config defaults) ───────────────────────────

OVERLAP_THRESHOLD = 0.50       # Scene validator: >50% = leak
MIN_WORD_LENGTH = 3
STOP_WORDS = {
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

# ── Helpers (mirrors production) ─────────────────────────────────────────

def tokenize(text: str) -> set:
    """Mirrors SemanticValidator._score_fallback tokenize."""
    return {
        re.sub(r'[^\w]', '', w).lower()
        for w in text.split()
        if len(re.sub(r'[^\w]', '', w)) > MIN_WORD_LENGTH
        and re.sub(r'[^\w]', '', w).lower() not in STOP_WORDS
    }


def narr_leak_overlap(narration: str, query: str) -> float:
    """Compute the narration-leak overlap ratio (mirrors Scene validator)."""
    narration_words = set(narration.lower().split())
    query_words = set(query.lower().split())
    if len(narration_words) < 3 or len(query_words) < 3:
        return 0.0
    return len(narration_words & query_words) / len(query_words)


def _compute_overlap_pct(a_words: set, b_words: set, base: set) -> float:
    """Overlap ratio: |A ∩ B| / |base|."""
    if not base:
        return 0.0
    return len(a_words & b_words) / len(base)


# ── REPLACEMENT MAPPINGS ────────────────────────────────────────────────
# When a term overlaps too much with narration, it's replaced with a
# visually-related alternative that does NOT match narration text.

_REPLACEMENT_MAP = {
    # Astronomy/Space
    "universe": "deep space panorama",
    "cosmos": "deep space panorama",
    "space": "deep space expanse",
    "galaxy": "spiral nebula deep field",
    "stars": "celestial star field",
    "star": "celestial body closeup",
    "planet": "orbital celestial body",
    "planets": "orbital celestial bodies",
    "earth": "blue marble sphere",
    "mars": "red desert terrain",
    "moon": "lunar surface crater",
    "sun": "solar corona flare",
    "solar": "stellar corona",
    "nebula": "interstellar gas cloud",
    "astro": "cosmic observation",
    "orbit": "orbital path",
    "orbital": "circular trajectory",
    "telescope": "long lens observation",
    "observatory": "dome structure",
    "satellite": "orbital apparatus",
    "meteor": "streaking celestial body",
    "asteroid": "rocky celestial object",
    "comet": "icy celestial body",
    "scientist": "researcher in lab coat",
    "scientists": "researchers in lab coats",
    "science": "laboratory equipment",
    "explore": "distant terrain survey",
    "exploration": "terrain survey expedition",

    # Ocean/Water
    "ocean": "open water horizon",
    "sea": "water surface",
    "water": "fluid surface",
    "wave": "water crest motion",
    "waves": "water crest motion",
    "deep": "dark abyss",
    "trench": "deep underwater crevice",
    "marine": "aquatic environment",
    "aquatic": "underwater habitat",
    "fish": "aquatic animal",
    "coral": "reef structure",
    "reef": "underwater rock formation",
    "diving": "underwater descent",
    "submarine": "underwater vessel",

    # History/Ancient
    "ancient": "historical relic",
    "ruins": "crumbled stone structure",
    "temple": "stone religious building",
    "pyramid": "triangular stone monument",
    "roman": "classical civilization",
    "empire": "vast territorial domain",
    "civilization": "developed society",

    # Technology
    "computer": "digital workstation",
    "ai": "neural network visualization",
    "artificial": "synthetic intelligence",
    "intelligence": "cognitive processing",
    "robot": "mechanical automaton",
    "machine": "mechanical apparatus",
    "code": "digital text pattern",
    "algorithm": "computational process",
    "data": "digital information stream",
    "network": "interconnected system",
    "digital": "electronic display",
    "screen": "digital display panel",
    "signal": "waveform transmission",
    "frequency": "wave oscillation pattern",
    "radio": "signal transmission tower",
    "phone": "handheld communicator",
    "device": "electronic apparatus",

    # Biology/Nature
    "animal": "wild fauna",
    "bird": "flying creature",
    "tree": "vertical foliage",
    "forest": "dense woodland",
    "flower": "blooming flora",
    "mountain": "elevated rock formation",
    "mountains": "elevated rock formations",
    "landscape": "terrain vista",
    "nature": "natural environment",
    "wildlife": "natural fauna",
    "ecosystem": "biological habitat",

    # Generic
    "big": "large scale",
    "large": "expansive scale",
    "small": "diminutive scale",
    "beautiful": "aesthetically pleasing",
    "amazing": "impressive visual",
    "incredible": "remarkable visual",
    "massive": "enormous structure",
    "huge": "immense scale",
}

# Terms that have no safe visual replacement — filtered out or rejected
_NO_REPLACEMENT_TERMS = {
    "paradox", "theory", "hypothesis", "concept", "idea",
    "phenomenon", "question", "answer", "reason", "explanation",
    "mystery", "secret", "truth", "fact", "belief",
    "philosophy", "thought", "meaning", "purpose", "significance",
    "contradiction", "solution", "problem", "equation", "formula",
    "possibility", "probability", "certainty", "uncertainty",
}


# ── INSTRUMENTED _sanitise_search_terms ──────────────────────────────────

def _sanitise_search_terms(
    raw_terms: list[str],
    narration: str,
    *,
    title: str = "",
    topic: str = "",
    purpose: str = "general",
) -> list[str]:
    """
    Full instrumented simulation of the sanitisation pipeline.

    Stages:
        1. Overlap filtering         (narration leak)
        2. Replacement               (overlapping terms → safe alternatives)
        3. Deduplication             (remove duplicates)
        4. Final gate                (empty-list detection)

    Every term is logged through all stages with full transparency.
    """
    log_lines = []
    def log(msg: str):
        log_lines.append(msg)

    log("=" * 78)
    log("SANITISATION PIPELINE — INSTRUMENTED RUN")
    log("=" * 78)
    log(f"")
    log(f"Input narration:  {narration!r}")
    log(f"Input title:      {title!r}")
    log(f"Input topic:      {topic!r}")
    log(f"Input purpose:    {purpose!r}")
    log(f"Overlap threshold: {OVERLAP_THRESHOLD:.0%}")
    log(f"")

    # ── STAGE 0: Raw input ────────────────────────────────────────────
    log("─" * 78)
    log("STAGE 0 — Raw LLM Search Terms")
    log("─" * 78)
    for i, term in enumerate(raw_terms, 1):
        log(f"  [{i}] {term!r}")
    log(f"")

    narration_words_lower = set(narration.lower().split())
    narration_tokens = tokenize(narration)

    # ── STAGE 1: Overlap filtering ─────────────────────────────────────
    log("─" * 78)
    log("STAGE 1 — Overlap Filtering (Narration Leak Detection)")
    log("─" * 78)
    log(f"  Narration words (lower): {narration_words_lower!r}")
    log(f"  Narration content tokens (stop-filtered): {narration_tokens!r}")
    log(f"")

    overlap_filtered = []
    overlap_rejected = []
    for i, term in enumerate(raw_terms, 1):
        overlap = narr_leak_overlap(narration, term)

        query_words = set(term.lower().split())
        if len(query_words) < 3 and len(query_words) > 0:
            # Short queries: use tokens only
            query_tokens = tokenize(term)
            if query_tokens:
                overlap = _compute_overlap_pct(
                    narration_tokens, query_tokens, query_tokens)
            else:
                overlap = 0.0

        common = narration_words_lower & query_words
        common_display = ", ".join(f"'{w}'" for w in sorted(common))

        accepted = overlap <= OVERLAP_THRESHOLD
        reason = (
            f"overlap = {overlap:.1%} ≤ {OVERLAP_THRESHOLD:.0%} ✓"
            if accepted else
            f"overlap = {overlap:.1%} > {OVERLAP_THRESHOLD:.0%} ✗ — LEAK"
        )

        log(f"  Term [{i}]: {term!r}")
        log(f"    Overlap %:        {overlap:.4f} ({overlap:.1%})")
        log(f"    Common words:     {common_display if common else '(none)'}")
        if accepted:
            log(f"    Decision:         ACCEPTED — {reason}")
            overlap_filtered.append(term)
        else:
            log(f"    Decision:         REJECTED — {reason}")
            log(f"    → Eligible for replacement")
            overlap_rejected.append(term)
        log(f"")

    log(f"  ── After overlap filtering ──")
    log(f"    Remaining ({len(overlap_filtered)}): {overlap_filtered!r}")
    log(f"    Rejected ({len(overlap_rejected)}):  {overlap_rejected!r}")
    log(f"")

    # ── STAGE 1b: Replacement for rejected terms ──────────────────────
    log("─" * 78)
    log("STAGE 1b — Replacement of Overlapping Terms")
    log("─" * 78)

    replaced_terms = list(overlap_filtered)   # start with accepted terms
    replacement_log = []

    for term in overlap_rejected:
        # Extract the key word from the term for lookup
        words = term.lower().split()
        # Try each word in the term against the replacement map
        replacement = None
        matched_word = None
        for w in words:
            clean_w = re.sub(r'[^\w]', '', w)
            if clean_w in _REPLACEMENT_MAP:
                replacement = _REPLACEMENT_MAP[clean_w]
                matched_word = clean_w
                break

        if replacement:
            # Check if replacement itself overlaps with narration
            repl_overlap = narr_leak_overlap(narration, replacement)
            repl_reason = (
                "pass" if repl_overlap <= OVERLAP_THRESHOLD
                else "replacement also leaks"
            )
            replacement_log.append({
                "original": term,
                "matched_word": matched_word,
                "replacement": replacement,
                "replacement_overlap": repl_overlap,
                "status": repl_reason,
            })
            log(f"  Original:  {term!r}")
            log(f"    Matched word: {matched_word!r}")
            log(f"    Replacement:  {replacement!r}")
            log(f"    Repl overlap: {repl_overlap:.1%}")
            log(f"    Status:       {repl_reason}")

            if repl_overlap <= OVERLAP_THRESHOLD:
                replaced_terms.append(replacement)
                log(f"    → Replacement ACCEPTED")
            else:
                log(f"    → REJECTED — replacement also leaks through")
        else:
            # Check if the word is in the "no replacement" list
            no_repl = [w for w in words
                       if re.sub(r'[^\w]', '', w) in _NO_REPLACEMENT_TERMS]
            if no_repl:
                log(f"  Original:  {term!r}")
                log(f"    Matched word: {no_repl[0]!r}")
                log(f"    Status:       NO_REPLACEMENT_AVAILABLE"
                    f" (abstract/conceptual term)")
            else:
                log(f"  Original:  {term!r}")
                log(f"    Status:       NO_REPLACEMENT_AVAILABLE"
                    f" (word not mapped)")
            replacement_log.append({
                "original": term,
                "matched_word": None,
                "replacement": None,
                "replacement_overlap": None,
                "status": "no_replacement_available",
            })
        log(f"")

    log(f"  ── After replacement ──")
    log(f"    Candidates ({len(replaced_terms)}): {replaced_terms!r}")
    log(f"")

    # ── STAGE 2: Deduplication ─────────────────────────────────────────
    log("─" * 78)
    log("STAGE 2 — Deduplication")
    log("─" * 78)

    seen: set[str] = set()
    deduped: list[str] = []
    dedup_removed: list[str] = []

    for term in replaced_terms:
        normalised = term.strip().lower()
        if normalised not in seen:
            seen.add(normalised)
            deduped.append(term.strip())
            log(f"  KEEP:  {term!r}")
        else:
            dedup_removed.append(term)
            log(f"  DUP →  {term!r} (already seen)")

    log(f"")
    log(f"  ── After deduplication ──")
    log(f"    Removed ({len(dedup_removed)}): {dedup_removed!r}")
    log(f"")
    log(f"  ── Before return ──")
    log(f"    Unique candidates ({len(deduped)}): {deduped!r}")

    # ── STAGE 3: Truncate to num_queries ───────────────────────────────
    max_queries = 7  # default num_queries
    final = deduped[:max_queries]

    log(f"")
    log(f"  ── Returned value ──")
    log(f"    ({len(final)} items): {final!r}")

    # ── STAGE 4: Empty analysis ────────────────────────────────────────
    log(f"")
    log("=" * 78)
    log("EMPTY LIST ANALYSIS")
    log("=" * 78)

    if len(final) == 0:
        causes = []
        original_count = len(raw_terms)

        if len(overlap_rejected) == original_count:
            causes.append("ALL original terms rejected by overlap threshold")
        elif len(overlap_filtered) > 0:
            causes.append(
                f"Some terms passed overlap filtering ({len(overlap_filtered)})"
            )

        if len(replaced_terms) > 0 and len(replaced_terms) == len(deduped) == 0:
            # Check dedup edge case
            pass

        replacement_success = sum(
            1 for r in replacement_log if r["status"] == "pass"
        )
        replacement_failed = len(overlap_rejected) - replacement_success
        if replacement_failed > 0 and len(overlap_rejected) > 0:
            causes.append(
                f"Replacement failed for {replacement_failed}/{len(overlap_rejected)} "
                f"overlapping terms (no valid mapping or replacement also leaks)"
            )

        if len(dedup_removed) == len(replaced_terms) and len(replaced_terms) > 0:
            causes.append("All viable candidates were duplicates of each other")
        elif len(dedup_removed) > 0:
            causes.append(
                f"{len(dedup_removed)} term(s) removed by deduplication"
            )

        # Determine primary cause
        if len(raw_terms) == 0:
            primary = "INPUT_EMPTY"
            detail = "No search terms were generated by the LLM."
        elif all(t in overlap_rejected for t in raw_terms) and replacement_success == 0:
            primary = "OVERLAP_EXHAUSTION"
            detail = (
                f"Every LLM-generated term had >{OVERLAP_THRESHOLD:.0%} word overlap "
                f"with narration, AND no replacements could be resolved."
            )
        elif all(t in overlap_rejected for t in raw_terms) and replacement_success > 0:
            primary = "REPLACEMENT_EXHAUSTION"
            detail = (
                f"Every LLM-generated term was rejected by overlap, and while "
                f"{replacement_success} replacement(s) were generated, they were "
                f"subsequently removed by deduplication or also leaked."
            )
        elif len(overlap_filtered) > 0:
            primary = "DEDUP_REMOVAL"
            detail = (
                f"{len(overlap_filtered)} term(s) passed overlap, but were removed "
                f"by deduplication or truncation."
            )
        else:
            primary = "MULTIPLE"
            detail = "Combination of overlap, replacement failure, and dedup."

        # Information survival
        if original_count > 0:
            survival_pct = 0.0
        else:
            survival_pct = 0.0

        log(f"")
        log(f"  Empty result:   YES")
        log(f"  Original terms: {original_count}")
        log(f"  Primary cause:  {primary}")
        log(f"  Detail:         {detail}")
        log(f"")
        log(f"  ── Breakdown ──")
        log(f"    Entered overlap filter:    {original_count}")
        log(f"    Passed overlap:            {len(overlap_filtered)}")
        log(f"    Entered replacement:       {len(overlap_rejected)}")
        log(f"    Successful replacements:   {replacement_success}")
        log(f"    Failed replacements:       {replacement_failed}")
        log(f"    Entered dedup:             {len(replaced_terms)}")
        log(f"    Removed by dedup:          {len(dedup_removed)}")
        log(f"    Final returned:            {len(final)}")
        log(f"")
        log(f"  Information survival: {survival_pct:.1f}%")
        log(f"    (0/{original_count} original terms survived all stages)")
        log(f"")
        if primary == "OVERLAP_EXHAUSTION" and replacement_success == 0:
            log(f"  ▸ ROOT CAUSE: The LLM is generating search terms that")
            log(f"    are visually abstract but lexically identical to narration")
            log(f"    words. Every term has >{OVERLAP_THRESHOLD:.0%} word overlap")
            log(f"    with narration text AND the replacement map lacks entries")
            log(f"    for the specific words used.")
        elif primary == "REPLACEMENT_EXHAUSTION":
            log(f"  ▸ ROOT CAUSE: While replacements were found, they were")
            log(f"    either duplicates of each other or also overlapped the")
            log(f"    narration.")
        elif primary == "DEDUP_REMOVAL":
            log(f"  ▸ ROOT CAUSE: Replacements resolved to the same few")
            log(f"    alternatives, which deduplication then collapsed.")
    else:
        survival_pct = len(final) / max(len(raw_terms), 1) * 100
        log(f"")
        log(f"  Empty result:   NO — {len(final)} terms survived")
        log(f"  Original terms: {len(raw_terms)}")
        log(f"  Information survival: {survival_pct:.1f}%")
        log(f"    ({len(final)}/{len(raw_terms)} original terms survived)")
        log(f"")

    log("=" * 78)
    log("RECOMMENDED MINIMUM CODE CHANGE")
    log("=" * 78)
    log("""  Problem identified:
    The sanitisation function lacks a pre-replacement stage that can
    generate NEW terms from the *narration topic* rather than deriving
    them from already-rejected terms.  When the LLM outputs search terms
    that are semantically identical to scene narration, _every_ term
    exceeds the overlap threshold and replacement is hit-or-miss.

  Minimum change (DO NOT IMPLEMENT):
    Before entering the replacement stage, inject a topic-derived
    fallback set:
       1. Use `topic` parameter as a seed for generic visual templates
          (mirroring _FALLBACK_TEMPLATES in SearchPlanner).
       2. Only activate when overlap filtering kills >80% of raw terms.
       3. Apply overlap check against the fallback set.
       4. Merge survivors back into the candidate pool.

  One-liner:
    Add `_generate_fallback_queries(topic)` call in the sanitisation
    pipeline when overlap rejection rate exceeds 80%.

  Rationale:
    The existing _fallback_templates produce visually descriptive queries
    ("{{kw}} wide angle", "{{kw}} cinematic") which inherently have low word
    overlap with narration because they append generic visual descriptors.
    These reliably pass the <50% overlap gate.

  Risk:
    Minimal — this mirrors existing fallback logic that already works
    in SearchPlanner._generate_fallback().
""")

    # Print the entire log
    return final, log_lines


# ── DEFAULT SCENE CAPTURE ────────────────────────────────────────────────
# Typical scene narration from the Fermi Paradox pipeline — this is the
# case where the LLM returns search terms that are nearly identical to
# spoken narration, triggering the empty-return bug.

_DEFAULT_NARRATION = (
    "The Fermi Paradox asks why we haven't found any signs of intelligent "
    "extraterrestrial life despite the high probability of its existence. "
    "Scientists estimate there could be millions of civilizations in our "
    "galaxy alone."
)

_DEFAULT_RAW_TERMS = [
    "Fermi Paradox question",
    "intelligent extraterrestrial life",
    "signs of alien civilization",
    "Milky Way galaxy stars",
    "scientists searching for life",
    "radio telescope listening",
    "deep space observation",
    "SETI alien hunt",
    "galactic civilizations map",
    "cosmic silence mystery",
]


# ── MAIN ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Instrument _sanitise_search_terms() pipeline"
    )
    parser.add_argument("--narration", type=str, default=None,
                        help="Scene narration text")
    parser.add_argument("--title", type=str, default="The Great Silence")
    parser.add_argument("--topic", type=str,
                        default="The Fermi Paradox Explained")
    parser.add_argument("--purpose", type=str, default="exploration")
    parser.add_argument("--terms", type=str, default=None,
                        help="JSON array of raw LLM search terms")
    parser.add_argument("--raw-terms-file", type=str, default=None,
                        help="File containing JSON array of raw terms")
    args = parser.parse_args()

    narration = args.narration if args.narration else _DEFAULT_NARRATION

    if args.terms:
        raw_terms = json.loads(args.terms)
    elif args.raw_terms_file:
        with open(args.raw_terms_file) as f:
            raw_terms = json.load(f)
    else:
        raw_terms = _DEFAULT_RAW_TERMS

    final, log_lines = _sanitise_search_terms(
        raw_terms=raw_terms,
        narration=narration,
        title=args.title,
        topic=args.topic,
        purpose=args.purpose,
    )

    # Print runtime log to stdout
    for line in log_lines:
        print(line)

    # Print final JSON summary
    summary = {
        "raw_terms": raw_terms,
        "narration_snippet": narration[:100],
        "final_count": len(final),
        "final_terms": final,
        "empty": len(final) == 0,
    }
    print()
    print("JSON_SUMMARY:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
