# Story Planning Engine

## Overview

The Story Planning Engine upgrades video planning from independent scene
generation to **structured storytelling**.

Instead of asking the LLM to produce scenes directly, the engine works in
**two phases**:

1. **Outline Generation** — Creates a narrative arc aligned to a story template.
2. **Scene Expansion** — Produces rich, continuity-aware scene descriptions
   from the outline.

This produces videos with a clear **beginning, middle, and ending**, better
pacing, reduced repetition, and search queries optimised for stock footage.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    StoryPlanner                      │
│  ┌─────────────┐          ┌──────────────────────┐  │
│  │ Phase 1     │  outline  │  Phase 2             │  │
│  │ Outline     │──────────▶│  Scene Generation    │──┼──▶ plan_json
│  │ Generation  │  JSON     │  (from outline)      │  │
│  └─────────────┘          └──────────────────────┘  │
│         │                           ▲                │
│         │ uses                      │ uses           │
│         ▼                           │                │
│  ┌─────────────┐                    │                │
│  │  StoryTemplate / LLMProvider     │                │
│  └─────────────┘────────────────────┘                │
└─────────────────────────────────────────────────────┘
```

### Provider Independence

The `StoryPlanner` depends only on the `LLMProvider` interface (not
ZAI GLM or Gemini directly). Any provider implementing `generate_json()`
works.

---

## Story Templates

Templates define the **narrative role of each scene** in the video.

### Built-in templates

| Template | Roles | Use case |
|----------|-------|----------|
| `documentary` | Hook → Context → Exploration → Climax → Conclusion | General documentaries |
| `problem_resolution` | Problem → Investigation → Resolution | Explainer / problem-solution content |
| `timeline` | Opening → Event 1 → Event 2 → Event 3 → Closing | Historical / chronological stories |
| `listicle` | Intro → Point 1 → Point 2 → Point 3 → Outro | Top-N, list-based content |

### Custom templates

Add new templates in `configs/planner.yaml`:

```yaml
planner:
  story_templates:
    my_custom_template:
      roles:
        - "Teaser — A hook that hints at the conclusion"
        - "Backstory — The context needed to understand"
        - "Reveal — The key insight or discovery"
        - "Impact — What this means going forward"
      description: "Custom template with a teaser → reveal structure."
```

---

## Configuration

All planning behaviour is governed by `configs/planner.yaml`:

```yaml
planner:
  story_template: "documentary"        # Active template
  target_scene_count: 10               # Minimum scenes (may expand to 15)
  target_duration: 120                 # Target video length (seconds)
  words_per_second: 3                  # Narration pace
  narration_style: "informative but conversational"
  search_query_style: "descriptive, landscape stock footage terms"
```

---

## Outline Generation (Phase 1)

The outline prompt instructs the LLM to produce a **narrative framework**
before any scene details. Each outline item specifies:

- **Role** — The narrative purpose (e.g. "Hook", "Climax")
- **Purpose** — What this scene uniquely contributes
- **Continuity** — How it connects to surrounding scenes
- **Visual Style** — Type of stock footage suitable

### Example output

```json
{
  "narrative_arc": "Explores the vastness of space and the silence of the cosmos.",
  "scenes": [
    {
      "role": "Hook",
      "purpose": "Grab viewer attention with a startling fact about cosmic silence.",
      "continuity": "Opens the video — no prior context needed.",
      "visual_style": "Deep space wide shot with stars and galaxies"
    },
    {
      "role": "Context",
      "purpose": "Explain the Drake Equation and why we expect alien life.",
      "continuity": "Builds on the hook by giving scientific background.",
      "visual_style": "Animated equation overlay with celestial background"
    }
  ]
}
```

---

## Scene Generation (Phase 2)

The scene prompt includes:

- The full narrative outline as context
- The topic and target parameters
- Narration style and search query style instructions
- The exact schema required

Scenes produced by Phase 2 follow the same schema as before, so the
execution node in `orchestrator.py` works unchanged.

---

## Orchestrator Integration

The orchestrator's `planner_node` now uses `StoryPlanner` instead of a
raw prompt:

```python
def planner_node(state: AgentState):
    iteration = state.get("iteration", 0) + 1
    planner = StoryPlanner(provider=zai)
    content = planner.generate_plan(state["topic"])
    return {"plan_json": content, "iteration": iteration}
```

No other nodes (execution, render, critic) needed changes.

---

## Testing

| Area | What it verifies |
|------|-----------------|
| **Templates** | All built-in templates loaded, correct role counts, fallback for unknown |
| **Outline** | JSON structure, topic in prompt, template roles in prompt, target scene count |
| **Scene phase** | Outline context passed, narration style, output structure |
| **Full pipeline** | Both phases called, returns valid JSON, works with all templates |
| **Config** | All planner keys present in YAML, proper default values |
| **Edge cases** | Empty topic, zero target, no-scene outline, long duration |

---

## Extension Points

### New story templates
Add entries to `configs/planner.yaml` under `planner.story_templates`.

### Custom narration styles
Change `planner.narration_style` in YAML — will be injected into prompts.

### Search query optimisation
Modify `planner.search_query_style` to tune stock footage results.

### Embedding-based outline selection (future)
The template system is config-driven and can support dynamic template
selection via cosine similarity between topic embeddings and template
descriptions without changing the public API.
