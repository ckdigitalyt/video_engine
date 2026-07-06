"""
aesthetic_agent.py — Aesthetic Consistency Agent.

Tracks the visual style of every selected asset and detects abrupt
changes between scenes.  When an asset would cause an incompatible
style transition (e.g. photorealistic scene followed by cartoon), the
agent rejects it and requests a replacement.

Style categories
----------------
- real_drone     : Real-world drone footage
- real_stock     : Standard real-world stock footage
- historic_image : Sepia/B&W historical photographs
- space_photo    : NASA / deep space astrophoto
- archival_film  : Old film footage
- cgi_render     : Computer-generated imagery
- infographic    : 2D diagrams / charts
- macro          : Extreme close-up / macro photography
- aerial         : Aerial / satellite imagery
- unknown        : Default / unclassified
"""

from __future__ import annotations

import re
from typing import Optional

from src.utils.config import get_config
from src.director.visual_style import VisualStyle


# ── Style classification ───────────────────────────────────────────────

def _classify_style(
    asset: dict,
    provider: str,
    query: str,
    category: str,
) -> str:
    """Classify an asset's visual style category.

    Uses provider info, asset metadata, and query context to determine
    the visual style category.
    """
    # Wikimedia = historical images
    if provider == "wikimedia":
        return "historic_image"

    # NASA = space
    if provider == "nasa":
        return "space_photo"

    # Check asset metadata
    raw = asset.get("_raw", {})

    # Check tags for style hints
    tags = raw.get("tags", "")
    if isinstance(tags, str) and tags:
        tags_lower = tags.lower()
        if any(w in tags_lower for w in ("drone", "aerial", "satellite")):
            return "aerial"
        if any(w in tags_lower for w in ("microscope", "macro", "extreme close")):
            return "macro"
        if any(w in tags_lower for w in ("cgi", "3d", "render", "animation", "computer generated")):
            return "cgi_render"
        if any(w in tags_lower for w in ("vintage", "old film", "retro", "archive", "sepia")):
            return "archival_film"

    # Check query for style hints
    query_lower = query.lower()
    if any(w in query_lower for w in ("drone", "aerial", "satellite")):
        return "aerial"
    if any(w in query_lower for w in ("cgi", "3d", "render", "animation")):
        return "cgi_render"
    if any(w in query_lower for w in ("microscope", "macro", "extreme close")):
        return "macro"

    # Category-based defaults
    if category == "Space":
        return "space_photo"
    if category == "History":
        return "historic_image"

    # Default: real stock footage
    return "real_stock"


# ── Compatibility matrix ───────────────────────────────────────────────

# Two styles are compatible if their entry exists in this set
_COMPATIBLE_PAIRS: set[tuple[str, str]] = {
    # Same category is always compatible
    ("real_drone", "real_drone"),
    ("real_stock", "real_stock"),
    ("real_drone", "real_stock"),  # Drone + stock are similar
    ("real_stock", "real_drone"),
    ("historic_image", "historic_image"),
    ("historic_image", "archival_film"),  # Historical images + old film
    ("archival_film", "historic_image"),
    ("archival_film", "archival_film"),
    ("space_photo", "space_photo"),
    ("space_photo", "real_stock"),  # Occasionally compatible
    ("real_stock", "space_photo"),
    ("infographic", "infographic"),
    ("cgi_render", "cgi_render"),
    ("cgi_render", "infographic"),  # 3D renders + infographics
    ("infographic", "cgi_render"),
    ("aerial", "aerial"),
    ("aerial", "real_drone"),  # Aerial + drone
    ("real_drone", "aerial"),
    ("aerial", "real_stock"),
    ("real_stock", "aerial"),
    ("macro", "macro"),
    ("macro", "real_stock"),
    ("real_stock", "macro"),
}

# Style categories that are NEVER compatible with each other
_INCOMPATIBLE: set[tuple[str, str]] = {
    ("historic_image", "cgi_render"),
    ("cgi_render", "historic_image"),
    ("historic_image", "infographic"),
    ("infographic", "historic_image"),
    ("archival_film", "cgi_render"),
    ("cgi_render", "archival_film"),
    ("archival_film", "infographic"),
    ("infographic", "archival_film"),
    ("historic_image", "space_photo"),
    ("space_photo", "historic_image"),
}


class AestheticAgent:
    """Ensures visual consistency across scenes.

    Maintains a rolling history of asset style categories and rejects
    assets that would cause incompatible transitions.

    Parameters
    ----------
    visual_style : VisualStyle | None
        The global visual style to enforce.
    enabled : bool, optional
        Override for ``visual_director.aesthetic_agent.enabled``.
    window_size : int, optional
        Number of recent styles to consider for consistency checks.
    """

    def __init__(
        self,
        visual_style: Optional[VisualStyle] = None,
        enabled: Optional[bool] = None,
        window_size: Optional[int] = None,
    ):
        self._style = visual_style or VisualStyle()
        self._enabled = enabled if enabled is not None else get_config(
            "visual_director.aesthetic_agent.enabled", True
        )
        self._window_size = window_size if window_size is not None else get_config(
            "visual_director.aesthetic_agent.window_size", 3
        )
        self._history: list[str] = []

    # ── Public API ─────────────────────────────────────────────────────

    def check_asset(
        self,
        asset: dict,
        provider: str,
        query: str,
        category: str,
    ) -> tuple[bool, str]:
        """Check if *asset* is aesthetically compatible with previous scenes.

        Returns (accepted, reason).
        """
        if not self._enabled:
            return True, "aesthetic_agent disabled"

        style_cat = _classify_style(asset, provider, query, category)

        # First asset — always accept
        if not self._history:
            self._history.append(style_cat)
            return True, f"first asset: style={style_cat}"

        # Check against global style's avoid list
        if self._style.aesthetic in ("photorealistic", "documentary", "archival"):
            if style_cat in ("cgi_render", "infographic"):
                # Check if the asset is explicitly tagged as CGI
                raw_tags = asset.get("_raw", {}).get("tags", "")
                if isinstance(raw_tags, str) and "cgi" in raw_tags.lower():
                    return False, (
                        f"style '{style_cat}' incompatible with global "
                        f"aesthetic '{self._style.aesthetic}'"
                    )

        # Check against recent history
        for prev_style in self._history[-self._window_size:]:
            pair = (prev_style, style_cat)

            # Hard incompatible
            if pair in _INCOMPATIBLE:
                return False, (
                    f"style '{style_cat}' incompatible with previous "
                    f"style '{prev_style}'"
                )

            # Not in compatible pairs = potentially problematic
            if pair not in _COMPATIBLE_PAIRS:
                # Allow with a warning but don't reject (unknown styles)
                continue

        # Accept and record
        self._history.append(style_cat)
        return True, f"accepted: style={style_cat}"

    def check_scene_assets(
        self,
        scene_assets: list[dict],
        scene_providers: list[str],
        scene_queries: list[str],
        scene_categories: list[str],
    ) -> tuple[bool, list[str]]:
        """Batch-check aesthetic consistency across a list of scenes.

        Returns (all_accepted, reasons).
        """
        reasons: list[str] = []
        all_ok = True

        for i, (asset, provider, query, cat) in enumerate(
            zip(scene_assets, scene_providers, scene_queries, scene_categories)
        ):
            ok, reason = self.check_asset(asset, provider, query, cat)
            if not ok:
                all_ok = False
            reasons.append(f"  Scene {i}: {reason}")

        return all_ok, reasons

    @property
    def history(self) -> list[str]:
        """Visible style history (read-only view)."""
        return list(self._history)

    def reset(self) -> None:
        """Clear style history (for new video)."""
        self._history.clear()
