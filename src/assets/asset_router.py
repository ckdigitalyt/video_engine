"""
asset_router.py — Topic-Aware Asset Router.

Routes media-asset requests to the best provider based on the video's
topic category.  Providers are tried in priority order per category.
If none return results, the next provider in the chain is tried until
results are found or all providers are exhausted.

The router is designed to be the *only* asset-fetching interface the
orchestrator depends on.  New providers can be added without changing
orchestrator logic — simply register them in the config file and
implement the ``AssetProvider`` interface.
"""

import os
from typing import Optional

from src.assets.topic_classifier import TopicClassifier
from src.assets.asset_library import AssetLibrary
from src.providers.asset_provider import AssetProvider, PexelsProvider
from src.providers.stubs import NasaMediaProvider, PixabayProvider, WikimediaCommonsProvider
from src.utils.config import get_config


# ── Default routing table (fallback when config YAML is absent) ────────────

_DEFAULT_ROUTES: dict[str, list[str]] = {
    "Space":      ["nasa", "pixabay", "pexels"],
    "History":    ["wikimedia", "pixabay", "pexels"],
    "Science":    ["nasa", "pixabay", "pexels"],
    "Nature":     ["pixabay", "pexels"],
    "Technology": ["pixabay", "pexels"],
    "Finance":    ["pixabay", "pexels"],
    "General":    ["pixabay", "pexels"],
}


class AssetRouter:
    """Routes asset ``search()`` / ``download()`` calls to the best provider
    for a given topic category.

    The router maintains a registry of named ``AssetProvider`` instances
    and a per-category priority list.  When ``search()`` is called, it
    iterates through the priority list for the current category and
    returns the first non-empty result.

    Usage::

        router = AssetRouter.for_topic("The Fermi Paradox")
        results = router.search("milky way galaxy", target_duration=10)
        router.download(url, output_path)

    Parameters
    ----------
    category : str
        Topic category (e.g. ``"Space"``, ``"History"``, ``"General"``).
    providers : dict[str, AssetProvider] | None
        Provider registry.  Created automatically if omitted.
    routes : dict[str, list[str]] | None
        Per-category priority lists.  Loaded from YAML if omitted.
    classifier : TopicClassifier | None
        Used by ``for_topic()``; not required for direct construction.
    """

    def __init__(
        self,
        category: str,
        providers: Optional[dict[str, AssetProvider]] = None,
        routes: Optional[dict[str, list[str]]] = None,
        classifier: Optional[TopicClassifier] = None,
    ) -> None:
        self._category = category
        self._providers = providers if providers is not None else self._default_providers()
        self._routes = routes if routes is not None else self._load_routes()
        self._classifier = classifier

        # Track last-used provider for download routing
        self._last_provider_name: str | None = None
        self._last_query: str | None = None

    # ── Factory ────────────────────────────────────────────────────────

    @classmethod
    def for_topic(
        cls,
        topic: str,
        providers: Optional[dict[str, AssetProvider]] = None,
        classifier: Optional[TopicClassifier] = None,
    ) -> "AssetRouter":
        """Create a router configured for a topic string.

        The topic is classified automatically.

        Example::

            router = AssetRouter.for_topic("The Roman Empire")
            # Category == "History", routes → [wikimedia, pixabay, pexels]
        """
        clf = classifier or TopicClassifier()
        category = clf.classify(topic)
        print(f"-> AssetRouter: topic='{topic}' → category='{category}'")
        return cls(
            category=category,
            providers=providers,
            classifier=clf,
        )

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def category(self) -> str:
        """The topic category this router was created for."""
        return self._category

    def search(self, query: str, **kwargs) -> list:
        """Search for assets matching *query*.

        Iterates through the provider priority list for the current
        category.  Returns the first non-empty result list, or an empty
        list if no provider returned results.

        Skips stub providers automatically.
        """
        self._last_query = query
        provider_order = self._routes.get(self._category, self._routes.get("General", []))

        for provider_name in provider_order:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue

            # Skip stubs silently (they log themselves)
            if provider.__class__.__name__.endswith("StubAssetProvider") or \
               type(provider).__module__.endswith("stubs"):
                provider.search(query, **kwargs)  # let it log the skip
                continue

            try:
                results = provider.search(query, **kwargs)
                if results:
                    self._last_provider_name = provider_name
                    print(f"-> Router selected: '{provider_name}' for query '{query}'")
                    return results
            except Exception as e:
                print(f"-> Router: provider '{provider_name}' error: {e}")
                continue

        print(f"-> Router: all providers exhausted for '{query}' — returning empty")
        return []

    def download(self, url: str, output_path: str) -> str:
        """Download from *url* to *output_path* using the last-used provider."""
        if self._last_provider_name and self._last_provider_name in self._providers:
            return self._providers[self._last_provider_name].download(url, output_path)

        # Fallback: try pexels if no provider was recorded
        pexels = self._providers.get("pexels")
        if pexels:
            return pexels.download(url, output_path)

        raise RuntimeError(
            f"AssetRouter: no provider available for download(url='{url}', path='{output_path}')"
        )

    def current_provider_name(self) -> str | None:
        """The name of the provider that handled the last successful search."""
        return self._last_provider_name

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _default_providers() -> dict[str, AssetProvider]:
        """Build the default provider registry.

        Pexels is wrapped in ``AssetLibrary`` for local-first caching.
        Stub providers are instantiated as-is.
        """
        return {
            "pexels": AssetLibrary(provider=PexelsProvider()),
            "pixabay": PixabayProvider(),
            "nasa": NasaMediaProvider(),
            "wikimedia": WikimediaCommonsProvider(),
        }

    @staticmethod
    def _load_routes() -> dict[str, list[str]]:
        """Load per-category priority lists from YAML config, falling back
        to ``_DEFAULT_ROUTES``."""
        cfg = get_config("asset_routing.routes", None)
        if cfg and isinstance(cfg, dict):
            return {
                k: v if isinstance(v, list) else ["pexels"]
                for k, v in cfg.items()
            }
        return dict(_DEFAULT_ROUTES)
