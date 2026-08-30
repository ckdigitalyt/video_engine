"""wan.py — Wan 2.2 image-to-video provider (directive §11).

Free path: HF ZeroGPU Gradio Spaces running Wan 2.2 I2V. The default Space
(hf_video.default_space in configs/providers.yaml) was verified live
2026-08-30: RUNNING, Gradio 6, endpoint ``/generate_video`` taking
(input_image, last_image, prompt, steps, negative_prompt, duration_seconds,
guidance_scale, guidance_scale_2, seed, randomize_seed, quality, scheduler,
flow_shift, frame_multiplier, safe_mode, video_component).

Override the Space with ``HF_VIDEO_SPACE``; endpoint/params are discovered
from /gradio_api/info at call time. Falls back cleanly when the Space is
asleep/queued-out so the broker can degrade down the chain (§24).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from engine.broker.cache import BrokerCache, broker_cache_key
from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)
from engine.broker.providers.hf_zerogpu import HFZeroGPUClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROVIDERS_YAML = PROJECT_ROOT / "configs" / "providers.yaml"

DEFAULT_SPACE = "Saravutw/WAN2.2_I2V_LIGHTNING_4-8step_custom"
DEFAULT_ENDPOINT = "generate_video"


def _video_provider_config() -> dict[str, Any]:
    try:
        with open(PROVIDERS_YAML, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return (data.get("hf_video") or {}).get("wan22_i2v") or {}
    except Exception:  # config missing → defaults only
        return {}


class Wan22I2VProvider(MediaProvider):
    """Wan 2.2 image-to-video via HF ZeroGPU Space (free tier)."""

    kind = "image_to_video"

    def __init__(self, cache: BrokerCache | None = None,
                 space_id: str | None = None,
                 endpoint: str | None = None,
                 token: str | None = None) -> None:
        cfg = _video_provider_config()
        self.cache = cache or BrokerCache()
        self.space_id = (space_id or os.environ.get("HF_VIDEO_SPACE")
                         or cfg.get("space_id") or DEFAULT_SPACE)
        self.endpoint_name = (endpoint or cfg.get("endpoint")
                              or DEFAULT_ENDPOINT)
        self._client = HFZeroGPUClient(self.space_id,
                                       endpoint_name=self.endpoint_name,
                                       token=token)
        self._enabled_env = bool(os.environ.get("HF_TOKEN", ""))

    id = "wan22_i2v"

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind,
            models=["Wan2.2-I2V-A14B-Lightning"],
            enabled=self._enabled_env, priority=20,
            notes=f"Wan 2.2 I2V via HF ZeroGPU Space {self.space_id}",
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
                       duration: float = 4.0, seed: int = 0,
                       aspect: str = "16:9", **kw: Any) -> BrokerResult:
        if not self._enabled_env:
            raise ProviderError("wan22_i2v: HF_TOKEN not set")
        image = Path(image)
        if not image.exists():
            raise ProviderError(f"wan22_i2v: input image missing: {image}")
        try:
            [server_path] = self._client.upload_files([str(image)])
        except ProviderError:
            raise
        fd = HFZeroGPUClient.file_data(server_path)
        result = self._client.generate(
            [
                fd,                    # input_image
                fd,                    # last_image (same frame → free motion)
                prompt or "high quality, cinematic motion",
                4,                     # steps (lightning 4-8)
                "blurry, low quality, deformed, watermark",
                float(duration),       # duration_seconds
                1,                     # guidance_scale
                1,                     # guidance_scale_2
                int(seed) if seed else 42,
                False,                 # randomize_seed → deterministic
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
                      "model": "Wan2.2-I2V", "seed": seed},
        )
