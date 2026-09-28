"""Gemini provider (ported from engine/director.py; disabled in configs/llm.yaml)."""
from __future__ import annotations

import base64
import json
import urllib.request
from urllib.error import HTTPError

from llm.env import env_key
from llm.types import RawRequest, RawResponse


class Gemini:
    def __init__(self, spec: dict):
        self.key_env = spec.get("key_env", "GEMINI_API_KEY")

    def complete(self, req: RawRequest) -> RawResponse:
        key = env_key(self.key_env)
        if not key:
            return RawResponse(error_kind="auth", error=f"{self.key_env} is not set")
        parts = [{"text": req.prompt}]
        for img in req.images:
            parts.append({"inline_data": {"mime_type": "image/png",
                                          "data": base64.b64encode(open(img, "rb").read()).decode()}})
        gen = {"temperature": req.temperature if req.temperature is not None else 0,
               "maxOutputTokens": max(1024, (req.max_tokens or 2000) * 3),
               # 2.5-flash is a thinking model: without a budget the answer arrives empty
               "thinkingConfig": {"thinkingBudget": 0}}
        if req.schema:
            gen["responseMimeType"] = "application/json"
        body = {"contents": [{"parts": parts}], "generationConfig": gen}
        http = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{req.model}:generateContent",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": key})  # header, not URL: errors never echo it
        try:
            with urllib.request.urlopen(http, timeout=req.timeout_s) as r:
                data = json.loads(r.read())
            text = " ".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
            return RawResponse(text=text, usage=data.get("usageMetadata") or {})
        except HTTPError as e:
            kind = "quota" if e.code == 429 else "auth" if e.code in (401, 403) else "transport"
            return RawResponse(error_kind=kind, error=f"HTTP {e.code}")
        except Exception as e:  # noqa: BLE001 - message only, never the request
            return RawResponse(error_kind="transport", error=type(e).__name__)
