"""
subtitles — Word-level subtitle generation, timing, formatting, and animation.

Provides the ``SubtitleEngine`` (main entry point), format helpers for
SRT / WebVTT / JSON, and an extensible animation system.
"""

from .engine import SubtitleEngine
from .animation import get_animation_clips

__all__ = ["SubtitleEngine", "get_animation_clips"]
