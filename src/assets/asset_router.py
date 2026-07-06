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
from src.providers.asset_provider import AssetProvider, PexelsProvider, PixabayProvider
from src.providers.stubs import NasaMediaProvider, WikimediaCommonsProvider
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

    # ── Multi-query search ────────────────────────────────────────────

    def multi_query_search(
        self,
        queries: list[str],
        min_acceptable_score: float = 0.75,
        max_attempts: int = 15,
        diversity_weighting: float = 0.2,
        **kwargs,
    ) -> dict:
        """Search for assets using multiple queries, stopping on the first
        sufficiently high-quality result.

        Iterates through *queries* in order.  For each query, searches
        providers in priority order.  If the best result exceeds
        *min_acceptable_score*, returns immediately.  Otherwise continues
        to the next query.  When no single query meets the threshold,
        returns the highest-scoring result across all queries (optionally
        boosted by diversity bonus).

        Parameters
        ----------
        queries : list[str]
            Diverse search queries (from a SearchPlanner).
        min_acceptable_score : float
            Score threshold to accept a result without further queries.
        max_attempts : int
            Maximum total provider calls across all queries.
        diversity_weighting : float
            Bonus weight for diversity (0 = pure quality, 1 = pure diversity).
        **kwargs
            Additional keyword args passed to each ``search()`` call
            (e.g. ``target_duration``).

        Returns
        -------
        dict
            ``{
                "assets": [...],       # Best asset list (or empty)
                "selected_query": str,  # Query that produced the assets
                "provider_name": str,   # Provider that returned the assets
                "selected_score": float,# Quality score of the best asset
                "query_log": [...],     # Per-query attempt log
            }``
        """
        query_log: list[dict] = []
        best_overall: list | None = None
        best_score: float = -1.0
        best_query: str = ""
        best_provider: str = ""
        attempts = 0

        for query in queries:
            if attempts >= max_attempts:
                query_log.append({
                    "query": query,
                    "status": "skipped",
                    "reason": "max_attempts_reached",
                })
                continue

            entry: dict[str, object] = {"query": query, "tried_providers": []}
            provider_order = self._routes.get(
                self._category, self._routes.get("General", [])
            )

            for provider_name in provider_order:
                if attempts >= max_attempts:
                    break
                attempts += 1

                provider = self._providers.get(provider_name)
                if provider is None:
                    continue

                # Skip stubs
                if provider.__class__.__name__.endswith("StubAssetProvider") or \
                   type(provider).__module__.endswith("stubs"):
                    provider.search(query, **kwargs)
                    entry["tried_providers"].append(
                        {"provider": provider_name, "status": "stub_skipped"}
                    )
                    continue

                try:
                    results = provider.search(query, **kwargs)
                    entry["tried_providers"].append({
                        "provider": provider_name,
                        "status": "ok" if results else "empty",
                        "count": len(results) if results else 0,
                    })

                    if results:
                        # Score the top result (it's already sorted best-first)
                        top = results[0]
                        score = self._score_top_asset(top, **kwargs)

                        # Apply diversity bonus: penalise if very similar
                        # to the current best (simple ratio-based heuristic)
                        diversity_bonus = self._diversity_bonus(
                            query, best_score, diversity_weighting
                        )
                        adjusted = score + diversity_bonus

                        entry["score"] = score
                        entry["adjusted_score"] = round(adjusted, 4)

                        if adjusted > best_score:
                            best_overall = results
                            best_score = adjusted
                            best_query = query
                            best_provider = provider_name
                            entry["selected"] = True

                            # Early exit: score exceeds threshold
                            if score >= min_acceptable_score:
                                entry["early_exit"] = True
                                query_log.append(entry)
                                print(
                                    "-> Multi-query: accepted '"
                                    f"{query}' (score={score:.3f} >= "
                                    f"{min_acceptable_score}) \u2014 early exit"
                                )
                                self._last_query = query
                                self._last_provider_name = provider_name
                                return {
                                    "assets": results,
                                    "selected_query": query,
                                    "provider_name": provider_name,
                                    "selected_score": score,
                                    "query_log": query_log,
                                }
                except Exception as e:
                    entry["tried_providers"].append({
                        "provider": provider_name,
                        "status": "error",
                        "error": str(e),
                    })
                    continue

            query_log.append(entry)

        # ── No query met the threshold; return the best we found ──────
        if best_overall:
            print(
                f"-> Multi-query: no query met threshold "
                f"({min_acceptable_score}), using best: '"
                f"{best_query}' (score={best_score:.3f})"
            )
            self._last_query = best_query
            self._last_provider_name = best_provider
            return {
                "assets": best_overall,
                "selected_query": best_query,
                "provider_name": best_provider,
                "selected_score": best_score,
                "query_log": query_log,
            }

        print("-> Multi-query: all queries returned no results")
        return {
            "assets": [],
            "selected_query": "",
            "provider_name": "",
            "selected_score": -1.0,
            "query_log": query_log,
        }

    @staticmethod
    def _score_top_asset(result: dict, **kwargs) -> float:
        """Extract or compute a quality score for the top asset result.

        The score is approximated from resolution and HD bonus when the
        result is already sorted (best-first by the provider).  This is
        a lightweight fallback for the search planner's early-exit logic;
        precise scoring is done by the provider natively.
        """
        video_files = result.get("video_files", [])
        w = result.get("width", 0) or 0
        h = result.get("height", 0) or 0
        dur = result.get("duration", 0) or 0

        # Resolution score (same formula as PexelsProvider)
        res_score = min((w * h) / (1920.0 * 1080.0), 1.0) if w * h > 0 else 0.0

        # HD bonus
        has_hd = any(vf.get("quality") == "hd" for vf in video_files)
        hd_score = 1.0 if has_hd else 0.0

        # Duration match (neutral if unknown)
        target = kwargs.get("target_duration")
        if target and target > 0 and dur > 0:
            ratio = dur / target
            dur_score = max(0.0, 1.0 - abs(1.0 - ratio) * 0.5)
        else:
            dur_score = 0.5

        w_res = get_config("providers.pexels.scoring.resolution_weight", 0.40)
        w_dur = get_config("providers.pexels.scoring.duration_match_weight", 0.40)
        w_hd = get_config("providers.pexels.scoring.hd_bonus_weight", 0.20)

        return round(w_res * res_score + w_dur * dur_score + w_hd * hd_score, 4)

    @staticmethod
    def _diversity_bonus(
        query: str,
        current_best_score: float,
        diversity_weighting: float,
    ) -> float:
        """Compute a diversity bonus for a new query relative to the
        current best score.

        When no query has been selected yet (current_best_score < 0),
        the bonus is 0.  Otherwise, queries with different keyword tokens
        receive a small bonus proportional to *diversity_weighting*.
        """
        if current_best_score < 0:
            return 0.0
        # A simple heuristic: each new query gets a small diversity bonus
        # proportional to the diversity weighting.  In a more sophisticated
        # implementation this would compare embeddings of returned assets.
        return diversity_weighting * 0.1

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

        Real providers (Pexels, Pixabay) are wrapped in ``AssetLibrary``
        for local-first caching.  Stub providers are instantiated as-is.
        """
        return {
            "pexels": AssetLibrary(provider=PexelsProvider()),
            "pixabay": AssetLibrary(provider=PixabayProvider()),
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
