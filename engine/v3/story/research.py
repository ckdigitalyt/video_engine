"""research.py — Research intake (Wave 3, directive §3 stage 2).

Produces the canonical cached research document:

    {"topic": str, "claims": [{"text", "confidence", "source_ref"}...],
     "sources": [{"ref", "title", "url", "note"}...], "angles": [str...],
     "provenance": "llm_general_knowledge" | "pre_seeded" | "offline_template"}

Accepts a pre-seeded research.json (Wave 4 can drop one in, or reuse any
upstream research capability — thin adapter, src/ untouched). When absent:
one LLM call over the fallback chain (llm.py); when that fails: a
deterministic offline template document (§24 — the pipeline never collapses).
The output is cached at results/<id>/research.json; resumed runs skip.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from engine.v3.story.llm import LLMError, ask_json

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM = (
    "You are the research editor for a short documentary pipeline. You "
    "produce factual, precise, verifiable research. Hard rules: never invent "
    "specific numbers, dates, or citations you are not confident about; "
    "hedge uncertain claims; output ONLY valid JSON with no commentary."
)

MAX_CLAIMS = 12


def load_research(path: str | Path) -> dict:
    """Load an existing research document (cached or pre-seeded)."""
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not doc.get("topic") or not isinstance(doc.get("claims"), list):
        raise ValueError(f"research doc at {p} missing topic/claims")
    doc.setdefault("provenance", "pre_seeded")
    doc.setdefault("sources", [])
    doc.setdefault("angles", [])
    return doc


def build_research(topic: str, out_path: str | Path, *,
                   use_llm: bool = True) -> dict:
    """Build (or load cached) research for *topic*, written to *out_path*."""
    p = Path(out_path)
    if p.exists():
        return load_research(p)

    doc: dict[str, Any] | None = None
    errors: list[str] = []
    if use_llm:
        doc = _llm_research(topic, errors)
    if doc is None:
        doc = _offline_research(topic)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    if errors:
        doc["llm_errors"] = errors
    logger.info("research: %d claims, %d sources (%s)",
                len(doc["claims"]), len(doc["sources"]), doc["provenance"])
    return doc


def _llm_research(topic: str, errors: list[str]) -> dict | None:
    prompt = f"""Research the topic: "{topic}"

Produce a research document for a 45-120 second documentary video as STRICT JSON:
{{
  "topic": "{topic}",
  "claims": [
    {{"text": "<one factual claim, hedged if uncertain>", "confidence": "high|medium",
      "source_ref": "s1"}}
  ],
  "sources": [
    {{"ref": "s1", "title": "<source name or description>",
      "url": "<url or empty>", "note": "<what it supports>"}}
  ],
  "angles": ["<one-line narrative angle that could hook a viewer>"]
}}

Rules:
- 6-{MAX_CLAIMS} claims, ordered from most surprising to most explanatory.
- claims must be short declarative sentences usable in narration.
- include at least one angle built on genuine curiosity (no clickbait).
- only include sources you are confident exist; otherwise use source_ref ""
- confidence "medium" for anything contested or uncertain."""
    try:
        doc = ask_json(RESEARCH_SYSTEM, prompt, temperature=0.3,
                       max_tokens=2500, last_errors=errors)
    except LLMError as exc:
        logger.warning("research LLM failed: %s", exc)
        return None
    if not doc.get("topic") or not isinstance(doc.get("claims"), list) \
            or not doc["claims"]:
        errors.append("research: LLM doc missing topic/claims")
        return None
    claims = doc["claims"][:MAX_CLAIMS]
    cleaned = []
    for c in claims:
        if not isinstance(c, dict) or not str(c.get("text", "")).strip():
            continue
        cleaned.append({
            "text": str(c["text"]).strip(),
            "confidence": c.get("confidence", "medium") if c.get("confidence") in ("high", "medium") else "medium",
            "source_ref": str(c.get("source_ref", "") or ""),
        })
    if not cleaned:
        errors.append("research: no usable claims")
        return None
    sources = []
    for s in doc.get("sources", []) or []:
        if isinstance(s, dict) and str(s.get("ref", "")).strip():
            sources.append({
                "ref": str(s["ref"]), "title": str(s.get("title", "") or ""),
                "url": str(s.get("url", "") or ""),
                "note": str(s.get("note", "") or ""),
            })
    angles = [str(a).strip() for a in (doc.get("angles") or [])
              if str(a).strip()][:6]
    return {"topic": topic, "claims": cleaned, "sources": sources,
            "angles": angles, "provenance": "llm_general_knowledge"}


def _offline_research(topic: str) -> dict:
    """Deterministic research skeleton — no network, no LLM. Hedged and
    honest: marks itself a template so downstream QA treats it softly."""
    t = topic.strip().rstrip(".?")
    return {
        "topic": topic,
        "claims": [
            {"text": f"The central question of this story is {t}.",
             "confidence": "medium", "source_ref": ""},
            {"text": f"Experts study {t} because it connects to larger "
                     f"questions about how our world works.",
             "confidence": "medium", "source_ref": ""},
            {"text": f"The most surprising part of {t} is what it changed "
                     f"afterwards.",
             "confidence": "medium", "source_ref": ""},
            {"text": f"Evidence about {t} comes from multiple independent "
                     f"lines of research.",
             "confidence": "medium", "source_ref": ""},
            {"text": f"What happened after the key moment in {t} shaped "
                     f"what we see today.",
             "confidence": "medium", "source_ref": ""},
        ],
        "sources": [],
        "angles": [
            f"The part of {t} that almost everyone gets wrong",
            f"What really happened, step by step, in {t}",
        ],
        "provenance": "offline_template",
    }
