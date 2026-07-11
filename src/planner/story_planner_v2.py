"""
story_planner_v2.py — Knowledge-graph-grounded narrative arc builder (Stage 3).

Design principles:
  - The KnowledgeGraph is the source of truth.
  - Every NarrativeBeat must reference KnowledgeGraph node IDs.
  - No beat may introduce entities not present in the KnowledgeGraph.
  - The LLM may choose narrative ordering and storytelling style,
    but not invent new facts.
  - The NarrativeArc must be fully traceable back to the KnowledgeGraph.

Algorithm:
  1. Validate KG — reject beats referencing unknown node IDs.
  2. Select narrative framework (LLM call 1).
  3. Design 5-8 beats + logline/title (LLM call 2).
  4. Validate every beat's knowledge_node_ids against the KG.
  5. Self-critic hook quality (LLM call 3, optional).
  6. Cache result.

Flow::

    planner = StoryPlannerV2(llm=provider)
    arc = planner.build_narrative(kg, duration=480)
    # arc is a NarrativeArc with beats traceable to kg.nodes
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from src.models.v2_types import (
    EmotionalTone,
    KnowledgeGraph,
    NarrativeArc,
    NarrativeBeat,
    NarrativeRole,
)
from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider
from src.utils.config import get_config

logger = logging.getLogger(__name__)

# ── Narrative frameworks ───────────────────────────────────────────────

VALID_FRAMEWORKS = {
    "mystery_reveal",
    "chronological",
    "problem_solution",
    "comparison",
    "listicle",
    "character_driven",
}

_DEFAULT_FRAMEWORK = "mystery_reveal"

# Minimum/maximum beats
_MIN_BEATS = 5
_MAX_BEATS = 8

# Hook self-critic threshold
_HOOK_THRESHOLD = 0.7


class StoryPlannerV2:
    """Knowledge-graph-grounded narrative arc builder.

    Parameters
    ----------
    llm : LLMProvider, optional
        LLM provider for framework selection and beat generation.
        If ``None``, resolves via ``ProviderFactory.get_llm_provider_for_role("planner")``.
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
        self._cache_dir = Path(
            self._config.get(
                "cache_store",
                get_config("narrative.cache.store", "cache/narrative"),
            )
        )
        self._cache_ttl_days = self._config.get(
            "cache_ttl_days",
            get_config("narrative.cache.ttl_days", 14),
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._min_beats = self._config.get("min_beats", _MIN_BEATS)
        self._max_beats = self._config.get("max_beats", _MAX_BEATS)
        self._hook_threshold = self._config.get("hook_threshold", _HOOK_THRESHOLD)

    # ── Public API ───────────────────────────────────────────────────────

    def build_narrative(
        self,
        kg: KnowledgeGraph,
        duration: float = 480.0,
        template: str = "documentary",
    ) -> NarrativeArc:
        """Build a narrative arc from a knowledge graph.

        Parameters
        ----------
        kg : KnowledgeGraph
            Structured knowledge graph from Stage 2.
        duration : float
            Target video duration in seconds (default 480 = 8 min).
        template : str
            Narrative template name from config (default ``"documentary"``).

        Returns
        -------
        NarrativeArc
            A validated arc where every beat's ``knowledge_node_ids``
            references existing nodes in *kg*.
        """
        topic = kg.topic
        if not topic and kg.nodes:
            # Fall back to the first concept node label
            topic = next(
                (n.label for n in kg.nodes if n.type == "concept"),
                kg.nodes[0].label,
            )
        if not topic:
            topic = "unknown topic"

        cache_key = self._cache_key(topic, template, duration)
        cached = self._load_from_cache(cache_key)
        if cached is not None:
            logger.info("NarrativeArc cache HIT for '%s'", topic)
            return self._validate_arc_nodes(cached, kg)

        # 1. Framework selection
        framework = self._select_framework(kg, topic)
        logger.info("Selected framework '%s' for '%s'", framework, topic)

        # 2. Beat generation
        arc = self._generate_arc(kg, topic, framework, duration, template)

        # 3. Validate node IDs
        arc = self._validate_arc_nodes(arc, kg)

        # 4. Cache
        self._save_to_cache(cache_key, arc)

        logger.info(
            "NarrativeArc built for '%s': %d beats, framework=%s",
            topic, len(arc.beats), arc.narrative_framework,
        )
        return arc

    # ── Framework selection ──────────────────────────────────────────────

    def _select_framework(self, kg: KnowledgeGraph, topic: str) -> str:
        """Select the best narrative framework for this knowledge graph."""
        kg_summary = self._kg_summary(kg)
        prompt = f"""You are a documentary story architect. Analyze this knowledge graph and select the best narrative framework.

Topic: "{topic}"
Knowledge Graph: {kg_summary}

Available frameworks:
- mystery_reveal — Best for questions/paradoxes with multiple competing explanations.
- chronological — Best for topics with clear temporal progression (history, biography, evolution).
- problem_solution — Best when a clear problem and resolution exist.
- comparison — Best when two or more distinct perspectives/approaches can be contrasted.
- listicle — Best for enumerable topics (top N, key factors, types).
- character_driven — Best when the topic is centred on one or more compelling individuals.

Return ONLY raw JSON. No markdown. No code fences.

{{
  "framework": "mystery_reveal",
  "reasoning": "Brief explanation of why this framework fits.",
  "expected_tension_curve": "gradual_rise_plateau"
}}"""
        try:
            raw = self._llm.generate_json(prompt)
            data = json.loads(raw) if raw else {}
            fw = str(data.get("framework", "")).strip().lower()
            if fw in VALID_FRAMEWORKS:
                return fw
            logger.warning("Framework '%s' not recognised, defaulting", fw)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Framework selection failed: %s", exc)

        return _DEFAULT_FRAMEWORK

    # ── Arc generation ──────────────────────────────────────────────────

    def _generate_arc(
        self,
        kg: KnowledgeGraph,
        topic: str,
        framework: str,
        duration: float,
        template: str,
    ) -> NarrativeArc:
        """Generate the full narrative arc via a single LLM call."""
        kg_json = self._kg_for_prompt(kg)
        valid_ids = {n.id for n in kg.nodes}
        valid_roles = [r.value for r in NarrativeRole]
        valid_tones = [t.value for t in EmotionalTone]

        prompt = f"""You are a documentary story architect designing a {framework} documentary.

Topic: "{topic}"
Target Duration: {duration}s
Knowledge Graph: {kg_json}

Design a structured narrative arc. Every beat MUST reference at least one knowledge graph node by its "id". Do NOT invent entities not present in the KG.
Use the "knowledge_node_ids" field to list the node IDs this beat references.

Available narrative roles (choose the best fit for each beat's place in the arc):
{valid_roles}

Available emotional tones:
{valid_tones}

Return ONLY raw JSON. No markdown. No code fences.

Schema:
{{
  "title": "Compelling documentary title",
  "subtitle": "Engaging subtitle",
  "logline": "One-sentence hook for the entire video.",
  "beats": [
    {{
      "index": 0,
      "role": "hook",
      "hook_sentence": "Opening sentence that grabs attention.",
      "core_message": "The single idea this beat conveys.",
      "emotional_tone": "wonder",
      "knowledge_node_ids": ["node_id_1", "node_id_2"],
      "target_duration_range": [60, 90],
      "cliffhanger": "Line that makes the viewer want the next beat."
    }}
  ]
}}

Rules:
1. Generate between {self._min_beats} and {self._max_beats} beats.
2. The first beat should be a hook (index 0).
3. The last beat should conclude.
4. Every knowledge_node_ids entry must match a node id in the KG above.
5. Roles should follow a logical narrative arc: hook → context → exploration → climax → conclusion.
6. Emotional tones should vary across beats.
7. Beats must not repeat the same core_message.
8. Estimated total duration should be approximately {duration}s (sum of beat midpoints)."""

        try:
            raw = self._llm.generate_json(prompt)
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Arc generation failed: %s", exc)
            data = {}

        beats = []
        beats_raw = data.get("beats", [])
        if not isinstance(beats_raw, list):
            beats_raw = []

        for b in beats_raw:
            if not isinstance(b, dict):
                continue
            index = int(b.get("index", len(beats)))
            role_str = str(b.get("role", "")).strip().lower()
            if role_str not in valid_roles:
                role_str = "context"
            tone_str = str(b.get("emotional_tone", "")).strip().lower()
            if tone_str not in valid_tones:
                tone_str = "neutral"

            node_ids_raw = b.get("knowledge_node_ids", [])
            if isinstance(node_ids_raw, list):
                node_ids = [str(nid) for nid in node_ids_raw if str(nid) in valid_ids]
            else:
                node_ids = []

            dr = b.get("target_duration_range", [45, 120])
            if isinstance(dr, list) and len(dr) == 2:
                d0, d1 = float(dr[0]), float(dr[1])
            else:
                d0, d1 = 45.0, 120.0

            beats.append(NarrativeBeat(
                index=index,
                role=NarrativeRole(role_str),
                hook_sentence=str(b.get("hook_sentence", "")),
                core_message=str(b.get("core_message", "")),
                emotional_tone=EmotionalTone(tone_str),
                knowledge_node_ids=node_ids,
                target_duration_range=(d0, d1),
                cliffhanger=str(b.get("cliffhanger", "")),
            ))

        if not beats:
            logger.warning("No valid beats generated — using fallback")
            return self._fallback_arc(kg, topic, duration)

        return NarrativeArc(
            topic=topic,
            title=str(data.get("title", topic)),
            subtitle=str(data.get("subtitle", "")),
            logline=str(data.get("logline", "")),
            beats=beats,
            total_target_duration=duration,
            narrative_framework=framework,
        )

    # ── Validation ──────────────────────────────────────────────────────

    def _validate_arc_nodes(self, arc: NarrativeArc, kg: KnowledgeGraph) -> NarrativeArc:
        """Ensure every beat references only valid KG node IDs.

        Strips any node IDs not present in *kg*. If a beat ends up with
        zero node IDs after filtering, injects the topic node as a fallback.
        """
        valid_ids = {n.id for n in kg.nodes}
        topic_id = self._find_topic_node_id(kg, arc.topic)

        cleaned_beats = []
        for beat in arc.beats:
            clean_ids = [nid for nid in beat.knowledge_node_ids if nid in valid_ids]
            if not clean_ids and topic_id:
                clean_ids = [topic_id]
            cleaned_beats.append(beat.model_copy(update={"knowledge_node_ids": clean_ids}))

        return arc.model_copy(update={"beats": cleaned_beats})

    @staticmethod
    def _find_topic_node_id(kg: KnowledgeGraph, topic: str) -> Optional[str]:
        """Find the primary topic node ID in the KG."""
        topic_lower = topic.lower().strip()
        for node in kg.nodes:
            if node.label.lower().strip() == topic_lower:
                return node.id
            if node.type == "concept" and (node.label.lower().startswith(topic_lower[:10])):
                return node.id
        # Fall back to the first concept node
        for node in kg.nodes:
            if node.type == "concept":
                return node.id
        # Fall back to the first node
        if kg.nodes:
            return kg.nodes[0].id
        return None

    # ── Fallback ────────────────────────────────────────────────────────

    def _fallback_arc(self, kg: KnowledgeGraph, topic: str, duration: float) -> NarrativeArc:
        """Generate a deterministic fallback arc when LLM generation fails."""
        role_cycle = [
            NarrativeRole.HOOK,
            NarrativeRole.CONTEXT,
            NarrativeRole.EXPLORATION,
            NarrativeRole.CLIMAX,
            NarrativeRole.RESOLUTION,
            NarrativeRole.CONCLUSION,
        ]
        topic_id = self._find_topic_node_id(kg, topic)
        fallback_ids = [topic_id] if topic_id else []

        # Distribute nodes across beats
        all_node_ids = [n.id for n in kg.nodes if n.id != topic_id]
        beats: list[NarrativeBeat] = []
        per_beat = max(1, len(all_node_ids) // len(role_cycle))

        beat_duration = duration / len(role_cycle)
        for i, role in enumerate(role_cycle):
            ids_this_beat = fallback_ids[:]
            start = i * per_beat
            ids_this_beat.extend(all_node_ids[start:start + per_beat])

            beats.append(NarrativeBeat(
                index=i,
                role=role,
                hook_sentence="",
                core_message=f"Narrative segment illustrating {topic}",
                emotional_tone=EmotionalTone.NEUTRAL,
                knowledge_node_ids=ids_this_beat,
                target_duration_range=(beat_duration * 0.8, beat_duration * 1.2),
                cliffhanger="",
            ))

        return NarrativeArc(
            topic=topic,
            title=f"The Story of {topic}",
            subtitle="",
            logline=f"A structured exploration of {topic}.",
            beats=beats,
            total_target_duration=duration,
            narrative_framework="chronological",
        )

    # ── Caching ─────────────────────────────────────────────────────────

    def _cache_key(self, topic: str, template: str, duration: float) -> str:
        """Generate a deterministic cache key from topic + template + duration."""
        raw = f"{topic.lower().strip()}|{template}|{duration}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_path(self, cache_key: str) -> Path:
        return self._cache_dir / f"{cache_key}.json"

    def _load_from_cache(self, cache_key: str) -> Optional[NarrativeArc]:
        """Return a cached NarrativeArc, or None if missing/stale."""
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        age_seconds = time.time() - path.stat().st_mtime
        max_age = self._cache_ttl_days * 86400
        if age_seconds > max_age:
            logger.info("NarrativeArc cache STALE (%.0f hours old)", age_seconds / 3600)
            return None
        try:
            data = json.loads(path.read_text())
            arc = NarrativeArc(**data)
            logger.debug("NarrativeArc cache HIT (key=%s)", cache_key[:10])
            return arc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("NarrativeArc cache CORRUPT: %s", exc)
            return None

    def _save_to_cache(self, cache_key: str, arc: NarrativeArc) -> None:
        """Write a NarrativeArc to the JSON cache."""
        path = self._cache_path(cache_key)
        try:
            path.write_text(arc.model_dump_json(indent=2))
            logger.debug("NarrativeArc cache written: %s", path)
        except OSError as exc:
            logger.warning("Failed to write NarrativeArc cache: %s", exc)

    # ── KG helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _kg_summary(kg: KnowledgeGraph) -> str:
        """Produce a compact text summary of the KG for an LLM prompt."""
        parts = [f"Topic: {kg.topic}"]
        parts.append(f"Nodes ({len(kg.nodes)}):")
        for n in kg.nodes:
            parts.append(f"  [{n.type}] {n.id}: {n.label} — {n.description[:120]}")
        if kg.edges:
            parts.append(f"Edges ({len(kg.edges)}):")
            for e in kg.edges:
                parts.append(f"  {e.source_id} --[{e.relationship}]--> {e.target_id}")
        return "\n".join(parts)

    @staticmethod
    def _kg_for_prompt(kg: KnowledgeGraph) -> str:
        """Produce a concise JSON representation of the KG for an LLM prompt.

        Only includes id, label, type, and description for each node.
        """
        return json.dumps({
            "topic": kg.topic,
            "nodes": [
                {"id": n.id, "label": n.label, "type": n.type, "description": n.description}
                for n in kg.nodes
            ],
            "edges": [
                {"source_id": e.source_id, "target_id": e.target_id, "relationship": e.relationship}
                for e in kg.edges
            ],
        }, indent=2)
