"""
improvement_pass.py — Automated video improvement passes.

Consumes a Gemini Flash end-to-end video review (structured JSON), selects
high-value recommendations that are *automatically applicable*, applies
them to the render inputs (timeline / audio mix / config), and re-renders.

Rules:
  - Max total iterations: initial render + up to 2 improvement passes = 3.
  - Recommendations that would materially change the story, dispute facts,
    or conflict with each other are FLAGGED for human approval, never auto-applied.
  - Every pass records: what changed, why, and the score delta.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════════ #
# Data
# ═══════════════════════════════════════════════════════════════════════ #

@dataclass
class AppliedChange:
    category: str
    detail: str
    source_rec: str


@dataclass
class ImprovementResult:
    iteration: int
    applied: list[AppliedChange] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    stopped_early: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "applied": [c.__dict__ for c in self.applied],
            "flagged": self.flagged,
            "stopped_early": self.stopped_early,
            "notes": self.notes,
        }


# ═══════════════════════════════════════════════════════════════════════ #
# Applicability classifier
# ═══════════════════════════════════════════════════════════════════════ #

# Recommendation categories that are safe to auto-apply (parameter-level).
AUTO_APPLY_CATEGORIES = {
    "pacing": "timeline shot durations",
    "transitions": "timeline transition types",
    "music": "audio mix levels / ducking",
    "audio_balance": "audio mix levels",
    "color": "render color grade",
    "subtitles": "subtitle styling/timing",
    "shot_order": "timeline shot order",
    "zoom": "motion/zoom parameters",
    "thumbnail": "thumbnail recommendation (recorded, not auto-applied to video)",
}

# Categories that MUST be flagged for human approval.
FLAG_CATEGORIES = {
    "story_change": "would change the story",
    "fact_change": "would change factual claims",
    "script_change": "would rewrite narration",
    "new_scene": "would add/remove scenes",
    "new_asset": "requires new asset search/generation",
}

QUALITY_TARGET_SCORE = 85  # stop improving once review score >= this


# ═══════════════════════════════════════════════════════════════════════ #
# Improvement engine
# ═══════════════════════════════════════════════════════════════════════ #

class ImprovementPass:
    """Applies feasible review recommendations to render inputs."""

    def __init__(
        self,
        work_dir: str = "results/improve",
        max_total_iterations: int = 3,
        quality_target: int = QUALITY_TARGET_SCORE,
        verbose: bool = True,
    ):
        self._work_dir = work_dir
        self._max_iter = max(1, min(max_total_iterations, 3))
        self._quality_target = quality_target
        self._verbose = verbose
        os.makedirs(work_dir, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────

    def plan(self, review: dict, iteration: int) -> ImprovementResult:
        """Classify a review's recommendations into applied vs flagged.

        *review* is the structured Gemini review (see review_video.py).
        Returns the plan; the caller applies ``applied`` changes to the
        render inputs and re-renders.
        """
        result = ImprovementResult(iteration=iteration)
        recs = review.get("recommendations") or review.get("prioritized_recommendations") or []
        if isinstance(recs, dict):  # tolerate {priority: [...]} shapes
            recs = [r for group in recs.values() for r in group]

        score = float(review.get("quality_score", review.get("score", 0)) or 0)
        if score >= self._quality_target:
            result.stopped_early = True
            result.notes = f"Quality target met ({score:.0f} >= {self._quality_target}); no changes applied."
            return result

        for rec in recs:
            text = rec if isinstance(rec, str) else rec.get("recommendation") or rec.get("action") or rec.get("text") or json.dumps(rec)
            category = (rec.get("category") if isinstance(rec, dict) else "") or self._classify(text)
            priority = (rec.get("priority") if isinstance(rec, dict) else "") or "medium"

            if category in FLAG_CATEGORIES:
                result.flagged.append(f"[{category}] {text}")
            elif category in AUTO_APPLY_CATEGORIES:
                result.applied.append(AppliedChange(
                    category=category,
                    detail=self._detail_for(category, text, priority),
                    source_rec=text[:200],
                ))
            else:
                # Unknown category: auto-apply only if high value & parameter-level
                if priority in ("high", "critical") and self._looks_parametric(text):
                    result.applied.append(AppliedChange(
                        category="pacing" if "pacing" in text.lower() or "duration" in text.lower() else "other",
                        detail=text[:200],
                        source_rec=text[:200],
                    ))
                else:
                    result.flagged.append(f"[unclassified] {text}")

        # Cap applied changes at 5 per pass to avoid over-engineering a render.
        result.applied = result.applied[:5]
        if not result.applied and not result.flagged:
            result.notes = "No actionable recommendations."
        return result

    # ── Internals ──────────────────────────────────────────────────────

    @staticmethod
    def _classify(text: str) -> str:
        t = text.lower()
        for cat, keywords in {
            "pacing": ("pacing", "duration", "slow", "too fast", "drag", "speed"),
            "transitions": ("transition", "cut", "fade", "crossfade"),
            "music": ("music", "score", "duck", "audio level", "mix"),
            "audio_balance": ("volume", "loud", "quiet", "narration level"),
            "color": ("color", "grade", "brightness", "contrast", "warm", "tint"),
            "subtitles": ("subtitle", "caption", "text on screen"),
            "story_change": ("story", "narrative", "plot", "scene", "ending"),
            "fact_change": ("fact", "claim", "inaccurate", "wrong"),
            "script_change": ("script", "narration wording", "voiceover text"),
        }.items():
            if any(k in t for k in keywords):
                return cat
        return "unclassified"

    @staticmethod
    def _looks_parametric(text: str) -> bool:
        """Heuristic: recommendation mentions a tunable parameter."""
        return any(k in text.lower() for k in (
            "second", "percent", "db", "level", "duration", "speed",
            "volume", "fade", "crop", "zoom", "brightness", "contrast",
        ))

    @staticmethod
    def _detail_for(category: str, text: str, priority: str) -> str:
        return f"[{category}][{priority}] {text[:200]}"

    def _log(self, msg: str):
        if self._verbose:
            print(msg, flush=True)
