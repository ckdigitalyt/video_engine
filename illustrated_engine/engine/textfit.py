"""V15 — on-screen text fitting with the real font metrics.

V14 emitted titles at a fixed size with no measurement, so most scene titles
ran off the 1080 px frame. fit_text measures with the same TTF the renderer
loads (assets/fonts, staged into Remotion via @font-face) and returns the
largest size <= `size` at which the text fits `max_w` in <= `max_lines`
lines (greedy word wrap). It raises TextFitError when even `min_size`
cannot fit — the caller must shorten the copy, never let it overflow.

text_bbox gives the rendered block rect for the gate's bounds pre-flight.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
DISPLAY = "BebasNeue-Regular.ttf"
BODY = "Inter-Variable.ttf"
LINE_GAP = 1.05  # line height = size * LINE_GAP (renderer uses the same)


class TextFitError(ValueError):
    pass


@lru_cache(maxsize=256)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def text_width(text: str, font: str, size: int, spacing: float = 0.0) -> float:
    f = _font(font, int(size))
    return f.getlength(text) + spacing * max(0, len(text) - 1)


def _wrap(words: list, font: str, size: int, max_w: float,
          spacing: float) -> list:
    lines, cur = [], []
    for w in words:
        cand = " ".join(cur + [w])
        if cur and text_width(cand, font, size, spacing) > max_w:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def fit_text(text: str, *, max_w: float, size: int, min_size: int = 28,
             max_lines: int = 2, font: str = DISPLAY,
             spacing: float = 0.0) -> dict:
    """-> {lines, size, width, height}. Deterministic."""
    words = str(text).split()
    if not words:
        raise TextFitError("empty text")
    s = int(size)
    while s >= min_size:
        lines = _wrap(words, font, s, max_w, spacing)
        widest = max(text_width(l, font, s, spacing) for l in lines)
        if len(lines) <= max_lines and widest <= max_w:
            return {"lines": lines, "size": s, "width": round(widest, 1),
                    "height": round(s * LINE_GAP * len(lines), 1)}
        s -= 2
    raise TextFitError(f"{text!r} does not fit {max_w:.0f}px in "
                       f"{max_lines} lines at >= {min_size}px")


def text_bbox(lines: list, size: float, x: float, y: float, anchor: str,
              font: str = DISPLAY, spacing: float = 0.0) -> tuple:
    """Rendered block rect (x0, y0, x1, y1); y is the first baseline."""
    widest = max(text_width(l, font, int(size), spacing) for l in lines)
    x0 = {"middle": x - widest / 2, "end": x - widest}.get(anchor, x)
    top = y - size * 0.8
    bottom = y + size * LINE_GAP * (len(lines) - 1) + size * 0.2
    return (x0, top, x0 + widest, bottom)
