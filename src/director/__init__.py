"""
director — Closed-loop Visual Director system.

The Visual Director replaces the pipeline's linear retrieval logic with
a self-correcting, director-driven system.  Each stage can reject,
repair, and regenerate outputs until all quality gates are satisfied.

Components
----------
- VisualStyle           — Global visual identity created before scene generation
- ConceptPlanner        — Concept-driven visual query generation (not keyword rewrites)
- SemanticValidator     — Authoritative semantic relevance gate (threshold >= 0.75)
- AestheticAgent        — Prevents abrupt visual style changes between scenes
- QualityGates          — Hard rejection for low score, reuse, style mismatch
- VisualDirector        — Orchestrates all components in a closed loop
"""
