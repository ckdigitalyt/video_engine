"""Decision #13 item 3 — subject consistency: a video's recurring main
character/animal/object (story["concepts"], the same per-beat recurrence
tracker v7's contradiction engine already builds) gets ONE reusable
appearance+clothing description, generated once via the text judge and
cached by story content (same convention as engine.v16_metadata), then
spliced into every image-generation prompt whose shot subject names that
concept — so the same figure doesn't get redesigned beat to beat.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "build" / "cache" / "subject_bible"
PROMPT_VERSION = "subject_bible/1.0"


def main_concept(story: dict) -> dict | None:
    """The concept spanning the most beats (ties: declaration order) — the
    video's one recurring visual subject, if it has one at all."""
    concepts = story.get("concepts") or []
    if not concepts:
        return None
    return max(concepts, key=lambda c: len(c.get("beats") or []))


def build_prompt(story: dict, concept: dict) -> str:
    beats_by_id = {b["beat_id"]: b for b in story["beats"]}
    mentions = "\n".join(
        f"- {beats_by_id[bid]['narration']}"
        for bid in concept.get("beats") or [] if bid in beats_by_id)
    return f"""You are a character designer for an illustrated explainer
video. One recurring subject ("{concept.get('id')}") appears across several
shots and MUST look the same figure every time — same build, same clothing,
same colors — even though a different AI image call draws each shot.

Video title: {story.get('title', story['story_id'])}
Subject: {story.get('subject', '')}
Lines of narration this subject appears in:
{mentions}

Write ONE short, concrete visual description (appearance + clothing/
markings only — no pose, no action, no background) that can be pasted
verbatim into every image prompt depicting this subject, so every drawing
matches. Keep it under 30 words.

Return ONLY JSON: {{"description": "..."}}"""


def _fallback_description(concept: dict) -> str:
    """No-LLM floor: the concept's own id, better than nothing but not a
    real consistency guarantee (flagged via source=fallback)."""
    return str(concept.get("id") or "").replace("_", " ")


def build_subject_bible(story: dict, *, use_llm: bool = True, ask=None) -> dict:
    """-> {} when the story has no recurring concept, else {"concept_id",
    "description", "source": llm|cache|fallback, "llm_calls"}. Cached by
    story content (same convention as engine.v16_metadata.build_metadata)."""
    concept = main_concept(story)
    if not concept:
        return {}
    blob = json.dumps({"v": PROMPT_VERSION, "concept": concept,
                       "title": story.get("title"),
                       "narration": [b.get("narration") for b in story["beats"]
                                    if b["beat_id"] in (concept.get("beats") or [])]},
                      sort_keys=True)
    key = hashlib.sha256(blob.encode()).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = CACHE_DIR / f"{key}.json"
    if cp.exists():
        data = json.loads(cp.read_text())
        if data.get("description"):
            return dict(data, source="cache", llm_calls=0)
    if use_llm:
        if ask is None:
            from engine.director import text_ask

            def ask(p):
                return text_ask(p, 0.3, 400, stage="text_misc")
        raw = ask(build_prompt(story, concept))
        m = re.search(r"\{.*\}", raw or "", re.S)
        desc = None
        if m:
            try:
                desc = json.loads(m.group()).get("description")
            except Exception:
                desc = None
        if isinstance(desc, str) and desc.strip():
            data = {"concept_id": concept.get("id"), "description": desc.strip()}
            cp.write_text(json.dumps(data, indent=1))
            return dict(data, source="llm", llm_calls=1)
    return {"concept_id": concept.get("id"),
           "description": _fallback_description(concept),
           "source": "fallback", "llm_calls": 1 if use_llm else 0}


def inject_subject(subject_text: str, bible: dict) -> str:
    """Append the subject bible's description when `subject_text` plausibly
    names the recurring concept (its id, underscores as spaces, appears in
    the shot's subject text — same alias-matching idea as
    engine.species.augment_subject)."""
    cid = str((bible or {}).get("concept_id") or "").replace("_", " ").strip()
    desc = (bible or {}).get("description")
    if not cid or not desc or cid.lower() not in subject_text.lower():
        return subject_text
    return subject_text.rstrip(". ") + ". " + desc
