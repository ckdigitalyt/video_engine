"""
asset_library.py — Reusable asset library for local-first asset lookup.

Before calling an external provider, the library searches a local index of
previously downloaded assets.  If a sufficiently similar asset already
exists, it is reused instead of making a new API call, which reduces
external API usage, speeds up rendering, and improves visual consistency.

Supports clip diversity: recently used assets are penalised to avoid
reusing the same clip repeatedly within a short window.

Similarity is currently based on keyword overlap (Jaccard index of
normalised query tokens).  The design allows embeddings/vector search to
be added later without changing the public interface.
"""

import os
import time
from typing import Optional

from src.assets.asset_cache import AssetCache
from src.providers.asset_provider import AssetProvider
from src.utils.config import get_config


class AssetLibrary:
    """
    Reusable asset library that looks up locally cached assets before
    delegating to an external provider.

    Parameters
    ----------
    provider : AssetProvider
        The backing provider (e.g. PexelsProvider) called on cache miss.
    cache : AssetCache | None
        SQLite-backed cache instance.  Created automatically if omitted.
    enabled : bool
        When *False*, every call bypasses local lookup and goes straight
        to the provider.  Useful for testing or debugging.
    threshold : float
        Minimum Jaccard similarity (0-1) required for a cached entry to
        be considered a match.  0.5 means at least half the tokens must
        overlap.
    max_candidates : int
        Maximum number of cached candidates to consider when scoring
        potential matches.  Sorted by similarity, descending.
    diversity_enabled : bool
        Whether to apply repeat penalties for clip diversity.
    recent_window : int
        Number of recent queries to track for repeat penalties.
    repeat_penalty : float
        Amount subtracted from similarity score for repeated asset urls.
    """

    def __init__(
        self,
        provider: AssetProvider,
        cache: Optional[AssetCache] = None,
        enabled: Optional[bool] = None,
        threshold: Optional[float] = None,
        max_candidates: Optional[int] = None,
        diversity_enabled: Optional[bool] = None,
        recent_window: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
    ):
        self._provider = provider
        self._cache = cache or AssetCache()

        # Load configuration (allow constructor override for testing)
        self._enabled = enabled if enabled is not None else get_config(
            "providers.pexels.reuse.enabled", True
        )
        self._threshold = threshold if threshold is not None else get_config(
            "providers.pexels.reuse.similarity_threshold", 0.45
        )
        self._max_candidates = max_candidates if max_candidates is not None else get_config(
            "providers.pexels.reuse.max_candidates", 5
        )
        self._diversity_enabled = diversity_enabled if diversity_enabled is not None else get_config(
            "clip_diversity.enabled", True
        )
        self._recent_window = recent_window if recent_window is not None else get_config(
            "clip_diversity.recent_window", 5
        )
        self._repeat_penalty = repeat_penalty if repeat_penalty is not None else get_config(
            "clip_diversity.repeat_penalty", 0.3
        )
        self._query_repeat_penalty = get_config("clip_diversity.query_repeat_penalty", 0.15)

        # Track the last query for download-time indexing
        self._last_query: str | None = None

        # Track recently used assets for diversity
        self._recent_asset_urls: list[str] = []
        self._recent_queries: list[str] = []

    # ── Public API ─────────────────────────────────────────────────────

    def search(self, query: str, **kwargs) -> list:
        """
        Search for assets matching *query*.

        1. If reuse is enabled, look up similar queries in the local index.
        2. On a hit, check clip diversity (penalise recently-used assets).
        3. If diverse enough, return the cached result.
        4. Otherwise delegate to the backing provider and track results.
        """
        self._last_query = query

        if self._enabled:
            match = self._lookup_similar(query)
            if match is not None:
                # v14 fix (52-Hz run resolution_headroom blocker): the reuse
                # path served STALE low-res cached scene clips (426x240,
                # 640x360) without any resolution check — 11 shots then
                # failed the pre-render headroom gate.  Probe the cached
                # local file; below-floor entries are evicted and re-searched
                # instead of silently shipping soft footage.
                from src.qa.resolution_gate import probe_image_size as _pis
                _min_w = get_config("providers.pexels.min_width", 1920)
                _min_h = get_config("providers.pexels.min_height", 1080)
                _lp = match.get("local_path", "")
                _reuse_ok = True
                if _lp and os.path.exists(_lp):
                    _sz = _pis(_lp)
                    if _sz is not None and (_sz[0] < _min_w or _sz[1] < _min_h):
                        print(f"-> AssetLibrary EVICT (below {_min_w}x{_min_h} floor): "
                              f"'{match.get('query', '')}' -> {_lp}")
                        try:
                            self._cache.evict("pexels", match.get("query", query))
                        except Exception:
                            pass
                        _reuse_ok = False
                if _reuse_ok:
                    # ── Diversity check ────────────────────────────────
                    if self._diversity_enabled:
                        penalty = self._compute_diversity_penalty(
                            query, match.get("asset_url", "")
                        )
                        if penalty > 0:
                            print(f"-> AssetLibrary diversity: penalty={penalty:.2f} "
                                  f"for '{match['query']}' — skipping reuse")
                            results = self._provider.search(query, **kwargs)
                            self._track_used(results, query)
                            return results

                    print(f"-> AssetLibrary REUSE: '{query}' similar to "
                          f"'{match['query']}' -> {match['local_path']}")
                    self._recent_asset_urls.append(match["asset_url"])
                    self._recent_queries.append(query)
                    self._trim_window()
                    return [{"video_files": [{"link": match["asset_url"]}]}]

        # Delegate to provider (cache miss or reuse disabled)
        results = self._provider.search(query, **kwargs)
        self._track_used(results, query)
        return results

    def download(self, url: str, output_path: str) -> str:
        """
        Download an asset from *url* and index it for future reuse.

        Delegates to the backing provider's download method.
        """
        local_path = self._provider.download(url, output_path)

        # Index the downloaded asset automatically (no-op if reuse disabled)
        if self._enabled and self._last_query:
            self._index_asset(self._last_query, url, local_path)

        return local_path

    # ── Diversity helpers ──────────────────────────────────────────────

    def _compute_diversity_penalty(self, query: str, asset_url: str) -> float:
        """Compute a diversity penalty for a potential reuse.

        Returns a penalty in [0, 1] where higher means more similar to
        recently used assets.
        """
        if not self._diversity_enabled:
            return 0.0

        # Penalty for same asset URL reused recently
        for recent_url in self._recent_asset_urls:
            if recent_url == asset_url:
                return self._repeat_penalty

        # Smaller penalty for same search query
        for recent_query in self._recent_queries:
            if recent_query.lower() == query.lower():
                return self._query_repeat_penalty

        return 0.0

    def _track_used(self, results: list, query: str) -> None:
        """Track assets from provider results for diversity checks."""
        if not self._diversity_enabled or not results:
            return
        first_url = results[0].get("video_files", [{}])[0].get("link", "")
        if first_url:
            self._recent_asset_urls.append(first_url)
            self._recent_queries.append(query)
            self._trim_window()

    def _trim_window(self) -> None:
        """Keep recent tracking within configured window size."""
        while len(self._recent_asset_urls) > self._recent_window:
            self._recent_asset_urls.pop(0)
            self._recent_queries.pop(0)

    # ── Similarity matching ─────────────────────────────────────────────

    def _lookup_similar(self, query: str) -> Optional[dict]:
        """
        Search the local asset index for entries whose query is similar
        to *query*.

        Returns the best-matching cache entry dict (with keys *query*,
        *asset_url*, *local_path*) or *None* if no entry meets the
        similarity threshold.
        """
        all_entries = self._get_all_indexed()
        if not all_entries:
            return None

        # Score each entry by keyword overlap
        scored: list[tuple[dict, float]] = []
        for entry in all_entries:
            score = self._keyword_similarity(query, entry["query"])
            if score >= self._threshold:
                scored.append((entry, score))

        if not scored:
            return None

        # Sort descending and cap at max_candidates
        scored.sort(key=lambda x: x[1], reverse=True)
        best = scored[0][0]

        # Verify the local file still exists
        if best.get("local_path") and os.path.exists(best["local_path"]):
            return best

        return None

    def _index_asset(self, query: str, url: str, local_path: str) -> None:
        """
        Register an asset in the cache so future similar queries can
        find it.

        The cache uses (provider="asset_library", search_query=normalized)
        as its primary key, ensuring each unique query has exactly one
        entry.
        """
        self._cache.register("asset_library", self._normalize(query), url, local_path)

    def _get_all_indexed(self) -> list[dict]:
        """
        Return every indexed entry from the cache as a list of dicts with
        keys *query*, *asset_url*, *local_path*.
        """
        cur = self._cache._conn().execute(
            "SELECT search_query AS query, asset_url, local_path "
            "FROM assets WHERE provider='asset_library' AND local_path IS NOT NULL"
        )
        return [dict(row) for row in cur.fetchall()]

    # ── Static helpers ─────────────────────────────────────────────────

    @staticmethod
    def _normalize(query: str) -> str:
        """Lowercase, strip, and collapse whitespace."""
        return " ".join(query.lower().split())

    @staticmethod
    def _keyword_tokens(query: str) -> set[str]:
        """Return the set of non-empty, lowercased keyword tokens."""
        return set(AssetLibrary._normalize(query).split())

    @staticmethod
    def _keyword_similarity(query_a: str, query_b: str) -> float:
        """
        Jaccard similarity of keyword tokens between two queries.

        Returns a float in [0, 1] where 1.0 means identical token sets.
        """
        tokens_a = AssetLibrary._keyword_tokens(query_a)
        tokens_b = AssetLibrary._keyword_tokens(query_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)
