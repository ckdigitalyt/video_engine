"""
renderer.py — Backward-compatible module-level interface.

Re-exports ``MoviePyRenderer`` and its ``render()`` / ``parse_timeline()``
as module-level functions so existing imports and patches continue to work.

New code should import ``MoviePyRenderer`` from ``src.renderer.moviepy_renderer``
and use it via the ``Renderer`` ABC from ``src.renderer``.
"""

# The compatibility shim runs in src/renderer/moviepy_renderer at import time;
# re-importing it here is safe (module caching means it runs exactly once).

from src.renderer.moviepy_renderer import MoviePyRenderer, parse_timeline

# Module-level backward-compat references ----------------------------------

_parse_timeline = parse_timeline

_renderer: MoviePyRenderer = MoviePyRenderer()
render_timeline = _renderer.render

# Re-export the class so callers can type-annotate with ``MoviePyRenderer``
# or instantiate their own instance.
__all__ = ["MoviePyRenderer", "_parse_timeline", "parse_timeline", "render_timeline"]
