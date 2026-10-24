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
# Owner directive 2026-10-11: max-SEO description + "use tags/keywords to
# the full extent" for @most.amazing.wonders. v1.0's prompt asked for a
# bare 2-3 line summary and only 5-8 tags -- nowhere near YouTube's real
# headroom (tags alone allow ~500 characters total, easily 20-30 short
# tags; see tools/youtube_upload.py's character-budget packer, fixed the
# same day the old `[:500]`-on-a-list bug did nothing). bvp bump forces
# every cached description/tag set to regenerate under the new prompt.
# 2026-10-15 review: titles read as topic labels ("Sound Waves That Levitate
# Objects (It's Real)"), descriptions gave away the whole payoff, and the
# "Source/fact-check: based on peer-reviewed..." line was vague boilerplate.
# meta/3.0: curiosity-gap title held to v16_script.check_title (the same
# 4-8 word / no-trope rules the script stage's metadata_pack uses -- the two
# title paths disagreed before: this one only capped 70 characters), a
# description that stops short of the answer, and real source URLs from the
# research stage appended in code instead of an LLM-written source line.
# meta/3.1 (2026-10-24 analytics review): the plain searchable title "Sound
# Waves That Levitate Objects" got 12% of its views from YouTube search vs
# 2-3% for curiosity-gap titles, so a title may now lead with the literal,
# searchable subject name + colon + a curiosity hook (hybrid). A bare topic
# label is still not allowed. The shape is code-checked by
# v16_script.check_title_lead_in.
PROMPT_VERSION = "meta/3.1"
MIN_TAGS, MAX_TAGS = 15, 30


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
    return f"""You are writing maximum-SEO YouTube Shorts metadata for
"Most Amazing" (@most.amazing.wonders), a fact-checked deep-time/science
explainer channel. Title: {story.get('title', story['story_id'])}
Subject: {story.get('subject', '')}

Beats (the whole narration, in order):
{beats}

Fact IDs already verified upstream by the research stage: {', '.join(facts) or 'none recorded'}

Write:
 title: 4-8 words, <= 70 characters. It must open a SPECIFIC curiosity gap
   and must not label the topic and stop there. Two shapes work:
   (a) searchable label + hook: the literal name someone would type into
       YouTube search for this subject (1-4 words), a colon, then a
       curiosity hook of 3+ words, e.g. "Acoustic Levitation: Sound That
       Holds Objects Up". Prefer this when the subject has a well-known,
       searchable name (a phenomenon, creature, place, object). On this
       channel a literal, searchable title earned ~12% of its views from
       search, against 2-3% for pure curiosity-gap titles.
   (b) pure curiosity gap: a question about the surprising thing, or an
       incomplete claim that names the specific thing but withholds what
       happened / what it means.
   Either way a viewer should know exactly what they will find out, but not
   the answer. No generic tails ("Explained", "The Truth"), no
   parenthetical tags like "(It's Real)", no ALL-CAPS words (acronyms
   excepted), no "shocked", "you won't believe", "mind-blowing",
   "baffled", "gone wrong". True to the beats.
 description: optimise for search AND click-through, in this order:
   1. ONE scroll-stopping opening line (shows before "...more" on mobile) that
      restates the hook's curiosity gap -- this line matters most for CTR.
   2. 2-3 more lines that build the setup and stakes, naturally working in
      the specific named things a viewer would search for (places, people,
      dates, named phenomena from the beats above). DO NOT give away the
      payoff: never state what the PAYOFF beats reveal or the final answer
      -- stop short of it so the video is the only place to get it.
   3. A short line inviting the viewer to follow/subscribe for more
      (channel growth, not just this video).
   4. No source line -- real source links are appended automatically.
   5. 3-5 relevant hashtags on their own line at the very end, always
      including #shorts first (critical for the Shorts discovery shelf),
      then 2-4 more specific to this video's actual subject.
 tags: 15-30 short lowercase search tags (no '#'), using as much of
   YouTube's real ~500-character tag budget as the subject supports --
   NOT just the 5-8 most obvious ones. Cover: the specific named subject
   terms, the broader topic/category, common ways someone would phrase a
   search for this ("why does X happen", "what is X"), and a few
   channel-level discovery terms (e.g. "shorts", "science facts",
   "mind blowing facts") alongside the video-specific ones. Every tag
   must still be genuinely relevant -- no unrelated tags just to fill
   space.

Return ONLY JSON:
{{"title": "...", "description": "...", "tags": ["...", "..."]}}"""


def check_title_rules(title: str) -> list:
    """The script stage's title rules (engine.v16_script.check_title), so
    the uploaded title and metadata_pack's title obey ONE rule set."""
    from engine.v16_script import check_title
    errs = check_title(title)
    if re.search(r"\([^)]*\)", title):
        errs.append("title: parenthetical tag")
    return errs


_SOURCE_LINE = re.compile(r"(?im)^\s*sources?(?:/fact-check)?\s*:.*$\n?")


def with_sources(description: str, sources: list) -> str:
    """Drop any LLM-written "Source/fact-check:" boilerplate; when the
    story carries real research sources, list them just above the
    hashtag line."""
    desc = _SOURCE_LINE.sub("", description).rstrip()
    urls = list(dict.fromkeys(str(u) for u in sources or [] if u))[:5]
    if not urls:
        return desc
    block = "Sources:\n" + "\n".join(f"- {u}" for u in urls)
    lines = desc.split("\n")
    if lines and lines[-1].lstrip().startswith("#"):
        return "\n".join(lines[:-1]).rstrip() + "\n\n" + block + "\n\n" + lines[-1]
    return desc + "\n\n" + block


def _validate(meta) -> list:
    errs = []
    if not isinstance(meta, dict):
        return ["not a JSON object"]
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        errs.append("title: missing")
    elif len(title) > 100:
        errs.append("title: too long")
    else:
        errs += check_title_rules(title)
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errs.append("description: missing")
    tags = meta.get("tags")
    if not isinstance(tags, list) or not (MIN_TAGS <= len(tags) <= MAX_TAGS) \
            or not all(isinstance(t, str) and t.strip() for t in tags):
        errs.append(f"tags: need {MIN_TAGS}-{MAX_TAGS} non-empty strings")
    return errs


# Channel-level discovery tags (no LLM needed): real search terms, used to
# pad the deterministic fallback up to MIN_TAGS instead of synthetic
# "<story_id>_7"-style junk, and genuinely relevant on every video here.
_CHANNEL_TAGS = ("shorts", "youtube shorts", "science facts", "mind blowing facts",
                 "amazing facts", "did you know", "fun facts", "weird facts",
                 "science shorts", "educational shorts", "most amazing",
                 "interesting facts", "wow facts", "fact check")


def _fallback_metadata(story: dict) -> dict:
    """Deterministic, story-fields-only floor (no LLM): never blocks the
    manifest on an adapter outage."""
    title = str(story.get("title") or story["story_id"]).title()
    claims = [b.get("claim") for b in story["beats"] if b.get("claim")]
    lines = claims[:2] or [b["narration"] for b in story["beats"][:2]]
    description = with_sources("\n".join(lines[:2] + ["", "#shorts #sciencefacts #amazingfacts"]),
                               story.get("sources"))
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
    for t in _CHANNEL_TAGS:
        if len(tags) >= MIN_TAGS:
            break
        if t not in seen:
            seen.add(t)
            tags.append(t)
    return {"title": title[:100], "description": description, "tags": tags}


def build_metadata(story: dict, *, use_llm: bool = True, ask=None) -> dict:
    """-> {"title", "description", "tags", "source": llm|cache|fallback,
    "llm_calls"}. Cached by story content (same convention as
    engine.v15_plan.make_plan). `ask` overrides the text judge (tests)."""
    blob = json.dumps({"v": PROMPT_VERSION, "title": story.get("title"),
                       "sources": story.get("sources"),
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
        raw = ask(build_prompt(story), 0.3, 1400)  # longer description + up to 30 tags
        meta = _parse_json(raw)
        errs = _validate(meta)
        if errs and isinstance(meta, dict):
            # one targeted retry (title rules are the usual miss)
            raw = ask(build_prompt(story) + "\n\nYour previous answer failed "
                      "these checks; fix them and return the full JSON again:\n"
                      + "\n".join(errs), 0.3, 1400)
            meta2 = _parse_json(raw)
            if isinstance(meta2, dict):
                meta = meta2
        # Cap, don't reject, a slight over-count: discarding an otherwise
        # good title/description because the model wrote 32 tags instead
        # of <=30 would waste the whole LLM response on the fallback path.
        if isinstance(meta, dict) and isinstance(meta.get("tags"), list):
            meta["tags"] = meta["tags"][:MAX_TAGS]
        if not _validate(meta):
            data = {"title": meta["title"],
                    "description": with_sources(meta["description"],
                                                story.get("sources")),
                    "tags": [str(t) for t in meta["tags"]]}
            cp.write_text(json.dumps(data, indent=1))
            return dict(data, source="llm", llm_calls=1)
    fb = _fallback_metadata(story)
    return dict(fb, source="fallback", llm_calls=1 if use_llm else 0)
