"""
v2_pipeline.py — V2 orchestration pipeline (LangGraph).

Wires the three existing V2 stages into a LangGraph workflow:

    research → knowledge → narrative → END

Each node receives its stage component via dependency injection
to keep the orchestration layer thin — no business logic here.

Usage::

    python -m src.orchestration.v2_pipeline --topic "The Fermi Paradox"
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from langgraph.graph import END, StateGraph

from src.models.v2_types import (
    KnowledgeGraph,
    NarrativeArc,
    PipelineStateV2,
    ResearchDocument,
)
from src.providers.factory import ProviderFactory
from src.research.knowledge_graph import KnowledgeGraphBuilder
from src.research.research_agent import ResearchAgent
from src.planner.story_planner_v2 import StoryPlannerV2

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════ #
# Node factories (dependency injection)
# ═══════════════════════════════════════════════════════════════════════ #


def _research_node(
    state: PipelineStateV2,
    *,
    research_agent: ResearchAgent,
) -> dict:
    """Stage 1: Research → ResearchDocument."""
    start = time.monotonic()
    logger.info("V2 pipeline: Stage 1 — Research for '%s'", state.topic)
    doc = research_agent.research(state.topic)
    elapsed = time.monotonic() - start
    logger.info("Stage 1 complete: %d facts, %d sources (%.1fs)",
                len(doc.key_facts), len(doc.sources), elapsed)
    elapsed_dict = dict(state.stages_elapsed or {})
    elapsed_dict["research"] = elapsed
    return {
        "research_document": doc,
        "status": "researching",
        "stages_elapsed": elapsed_dict,
    }


def _knowledge_node(
    state: PipelineStateV2,
    *,
    kg_builder: KnowledgeGraphBuilder,
) -> dict:
    """Stage 2: ResearchDocument → KnowledgeGraph."""
    if state.research_document is None:
        raise ValueError("research_document is required before knowledge stage")
    start = time.monotonic()
    logger.info("V2 pipeline: Stage 2 — Knowledge Graph for '%s'", state.topic)
    kg = kg_builder.build(state.research_document)
    elapsed = time.monotonic() - start
    logger.info("Stage 2 complete: %d nodes, %d edges (%.1fs)",
                len(kg.nodes), len(kg.edges), elapsed)
    elapsed_dict = dict(state.stages_elapsed or {})
    elapsed_dict["knowledge"] = elapsed
    return {
        "knowledge_graph": kg,
        "status": "kged",
        "stages_elapsed": elapsed_dict,
    }


def _narrative_node(
    state: PipelineStateV2,
    *,
    story_planner: StoryPlannerV2,
) -> dict:
    """Stage 3: KnowledgeGraph → NarrativeArc."""
    if state.knowledge_graph is None:
        raise ValueError("knowledge_graph is required before narrative stage")
    start = time.monotonic()
    logger.info("V2 pipeline: Stage 3 — Narrative arc for '%s'", state.topic)
    arc = story_planner.build_narrative(state.knowledge_graph)
    elapsed = time.monotonic() - start
    logger.info("Stage 3 complete: %d beats, framework=%s (%.1fs)",
                len(arc.beats), arc.narrative_framework, elapsed)
    elapsed_dict = dict(state.stages_elapsed or {})
    elapsed_dict["narrative"] = elapsed
    return {
        "narrative_arc": arc,
        "status": "narratived",
        "stages_elapsed": elapsed_dict,
    }


# ═══════════════════════════════════════════════════════════════════════ #
# Graph construction
# ═══════════════════════════════════════════════════════════════════════ #


def build_v2_pipeline(
    *,
    research_agent: Optional[ResearchAgent] = None,
    kg_builder: Optional[KnowledgeGraphBuilder] = None,
    story_planner: Optional[StoryPlannerV2] = None,
) -> StateGraph:
    """Build the V2 LangGraph pipeline with injected stage components.

    Parameters
    ----------
    research_agent : ResearchAgent, optional
        Defaults to ``ResearchAgent()``.
    kg_builder : KnowledgeGraphBuilder, optional
        Defaults to ``KnowledgeGraphBuilder()``.
    story_planner : StoryPlannerV2, optional
        Defaults to ``StoryPlannerV2()``.

    Returns
    -------
    StateGraph
        A compiled LangGraph ready to invoke.
    """
    ra = research_agent or ResearchAgent()
    kb = kg_builder or KnowledgeGraphBuilder()
    sp = story_planner or StoryPlannerV2()

    def research(state: PipelineStateV2) -> dict:
        return _research_node(state, research_agent=ra)

    def knowledge(state: PipelineStateV2) -> dict:
        return _knowledge_node(state, kg_builder=kb)

    def narrative(state: PipelineStateV2) -> dict:
        return _narrative_node(state, story_planner=sp)

    workflow = StateGraph(PipelineStateV2)
    workflow.add_node("research", research)
    workflow.add_node("knowledge", knowledge)
    workflow.add_node("narrative", narrative)

    workflow.set_entry_point("research")
    workflow.add_edge("research", "knowledge")
    workflow.add_edge("knowledge", "narrative")
    workflow.add_edge("narrative", END)

    return workflow.compile()


# ═══════════════════════════════════════════════════════════════════════ #
# Entry point
# ═══════════════════════════════════════════════════════════════════════ #


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 video pipeline (research → KG → narrative)")
    parser.add_argument("--topic", default="The Fermi Paradox", help="Video topic")
    parser.add_argument("--output", "-o", default=None,
                        help="Output path for the narrative arc JSON")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("V2 pipeline starting — topic: '%s'", args.topic)
    app = build_v2_pipeline()

    initial_state = PipelineStateV2(
        topic=args.topic,
        status="initialized",
        started_at=time.time(),
    )

    final_state = app.invoke(initial_state)

    logger.info("V2 pipeline complete — status: '%s'", final_state["status"])
    logger.info("  Stages elapsed: %s", final_state.get("stages_elapsed", {}))
    logger.info("  Research facts: %d", len(final_state.get("research_document", ResearchDocument(topic="")).key_facts) if final_state.get("research_document") else 0)
    logger.info("  KG nodes: %d", len(final_state.get("knowledge_graph", KnowledgeGraph(topic="")).nodes) if final_state.get("knowledge_graph") else 0)
    logger.info("  Narrative beats: %d", len(final_state.get("narrative_arc", NarrativeArc(topic="")).beats) if final_state.get("narrative_arc") else 0)

    # Optionally write the NarrativeArc to a file
    if args.output:
        arc = final_state.get("narrative_arc")
        if arc:
            Path(args.output).write_text(arc.model_dump_json(indent=2))
            logger.info("NarrativeArc written to %s", args.output)


if __name__ == "__main__":
    main()
