"""
stubs.py — Stub asset providers for future API integration.

These providers implement the ``AssetProvider`` interface but are not
yet backed by a real API.  They exist so that the ``AssetRouter`` can
reference them by name and gracefully skip them when they are not yet
configured/implemented.

When adding a real provider:
1. Subclass ``StubAssetProvider`` (or ``AssetProvider`` directly).
2. Replace ``search()`` with a real API call.
3. Replace ``download()`` with a real download implementation.
4. Register the provider in the routing table in ``configs/providers.yaml``.
"""

from src.providers.asset_provider import AssetProvider


class StubAssetProvider(AssetProvider):
    """Base class for non-functional provider stubs.

    Subclasses override only the provider name.  ``search()`` returns
    an empty list and ``download()`` raises ``NotImplementedError``.
    """

    PROVIDER_NAME = "stub"

    def search(self, query: str, **kwargs) -> list:
        print(f"-> [{self.PROVIDER_NAME}] Stub: '{query}' — not yet implemented, skipping.")
        return []

    def download(self, url: str, output_path: str) -> str:
        raise NotImplementedError(
            f"[{self.PROVIDER_NAME}] download() is not implemented. "
            f"Called with url='{url}' path='{output_path}'"
        )


class NasaMediaProvider(StubAssetProvider):
    """Stub for NASA Image and Video Library API.

    Future implementation: https://images-api.nasa.gov
    """
    PROVIDER_NAME = "nasa"


class PixabayProvider(StubAssetProvider):
    """Stub for Pixabay video API.

    Future implementation: https://pixabay.com/api/videos/
    """
    PROVIDER_NAME = "pixabay"


class WikimediaCommonsProvider(StubAssetProvider):
    """Stub for Wikimedia Commons API.

    Future implementation: https://commons.wikimedia.org/w/api.php
    """
    PROVIDER_NAME = "wikimedia"
