"""
providers — Abstract provider interfaces and concrete implementations.

Exported symbols:
- LLMProvider (ABC)
- DeepSeekProvider
- GeminiProvider
- AssetProvider (ABC)
- PexelsProvider
- PixabayProvider
- TTSProvider (ABC)
- KokoroProvider
- StubAssetProvider
- NasaMediaProvider
- WikimediaCommonsProvider
"""

from .llm_provider import LLMProvider, DeepSeekProvider, GeminiProvider
from .asset_provider import AssetProvider, PexelsProvider, PixabayProvider
from .tts_provider import TTSProvider, KokoroProvider
from .asset_provider import AssetProvider, PexelsProvider, PixabayProvider, NasaMediaProvider, WikimediaCommonsProvider

# StubAssetProvider is no longer used — all providers are real implementations.
# Keep a reference for backward compatibility.
StubAssetProvider = AssetProvider

__all__ = [
    "LLMProvider",
    "DeepSeekProvider",
    "GeminiProvider",
    "AssetProvider",
    "PexelsProvider",
    "PixabayProvider",
    "NasaMediaProvider",
    "WikimediaCommonsProvider",
    "TTSProvider",
    "KokoroProvider",
    "StubAssetProvider",
]
