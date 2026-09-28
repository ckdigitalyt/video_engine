"""OpenRouter provider (GLM 5.3 Flash, ported from engine/director.py; disabled in configs/llm.yaml)."""
from __future__ import annotations

import base64
import json
import urllib.request
from urllib.error import HTTPError

from llm.env import env_key
from llm.types import RawRequest, RawResponse

URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouter:
    def __init__(self, spec: dict):
        self.key_env = spec.get("key_env", "OPENROUTER_API_KEY")

    def complete(self, req: RawRequest) -> RawResponse:
        key = env_key(self.key_env)
        if not key:
            return RawResponse(error_kind="auth", error=f"{self.key_env} is not set")
        content: list | str = req.prompt
        if req.images:
            content = [{"type": "text", "text": req.prompt}] + [
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(open(i, "rb").read()).decode()}}
                for i in req.images]
        body = {"model": req.model, "temperature": req.temperature if req.temperature is not None else 0,
                "max_tokens": max(512, req.max_tokens or 2000),
                # GLM-5.3-flash is a reasoning model: with no budget it can spend all max_tokens
                # on hidden reasoning and return empty content (V15)
                "reasoning": {"effort": "low"},
                "messages": [{"role": "user", "content": content}]}
        if req.schema:
            body["response_format"] = {"type": "json_object"}
        http = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(http, timeout=req.timeout_s) as r:
                data = json.loads(r.read())
            text = (data["choices"][0]["message"].get("content") or "").strip()
            return RawResponse(text=text, usage=data.get("usage") or {})
        except HTTPError as e:
            kind = "quota" if e.code == 429 else "auth" if e.code in (401, 403) else "transport"
            return RawResponse(error_kind=kind, error=f"HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            return RawResponse(error_kind="transport", error=type(e).__name__)
