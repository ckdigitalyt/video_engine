"""Decision #13 item 5 — closes the "freshly ideated topic has no sources"
gap `engine.v16_research.build_facts` leaves to its caller: a plain-text
Wikipedia fetch (public REST API, no key, stdlib `requests` only — no new
dependency and no paid/custom search service, per the existing-solutions
preflight).
"""
from __future__ import annotations

import requests

API = "https://en.wikipedia.org/w/api.php"
TIMEOUT_S = 10
MAX_CHARS = 6000
# Wikipedia's API 403s a request with no descriptive User-Agent (their API
# etiquette policy, not an auth wall) — confirmed live during the decision
# #13 item 6 dry run: every query returned 403/empty until this was added.
HEADERS = {"User-Agent": "video_engine-research-bot/1.0 "
                        "(https://github.com/ckdigitalyt/video_engine; "
                        "contact: ckdigitalyt@gmail.com)"}


def _search(query: str, n: int) -> list:
    """-> up to `n` article titles for `query` ([] on any failure)."""
    try:
        r = requests.get(API, params={"action": "query", "list": "search",
                                      "srsearch": query, "format": "json",
                                      "srlimit": n}, timeout=TIMEOUT_S,
                         headers=HEADERS)
        r.raise_for_status()
        hits = r.json().get("query", {}).get("search", [])
    except (requests.RequestException, ValueError):
        return []
    return [h["title"] for h in hits if h.get("title")]


def _extract(title: str) -> str:
    try:
        r2 = requests.get(API, params={"action": "query", "prop": "extracts",
                                       "explaintext": 1, "titles": title,
                                       "format": "json"}, timeout=TIMEOUT_S,
                          headers=HEADERS)
        r2.raise_for_status()
        pages = r2.json().get("query", {}).get("pages", {})
        return next(iter(pages.values()), {}).get("extract", "")
    except (requests.RequestException, ValueError):
        return ""


def _fetch(titles: list, n: int) -> list:
    out = []
    for title in titles:
        if len(out) >= n:
            break
        text = _extract(title)
        if text.strip():
            out.append({"id": f"wiki_{len(out) + 1}",
                        "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                        "text": text[:MAX_CHARS]})
    return out


def wikipedia_sources(query: str, n: int = 3) -> list:
    """-> [{"id", "url", "text"}, ...] for up to `n` real Wikipedia articles
    matching `query`; fewer (even []) on a thin/no-match topic or a network
    failure — the caller (engine.v16_autostory) treats "too few sources" as
    a HOLD, same as every other research-stage failure, never a silent
    fabrication."""
    return _fetch(_search(query, n), n)


def source_queries(candidate: dict) -> list:
    """Search queries for a topic candidate, most specific first: the
    candidate's own `entities.subject` (engine.v16_topics ideation already
    names it -- "Burgess Shale fossils", "Jack Hills zircon"), then subject
    + phenomenon, then the title as before."""
    ents = candidate.get("entities") if isinstance(candidate.get("entities"), dict) else {}
    subj = str(ents.get("subject") or "").strip()
    phen = str(ents.get("phenomenon") or "").strip()
    qs = [subj, f"{subj} {phen}".strip() if subj and phen else "",
          str(candidate.get("title") or "").strip()]
    return list(dict.fromkeys(q for q in qs if q))


def candidate_sources(candidate: dict, n: int = 3) -> list:
    """Sources for a topic candidate, not just its headline.

    2026-10-16 (zero-publish day): searching Wikipedia with the curiosity-gap
    TITLE was the single biggest research-stage loss. Measured live:
      "The Burgess Shale Froze an Explosion of Alien-Looking Animal Life"
          -> 0 articles          ("Burgess Shale fossils" -> 3, on-subject)
      "The Grand Canyon Was Carved in a Geological Blink of an Eye"
          -> Manhattan, Los_Angeles_River (every claim then dropped as
             off-subject)        ("Grand Canyon" -> Grand_Canyon, ...)
      "Astronomers Found a Planet Where It Rains Glass Sideways"
          -> 1 (a TV episode list)
      "A Magnetar Could Wipe a Hard Drive From Half a Galaxy Away"
          -> 1 (2020_in_science) ("magnetar" -> Magnetar, ...)
    Hits from the entity queries are interleaved round-robin (best hit of
    each first) so one query's homonyms ("Magnetar_Capital") can't crowd
    out the others; the title query -- the noisiest -- only fills what is
    left. Same MIN_SOURCES / quote-check / same_subject bar downstream; this
    only changes WHICH articles reach it."""
    qs = source_queries(candidate)
    title = str(candidate.get("title") or "").strip()
    lists = [_search(q, n) for q in qs if q != title]
    order = []
    for rank in range(max((len(x) for x in lists), default=0)):
        order += [hits[rank] for hits in lists if rank < len(hits)]
    if title:
        order += _search(title, n)
    return _fetch(list(dict.fromkeys(order)), n)
