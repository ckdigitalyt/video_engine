"""Daily topic engine (JADE v0.3 §24–25).

TopicScout scores candidate topics on the §24 rubric:

    curiosity, novelty, visual_potential, educational_value,
    story_potential, search_interest, shareability, comment_potential,
    production_feasibility, source_availability

Each factor 0–1 (deterministic by default; `llm_override` lets a
reasoning model adjust scores later — never required).  Total = weighted
mean.  Topics that cannot be meaningfully visualized are rejected.

§25 diversity: the scheduler tracks recent topics by category and avoids
repeating the same visual grammar too frequently (category rotation),
while still allowing the same category after enough separation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# §24 scoring factors (each 0–1).
SCORE_FACTORS: tuple[str, ...] = (
    "curiosity", "novelty", "visual_potential", "educational_value",
    "story_potential", "search_interest", "shareability",
    "comment_potential", "production_feasibility", "source_availability",
)

# Factor weights: visual/story/education dominate production value.
FACTOR_WEIGHTS: dict[str, float] = {
    "curiosity": 1.0, "novelty": 0.8, "visual_potential": 1.4,
    "educational_value": 1.2, "story_potential": 1.2,
    "search_interest": 0.6, "shareability": 0.8,
    "comment_potential": 0.5, "production_feasibility": 1.3,
    "source_availability": 1.0,
}

# §25 category rotation order (the example daily rotation).
CATEGORY_ROTATION: tuple[str, ...] = (
    "science", "psychology", "technology", "mathematics", "space",
    "history", "human_body", "everyday_phenomenon", "engineering",
)


@dataclass
class TopicCandidate:
    topic: str
    category: str = "science"
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def total(self) -> float:
        if not self.scores:
            return 0.0
        w = sum(FACTOR_WEIGHTS.get(k, 1.0) for k in self.scores)
        return sum(self.scores.get(k, 0.0) * FACTOR_WEIGHTS.get(k, 1.0)
                   for k in self.scores) / max(1.0, w)

    def to_dict(self) -> dict:
        return {"topic": self.topic, "category": self.category,
                "scores": dict(self.scores),
                "total": round(self.total, 3)}


# ── deterministic keyword scoring (LLM-free baseline) ──────────────────
_VISUAL_KEYWORDS = frozenset({
    "wave", "light", "orbit", "fall", "collide", "explosion", "burst",
    "simulation", "diagram", "mechanism", "inside", "structure", "growth",
    "signal", "network", "trajectory", "motion", "color", "sound",
})
_STORY_KEYWORDS = frozenset({
    "why", "how", "mystery", "secret", "surprising", "counterintuitive",
    "paradox", "impossible", "strange", "hidden", "against",
})
_HARD_TO_VISUALIZE = frozenset({
    "abstract", "philosophy", "metaphysics", "tax law", "grammar",
})


def _keywords(topic: str) -> set[str]:
    return {w for w in (topic or "").lower().replace("?", "").split()
            if w}


def default_scores(topic: str) -> dict[str, float]:
    """Deterministic §24 baseline: keyword-driven 0–1 factor scores."""
    kw = _keywords(topic)
    has_visual = bool(kw & _VISUAL_KEYWORDS)
    has_story = bool(kw & _STORY_KEYWORDS)
    hard = bool(kw & _HARD_TO_VISUALIZE)
    n = max(1, len(kw))
    return {
        "curiosity": 0.8 if ("why" in kw or "how" in kw) else 0.5,
        "novelty": 0.7 if has_story else 0.5,
        "visual_potential": (0.25 if hard else
                              0.85 if has_visual else 0.45),
        "educational_value": 0.75 if n >= 3 else 0.6,
        "story_potential": 0.8 if has_story else 0.5,
        "search_interest": 0.5,
        "shareability": 0.6 if has_story else 0.45,
        "comment_potential": 0.55 if has_story else 0.4,
        "production_feasibility": 0.35 if hard else 0.8,
        "source_availability": 0.7,
    }


def score_topic(topic: str, category: str = "science",
                scores: Optional[dict[str, float]] = None) -> TopicCandidate:
    """Score one candidate topic (§24).  `scores` overrides the baseline."""
    base = default_scores(topic)
    if scores:
        base.update({k: float(v) for k, v in scores.items()
                     if k in SCORE_FACTORS})
    return TopicCandidate(topic=topic, category=category, scores=base)


def is_visualizable(topic: str, min_visual: float = 0.4) -> bool:
    """§24: reject topics that cannot be meaningfully visualized."""
    return default_scores(topic)["visual_potential"] >= min_visual


# ── history tracking (§25) ─────────────────────────────────────────────
HISTORY_FILENAME = "topic_history.json"


def load_history(base: Optional[Path] = None) -> dict:
    p = Path(base) if base else Path.cwd()
    f = p / HISTORY_FILENAME
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"recent": [], "category_counts": {}}


def record_topic(topic: str, category: str, base: Optional[Path] = None,
                 max_recent: int = 10) -> dict:
    """Record a produced topic (§25): recent list + category counts."""
    hist = load_history(base)
    hist["recent"] = [t for t in hist["recent"] if t != topic]
    hist["recent"].append(topic)
    hist["recent"] = hist["recent"][-max_recent:]
    counts = hist.setdefault("category_counts", {})
    counts[category] = counts.get(category, 0) + 1
    f = Path(base) if base else Path.cwd()
    (f / HISTORY_FILENAME).write_text(json.dumps(hist, indent=2))
    return hist


def _category_penalty(category: str, hist: dict,
                      recency_penalty: float = 0.25) -> float:
    """§25: penalty for repeating a category recently."""
    recent = hist.get("recent", [])
    if not recent:
        return 0.0
    last_idx = None
    for i, t in enumerate(reversed(recent)):
        pass  # topics carry no category; use category_counts proximity
    counts = hist.get("category_counts", {})
    recent_cats = _recent_categories(recent)
    if category in recent_cats:
        return recency_penalty
    return min(recency_penalty,
               0.12 * counts.get(category, 0))


def _recent_categories(recent_topics: list[str]) -> set[str]:
    """Best-effort category of recent topics (by keyword match)."""
    out: set[str] = set()
    for t in recent_topics:
        tl = t.lower()
        if any(k in tl for k in ("math", "number", "digit", "collatz",
                                 "kaprekar")):
            out.add("mathematics")
        elif any(k in tl for k in ("space", "orbit", "star", "planet",
                                   "galaxy", "satellite")):
            out.add("space")
        elif any(k in tl for k in ("brain", "psych", "illusion", "mind")):
            out.add("psychology")
        elif any(k in tl for k in ("headphone", "engineer", "circuit",
                                   "machine", "computer")):
            out.add("technology")
        elif any(k in tl for k in ("sky", "popcorn", "microwave", "ice",
                                   "slippery", "lift")):
            out.add("everyday_phenomenon")
        elif any(k in tl for k in ("body", "cell", "dna", "heart")):
            out.add("human_body")
        else:
            out.add("science")
    return out


def select_daily_topic(candidates: list[TopicCandidate],
                       base: Optional[Path] = None,
                       prefer_rotation: bool = True) -> TopicCandidate:
    """§25: pick the best topic while avoiding grammar repetition.

    Applies the category recency penalty, then returns the highest
    adjusted total.  With `prefer_rotation`, the next category in the
    §25 rotation order gets a small boost.
    """
    hist = load_history(base)
    recent = hist.get("recent", [])
    recent_cats = _recent_categories(recent)
    best = None
    best_score = -1.0
    for cand in candidates:
        adj = cand.total - _category_penalty(cand.category, hist)
        if prefer_rotation and recent_cats:
            # boost the next category in the rotation that was not recent
            for cat in CATEGORY_ROTATION:
                if cat not in recent_cats:
                    if cand.category == cat:
                        adj += 0.05
                    break
        if adj > best_score:
            best_score = adj
            best = cand
    return best or (candidates[0] if candidates else TopicCandidate(""))
