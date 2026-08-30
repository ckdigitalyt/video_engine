"""test_zai_provider.py — ZAI GLM broker provider (mocked HTTP, offline).

Covers the glm-5.3-flash quirks verified live 2026-08:
- the ``thinking`` field is NEVER sent (any thinking object is rejected
  by the API with HTTP 400 code 1210, since glm-5.3-flash always thinks);
- ``content`` is read from the response (not ``reasoning_content``);
- max_tokens is set generously so reasoning tokens don't truncate output;
- vision requests use base64 image_url parts.
"""

import base64
import io
import json
import struct
import zlib
from unittest.mock import patch

import pytest

from engine.broker.providers.zai import BASE_URL, ZaiVisionProvider
from engine.broker.providers.base import ProviderError


def _png_bytes(size: int = 8) -> bytes:
    """Minimal valid PNG (1x1-ish) — enough for mimetypes + base64 tests."""

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _fake_urlopen(resp_dict: dict):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(json.dumps(resp_dict).encode("utf-8"))


def _chat_response(content="FINAL", model="glm-5.3-flash"):
    return {
        "choices": [{"message": {
            "role": "assistant",
            "content": content,
            "reasoning_content": "thinking out loud — must be ignored",
        }}],
        "model": model,
        "usage": {"total_tokens": 42},
    }


class TestZaiProviderChat:
    def test_no_thinking_field_sent_and_content_read(self):
        captured = {}

        def fake_request(self, method, path, payload=None, timeout=60):
            captured["payload"] = payload
            return _chat_response()

        with patch.object(ZaiVisionProvider, "_request", fake_request):
            provider = ZaiVisionProvider(api_key="test-key")
            out = provider.chat([{"role": "user", "content": "hi"}],
                                max_tokens=1000)

        assert out == "FINAL"  # content, not reasoning_content
        assert "thinking" not in captured["payload"]  # 400 code 1210 guard
        assert captured["payload"]["max_tokens"] == 1000
        assert captured["payload"]["model"] == "glm-5.3-flash"

    def test_analyze_image_builds_base64_vision_payload(self, tmp_path):
        img = tmp_path / "sheet.png"
        img.write_bytes(_png_bytes())
        captured = {}

        def fake_request(self, method, path, payload=None, timeout=60):
            captured["payload"] = payload
            return _chat_response(content='{"score": 88, "issues": [], "ok": true}')

        with patch.object(ZaiVisionProvider, "_request", fake_request):
            provider = ZaiVisionProvider(api_key="test-key")
            result = provider.analyze_image(img, "score this sheet")

        assert result["content"].startswith('{"score"')
        parts = captured["payload"]["messages"][0]["content"]
        assert parts[0]["type"] == "image_url"
        url = parts[0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        base64.b64decode(url.split(",", 1)[1])  # valid base64
        assert parts[1] == {"type": "text", "text": "score this sheet"}
        assert "thinking" not in captured["payload"]
        assert captured["payload"]["max_tokens"] == 4096

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ZAI_MODEL", "glm-5.3-flash")
        monkeypatch.setenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4/")
        with patch.object(ZaiVisionProvider, "_request",
                          lambda self, m, p, payload=None, timeout=60: _chat_response()):
            provider = ZaiVisionProvider(api_key="k")
            assert provider.model == "glm-5.3-flash"
            assert BASE_URL.startswith("https://api.z.ai/api/paas/v4")

    def test_disabled_without_key(self, monkeypatch):
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        provider = ZaiVisionProvider(api_key="")
        assert provider.capabilities().enabled is False
        with pytest.raises(ProviderError):
            provider._headers()

    def test_generate_image_fails_over(self):
        provider = ZaiVisionProvider(api_key="k")
        with pytest.raises(ProviderError):
            provider.generate_image("a hero shot")
