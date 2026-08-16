"""Publishing module: deterministic metadata + thumbnails for video runs.

Public API::

    from engine.publishing import generate_metadata, generate_thumbnail, save

- ``generate_metadata`` — publishing metadata dict from run artifacts (title
  candidates, description, tags, chapters, credits). No LLM, deterministic.
- ``generate_thumbnail`` — 1280x720 thumbnail (Pillow PNG, SVG fallback).
- ``save`` — write a metadata dict to ``<out_dir>/metadata.json``.
"""

from engine.publishing.metadata import generate_metadata, save
from engine.publishing.thumbnail import generate_thumbnail

__all__ = ["generate_metadata", "generate_thumbnail", "save"]
