"""Layout zones — semantic placement so objects never arbitrarily overlap
(directive §10).

Objects are assigned to named zones (Top/Center/Bottom/Left/Right/Focus/
Support).  The layout engine computes concrete Manim coordinates per zone,
and knows which objects are legal to coexist (one focal + support per region).
"""

from __future__ import annotations

from manim import DOWN, LEFT, RIGHT, UP, ORIGIN

from engine.config.loader import get_style

# Fraction of the frame each zone occupies (Manim unit space is usually
# [-7,7]x[-4,4] for a 16:9 frame).
_ZONE_OFFSETS = {
    "top": {"x": 0.0, "y": 3.0},
    "center": {"x": 0.0, "y": 0.0},
    "bottom": {"x": 0.0, "y": -3.0},
    "left": {"x": -4.0, "y": 0.0},
    "right": {"x": 4.0, "y": 0.0},
    "focus": {"x": 0.0, "y": 1.2},     # main number region
    "support": {"x": 0.0, "y": -1.2},  # equation/result region
}

# Legal coexistences: which object roles may share a zone at once.
# One +support (+ head/subtitle) is fine; two focal is not.
_SUPPORT_ROLES = {"headline", "subtitle", "equation", "descending", "ascending",
                  "caption", "label"}
_FOCAL_ROLES = {"number_main", "attractor", "result", "digit", "number"}


def zone_offset(zone: str):
    off = _ZONE_OFFSETS.get(zone.lower())
    if not off:
        return ORIGIN
    return RIGHT * off["x"] + UP * off["y"]


def zone_conflict(ids_in_zone: list[tuple[str, str]]) -> list[str]:
    """ids_in_zone: list of (oid, role).  Returns overlap conflict strings
    if two focal objects share a zone.

    A focal + support (or support + support) may share; two focal may not.
    """
    conflicts: list[str] = []
    for zone, entries in _group_by_zone(ids_in_zone).items():
        focal = [oid for oid, role in entries if role in _FOCAL_ROLES]
        if len(focal) > 1:
            conflicts.append(
                f"zone '{zone}' has multiple focal objects: {', '.join(focal)}"
            )
    return conflicts


def _group_by_zone(entries: list[tuple[str, str]]) -> dict:
    out: dict[str, list] = {}
    # entries carry zone in oid prefix or we default to center
    for oid, role in entries:
        zone = "center"
        out.setdefault(zone, [])
        out[zone].append((oid, role))
    return out


def is_support_role(role: str) -> bool:
    return role in _SUPPORT_ROLES


def is_focal_role(role: str) -> bool:
    return role in _FOCAL_ROLES
