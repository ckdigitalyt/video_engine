"""hf_zerogpu.py — Generic Hugging Face Gradio Space client (directive §10).

Endpoint-name-agnostic by design: discovers named endpoints from
``/gradio_api/info`` (fallback ``/config``), submits via
``POST /gradio_api/call/<endpoint>``, polls the SSE result stream at
``GET /gradio_api/call/<endpoint>/<event_id>``, downloads result files and
validates them (existence, size, magic bytes) before caching.

``discover(space_id)`` is a dry-run that only prints/returns endpoint
metadata. HF_TOKEN is sent as a Bearer header and NEVER logged.

Unit tests mock HTTP entirely; one optional live smoke test is marked
``@pytest.mark.live``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from engine.broker.providers.base import ProviderError

HF_BASE = "https://huggingface.co"
_REQUEST_TIMEOUT = 30
_POLL_TIMEOUT_DEFAULT = 300
_POLL_INTERVAL = 2.0
_MIN_OUTPUT_BYTES = 1024  # real generated media is never a few hundred bytes

# Magic bytes for output validation (directive step 9).
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"RIFF", "webp_or_wav"),  # RIFF container (WEBP/WAV judged by ext)
    (b"GIF8", "gif"),
    (b"\x1a\x45\xdf\xa3", "webm_or_mkv"),
)


def sniff_magic(data: bytes) -> str | None:
    """Return a coarse container type for *data*, or None if unrecognised."""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    if data[:2] == b"\x00\x00" and b"ftyp" in data[:16]:
        return "mp4"
    if b"ftyp" in data[:32]:
        return "mp4"
    return None


@dataclass
class SpaceEndpoint:
    name: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    returns: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""


@dataclass
class SpaceInfo:
    space_id: str
    endpoints: list[SpaceEndpoint] = field(default_factory=list)
    source: str = "info"  # info | config

    def endpoint(self, name: str) -> SpaceEndpoint | None:
        for ep in self.endpoints:
            if ep.name == name:
                return ep
        return None


class HFZeroGPUClient:
    """Generic Gradio Space client (ZeroGPU or CPU Spaces with gradio_api)."""

    provider_id = "hf_zerogpu"
    kind = "video"  # most Spaces used here generate video/image media

    def __init__(
        self,
        space_id: str,
        endpoint_name: str | None = None,
        token: str | None = None,
        poll_timeout: float = _POLL_TIMEOUT_DEFAULT,
    ) -> None:
        self.space_id = space_id
        self.endpoint_name = endpoint_name
        self.poll_timeout = poll_timeout
        self._token = token if token is not None else os.environ.get("HF_TOKEN", "")

    # ── HTTP plumbing (mocked in tests) ──────────────────────────────────

    def _base_url(self) -> str:
        sid = urllib.parse.quote(self.space_id, safe="/-_.")
        return f"{HF_BASE}/spaces/{sid}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _http(self, method: str, url: str, payload: dict | None = None,
              timeout: float = _REQUEST_TIMEOUT, stream: bool = False) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(512).decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code == 401 or exc.code == 403:
                raise ProviderError(
                    f"hf_zerogpu: auth failed (HTTP {exc.code}) — check HF_TOKEN"
                ) from None
            raise ProviderError(
                f"hf_zerogpu: HTTP {exc.code} on {url}: {detail[:200]}"
            ) from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"hf_zerogpu: connection error ({exc.reason})") from None

    # ── 1–3: discover / inspect / endpoints ─────────────────────────────

    def _fetch_info(self) -> dict[str, Any]:
        resp = self._http("GET", f"{self._base_url()}/gradio_api/info")
        return json.loads(resp.read().decode("utf-8"))

    def _fetch_config(self) -> dict[str, Any]:
        resp = self._http("GET", f"{self._base_url()}/config")
        return json.loads(resp.read().decode("utf-8"))

    def discover(self, verbose: bool = True) -> SpaceInfo:
        """Dry-run: discover named endpoints + parameter schemas.

        Never submits a job. Tries /gradio_api/info first, falls back to
        /config (older Spaces expose dependencies there).
        """
        try:
            raw = self._fetch_info()
            info = self._parse_info(raw)
            info.source = "info"
        except ProviderError:
            raw = self._fetch_config()
            info = self._parse_config(raw)
            info.source = "config"
        if verbose:
            print(f"Space {self.space_id} (source: {info.source})")
            for ep in info.endpoints:
                params = ", ".join(
                    f"{p.get('parameter_name', p.get('label', '?'))}"
                    f":{p.get('python_type', {}).get('type', '?')}"
                    for p in ep.parameters
                )
                print(f"  {ep.name}({params}) -> {len(ep.returns)} output(s)")
        return info

    def _parse_info(self, raw: dict[str, Any]) -> SpaceInfo:
        named = raw.get("named_endpoints", {})
        endpoints = [
            SpaceEndpoint(
                name=name.rstrip("/"),
                parameters=meta.get("parameters", []),
                returns=meta.get("returns", []),
                description=meta.get("description", ""),
            )
            for name, meta in named.items()
        ]
        return SpaceInfo(space_id=self.space_id, endpoints=endpoints)

    def _parse_config(self, raw: dict[str, Any]) -> SpaceInfo:
        endpoints: list[SpaceEndpoint] = []
        deps = raw.get("dependencies", [])
        components = {c.get("id"): c for c in raw.get("components", [])}
        for dep in deps:
            if not dep.get("api_name"):
                continue
            params = []
            for cid in dep.get("inputs", []):
                comp = components.get(cid, {})
                params.append({
                    "parameter_name": comp.get("label", f"input_{cid}"),
                    "python_type": {"type": comp.get("type", "?")},
                })
            endpoints.append(SpaceEndpoint(
                name=dep["api_name"],
                parameters=params,
                returns=[{} for _ in dep.get("outputs", [])],
            ))
        return SpaceInfo(space_id=self.space_id, endpoints=endpoints, source="config")

    # ── 4–7: submit / poll / queue handling ──────────────────────────────

    def call(self, data: list[Any], endpoint_name: str | None = None,
             timeout: float | None = None) -> dict[str, Any]:
        """Submit *data* to the named endpoint and wait for the result.

        Returns the parsed SSE 'complete' data (dict with 'output' or file
        descriptors). Raises ProviderError on error events or timeout.
        """
        ep = endpoint_name or self.endpoint_name
        if not ep:
            raise ProviderError("hf_zerogpu: no endpoint name given or configured")
        limit = timeout if timeout is not None else self.poll_timeout

        submit_url = f"{self._base_url()}/gradio_api/call/{ep}"
        resp = self._http("POST", submit_url, {"data": data})
        body = json.loads(resp.read().decode("utf-8"))
        event_id = body.get("event_id")
        if not event_id:
            raise ProviderError(f"hf_zerogpu: no event_id in submit response: {body}")

        return self._poll(ep, event_id, limit)

    def _poll(self, endpoint: str, event_id: str, timeout: float) -> dict[str, Any]:
        url = f"{self._base_url()}/gradio_api/call/{endpoint}/{event_id}"
        deadline = time.monotonic() + timeout
        req = urllib.request.Request(url, headers=self._headers())
        try:
            resp = urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT)
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"hf_zerogpu: poll HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"hf_zerogpu: poll connection error ({exc.reason})") from None
        except TimeoutError as exc:
            raise ProviderError(
                f"hf_zerogpu: poll stream stalled past request timeout"
            ) from None

        event, data_lines = None, []
        with resp:
            for raw_line in resp:
                if time.monotonic() > deadline:
                    raise ProviderError(
                        f"hf_zerogpu: poll timeout after {timeout:.0f}s "
                        f"(queue may still be running)"
                    )
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
                elif not line.strip():
                    # SSE event boundary — evaluate the completed event.
                    if event == "error":
                        raise ProviderError(
                            f"hf_zerogpu: space error: {' '.join(data_lines)[:300]}"
                        )
                    if event == "complete":
                        payload = "\n".join(data_lines)
                        try:
                            return json.loads(payload)
                        except json.JSONDecodeError:
                            return {"output": payload}
                    event, data_lines = None, []
        raise ProviderError("hf_zerogpu: stream ended without a complete event")

    # ── 8–9: download + validate ─────────────────────────────────────────

    def download_result(self, result: dict[str, Any]) -> list[bytes]:
        """Extract file URLs from a complete payload and download the bytes.

        Accepts Gradio file dicts ({url: ...} / {path: ...}) anywhere in the
        payload. Returns list of raw file bytes (validated, not yet cached).
        """
        urls = self._extract_urls(result)
        if not urls:
            raise ProviderError("hf_zerogpu: no downloadable file in result")
        out: list[bytes] = []
        for url in urls:
            data = self._download_bytes(url)
            kind = sniff_magic(data)
            if kind is None:
                raise ProviderError(f"hf_zerogpu: unrecognised output format from {url}")
            out.append(data)
        return out

    def _extract_urls(self, node: Any) -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            url = node.get("url")
            if isinstance(url, str) and url:
                found.append(url)
            for value in node.values():
                found.extend(self._extract_urls(value))
        elif isinstance(node, list):
            for item in node:
                found.extend(self._extract_urls(item))
        return found

    def _download_bytes(self, url: str, timeout: float = 120) -> bytes:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"hf_zerogpu: download HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"hf_zerogpu: download error ({exc.reason})") from None
        if len(data) < _MIN_OUTPUT_BYTES:
            raise ProviderError(
                f"hf_zerogpu: output suspiciously small ({len(data)} bytes)"
            )
        return data

    # ── 11–12: retry + failover hooks (broker orchestrates) ─────────────

    def generate(self, data: list[Any], endpoint_name: str | None = None,
                 retries: int = 2, timeout: float | None = None) -> dict[str, Any]:
        """call() with intelligent retry on transient failures.

        Auth/validation errors are not retried; queue/timeouts are.
        """
        last_exc: ProviderError | None = None
        for attempt in range(retries + 1):
            try:
                return self.call(data, endpoint_name=endpoint_name, timeout=timeout)
            except ProviderError as exc:
                msg = str(exc)
                transient = any(
                    s in msg for s in ("timeout", "connection", "queue", "HTTP 5")
                )
                last_exc = exc
                if not transient or attempt == retries:
                    raise
                time.sleep(_POLL_INTERVAL * (attempt + 1))
        raise last_exc  # pragma: no cover
