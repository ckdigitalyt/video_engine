"""test_v4_minimax_h3.py — Offline contract tests for the MiniMax H3 provider
(directive §9). All HTTP mocked; no key required (enabled:false without
MINIMAX_API_KEY — verified). Live testing requires paid spend → NOT done.
"""

import json
import urllib.error
from unittest import mock

import pytest

from engine.broker.providers.base import ProviderError
from engine.broker.providers import minimax as mm


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _provider():
    return mm.MiniMaxH3Provider(api_key="test-key", poll_interval=0.01)


# ── Registration / gating ────────────────────────────────────────────────


def test_disabled_without_api_key():
    p = mm.MiniMaxH3Provider(api_key="")
    assert p.capabilities().enabled is False
    assert p.health_check() is False
    with pytest.raises(ProviderError, match="MINIMAX_API_KEY not set"):
        p.generate_video("x")
    with pytest.raises(ProviderError, match="MINIMAX_API_KEY not set"):
        p.image_to_video("/tmp/nope.png", "x")


def test_enabled_with_api_key_and_descriptor_notes():
    p = _provider()
    caps = p.capabilities()
    assert caps.enabled is True
    assert caps.id == "minimax_h3"
    assert "MiniMax-H3" in caps.models
    # Directive §9/§26: paid-only must be loudly documented.
    assert "paid" in caps.notes.lower() or "pay" in caps.notes.lower()


# ── Submit contract (v2 payload shape from live docs) ────────────────────


def test_t2v_payload_shape_and_ratio_required():
    p = _provider()
    captured = {}

    def fake_post(method, url, payload=None):
        captured["method"], captured["url"], captured["payload"] = \
            method, url, payload
        return {"task_id": "task-123"}

    with mock.patch.object(p, "_request_json", side_effect=fake_post):
        tid = p.submit_task([{"type": "text", "text": "hello"}],
                            duration=6, ratio="16:9")
    assert tid == "task-123"
    assert captured["url"] == "https://api.minimax.io/v2/video_generation"
    assert captured["method"] == "POST"
    assert captured["payload"]["model"] == "MiniMax-H3"
    assert captured["payload"]["duration"] == 6
    assert captured["payload"]["resolution"] == "768P"
    assert captured["payload"]["ratio"] == "16:9"


def test_i2v_payload_uses_first_frame_role_and_adaptive_ratio():
    p = _provider()
    captured = {}

    def fake_post(method, url, payload=None):
        captured["payload"] = payload
        return {"task_id": "t"}

    with mock.patch.object(p, "_request_json", side_effect=fake_post):
        p.submit_task([
            {"type": "text", "text": "bring to life"},
            {"type": "image_url",
             "image_url": {"url": "https://cdn.example/kf.png"},
             "role": "first_frame"},
        ], duration=6, ratio=None)
    body = captured["payload"]
    assert "ratio" not in body  # I2V: adaptive — aspect follows input image
    roles = [c.get("role") for c in body["content"]]
    assert roles == [None, "first_frame"]


def test_duration_must_be_integer_4_to_15():
    p = _provider()
    for bad in (0, 3, 16):
        with pytest.raises(ProviderError, match="4–15"):
            p.submit_task([{"type": "text", "text": "x"}], duration=bad)
    # Broker callers pass floats (5.0) — 4.5 rounds to a valid 4.
    assert p._coerce_duration(5.0) == 5
    assert p._coerce_duration(4.5) == 4


def test_auth_error_classification():
    p = _provider()
    err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(ProviderError, match="auth failed"):
            p.query_task("t")


# ── Poll / download lifecycle ────────────────────────────────────────────


def test_poll_returns_url_on_success_and_downloads_mp4(tmp_path, monkeypatch):
    class _StubCache:
        def store_bytes(self, key, data, ext="mp4"):
            return tmp_path / "out.mp4"

    p = mm.MiniMaxH3Provider(api_key="test-key", poll_interval=0.01,
                             cache=_StubCache())

    def fake_post(method, url, payload=None):
        if method == "POST":
            return {"task_id": "t-42"}
        task = {"status": "succeeded",
                "content": {"url": "https://cdn.example/v.mp4"}}
        return {"task": task}

    mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8192
    with mock.patch.object(p, "_request_json", side_effect=fake_post), \
         mock.patch.object(p, "_download", return_value=mp4) as dl:
        out = p.generate_video("a volcano erupts", duration=6)
    dl.assert_called_once_with("https://cdn.example/v.mp4")
    assert out.provider == "minimax_h3"
    assert out.kind == "video"
    assert out.metadata["task_id"] == "t-42"


def test_poll_times_out():
    p = mm.MiniMaxH3Provider(api_key="k", poll_timeout=0.05, poll_interval=0.01)
    with mock.patch.object(p, "query_task",
                           return_value={"status": "in_progress"}):
        with pytest.raises(ProviderError, match="poll timeout"):
            p.poll_task("t")


def test_terminal_failure_raises():
    p = _provider()
    with mock.patch.object(p, "query_task",
                           return_value={"status": "failed",
                                         "base_resp": {"msg": "bad prompt"}}):
        with pytest.raises(ProviderError, match="failed"):
            p.poll_task("t")


def test_download_validates_mp4_magic():
    p = _provider()
    with mock.patch("urllib.request.urlopen",
                    return_value=_FakeResponse(b"GIF89a" + b"\x00" * 2048)):
        with pytest.raises(ProviderError, match="not a valid MP4"):
            p._download("https://cdn.example/v.mp4")


def test_image_to_video_local_path_becomes_data_url(tmp_path):
    p = _provider()
    img = tmp_path / "key.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    captured = {}

    def fake_post(method, url, payload=None):
        captured["payload"] = payload
        return {"task_id": "t"}

    with mock.patch.object(p, "_request_json", side_effect=fake_post), \
         mock.patch.object(p, "poll_task", return_value="https://u/v.mp4"), \
         mock.patch.object(p, "_download",
                           return_value=b"\x00\x00\x00\x18ftypisom" +
                                        b"\x00" * 8192):
        out = p.image_to_video(img, "animate this", duration=6)
    content = captured["payload"]["content"]
    assert content[1]["role"] == "first_frame"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert out.kind == "image_to_video"


def test_image_to_data_url_missing_file():
    with pytest.raises(ProviderError, match="not found"):
        mm.image_to_data_url("/definitely/not/here.png")


def test_sniff_mp4():
    assert mm.sniff_mp4(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64)
    assert not mm.sniff_mp4(b"GIF89a" + b"\x00" * 64)
