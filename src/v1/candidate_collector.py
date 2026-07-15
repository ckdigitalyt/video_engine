"""
candidate_collector.py — Collects asset candidates from all providers
before scoring. Never accepts first result.
"""

from __future__ import annotations

from typing import Any, Optional

from src.assets.asset_router import AssetRouter


class CandidateCollector:
    """Collects candidates from all providers before ranking.

    Usage::

        collector = CandidateCollector(router)
        candidates = collector.collect("spiral galaxy", target_duration=10)
        # Returns [(provider_name, query, [asset_dict, ...]), ...]
    """

    def __init__(self, router: AssetRouter):
        self._router = router

    def collect(
        self,
        query: str,
        **kwargs: Any,
    ) -> list[tuple[str, list[dict]]]:
        """Query all providers and collect all candidates.

        Returns: List of (provider_name, [assets]) tuples.
        """
        return self._collect_all(query, **kwargs)

    def collect_multi(
        self,
        queries: list[str],
        **kwargs: Any,
    ) -> list[tuple[str, str, list[dict]]]:
        """Query multiple search terms across all providers.

        Returns: List of (provider_name, query, [assets]) tuples.
        """
        all_candidates: list[tuple[str, str, list[dict]]] = []
        seen_urls: set[str] = set()

        for query in queries:
            for provider_name, assets in self._collect_all(query, **kwargs):
                # Deduplicate by URL
                unique_assets = []
                for a in assets:
                    url = a.get("url", a.get("link", ""))
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        unique_assets.append(a)
                    elif not url:
                        unique_assets.append(a)
                if unique_assets:
                    all_candidates.append((provider_name, query, unique_assets))

        return all_candidates

    def _collect_all(
        self,
        query: str,
        **kwargs: Any,
    ) -> list[tuple[str, list[dict]]]:
        results: list[tuple[str, list[dict]]] = []
        provider_order = self._router._routes.get(
            self._router.category,
            self._router._routes.get("General", []),
        )

        for provider_name in provider_order:
            provider = self._router._providers.get(provider_name)
            if provider is None:
                continue
            if not AssetRouter._is_provider_ready(provider, provider_name):
                continue

            try:
                search_results = provider.search(query, **kwargs)
                if search_results:
                    results.append((provider_name, search_results))
            except Exception as e:
                print(f"  [CandidateCollector] {provider_name}: {e}")
                continue

        return results
