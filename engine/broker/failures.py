"""failures.py — Precise failure taxonomy for AI-video providers (directive §7/§8).

Every failed generation attempt is classified into a coarse but *actionable*
category so the ZeroGPU scheduler can decide whether to:

* try the SAME space again            → TRANSIENT_NETWORK
* try a DIFFERENT space               → QUEUE_TIMEOUT, SPACE_ERROR, INVALID_PARAMS
* stop burning attempts account-wide  → QUOTA_EXHAUSTED (ZeroGPU quota is
  account-level: once exhausted, *every* Space will refuse — retrying other
  Spaces only wastes wall-clock and risk-exposes the session)
* fix the calling code, not retry     → INVALID_PARAMS
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class FailureClass(str, Enum):
    QUEUE_TIMEOUT = "QUEUE_TIMEOUT"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    SPACE_ERROR = "SPACE_ERROR"
    INVALID_PARAMS = "INVALID_PARAMS"
    AUTH_ERROR = "AUTH_ERROR"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    UNKNOWN = "UNKNOWN"


# Account-level ZeroGPU quota messages. Examples observed in the wild:
#   "You have exceeded your GPU quota (60s requested vs. 44s left). Try again in 1:23:45"
#   "You have exceeded your GPU quota" / "ZeroGPU quota exceeded"
#   "Too many users have used or used up their quota..."
_QUOTA_PATTERNS = (
    "exceeded your gpu quota",
    "gpu quota exceeded",
    "zerogpu quota",
    "out of quota",
    "insufficient quota",
    "used up their quota",
    "quota exhausted",
    "depleted your monthly included credits",
    "depleted",
)

# Queue/wait failures — another Space (or later) may succeed.
_QUEUE_PATTERNS = (
    "poll timeout",
    "queue may still be running",
    "queue is full",
    "queue timeout",
    "too many users are trying",
    "currently waiting in queue",
)

# Bad request shape — retrying the same payload can never work.
_INVALID_PATTERNS = (
    "http 422",
    "http 400",
    "validation",
    "invalid parameter",
    "missing required",
    "schema violation",
    "unexpected value",
)

_TRANSIENT_PATTERNS = (
    "connection error",
    "timed out",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "temporarily",
)

_AUTH_PATTERNS = (
    "auth failed",
    "http 401",
    "http 403",
    "invalid token",
)

# "space error: null" — Gradio SSE error event with a null payload. Observed
# account-wide during the dino_v1 quota exhaustion (Space was RUNNING but
# every call died with a null error), so it is quota-suspicious but not proof.
_NULL_ERROR_SIGNATURE = "space error: null"


def classify_failure(message: str) -> FailureClass:
    """Classify a provider error message into the §7 taxonomy."""
    if not message:
        return FailureClass.UNKNOWN
    low = message.lower()
    if _NULL_ERROR_SIGNATURE in low:
        return FailureClass.SPACE_ERROR
    if any(p in low for p in _QUOTA_PATTERNS):
        return FailureClass.QUOTA_EXHAUSTED
    if any(p in low for p in _QUEUE_PATTERNS):
        return FailureClass.QUEUE_TIMEOUT
    if any(p in low for p in _INVALID_PATTERNS):
        return FailureClass.INVALID_PARAMS
    if any(p in low for p in _AUTH_PATTERNS):
        return FailureClass.AUTH_ERROR
    if any(p in low for p in _TRANSIENT_PATTERNS):
        return FailureClass.TRANSIENT_NETWORK
    if "space error" in low:
        return FailureClass.SPACE_ERROR
    return FailureClass.UNKNOWN


# "You have exceeded your GPU quota (60s requested vs. 44s left). Try again in 1:23:45"
_REMAINING_RE = re.compile(r"vs\.?\s*([0-9.]+)\s*s(?:ec|econds?)?\s*left", re.IGNORECASE)
_RETRY_IN_RE = re.compile(r"try again in\s*([0-9:]+)", re.IGNORECASE)


def parse_quota_remaining(message: str) -> dict[str, float | None]:
    """Best-effort extraction of remaining quota info from a quota error.

    Returns {"gpu_sec_left": float|None, "retry_in_sec": float|None}.
    """
    out: dict[str, float | None] = {"gpu_sec_left": None, "retry_in_sec": None}
    m = _REMAINING_RE.search(message or "")
    if m:
        out["gpu_sec_left"] = float(m.group(1))
    m = _RETRY_IN_RE.search(message or "")
    if m:
        parts = [int(p) for p in m.group(1).split(":")]
        secs = 0.0
        for p in parts:
            secs = secs * 60 + p
        out["retry_in_sec"] = secs
    return out


@dataclass
class SpaceAttempt:
    """Per-attempt record (directive §7 requires these exact fields)."""

    attempted_provider: str
    space_id: str
    success: bool = False
    failure_reason: str = ""
    fallback_reason: str = ""
    classification: str = ""
    elapsed_sec: float = 0.0
    output_path: str = ""
    output_kind: str = ""  # t2v | i2v
    detail: dict = field(default_factory=dict)

    def to_record(self) -> dict:
        return {
            "attempted_provider": self.attempted_provider,
            "space_id": self.space_id,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "fallback_reason": self.fallback_reason,
            "classification": self.classification,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "output_path": self.output_path,
            "output_kind": self.output_kind,
            **({"detail": self.detail} if self.detail else {}),
        }
