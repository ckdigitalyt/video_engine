"""
query_expander.py — Semantic query expansion for stock footage search.

Transforms a scene's VisualIntent (concepts, search_terms) into a ranked
list of diversified search queries, using provider-aware formatting and
synonym expansion to maximize the chance of finding relevant assets.

Designed to slot into the existing AssetRouter's multi_query_search flow
as a query producer, without changing the router or provider interfaces.
"""

from __future__ import annotations

import random
from typing import Optional

from src.models.schemas import VisualIntent
from src.utils.config import get_config


# ── Domain keyword banks for fallback expansion ─────────────────────────

_KEYWORD_BANKS: dict[str, list[str]] = {
    "Space": [
        "deep space", "night sky", "Milky Way", "starfield", "nebula",
        "galaxy", "cosmic", "astronomy", "telescope", "observatory",
        "celestial", "stellar", "interstellar", "astronaut", "space station",
        "satellite", "Earth orbit", "solar system", "planet", "moon",
        "sun", "solar flare", "aurora", "comet", "asteroid",
        "black hole", "supernova", "star cluster", "cosmic dust",
        "spacecraft", "rocket launch", "zero gravity", "space walk",
    ],
    "Science": [
        "laboratory", "microscope", "experiment", "scientist",
        "chemical reaction", "DNA", "cell", "molecule", "atom",
        "particle accelerator", "research", "data visualization",
        "chart", "graph", "diagram", "equation", "formula",
        "scientific instrument", "beaker", "test tube",
    ],
    "History": [
        "historical", "archive", "vintage", "old photograph",
        "documentary", "ancient", "ruins", "artifact",
        "museum", "exhibition", "timeline", "map",
    ],
    "General": [
        "stock footage", "documentary", "cinematic", "aerial",
        "time lapse", "establishing shot", "wide angle",
        "close up", "detail shot", "slow motion",
    ],
}


def expand_queries(
    visual_intent: VisualIntent,
    topic: str = "",
    category: str = "General",
    seed: Optional[int] = None,
) -> list[str]:
    """Expand a scene's VisualIntent into a ranked list of search queries.

    The expansion uses three sources in priority order:
    1. The VisualIntent's explicit ``search_terms`` field
    2. Concept-to-keyword mapping from ``_KEYWORD_BANKS``
    3. Provider-specific formatting (HD, 4K, landscape qualifiers)

    Returns a deduplicated list of up to 20 queries, ranked by relevance
    (concept-derived first, general fallback last).

    Parameters
    ----------
    visual_intent : VisualIntent
        Structured visual metadata for the scene.
    topic : str
        The video topic (used for general fallback).
    category : str
        Topic category for keyword bank selection.
    seed : int | None
        Random seed for reproducible ordering.

    Returns
    -------
    list[str]
        Ranked query strings (best-first) for ``multi_query_search``.
    """
    rng = random.Random(seed) if seed is not None else random

    queries: list[str] = []

    # 1. Use explicit search_terms from VisualIntent (highest priority)
    if visual_intent.search_terms:
        queries.extend(visual_intent.search_terms)

    # 2. Expand from concepts
    if visual_intent.concepts:
        for concept in visual_intent.concepts:
            concept_lower = concept.lower()
            # Check keyword banks for matches
            for bank_keywords in _KEYWORD_BANKS.values():
                matches = [kw for kw in bank_keywords if concept_lower in kw.lower()]
                queries.extend(matches)

            # Add concept itself as a query
            queries.append(f"{concept} 4k footage")
            queries.append(f"{concept} cinematic")

    # 3. Add category-specific keywords
    bank = _KEYWORD_BANKS.get(category, _KEYWORD_BANKS["General"])
    # Pick 3-5 random keywords from the bank for diversity
    if bank:
        rng.shuffle(bank)
        queries.extend(bank[:5])

    # 4. Add topic-derived fallback queries
    if topic:
        queries.append(f"{topic} documentary")
        queries.append(f"{topic} explained")
        queries.append(f"{topic} stock footage")
        queries.append(f"{topic} 4k")

    # 5. Add asset-type-specific qualifiers
    if "diagram" in visual_intent.required_assets or "infographic" in visual_intent.required_assets:
        queries.append("science diagram educational")
        queries.append("infographic animation")
        queries.append("data visualization motion graphics")
    if "animation" in visual_intent.required_assets:
        queries.append("motion graphics explainer")
        queries.append("3d animation scientific")
    if "photograph" in visual_intent.required_assets:
        queries.append("space photograph hubble")
        queries.append("deep space photo")
    if "timelapse" in visual_intent.preferred_asset_types:
        queries.append("time lapse space")
        queries.append("time lapse stars")
        queries.append("hyperlapse night sky")

    # 6. De-duplicate while preserving priority order
    seen: set[str] = set()
    unique_queries: list[str] = []
    for q in queries:
        q_norm = q.strip().lower()
        if q_norm and q_norm not in seen:
            seen.add(q_norm)
            unique_queries.append(q.strip())

    return unique_queries[:20]


def expand_for_shot(
    base_query: str,
    shot_type: str,
    topic: str,
    category: str = "General",
) -> list[str]:
    """Generate search queries for a single shot within a beat.

    Used by BeatDirector to get per-shot queries from a scene-level base.

    Parameters
    ----------
    base_query : str
        The scene-level search query or topic.
    shot_type : str
        Shot role: 'primary', 'cutaway', 'backup'.
    topic : str
        Video topic.
    category : str
        Topic category.

    Returns
    -------
    list[str]
        3-5 diversified queries for this shot.
    """
    queries = [f"{base_query} {shot_type} shot"]

    # Add shot-type-specific diversifiers
    if shot_type == "primary":
        queries.append(f"{base_query} wide shot")
        queries.append(f"{base_query} establishing")
    elif shot_type == "cutaway":
        queries.append(f"{base_query} close up")
        queries.append(f"{base_query} detail")
        queries.append(f"{base_query} macro")

    # Topic fallback
    queries.append(f"{topic} {shot_type}")
    queries.append(f"{topic} documentary footage")

    # Category fallback
    bank = _KEYWORD_BANKS.get(category, _KEYWORD_BANKS["General"])
    if bank:
        rng = random.Random(abs(hash(base_query + shot_type)))
        samples = rng.sample(bank, min(3, len(bank)))
        queries.extend(samples)

    # De-duplicate
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        q_norm = q.strip().lower()
        if q_norm and q_norm not in seen:
            seen.add(q_norm)
            unique.append(q.strip())

    return unique[:5]
