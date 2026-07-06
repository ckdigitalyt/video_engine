"""
asset_provider.py — Abstract asset provider and concrete implementations.

Defines the AssetProvider interface, then implements:
- PexelsProvider (stock video search / download)
"""

import os
import requests
from abc import ABC, abstractmethod

from src.utils.config import get_config


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
    """Asset provider backed by the Pexels video API."""

    def __init__(self):
        self._api_key = os.environ.get("PEXELS_API_KEY")
        self._base_url = get_config("providers.pexels.base_url", "https://api.pexels.com/videos/search")
        self._per_page = get_config("providers.pexels.per_page", 5)
        self._orientation = get_config("providers.pexels.orientation", "landscape")

    def search(self, query: str, **kwargs) -> list:
        headers = {"Authorization": self._api_key}
        url = f"{self._base_url}?query={query}&per_page={self._per_page}&orientation={self._orientation}"
        res = requests.get(url, headers=headers).json()
        return res.get("videos", [])

    def download(self, url: str, output_path: str) -> str:
        resp = requests.get(url)
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path
