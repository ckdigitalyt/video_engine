"""
broll_taxonomy.py — Documentary B-roll taxonomy for approved search templates.

Defines a reusable internal taxonomy of search templates organized by
visual category. Each category contains approved search patterns.
The system should search from this taxonomy, never from raw narration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BrollTemplate:
    """A search template for a specific visual category."""

    name: str
    queries: list[str]
    priority: int = 10
    providers: Optional[list[str]] = None
    min_score: float = 0.0

    def __repr__(self) -> str:
        return f"BrollTemplate({self.name}, {len(self.queries)} queries)"


@dataclass
class BrollCategory:
    """A category in the documentary B-roll taxonomy."""

    name: str
    templates: list[BrollTemplate] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"BrollCategory({self.name}, {len(self.templates)} templates)"


class BrollTaxonomy:
    """Documentary B-roll taxonomy.

    Organized by visual category, each containing approved search templates.
    Never search raw narration — search approved taxonomy.

    Usage::

        taxonomy = BrollTaxonomy()
        templates = taxonomy.get_templates_for_category("Space")
        for tmpl in templates:
            result = router.search(tmpl.queries[0])
    """

    def __init__(self):
        self._categories: dict[str, BrollCategory] = self._build()

    # ── Public API ─────────────────────────────────────────────────────

    def get_templates_for_category(
        self,
        category: str,
        subcategory: str = "",
    ) -> list[BrollTemplate]:
        """Get search templates for a visual category.

        Args:
            category: Top-level category name (Space, Science, etc.).
            subcategory: Optional subcategory filter (Planets, Nebulae, etc.).

        Returns:
            List of BrollTemplate, ordered by priority.
        """
        cat = self._categories.get(category, self._categories.get("General", BrollCategory("General")))
        if subcategory:
            return [t for t in cat.templates if subcategory.lower() in t.name.lower()]
        return sorted(cat.templates, key=lambda t: t.priority)

    def get_all_categories(self) -> list[str]:
        return list(self._categories.keys())

    def get_subcategories(self, category: str) -> list[str]:
        cat = self._categories.get(category)
        if not cat:
            return []
        seen: set[str] = set()
        for t in cat.templates:
            parts = t.name.split(" > ")
            if len(parts) > 1:
                seen.add(parts[1])
            else:
                seen.add(parts[0])
        return sorted(seen)

    def find_matching_templates(
        self,
        keywords: list[str],
        max_results: int = 5,
    ) -> list[BrollTemplate]:
        """Find templates matching a list of keywords.

        Simple keyword matching across all template names and queries.
        """
        kw_lower = [k.lower() for k in keywords]
        matches: list[tuple[int, BrollTemplate]] = []

        for category in self._categories.values():
            for template in category.templates:
                score = 0
                text = (template.name + " " + " ".join(template.queries)).lower()
                for kw in kw_lower:
                    if kw in text:
                        score += 1
                if score > 0:
                    matches.append((score, template))

        matches.sort(key=lambda m: (-m[0], m[1].priority))
        return [m[1] for m in matches[:max_results]]

    # ── Internal: Build the taxonomy ───────────────────────────────────

    @staticmethod
    def _build() -> dict[str, BrollCategory]:
        categories: dict[str, BrollCategory] = {}

        # ── Space ──────────────────────────────────────────────────────
        categories["Space"] = BrollCategory("Space", [
            BrollTemplate("Planets > Rotating planets", [
                "planet rotating in space",
                "planet surface orbit view",
                "planet atmosphere timelapse",
            ], priority=1),
            BrollTemplate("Planets > Planet surfaces", [
                "planet surface landscape",
                "Martian desert landscape",
                "alien planet surface",
            ], priority=2),
            BrollTemplate("Nebulae", [
                "nebula cloud space",
                "star forming nebula",
                "colorful nebula deep space",
            ], priority=1),
            BrollTemplate("Galaxies", [
                "spiral galaxy rotating",
                "galaxy cluster deep space",
                "Andromeda galaxy wide shot",
            ], priority=1),
            BrollTemplate("Galaxies > Starry sky", [
                "starry night sky timelapse",
                "Milky Way galaxy night",
                "stars twinkling night sky",
            ], priority=2),
            BrollTemplate("Astronauts", [
                "astronaut floating in space",
                "astronaut spacewalk",
                "astronaut in spacecraft",
            ], priority=3),
            BrollTemplate("Rocket launches", [
                "rocket launch into space",
                "spacecraft liftoff",
                "rocket ascending through clouds",
            ], priority=3),
            BrollTemplate("Stars", [
                "star field deep space",
                "sun surface corona",
                "binary star system",
            ], priority=1),
            BrollTemplate("Moons", [
                "moon surface craters",
                "moon orbiting planet",
                "full moon night sky",
            ], priority=3),
            BrollTemplate("Telescopes", [
                "radio telescope dish",
                "observatory dome opening",
                "space telescope orbiting",
            ], priority=1),
        ])

        # ── Science ────────────────────────────────────────────────────
        categories["Science"] = BrollCategory("Science", [
            BrollTemplate("Laboratories", [
                "scientist working in laboratory",
                "research laboratory equipment",
                "clean room scientists",
            ], priority=1),
            BrollTemplate("Microscopes", [
                "microscope close up",
                "microscopic cells dividing",
                "laboratory microscope footage",
            ], priority=1),
            BrollTemplate("DNA", [
                "DNA double helix animation",
                "genetic code visualization",
                "DNA strand scientific",
            ], priority=2),
            BrollTemplate("Experiments", [
                "science experiment laboratory",
                "chemical reaction in flask",
                "laboratory test tubes",
            ], priority=2),
            BrollTemplate("Data", [
                "data visualization screen",
                "computer code screen",
                "scientific data graphs",
            ], priority=3),
        ])

        # ── Technology ─────────────────────────────────────────────────
        categories["Technology"] = BrollCategory("Technology", [
            BrollTemplate("Computers", [
                "computer server room",
                "data center servers",
                "computer processor chip",
            ], priority=1),
            BrollTemplate("Robotics", [
                "robot arm moving",
                "industrial robotic automation",
                "humanoid robot hands",
            ], priority=2),
            BrollTemplate("Spacecraft", [
                "satellite orbiting Earth",
                "space station interior",
                "spacecraft docking",
            ], priority=1),
            BrollTemplate("Engineering", [
                "engineer working on machine",
                "mechanical engineering workshop",
                "industrial machinery",
            ], priority=2),
        ])

        # ── Nature ─────────────────────────────────────────────────────
        categories["Nature"] = BrollCategory("Nature", [
            BrollTemplate("Oceans", [
                "ocean waves crashing",
                "deep sea underwater",
                "hydrothermal vent ocean floor",
            ], priority=1),
            BrollTemplate("Forests", [
                "forest aerial drone view",
                "ancient forest trees",
                "plants growing timelapse",
            ], priority=2),
            BrollTemplate("Deserts", [
                "desert landscape aerial",
                "sand dunes at sunset",
                "barren desert wide shot",
            ], priority=2),
            BrollTemplate("Mountains", [
                "mountain peaks aerial",
                "snow capped mountains",
                "mountain landscape scenic",
            ], priority=3),
        ])

        # ── History ────────────────────────────────────────────────────
        categories["History"] = BrollCategory("History", [
            BrollTemplate("Ancient", [
                "ancient ruins archaeological site",
                "historical monument old",
                "ancient civilization artifacts",
            ], priority=1),
            BrollTemplate("Observatories", [
                "ancient observatory stone",
                "historical telescope museum",
                "old astronomical instruments",
            ], priority=1),
            BrollTemplate("Archives", [
                "old book library archives",
                "historical document close up",
                "vintage scientific illustration",
            ], priority=2),
        ])

        # ── General ────────────────────────────────────────────────────
        categories["General"] = BrollCategory("General", [
            BrollTemplate("Cinematic", [
                "cinematic establishing shot",
                "aerial drone landscape cinematic",
                "time lapse clouds moving",
            ], priority=10),
            BrollTemplate("Abstract", [
                "abstract particle animation",
                "glowing particles motion",
                "sci-fi holographic interface",
            ], priority=10),
        ])

        return categories
