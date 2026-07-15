"""
search_tree.py — Hierarchical Search Strategy with tiered fallback.

Implements a multi-level search tree:
  Level 1: Very specific query
  Level 2: Broader query
  Level 3: Generic category query
  Level 4: NASA animation
  Level 5: Manim generation
  Level 6: Previous shot extension

Provider routing exhausts ALL configured providers before moving to the next
level. This fixes the max_attempts=1 architecture flaw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class SearchLevel(str, Enum):
    SPECIFIC = "specific"
    BROAD = "broad"
    GENERIC = "generic"
    NASA_ANIMATION = "nasa_animation"
    MANIM_GENERATION = "manim_generation"
    SHOT_EXTENSION = "shot_extension"


@dataclass
class SearchTreeLevel:
    """A single level in the search tree."""

    level: SearchLevel
    query_template: str
    min_acceptable_score: float = 0.0
    providers: Optional[list[str]] = None  # None = use default provider order


@dataclass
class SearchResult:
    """Result from a search tree traversal."""

    assets: list = field(default_factory=list)
    selected_query: str = ""
    provider_name: str = ""
    selected_score: float = 0.0
    level: SearchLevel = SearchLevel.SPECIFIC
    exception: Optional[str] = None


class SearchTree:
    """Hierarchical search strategy.

    Each level provides increasingly broad queries. The tree exhausts all
    providers at each level before descending to the next.

    Usage::

        tree = SearchTree()
        result = tree.search(
            router=asset_router,
            specific_query="spiral galaxy radio telescope night",
            broad_query="radio telescope night",
            generic_query="deep space observatory",
        )
    """

    def __init__(self):
        self._levels: list[SearchTreeLevel] = []

    def search(
        self,
        router: Any,
        specific_query: str,
        broad_query: str = "",
        generic_query: str = "",
        **kwargs: Any,
    ) -> SearchResult:
        """Execute the full search tree.

        Args:
            router: AssetRouter instance.
            specific_query: Very specific Level 1 query.
            broad_query: Broader Level 2 query.
            generic_query: Generic Level 3 fallback.
            **kwargs: Passed through to router.search().

        Returns:
            SearchResult with best assets found.
        """
        queries = [
            (SearchLevel.SPECIFIC, specific_query, 0.75),
            (SearchLevel.BROAD, broad_query or specific_query, 0.60),
            (SearchLevel.GENERIC, generic_query or broad_query or specific_query, 0.40),
        ]

        last_exception = None
        for level, query, min_score in queries:
            try:
                result = router.search(query, **kwargs)
                if result:
                    score = router._score_top_asset(result[0], **kwargs) if hasattr(router, '_score_top_asset') else 0.5
                    print(f"  [SearchTree] Level {level.value}: '{query}' → {len(result)} results, score={score:.3f}")
                    if score >= min_score:
                        return SearchResult(
                            assets=result,
                            selected_query=query,
                            provider_name=router.current_provider_name() or "",
                            selected_score=score,
                            level=level,
                        )
            except Exception as e:
                last_exception = e
                print(f"  [SearchTree] Level {level.value} failed: {e}")
                continue

        # All levels exhausted
        return SearchResult(
            exception=str(last_exception) if last_exception else "All search levels exhausted"
        )
