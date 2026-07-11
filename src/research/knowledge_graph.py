"""
knowledge_graph.py — KnowledgeGraph builder for the video_engine pipeline.

Transforms a flat ``ResearchDocument`` into a structured ``KnowledgeGraph``
with typed nodes (concepts, people, events, dates, statistics) and directed
edges representing relationships (causes, contradicts, supports, precedes,
proposed, example_of, predicts, questions, solves).

Usage::

    builder = KnowledgeGraphBuilder(llm=some_llm_provider)
    kg = builder.build(research_doc)

The builder uses two LLM calls (entity extraction, relationship extraction).
On failure it degrades gracefully:

  1. LLM entity extraction fails → rule-based node generation from the doc
  2. LLM relationship extraction fails → star graph (all nodes → topic)
  3. No entities found at all → single node with the topic label

Results are cached to ``cache/knowledge/{key}.json`` (TTL 30 days).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from src.models.v2_types import (
    Fact,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    ResearchDocument,
)
from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider
from src.utils.config import get_config

logger = logging.getLogger(__name__)

# ── Relationship vocabulary ────────────────────────────────────────────

VALID_RELATIONSHIPS = {
    "proposed",
    "contradicts",
    "supports",
    "causes",
    "precedes",
    "example_of",
    "predicts",
    "questions",
    "solves",
}

_ENTITY_TYPES = {"concept", "person", "event", "date", "stat", "place"}


class KnowledgeGraphBuilder:
    """Build a structured ``KnowledgeGraph`` from a ``ResearchDocument``.

    Parameters
    ----------
    llm : LLMProvider, optional
        LLM provider for entity/relationship extraction.  If ``None``, uses
        ``ProviderFactory`` to resolve one for the ``planner`` role.
    config : dict, optional
        Override configuration keys.
    """

    def __init__(
        self,
        llm: Optional[LLMProvider] = None,
        config: Optional[dict] = None,
    ):
        if llm is not None:
            self._llm = llm
        else:
            factory = ProviderFactory()
            self._llm = factory.get_llm_provider_for_role("planner")

        self._config = config or {}

        # Cache settings
        self._cache_dir = Path(
            self._config.get(
                "cache_store",
                get_config("knowledge.cache.store", "cache/knowledge"),
            )
        )
        self._cache_ttl_days = self._config.get(
            "cache_ttl_days",
            get_config("knowledge.cache.ttl_days", 30),
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # SQLite store
        self._sqlite_path = Path(
            self._config.get(
                "sqlite_store",
                get_config("knowledge.cache.sqlite", "cache/knowledge/graphs.db"),
            )
        )
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()

    # ── Public API ───────────────────────────────────────────────────────

    def build(self, document: ResearchDocument) -> KnowledgeGraph:
        """Build a knowledge graph from a research document.

        Steps:
          1. Cache check (by document content hash)
          2. Entity extraction (LLM), with fallback
          3. Relationship extraction (LLM), with fallback
          4. Construct KnowledgeGraph
          5. Cache result
          6. Store in SQLite
          7. Return
        """
        topic = document.topic
        cache_key = self._content_hash(document)

        # 1. Cache check
        cached = self._load_from_cache(cache_key)
        if cached is not None:
            logger.info("KnowledgeGraph cache HIT for '%s'", topic)
            return cached

        # 2. Entity extraction
        entities = self._extract_entities(document)
        if not entities.get("all_nodes"):
            logger.warning("Entity extraction returned empty for '%s' — using fallback", topic)
            entities = self._fallback_entities(document)

        # 3. Relationship extraction
        if len(entities.get("all_nodes", [])) >= 2:
            edges = self._extract_relationships(topic, entities["all_nodes"])
        else:
            edges = []
            logger.info("Skipping relationship extraction (only 0-1 entities)")

        # 4. Build graph
        kg = KnowledgeGraph(
            nodes=entities.get("all_nodes", []),
            edges=edges or [],
            topic=topic,
        )

        # 5. Cache
        self._save_to_cache(cache_key, kg)

        # 6. SQLite
        self._store_to_sqlite(topic, cache_key, kg)

        logger.info(
            "KnowledgeGraph built for '%s': %d nodes, %d edges",
            topic, len(kg.nodes), len(kg.edges),
        )
        return kg

    # ── Entity extraction ───────────────────────────────────────────────

    def _extract_entities(self, document: ResearchDocument) -> dict:
        """Extract entities from a research document via LLM.

        Returns a dict with keys ``concepts``, ``people``, ``events``,
        ``dates``, ``stats``, and ``all_nodes``.
        """
        topic = document.topic

        # Build a compact JSON representation of the research doc for the prompt
        doc_json = {
            "topic": document.topic,
            "key_facts": [f.model_dump(include={"claim", "confidence", "category"})
                          for f in document.key_facts],
            "key_statistics": document.key_statistics,
            "key_people": document.key_people,
            "key_dates": document.key_dates,
            "timelines": document.timelines,
            "controversies": document.controversies,
            "unanswered_questions": document.unanswered_questions,
        }

        prompt = f"""From this research document about "{topic}", extract all named entities (concepts, people, events, dates, places, statistics).

Research: {json.dumps(doc_json, indent=2)}

Return ONLY a raw JSON object. Use short alphanumeric ids (e.g. "c1", "c2").

Schema:
{{
  "concepts": [{{"id": "c1", "label": "Great Filter", "description": "Brief description."}}],
  "people": [{{"id": "p1", "label": "Enrico Fermi", "description": "Brief description."}}],
  "events": [{{"id": "e1", "label": "Drake Equation (1961)", "description": "Brief description."}}],
  "dates": [{{"id": "d1", "label": "1961", "description": "Context for this date."}}],
  "statistics": [{{"id": "s1", "label": "100 billion stars", "description": "Context."}}],
  "places": [{{"id": "l1", "label": "Milky Way", "description": "Brief description."}}]
}}

Rules:
- Extract at least 3 entities, up to 20.
- Each entity must have a unique id.
- Labels should be concise (2-6 words).
- Groups by type: concept, person, event, date, stat, place.
- Use empty arrays for types not found."""
        try:
            raw = self._llm.generate_json(prompt)
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("LLM entity extraction failed: %s", exc)
            return self._fallback_entities(document)

        return self._parse_entities(data, document)

    def _parse_entities(self, data: dict, document: ResearchDocument) -> dict:
        """Parse LLM entity response into KnowledgeNode lists."""
        result: dict[str, list[KnowledgeNode]] = {
            "concepts": [],
            "people": [],
            "events": [],
            "dates": [],
            "stats": [],
            "places": [],
        }
        seen_ids: set[str] = set()
        type_map = {
            "concepts": "concept",
            "people": "person",
            "events": "event",
            "dates": "date",
            "statistics": "stat",
            "stats": "stat",
            "places": "place",
        }

        for json_key, pydantic_type in type_map.items():
            items = data.get(json_key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                eid = str(item.get("id", ""))
                if eid in seen_ids or not eid:
                    continue
                seen_ids.add(eid)
                result.setdefault(json_key.replace("statistics", "stats").replace("stats", "stats"), [])
                # Normalise the key for the result
                category = pydantic_type
                if pydantic_type == "stat":
                    result_key = "stats"
                else:
                    result_key = json_key if json_key in result else f"{pydantic_type}s"
                result.setdefault(result_key, [])
                node = KnowledgeNode(
                    id=eid,
                    label=str(item.get("label", "")),
                    type=pydantic_type,
                    description=str(item.get("description", "")),
                )
                result[result_key].append(node)

        # Also inject key_people and key_dates from document that the LLM might have missed
        doc_people = document.key_people
        doc_dates = document.key_dates
        doc_stats = document.key_statistics

        for person_name in doc_people:
            if not person_name:
                continue
            eid = self._slug_id(person_name, seen_ids)
            if eid not in seen_ids:
                seen_ids.add(eid)
                result.setdefault("people", [])
                result["people"].append(KnowledgeNode(
                    id=eid,
                    label=person_name[:80],
                    type="person",
                    description=f"Key person mentioned in research on {document.topic}",
                ))

        for date_entry in doc_dates:
            if isinstance(date_entry, dict):
                date_label = date_entry.get("date", "") or date_entry.get("label", "")
                date_desc = date_entry.get("event", "") or date_entry.get("description", "")
            else:
                date_label = str(date_entry)
                date_desc = ""
            if not date_label:
                continue
            eid = self._slug_id(f"date_{date_label}", seen_ids)
            if eid not in seen_ids:
                seen_ids.add(eid)
                result.setdefault("dates", [])
                result["dates"].append(KnowledgeNode(
                    id=eid,
                    label=str(date_label)[:80],
                    type="date",
                    description=str(date_desc)[:200],
                ))

        for stat_text in doc_stats:
            if not stat_text:
                continue
            eid = self._slug_id(f"stat_{stat_text[:40]}", seen_ids)
            if eid not in seen_ids:
                seen_ids.add(eid)
                result.setdefault("stats", [])
                result["stats"].append(KnowledgeNode(
                    id=eid,
                    label=str(stat_text)[:80],
                    type="stat",
                    description=f"Statistic from research on {document.topic}",
                ))

        # Build flat all_nodes list
        all_nodes: list[KnowledgeNode] = []
        for key in ("concepts", "people", "events", "dates", "stats", "places"):
            all_nodes.extend(result.get(key, []))

        result["all_nodes"] = all_nodes
        return result

    def _fallback_entities(self, document: ResearchDocument) -> dict:
        """Rule-based entity extraction when LLM call fails."""
        result: dict[str, list[KnowledgeNode]] = {
            "concepts": [],
            "people": [],
            "events": [],
            "dates": [],
            "stats": [],
            "places": [],
        }
        seen_ids: set[str] = set()

        # Topic as a concept
        topic = document.topic
        if topic:
            nid = self._slug_id(topic, seen_ids)
            seen_ids.add(nid)
            result["concepts"].append(KnowledgeNode(
                id=nid,
                label=topic[:80],
                type="concept",
                description=f"Main topic: {topic}",
            ))

        # People
        for person_name in document.key_people:
            if not person_name:
                continue
            eid = self._slug_id(person_name, seen_ids)
            if eid not in seen_ids:
                seen_ids.add(eid)
                result["people"].append(KnowledgeNode(
                    id=eid, label=person_name[:80], type="person",
                    description=f"Key person in {topic}",
                ))

        # Dates
        for date_entry in document.key_dates:
            label = date_entry.get("date", "") if isinstance(date_entry, dict) else str(date_entry)
            desc = date_entry.get("event", "") if isinstance(date_entry, dict) else ""
            if not label:
                continue
            eid = self._slug_id(f"date_{label}", seen_ids)
            if eid not in seen_ids:
                seen_ids.add(eid)
                result["dates"].append(KnowledgeNode(
                    id=eid, label=str(label)[:80], type="date",
                    description=str(desc)[:200],
                ))

        # Statistics
        for stat in document.key_statistics:
            if not stat:
                continue
            eid = self._slug_id(f"stat_{stat[:40]}", seen_ids)
            if eid not in seen_ids:
                seen_ids.add(eid)
                result["stats"].append(KnowledgeNode(
                    id=eid, label=str(stat)[:80], type="stat",
                    description=f"Statistic from research on {topic}",
                ))

        # Facts → concepts
        for fact in document.key_facts:
            if not fact.claim:
                continue
            label = fact.claim[:60]
            eid = self._slug_id(f"fact_{label}", seen_ids)
            if eid not in seen_ids:
                seen_ids.add(eid)
                result["concepts"].append(KnowledgeNode(
                    id=eid, label=label, type="concept",
                    description=f"Claim (confidence={fact.confidence}): {fact.claim[:200]}",
                ))

        # Build all_nodes
        all_nodes: list[KnowledgeNode] = []
        for key in ("concepts", "people", "events", "dates", "stats", "places"):
            all_nodes.extend(result.get(key, []))

        result["all_nodes"] = all_nodes
        logger.info("Fallback entity extraction produced %d nodes for '%s'",
                     len(all_nodes), topic)
        return result

    # ── Relationship extraction ─────────────────────────────────────────

    def _extract_relationships(self, topic: str, nodes: list[KnowledgeNode]) -> list[KnowledgeEdge]:
        """Extract relationships between entities via LLM.

        Falls back to a star graph if the LLM call fails.
        """
        entities_json = json.dumps([
            {"id": n.id, "label": n.label, "type": n.type}
            for n in nodes
        ], indent=2)

        prompt = f"""Identify relationships between these entities about "{topic}":

Entities: {entities_json}

Return ONLY a raw JSON object.

Schema:
{{
  "edges": [
    {{"source_id": "c1", "target_id": "c2", "relationship": "contradicts"}},
    {{"source_id": "p1", "target_id": "e1", "relationship": "proposed"}}
  ]
}}

Valid relationships: {", ".join(sorted(VALID_RELATIONSHIPS))}

Rules:
- source_id and target_id must match entity ids from the input.
- Use empty array if no relationships are obvious."""

        try:
            raw = self._llm.generate_json(prompt)
            data = json.loads(raw) if raw else {}
            edges_raw = data.get("edges", [])
            if not isinstance(edges_raw, list):
                raise ValueError("edges is not a list")

            valid_ids = {n.id for n in nodes}
            edges: list[KnowledgeEdge] = []
            for e in edges_raw:
                sid = e.get("source_id", "")
                tid = e.get("target_id", "")
                rel = e.get("relationship", "").lower().strip()
                if sid in valid_ids and tid in valid_ids and rel in VALID_RELATIONSHIPS:
                    edges.append(KnowledgeEdge(
                        source_id=sid, target_id=tid, relationship=rel,
                    ))
            if edges:
                logger.debug("LLM extracted %d relationships for '%s'", len(edges), topic)
                return edges
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("LLM relationship extraction failed for '%s': %s", topic, exc)

        # Fallback: star graph — all nodes connect to the topic node
        logger.info("Using star-graph fallback for '%s'", topic)
        return self._star_graph(topic, nodes)

    def _star_graph(self, topic: str, nodes: list[KnowledgeNode]) -> list[KnowledgeEdge]:
        """Build a star graph: all nodes connected to the topic node."""
        topic_id = self._slug_id(topic, set())
        edges: list[KnowledgeEdge] = []
        for node in nodes:
            if node.id != topic_id:
                edges.append(KnowledgeEdge(
                    source_id=topic_id,
                    target_id=node.id,
                    relationship="supports",
                ))
        return edges

    # ── Caching ─────────────────────────────────────────────────────────

    def _content_hash(self, document: ResearchDocument) -> str:
        """Generate a deterministic cache key from research document content."""
        fact_json = json.dumps([
            {"claim": f.claim, "confidence": f.confidence}
            for f in document.key_facts
        ], sort_keys=True)
        raw = f"{document.topic}|{len(document.sources)}|{fact_json}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_path(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.json"

    def _load_from_cache(self, cache_key: str) -> Optional[KnowledgeGraph]:
        """Return a cached KnowledgeGraph, or None if missing/stale."""
        path = self._cache_path(cache_key)
        if not path.exists():
            return None

        age_seconds = time.time() - path.stat().st_mtime
        max_age = self._cache_ttl_days * 86400
        if age_seconds > max_age:
            logger.info("KnowledgeGraph cache STALE (%.0f hours old)", age_seconds / 3600)
            return None

        try:
            data = json.loads(path.read_text())
            kg = KnowledgeGraph(**data)
            logger.debug("KnowledgeGraph cache HIT (key=%s)", cache_key[:10])
            return kg
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("KnowledgeGraph cache CORRUPT: %s", exc)
            return None

    def _save_to_cache(self, cache_key: str, kg: KnowledgeGraph) -> None:
        """Write a KnowledgeGraph to the JSON cache."""
        path = self._cache_path(cache_key)
        try:
            path.write_text(kg.model_dump_json(indent=2))
            logger.debug("KnowledgeGraph cache written: %s", path)
        except OSError as exc:
            logger.warning("Failed to write KnowledgeGraph cache: %s", exc)

    # ── SQLite persistence ──────────────────────────────────────────────

    def _init_sqlite(self):
        """Initialise the SQLite database schema."""
        try:
            conn = sqlite3.connect(str(self._sqlite_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_graphs (
                    cache_key TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    node_count INTEGER DEFAULT 0,
                    edge_count INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_kg_topic ON knowledge_graphs(topic);
                CREATE TABLE IF NOT EXISTS knowledge_nodes (
                    id TEXT NOT NULL,
                    graph_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    type TEXT NOT NULL,
                    PRIMARY KEY (graph_key, id)
                );
                CREATE INDEX IF NOT EXISTS idx_kn_graph ON knowledge_nodes(graph_key);
                CREATE INDEX IF NOT EXISTS idx_kn_type ON knowledge_nodes(type);
                CREATE TABLE IF NOT EXISTS knowledge_edges (
                    graph_key TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relationship TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ke_graph ON knowledge_edges(graph_key);
            """)
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("SQLite init failed: %s", exc)
        finally:
            conn.close()

    def _store_to_sqlite(self, topic: str, cache_key: str, kg: KnowledgeGraph) -> None:
        """Store a KnowledgeGraph in the SQLite database."""
        try:
            conn = sqlite3.connect(str(self._sqlite_path))
            graph_json = kg.model_dump_json()
            conn.execute(
                """INSERT OR REPLACE INTO knowledge_graphs
                   (cache_key, topic, graph_json, created_at, node_count, edge_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (cache_key, topic, graph_json, time.time(),
                 len(kg.nodes), len(kg.edges)),
            )
            # Nodes
            conn.execute("DELETE FROM knowledge_nodes WHERE graph_key = ?", (cache_key,))
            for node in kg.nodes:
                conn.execute(
                    "INSERT OR IGNORE INTO knowledge_nodes (id, graph_key, label, type) VALUES (?, ?, ?, ?)",
                    (node.id, cache_key, node.label, node.type),
                )
            # Edges
            conn.execute("DELETE FROM knowledge_edges WHERE graph_key = ?", (cache_key,))
            for edge in kg.edges:
                conn.execute(
                    "INSERT OR IGNORE INTO knowledge_edges (graph_key, source_id, target_id, relationship) VALUES (?, ?, ?, ?)",
                    (cache_key, edge.source_id, edge.target_id, edge.relationship),
                )
            conn.commit()
            logger.debug("KnowledgeGraph stored in SQLite: %s", cache_key[:10])
        except sqlite3.Error as exc:
            logger.warning("SQLite store failed: %s", exc)
        finally:
            conn.close()

    def query_by_topic(self, topic: str) -> Optional[KnowledgeGraph]:
        """Retrieve the most recent KnowledgeGraph for a topic from SQLite."""
        try:
            conn = sqlite3.connect(str(self._sqlite_path))
            cursor = conn.execute(
                "SELECT graph_json FROM knowledge_graphs WHERE topic = ? ORDER BY created_at DESC LIMIT 1",
                (topic,),
            )
            row = cursor.fetchone()
            if row:
                data = json.loads(row[0])
                return KnowledgeGraph(**data)
        except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("SQLite query failed for '%s': %s", topic, exc)
        finally:
            conn.close()
        return None

    def list_topics(self) -> list[dict]:
        """List all topics that have knowledge graphs stored."""
        try:
            conn = sqlite3.connect(str(self._sqlite_path))
            cursor = conn.execute(
                "SELECT topic, node_count, edge_count, created_at FROM knowledge_graphs ORDER BY created_at DESC"
            )
            return [
                {"topic": row[0], "nodes": row[1], "edges": row[2], "created_at": row[3]}
                for row in cursor.fetchall()
            ]
        except sqlite3.Error as exc:
            logger.warning("SQLite list_topics failed: %s", exc)
            return []
        finally:
            conn.close()

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _slug_id(label: str, seen: set[str]) -> str:
        """Generate a short unique id from a label."""
        slug = re.sub(r"[^a-zA-Z0-9_]", "_", label.lower().strip())
        slug = re.sub(r"_+", "_", slug)[:30].strip("_")
        if not slug:
            slug = "entity"
        # Add a counter suffix to avoid collisions
        suffix = 0
        candidate = slug
        while candidate in seen:
            suffix += 1
            candidate = f"{slug}_{suffix}"
        return candidate
