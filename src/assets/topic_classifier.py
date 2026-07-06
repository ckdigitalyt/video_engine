"""
topic_classifier.py — Topic-Aware Asset Routing: Topic Classification.

Classifies a video topic string into a category (Space, History, Science,
etc.) using configurable keyword matching.  The categories and their
associated keywords are defined in ``configs/providers.yaml`` under the
``asset_routing.keywords`` key, with a built-in fallback.
"""

from src.utils.config import get_config


# ── Default category keywords (fallback when config YAML is absent) ────────

_DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Space": [
        "space", "astronomy", "astronaut", "nasa", "planet", "star",
        "galaxy", "universe", "cosmos", "telescope", "orbit", "satellite",
        "solar", "mars", "moon", "alien", "ufo", "extraterrestrial",
        "rocket", "launch", "nebula", "asteroid", "comet", "stellar",
        "fermi", "paradox", "cosmic", "interstellar", "celestial",
        "constellation", "lunar", "meteor", "observatory", "sputnik",
        "voyager", "hubble", "spacecraft", "spaceflight", "spacewalk",
        "black hole", "quasar",
    ],
    "History": [
        "history", "ancient", "empire", "war", "revolution", "medieval",
        "roman", "greek", "egyptian", "civilization", "king", "queen",
        "battle", "century", "historical", "archaeology", "ruins",
        "renaissance", "colony", "dynasty", "monarch", "conquest",
    ],
    "Science": [
        "science", "physics", "chemistry", "biology", "experiment",
        "laboratory", "research", "discovery", "dna", "genetics",
        "quantum", "particle", "energy", "element", "molecule",
        "scientist", "theory", "evolution", "microscope", "lab",
    ],
    "Technology": [
        "technology", "computer", "ai", "programming", "software",
        "internet", "robot", "digital", "startup", "innovation",
        "cyber", "blockchain", "code", "algorithm", "machine learning",
        "artificial intelligence", "data", "network", "processor",
    ],
    "Nature": [
        "nature", "animal", "wildlife", "ocean", "forest", "mountain",
        "river", "climate", "weather", "environment", "planet earth",
        "ecosystem", "bird", "fish", "plant", "garden", "landscape",
        "sea", "rainforest", "desert", "coral", "conservation",
    ],
    "Finance": [
        "finance", "money", "economy", "bank", "stock", "investment",
        "wealth", "crypto", "market", "trading", "budget", "fund",
        "financial", "business", "entrepreneur", "recession", "inflation",
    ],
    "General": [],
}


class TopicClassifier:
    """Classifies a video topic into a routing category.

    Uses keyword overlap scoring: each keyword token that appears in the
    (lowercased) topic string contributes one point.  The category with
    the highest score wins.  When no keyword matches, returns ``"General"``.
    Categories are loaded from YAML config (``asset_routing.keywords``)
    with a built-in fallback to ``_DEFAULT_CATEGORIES``.
    """

    def __init__(self, categories: dict[str, list[str]] | None = None) -> None:
        """Initialise with optional custom category definitions.

        If *categories* is *None*, the classifier reads from
        ``configs/providers.yaml`` (``asset_routing.keywords``),
        falling back to ``_DEFAULT_CATEGORIES``.
        """
        self._categories = categories if categories is not None else self._load_categories()
        # Ordered list of non-General categories for deterministic scoring
        self._category_names = [k for k in sorted(self._categories.keys()) if k != "General"]

    # ── Public API ─────────────────────────────────────────────────────

    def classify(self, topic: str) -> str:
        """Return the best-matching category for *topic*.

        Matching uses whole-word boundary checks: a single-word keyword
        must appear as a distinct word (not as a substring of another word).
        Multi-word keywords (e.g. ``"machine learning"``) are matched
        as substrings against the lowercased topic text.

        Returns ``"General"`` when no category has a positive score.
        """
        topic_lower = topic.lower()
        topic_words = set(topic_lower.split())
        scores: dict[str, int] = {}

        for name in self._category_names:
            keywords = self._categories.get(name, [])
            score = 0
            for kw in keywords:
                kw_lower = kw.lower()
                if " " in kw_lower:
                    # Multi-word keyword: substring match
                    if kw_lower in topic_lower:
                        score += 1
                else:
                    # Single-word keyword: whole-word match only
                    if kw_lower in topic_words:
                        score += 1
            if score > 0:
                scores[name] = score

        if not scores:
            return "General"

        # Tie-break: deterministic alphabetical order
        max_score = max(scores.values())
        tied = sorted(name for name, s in scores.items() if s == max_score)
        return tied[0]

    def list_categories(self) -> list[str]:
        """Return all configured category names (including ``General``)."""
        return list(self._categories.keys())

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _load_categories() -> dict[str, list[str]]:
        """Load keyword definitions from YAML config, falling back to defaults.

        Always ensures a ``"General"`` category exists (with an empty keyword
        list) so ``classify()`` always has a fallback.
        """
        cfg = get_config("asset_routing.keywords", None)
        if cfg and isinstance(cfg, dict):
            cats = {k: v if isinstance(v, list) else [] for k, v in cfg.items()}
        else:
            cats = dict(_DEFAULT_CATEGORIES)
        if "General" not in cats:
            cats["General"] = []
        return cats
