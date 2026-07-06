"""
assets — Asset management components.

Exported symbols:
- AssetCache
- AssetLibrary
- TopicClassifier
- AssetRouter
"""

from .asset_cache import AssetCache
from .asset_library import AssetLibrary
from .topic_classifier import TopicClassifier
from .asset_router import AssetRouter

__all__ = [
    "AssetCache",
    "AssetLibrary",
    "TopicClassifier",
    "AssetRouter",
]
