"""
manim_provider.py — Manim as a first-class asset provider.

Bypasses stock footage entirely when a concept is better explained by
animation.  The EditorialPlanner and Visual Knowledge Library decide
when Manim is appropriate — not the fallback chain.

This provider implements the AssetProvider interface so it can be used
transparently by AssetIntentRouter.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Optional

from src.assets.visual_intent import AssetType
from src.providers.asset_provider import AssetProvider

# ── Match known ManimTemplate topics to ManimTopic enums ──────────────

_MANIM_TOPIC_MAP: dict[str, str] = {
    "drake equation": "drake_equation",
    "drake": "drake_equation",
    "black hole": "black_hole_geometry",
    "black hole geometry": "black_hole_geometry",
    "spacetime curvature": "spacetime_curvature",
    "spacetime": "spacetime_curvature",
    "gravitational lensing": "gravitational_lensing",
    "redshift": "redshift",
    "doppler shift": "redshift",
    "big bang": "big_bang_timeline",
    "cosmic timeline": "big_bang_timeline",
    "solar system": "solar_system",
    "planet orbit": "solar_system",
    "exoplanet": "exoplanets",
    "transit method": "exoplanets",
    "gravitational waves": "gravitational_waves",
    "ligo": "gravitational_waves",
    "nuclear fusion": "nuclear_fusion",
    "fusion reaction": "nuclear_fusion",
    "neural network": "neural_networks",
    "deep learning": "neural_networks",
    "dna": "dna",
    "dna replication": "dna",
    "double helix": "dna",
    "evolution": "evolution",
    "tree of life": "evolution",
    "natural selection": "evolution",
    "compound interest": "compound_interest",
    "exponential growth": "compound_interest",
    "probability": "probability",
    "bayes theorem": "probability",
    "normal distribution": "probability",
    "periodic table": "periodic_table",
    "elements": "periodic_table",
    "photosynthesis": "photosynthesis",
    "calvin cycle": "photosynthesis",
    "quantum mechanics": "quantum_mechanics",
    "wave particle duality": "quantum_mechanics",
    "double slit": "quantum_mechanics",
    "electromagnetism": "electromagnetism",
    "maxwell equations": "electromagnetism",
    "em spectrum": "electromagnetism",
    "thermodynamics": "thermodynamics",
    "entropy": "thermodynamics",
    "supply and demand": "supply_demand",
    "supply demand": "supply_demand",
    "market equilibrium": "supply_demand",
    "cmb": "cmb_formation",
    "cosmic microwave background": "cmb_formation",
    "dark matter": "dark_matter_halo",
    "roman empire": "roman_timeline",
    "industrial revolution": "industrial_timeline",
}

_MANIM_CACHE_DIR = "cache/manim"


class ManimProvider(AssetProvider):
    """Manim as a first-class asset provider.

    If a search query matches a known Manim template topic, this provider
    renders the animation and returns it as an asset result.  Otherwise
    returns empty (letting the next provider in the chain handle it).
    """

    def __init__(self, output_dir: str = _MANIM_CACHE_DIR):
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)
        self._cached_results: dict[str, list[dict]] = {}
        self._last_rendered: str = ""

    def search(self, query: str, **kwargs: Any) -> list[dict]:
        """Search for a Manim animation matching the query topic.

        If the query matches a known template, returns a single result
        with the cached (or freshly rendered) animation file path.
        """
        topic_key = self._match_topic(query)
        if not topic_key:
            return []

        # Check cache first
        cache_key = topic_key.lower().replace(" ", "_")
        cached_path = os.path.join(self._output_dir, f"{cache_key}.mp4")

        if os.path.exists(cached_path):
            self._last_rendered = cached_path
            return [self._make_result(cached_path, topic_key, query)]

        # Attempt render
        try:
            from src.manim.planner import ManimPlanner, ManimTopic

            planner = ManimPlanner(output_dir=self._output_dir)

            # Map topic_key → ManimTopic enum
            topic_enum = None
            for member in ManimTopic:
                if member.value == topic_key:
                    topic_enum = member
                    break

            if topic_enum is None:
                return []

            plan = planner.plan(topic=topic_enum)
            if not plan.script_path:
                return []

            output = planner.render(plan)
            if output and os.path.exists(output):
                self._last_rendered = output
                return [self._make_result(output, topic_key, query)]

        except (ImportError, Exception) as e:
            print(f"[ManimProvider] Render failed for '{topic_key}': {e}")

        return []

    def download(self, url: str, output_path: str) -> str:
        """Copy the cached Manim render to output_path."""
        src = url if os.path.exists(url) else self._last_rendered
        if not src or not os.path.exists(src):
            raise FileNotFoundError(f"Manim render not found: {url}")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copy2(src, output_path)
        return output_path

    def _match_topic(self, query: str) -> str | None:
        """Find the best matching Manim topic for a query string."""
        query_lower = query.lower().strip()

        if query_lower in _MANIM_TOPIC_MAP:
            return _MANIM_TOPIC_MAP[query_lower]

        for keyword, topic in _MANIM_TOPIC_MAP.items():
            if keyword in query_lower:
                return topic

        return None

    def _make_result(self, path: str, topic: str, query: str) -> dict:
        return {
            "url": path,
            "provider": "manim",
            "asset_type": "manim",
            "duration": 10.0,
            "width": 1920,
            "height": 1080,
            "topic": topic,
            "search_query": query,
            "score": 0.95,
        }
