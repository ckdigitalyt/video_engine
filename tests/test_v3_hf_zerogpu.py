"""test_v3_hf_zerogpu.py — HF ZeroGPU client against mock HTTP (no network).

One optional live smoke test is marked `live` and skipped unless
RUN_LIVE_TESTS=1 is set.
"""

import io
import json
import urllib.error

import pytest

from engine.broker.providers.base import ProviderError
from engine.broker.providers.hf_zerogpu import (
    HFZeroGPUClient,
    SpaceInfo,
    sniff_magic,
)

SPACE = "acme-labs/wan-video"

INFO_JSON = {
    "named_endpoints": {
        "/infer": {
            "description": "Generate a video from a prompt",
            "parameters": [
                {"parameter_name": "prompt",
                 "python_type": {"type": "string"}},
                {"parameter_name": "seed",
                 "python_type": {"type": "float"}},
            ],
            "returns": [{"label": "output video"}],
        },
        "/upscale": {
            "description": "Upscale a video",
            "parameters": [{"parameter_name": "video",
                            "python_type": {"type": "str"}}],
            "returns": [{"label": "video"}],
        },
    }
}

CONFIG_JSON = {
    "components": [
        {"id": 12, "label": "Prompt", "type": "Textbox"},
        {"id": 15, "label": "Video out", "type": "Video"},
    ],
    "dependencies": [
        {"api_name": "infer", "inputs": [12], "outputs": [15], "trigger": "click"},
        {"api_name": "upscale", "inputs": [15], "outputs": [15], "trigger": "click"},
    ],
}

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + bytes(4096)


class FakeResp(io.BytesIO):
    """BytesIO that satisfies the urlopen response interface (read/iterate/CM)."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def sse(*events: tuple[str, str]) -> bytes:
    out = b""
    for event, data in events:
        out += f"event: {event}\ndata: {data}\n\n".encode()
    return out


class FakeURLOpen:
    """Programmable urlopen replacement keyed by URL substring."""

    def __init__(self, routes: dict):
        self.routes = routes  # callable(url) -> bytes | raises
        self.calls: list[tuple[str, bytes | None]] = []

    def __call__(self, req, timeout=None):
        url = req.get_full_url() if hasattr(req, "get_full_url") else req
        body = req.data if hasattr(req, "data") else None
        self.calls.append((url, body))
        handler = self.routes[url]
        result = handler(url, req)
        if isinstance(result, bytes):
            return FakeResp(result)
        return result  # already a response or exception


def make_client(token: str = "hf_SECRET_TOKEN") -> HFZeroGPUClient:
    return HFZeroGPUClient(SPACE, endpoint_name="infer", token=token)


class TestDiscover:
    def test_discover_from_info(self, monkeypatch, capsys):
        routes = {f"https://huggingface.co/spaces/{SPACE}/gradio_api/info":
                  lambda u, r: json.dumps(INFO_JSON).encode()}
        fake = FakeURLOpen(routes)
        monkeypatch.setattr("urllib.request.urlopen", fake)
        client = make_client()
        info = client.discover()
        assert isinstance(info, SpaceInfo)
        assert info.source == "info"
        assert [e.name for e in info.endpoints] == ["/infer", "/upscale"]
        ep = info.endpoint("/infer")
        assert ep.parameters[0]["parameter_name"] == "prompt"
        out = capsys.readouterr().out
        assert "/infer" in out and "prompt:string" in out

    def test_discover_falls_back_to_config(self, monkeypatch):
        def http_error_404(url, req):
            raise urllib.error.HTTPError(url, 404, "not found", None, None)

        routes = {
            f"https://huggingface.co/spaces/{SPACE}/gradio_api/info": http_error_404,
            f"https://huggingface.co/spaces/{SPACE}/config":
                lambda u, r: json.dumps(CONFIG_JSON).encode(),
        }
        monkeypatch.setattr("urllib.request.urlopen", FakeURLOpen(routes))
        info = make_client().discover(verbose=False)
        assert info.source == "config"
        assert info.endpoint("infer") is not None

    def test_discover_never_submits_a_job(self, monkeypatch):
        routes = {f"https://huggingface.co/spaces/{SPACE}/gradio_api/info":
                  lambda u, r: json.dumps(INFO_JSON).encode()}
        fake = FakeURLOpen(routes)
        monkeypatch.setattr("urllib.request.urlopen", fake)
        make_client().discover(verbose=False)
        assert all("call/" not in url for url, _ in fake.calls)


class TestCallFlow:
    def _routes(self, sse_bytes=b""):
        # Wave 2: client submits to the Space's direct hf.space subdomain
        # first (huggingface.co does not proxy /gradio_api/* live).
        submit_url = f"https://acme-labs-wan-video.hf.space/gradio_api/call/infer"
        poll_url = f"{submit_url}/evt-123"
        return {
            submit_url: lambda u, r: json.dumps({"event_id": "evt-123"}).encode(),
            poll_url: lambda u, r: sse_bytes,
        }, submit_url

    def test_call_completes_and_downloads_result(self, monkeypatch):
        result_payload = json.dumps(
            {"output": [{"video": {"url": "https://example.com/out.mp4",
                                   "orig_name": "out.mp4"}}]}
        )
        routes, submit_url = self._routes(
            sse(("generating", "null"), ("complete", result_payload)))
        downloads = []

        def fake_download(url, req):
            downloads.append(url)
            return FAKE_PNG

        routes["https://example.com/out.mp4"] = fake_download
        fake = FakeURLOpen(routes)
        monkeypatch.setattr("urllib.request.urlopen", fake)

        client = make_client()
        result = client.call(["a volcano erupting", 42])
        files = client.download_result(result)
        assert len(files) == 1 and sniff_magic(files[0]) == "png"
        # submit used POST with {"data": [...]}
        assert b'"data"' in (fake.calls[0][1] or b"")
        assert "evt-123" in fake.calls[1][0]

    def test_call_requires_endpoint(self, monkeypatch):
        client = HFZeroGPUClient(SPACE, endpoint_name=None)
        with pytest.raises(ProviderError, match="no endpoint"):
            client.call([])

    def test_submit_without_event_id_raises(self, monkeypatch):
        routes, _ = self._routes()
        routes[f"https://acme-labs-wan-video.hf.space/gradio_api/call/infer"] = (
            lambda u, r: json.dumps({"error": "nope"}).encode())
        monkeypatch.setattr("urllib.request.urlopen", FakeURLOpen(routes))
        with pytest.raises(ProviderError, match="event_id"):
            make_client().call(["x"])

    def test_error_event_raises(self, monkeypatch):
        routes, _ = self._routes(
            sse(("error", '"GPU quota exceeded"')))
        monkeypatch.setattr("urllib.request.urlopen", FakeURLOpen(routes))
        with pytest.raises(ProviderError, match="GPU quota"):
            make_client().call(["x"])

    def test_stream_without_complete_raises(self, monkeypatch):
        routes, _ = self._routes(sse(("generating", "null")))
        monkeypatch.setattr("urllib.request.urlopen", FakeURLOpen(routes))
        with pytest.raises(ProviderError, match="stream ended"):
            make_client().call(["x"], timeout=0.1)

    def test_sse_multi_line_data_is_joined(self, monkeypatch):
        payload = {"output": [{"url": "https://example.com/a.mp4"}]}
        # split the payload between JSON tokens across two data: lines
        j = json.dumps(payload)
        mid = j.index(": ") + 2
        raw = (f"event: complete\ndata: {j[:mid]}\ndata: {j[mid:]}\n\n").encode()
        routes, _ = self._routes(raw)
        routes["https://example.com/a.mp4"] = lambda u, r: FAKE_PNG
        monkeypatch.setattr("urllib.request.urlopen", FakeURLOpen(routes))
        client = make_client()
        result = client.call(["x"])
        assert client._extract_urls(result) == ["https://example.com/a.mp4"]


class TestOutputValidation:
    def test_tiny_output_rejected(self, monkeypatch):
        client = make_client()
        monkeypatch.setattr(
            "urllib.request.urlopen",
            FakeURLOpen({"https://x/y.mp4": lambda u, r: b"\x00" * 100}))
        with pytest.raises(ProviderError, match="suspiciously small"):
            client._download_bytes("https://x/y.mp4")

    def test_unknown_magic_rejected(self, monkeypatch):
        client = make_client()
        monkeypatch.setattr(
            "urllib.request.urlopen",
            FakeURLOpen({"https://x/y.mp4": lambda u, r: b"JUNKJUNK" * 500}))
        with pytest.raises(ProviderError, match="unrecognised"):
            client.download_result({"output": [{"url": "https://x/y.mp4"}]})

    @pytest.mark.parametrize("data,kind", [
        (b"\xff\xd8\xff" + bytes(2048), "jpeg"),
        (b"\x89PNG\r\n\x1a\n" + bytes(2048), "png"),
        (b"\x00\x00\x00\x18ftypisom" + bytes(2048), "mp4"),
        (b"GIF89a" + bytes(2048), "gif"),
    ])
    def test_sniff_magic(self, data, kind):
        assert sniff_magic(data) == kind

    def test_no_downloadable_file_rejected(self):
        with pytest.raises(ProviderError, match="no downloadable"):
            make_client().download_result({"output": "just text"})


class TestTokenSafety:
    def test_token_not_in_error_messages(self, monkeypatch):
        def auth_error(url, req):
            raise urllib.error.HTTPError(url, 401, "unauthorized", None, None)

        routes = {f"https://huggingface.co/spaces/{SPACE}/gradio_api/info": auth_error,
                  f"https://huggingface.co/spaces/{SPACE}/config": auth_error}
        monkeypatch.setattr("urllib.request.urlopen", FakeURLOpen(routes))
        client = make_client(token="hf_SECRET_TOKEN")
        with pytest.raises(ProviderError) as excinfo:
            client.discover(verbose=False)
        assert "hf_SECRET_TOKEN" not in str(excinfo.value)

    def test_token_sent_as_bearer_header(self, monkeypatch):
        routes = {f"https://huggingface.co/spaces/{SPACE}/gradio_api/info":
                  lambda u, r: json.dumps(INFO_JSON).encode()}
        fake = FakeURLOpen(routes)
        monkeypatch.setattr("urllib.request.urlopen", fake)
        make_client(token="hf_SECRET_TOKEN").discover(verbose=False)
        req = fake.calls[0][1]
        # We can't inspect headers on a Request built after the fact in this
        # fake, so assert via the client's own header builder instead.
        headers = make_client(token="hf_SECRET_TOKEN")._headers()
        assert headers["Authorization"] == "Bearer hf_SECRET_TOKEN"


class TestRetry:
    def test_transient_error_retried_then_succeeds(self, monkeypatch):
        client = make_client()
        attempts = {"n": 0}
        real_call = client.call

        def flaky(*a, **kw):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ProviderError("hf_zerogpu: connection error (reset)")
            return {"output": "ok"}

        monkeypatch.setattr(client, "call", flaky)
        monkeypatch.setattr("time.sleep", lambda s: None)
        assert client.generate(["x"]) == {"output": "ok"}
        assert attempts["n"] == 2

    def test_permanent_error_not_retried(self, monkeypatch):
        client = make_client()
        attempts = {"n": 0}

        def dead(*a, **kw):
            attempts["n"] += 1
            raise ProviderError("hf_zerogpu: space error: bad input")

        monkeypatch.setattr(client, "call", dead)
        with pytest.raises(ProviderError, match="bad input"):
            client.generate(["x"])
        assert attempts["n"] == 1


@pytest.mark.live
@pytest.mark.skipif(
    __import__("os").environ.get("RUN_LIVE_TESTS") != "1",
    reason="live HF test — set RUN_LIVE_TESTS=1",
)
class TestLive:
    def test_discover_live_space(self):
        # Cheap, well-known public Space; discover() never submits a job.
        client = HFZeroGPUClient("multimodalart-flux-1-schnell")
        info = client.discover()
        assert info.endpoints, "expected at least one named endpoint"
