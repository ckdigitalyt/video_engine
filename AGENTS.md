# AGENTS.md — video_engine

Operating rules for the Jade Studio documentary pipeline (mission_run.py /
mission_stills.py and all of `src/`). These are binding engineering
constraints, not suggestions.

## Dead code vs. load-bearing fallbacks

- Do not preserve backward compatibility for dead code. Remove unused
  functions, flags, and migration shims once nothing calls them.
- EXCEPTION: fallback and retry chains that exist to handle unreliable
  external services are NOT "obsolete paths" — they are load-bearing
  reliability design. This includes (but is not limited to):
  - the Gemini model fallback chain (video review)
  - the image-generation provider fallback (NIM Flux → Pollinations → others)
  - the TTS pipeline fallbacks (Chatterbox → Edge → Kokoro)
  - any auto-detection/auto-replacement logic (e.g. silent-audio detection,
    dead-bed replacement, manim source resolution)
- Never remove or weaken a fallback/retry path without flagging it to S
  first and getting explicit confirmation — even if it looks unused or
  redundant from a code-reading pass alone.
- Any change that deletes, disables, or narrows a fallback chain, retry
  path, or error-recovery branch requires explicit approval from S before
  merging — describe what's being removed and why in the commit/PR
  description, and wait for confirmation.

## Simplicity and layering

- Choose the simplest implementation that fully meets the current
  requirements. Avoid speculative abstractions, configuration, and
  indirection that isn't already justified by an existing need.
- Grow the system in layers. Start from the smallest version that works
  end to end, and add each new capability on top of a pipeline stage that
  already works. Never trade a working run for unfinished complexity —
  mission_run.py must stay runnable end-to-end at every commit.
- Make architectural decisions for the long term, but do not use this as
  license for speculative abstraction — "long term" means "won't need to
  be redone for a known near-future requirement," not "handles
  hypothetical future requirements."

## Modularity

- Keep pipeline stages modular and concerns clearly separated
  (research / script / narration / render / review / postmortem).
- Prefer established, well-maintained libraries when they reduce overall
  complexity or improve reliability (as already done with MoviePy, FFmpeg,
  Manim, Kokoro). Do not reimplement functionality those libraries already
  provide without a clear, stated reason.
- Lean on dependencies already in the project before writing new
  implementations or adding packages. Do not assume a library lacks a
  capability without checking its documentation and types first.
