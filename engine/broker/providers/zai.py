"""zai.py — Z.AI (Zhipu GLM) API broker client.

Reality check (verified live, 2026-08): the Z.AI API
(``https://api.z.ai/api/paas/v4``, OpenAI-compatible chat completions)
exposes **text and vision understanding** via ``glm-5.3-flash`` — it has no
image/video *generation* endpoint. The repo uses it as the primary planning
LLM and as the vision model for frame/thumbnail QA.

Quirk: ``glm-5.3-flash`` ALWAYS engages in thinking — passing any
``thinking`` object returns HTTP 400 code 1210. So we omit the field
entirely. Responses include a ``reasoning_content`` field alongside
``content``; we always read ``content`` and set generous ``max_tokens``
(reasoning tokens count against it).

This provider implements the *vision* kind: image analysis for shot QA plus
health/quota probing. Image generation fails over to the image-capable
providers (NVIDIA NIM, pollinations) registered in the broker — see
docs/architecture/v3_multi_renderer_design.md §6.

The API key is read from ``ZAI_API_KEY`` and NEVER logged.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)

BASE_URL = os.environ.get(
    "ZAI_BASE_URL", "https://api.z.ai/api/paas/v4"
).rstrip("/")
VISION_MODEL = os.environ.get("ZAI_MODEL", "glm-5.3-flash")
_TIMEOUT = 60


class ZaiVisionProvider(MediaProvider):
    """Vision-understanding client over the OpenAI-compatible Z.AI API."""

    id = "zai"
    kind = "vision"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or VISION_MODEL
        self._api_key = api_key if api_key is not None else os.environ.get("ZAI_API_KEY", "")

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id,
            kind=self.kind,
            models=[self.model],
            enabled=bool(self._api_key),
            priority=10,
            notes="Vision analysis (shot QA) via glm-5.3-flash; no generation endpoint on Z.AI API",
        )

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ProviderError("zai: ZAI_API_KEY not set")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None,
                 timeout: int = _TIMEOUT) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Never include the auth header or key in error text.
            raise ProviderError(f"zai: HTTP {exc.code} on {path}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"zai: connection error ({exc.reason})") from None

    @staticmethod
    def _chat_payload(model: str, messages: list[dict[str, Any]],
                      max_tokens: int | None = None) -> dict[str, Any]:
        """Build a chat-completions payload.

        NOTE: the ``thinking`` field is deliberately omitted — glm-5.3-flash
        always thinks and rejects any thinking object with 400 code 1210.
        """
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    @staticmethod
    def _extract_content(resp: dict[str, Any]) -> str:
        """Extract ``content`` from a chat response.

        glm-5.3-flash responses carry a ``reasoning_content`` field alongside
        ``content``; we always take ``content`` (the final answer).
        """
        try:
            content = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("zai: malformed chat response") from None
        if content is None:
            raise ProviderError("zai: empty content in chat response")
        return content

    def health_check(self) -> bool:
        """POST a tiny chat completion — cheap authenticated liveness probe."""
        if not self._api_key:
            return False
        try:
            self._request(
                "POST", "/chat/completions",
                self._chat_payload(self.model, [{"role": "user", "content": "ping"}],
                                   max_tokens=64),
            )
            return True
        except ProviderError:
            return False

    def quota(self) -> dict[str, Any] | None:
        """Z.AI exposes no quota endpoint — reported as unknown."""
        return None

    def chat(self, messages: list[dict[str, Any]], max_tokens: int | None = None,
             **kw: Any) -> str:
        """Plain text chat completion (used for LLM chains)."""
        resp = self._request("POST", "/chat/completions",
                             self._chat_payload(self.model, messages, max_tokens))
        return self._extract_content(resp)

    def analyze_image(self, image: str | Path, prompt: str,
                      **kw: Any) -> dict[str, Any]:
        """Vision QA: ask the multimodal model about an image.

        Returns the raw response content dict: {"content": str, "model": ...}.
        """
        p = Path(image)
        if not p.exists():
            raise ProviderError(f"zai: image not found: {p}")
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        # Generous max_tokens: glm-5.3-flash reasoning tokens count.
        resp = self._request("POST", "/chat/completions",
                             self._chat_payload(self.model, messages, max_tokens=4096))
        return {"content": self._extract_content(resp),
                "model": resp.get("model", self.model),
                "usage": resp.get("usage", {})}

    # BrokerResult-returning alias so the broker can route vision QA
    # through the same generate_* plumbing.
    def analyze_image_result(self, image: str | Path, prompt: str,
                             cache_key: str | None = None) -> BrokerResult:
        from engine.broker.cache import BrokerCache

        cache = BrokerCache()
        if cache_key:
            hit = cache.get(cache_key, ext="json")
            if hit:
                return BrokerResult(path=hit, provider=self.id, kind="vision",
                                    cached=True)
        result = self.analyze_image(image, prompt)
        key = cache_key or f"vision-{int(result.get('usage', {}).get('total_tokens', 0))}"
        path = cache.store_bytes(key, json.dumps(result).encode("utf-8"), ext="json")
        return BrokerResult(path=path, provider=self.id, kind="vision", cached=False)

    # Generation ops explicitly unsupported (broker fails over).
    def generate_image(self, prompt: str, **kw: Any) -> BrokerResult:
        raise ProviderError(
            "zai: no image-generation endpoint; fail over to nvidia_nim/pollinations"
        )
