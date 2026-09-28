"""S1 research pack -> facts with a verbatim quote check (DESIGN §3 S1, §9.4).

    build_facts(topic, sources)   sources = [{id, url, text}] already fetched
        -> {"claims": [...], "dropped": [...]}; one `research_extract` call.
    from_curated(pack)            a hand-curated bench pack (verified:true claims)

Every LLM-extracted claim must carry a quote that EXISTS in the named source's
text (code check, whitespace/quote-style tolerant) and its claim text may not add
numbers the quote does not contain. Claims failing either are dropped; fewer than
MIN_CLAIMS survivors is a HOLD. Fetching is the caller's job (no network here).
"""
from __future__ import annotations

import re
import unicodedata

from llm import client as llm
from llm.prompts import render

MIN_CLAIMS = 3
MAX_SOURCE_CHARS = 12000        # per source, keeps the extract prompt bounded


class ResearchHold(Exception):
    """Not enough checkable facts to write a script."""


# ------------------------------------------------------------- numbers --

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"thousand": 10**3, "million": 10**6, "billion": 10**9, "trillion": 10**12}
_TOKEN = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|[A-Za-z]+|-|[^\w\s]")


def numbers_in(text: str, min_spelled: int = 0) -> set:
    """Numeric values mentioned in `text`, digits or spelled ("sixty-five",
    "eighty million", "80 million"). Spelled values below `min_spelled` are
    ignored: "one"/"two" are mostly idiom ("one of", "in two ways") in narration.
    Years and ordinals are read as their digits."""
    toks = _TOKEN.findall(text)
    out, i, n = set(), 0, len(toks)
    while i < n:
        t = toks[i]
        if t[0].isdigit():
            v = float(t.replace(",", ""))
            if i + 1 < n and toks[i + 1].lower() in _SCALES:
                v *= _SCALES[toks[i + 1].lower()]
                i += 1
            out.add(v)
            i += 1
            continue
        w = t.lower()
        if w in _UNITS or w in _TENS or w in _SCALES or w == "hundred":
            total, cur, last, j = 0, 0, None, i
            while j < n:
                w = toks[j].lower()
                if w == "-" and last and j + 1 < n and toks[j + 1].lower() in _UNITS:
                    j += 1
                    continue
                if w == "and" and last in ("hundred", "scale") and j + 1 < n \
                        and toks[j + 1].lower() in {**_UNITS, **_TENS}:
                    j += 1
                    continue
                if w in _UNITS and last in (None, "hundred", "scale", "tens"):
                    if last == "tens" and _UNITS[w] > 9:
                        break
                    cur += _UNITS[w]
                    last = "unit"
                elif w in _UNITS:
                    break                       # "seven five": two numbers
                elif w in _TENS and last in (None, "hundred", "scale"):
                    cur += _TENS[w]
                    last = "tens"
                elif w == "hundred":
                    cur = max(cur, 1) * 100
                    last = "hundred"
                elif w in _SCALES:
                    total += max(cur, 1) * _SCALES[w]
                    cur, last = 0, "scale"
                else:
                    break
                j += 1
            v = total + cur
            if v >= min_spelled:
                out.add(float(v))
            i = max(j, i + 1)
            continue
        i += 1
    return out


# --------------------------------------------------------------- quotes --

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", "−": "-", " ": " "})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip().casefold()


def quote_exists(quote: str, source_text: str) -> bool:
    """The quote occurs verbatim in the source text (case, whitespace, curly
    quotes and dash style ignored; any other difference is a miss)."""
    q = _norm(quote)
    return len(q) >= 12 and q in _norm(source_text)


# ---------------------------------------------------------------- facts --

def usable(fact: dict) -> bool:
    return bool(fact.get("quote_verified") or (fact.get("curated") and fact.get("verified")))


def _nuance(v) -> str:
    if isinstance(v, dict):
        v = v.get("classification")
    if v in ("ESTABLISHED", "CONTESTED", "HYPOTHESIS"):
        return v
    return "CONTESTED"              # DEBATED_DETAIL or anything unknown: never upgrade to settled


def from_curated(pack: dict) -> dict:
    """Bench pack claims -> fact records. Only claims marked verified:true are
    usable; they carry no verbatim quote, so quote_verified stays False. A source-
    check `correction` replaces the claim wording."""
    claims = []
    for c in pack["claims"]:
        claims.append({
            "id": c["id"], "claim": c.get("correction") or c["claim"],
            "evidence": c.get("measured_value") or c.get("correction") or c["claim"],
            "quote": None, "quote_verified": False, "curated": True,
            "verified": bool(c.get("verified")),
            "source_id": c.get("authoritative_source") or c.get("source_hint", ""),
            "source_url": c.get("source_url", ""),
            "nuance": _nuance(c.get("nuance")),
        })
    return {"topic": pack.get("title", ""), "claims": claims, "dropped": []}


def check_claim(c: dict, sources: dict) -> str | None:
    """-> None if the extracted claim passes the S1 code checks, else the reason."""
    text = sources.get(c["source_id"])
    if text is None:
        return "unknown source_id"
    if not quote_exists(c["quote"], text):
        return "quote not found in source"
    extra = numbers_in(c["claim"]) - numbers_in(c["quote"])
    if extra:
        return f"claim has numbers not in the quote: {sorted(extra)}"
    return None


def build_facts(topic: str, sources: list, *, ask=None) -> dict:
    ask = ask or llm.ask
    by_id = {s["id"]: s["text"][:MAX_SOURCE_CHARS] for s in sources}
    block = "\n\n".join(f"### SOURCE {s['id']} ({s.get('url', '')})\n{s['text'][:MAX_SOURCE_CHARS]}"
                        for s in sources)
    prompt, ver = render("research_extract", topic=topic, sources=block)
    res = ask("research_extract", prompt, schema="research_extract", prompt_version=ver)
    urls = {s["id"]: s.get("url", "") for s in sources}
    claims, dropped = [], []
    for c in res.data["claims"]:
        why = check_claim(c, by_id)
        if why:
            dropped.append({"id": c["id"], "reason": why})
            continue
        claims.append({**c, "evidence": c["quote"], "quote_verified": True, "curated": False,
                       "verified": True, "source_url": urls.get(c["source_id"], "")})
    if len(claims) < MIN_CLAIMS:
        raise ResearchHold(f"only {len(claims)} claims passed the quote check "
                           f"(need {MIN_CLAIMS}); dropped: {dropped}")
    return {"topic": topic, "claims": claims, "dropped": dropped, "prompt_version": ver}
