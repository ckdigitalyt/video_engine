"""
animation.py — Extensible subtitle animation system.

Each animation style is a callable that takes a list of
``(word_text, start_ms, end_ms)`` tuples and returns a list of
``TextClip``-compatible dicts with per-frame visual properties.

New styles can be added by implementing the same signature and
registering in ``ANIMATION_STYLES``.
"""

from __future__ import annotations

from typing import Any, Callable

# ── Type alias ────────────────────────────────────────────────────────────

WordTiming = dict[str, Any]
"""
A word timing entry::

    {
        "word": str,
        "start_ms": float,
        "end_ms": float,
        "line": int,
        "is_first_in_line": bool,
        "is_last_in_line": bool,
    }

Produced by ``SubtitleEngine.generate()``.
"""

AnimationFn = Callable[[list[WordTiming]], list[WordTiming]]
"""Signature: (word_timings) -> word_timings with animation fields added."""


# ── Styles ────────────────────────────────────────────────────────────────


def _static(words: list[WordTiming]) -> list[WordTiming]:
    """No animation — text is fully visible during its time range."""
    for w in words:
        w["anim_opacity"] = 1.0
    return words


def _fade(words: list[WordTiming]) -> list[WordTiming]:
    """Fade-in at start, fade-out at end of each word."""
    fade_duration = 80  # ms
    for w in words:
        dur = w["end_ms"] - w["start_ms"]
        fade = min(fade_duration, dur / 3)
        w["anim_opacity"] = 1.0
        w["fade_in_ms"] = fade
        w["fade_out_ms"] = fade
    return words


def _karaoke(words: list[WordTiming]) -> list[WordTiming]:
    """Karaoke style — only the current word is highlighted.

    Previous words are dimmed, next words are invisible.
    Each word gets a ``highlight`` field (0 = dim, 1 = bright).
    Timed so exactly one word is highlighted at any moment.
    """
    highlight_duration = 80  # ms highlight fade
    for i, w in enumerate(words):
        dur = w["end_ms"] - w["start_ms"]
        fade = min(highlight_duration, dur / 3)
        w["anim_opacity"] = 1.0
        w["fade_in_ms"] = fade
        w["fade_out_ms"] = fade
        # Karaoke-specific: dimmed state for previous words
        w["highlight"] = 1.0  # will be modified at render time
        w["prev_dim"] = 0.35  # opacity for previously spoken words
    return words


def _pop(words: list[WordTiming]) -> list[WordTiming]:
    """Pop — each word scales up slightly when it appears."""
    for w in words:
        dur = w["end_ms"] - w["start_ms"]
        fade = min(60, dur / 4)
        w["anim_opacity"] = 1.0
        w["fade_in_ms"] = fade
        w["fade_out_ms"] = fade
        w["pop_scale"] = 1.15  # scale up at appearance
    return words


# ── Registry ──────────────────────────────────────────────────────────────

ANIMATION_STYLES: dict[str, AnimationFn] = {
    "static": _static,
    "fade": _fade,
    "karaoke": _karaoke,
    "pop": _pop,
}

DEFAULT_STYLE = "fade"


def get_animation_style(name: str) -> AnimationFn:
    """Return the animation function for *name*.

    Falls back to ``DEFAULT_STYLE`` if *name* is not found.
    """
    fn = ANIMATION_STYLES.get(name)
    if fn is None:
        fn = ANIMATION_STYLES[DEFAULT_STYLE]
    return fn


def get_animation_clips(
    words: list[WordTiming],
    style: str,
    font_size: int,
    bottom_margin: int,
    max_words_per_line: int,
    resolution: tuple[int, int],
) -> list[dict]:
    """
    Produce a list of clip-description dicts suitable for the renderer.

    Each dict contains::

        {
            "text": str,
            "start_ms": float,
            "end_ms": float,
            "font_size": int,
            "bottom_margin": int,
            "max_words_per_line": int,
            "animation": str,
            "opacity": float,
            "fade_in_ms": float,
            "fade_out_ms": float,
        }

    The renderer is responsible for converting these into actual visual
    clips using its own framework (e.g. MoviePy ``TextClip``).
    """
    fn = get_animation_style(style)
    words = fn(words)

    clips: list[dict] = []
    for w in words:
        clips.append({
            "text": w.get("word", ""),
            "start_ms": w["start_ms"],
            "end_ms": w["end_ms"],
            "font_size": font_size,
            "bottom_margin": bottom_margin,
            "max_words_per_line": max_words_per_line,
            "animation": style,
            "opacity": w.get("anim_opacity", 1.0),
            "fade_in_ms": w.get("fade_in_ms", 0),
            "fade_out_ms": w.get("fade_out_ms", 0),
        })
    return clips
