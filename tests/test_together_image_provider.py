"""Together.ai FLUX.1-schnell-Free provider (added 2026-10-23, see
src/providers/image_gen.py::TogetherProvider docstring for why: nvidia_nim,
the chain's main fallback, was the biggest driver of worst-case render
time; Together's free/uncapped FLUX tier goes ahead of it)."""
import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from src.providers.image_gen import TogetherProvider


def test_is_available_requires_api_key(monkeypatch):
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    assert not TogetherProvider().is_available()
    assert TogetherProvider(api_key="x").is_available()


@pytest.mark.parametrize("v,expected", [(1024, 1024), (720, 720), (700, 704),
                                        (100, 512), (3000, 1536)])
def test_snap_rounds_to_multiple_of_16_within_range(v, expected):
    assert TogetherProvider._snap(v) == expected


def test_generate_decodes_base64_and_writes_file(tmp_path):
    img_bytes = b"\x89PNG\r\n\x1a\nfake-but-nonempty-payload"
    body = json.dumps({"data": [{"index": 0, "b64_json":
                                 base64.b64encode(img_bytes).decode()}]}).encode()
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = body
    out = tmp_path / "plate.png"
    with patch("src.providers.image_gen.urllib.request.urlopen", return_value=resp), \
         patch("src.providers.image_gen._write_verified",
               side_effect=lambda raw, path, name: str(path)) as wv:
        p = TogetherProvider(api_key="x")
        result = p.generate("a cat", str(out), width=1024, height=576, seed=7)
    assert result == str(out)
    wv.assert_called_once()
    assert wv.call_args[0][0] == img_bytes


def test_generate_without_key_raises():
    with pytest.raises(RuntimeError, match="TOGETHER_API_KEY"):
        TogetherProvider(api_key="").generate("a cat", "out.png")


def test_generate_raises_on_missing_image_in_response(tmp_path):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps({"data": []}).encode()
    with patch("src.providers.image_gen.urllib.request.urlopen", return_value=resp):
        with pytest.raises(RuntimeError, match="together: no image"):
            TogetherProvider(api_key="x").generate("a cat", str(tmp_path / "o.png"))


def test_registered_in_provider_chain():
    from src.providers.image_gen import _PROVIDERS
    assert _PROVIDERS["together"] is TogetherProvider
