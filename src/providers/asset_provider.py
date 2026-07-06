"""
asset_provider.py — Abstract asset provider and concrete implementations.

Defines the AssetProvider interface, then implements:
- PexelsProvider (stock video search / download)
"""

import os
import requests
from abc import ABC, abstractmethod

from src.utils.config import get_config
from src.assets.asset_cache import AssetCache


# ── Abstract base ──────────────────────────────────────────────────────────

class AssetProvider(ABC):
    """Interface for media-asset search and download."""

    @abstractmethod
    def search(self, query: str, **kwargs) -> list:
        """
        Search for assets matching *query*.

        Returns a list of item dicts; the exact schema is provider-specific.
        """
        ...

    @abstractmethod
    def download(self, url: str, output_path: str) -> str:
        """
        Download from *url* to *output_path*.

        Returns the local path of the downloaded file.
        """
        ...


# ── Pexels ─────────────────────────────────────────────────────────────────

class PexelsProvider(AssetProvider):
    """Asset provider backed by the Pexels video API, with SQLite cache."""

    def __init__(self, cache: AssetCache | None = None):
        self._api_key = os.environ.get("PEXELS_API_KEY")
        self._base_url = get_config("providers.pexels.base_url", "https://api.pexels.com/videos/search")
        self._per_page = get_config("providers.pexels.per_page", 5)
        self._orientation = get_config("providers.pexels.orientation", "landscape")
        self._cache = cache or AssetCache()

    def search(self, query: str, **kwargs) -> list:
        # ── Check cache first ──────────────────────────────────────────
        cached = self._cache.lookup("pexels", query)
        if cached is not None:
            print(f"-> Cache HIT: '{query}' → {cached['local_path']}")
            # Return a mock result so the orchestrator's existing workflow
            # (take videos[0]["video_files"][0]["link"]) picks up the cached URL.
            return [{"video_files": [{"link": cached["asset_url"]}]}]

        print(f"-> Cache MISS: '{query}' — calling Pexels API")
        headers = {"Authorization": self._api_key}
        url = f"{self._base_url}?query={query}&per_page={self._per_page}&orientation={self._orientation}"
        res = requests.get(url, headers=headers).json()
        results = res.get("videos", [])

        # Pre-register the first result URL so a future lookup (e.g. on
        # a re-run of the same query) finds it, even before download.
        if results:
            first_url = results[0]["video_files"][0]["link"]
            self._cache.register("pexels", query, first_url)

        return results

    def download(self, url: str, output_path: str) -> str:
        # ── Skip download if file already exists ───────────────────────
        if os.path.exists(output_path):
            print(f"-> Already on disk: {output_path}")
            self._cache.touch(output_path)
            return output_path

        # ── Download ───────────────────────────────────────────────────
        print("-> Downloading from Pexels…")
        resp = requests.get(url)
        with open(output_path, "wb") as f:
            f.write(resp.content)

        # Update cache with the local path so future lookups resolve fully
        self._cache.update_local_path(url, output_path)
        print(f"-> Saved: {output_path}")

        return output_path
