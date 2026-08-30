"""engine.v3 — Jade v3 pipeline brain (Wave 3).

Layered production pipeline per docs/directives/v3_master_brief_2026-08-30.md §3:

    story   → research intake, narrative structure, scriptwriter
    plan    → shot planner (visual director LLM + router + budget + variety)
    render  → per-shot render orchestration through the renderer registry
    qa      → shot QA (technical + vision), full-video QA, publish gate
    repair  → selective regeneration loop with versioned outputs
    assemble→ concat + narration TTS + music bed + loudness master

Every LLM call has a deterministic offline fallback (§24): the pipeline must
not collapse without network.
"""
