"""ltx.py — LTX video provider (directive §10/§11).

Free path: the official Lightricks ZeroGPU Spaces. Default Space
``Lightricks/ltx-video-distilled`` verified LIVE 2026-08-30: RUNNING,
endpoints ``/text_to_video`` and ``/image_to_video`` (13 UI params incl.
mode/duration_ui/seed_ui). A live image-to-video generation was completed
during Wave 2 (4.0s 704x512 mp4 in ~12s queue-to-result).

Parameter names/order taken from the Space's live ``/gradio_api/info``:
  /text_to_video(prompt, negative_prompt, input_image_filepath:str,
    input_video_filepath:str, height_ui, width_ui,
    mode:'text-to-video', duration_ui, ui_frames_to_use, seed_ui,
    randomize_seed, ui_guidance_scale, improve_texture_flag)
  /image_to_video(prompt, negative_prompt, input_image_filepath:FileData,
    input_video_filepath:str, height_ui, width_ui,
    mode:'image-to-video', ...same tail)
T2V passes ``""`` for the two str-typed file inputs.

Note: ``Lightricks/ltx-2-distilled`` (newer UI) rejects API calls with a
null error event — kept as a documented fallback candidate only (it is
covered by the quota-aware scheduler, which retries on different Spaces).

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

DEFAULT_SPACE = "Lightricks/ltx-video-distilled"
DEFAULT_I2V_ENDPOINT = "image_to_video"
DEFAULT_T2V_ENDPOINT = "text_to_video"


class LTXVideoProvider(MediaProvider):
    """LTX image-to-video + text-to-video via official Lightricks HF Space."""

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
        self.endpoint_name = (endpoint or cfg.get("i2v_endpoint")
                              or DEFAULT_I2V_ENDPOINT)
        self._client = HFZeroGPUClient(self.space_id,
                                       endpoint_name=self.endpoint_name,
                                       token=token)
        self._enabled_env = bool(os.environ.get("HF_TOKEN", ""))

    def capabilities(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=["LTX-Video-Distilled"],
            enabled=self._enabled_env, priority=30,
            notes=f"LTX via official ZeroGPU Space {self.space_id} "
                  f"(live-verified 2026-08-30)",
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
                prompt or "cinematic motion, high quality",
                "blurry, low quality, deformed, watermark",
                fd,                 # input_image_filepath
                None,               # input_video_filepath
                512,                # height_ui (small = fast + low quota)
                704,                # width_ui (~16:9-ish for 512)
                "image-to-video",   # mode
                float(duration),    # duration_ui (seconds)
                9.0,                # ui_frames_to_use
                int(seed) if seed else 42,
                False,              # randomize_seed → deterministic
                3.0,                # ui_guidance_scale
                False,              # improve_texture_flag (faster)
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
                      "model": "LTX-Video-Distilled", "seed": seed},
        )

    def generate_video(self, prompt: str, *, duration: float = 4.0,
                       seed: int = 0, aspect: str = "16:9",
                       **kw: Any) -> BrokerResult:
        """T2V via /text_to_video (§10: model-appropriate structured prompt)."""
        if not self._enabled_env:
            raise ProviderError("ltx_video: HF_TOKEN not set")
        result = self._client.generate(
            [
                prompt or "cinematic motion, high quality",
                "blurry, low quality, deformed, distorted, watermark, "
                "static, motionless",
                "",                 # input_image_filepath (str, empty for T2V)
                "",                 # input_video_filepath
                512,                # height_ui (small = fast + low quota)
                704,                # width_ui
                "text-to-video",    # mode
                float(duration),    # duration_ui (seconds)
                float(duration) + 5.0,  # ui_frames_to_use
                int(seed) if seed else 42,
                False,              # randomize_seed → deterministic
                3.0,                # ui_guidance_scale
                False,              # improve_texture_flag (faster)
            ],
            endpoint_name="text_to_video",
            timeout=600,
        )
        [data] = self._client.download_result(result)
        key = broker_cache_key(prompt=prompt, model=self.space_id,
                               duration=duration, seed=seed, aspect=aspect,
                               op="generate_video", renderer_version="v4")
        path = self.cache.store_bytes(key, data, ext="mp4")
        return BrokerResult(
            path=path, provider=self.id, kind="video",
            metadata={"space": self.space_id, "endpoint": "text_to_video",
                      "model": "LTX-Video-Distilled", "seed": seed},
        )
