"""Factual integrity (V4 §1, P0).

No superlative/record claim enters a script without explicit verification.
The story generator must distinguish e.g. "highest above sea level" from
"tallest from base to summit" — every claim carries a definition.

A story carries `facts.json`:
    {"claims": [{
        "id": "...", "beats": ["B2"],          # which beats assert it
        "claim": "...",                        # the exact assertion
        "definition": "...",                   # precise meaning (sea level vs base)
        "current_record_holder": "...|n/a",    # for records
        "measured_value": "...",
        "date_verified": "YYYY-MM",
        "authoritative_source": "...",
        "source_url": "...",
        "historically_changed": true|false,    # has the record/premise changed?
        "notes": "..."
    }]}

`verify_story` fails a story when narration contains a superlative/record
word whose beat is not covered by a verified claim entry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SUPERLATIVE_RE = re.compile(
    r"\b(oldest|youngest|largest|smallest|highest|deepest|fastest|first|"
    r"only|record|most|longest|shortest|densest|heaviest|biggest|"
    r"nearest|farthest)\b", re.I)

FACTS_REQUIRED = ("id", "beats", "claim", "definition", "measured_value",
                  "date_verified", "authoritative_source", "source_url",
                  "historically_changed")


def load_facts(story_dir: Path) -> dict:
    p = Path(story_dir) / "facts.json"
    return json.loads(p.read_text()) if p.exists() else {"claims": []}


def scan_claims(story: dict) -> list:
    """Find superlative/record usages in narration with beat + context."""
    hits = []
    for b in story.get("beats", []):
        text = b.get("narration", "") or ""
        for m in SUPERLATIVE_RE.finditer(text):
            s, e = max(0, m.start() - 60), min(len(text), m.end() + 60)
            hits.append({"beat_id": b.get("beat_id"), "word": m.group(0).lower(),
                         "context": text[s:e].strip()})
    return hits


def verify_story(story_dir: Path) -> dict:
    """Every beat containing a superlative/record word must be covered by a
    claim entry whose `beats` include that beat_id. Fact entries must carry
    all required fields. Returns {ok, uncovered, bad_entries, facts_count}.
    """
    story_dir = Path(story_dir)
    story = json.loads((story_dir / "story.json").read_text())
    facts = load_facts(story_dir)
    covered_beats = set()
    bad_entries = []
    for c in facts.get("claims", []):
        missing = [k for k in FACTS_REQUIRED if k not in c]
        if missing:
            bad_entries.append({"id": c.get("id", "?"), "missing": missing})
        covered_beats.update(b for b in c.get("beats", []))

    uncovered = []
    for h in scan_claims(story):
        if h["beat_id"] not in covered_beats:
            uncovered.append(h)

    # V5 §18: unstable-record claims flagged for re-verification before reuse
    recheck = [{"id": c.get("id", "?"), "note": c.get("recheck_note", "")}
               for c in facts.get("claims", []) if c.get("recheck_required")]
    return {
        "ok": not uncovered and not bad_entries,
        "uncovered": uncovered,
        "bad_entries": bad_entries,
        "facts_count": len(facts.get("claims", [])),
        "recheck_required": recheck,
    }
