"""
effects — Cinematic motion and transition engines for the video_engine pipeline.

Provides renderer-agnostic effect descriptors so future renderers can reuse
the same motion and transition logic without depending on MoviePy.

* ``MotionEngine`` — generates Ken Burns-style camera motion per clip.
* ``TransitionEngine`` — selects transitions between adjacent clips.
"""

from .motion import MotionEngine
from .transitions import TransitionEngine

__all__ = ["MotionEngine", "TransitionEngine"]
