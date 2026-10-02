"""V16 — video metadata (B5, VIS package): title/description/tags from a
real LLM call (engine.director.text_ask — the same one-adapter convention
v15_plan/v15_plates already use), cached by story content, with a
deterministic story-fields fallback so an adapter outage never blocks the
manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "build" / "cache" / "v16_metadata"
PROMPT_VERSION = "meta/1.0"
MIN_TAGS, MAX_TAGS = 5, 8


def _parse_json(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    for cand in (m.group(), re.sub(r",\s*([}\]])", r"\1", m.group())):
        try:
            return json.loads(cand)
        except Exception:
            pass
    return None


def build_prompt(story: dict) -> str:
    beats = "\n".join(f"- {b['beat_id']} [{b.get('function', '')}]: "
                      f"{b['narration']}" for b in story["beats"])
    facts = sorted({fid for b in story["beats"] for fid in b.get("fact_ids") or []})
    return f"""You are writing YouTube Shorts metadata for a fact-checked
deep-time/science explainer. Title: {story.get('title', story['story_id'])}
Subject: {story.get('subject', '')}

Beats (the whole narration, in order):
{beats}

Fact IDs already verified upstream by the research stage: {', '.join(facts) or 'none recorded'}

Write:
 title: <= 70 characters, punchy, matches the hook, no clickbait fabrication
 description: 2-3 short lines summarising the video for a viewer scrolling
   past, then ONE final line starting "Source/fact-check:" naming what kind
   of sources back it (do not invent a specific citation not in the beats)
 tags: 5-8 short lowercase search tags (no '#'), specific to this video's
   actual subject, not generic channel-wide tags

Return ONLY JSON:
{{"title": "...", "description": "...", "tags": ["...", "..."]}}"""


def _validate(meta) -> list:
    errs = []
    if not isinstance(meta, dict):
        return ["not a JSON object"]
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        errs.append("title: missing")
    elif len(title) > 100:
        errs.append("title: too long")
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errs.append("description: missing")
    tags = meta.get("tags")
    if not isinstance(tags, list) or not (MIN_TAGS <= len(tags) <= MAX_TAGS) \
            or not all(isinstance(t, str) and t.strip() for t in tags):
        errs.append(f"tags: need {MIN_TAGS}-{MAX_TAGS} non-empty strings")
    return errs


def _fallback_metadata(story: dict) -> dict:
    """Deterministic, story-fields-only floor (no LLM): never blocks the
    manifest on an adapter outage."""
    title = str(story.get("title") or story["story_id"]).title()
    claims = [b.get("claim") for b in story["beats"] if b.get("claim")]
    lines = claims[:2] or [b["narration"] for b in story["beats"][:2]]
    note = ("Source/fact-check: every claim traces to this video's "
           "verified fact_ids (see pipeline_report.json).")
    description = "\n".join(lines[:2] + [note])
    blob = (str(story.get("subject", "")) + " " + str(story.get("story_type", ""))
           + " " + " ".join(c.get("id", "") for c in story.get("concepts") or [])
           + " " + title)
    tags, seen = [], set()
    for w in re.findall(r"[a-z0-9]+", blob.lower()):
        if len(w) > 2 and w not in seen:
            seen.add(w)
            tags.append(w)
        if len(tags) >= MAX_TAGS:
            break
    while len(tags) < MIN_TAGS:
        tags.append(f"{story['story_id']}_{len(tags)}")
    return {"title": title[:100], "description": description, "tags": tags}


def build_metadata(story: dict, *, use_llm: bool = True, ask=None) -> dict:
    """-> {"title", "description", "tags", "source": llm|cache|fallback,
    "llm_calls"}. Cached by story content (same convention as
    engine.v15_plan.make_plan). `ask` overrides the text judge (tests)."""
    blob = json.dumps({"v": PROMPT_VERSION, "title": story.get("title"),
                       "beats": [{k: b.get(k) for k in
                                  ("beat_id", "narration", "claim", "fact_ids")}
                                 for b in story["beats"]]}, sort_keys=True)
    key = hashlib.sha256(blob.encode()).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = CACHE_DIR / f"{key}.json"
    if cp.exists():
        data = json.loads(cp.read_text())
        if not _validate(data):
            return dict(data, source="cache", llm_calls=0)
    if use_llm:
        if ask is None:
            from engine.director import text_ask

            # text_misc: the adapter's general-purpose text stage (no new
            # llm.yaml stage needed for a straightforward JSON-ask call).
            def ask(p, t, m):
                return text_ask(p, t, m, stage="text_misc")
        raw = ask(build_prompt(story), 0.3, 800)
        meta = _parse_json(raw)
        if not _validate(meta):
            data = {"title": meta["title"], "description": meta["description"],
                    "tags": [str(t) for t in meta["tags"]]}
            cp.write_text(json.dumps(data, indent=1))
            return dict(data, source="llm", llm_calls=1)
    fb = _fallback_metadata(story)
    return dict(fb, source="fallback", llm_calls=1 if use_llm else 0)
