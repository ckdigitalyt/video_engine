"""Decision #13 item 3 — subject consistency: a video's recurring main
character/animal/object (story["concepts"], the same per-beat recurrence
tracker v7's contradiction engine already builds) gets ONE reusable
appearance+clothing description, generated once via the text judge and
cached by story content (same convention as engine.v16_metadata), then
spliced into every image-generation prompt whose shot subject names that
concept — so the same figure doesn't get redesigned beat to beat.

Decision #18 item 2: stories from engine.v16_autostory carry NO
`concepts`, so the bible above never ran on any auto-generated video
(dry run 5: `subject_bible: {}` -> the image model drew its "tiny icy
world" as Earth, continents and oceans, on 8/21 plates). For those
stories one cached text call now derives the recurring subject's IDENTITY
from title + narration: {name, aliases, description, not_like}.
  - name/description feed the visual planner (engine.v15_plan) so every
    shot is written about the specific thing, and are spliced into each
    image prompt whose subject mentions any alias (whole-word match);
  - not_like (the generic stand-in an illustrator would default to) is
    used ONLY by plate QA (engine.v15_plates) — never in an image prompt:
    FLUX has no negative prompt, naming the wrong thing summons it.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "build" / "cache" / "subject_bible"
PROMPT_VERSION = "subject_bible/1.0"
IDENTITY_VERSION = "subject_identity/1.1"  # 2026-10-15: one object, look only


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


def identity_prompt(story: dict) -> str:
    lines = "\n".join(f"- {b['narration']}" for b in story["beats"])
    return f"""You are the art director of an illustrated vertical explainer
video. Every shot is drawn by a separate AI image call, so the video's ONE
recurring main visual subject must be described once, concretely, or each
call will invent a generic stand-in (e.g. a "tiny icy world" drawn as Earth).

Video title: {story.get('title', story['story_id'])}
Narration:
{lines}

Identify the recurring main visual subject: ONE physical object or creature
you could photograph (e.g. "the asteroid") -- never an event or a compound
like "the asteroid impact and megatsunami". Return ONLY JSON:
{{"name": "<short concrete noun phrase, e.g. 'the icy dwarf planet'>",
 "aliases": ["<every lowercase 1-4 word phrase the narration or a shot
   description may use for it, e.g. 'tiny world', 'small world', 'dwarf
   planet' — 3 to 8 entries>"],
 "description": "<= 30 words, the object's own fixed LOOK only: shape,
   surface, colours, texture, scale cues -- no action, no surroundings,
   no event (it is pasted verbatim into every shot, so it must hold in all
   of them). Positive phrasing only (say what it IS, never 'not X').
   Scientifically plausible for this exact subject.",
 "not_like": "<= 12 words: the most likely WRONG generic depiction an
   illustrator would default to, e.g. 'Earth with blue oceans and green
   continents'"}}
If the video truly has no single recurring visual subject, return
{{"name": null}}."""


def _identity_bible(story: dict, *, use_llm: bool, ask) -> dict:
    """No-concepts path (auto-generated stories). -> {} when there is no
    LLM, no answer, or no single recurring subject."""
    blob = json.dumps({"v": IDENTITY_VERSION, "title": story.get("title"),
                       "narration": [b.get("narration") for b in story["beats"]]},
                      sort_keys=True)
    key = hashlib.sha256(blob.encode()).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = CACHE_DIR / f"id_{key}.json"
    if cp.exists():
        data = json.loads(cp.read_text())
        if data.get("description"):
            return dict(data, source="cache", llm_calls=0)
    if not use_llm:
        return {}
    if ask is None:
        from engine.director import text_ask

        def ask(p):
            return text_ask(p, 0.2, 500, stage="text_misc")
    raw = ask(identity_prompt(story))
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        ans = json.loads(m.group()) if m else {}
    except Exception:
        ans = {}
    name, desc = ans.get("name"), ans.get("description")
    if not (isinstance(name, str) and name.strip() and isinstance(desc, str)
            and desc.strip()):
        return {"llm_calls": 1}
    aliases = [a.strip().lower() for a in (ans.get("aliases") or [])
               if isinstance(a, str) and a.strip()]
    core = re.sub(r"^(the|a|an)\s+", "", name.strip().lower())
    if core not in aliases:
        aliases.insert(0, core)
    data = {"concept_id": core.replace(" ", "_"), "name": name.strip(),
            "aliases": aliases[:10], "description": desc.strip(),
            "not_like": str(ans.get("not_like") or "").strip()}
    cp.write_text(json.dumps(data, indent=1))
    return dict(data, source="llm", llm_calls=1)


def build_subject_bible(story: dict, *, use_llm: bool = True, ask=None) -> dict:
    """-> {} when the story has no recurring subject, else {"concept_id",
    "description", "source": llm|cache|fallback, "llm_calls"} (+ "name",
    "aliases", "not_like" on the identity path). Cached by story content
    (same convention as engine.v16_metadata.build_metadata)."""
    concept = main_concept(story)
    if not concept:
        # decision #18 item 2: auto-generated stories have no concepts
        return _identity_bible(story, use_llm=use_llm, ask=ask)
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
    names the recurring subject — its id (underscores as spaces) or any of
    its `aliases`, matched as whole words (engine.species.alias_in)."""
    from engine.species import alias_in
    bible = bible or {}
    cid = str(bible.get("concept_id") or "").replace("_", " ").strip()
    desc = bible.get("description")
    aliases = [a for a in (bible.get("aliases") or []) if a] + ([cid] if cid else [])
    if not desc or desc.rstrip(". ") in subject_text:
        return subject_text
    # 2026-10-15 review (subject lock): also match each alias without its
    # leading article ("the asteroid" -> "asteroid" in "A dark asteroid
    # fragment"), and splice the locked look in RIGHT AFTER the first
    # mention -- image models weight early tokens, so a description appended
    # at the end lost to the shot's own adjectives and the subject was
    # redesigned shot to shot.
    import re as _re
    cands = set()
    for a in aliases:
        a = str(a).strip().lower()
        cands.add(a)
        core = _re.sub(r"^(the|a|an)\s+", "", a)
        if core:
            cands.add(core)
    hits = []
    low = subject_text.lower()
    for a in sorted(cands, key=len, reverse=True):
        if not alias_in(a, subject_text):
            continue
        m = _re.search(r"(?<!\w)" + _re.escape(a) + r"(?:e?s)?(?!\w)", low)
        if m:
            hits.append((m.start(), m.end()))
    if not hits:
        return subject_text
    start, end = min(hits)
    return (subject_text[:end] + f" ({desc.rstrip('. ')})"
            + subject_text[end:])
