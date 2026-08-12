"""
image_gen.py — AI image generation provider abstraction.

Interface for AI image generation with pluggable providers.  Providers are
selected by benchmark results (see scripts/benchmark_image_gen.py) and
configured via configs/image_gen.yaml.  Generated images enter the same
asset cache + Ken Burns motion pipeline as any other still asset.

Supported providers (v1):
  - nvidia_nim   : NVIDIA NIM (FLUX.1-schnell family)  [needs NVIDIA_API_KEY]
  - siliconflow  : SiliconFlow FLUX endpoint            [needs SILICONFLOW_API_KEY]
  - hf_serverless: Hugging Face Inference Endpoints     [needs HF_TOKEN]
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.config import get_config


# ═══════════════════════════════════════════════════════════════════════ #
# Interface
# ═══════════════════════════════════════════════════════════════════════ #


class ImageGenProvider(ABC):
    """Interface for AI image generation providers."""

    name: str = "base"

    @abstractmethod
    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        """Generate an image for *prompt*, save to *output_path*, return path."""
        ...

    def is_available(self) -> bool:
        """Whether this provider has the credentials needed to run."""
        return True


# ═══════════════════════════════════════════════════════════════════════ #
# NVIDIA NIM (FLUX family)
# ═══════════════════════════════════════════════════════════════════════ #


class NvidiaNimProvider(ImageGenProvider):
    """NVIDIA NIM hosted FLUX image generation.

    Verified endpoint (2026-08): ``/v1/genai/black-forest-labs/flux.1-dev``.
    ``flux.1-dev`` accepts square/landscape dims from a fixed set
    (multiples of 64); we snap requested sizes to the nearest allowed.
    """

    name = "nvidia_nim"

    # flux.1-dev valid dimensions (multiples of 64, min 768).  VERIFIED
    # against the live API 2026-08-12: BOTH axes are capped at 1344 — the
    # old list went to 2048, so 2560x1440 snapped to 2048x1408, the API
    # 422'd ("Input should be 768, ..., 1280 or 1344"), every fallback
    # endpoint failed, and the surfaced error was the dead 3rd endpoint's
    # 404.  v30: dims match what the API actually accepts.
    _ALLOWED_DIMS = [768, 832, 896, 960, 1024, 1088, 1152, 1216, 1280,
                     1344]

    # v30: dropped the dead `nvidia/flux.1-dev` route (404 page not
    # found) — it masked the real 422 dims error on every still.
    ENDPOINTS = [
        "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
        "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell",
    ]

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self._api_key)

    @classmethod
    def _snap(cls, v: int) -> int:
        return min(cls._ALLOWED_DIMS, key=lambda d: abs(d - v))

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY not set")
        # v30: preserve the requested aspect ratio — snap width first,
        # then derive the height from the snapped width (2560x1440 ->
        # 1344x768, not 1344x1344).  Independent per-axis snapping of the
        # old oversized list produced 422s.
        _w0 = width
        width = self._snap(width)
        height = self._snap(int(round(height * width / max(1, _w0))))
        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "seed": seed or int(time.time()) % 100000,
        }
        last_err: Optional[Exception] = None
        for url in self.ENDPOINTS:
            try:
                data = json.dumps(payload).encode()
                req = urllib.request.Request(
                    url, data=data,
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
                    or body.get("images", [None])[0]
                    or body.get("output", [None])[0]
                )
                if b64:
                    raw = base64.b64decode(b64)
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(raw)
                    return output_path
                img_url = body.get("url") or (body.get("data") or [{}])[0].get("url")
                if img_url:
                    with urllib.request.urlopen(img_url, timeout=120) as r:
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        Path(output_path).write_bytes(r.read())
                    return output_path
                last_err = RuntimeError(f"unexpected NIM response shape: {list(body)[:5]}")
            except urllib.error.HTTPError as e:
                last_err = e
                # 422 = schema error on this endpoint (e.g. bad dims) — try next
                continue
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        raise RuntimeError(f"NVIDIA NIM generation failed: {last_err}")


# ═══════════════════════════════════════════════════════════════════════ #
# SiliconFlow (FLUX family, OpenAI-compatible)
# ═══════════════════════════════════════════════════════════════════════ #


class SiliconFlowProvider(ImageGenProvider):
    """SiliconFlow hosted FLUX image generation (OpenAI-compatible)."""

    name = "siliconflow"

    def __init__(self, api_key: Optional[str] = None,
                 base_url: Optional[str] = None):
        self._api_key = api_key or os.environ.get("SILICONFLOW_API_KEY", "")
        self._base_url = base_url or get_config(
            "image_gen.siliconflow.base_url",
            "https://api.siliconflow.cn/v1/images/generations",
        )
        self._model = get_config("image_gen.siliconflow.model", "black-forest-labs/FLUX.1-schnell")

    def is_available(self) -> bool:
        return bool(self._api_key)

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("SILICONFLOW_API_KEY not set")
        payload = {
            "model": self._model,
            "prompt": prompt,
            "image_size": f"{width}x{height}",
            "batch_size": 1,
            "seed": seed,
        }
        req = urllib.request.Request(
            self._base_url, data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
        b64 = (
            body.get("data", [{}])[0].get("b64_json")
            or body.get("images", [None])[0]
            or body.get("output", [None])[0]
        )
        if b64:
            raw = base64.b64decode(b64) if isinstance(b64, str) else b64
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(raw)
            return output_path
        url = body.get("data", [{}])[0].get("url")
        if url:
            with urllib.request.urlopen(url, timeout=60) as r:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(r.read())
            return output_path
        raise RuntimeError(f"SiliconFlow unexpected response: {list(body)[:5]}")


# ═══════════════════════════════════════════════════════════════════════ #
# Hugging Face serverless
# ═══════════════════════════════════════════════════════════════════════ #


class HFServerlessProvider(ImageGenProvider):
    """Hugging Face Inference API (serverless) image generation."""

    name = "hf_serverless"

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None):
        self._api_key = api_key or os.environ.get("HF_TOKEN", "")
        self._model = model or get_config(
            "image_gen.hf.model", "black-forest-labs/FLUX.1-schnell"
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("HF_TOKEN not set")
        url = f"https://router.huggingface.co/hf-inference/models/{self._model}"
        payload = {"inputs": prompt, "parameters": {"width": width, "height": height}}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(raw)
        return output_path


# ═══════════════════════════════════════════════════════════════════════ #
# Pollinations (free, keyless image API)
# ═══════════════════════════════════════════════════════════════════════ #


class PollinationsProvider(ImageGenProvider):
    """Pollinations.ai — free, keyless image generation (GET endpoint).

    Endpoint: https://image.pollinations.ai/prompt/<prompt>?width=&height=&seed=
    No API key required.  Supports model selection via ``model`` query param
    (default FLUX-based).  Verified working 2026-08 (1.7s / 1024x576 JPEG).
    """

    name = "pollinations"

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url or get_config(
            "image_gen.pollinations.base_url",
            "https://image.pollinations.ai/prompt",
        )

    def is_available(self) -> bool:
        return True  # keyless

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        import urllib.parse
        params = {"width": width, "height": height, "nologo": "true"}
        if seed is not None:
            params["seed"] = seed
        url = f"{self._base_url}/{urllib.parse.quote(prompt)}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
        if not raw or raw[:3] == b"<ht":
            raise RuntimeError(f"Pollinations returned non-image response ({len(raw)} bytes)")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(raw)
        return output_path


# ═══════════════════════════════════════════════════════════════════════ #
# Factory
# ═══════════════════════════════════════════════════════════════════════ #

_PROVIDERS: dict[str, type[ImageGenProvider]] = {
    "nvidia_nim": NvidiaNimProvider,
    "siliconflow": SiliconFlowProvider,
    "hf_serverless": HFServerlessProvider,
    "pollinations": PollinationsProvider,
}


class ImageGenFactory:
    """Creates image-gen providers; resolves the configured default."""

    def __init__(self):
        self._instances: dict[str, ImageGenProvider] = {}

    def get(self, name: str) -> ImageGenProvider:
        if name not in _PROVIDERS:
            raise ValueError(f"Unknown image-gen provider: {name}")
        if name not in self._instances:
            self._instances[name] = _PROVIDERS[name]()
        return self._instances[name]

    def available(self) -> list[ImageGenProvider]:
        """Providers with credentials present."""
        return [self.get(n) for n in _PROVIDERS if self.get(n).is_available()]

    def default(self) -> Optional[ImageGenProvider]:
        """Configured default, or first available provider."""
        cfg = get_config("image_gen.default_provider", "")
        if cfg and cfg in _PROVIDERS:
            p = self.get(cfg)
            if p.is_available():
                return p
        avail = self.available()
        return avail[0] if avail else None


# ═══════════════════════════════════════════════════════════════════════ #
# CLI
# ═══════════════════════════════════════════════════════════════════════ #

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="A golden phonograph record floating in deep space, cinematic")
    ap.add_argument("--out", default="cache/generated/test_ai.png")
    ap.add_argument("--provider", default=None)
    args = ap.parse_args()

    factory = ImageGenFactory()
    provider = factory.get(args.provider) if args.provider else factory.default()
    if provider is None:
        print("No image-gen provider available (no API keys).")
        sys.exit(1)
    print(f"Provider: {provider.name}")
    t0 = time.time()
    path = provider.generate(args.prompt, args.out)
    print(f"Generated in {time.time()-t0:.1f}s → {path}")
