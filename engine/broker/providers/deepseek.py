"""deepseek.py — DeepSeek API broker client.

Reality check (verified against how src/ uses this key): the DeepSeek API
(``api.deepseek.com``, OpenAI-compatible) exposes **text and vision
understanding** — it has no image/video *generation* endpoint. The repo
already uses it as the planning LLM (``src/providers/llm_provider.py``) and,
since 2026-08, as the vision model (``deepseek-v4-flash-vision-exp``) for
frame/thumbnail QA.

This provider therefore implements the *vision* kind: image analysis for
shot QA plus health/quota probing. Image generation fails over to the
image-capable providers (SiliconFlow FLUX, NVIDIA NIM) registered in the
broker — see docs/architecture/v3_multi_renderer_design.md §6.

The API key is read from ``DEEPSEEK_API_KEY`` and NEVER logged.
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

BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
VISION_MODEL = "deepseek-v4-flash-vision-exp"
_TIMEOUT = 60


class DeepSeekVisionProvider(MediaProvider):
    """Vision-understanding client over the OpenAI-compatible DeepSeek API."""

    id = "deepseek"
    kind = "vision"

    def __init__(self, model: str = VISION_MODEL, api_key: str | None = None) -> None:
        self.model = model
        self._api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id,
            kind=self.kind,
            models=[self.model],
            enabled=bool(self._api_key),
            priority=10,
            notes="Vision analysis (shot QA); no generation endpoint exists on DeepSeek API",
        )

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ProviderError("deepseek: DEEPSEEK_API_KEY not set")
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
            raise ProviderError(f"deepseek: HTTP {exc.code} on {path}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"deepseek: connection error ({exc.reason})") from None

    def health_check(self) -> bool:
        """GET /models — cheap authenticated liveness probe."""
        if not self._api_key:
            return False
        try:
            self._request("GET", "/models")
            return True
        except ProviderError:
            return False

    def quota(self) -> dict[str, Any] | None:
        """DeepSeek exposes no quota endpoint — reported as unknown."""
        return None

    def analyze_image(self, image: str | Path, prompt: str,
                      **kw: Any) -> dict[str, Any]:
        """Vision QA: ask the multimodal model about an image.

        Returns the raw response content dict: {"content": str, "model": ...}.
        """
        p = Path(image)
        if not p.exists():
            raise ProviderError(f"deepseek: image not found: {p}")
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        resp = self._request("POST", "/chat/completions", payload)
        try:
            content = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("deepseek: malformed chat response") from None
        return {"content": content, "model": resp.get("model", self.model),
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
            "deepseek: no image-generation endpoint; fail over to siliconflow/nvidia_nim"
        )
