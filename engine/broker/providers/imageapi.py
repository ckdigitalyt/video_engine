"""imageapi.py — SiliconFlow + NVIDIA NIM image providers for the broker.

Thin MediaProvider wrappers around the proven generation logic in
``src/providers/image_gen.py`` patterns (FLUX endpoints, verified 2026-08).
Both are free-tier keys already present in .env; the broker tries them in
failover order (siliconflow → nvidia_nim → hf_zerogpu space).
"""

from __future__ import annotations

import base64
import json
import os
import time
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

_MIN_IMAGE_BYTES = 15_000

# (width, height) per aspect — request size for the image APIs.
_ASPECT_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (1024, 1024),
}


def _looks_like_image(data: bytes) -> bool:
    if len(data) < _MIN_IMAGE_BYTES:
        return False
    try:
        from PIL import Image
        import io

        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:
        return False


class SiliconFlowImageProvider(MediaProvider):
    """SiliconFlow FLUX image generation (OpenAI-compatible endpoint)."""

    id = "siliconflow"
    kind = "image"

    def __init__(self, cache: BrokerCache | None = None, api_key: str | None = None,
                 model: str = "black-forest-labs/FLUX.1-schnell") -> None:
        self.cache = cache or BrokerCache()
        self._api_key = api_key if api_key is not None else os.environ.get("SILICONFLOW_API_KEY", "")
        self._model = model

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=[self._model],
            enabled=bool(self._api_key), priority=10,
            notes="SiliconFlow FLUX.1-schnell (free-tier key)",
        )

    def health_check(self) -> bool:
        return bool(self._api_key)

    def _generate_bytes(self, prompt: str, width: int, height: int,
                        seed: int) -> bytes:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "image_size": f"{width}x{height}",
            "batch_size": 1,
            "seed": seed,
        }
        req = urllib.request.Request(
            "https://api.siliconflow.cn/v1/images/generations",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
        b64 = body.get("data", [{}])[0].get("b64_json")
        if b64:
            return base64.b64decode(b64)
        url = body.get("data", [{}])[0].get("url")
        if url:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        raise ProviderError(f"{self.id}: unexpected response shape {list(body)[:5]}")

    def generate_image(self, prompt: str, *, style: Any = None,
                       aspect: str = "16:9", seed: int = 0,
                       **kw: Any) -> BrokerResult:
        if not self._api_key:
            raise ProviderError(f"{self.id}: SILICONFLOW_API_KEY not set")
        width, height = _ASPECT_SIZES.get(aspect, _ASPECT_SIZES["16:9"])
        seed = seed or int(time.time()) % 100000
        data = self._generate_bytes(prompt, width, height, seed)
        if not _looks_like_image(data):
            raise ProviderError(f"{self.id}: non-image payload returned")
        key = broker_cache_key(prompt=prompt, model=self._model, seed=seed,
                               aspect=aspect, op="generate_image")
        path = self.cache.store_bytes(key, data, ext="png")
        return BrokerResult(path=path, provider=self.id, kind="image",
                            metadata={"model": self._model, "seed": seed})


class NvidiaNimImageProvider(MediaProvider):
    """NVIDIA NIM hosted FLUX (flux.2-klein-4b → flux.1-dev → schnell)."""

    id = "nvidia_nim"
    kind = "image"

    _FLUX2_PAIRS = [
        (672, 1568), (688, 1504), (720, 1456), (752, 1392), (800, 1328),
        (832, 1248), (880, 1184), (944, 1104), (1024, 1024),
    ]
    _ALLOWED_DIMS = [768, 832, 896, 960, 1024, 1088, 1152, 1216, 1280, 1344]
    ENDPOINTS = [
        "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b",
        "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
        "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell",
    ]

    def __init__(self, cache: BrokerCache | None = None, api_key: str | None = None) -> None:
        self.cache = cache or BrokerCache()
        self._api_key = api_key if api_key is not None else os.environ.get("NVIDIA_API_KEY", "")

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=["flux.2-klein-4b", "flux.1-dev"],
            enabled=bool(self._api_key), priority=20,
            notes="NVIDIA NIM FLUX (free-tier key)",
        )

    def health_check(self) -> bool:
        return bool(self._api_key)

    @classmethod
    def _snap_pair(cls, width: int, height: int) -> tuple[int, int]:
        target = width / max(height, 1)
        return min(
            ((w, h) for p in cls._FLUX2_PAIRS for w, h in (p, (p[1], p[0]))),
            key=lambda wh: abs(wh[0] / wh[1] - target),
        )

    def _generate_bytes(self, prompt: str, width: int, height: int,
                        seed: int) -> bytes:
        pair = self._snap_pair(width, height)
        last_err: Exception | None = None
        for i, url in enumerate(self.ENDPOINTS):
            try:
                payload = {
                    "prompt": prompt,
                    "width": pair[0] if i == 0 else min(
                        self._ALLOWED_DIMS, key=lambda d: abs(d - width)),
                    "height": pair[1] if i == 0 else min(
                        self._ALLOWED_DIMS, key=lambda d: abs(d - height)),
                    "seed": seed,
                }
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode(),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    body = json.loads(resp.read().decode())
                b64 = (
                    body.get("artifacts", [{}])[0].get("base64")
                    or body.get("data", [{}])[0].get("b64_json")
                )
                if b64:
                    return base64.b64decode(b64)
                img_url = body.get("url") or (body.get("data") or [{}])[0].get("url")
                if img_url:
                    with urllib.request.urlopen(img_url, timeout=120) as r:
                        return r.read()
                last_err = ProviderError(
                    f"{self.id}: unexpected response shape {list(body)[:5]}")
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 — try next endpoint
                last_err = exc
                continue
        raise ProviderError(f"{self.id}: all endpoints failed ({last_err})")

    def generate_image(self, prompt: str, *, style: Any = None,
                       aspect: str = "16:9", seed: int = 0,
                       **kw: Any) -> BrokerResult:
        if not self._api_key:
            raise ProviderError(f"{self.id}: NVIDIA_API_KEY not set")
        width, height = _ASPECT_SIZES.get(aspect, _ASPECT_SIZES["16:9"])
        seed = seed or int(time.time()) % 100000
        data = self._generate_bytes(prompt, width, height, seed)
        if not _looks_like_image(data):
            raise ProviderError(f"{self.id}: non-image payload returned")
        key = broker_cache_key(prompt=prompt, model="nvidia_nim", seed=seed,
                               aspect=aspect, op="generate_image")
        path = self.cache.store_bytes(key, data, ext="png")
        return BrokerResult(path=path, provider=self.id, kind="image",
                            metadata={"model": "flux.2-klein-4b", "seed": seed})
