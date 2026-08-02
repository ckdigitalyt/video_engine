"""
spec_builder.py — Derive EntitySpecs from narration + facts (general).

Given a beat's narration and the verified research facts, produce an
EntitySpec: required / optional / prohibited entities, scene intent, and
confidence.  Uses one structured LLM call per beat with a deterministic
keyword fallback when the LLM is unavailable or malformed.

General framework: entity extraction is semantic (LLM), not topic rules.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

from .entity_spec import EntitySpec

# Deterministic fallback vocabulary (general-purpose, not topic-specific):
# these are common classes of "wrong subject" failures.
_FALLBACK_PROHIBITED_HINTS = {
    "spacecraft": ["rocket", "shuttle", "airplane", "jet", "fighter",
                   "falcon heavy", "spacex", "satellite dish on ground"],
    "planet": ["earth surface", "city", "ocean", "forest", "mountain"],
    "person": ["actor", "cartoon", "celebrity"],
    "era": ["modern city", "skyscraper", "smartphone"],
}

_ABSTRACT_TERMS = ("branding", "logo", "imagery", "era", "style", "aesthetic",
                    "vibe", "look", "feel", "atmosphere", "sense", "mood",
                    "decade", "period", "depiction", "rendering")

_SPEC_PROMPT = """You are a documentary visual planner. For the given narration and facts,
decide what MUST, MAY, and MUST NOT appear on screen.

RULES for required_entities:
- Only CONCRETE, VERIFIABLE subjects: named spacecraft/missions, planets,
  vehicles, people, landmarks, objects (e.g. "Voyager 1", "Jupiter", "rocket").
- NEVER include abstract descriptors like era, branding, logo, imagery,
  style, mood, or atmosphere — those cannot be verified from asset metadata.
- Keep 1-3 required entities max.

Also provide "match_terms": for EACH required entity, the concrete strings
that would appear in a real asset's title/filename/description (aliases).
Example: entity "Earth" -> match_terms ["earth", "pale blue dot"] because
NASA titles the photo "Pale Blue Dot". Entity "Voyager 1" -> ["voyager 1",
"voyager"]. These make metadata matching tolerant of terse official titles.

NARRATION: {narration}
FACTS: {facts}

Return STRICT JSON:
{{
  "required_entities": ["concrete subjects that must be shown or strongly implied"],
  "match_terms": {{"<entity>": ["term1", "term2"]}},
  "optional_entities": ["acceptable alternatives"],
  "prohibited_entities": ["things that would be factually WRONG to show (wrong spacecraft, wrong planet, wrong era, wrong event, anachronisms)"],
  "scene_intent": "hook|reveal|scale|journey|exploration|emotion|conclusion|explanation",
  "visual_objective": "one sentence: what the viewer should SEE and FEEL"
}}"""


def build_spec(
    beat_id: str,
    scene_id: int,
    narration: str,
    facts: Optional[list] = None,
    provider=None,
    confidence: float = 1.0,
) -> EntitySpec:
    """Build an EntitySpec from narration (+facts). LLM-first, fallback-safe."""
    spec = _from_llm(beat_id, scene_id, narration, facts, provider, confidence)
    if spec is None:
        spec = _from_keywords(beat_id, scene_id, narration, confidence)
    return spec


def _from_llm(beat_id, scene_id, narration, facts, provider, confidence) -> Optional[EntitySpec]:
    if provider is None:
        return None
    facts_text = json.dumps(facts or [], indent=1)[:2500]
    try:
        raw = provider.generate_json(_SPEC_PROMPT.format(
            narration=narration[:800], facts=facts_text))
        data = json.loads(raw)
        required = [str(e) for e in data.get("required_entities", [])]
        # Strip abstract, unverifiable descriptors (root-cause fix from
        # validation: "NASA branding/logo", "1970s era imagery" can never
        # match asset metadata and caused false rejections).
        required = [e for e in required if not any(a in e.lower() for a in _ABSTRACT_TERMS)]
        prohibited = [str(e) for e in data.get("prohibited_entities", [])]
        prohibited = [e for e in prohibited if not any(a in e.lower() for a in _ABSTRACT_TERMS)]
        # Alias layer: entity -> concrete metadata strings (general, not
        # topic-specific — the LLM provides them per beat).
        match_terms_raw = data.get("match_terms", {}) or {}
        match_terms = {}
        for ent in required:
            terms = [str(t) for t in match_terms_raw.get(ent, []) if str(t).strip()]
            # always include the entity itself as a term
            terms = [ent] + [t for t in terms if t.lower() != ent.lower()]
            match_terms[ent] = terms[:6]
        return EntitySpec(
            beat_id=beat_id,
            scene_id=scene_id,
            required_entities=required[:4],
            match_terms=match_terms,
            optional_entities=[str(e) for e in data.get("optional_entities", [])][:6],
            prohibited_entities=prohibited[:6],
            scene_intent=str(data.get("scene_intent", "default")),
            visual_objective=str(data.get("visual_objective", "")),
            confidence=confidence,
        )
    except Exception:
        return None


def _from_keywords(beat_id, scene_id, narration, confidence) -> EntitySpec:
    """Deterministic fallback: extract proper nouns + apply general hints."""
    text = narration.lower()
    # Proper-noun-ish candidates (capitalized words) from the narration
    required = list(dict.fromkeys(
        w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", narration)
        if w.lower() not in ("the", "and", "its", "that", "this", "was", "were", "one", "two")
    ))[:6]
    prohibited = []
    for category, hints in _FALLBACK_PROHIBITED_HINTS.items():
        # if the beat names a specific instance (e.g. "voyager"), prohibit
        # the generic wrong-class items only when they conflict semantically
        if any(h in text for h in hints):
            prohibited.extend(hints)
    return EntitySpec(
        beat_id=beat_id, scene_id=scene_id,
        required_entities=required,
        prohibited_entities=prohibited[:6],
        scene_intent="default",
        visual_objective=f"Show: {', '.join(required) or 'subject of narration'}",
        confidence=confidence,
    )
