"""test_v4_hf_router.py — Offline tests for the HF Inference Providers
router video path (directive §8/§10). All HTTP mocked; no network, no
credits spent.

Covers: broker registration, capability/enablement gating on HF_TOKEN,
T2V/I2V payload shape, 402 → QUOTA_EXHAUSTED classification, auth errors,
malformed responses, invalid downloads, config loading from
configs/providers.yaml, and the §7 taxonomy for the monthly-credit
depletion message.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest import mock

import pytest

from engine.broker.failures import FailureClass, classify_failure
from engine.broker.providers.base import BrokerResult, ProviderError
from engine.broker.providers.hf_router import (
    HFRouterI2VProvider,
    HFRouterT2VProvider,
    sniff_mp4,
)

_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 512  # ≥ _MIN_OUTPUT_BYTES


def _urlopen_json(payload: dict):
    """Fake urlopen returning a JSON body."""
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(body.getvalue())


def _urlopen_raw(data: bytes):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(data)


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://router.huggingface.co/fake", code, "err",
        hdrs=None, fp=io.BytesIO(body))


def _provider(cls, tmp_path, cfg=None):
    cache = mock.Mock()
    cache.store_bytes.side_effect = \
        lambda key, data, ext: str(tmp_path / f"{key[:16]}.{ext}")
    return cls(cache=cache, token="hf_test_token", cfg=cfg if cfg is not None else {})


# ── §7 taxonomy: monthly-credit depletion ────────────────────────────────


def test_402_message_classifies_quota_exhausted():
    assert classify_failure(
        "hf_router: monthly included credits depleted (HTTP 402) — "
        "QUOTA_EXHAUSTED until renewal; purchase prepaid credits or wait "
        "for reset") is FailureClass.QUOTA_EXHAUSTED


# ── Enablement / capabilities ────────────────────────────────────────────


def test_disabled_without_token(tmp_path):
    p = HFRouterT2VProvider(cache=mock.Mock(), token="", cfg={})
    assert p.capabilities().enabled is False
    assert p.health_check() is False


def test_capabilities_with_token(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    cap = p.capabilities()
    assert cap.enabled is True
    assert cap.kind == "video"
    assert "wan2.2" in cap.models[0].lower()
    assert "monthly" in cap.notes.lower()


# ── Transport / payload shape ────────────────────────────────────────────


def test_t2v_payload_and_result(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["payload"] = json.loads(req.data.decode("utf-8"))
        seen["auth"] = req.headers.get("Authorization")
        return _urlopen_json({"video": {"url": "https://cdn/x.mp4"}})

    def fake_download(url):
        seen["downloaded"] = url
        return _MP4

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
            mock.patch.object(HFRouterT2VProvider, "_download",
                              side_effect=fake_download):
        result = p.generate_video("a slow dolly-in over a coral reef",
                                  duration=5.0, aspect="16:9", seed=7)

    assert isinstance(result, BrokerResult)
    assert result.kind == "video"
    assert result.provider == "hf_router_t2v"
    assert seen["url"].endswith(
        "fal-ai/fal-ai/wan/v2.2-a14b/text-to-video")  # provider prefix + endpoint
    assert seen["auth"] == "Bearer hf_test_token"
    assert seen["payload"]["prompt"] == "a slow dolly-in over a coral reef"
    assert seen["payload"]["resolution"] == "480p"
    assert seen["payload"]["aspect_ratio"] == "16:9"
    assert seen["payload"]["duration"] == 5
    assert seen["payload"]["enable_prompt_expansion"] is False
    assert seen["downloaded"] == "https://cdn/x.mp4"


def test_duration_clamped_to_supported_tiers(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    payloads = []

    def fake_urlopen(req, timeout=0):
        payloads.append(json.loads(req.data.decode("utf-8")))
        return _urlopen_json({"video": {"url": "https://cdn/x.mp4"}})

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
            mock.patch.object(HFRouterT2VProvider, "_download",
                              return_value=_MP4):
        p.generate_video("x", duration=4.0)
        p.generate_video("x", duration=8.0)
    assert [pl["duration"] for pl in payloads] == [5, 9]


def test_unsupported_aspect_falls_back(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)

    def fake_urlopen(req, timeout=0):
        return _urlopen_json({"video": {"url": "https://cdn/x.mp4"}})

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
            mock.patch.object(HFRouterT2VProvider, "_download",
                              return_value=_MP4):
        result = p.generate_video("x", aspect="21:9")
    assert isinstance(result, BrokerResult)


def test_i2v_sends_data_uri(tmp_path):
    p = _provider(HFRouterI2VProvider, tmp_path)
    img = tmp_path / "kf.png"
    img.write_bytes(b"\x89PNG fake image bytes")
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["payload"] = json.loads(req.data.decode("utf-8"))
        return _urlopen_json({"video": {"url": "https://cdn/x.mp4"}})

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
            mock.patch.object(HFRouterI2VProvider, "_download",
                              return_value=_MP4):
        result = p.image_to_video(str(img), "waves roll onto dark sand",
                                  duration=5.0, seed=1)

    assert result.kind == "image_to_video"
    assert result.provider == "hf_router_i2v"
    assert seen["payload"]["image_url"].startswith("data:image/png;base64,")
    assert seen["payload"]["prompt"] == "waves roll onto dark sand"


def test_i2v_missing_image_raises(tmp_path):
    p = _provider(HFRouterI2VProvider, tmp_path)
    with pytest.raises(ProviderError, match="image not found|missing"):
        p.image_to_video(str(tmp_path / "nope.png"), "x")


# ── Error paths ──────────────────────────────────────────────────────────


def test_402_raises_quota_error(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    with mock.patch("urllib.request.urlopen",
                    side_effect=_http_error(402, b"depleted your monthly "
                                                 b"included credits")):
        with pytest.raises(ProviderError, match="402|credits"):
            p.generate_video("x")


def test_401_raises_auth_error(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    with mock.patch("urllib.request.urlopen", side_effect=_http_error(401)):
        with pytest.raises(ProviderError, match="auth failed"):
            p.generate_video("x")


def test_500_raises_and_classifies_transient(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    with mock.patch("urllib.request.urlopen",
                    side_effect=_http_error(500, b"boom")):
        with pytest.raises(ProviderError, match="HTTP 500") as exc:
            p.generate_video("x")
    assert classify_failure(str(exc.value)) is FailureClass.TRANSIENT_NETWORK


def test_missing_video_url_raises(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    with mock.patch("urllib.request.urlopen",
                    return_value=_urlopen_json({"error": "no video here"})):
        with pytest.raises(ProviderError, match="no video url"):
            p.generate_video("x")


def test_invalid_download_rejected(tmp_path):
    p = _provider(HFRouterT2VProvider, tmp_path)
    # _download itself validates: fake a response body that is not an MP4.
    with mock.patch("urllib.request.urlopen",
                    return_value=_urlopen_raw(b"<html>not a video</html>" + b"0" * 4096)):
        with pytest.raises(ProviderError, match="not a valid MP4"):
            p._download("https://cdn/x.mp4")


def test_no_token_raises(tmp_path):
    p = HFRouterT2VProvider(cache=mock.Mock(), token="", cfg={})
    with pytest.raises(ProviderError, match="HF_TOKEN"):
        p.generate_video("x")


# ── Config plumbing ──────────────────────────────────────────────────────


def test_config_from_providers_yaml():
    """The shipped configs/providers.yaml section is picked up: endpoint,
    model and defaults flow into capabilities + payload."""
    p1 = HFRouterT2VProvider(cache=mock.Mock(), token="t")  # loads real config
    cfg = p1._cfg
    assert cfg.get("provider"), "hf_router section missing in providers.yaml"
    assert cfg["t2v"]["endpoint"].endswith("text-to-video")
    assert cfg["i2v"]["endpoint"].endswith("image-to-video")
    p2 = HFRouterI2VProvider(cache=mock.Mock(), token="t")
    assert "wan2.2" in p2.capabilities().models[0].lower()


def test_sniff_mp4():
    assert sniff_mp4(_MP4) is True
    assert sniff_mp4(b"<html>" + b"0" * 64) is False
    assert sniff_mp4(b"short") is False
