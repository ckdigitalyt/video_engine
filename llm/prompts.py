"""Prompt templates (DESIGN §2.5): llm/prompts/<stage>.md, ``{{var}}`` substitution.

The first line of each file is ``<!-- prompt_version: N -->``; the version goes into
the adapter's cache key (``ask(prompt_version=...)``) and into every artifact.
"""
from __future__ import annotations

import re
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_VERSION = re.compile(r"\A<!--\s*prompt_version:\s*(\S+)\s*-->\n")
_VAR = re.compile(r"\{\{(\w+)\}\}")


def render(stage: str, **vars: str) -> tuple[str, str]:
    """-> (prompt, prompt_version). Every {{var}} must be supplied; extras are an error."""
    raw = (PROMPT_DIR / f"{stage}.md").read_text()
    m = _VERSION.match(raw)
    if not m:
        raise ValueError(f"prompt {stage}: missing prompt_version header")
    body = raw[m.end():]
    need = set(_VAR.findall(body))
    if need != set(vars):
        raise ValueError(f"prompt {stage}: needs {sorted(need)}, got {sorted(vars)}")
    return _VAR.sub(lambda k: str(vars[k.group(1)]), body).strip() + "\n", m.group(1)
