"""minimax.py — MiniMax H3 video provider (directive §9).

Official API ONLY (no unofficial wrappers/downloaders). Contract researched
from the live docs on 2026-08-30:

  https://platform.minimax.io/docs/guides/video-generation
  https://platform.minimax.io/docs/api-reference/video-generation-v2-create
  https://platform.minimax.io/docs/api-reference/video-generation-v2-query

  Create : POST https://api.minimax.io/v2/video_generation
           Bearer MINIMAX_API_KEY
           {"model": "MiniMax-H3",
            "content": [{"type": "text", "text": ...},
                        {"type": "image_url", "image_url": {"url": ...},
                         "role": "first_frame"|"last_frame"}, ...],
            "duration": 4..15 (int seconds),
            "resolution": "768P"|"2K",
            "ratio": "16:9"|... (REQUIRED for T2V; I2V is "adaptive")}
           → {"task_id": ...}
  Poll   : GET https://api.minimax.io/v2/query/video_generation/{task_id}
           → {"task": {"status": "queued"|"in_progress"|"succeeded"|
                       "failed"|"cancelled",
                       "content": {"url": <mp4 download url>}}}
  Fetch  : GET content.url → mp4 bytes (validated by magic bytes).

COST (2026-08-30): pay-as-you-go per-second video billing; NO free tier.
Enabled only when MINIMAX_API_KEY exists — otherwise ``enabled: false`` and
the broker fails over to Wan 2.2 / LTX (free ZeroGPU Spaces). NOT live-tested
this phase: no key in .env and testing requires spend (§26 HERO-only gate).

Modes implemented: T2V, I2V (first-frame), first+last-frame; reference
generation is an H3-only extension (accepts reference images via
``reference_images`` kwarg).
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from engine.broker.cache import BrokerCache, broker_cache_key
from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)

BASE_URL = "https://api.minimax.io"
DEFAULT_MODEL = "MiniMax-H3"
DEFAULT_RESOLUTION = "768P"  # 2K costs more; 768P is the sane default
_MIN_OUTPUT_BYTES = 4096
_POLL_INTERVAL = 10.0  # docs-recommended
_TERMINAL_OK = ("succeeded",)
_TERMINAL_BAD = ("failed", "cancelled")


def sniff_mp4(data: bytes) -> bool:
    """Coarse MP4/ISOMBFF magic check (ftyp box within first 32 bytes)."""
    if len(data) < 16:
        return False
    return data[4:8] == b"ftyp" or b"ftyp" in data[:32]


def image_to_data_url(path: str | Path) -> str:
    """Local image → base64 data URL (input-requirements doc: JPG/PNG/WEBP ≤30MB).

    NOTE (honest limitation): the docs show hosted-URL input for I2V. Data-URL
    input is the standard fallback and accepted per the ≤64MB body limit, but
    is UNVERIFIED live (no key this phase). Prefer passing a hosted URL.
    """
    p = Path(path)
    if not p.exists():
        raise ProviderError(f"minimax_h3: image not found: {p}")
    raw = p.read_bytes()
    if len(raw) > 30 * 1024 * 1024:
        raise ProviderError("minimax_h3: image exceeds 30MB limit")
    suffix = p.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


class MiniMaxH3Provider(MediaProvider):
    """MiniMax H3 (Hailuo) cinematic video — official v2 API, pay-as-you-go."""

    id = "minimax_h3"
    kind = "video"

    def __init__(self, api_key: str | None = None,
                 cache: BrokerCache | None = None,
                 model: str = DEFAULT_MODEL,
                 poll_timeout: float = 900.0,
                 poll_interval: float = _POLL_INTERVAL) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get(
            "MINIMAX_API_KEY", "")
        self.cache = cache or BrokerCache()
        self.model = model
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval

    # ── MediaProvider surface ────────────────────────────────────────────

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=[self.model, "MiniMax-H3-Max"],
            enabled=bool(self._api_key), priority=10,
            notes=(
                "Paid-only official MiniMax v2 API (api.minimax.io/"
                "v2/video_generation), pay-as-you-go per-second billing, "
                "no free tier (verified 2026-08-30 docs). Set "
                "MINIMAX_API_KEY + §26 cost approval to enable. T2V + I2V + "
                "first/last-frame + reference. NOT live-tested this phase "
                "(testing requires spend)."
            ),
        )

    def health_check(self) -> bool:
        return bool(self._api_key)

    # ── HTTP plumbing (never logs the key) ───────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _request_json(self, method: str, url: str,
                      payload: dict | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(),
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(512).decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code in (401, 403):
                raise ProviderError(
                    f"minimax_h3: auth failed (HTTP {exc.code}) — check "
                    "MINIMAX_API_KEY") from None
            raise ProviderError(
                f"minimax_h3: HTTP {exc.code}: {detail[:300]}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"minimax_h3: connection error ({exc.reason})") from None

    # ── Task lifecycle: submit → poll → download ────────────────────────

    @staticmethod
    def _coerce_duration(duration: float) -> int:
        """API requires integer 4–15 seconds. Broker callers pass floats
        (e.g. 5.0) — round to nearest int, then range-check."""
        try:
            secs = int(round(float(duration)))
        except (TypeError, ValueError):
            raise ProviderError("minimax_h3: invalid duration") from None
        if not 4 <= secs <= 15:
            raise ProviderError(
                "minimax_h3: duration must be 4–15 seconds after rounding")
        return secs

    def submit_task(self, content: list[dict[str, Any]], *,
                    duration: int, resolution: str = DEFAULT_RESOLUTION,
                    ratio: str | None = None) -> str:
        """Create a video_generation task; returns task_id.

        ``ratio`` is REQUIRED for T2V (cannot be 'adaptive'); I2V omits it
        (aspect follows the input image → 'adaptive' server-side).
        """
        secs = self._coerce_duration(duration)
        payload: dict[str, Any] = {
            "model": self.model,
            "content": content,
            "duration": secs,
            "resolution": resolution,
        }
        if ratio:
            payload["ratio"] = ratio
        body = self._request_json("POST", f"{BASE_URL}/v2/video_generation",
                                  payload)
        task_id = body.get("task_id")
        if not task_id:
            raise ProviderError(
                f"minimax_h3: no task_id in submit response: {str(body)[:200]}")
        return str(task_id)

    def query_task(self, task_id: str) -> dict[str, Any]:
        body = self._request_json(
            "GET", f"{BASE_URL}/v2/query/video_generation/{task_id}")
        return body.get("task") or {}

    def poll_task(self, task_id: str, timeout: float | None = None) -> str:
        """Poll until terminal; returns the video download URL on success."""
        limit = timeout if timeout is not None else self.poll_timeout
        deadline = time.monotonic() + limit
        while True:
            task = self.query_task(task_id)
            status = task.get("status", "")
            if status in _TERMINAL_OK:
                url = (task.get("content") or {}).get("url")
                if not url:
                    raise ProviderError(
                        f"minimax_h3: task {task_id} succeeded without "
                        "content.url")
                return str(url)
            if status in _TERMINAL_BAD:
                raise ProviderError(
                    f"minimax_h3: task {task_id} terminal status "
                    f"{status!r}: {str(task.get('base_resp') or task)[:300]}")
            if time.monotonic() > deadline:
                raise ProviderError(
                    f"minimax_h3: poll timeout after {limit:.0f}s "
                    f"(task {task_id} status={status!r})")
            time.sleep(self.poll_interval)

    def _download(self, url: str) -> bytes:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            raise ProviderError(
                f"minimax_h3: download HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"minimax_h3: download error ({exc.reason})") from None
        if len(data) < _MIN_OUTPUT_BYTES or not sniff_mp4(data):
            raise ProviderError(
                "minimax_h3: download is not a valid MP4 "
                f"({len(data)} bytes)")
        return data

    # ── Generation ops ───────────────────────────────────────────────────

    def generate_video(self, prompt: str, *, duration: int = 6,
                       aspect: str = "16:9", resolution: str = DEFAULT_RESOLUTION,
                       seed: int = 0, style: Any = None,
                       reference_images: list[str] | None = None,
                       **kw: Any) -> BrokerResult:
        """T2V (and H3 reference-conditioned T2V via ``reference_images``)."""
        if not self._api_key:
            raise ProviderError(
                "minimax_h3: provider not enabled — MINIMAX_API_KEY not set "
                "(paid-only, per-second billing; §26 HERO-only spend gate)")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for idx, img in enumerate(reference_images or []):
            content.append({
                "type": "image_url",
                "image_url": {"url": image_to_data_url(img)
                              if not str(img).startswith(("http://", "https://",
                                                          "data:"))
                              else str(img)},
                "role": f"reference_{idx + 1}",
            })
        task_id = self.submit_task(content, duration=duration,
                                   resolution=resolution, ratio=aspect)
        url = self.poll_task(task_id)
        data = self._download(url)
        key = broker_cache_key(prompt=prompt, model=self.model,
                               duration=duration, seed=seed, aspect=aspect,
                               op="generate_video", renderer_version="v4")
        path = self.cache.store_bytes(key, data, ext="mp4")
        return BrokerResult(
            path=path, provider=self.id, kind="video",
            metadata={"task_id": task_id, "model": self.model,
                      "resolution": resolution, "duration": duration,
                      "aspect": aspect, "seed": seed},
        )

    def image_to_video(self, image: str | Path, prompt: str, *,
                       duration: int = 6, resolution: str = DEFAULT_RESOLUTION,
                       last_frame: str | Path | None = None,
                       seed: int = 0, **kw: Any) -> BrokerResult:
        """I2V: first-frame image (+ optional last-frame) + prompt.

        Aspect follows the input image ('adaptive' server-side) — no ratio.
        """
        if not self._api_key:
            raise ProviderError(
                "minimax_h3: provider not enabled — MINIMAX_API_KEY not set "
                "(paid-only, per-second billing; §26 HERO-only spend gate)")
        img = str(image)
        if not img.startswith(("http://", "https://", "data:")):
            img = image_to_data_url(img)
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": img},
             "role": "first_frame"},
        ]
        if last_frame is not None:
            lf = str(last_frame)
            if not lf.startswith(("http://", "https://", "data:")):
                lf = image_to_data_url(lf)
            content.append({"type": "image_url", "image_url": {"url": lf},
                            "role": "last_frame"})
        task_id = self.submit_task(content, duration=duration,
                                   resolution=resolution, ratio=None)
        url = self.poll_task(task_id)
        data = self._download(url)
        key = broker_cache_key(prompt=prompt, input_path=image,
                               model=self.model, duration=duration, seed=seed,
                               op="image_to_video", renderer_version="v4")
        path = self.cache.store_bytes(key, data, ext="mp4")
        return BrokerResult(
            path=path, provider=self.id, kind="image_to_video",
            metadata={"task_id": task_id, "model": self.model,
                      "resolution": resolution, "duration": duration,
                      "seed": seed},
        )
