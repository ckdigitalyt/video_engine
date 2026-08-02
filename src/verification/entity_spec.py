"""
entity_spec.py — Entity–Asset verification data model.

Every narrative beat declares what it REQUIRES, what is OPTIONAL, and what
is PROHIBITED on screen, plus scene intent and confidence.  This is the
contract the asset verifier evaluates candidates against.

General framework: no topic-specific rules live here.  A beat's EntitySpec
is derived from its narration + verified facts by the planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EntitySpec:
    """What a beat expects to see on screen."""

    beat_id: str = ""
    scene_id: int = 0
    # Entities that MUST be present or strongly implied by the asset.
    required_entities: list[str] = field(default_factory=list)
    # Concrete strings that would appear in asset metadata for each
    # required entity (aliases, filenames, titles).  e.g. "Earth" may have
    # match_terms ["pale blue dot", "earth"] because NASA titles the photo
    # "Pale Blue Dot".  General alias layer — not topic-specific rules.
    match_terms: dict = field(default_factory=dict)  # entity -> [terms]
    # Entities that may appear but are not required.
    optional_entities: list[str] = field(default_factory=list)
    # Entities that must NEVER appear (wrong spacecraft, wrong planet, ...).
    prohibited_entities: list[str] = field(default_factory=list)
    # What the scene is trying to achieve visually (reveal, scale, emotion...).
    scene_intent: str = ""
    # 0-1 confidence in the spec itself (from fact verification).
    confidence: float = 1.0
    # Short human-readable summary of what the viewer should see.
    visual_objective: str = ""

    def to_dict(self) -> dict:
        return {
            "beat_id": self.beat_id,
            "scene_id": self.scene_id,
            "required_entities": self.required_entities,
            "match_terms": self.match_terms,
            "optional_entities": self.optional_entities,
            "prohibited_entities": self.prohibited_entities,
            "scene_intent": self.scene_intent,
            "confidence": self.confidence,
            "visual_objective": self.visual_objective,
        }


@dataclass
class VerificationResult:
    """Outcome of verifying one candidate asset against an EntitySpec."""

    asset_path: str = ""
    beat_id: str = ""
    passed: bool = False
    score: float = 0.0            # 0-1 combined signal score
    signal_scores: dict = field(default_factory=dict)  # signal -> {score, evidence}
    matched_required: list[str] = field(default_factory=list)
    violated_prohibited: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    vision_check: Optional[dict] = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "asset_path": self.asset_path,
            "beat_id": self.beat_id,
            "passed": self.passed,
            "score": round(self.score, 3),
            "signal_scores": {
                k: {"score": round(v.get("score", 0), 3), "evidence": v.get("evidence", "")}
                for k, v in self.signal_scores.items()
            },
            "matched_required": self.matched_required,
            "violated_prohibited": self.violated_prohibited,
            "missing_required": self.missing_required,
            "vision_check": self.vision_check,
            "reasons": self.reasons,
        }
