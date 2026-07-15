"""
provider_router.py — V1 provider router that exhausts ALL configured providers
before failing. Fixes the max_attempts=1 architecture flaw.
"""

from __future__ import annotations

from typing import Any, Optional

from src.assets.asset_router import AssetRouter
from src.utils.result import Result


class ProviderRouter:
    """Routes search requests across all configured providers.

    Unlike AssetRouter which returns on first result, ProviderRouter
    exhausts ALL providers, returning the complete set of candidates
    for downstream ranking.
    """

    def __init__(self, router: AssetRouter):
        self._router = router

    def search_all(
        self,
        query: str,
        **kwargs: Any,
    ) -> list[tuple[str, list[dict]]]:
        """Search ALL providers for a query.

        Args:
            query: Search query string.
            **kwargs: Passed to provider.search().

        Returns:
            List of (provider_name, results_list) tuples.
        """
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
                provider_results = provider.search(query, **kwargs)
                if provider_results:
                    results.append((provider_name, provider_results))
            except Exception as e:
                print(f"  [ProviderRouter] {provider_name} error: {e}")
                continue

        return results
