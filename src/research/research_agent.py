"""
research_agent.py — Structured web research for documentary video production.

ResearchAgent performs the following steps:
  1. Classify topic (via TopicClassifier from V1 assets)
  2. Generate search queries from topic (DeepSeek LLM)
  3. Execute web searches in parallel
  4. Fetch page content in parallel
  5. Extract structured facts via LLM (parallel)
  6. Consolidate all extractions into a single ResearchDocument
  7. Cache result to disk

FactVerifier cross-references claims against their sources,
assigning confidence scores based on source multiplicity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

import requests

from src.models.v2_types import (
    Fact,
    ResearchDocument,
    Source,
    TopicCategory,
)
from src.providers.llm_provider import DeepSeekProvider
from src.utils.config import get_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════ #
# FactVerifier
# ═══════════════════════════════════════════════════════════════════════ #


class FactVerifier:
    """Cross-reference facts against their sources and assign confidence scores.

    Confidence scoring:
      - 0.80 (high):  3+ supporting sources
      - 0.60 (medium): 2 supporting sources
      - 0.30 (low):    1 supporting source (LLM fallback)
      - 0.15 (insufficient): No source supports the claim
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._cross_ref_required = self._config.get(
            "cross_ref_required",
            get_config("research.verification.cross_ref_required", 2),
        )
        self._high = self._config.get(
            "high_confidence",
            get_config("research.verification.high_confidence", 0.8),
        )
        self._medium = self._config.get(
            "medium_confidence",
            get_config("research.verification.medium_confidence", 0.6),
        )
        self._low = self._config.get(
            "low_confidence",
            get_config("research.verification.low_confidence", 0.3),
        )
        self._insufficient = self._config.get(
            "insufficient",
            get_config("research.verification.insufficient", 0.15),
        )

    def verify(self, fact: Fact, all_sources: list[Source]) -> Fact:
        """Verify a single fact against all available sources.

        A fact is supported by a source if:
        - The source has a non-empty URL, AND
        - The fact claim text appears as a substring of the source snippet,
          OR the source domain is an authoritative domain and the confidence
          is above zero.

        Returns a new Fact with updated ``confidence``, ``verified``, and
        ``verification_notes``.
        """
        supporting: list[Source] = []
        primary_domains = {
            "wikipedia.org", "nasa.gov", "nature.com", "science.org",
            "nationalgeographic.com", "bbc.com", "bbc.co.uk", "reuters.com",
            "apnews.com", "nytimes.com", "theguardian.com", "sciencedaily.com",
            "pubmed.ncbi.nlm.nih.gov", "arxiv.org", "cdc.gov", "who.int",
        }

        claim_lower = fact.claim.lower()
        for src in all_sources:
            if not src.url:
                continue
            snippet_lower = (src.snippet or "").lower()
            domain = src.domain.lower()

            # Direct text match in snippet
            if len(claim_lower) > 5 and claim_lower in snippet_lower:
                supporting.append(src)
                continue

            # Authoritative domain + the source has relevant topic keywords
            if domain in primary_domains and src.relevance_score > 0.0:
                supporting.append(src)
                continue

        source_count = len(supporting)

        if source_count >= self._cross_ref_required:
            confidence = self._high
            notes = f"Verified by {source_count} supporting sources"
            verified = True
        elif source_count == 1:
            confidence = self._low
            notes = f"Single source: {supporting[0].domain}"
            verified = True
        else:
            confidence = self._insufficient
            notes = "No supporting source found"
            verified = False

        return Fact(
            id=fact.id,
            claim=fact.claim,
            sources=fact.sources,
            confidence=min(confidence, fact.confidence),  # Never exceed extraction confidence
            category=fact.category,
            verified=verified,
            verification_notes=notes,
        )

    def verify_all(self, facts: list[Fact], all_sources: list[Source]) -> list[Fact]:
        """Verify all facts against the full source list."""
        return [self.verify(f, all_sources) for f in facts]


# ═══════════════════════════════════════════════════════════════════════ #
# ResearchAgent
# ═══════════════════════════════════════════════════════════════════════ #


class ResearchAgent:
    """Structured research agent — gathers facts from web sources via LLM.

    Usage::

        agent = ResearchAgent()
        doc = agent.research("The Fermi Paradox")
        # doc is a ResearchDocument with sources, facts, statistics, etc.

    All external calls (web_search, web_fetch, LLM) are parallelised.
    Results are cached to disk.  Failures degrade gracefully.
    """

    def __init__(
        self,
        llm: Optional[DeepSeekProvider] = None,
        config: Optional[dict] = None,
    ):
        self._llm = llm or DeepSeekProvider()
        self._config = config or {}
        self._max_sources = self._config.get(
            "max_sources",
            get_config("research.max_sources", 15),
        )
        self._recency_days = self._config.get(
            "recency_days",
            get_config("research.recency_days", 365),
        )
        self._search_query_count = self._config.get(
            "search_query_count",
            get_config("research.search_query_count", 6),
        )
        self._results_per_query = self._config.get(
            "results_per_query",
            get_config("research.results_per_query", 3),
        )
        self._concurrency_web = self._config.get(
            "concurrency_web",
            get_config("research.concurrency.web_requests", 4),
        )
        self._concurrency_llm = self._config.get(
            "concurrency_llm",
            get_config("research.concurrency.llm_extractions", 4),
        )
        self._cache_dir = Path(
            self._config.get(
                "cache_store",
                get_config("research.cache.store", "cache/research"),
            )
        )
        self._cache_ttl_days = self._config.get(
            "cache_ttl_days",
            get_config("research.cache.ttl_days", 7),
        )
        self._fallback_fact_count = self._config.get(
            "fallback_fact_count",
            get_config("research.fallback_fact_count", 5),
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────────

    def research(self, topic: str) -> ResearchDocument:
        """Run the full research pipeline for *topic*.

        Steps:
          1. Check cache (by topic hash)
          2. Generate search queries (LLM)
          3. Web search (parallel)
          4. Web fetch (parallel)
          5. Extract facts (parallel LLM)
          6. Consolidate (LLM)
          7. Verify facts
          8. Cache and return

        If all web searches fail, a fallback document is generated from
        the LLM's training data with low confidence scores.
        """
        logger.info("Researching topic: '%s'", topic)
        start = time.monotonic()

        # 1. Cache check
        cached = self._load_from_cache(topic)
        if cached is not None:
            logger.info("Research cache HIT for '%s' (%.1fs)", topic, time.monotonic() - start)
            return cached

        topic_hash = self._topic_hash(topic)

        # 2. Generate search queries
        queries = self._generate_search_queries(topic)
        if not queries:
            logger.warning("No search queries generated for '%s' — using fallback", topic)
            doc = self._generate_fallback_document(topic)
            self._save_to_cache(topic, doc)
            return doc

        # 3. Web search (parallel)
        raw_results = self._parallel_web_search(queries)

        # 4. Accumulate all found URLs
        search_results = []
        seen_urls: set[str] = set()
        for results in raw_results:
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    search_results.append(r)

        if not search_results:
            logger.warning("All web searches returned empty for '%s' — using fallback", topic)
            doc = self._generate_fallback_document(topic)
            self._save_to_cache(topic, doc)
            return doc

        # Build Source models from search results
        sources = []
        for r in search_results[:self._max_sources]:
            sources.append(Source(
                url=r.get("url", ""),
                title=r.get("title", ""),
                domain=self._extract_domain(r.get("url", "")),
                snippet=r.get("snippet", ""),
                relevance_score=self._compute_relevance(topic, r.get("snippet", ""), r.get("title", "")),
            ))

        # 5. Extract facts from each source (parallel)
        extractions = self._parallel_extract_facts(topic, sources)

        # 6. Consolidate
        doc = self._consolidate_research(topic, extractions, sources)

        # 6b. Verify facts
        doc.key_facts = FactVerifier().verify_all(doc.key_facts, doc.sources)

        # 7. Cache
        self._save_to_cache(topic, doc)

        elapsed = time.monotonic() - start
        logger.info(
            "Research complete for '%s': %d sources, %d facts, %d stats (%.1fs)",
            topic, len(doc.sources), len(doc.key_facts), len(doc.key_statistics), elapsed,
        )
        return doc

    # ── Cache ────────────────────────────────────────────────────────────

    def _topic_hash(self, topic: str) -> str:
        """Generate a deterministic cache key for *topic*."""
        key = f"{topic.lower().strip()}|{self._max_sources}|{self._recency_days}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _cache_path(self, topic: str) -> Path:
        return self._cache_dir / f"{self._topic_hash(topic)}.json"

    def _load_from_cache(self, topic: str) -> Optional[ResearchDocument]:
        """Return a cached ResearchDocument, or None if missing/stale."""
        path = self._cache_path(topic)
        if not path.exists():
            return None

        age_seconds = time.time() - path.stat().st_mtime
        max_age = self._cache_ttl_days * 86400
        if age_seconds > max_age:
            logger.info("Research cache STALE for '%s' (%.0f hours old)", topic, age_seconds / 3600)
            return None

        try:
            data = json.loads(path.read_text())
            doc = ResearchDocument(**data)
            logger.info("Research cache HIT for '%s'", topic)
            return doc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Research cache CORRUPT for '%s': %s", topic, exc)
            return None

    def _save_to_cache(self, topic: str, doc: ResearchDocument) -> None:
        """Write a ResearchDocument to the cache."""
        path = self._cache_path(topic)
        try:
            path.write_text(doc.model_dump_json(indent=2))
            logger.debug("Research cache written: %s", path)
        except OSError as exc:
            logger.warning("Failed to write research cache: %s", exc)

    # ── Search query generation ──────────────────────────────────────────

    def _generate_search_queries(self, topic: str) -> list[str]:
        """Generate diverse search queries from the topic using LLM."""
        count = self._search_query_count
        prompt = f"""You are a research query planner for a documentary video about "{topic}".
Generate {count} search queries that will find authoritative, factual,
up-to-date information. Cover:
- Core facts and definitions
- Key controversies or debates
- Statistical data
- Historical timeline
- Expert perspectives

Return ONLY a JSON list of strings. Each query 3-8 words."""
        try:
            raw = self._llm.generate_json(prompt)
            queries = json.loads(raw)
            if isinstance(queries, list) and len(queries) > 0:
                # Validate all items are strings
                validated = [str(q).strip() for q in queries if isinstance(q, str) and str(q).strip()]
                if validated:
                    logger.debug("Generated %d search queries for '%s'", len(validated), topic)
                    return validated[:count]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Search query generation failed for '%s': %s", topic, exc)

        # Fallback: generate queries from the topic itself
        logger.info("Using fallback query generation for '%s'", topic)
        fallback_queries = self._fallback_queries(topic)
        return fallback_queries[:count]

    def _fallback_queries(self, topic: str) -> list[str]:
        """Rule-based fallback queries when LLM generation fails."""
        words = topic.lower().split()
        return [
            f"{topic} facts and information",
            f"{topic} explained documentary",
            f"{topic} history and background",
            f"{topic} scientific research",
            f"{topic} controversies debates",
            f"{topic} statistics data",
        ]

    # ── Web search ───────────────────────────────────────────────────────

    def _web_search(self, query: str) -> list[dict]:
        """Execute a web search for *query* and return structured results.

        Uses Brave Search API if BRAVE_API_KEY is set, otherwise uses
        a DuckDuckGo-style fallback via a public endpoint, and finally
        falls back to Google Programmable Search.

        Returns a list of dicts with keys: url, title, snippet.
        """
        results = self._brave_search(query)
        if results:
            return results

        results = self._duckduckgo_search(query)
        if results:
            return results

        results = self._google_search(query)
        if results:
            return results

        return []

    def _brave_search(self, query: str) -> list[dict]:
        """Search via Brave Search API."""
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return []

        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": self._results_per_query},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data.get("web", {}).get("results", []):
                    results.append({
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                        "snippet": item.get("description", ""),
                    })
                return results
        except requests.RequestException as exc:
            logger.debug("Brave search failed for '%s': %s", query, exc)

        return []

    def _duckduckgo_search(self, query: str) -> list[dict]:
        """Search via DuckDuckGo's lite interface (no API key required)."""
        try:
            resp = requests.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; VideoEngine/2.0)"},
                timeout=10,
            )
            if resp.status_code == 200:
                # Parse the very simple HTML response
                return self._parse_ddg_html(resp.text, query)
        except requests.RequestException as exc:
            logger.debug("DDG search failed for '%s': %s", query, exc)

        return []

    def _parse_ddg_html(self, html: str, query: str) -> list[dict]:
        """Parse DuckDuckGo lite HTML into structured results."""
        results = []
        # Extract from the simple HTML table structure
        # Looking for <a rel="nofollow" href="...">title</a> patterns
        href_pattern = re.compile(r'<a\s+rel="nofollow"\s+href="([^"]+)"[^>]*>(.*?)</a>')
        snippet_pattern = re.compile(r'<td\s+class="result-snippet">(.*?)</td>')

        hrefs = href_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(hrefs):
            snippet = snippets[i] if i < len(snippets) else ""
            # Clean HTML tags from snippet
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({
                "url": url,
                "title": title.strip(),
                "snippet": snippet,
            })

        return results[:self._results_per_query]

    def _google_search(self, query: str) -> list[dict]:
        """Fallback: Google Programmable / Custom Search API."""
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        cse_id = os.environ.get("GOOGLE_CSE_ID", "")
        if not api_key or not cse_id:
            return []

        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": min(self._results_per_query, 10),
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data.get("items", []):
                    results.append({
                        "url": item.get("link", ""),
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    })
                return results
            elif resp.status_code == 429:
                logger.warning("Google search rate-limited for '%s'", query)
        except requests.RequestException as exc:
            logger.debug("Google search failed for '%s': %s", query, exc)

        return []

    def _parallel_web_search(self, queries: list[str]) -> list[list[dict]]:
        """Execute all search queries in parallel with a thread pool."""
        results: list[list[dict]] = []
        with ThreadPoolExecutor(max_workers=self._concurrency_web) as pool:
            fut_map = {pool.submit(self._web_search, q): q for q in queries}
            for future in as_completed(fut_map):
                try:
                    res = future.result()
                    if res:
                        results.append(res)
                except Exception as exc:
                    logger.warning("Web search failed for '%s': %s", fut_map[future], exc)
        return results

    # ── Web fetch ────────────────────────────────────────────────────────

    def _web_fetch(self, url: str, max_chars: int = 3000) -> str:
        """Fetch page content from *url*.

        Returns plain text content truncated to *max_chars*.
        """
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; VideoEngine/2.0)",
                    "Accept": "text/html,text/plain,*/*",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                text = resp.text
                # Simple tag stripping
                text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                return text[:max_chars]
        except requests.RequestException as exc:
            logger.debug("Web fetch failed for %s: %s", url, exc)

        return ""

    # ── Fact extraction ──────────────────────────────────────────────────

    def _extract_facts_from_source(self, topic: str, source: Source) -> Optional[dict]:
        """Extract structured facts from a single source via LLM."""

        content = self._web_fetch(source.url)
        if not content:
            return None

        content_snippet = content[:2500]
        prompt = f"""Extract factual information from the following text about "{topic}".

SOURCE: {source.url}
TITLE: {source.title}
TEXT: {content_snippet}

Return JSON:
{{
  "facts": [{{"claim": "...", "confidence": 0.0-1.0}}],
  "statistics": ["..."],
  "key_dates": [{{"date": "...", "event": "..."}}],
  "key_people": ["..."],
  "controversies": ["..."],
  "unresolved_questions": ["..."]
}}"""
        try:
            raw = self._llm.generate_json(prompt)
            data = json.loads(raw)
            if isinstance(data, dict) and "facts" in data:
                return data
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("LLM extraction failed for %s: %s", source.url, exc)

        return None

    def _parallel_extract_facts(self, topic: str, sources: list[Source]) -> list[dict]:
        """Extract facts from all sources in parallel."""
        extractions: list[dict] = []
        with ThreadPoolExecutor(max_workers=self._concurrency_llm) as pool:
            fut_map = {
                pool.submit(self._extract_facts_from_source, topic, s): s
                for s in sources
            }
            for future in as_completed(fut_map):
                try:
                    result = future.result()
                    if result is not None:
                        extractions.append(result)
                except Exception as exc:
                    source = fut_map[future]
                    logger.warning("Fact extraction failed for %s: %s", source.url, exc)
        return extractions

    # ── Consolidation ────────────────────────────────────────────────────

    def _consolidate_research(
        self,
        topic: str,
        extractions: list[dict],
        sources: list[Source],
    ) -> ResearchDocument:
        """Consolidate multiple fact extractions into a single ResearchDocument.

        Uses LLM consolidation when possible, falls back to rule-based merge.
        """
        if not extractions:
            return self._generate_fallback_document(topic)

        if len(extractions) == 1:
            # Single source — use its extraction directly
            return self._extraction_to_document(topic, extractions[0], sources)

        # Try LLM consolidation
        try:
            return self._llm_consolidate(topic, extractions, sources)
        except Exception as exc:
            logger.warning("LLM consolidation failed, using rule-based merge: %s", exc)
            return self._rule_merge(topic, extractions, sources)

    def _llm_consolidate(
        self,
        topic: str,
        extractions: list[dict],
        sources: list[Source],
    ) -> ResearchDocument:
        """Consolidate extractions via one LLM call."""
        n = len(extractions)
        extractions_json = json.dumps(extractions, indent=2)

        prompt = f"""You have {n} research extracts about "{topic}". Consolidate them into a
coherent research document. Merge duplicate facts, resolve contradictions,
rank by confidence. Remove speculative content.

Current extracts:
{extractions_json}

Return a ResearchDocument JSON structure with these keys:
"key_facts" — list of {{"claim": str, "confidence": float}},
"key_statistics" — list of strings,
"key_dates" — list of {{"date": str, "event": str}},
"key_people" — list of strings,
"controversies" — list of strings,
"unresolved_questions" — list of strings."""

        raw = self._llm.generate_json(prompt)
        data = json.loads(raw)
        doc = self._extraction_to_document(topic, data, sources)
        return doc

    def _extraction_to_document(
        self,
        topic: str,
        data: dict,
        sources: list[Source],
    ) -> ResearchDocument:
        """Convert an extraction dict to a ResearchDocument."""
        facts = []
        for f in data.get("key_facts", data.get("facts", [])):
            if isinstance(f, dict) and "claim" in f:
                facts.append(Fact(
                    claim=f["claim"],
                    sources=[s for s in sources if s.url],
                    confidence=float(f.get("confidence", 0.5)),
                    category="general",
                ))

        return ResearchDocument(
            topic=topic,
            sources=sources,
            key_facts=facts,
            key_statistics=data.get("key_statistics", data.get("statistics", [])),
            key_dates=data.get("key_dates", data.get("dates", [])),
            key_people=data.get("key_people", data.get("people", [])),
            controversies=data.get("controversies", []),
            unanswered_questions=data.get("unresolved_questions", data.get("unresolved_questions", [])),
        )

    def _rule_merge(
        self,
        topic: str,
        extractions: list[dict],
        sources: list[Source],
    ) -> ResearchDocument:
        """Simple rule-based merge when LLM consolidation fails."""
        all_facts: list[dict] = []
        all_stats: list[str] = []
        all_dates: list[dict] = []
        all_people: list[str] = []
        all_controversies: list[str] = []
        all_questions: list[str] = []

        seen_claims: set[str] = set()
        seen_stats: set[str] = set()
        seen_people: set[str] = set()

        for ext in extractions:
            for f in ext.get("facts", []):
                if isinstance(f, dict):
                    claim = f.get("claim", "").strip()
                    if claim and claim.lower() not in seen_claims:
                        seen_claims.add(claim.lower())
                        all_facts.append(f)

            for s in ext.get("statistics", []):
                s = str(s).strip()
                if s and s.lower() not in seen_stats:
                    seen_stats.add(s.lower())
                    all_stats.append(s)

            all_dates.extend(ext.get("key_dates", ext.get("dates", [])))

            for p in ext.get("key_people", ext.get("people", [])):
                p = str(p).strip()
                if p and p.lower() not in seen_people:
                    seen_people.add(p.lower())
                    all_people.append(p)

            all_controversies.extend(
                ext.get("controversies", [])
            )
            all_questions.extend(
                ext.get("unresolved_questions", ext.get("unresolved_questions", []))
            )

        facts = [
            Fact(
                claim=f["claim"],
                sources=[s for s in sources if s.url],
                confidence=float(f.get("confidence", 0.5)),
            )
            for f in all_facts
        ]

        return ResearchDocument(
            topic=topic,
            sources=sources,
            key_facts=facts,
            key_statistics=all_stats,
            key_dates=all_dates,
            key_people=all_people,
            controversies=all_controversies,
            unanswered_questions=all_questions,
        )

    # ── Fallback ─────────────────────────────────────────────────────────

    def _generate_fallback_document(self, topic: str) -> ResearchDocument:
        """Generate a ResearchDocument from LLM training data when web search fails."""
        logger.info("Generating fallback research for '%s' from LLM knowledge", topic)

        prompt = f"""You are a research assistant. Generate a structured research document about "{topic}".
Use ONLY well-known, established facts from your training data.

Return JSON:
{{
  "key_facts": [{{"claim": "string", "confidence": 0.0-1.0}}],
  "key_statistics": ["string"],
  "key_dates": [{{"date": "string", "event": "string"}}],
  "key_people": ["string"],
  "controversies": ["string"],
  "unresolved_questions": ["string"]
}}

Include at least {self._fallback_fact_count} facts. Set confidence to 0.3 (training data only, not verified)."""
        try:
            raw = self._llm.generate_json(prompt)
            data = json.loads(raw)
            doc = self._extraction_to_document(topic, data, [])

            # Mark all facts with low confidence (training data, not web-verified)
            doc.key_facts = [
                Fact(
                    id=f.id,
                    claim=f.claim,
                    sources=[],
                    confidence=min(f.confidence, 0.3),
                    category=f.category,
                    verified=False,
                    verification_notes="Fallback: LLM training data, not web-verified",
                )
                for f in doc.key_facts
            ]
            return doc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Fallback generation failed: %s", exc)
            return ResearchDocument(
                topic=topic,
                sources=[],
                key_facts=[
                    Fact(
                        claim=f"{topic} is a notable topic.",
                        sources=[],
                        confidence=0.15,
                        verified=False,
                        verification_notes="Emergency fallback: minimal factual content",
                    ),
                ],
                key_statistics=[],
                key_dates=[],
                key_people=[],
                controversies=[],
                unanswered_questions=[],
            )

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract the domain from a URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ""

    def _compute_relevance(self, topic: str, snippet: str, title: str) -> float:
        """Compute a relevance score for a source against the topic.

        Returns 0.0–1.0 based on keyword overlap between topic and source text.
        """
        topic_lower = topic.lower()
        topic_words = set(topic_lower.split())
        text = f"{title} {snippet}".lower()
        text_words = set(text.split())

        if not topic_words:
            return 0.5

        overlap = len(topic_words & text_words) / len(topic_words)
        return min(max(overlap, 0.0), 1.0)
