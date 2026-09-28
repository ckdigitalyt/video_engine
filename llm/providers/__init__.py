"""Provider registry: each provider implements ``complete(req) -> RawResponse``."""
from __future__ import annotations


def make_provider(name: str, spec: dict):
    t = spec["type"]
    if t == "claude_cli":
        from llm.providers.claude_cli import ClaudeCLI
        return ClaudeCLI(spec)
    if t == "gemini":
        from llm.providers.gemini import Gemini
        return Gemini(spec)
    if t == "openrouter":
        from llm.providers.openrouter import OpenRouter
        return OpenRouter(spec)
    raise ValueError(f"unknown provider type {t!r} for {name!r}")
