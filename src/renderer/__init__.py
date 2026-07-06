"""
renderer — Abstract renderer interface and implementations.

Provides a pluggable ``Renderer`` abstract base class so the orchestrator
depends only on the abstraction, not on any specific rendering engine.
"""

from abc import ABC, abstractmethod
from typing import Optional


class Renderer(ABC):
    """Abstract interface for video rendering.

    Implementations consume a timeline JSON file and produce the final
    rendered video file at the given output path.  Optional subtitle
    data can be passed via a separate subtitle timeline.
    """

    @abstractmethod
    def render(
        self,
        timeline_path: str,
        output_path: str,
        subtitles: Optional[list[dict]] = None,
    ) -> None:
        """Render *timeline_path* (JSON) to *output_path* (mp4).

        Args:
            timeline_path: Path to the timeline JSON file produced by
                the TimelineBuilder.
            output_path: Destination path for the rendered video.
            subtitles: Optional list of word-timing dicts from the
                SubtitleEngine; each entry describes a subtitle word
                with timing, text, and animation metadata.
        """
        ...
