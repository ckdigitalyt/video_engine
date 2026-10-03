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


def wikipedia_sources(query: str, n: int = 3) -> list:
    """-> [{"id", "url", "text"}, ...] for up to `n` real Wikipedia articles
    matching `query`; fewer (even []) on a thin/no-match topic or a network
    failure — the caller (engine.v16_autostory) treats "too few sources" as
    a HOLD, same as every other research-stage failure, never a silent
    fabrication."""
    try:
        r = requests.get(API, params={"action": "query", "list": "search",
                                      "srsearch": query, "format": "json",
                                      "srlimit": n}, timeout=TIMEOUT_S)
        r.raise_for_status()
        hits = r.json().get("query", {}).get("search", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for i, h in enumerate(hits):
        title = h.get("title")
        if not title:
            continue
        try:
            r2 = requests.get(API, params={"action": "query", "prop": "extracts",
                                           "explaintext": 1, "titles": title,
                                           "format": "json"}, timeout=TIMEOUT_S)
            r2.raise_for_status()
            pages = r2.json().get("query", {}).get("pages", {})
            text = next(iter(pages.values()), {}).get("extract", "")
        except (requests.RequestException, ValueError):
            continue
        if text.strip():
            out.append({"id": f"wiki_{i + 1}",
                       "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                       "text": text[:MAX_CHARS]})
    return out
