"""Font file resolution for publishing assets.

Finds bundled/system DejaVu Sans (regular/bold) font files so thumbnail
rendering never depends on Manim's internal font discovery. All lookups
are deterministic: the first existing path in a fixed candidate list wins.
"""

from __future__ import annotations

import os
from typing import Optional

# StyleSpec v1 declares "DejaVu Sans" as the engine's font family. These are
# the common system locations, checked in order.
_DEJAVU_CANDIDATES = {
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/local/share/fonts/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/DejaVuSans.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/local/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/DejaVuSans-Bold.ttf",
    ],
}

_VALID_WEIGHTS = frozenset(_DEJAVU_CANDIDATES)


def find_font(weight: str = "regular") -> Optional[str]:
    """Return the first existing DejaVu Sans font file for ``weight``.

    ``weight`` is one of ``"regular"`` or ``"bold"``. Returns ``None`` when
    no candidate path exists (callers then fall back to PIL's default font
    or a plain SVG).
    """
    weight = weight.lower()
    if weight not in _VALID_WEIGHTS:
        raise ValueError(f"unknown font weight {weight!r}; expected one of {sorted(_VALID_WEIGHTS)}")
    for path in _DEJAVU_CANDIDATES[weight]:
        if os.path.isfile(path):
            return path
    return None
