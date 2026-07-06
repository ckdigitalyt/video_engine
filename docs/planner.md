# Planner Module

The **Creative Planner** is the first node in the video_engine pipeline. It
generates a structured, multi-scene script from a topic string using a
large language model (DeepSeek by default).

---

## Planning Strategy

The planner follows a **director-agent** pattern: it receives a topic and
produces a complete storyboard covering the introduction, body, and
conclusion.  No iterative refinement is performed at this stage — that's
handled by the critic loop.

The prompt instructs the LLM to:

1. **Scope the topic** — determine depth, complexity, and number of scenes.
2. **Generate 8–15 scenes** depending on topic length and richness.
3. **Assign unique search queries** for visual asset retrieval.
4. **Write narration** that fits within `estimated_duration` at ~3 words/second.
5. **Enforce logical progression** — open with a hook, develop the
   argument, conclude decisively.
6. **Avoid duplicates** — no repeated scenes, titles, queries, or
   narration.

---

## Scene Ordering

Scenes are ordered by `scene_id` (1-indexed).  The planner is given a
single constraint: the sequence must feel natural from start to finish.
No reordering is performed downstream — the Timeline Builder consumes
scenes sorted by `scene_id`.

A typical arc:

| Position | Purpose                   |
|----------|---------------------------|
| 1–2      | Hook / establish stakes   |
| 3–10     | Develop the argument      |
| 11–15    | Conclusion / call to action |

---

## Duration Estimation

Each scene carries an `estimated_duration` field (seconds).  The planner
calculates this based on narration word count (~3 words/second).  The
actual timeline duration is determined later by measuring the generated
audio file with pydub, so `estimated_duration` is an approximate guide for
the planner, not a hard constraint.

---

## Search-Query Generation

Each scene receives a unique `search_query` for the Pexels video search API.
The planner is instructed to:

- Vary queries so that the same footage is not returned for different
  scenes.
- Use descriptive, visually-rich terms (e.g. `"Fermi Paradox illustration
  aliens"` rather than `"space"`).
- Avoid queries that could return unrelated or low-quality results.

The PexelsProvider caches results by `(provider, search_query)` in the
AssetCache, so re-running the same plan on the same topic reuses assets.

---

## Output Format

The planner returns a JSON object matching this schema:

```json
{
  "scenes": [
    {
      "scene_id": 1,
      "title": "The Vast Cosmos",
      "search_query": "deep space milky way galaxy",
      "narration": "The universe is unimaginably vast...",
      "estimated_duration": 10
    }
  ]
}
```

This is stored as `plan_json` in the AgentState and consumed by the
execution node.

---

## Validation

The planner output is **not explicitly validated** beyond what the LLM
produces.  Downstream validation occurs in the:

- **Timeline Builder** — checks file existence, monotonic timestamps,
  no overlapping clips, matching audio/video durations.
- **Critic** — validates the rendered video frame-by-frame and can reject
  and re-trigger the planner.

---

## Future Research-Agent Integration

Future iterations may replace the single LLM call with a **research-agent
pattern**:

1. **Research agent** gathers facts, quotes, and references about the
   topic using web search.
2. **Planner** receives the research summary and produces a richer,
   factually-grounded script.
3. **Fact-checker** validates claims before rendering.

This would require no changes to the execution, renderer, or critic nodes —
the planner's output schema is the only interface contract.
