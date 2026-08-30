"""llm.py — Thin LLM client with an ordered fallback chain (Wave 3).

Chain (2026-08-30: ZAI GLM-5.3-flash first, then Gemini → OpenRouter →
Groq → Mistral — GLM replaces DeepSeek in the head slot; the chain keeps
its length). Every caller must ALSO provide a deterministic offline
fallback — this module raises :class:`LLMError` when every provider fails
so callers can degrade.

Deliberately dependency-light (stdlib urllib): no langchain, no SDKs, so the
v3 pipeline cannot break when a heavyweight dependency moves. Keys come from
the environment (loaded from .env via dotenv); keys are NEVER logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = int(os.environ.get("V3_LLM_TIMEOUT", "90"))
_MAX_RETRIES = 2


class LLMError(RuntimeError):
    """All providers in the chain failed (or none configured)."""


_ENV_LOADED = False


def _ensure_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    try:
        from dotenv import load_dotenv

        project_root = Path(__file__).resolve().parent.parent.parent.parent
        load_dotenv(project_root / ".env", override=True)
    except Exception:  # noqa: BLE001 — env may already be set
        pass


def _post_json(url: str, headers: dict[str, str], payload: dict,
               timeout: int = _TIMEOUT) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"connection error: {exc}") from None
    except json.JSONDecodeError as exc:
        raise LLMError(f"bad JSON response: {exc}") from None


# ── Provider adapters ────────────────────────────────────────────────────────
# Each adapter: (name, enabled?, messages/prompt → text)

def _zai(messages: list[dict], temperature: float, max_tokens: int) -> str:
    _ensure_env()
    key = os.environ.get("ZAI_API_KEY", "")
    if not key:
        raise LLMError("ZAI_API_KEY not set")
    model = os.environ.get("ZAI_MODEL", "glm-5.3-flash")
    base_url = os.environ.get("ZAI_BASE_URL",
                              "https://api.z.ai/api/paas/v4").rstrip("/")
    out = _post_json(
        f"{base_url}/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        # NOTE: no "thinking" field — glm-5.3-flash always thinks and any
        # thinking object is rejected with 400 code 1210.
        {"model": model, "messages": messages,
         "temperature": temperature, "max_tokens": max_tokens},
    )
    # GLM replies carry reasoning_content alongside content; read content.
    return out["choices"][0]["message"]["content"]


def _gemini(messages: list[dict], temperature: float, max_tokens: int) -> str:
    _ensure_env()
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise LLMError("GEMINI_API_KEY not set")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    # Flatten chat messages into one gemini contents list.
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    out = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"Content-Type": "application/json", "x-goog-api-key": key},
        {"contents": contents,
         "generationConfig": {"temperature": temperature,
                              "maxOutputTokens": max_tokens}},
    )
    cands = out.get("candidates") or []
    if not cands:
        raise LLMError("empty candidates")
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise LLMError("empty text")
    return text


def _openrouter(messages: list[dict], temperature: float, max_tokens: int) -> str:
    _ensure_env()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise LLMError("OPENROUTER_API_KEY not set")
    model = os.environ.get("OPENROUTER_MODEL",
                           "meta-llama/llama-3.3-70b-instruct")
    out = _post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": model, "messages": messages,
         "temperature": temperature, "max_tokens": max_tokens},
    )
    return out["choices"][0]["message"]["content"]


def _mistral(messages: list[dict], temperature: float, max_tokens: int) -> str:
    _ensure_env()
    key = os.environ.get("MISTRAL_API_KEY", "")
    if not key:
        raise LLMError("MISTRAL_API_KEY not set")
    model = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
    out = _post_json(
        "https://api.mistral.ai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": model, "messages": messages,
         "temperature": temperature, "max_tokens": max_tokens},
    )
    return out["choices"][0]["message"]["content"]


def _groq(messages: list[dict], temperature: float, max_tokens: int) -> str:
    _ensure_env()
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise LLMError("GROQ_API_KEY not set")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    out = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": model, "messages": messages,
         "temperature": temperature, "max_tokens": max_tokens},
    )
    return out["choices"][0]["message"]["content"]


# Ordered fallback chain (ZAI GLM first, 2026-08-30; Mistral
# added 2026-08-30 when balances ran dry mid-production). GLM-5.3-flash
# replaces DeepSeek in the head slot — chain length preserved.
CHAIN: list[tuple[str, Any]] = [
    ("zai", _zai),
    ("gemini", _gemini),
    ("openrouter", _openrouter),
    ("groq", _groq),
    ("mistral", _mistral),
]


def ask_text(system: str, prompt: str, *, temperature: float = 0.7,
             max_tokens: int = 2000, chain: list[tuple[str, Any]] | None = None,
             last_errors: list[str] | None = None) -> str:
    """Run one completion through the fallback chain. Raises LLMError when
    every configured provider fails. Per-provider errors are appended to
    *last_errors* (when provided) for run diagnostics — never keys."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": prompt}]
    errors = last_errors if last_errors is not None else []
    for name, fn in (chain or CHAIN):
        for attempt in range(_MAX_RETRIES):
            try:
                text = fn(messages, temperature, max_tokens)
                if text and text.strip():
                    return text
                raise LLMError("empty response")
            except LLMError as exc:
                errors.append(f"{name}: {exc}")
                if attempt + 1 < _MAX_RETRIES:
                    continue
    raise LLMError("all LLM providers failed: " + " | ".join(errors[-4:]))


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Best-effort strict-JSON extraction from an LLM reply."""
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Balanced-brace scan for the first JSON object/array.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise LLMError("no parseable JSON in reply")


def ask_json(system: str, prompt: str, *, temperature: float = 0.5,
             max_tokens: int = 3000, chain: list[tuple[str, Any]] | None = None,
             last_errors: list[str] | None = None) -> Any:
    """ask_text + strict JSON parse (one retry with a terse repair nudge)."""
    try:
        return extract_json(
            ask_text(system, prompt, temperature=temperature,
                     max_tokens=max_tokens, chain=chain,
                     last_errors=last_errors))
    except (LLMError, json.JSONDecodeError):
        pass
    # One repair attempt: demand JSON only.
    return extract_json(
        ask_text(
            system,
            prompt + "\n\nIMPORTANT: reply with ONLY the raw JSON document, "
            "no prose, no markdown fences.",
            temperature=0.2, max_tokens=max_tokens, chain=chain,
            last_errors=last_errors))


def llm_available(chain: list[tuple[str, Any]] | None = None) -> bool:
    """Cheap config-only probe: is any provider in the chain configured?
    (No network call — a provider with a key counts as available.)"""
    _ensure_env()
    for _name, fn in (chain or CHAIN):
        try:
            if fn == _zai and os.environ.get("ZAI_API_KEY"):
                return True
            if fn == _gemini and os.environ.get("GEMINI_API_KEY"):
                return True
            if fn == _mistral and os.environ.get("MISTRAL_API_KEY"):
                return True
            if fn == _openrouter and os.environ.get("OPENROUTER_API_KEY"):
                return True
            if fn == _groq and os.environ.get("GROQ_API_KEY"):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False
