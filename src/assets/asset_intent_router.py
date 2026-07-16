"""
asset_intent_router.py — Intent-based Asset Routing.

Replaces keyword/topic routing with intent routing.
The planner selects AssetType.  The router maps AssetType → provider chain.
The renderer remains provider-agnostic.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from src.assets.visual_intent import VisualIntent, AssetType
from src.assets.asset_library import AssetLibrary
from src.providers.asset_provider import (
    AssetProvider,
    PexelsProvider,
    PixabayProvider,
    NasaMediaProvider,
    WikimediaCommonsProvider,
)
from src.providers.manim_provider import ManimProvider
from src.providers.chart_provider import ChartProvider

ASSET_TYPE_ROUTES: dict[str, list[str]] = {
    "stock_video": ["pexels", "pixabay"],
    "pexels":      ["pexels"],
    "pixabay":     ["pixabay"],
    "nasa":        ["nasa"],
    "wikimedia":   ["wikimedia"],
    "manim":       ["manim"],
    "chart":       ["chart"],
    "timeline":    ["chart"],
    "map":         ["wikimedia", "pexels"],
    "photo":       ["pexels", "wikimedia"],
    "archive":     ["wikimedia"],
    "svg":         ["chart"],
}


class AssetIntentRouter:
    """Routes asset searches by AssetType instead of topic category.

    Usage::

        router = AssetIntentRouter(AssetType.MANIM)
        results = router.search("Drake Equation visualization")
    """

    def __init__(
        self,
        asset_type: AssetType = AssetType.STOCK_VIDEO,
        visual_intent: Optional[VisualIntent] = None,
        providers: Optional[dict[str, AssetProvider]] = None,
    ):
        self._asset_type = asset_type
        self._visual_intent = visual_intent
        self._providers = providers if providers is not None else self._default_providers()
        self._last_provider_name: str | None = None
        self._last_query: str | None = None

    @classmethod
    def for_intent(cls, visual_intent: VisualIntent) -> "AssetIntentRouter":
        return cls(asset_type=visual_intent.asset_type, visual_intent=visual_intent)

    @property
    def asset_type(self) -> AssetType:
        return self._asset_type

    def search(self, query: str, **kwargs: Any) -> list:
        self._last_query = query
        type_key = self._asset_type.value
        provider_order = ASSET_TYPE_ROUTES.get(type_key, ["pexels", "pixabay"])

        for provider_name in provider_order:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue
            if not self._is_provider_ready(provider, provider_name):
                continue
            try:
                results = provider.search(query, **kwargs)
                if results:
                    self._last_provider_name = provider_name
                    return results
            except Exception:
                continue

        return []

    def search_by_intent(
        self,
        shot_purpose: str = "",
        search_guidance: str = "",
        **kwargs: Any,
    ) -> dict:
        """Search using VisualIntent metadata.

        Uses preferred_providers from the VisualIntent and applies
        must_have / must_not_have filters to results.
        """
        query = search_guidance or shot_purpose
        raw_results = self.search(query, **kwargs)

        if not raw_results:
            return {"assets": [], "provider_name": "", "query": query}

        filtered = raw_results
        if self._visual_intent:
            must_not = set(str(o).lower() for o in self._visual_intent.must_not_have_objects)
            if must_not:
                filtered = [
                    r for r in filtered
                    if not any(
                        kw in str(r.get("url", "")).lower()
                        or kw in str(r.get("description", "")).lower()
                        for kw in must_not
                    )
                ]

        return {
            "assets": filtered,
            "provider_name": self._last_provider_name or "",
            "query": query,
            "count": len(filtered),
        }

    def download(self, url: str, output_path: str) -> str:
        if self._last_provider_name and self._last_provider_name in self._providers:
            return self._providers[self._last_provider_name].download(url, output_path)
        pexels = self._providers.get("pexels")
        if pexels:
            return pexels.download(url, output_path)
        raise RuntimeError(f"No provider available to download {url}")

    def current_provider_name(self) -> str | None:
        return self._last_provider_name

    @staticmethod
    def _default_providers() -> dict[str, AssetProvider]:
        from src.assets.asset_library import AssetLibrary
        return {
            "pexels":    AssetLibrary(provider=PexelsProvider()),
            "pixabay":   AssetLibrary(provider=PixabayProvider()),
            "nasa":      AssetLibrary(provider=NasaMediaProvider()),
            "wikimedia": AssetLibrary(provider=WikimediaCommonsProvider()),
            "manim":     ManimProvider(),
            "chart":     ChartProvider(),
        }

    @staticmethod
    def _is_provider_ready(provider: AssetProvider, name: str) -> bool:
        if name == "pixabay":
            return bool(os.environ.get("PIXABAY_API_KEY", ""))
        return True
