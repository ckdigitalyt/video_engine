"""ltx.py — LTX video provider (directive §11).

Free path: the official Lightricks ZeroGPU Spaces. Default Space
``Lightricks/ltx-2-distilled`` verified live 2026-08-30: RUNNING, endpoint
``/generate_video`` (input_image, prompt, duration, enhance_prompt, seed,
randomize_seed, height, width). Fallback Space: ``Lightricks/ltx-video-distilled``
(endpoint ``/image_to_video``, older LTX-Video distilled).

Alternative free path if ZeroGPU quota is exhausted: WavespeedAI/LTX-Video
on fal.ai requires credits (paid) — NOT enabled.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from engine.broker.cache import BrokerCache, broker_cache_key
from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)
from engine.broker.providers.hf_zerogpu import HFZeroGPUClient
from engine.broker.providers.wan import _video_provider_config

DEFAULT_SPACE = "Lightricks/ltx-2-distilled"
DEFAULT_ENDPOINT = "generate_video"


class LTXVideoProvider(MediaProvider):
    """LTX image-to-video via official Lightricks HF ZeroGPU Space."""

    id = "ltx_video"
    kind = "image_to_video"

    def __init__(self, cache: BrokerCache | None = None,
                 space_id: str | None = None,
                 endpoint: str | None = None,
                 token: str | None = None) -> None:
        cfg = (_video_provider_config() or {}).get("ltx") or {}
        self.cache = cache or BrokerCache()
        self.space_id = (space_id or os.environ.get("HF_LTX_SPACE")
                         or cfg.get("space_id") or DEFAULT_SPACE)
        self.endpoint_name = (endpoint or cfg.get("endpoint")
                              or DEFAULT_ENDPOINT)
        self._client = HFZeroGPUClient(self.space_id,
                                       endpoint_name=self.endpoint_name,
                                       token=token)
        self._enabled_env = bool(os.environ.get("HF_TOKEN", ""))

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=["LTX-2-distilled"],
            enabled=self._enabled_env, priority=30,
            notes=f"LTX via official ZeroGPU Space {self.space_id}",
        )

    def health_check(self) -> bool:
        if not self._enabled_env:
            return False
        try:
            self._client.discover(verbose=False)
            return True
        except ProviderError:
            return False

    def image_to_video(self, image: str | Path, prompt: str, *,
                       duration: float = 3.0, seed: int = 0,
                       aspect: str = "16:9", **kw: Any) -> BrokerResult:
        if not self._enabled_env:
            raise ProviderError("ltx_video: HF_TOKEN not set")
        image = Path(image)
        if not image.exists():
            raise ProviderError(f"ltx_video: input image missing: {image}")
        [server_path] = self._client.upload_files([str(image)])
        fd = HFZeroGPUClient.file_data(server_path)
        result = self._client.generate(
            [
                fd,                # input_image
                prompt or "cinematic motion, high quality",
                float(duration),   # duration (seconds)
                False,             # enhance_prompt (keep deterministic)
                int(seed) if seed else 42,
                False,             # randomize_seed
                512,               # height (small = fast + low quota use)
                896,               # width (~16:9)
            ],
            timeout=600,
        )
        [data] = self._client.download_result(result)
        key = broker_cache_key(prompt=prompt, input_path=image,
                               model=self.space_id, duration=duration,
                               seed=seed, aspect=aspect,
                               op="image_to_video", renderer_version="w2")
        path = self.cache.store_bytes(key, data, ext="mp4")
        return BrokerResult(
            path=path, provider=self.id, kind="image_to_video",
            metadata={"space": self.space_id, "endpoint": self.endpoint_name,
                      "model": "LTX-2-distilled", "seed": seed},
        )
