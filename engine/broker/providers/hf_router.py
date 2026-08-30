"""hf_router.py — HF Inference Providers video generation (directive §8/§10).

Free-tier production path discovered 2026-08-30: the repo HF token ships a
small monthly credit balance usable against Inference Providers — Wan 2.2
T2V **and** I2V were generated LIVE through it this phase:

  POST https://router.huggingface.co/fal-ai/fal-ai/wan/v2.2-a14b/text-to-video
       {"prompt", "resolution": "480p", "aspect_ratio": "16:9",
        "duration": 5, "enable_prompt_expansion": false}
       → 200 {"video": {"url": ...}}          (live-verified, 2026-08-30)

  POST https://router.huggingface.co/fal-ai/fal-ai/wan/v2.2-a14b/image-to-video
       {"prompt", "image_url": <data URI>, "resolution": "480p",
        "duration": 5, "enable_prompt_expansion": false}
       → 200 {"video": {"url": ...}}          (live-verified, 20s, 2026-08-30)

Cost model: draws down the account's MONTHLY included credits (free tier is
tiny; HTTP 402 "You have depleted your monthly included credits" when empty).
Credits renew monthly → this provider self-recovers, unlike ZeroGPU's daily
quota. A 402 is classified QUOTA_EXHAUSTED by the §7 taxonomy so failover is
clean. Model/provider alternatives (fal-ai LTX, wavespeed Wan) are documented
in configs/providers.yaml and enabled by swapping the endpoint mapping.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
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

ROUTER_BASE = "https://router.huggingface.co"
_MIN_OUTPUT_BYTES = 4096
_TIMEOUT = 480


def sniff_mp4(data: bytes) -> bool:
    if len(data) < 16:
        return False
    return data[4:8] == b"ftyp" or b"ftyp" in data[:32]


def _data_url(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise ProviderError(f"hf_router: image not found: {p}")
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    raw = p.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _load_cfg() -> dict[str, Any]:
    try:
        import yaml

        root = Path(__file__).resolve().parent.parent.parent.parent
        with open(root / "configs" / "providers.yaml", "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return (data.get("hf_router") or {})
    except Exception:  # config missing → defaults
        return {}


class _HFRouterBase(MediaProvider):
    """Shared plumbing for the HF-router T2V / I2V providers."""

    kind = "video"

    def __init__(self, cache: BrokerCache | None = None,
                 token: str | None = None,
                 cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg if cfg is not None else _load_cfg()
        self.cache = cache or BrokerCache()
        self._token = token if token is not None else os.environ.get("HF_TOKEN", "")

    @property
    def _op_cfg(self) -> dict[str, Any]:
        raise NotImplementedError

    def capabilities(self) -> ProviderDescriptor:
        op = self._op_cfg
        return ProviderDescriptor(
            id=self.id, kind=self.kind,
            models=[op.get("model_id", "Wan2.2")],
            enabled=bool(self._token),
            priority=12,
            notes=(
                "HF Inference Providers (router.huggingface.co) via fal-ai — "
                "bills the account's MONTHLY included credits (not ZeroGPU "
                "quota). T2V + I2V live-verified 2026-08-30. 402 when credits "
                "depleted; renews monthly."
            ),
        )

    def health_check(self) -> bool:
        return bool(self._token)

    def quota(self) -> dict[str, Any] | None:
        return None  # no readback endpoint; 402 is the signal

    def _call(self, provider_id_path: str, payload: dict[str, Any]) -> str:
        """POST to the router; return the result video URL."""
        if not self._token:
            raise ProviderError("hf_router: HF_TOKEN not set")
        url = f"{ROUTER_BASE}/{self._cfg.get('provider', 'fal-ai')}/{provider_id_path}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._token}",
                     "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                out = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(400).decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code == 402:
                raise ProviderError(
                    "hf_router: monthly included credits depleted (HTTP 402) "
                    "— QUOTA_EXHAUSTED until renewal; purchase prepaid "
                    "credits or wait for reset") from None
            if exc.code in (401, 403):
                raise ProviderError(
                    f"hf_router: auth failed (HTTP {exc.code}) — check "
                    "HF_TOKEN / provider permissions") from None
            raise ProviderError(
                f"hf_router: HTTP {exc.code}: {detail[:300]}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"hf_router: connection error ({exc.reason})") from None
        video = out.get("video") if isinstance(out, dict) else None
        url_out = (video or {}).get("url") if isinstance(video, dict) else None
        if not url_out:
            raise ProviderError(
                f"hf_router: no video url in response: {str(out)[:200]}")
        return str(url_out)

    def _download(self, url: str) -> bytes:
        try:
            with urllib.request.urlopen(url, timeout=300) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"hf_router: download HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"hf_router: download error ({exc.reason})") from None
        if len(data) < _MIN_OUTPUT_BYTES or not sniff_mp4(data):
            raise ProviderError(
                f"hf_router: download is not a valid MP4 ({len(data)} bytes)")
        return data

    def _store(self, key: str, data: bytes, kind: str, extra: dict) -> BrokerResult:
        path = self.cache.store_bytes(key, data, ext="mp4")
        return BrokerResult(path=path, provider=self.id, kind=kind,
                            metadata=extra)


class HFRouterT2VProvider(_HFRouterBase):
    """Text-to-video via HF Inference Providers (default: Wan2.2-T2V-A14B)."""

    id = "hf_router_t2v"
    kind = "video"

    @property
    def _op_cfg(self) -> dict[str, Any]:
        return self._cfg.get("t2v") or {}

    def generate_video(self, prompt: str, *, duration: float = 5.0,
                       aspect: str = "16:9", seed: int = 0, **kw: Any
                       ) -> BrokerResult:
        op = self._op_cfg
        endpoint = op.get("endpoint",
                          "fal-ai/wan/v2.2-a14b/text-to-video")
        defaults = dict(op.get("defaults") or {})
        payload = {
            "prompt": prompt,
            "resolution": defaults.get("resolution", "480p"),
            "aspect_ratio": aspect if aspect in ("16:9", "9:16", "1:1",
                                                 "4:3", "3:4") else "16:9",
            "duration": 9 if float(duration) > 6 else 5,
            "enable_prompt_expansion": defaults.get(
                "enable_prompt_expansion", False),
        }
        url = self._call(endpoint, payload)
        data = self._download(url)
        key = broker_cache_key(prompt=prompt, model=op.get("model_id", ""),
                               seed=seed, duration=duration, aspect=aspect,
                               op="generate_video", renderer_version="v4")
        return self._store(key, data, "video", {
            "router_endpoint": endpoint, "model": op.get("model_id"),
            "seed": seed, "duration": payload["duration"],
        })


class HFRouterI2VProvider(_HFRouterBase):
    """Image-to-video via HF Inference Providers (default: Wan2.2-I2V-A14B)."""

    id = "hf_router_i2v"
    kind = "image_to_video"

    @property
    def _op_cfg(self) -> dict[str, Any]:
        return self._cfg.get("i2v") or {}

    def image_to_video(self, image: str | Path, prompt: str, *,
                       duration: float = 5.0, seed: int = 0,
                       aspect: str = "16:9", **kw: Any) -> BrokerResult:
        op = self._op_cfg
        endpoint = op.get("endpoint",
                          "fal-ai/wan/v2.2-a14b/image-to-video")
        defaults = dict(op.get("defaults") or {})
        image = Path(image)
        if not image.exists():
            raise ProviderError(f"hf_router: input image missing: {image}")
        payload = {
            "prompt": prompt,
            "image_url": _data_url(image),
            "resolution": defaults.get("resolution", "480p"),
            "duration": 9 if float(duration) > 6 else 5,
            "enable_prompt_expansion": defaults.get(
                "enable_prompt_expansion", False),
        }
        url = self._call(endpoint, payload)
        data = self._download(url)
        key = broker_cache_key(prompt=prompt, input_path=image,
                               model=op.get("model_id", ""), seed=seed,
                               duration=duration, aspect=aspect,
                               op="image_to_video", renderer_version="v4")
        return self._store(key, data, "image_to_video", {
            "router_endpoint": endpoint, "model": op.get("model_id"),
            "seed": seed, "duration": payload["duration"],
        })
