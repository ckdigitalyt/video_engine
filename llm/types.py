"""Shared types for the LLM adapter (DESIGN §2.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class LLMResult:
    data: dict | None          # parsed + schema-validated JSON (None for schema=None calls)
    text: str
    stage: str
    provider: str
    model: str
    attempts: int
    latency_s: float
    cached: bool
    usage: dict = field(default_factory=dict)


class LLMUnavailable(Exception):
    """Every configured provider for this stage is in quota/auth/outage state."""

    def __init__(self, message: str, kind: str, retry_at: datetime | None = None):
        super().__init__(message)
        self.kind = kind            # "quota" | "auth" | "outage"
        self.retry_at = retry_at


class LLMSchemaError(Exception):
    """Output still invalid after the repair round on every provider."""


@dataclass
class RawRequest:
    system: str
    prompt: str
    images: list[Path]
    schema: dict | None
    model: str
    effort: str
    timeout_s: float
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class RawResponse:
    text: str = ""
    data: dict | None = None    # provider-native structured payload, when it has one
    usage: dict = field(default_factory=dict)
    error_kind: str | None = None   # None | "transport" | "quota" | "auth"
    error: str = ""
    retry_at: datetime | None = None
