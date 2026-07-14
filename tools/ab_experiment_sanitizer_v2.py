#!/usr/bin/env python3
"""
ab_experiment_sanitizer_v2.py — A/B experiment for search-term sanitisation.

Isolates the sanitiser's effect by:
1. Running the ConceptPlanner once to get raw LLM search terms
2. Splitting into A (raw) and B (sanitised) term sets
3. Running both through AssetRouter.multi_query_search() for each term
4. Capturing hit rate, semantic score, gate decisions per term

This avoids the full pipeline convergence issues (NASA loop) while
measuring the exact impact of the sanitiser on search quality.

Usage:
    python3 tools/ab_experiment_sanitizer_v2.py --topic "The Fermi Paradox"
"""

import argparse
import json
import os
import re
import sys
import time
import types
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Config (mirrors production) ─────────────────────────────────────────

OVERLAP_THRESHOLD = 0.50         # narration leak threshold

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


# ── Sanitiser function ──────────────────────────────────────────────────

def sanitise_search_terms(raw_terms, narration):
    """
    Sanitise search terms — reject >50% overlap, attempt replacement.
    Returns (final_terms, log_entries).
    """
    log = []
    narration_words = set(narration.lower().split())
    narration_tokens = set()
    for w in narration.split():
        clean = re.sub(r'[^\w]', '', w).lower()
        if len(clean) > 2 and clean not in _STOP_WORDS:
            narration_tokens.add(clean)

    for term in raw_terms:
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

        log.append({
            "term": term,
            "overlap_pct": round(overlap, 4),
            "common_words": sorted(narration_words & query_words),
            "rejected": overlap > OVERLAP_THRESHOLD,
        })

    accepted = [t for t in raw_terms if not any(
        e["term"] == t and e["rejected"] for e in log)]
    rejected = [t for t in raw_terms if any(
        e["term"] == t and e["rejected"] for e in log)]

    # Replacement
    replacements = []
    for term in rejected:
        repl = None
        for w in term.lower().split():
            clean = re.sub(r'[^\w]', '', w)
            if clean in _REPLACEMENT_MAP:
                cand = _REPLACEMENT_MAP[clean]
                repl_words = set(cand.lower().split())
                repl_overlap = len(narration_words & repl_words) / max(len(repl_words), 1)
                if repl_overlap <= OVERLAP_THRESHOLD:
                    repl = cand
                    break
        if repl:
            replacements.append(repl)

    candidates = list(accepted) + replacements
    seen = set()
    deduped = []
    for t in candidates:
        n = t.strip().lower()
        if n not in seen:
            seen.add(n)
            deduped.append(t.strip())

    final = deduped[:7]

    for entry in log:
        if entry["term"] in rejected:
            entry["replacement"] = None
            for r in [x for x in replacements if re.sub(r'[^\w]', '', entry["term"].split()[0]) if any(
                    re.sub(r'[^\w]', '', w) in _REPLACEMENT_MAP for w in entry["term"].lower().split())]:
                entry["replacement"] = r
                break

    # Map replacements to rejected terms in log
    repl_map = {}
    for term in rejected:
        for w in term.lower().split():
            clean = re.sub(r'[^\w]', '', w)
            if clean in _REPLACEMENT_MAP:
                cand = _REPLACEMENT_MAP[clean]
                repl_words = set(cand.lower().split())
                repl_overlap = len(narration_words & repl_words) / max(len(repl_words), 1)
                if repl_overlap <= OVERLAP_THRESHOLD:
                    repl_map[term] = cand
                    break
    for entry in log:
        if entry["term"] in repl_map:
            entry["replacement"] = repl_map[entry["term"]]
        else:
            entry["replacement"] = None

    return final, log


# ── A/B Runner ──────────────────────────────────────────────────────────

class TermResult:
    """Result of one search term through the pipeline."""
    def __init__(self, term, sanitised_version=None):
        self.term = term
        self.sanitised_version = sanitised_version
        self.provider = None
        self.hits = 0
        self.semantic_score = None
        self.gate_passed = None
        self.downloaded = False


def run_term_through_pipeline(term, narration, scene_title, topic, purpose, router, semantic_validator, quality_gates, category):
    """
    Run ONE search term through AssetRouter + SemanticValidator + QualityGates.
    Returns a TermResult.
    """
    result = TermResult(term)
    result.sanitised_version = term

    try:
        mq_result = router.multi_query_search(
            [term],
            min_acceptable_score=0.0,
            max_attempts=3,
            diversity_weighting=0.2,
        )
    except Exception as e:
        print(f"    [Search error for '{term}']: {e}")
        return result

    videos = mq_result.get("assets", [])
    selected_query = mq_result.get("selected_query", term)
    selected_provider = mq_result.get("provider_name", "")
    technical_score = mq_result.get("selected_score", -1.0)

    result.provider = selected_provider
    result.hits = len(videos)

    if not videos:
        return result

    best = videos[0]
    vf = best.get("video_files", [{}])
    vf_link = vf[0].get("link", "") if isinstance(vf, list) and vf else ""

    from src.models.schemas import AssetPlan, ProviderType
    asset_plan = AssetPlan(
        provider=ProviderType(selected_provider),
        filepath="",
        video_url=vf_link,
        query_used=selected_query if isinstance(selected_query, str) else selected_query[0],
        score=technical_score if technical_score >= 0 else 0.5,
        semantic_score=0.5,
        technical_score=technical_score if technical_score >= 0 else 0.5,
        aesthetic_style="real_stock",
        duration=best.get("duration", 0.0),
    )

    # Semantic scoring
    sem_score = semantic_validator.score(
        narration=narration,
        query=selected_query,
        asset=asset_plan,
    )
    asset_plan.semantic_score = sem_score
    result.semantic_score = sem_score

    # Quality gates
    gate_passed, gate_reason, gate_details = quality_gates.check_all(
        asset=asset_plan,
        category=category,
    )
    result.gate_passed = gate_passed

    return result


def main():
    parser = argparse.ArgumentParser(description="A/B experiment v2 — isolated search-term comparison")
    parser.add_argument("--topic", default="The Fermi Paradox", help="Video topic")
    parser.add_argument("--output-dir", default="results/ab_experiment", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from dotenv import load_dotenv
    load_dotenv()

    # ── Build scenes ──────────────────────────────────────────────────
    from src.providers.factory import ProviderFactory
    factory = ProviderFactory()
    planning_provider = factory.get_llm_provider_for_role("planner")

    from src.planner import ScenePlanner
    planner = ScenePlanner(provider=planning_provider)
    scenes = planner.generate_plan(args.topic)

    # ── Build pipeline components ─────────────────────────────────────
    from src.assets.asset_router import AssetRouter
    from src.validation.semantic_validator import SemanticValidator
    from src.director.quality_gate import QualityGates
    from src.director.aesthetic_agent import AestheticAgent
    from src.director.visual_style import VisualStyle
    from src.director.concept_planner import ConceptPlanner

    router = AssetRouter.for_topic(args.topic)
    style = VisualStyle.for_topic(args.topic, router.category)
    concept_planner = ConceptPlanner(provider=planning_provider, visual_style=style)
    semantic_validator = SemanticValidator(provider=planning_provider, enabled=True)
    aesthetic_agent = AestheticAgent(visual_style=style)
    quality_gates = QualityGates(
        visual_style=style,
        aesthetic_agent=aesthetic_agent,
        semantic_threshold=semantic_validator._threshold,
    )

    category = router.category

    # ── Run A/B per scene ─────────────────────────────────────────────
    all_results = []
    runtime_log_lines = []
    def rlog(msg):
        runtime_log_lines.append(msg)
        print(msg)

    rlog("=" * 70)
    rlog(f"  A/B EXPERIMENT v2 — Search-Term Sanitiser Impact")
    rlog(f"  Topic: {args.topic}")
    rlog(f"  Scenes: {len(scenes)}")
    rlog(f"  Overlap threshold: {OVERLAP_THRESHOLD:.0%}")
    rlog(f"  Replacement map size: {len(_REPLACEMENT_MAP)} entries")
    rlog(f"=" * 70)

    for scene in scenes:
        scene_id = scene.scene_id
        narration = scene.narration.spoken_narration
        title = scene.title
        purpose = scene.search_plan.scene_purpose
        topic = scene.search_plan.primary_topic or args.topic

        rlog(f"\n{'─'*60}")
        rlog(f"  Scene {scene_id}: {title}")
        rlog(f"{'─'*60}")
        rlog(f"  Narration: {narration[:120]}...")

        # Generate raw LLM terms ONCE
        raw_terms = concept_planner.generate_queries(
            narration=narration,
            title=title,
            topic=topic,
            purpose=purpose,
        )

        if not raw_terms or all(t in ("", "stock footage") for t in raw_terms):
            rlog(f"  ⚠ No concept queries generated — using fallback ['stock footage']")
            raw_terms = ["stock footage"]

        rlog(f"  Raw LLM terms ({len(raw_terms)}):")
        for i, t in enumerate(raw_terms, 1):
            rlog(f"    [{i}] {t!r}")

        # Split: A = raw, B = sanitised
        sanitised, sanitise_log = sanitise_search_terms(raw_terms, narration)

        rlog(f"\n  ── Sanitiser Output ──")
        rlog(f"  Raw terms:      {len(raw_terms)}")
        rlog(f"  Sanitised terms: {len(sanitised)}")
        rlog(f"  Terms removed:   {len(raw_terms) - len(sanitised)}")
        if len(sanitised) == 0:
            rlog(f"  ⚠ CRITICAL: Sanitiser returned ZERO terms!")

        rlog(f"\n  ── Per-term Overlap (B) ──")
        for entry in sanitise_log:
            status = "REJECTED" if entry["rejected"] else "ACCEPTED"
            repl = entry.get("replacement")
            common = ", ".join(entry["common_words"]) or "(none)"
            rlog(f"    {entry['term']!r}")
            rlog(f"      Overlap: {entry['overlap_pct']:.1%} — {status}")
            rlog(f"      Common:  {common}")
            if repl:
                rlog(f"      → Replacement: {repl!r}")
            elif entry["rejected"]:
                rlog(f"      → No replacement available")

        # ── Run A and B terms through the pipeline ──────────────────
        # Use set union to avoid duplicate work
        all_terms_to_test = list(dict.fromkeys(raw_terms + sanitised))

        term_results = {}
        rlog(f"\n  ── Per-Term Pipeline Results ──")
        for term in all_terms_to_test:
            rlog(f"    Testing: {term!r}")
            res = run_term_through_pipeline(
                term, narration, title, topic, args.topic,
                router, semantic_validator, quality_gates, category,
            )
            term_results[term] = res
            status = f"✓ hit={res.hits}" if res.hits > 0 else "✗ no hits"
            if res.hits > 0:
                status += f" sem={res.semantic_score:.3f}" if res.semantic_score else ""
                status += f" gate={'PASS' if res.gate_passed else 'FAIL'}" if res.gate_passed is not None else ""
            rlog(f"      Provider: {res.provider or 'N/A'}")
            rlog(f"      Hits:     {res.hits}")
            if res.semantic_score is not None:
                rlog(f"      Semantic: {res.semantic_score:.3f}")
            if res.gate_passed is not None:
                rlog(f"      Gate:     {'PASS' if res.gate_passed else 'FAIL'}")
            rlog(f"")

        # ── Aggregate results for A and B ───────────────────────────
        a_terms = raw_terms
        b_terms = sanitised if len(sanitised) > 0 else raw_terms  # fallback to raw if empty

        def aggregate(term_list, label):
            hits = sum(term_results.get(t, TermResult(t)).hits for t in term_list)
            downloads = sum(1 for t in term_list if term_results.get(t, TermResult(t)).hits > 0)
            sem_scores = [term_results[t].semantic_score for t in term_list
                          if t in term_results and term_results[t].semantic_score is not None]
            gates = [term_results[t].gate_passed for t in term_list
                     if t in term_results and term_results[t].gate_passed is not None]
            return {
                "label": label,
                "term_count": len(term_list),
                "total_hits": hits,
                "hit_rate": hits / max(len(term_list), 1),
                "downloadable": downloads,
                "download_rate": downloads / max(len(term_list), 1),
                "avg_semantic": sum(sem_scores) / max(len(sem_scores), 1) if sem_scores else 0.0,
                "gate_pass": sum(1 for g in gates if g),
                "gate_fail": sum(1 for g in gates if not g),
                "gate_rate": sum(1 for g in gates if g) / max(len(gates), 1) if gates else 0.0,
            }

        a_stats = aggregate(a_terms, "A (Baseline)")
        b_stats = aggregate(b_terms, "B (Sanitiser)")

        all_results.append({
            "scene_id": scene_id,
            "title": title,
            "raw_terms": a_terms,
            "sanitised_terms": b_terms,
            "sanitise_log": sanitise_log,
            "A": a_stats,
            "B": b_stats,
        })

        rlog(f"\n  ── Scene Summary ──")
        rlog(f"  | Metric              | A (Baseline) | B (Sanitiser) |")
        rlog(f"  |---------------------|--------------|---------------|")
        rlog(f"  | Terms tested        | {a_stats['term_count']:>12} | {b_stats['term_count']:>13} |")
        rlog(f"  | Total hits          | {a_stats['total_hits']:>12} | {b_stats['total_hits']:>13} |")
        rlog(f"  | Hit rate            | {a_stats['hit_rate']:.2f}/term{'':>5} | {b_stats['hit_rate']:.2f}/term{'':>6} |")
        rlog(f"  | Downloadable terms  | {a_stats['downloadable']:>12} | {b_stats['downloadable']:>13} |")
        rlog(f"  | Avg semantic score  | {a_stats['avg_semantic']:.3f}{'':>9} | {b_stats['avg_semantic']:.3f}{'':>10} |")
        rlog(f"  | Gate pass rate      | {a_stats['gate_rate']:.1%}{'':>9} | {b_stats['gate_rate']:.1%}{'':>10} |")

    # ── Overall results ─────────────────────────────────────────────
    rlog(f"\n{'='*70}")
    rlog(f"  OVERALL RESULTS")
    rlog(f"{'='*70}")

    total_a_terms = sum(r["A"]["term_count"] for r in all_results)
    total_b_terms = sum(r["B"]["term_count"] for r in all_results)
    total_a_hits = sum(r["A"]["total_hits"] for r in all_results)
    total_b_hits = sum(r["B"]["total_hits"] for r in all_results)
    total_a_dl = sum(r["A"]["downloadable"] for r in all_results)
    total_b_dl = sum(r["B"]["downloadable"] for r in all_results)
    total_a_sem = sum(r["A"]["avg_semantic"] * r["A"]["term_count"] for r in all_results)
    total_b_sem = sum(r["B"]["avg_semantic"] * r["B"]["term_count"] for r in all_results)
    sem_a_count = sum(r["A"]["term_count"] for r in all_results)
    sem_b_count = sum(r["B"]["term_count"] for r in all_results)
    total_a_gate_pass = sum(r["A"]["gate_pass"] for r in all_results)
    total_a_gate_fail = sum(r["A"]["gate_fail"] for r in all_results)
    total_b_gate_pass = sum(r["B"]["gate_pass"] for r in all_results)
    total_b_gate_fail = sum(r["B"]["gate_fail"] for r in all_results)

    overall_a = {
        "term_count": total_a_terms,
        "total_hits": total_a_hits,
        "hit_rate": total_a_hits / max(total_a_terms, 1),
        "downloadable": total_a_dl,
        "download_rate": total_a_dl / max(total_a_terms, 1),
        "avg_semantic": total_a_sem / max(sem_a_count, 1),
        "gate_rate": total_a_gate_pass / max(total_a_gate_pass + total_a_gate_fail, 1),
    }
    overall_b = {
        "term_count": total_b_terms,
        "total_hits": total_b_hits,
        "hit_rate": total_b_hits / max(total_b_terms, 1),
        "downloadable": total_b_dl,
        "download_rate": total_b_dl / max(total_b_terms, 1),
        "avg_semantic": total_b_sem / max(sem_b_count, 1),
        "gate_rate": total_b_gate_pass / max(total_b_gate_pass + total_b_gate_fail, 1),
    }

    rlog(f"")
    rlog(f"  | Metric                  | A (Baseline)  | B (Sanitiser) | Delta      |")
    rlog(f"  |-------------------------|---------------|---------------|------------|")
    rlog(f"  | Total terms             | {overall_a['term_count']:>13} | {overall_b['term_count']:>13} | {overall_b['term_count'] - overall_a['term_count']:+>8} |")
    rlog(f"  | Total hits              | {overall_a['total_hits']:>13} | {overall_b['total_hits']:>13} | {overall_b['total_hits'] - overall_a['total_hits']:+>8} |")
    rlog(f"  | Hit rate (hits/term)    | {overall_a['hit_rate']:.2f}/term{'':>6} | {overall_b['hit_rate']:.2f}/term{'':>7} | {overall_b['hit_rate'] - overall_a['hit_rate']:+.2f}/term{'':>3} |")
    rlog(f"  | Downloadable terms      | {overall_a['downloadable']:>13} | {overall_b['downloadable']:>13} | {overall_b['downloadable'] - overall_a['downloadable']:+>8} |")
    rlog(f"  | Download rate           | {overall_a['download_rate']:.1%}{'':>9} | {overall_b['download_rate']:.1%}{'':>10} | {overall_b['download_rate'] - overall_a['download_rate']:+.1%}{'':>5} |")
    rlog(f"  | Avg semantic score      | {overall_a['avg_semantic']:.3f}{'':>9} | {overall_b['avg_semantic']:.3f}{'':>10} | {overall_b['avg_semantic'] - overall_a['avg_semantic']:+.3f}{'':>5} |")
    rlog(f"  | Gate pass rate          | {overall_a['gate_rate']:.1%}{'':>9} | {overall_b['gate_rate']:.1%}{'':>10} | {overall_b['gate_rate'] - overall_a['gate_rate']:+.1%}{'':>5} |")
    rlog(f"  | Terms removed by sanit  | —             | {total_a_terms - total_b_terms:>13} | —          |")
    rlog(f"")

    # Determine winner
    winner_hit = "A" if overall_a["hit_rate"] > overall_b["hit_rate"] else "B" if overall_b["hit_rate"] > overall_a["hit_rate"] else "Tie"
    winner_sem = "A" if overall_a["avg_semantic"] > overall_b["avg_semantic"] else "B" if overall_b["avg_semantic"] > overall_a["avg_semantic"] else "Tie"
    winner_gate = "A" if overall_a["gate_rate"] > overall_b["gate_rate"] else "B" if overall_b["gate_rate"] > overall_a["gate_rate"] else "Tie"
    winner_dl = "A" if overall_a["download_rate"] > overall_b["download_rate"] else "B" if overall_b["download_rate"] > overall_a["download_rate"] else "Tie"

    rlog(f"  WINNERS:")
    rlog(f"    Hit rate:      {winner_hit}")
    rlog(f"    Semantic:      {winner_sem}")
    rlog(f"    Gate pass:     {winner_gate}")
    rlog(f"    Download rate: {winner_dl}")
    rlog(f"")

    # ── Analysis ─────────────────────────────────────────────────────
    rlog(f"  ANALYSIS:")
    rlog(f"")

    # 1. Provider retrieval
    if overall_b["hit_rate"] > overall_a["hit_rate"]:
        rlog(f"  1. Provider retrieval: SANITISER IMPROVED by {overall_b['hit_rate'] - overall_a['hit_rate']:.2f} hits/term")
    elif overall_b["hit_rate"] < overall_a["hit_rate"]:
        rlog(f"  1. Provider retrieval: SANITISER WORSENED by {overall_a['hit_rate'] - overall_b['hit_rate']:.2f} hits/term")
    else:
        rlog(f"  1. Provider retrieval: NO CHANGE ({overall_a['hit_rate']:.2f} hits/term both)")

    # 2. Semantic quality
    if overall_b["avg_semantic"] > overall_a["avg_semantic"]:
        rlog(f"  2. Semantic quality: SANITISER IMPROVED by {overall_b['avg_semantic'] - overall_a['avg_semantic']:.3f}")
    elif overall_b["avg_semantic"] < overall_a["avg_semantic"]:
        rlog(f"  2. Semantic quality: SANITISER WORSENED by {overall_a['avg_semantic'] - overall_b['avg_semantic']:.3f}")
    else:
        rlog(f"  2. Semantic quality: NO CHANGE ({overall_a['avg_semantic']:.3f} both)")

    # 3. Downloads
    if overall_b["download_rate"] < overall_a["download_rate"]:
        rlog(f"  3. Irrelevant downloads: SANITISER REDUCED by {(overall_a['download_rate'] - overall_b['download_rate']):.1%}")
        rlog(f"     (fewer downloadable terms → fewer downloads → less irrelevant data)")
    elif overall_b["download_rate"] > overall_a["download_rate"]:
        rlog(f"  3. Irrelevant downloads: SANITISER INCREASED by {(overall_b['download_rate'] - overall_a['download_rate']):.1%}")
    else:
        rlog(f"  3. Irrelevant downloads: NO CHANGE")

    # 4. Primary pipeline success
    rlog("  4. Primary pipeline success (gate pass): ")
    if overall_b["gate_rate"] > overall_a["gate_rate"]:
        rlog(f"Sanitiser IMPROVED by {(overall_b['gate_rate'] - overall_a['gate_rate']):.1%}")
    elif overall_b["gate_rate"] < overall_a["gate_rate"]:
        rlog(f"Sanitiser WORSENED by {(overall_a['gate_rate'] - overall_b['gate_rate']):.1%}")
    else:
        rlog(f"NO CHANGE")

    # 5. Verdict
    rlog(f"")
    rlog(f"  5. VERDICT:")

    # Collect evidence
    sem_change = overall_b["avg_semantic"] - overall_a["avg_semantic"]
    hit_change = overall_b["hit_rate"] - overall_a["hit_rate"]
    dl_change = overall_b["download_rate"] - overall_a["download_rate"]
    gate_change = overall_b["gate_rate"] - overall_a["gate_rate"]

    evidence_for = 0
    evidence_against = 0
    if sem_change > 0: evidence_for += 1
    else: evidence_against += 1
    if hit_change > 0: evidence_for += 1
    else: evidence_against += 1
    if gate_change > 0: evidence_for += 1
    else: evidence_against += 1
    if dl_change < 0: evidence_for += 1  # fewer downloads = less waste
    else: evidence_against += 1

    terms_removed = total_a_terms - total_b_terms
    if terms_removed > 0 and terms_removed > 0.2 * total_a_terms:
        rlog(f"     ⚠ {terms_removed} terms removed ({terms_removed/max(total_a_terms,1):.0%} of raw) — high destruction rate")

    if evidence_for >= 3:
        rlog(f"     RECOMMENDATION: KEEP — sanitiser improves pipeline metrics")
    elif evidence_against >= 3:
        rlog(f"     RECOMMENDATION: REMOVE or REDESIGN — sanitiser degrades pipeline")
    else:
        rlog(f"     RECOMMENDATION: REDESIGN — mixed results, targeted fix needed")
        if terms_removed > 0.3 * total_a_terms:
            rlog(f"     Primary issue: {terms_removed}/{total_a_terms} terms destroyed ({terms_removed/max(total_a_terms,1):.0%})")
            rlog(f"     Fix: add topic-derived fallback when destruction rate >80%")

    # Save runtime log
    log_path = output_dir / f"ab_experiment_v2_{args.topic.replace(' ', '_')}.txt"
    with open(log_path, "w") as f:
        f.write("\n".join(runtime_log_lines))
    print(f"\nRuntime log saved to: {log_path}")
    print(f"\n{'='*70}")
    print(f"  EXPERIMENT COMPLETE")
    print(f"{'='*70}")

    return all_results, overall_a, overall_b, log_path


if __name__ == "__main__":
    main()
