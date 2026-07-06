"""
planner — Story planning engine for the video_engine pipeline.

Provides a two-phase planning workflow:
1. **Outline generation** — creates a narrative arc with scene roles.
2. **Scene generation** — produces rich scene descriptions from the outline.

Keeps the planner provider-independent by depending only on ``LLMProvider``.
"""

from .planner import StoryPlanner

__all__ = ["StoryPlanner"]
