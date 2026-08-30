"""broker.py — AI Media Broker (directive §9/§11/§12).

Single entry point for ALL external AI media. The pipeline asks for
``generate_high_value_hero_shot(...)`` — never for a specific model. Providers
are tried in priority order per media kind with cache-first semantics and
ordered failover.

Wave-1 working clients: ZAI GLM (vision QA), Pexels/Pixabay (stock).
Wave-2 clients: SiliconFlow/NVIDIA NIM (image), MiniMax H3 / Wan 2.2 / LTX /
HF ZeroGPU Spaces (video) — registered here already so failover order is
final; unimplemented providers raise ProviderError internally and are skipped.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from engine.broker.cache import BrokerCache, broker_cache_key
from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)
from engine.broker.providers.archival import (
    ARCHIVAL_PROVIDERS,
    InternetArchiveProvider,
    NasaImagesProvider,
    WikimediaCommonsProvider,
)
from engine.broker.providers.hf_zerogpu import HFZeroGPUClient
from engine.broker.providers.imageapi import (
    NvidiaNimImageProvider,
    SiliconFlowImageProvider,
)
from engine.broker.providers.minimax import MiniMaxH3Provider
from engine.broker.providers.stock import PexelsStockProvider, PixabayStockProvider
from engine.broker.providers.zai import ZaiVisionProvider
from engine.broker.zerogpu_scheduler import (
    ZeroGPUI2VProvider,
    ZeroGPUScheduler,
    ZeroGPUVideoProvider,
)

logger = logging.getLogger(__name__)

# Provider factories per kind, in failover order. A factory returns None when
# the provider isn't configured (missing key) so the broker skips it cleanly.
# Wave-2 providers are listed where they will slot in (registration ≠ body).
PROVIDER_FACTORIES: dict[str, list[tuple[str, Callable[[], MediaProvider | None]]]] = {
    "image": [
        ("siliconflow", lambda: _configured(SiliconFlowImageProvider)),
        ("nvidia_nim", lambda: _configured(NvidiaNimImageProvider)),
        ("hf_zerogpu", lambda: _hf_space_provider("image")),
    ],
    # T2V chain (§7): paid MiniMax first when a key + spend approval exist,
    # then the quota-aware multi-Space ZeroGPU scheduler (§8).
    "video": [
        ("minimax_h3", lambda: _configured(MiniMaxH3Provider)),
        ("zerogpu_t2v", lambda: None),  # built once below (shared scheduler)
    ],
    # I2V chain (§7 HERO fallback): quota-aware scheduler (multi-Space,
    # Wan+LTX) first — it classifies quota exhaustion account-wide — then the
    # single-Space Wave-2 providers as belt-and-braces fallback.
    "image_to_video": [
        ("wan22_i2v", lambda: _configured_wan()),
        ("ltx_video", lambda: _configured_ltx()),
        ("zerogpu_i2v", lambda: None),  # built once below (shared scheduler)
    ],
    "stock": [
        ("pexels", lambda: _configured(PexelsStockProvider)),
        ("pixabay", lambda: _configured(PixabayStockProvider)),
    ],
    "archival": [
        ("nasa_images", lambda: _configured(NasaImagesProvider)),
        ("wikimedia_commons", lambda: _configured(WikimediaCommonsProvider)),
        ("internet_archive", lambda: _configured(InternetArchiveProvider)),
    ],
    "vision": [
        ("zai", lambda: _configured(ZaiVisionProvider)),
    ],
}


def _configured(cls: type[MediaProvider], *args: Any, **kw: Any) -> MediaProvider | None:
    try:
        provider = cls(*args, **kw)
    except Exception:  # never let one provider break broker construction
        logger.debug("provider %s failed to construct", cls.__name__)
        return None
    return provider if provider.capabilities().enabled else None


def _configured_wan() -> MediaProvider | None:
    from engine.broker.providers.wan import Wan22I2VProvider

    return _configured(Wan22I2VProvider)


def _configured_ltx() -> MediaProvider | None:
    from engine.broker.providers.ltx import LTXVideoProvider

    return _configured(LTXVideoProvider)


def _hf_space_provider(kind: str) -> MediaProvider | None:
    """Wave-2 hook: build an HFZeroGPUClient from env (HF_VIDEO_SPACE /
    HF_IMAGE_SPACE). Returns None until those are configured."""
    space = os.environ.get("HF_VIDEO_SPACE" if kind == "video" else "HF_IMAGE_SPACE", "")
    if not space:
        return None

    class _HFSpaceProvider(HFZeroGPUClient, MediaProvider):
        @property
        def id(self) -> str:  # type: ignore[override]
            return f"hf_zerogpu::{self.space_id}"

        def capabilities(self) -> ProviderDescriptor:  # type: ignore[override]
            return ProviderDescriptor(
                id=self.id, kind=kind, enabled=True, priority=20,
                notes=f"Gradio Space {self.space_id}",
            )

        def health_check(self) -> bool:
            try:
                self.discover(verbose=False)
                return True
            except ProviderError:
                return False

        def generate_image(self, prompt: str, **kw: Any) -> BrokerResult:  # type: ignore[override]
            result = self.generate([prompt])
            data = self.download_result(result)[0]
            path = BrokerCache().store_bytes(
                broker_cache_key(prompt=prompt, model=self.space_id, op="image"),
                data, ext="png",
            )
            return BrokerResult(path=path, provider=self.id, kind="image")

        def generate_video(self, prompt: str, **kw: Any) -> BrokerResult:  # type: ignore[override]
            result = self.generate([prompt])
            data = self.download_result(result)[0]
            path = BrokerCache().store_bytes(
                broker_cache_key(prompt=prompt, model=self.space_id, op="video"),
                data, ext="mp4",
            )
            return BrokerResult(path=path, provider=self.id, kind="video")

    return _configured(_HFSpaceProvider, space)


@dataclass
class HeroShotRequest:
    """What the planner hands to generate_high_value_hero_shot (§9)."""

    shot_id: str
    prompt: str
    duration_sec: float
    aspect: str = "16:9"
    seed: int = 0
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MediaBroker:
    """Facade over all providers; the ONLY object the pipeline touches."""

    def __init__(self, cache: BrokerCache | None = None,
                 providers: dict[str, MediaProvider] | None = None) -> None:
        self.cache = cache or BrokerCache()
        if providers is not None:
            self._providers = providers
        else:
            self._providers = self._build_default_providers()

    @staticmethod
    def _build_default_providers() -> dict[str, MediaProvider]:
        out: dict[str, MediaProvider] = {}
        # One shared scheduler → one shared quota ledger across T2V and I2V
        # (ZeroGPU quota is ACCOUNT-level, §8).
        scheduler: ZeroGPUScheduler | None = None
        if os.environ.get("HF_TOKEN"):
            try:
                scheduler = ZeroGPUScheduler()
            except Exception:  # never let scheduler construction break broker
                scheduler = None
        for factories in PROVIDER_FACTORIES.values():
            for name, factory in factories:
                try:
                    provider = factory()
                except Exception:
                    provider = None
                if provider is not None and name not in out:
                    out[name] = provider
        if scheduler is not None:
            out["zerogpu_t2v"] = ZeroGPUVideoProvider(scheduler)
            out["zerogpu_i2v"] = ZeroGPUI2VProvider(scheduler)
        return out

    @property
    def scheduler(self) -> ZeroGPUScheduler | None:
        """The shared quota-aware ZeroGPU scheduler, if configured (§8)."""
        provider = self._providers.get("zerogpu_t2v")
        return provider.scheduler if isinstance(provider, ZeroGPUVideoProvider) else None

    # ── Introspection (§9) ───────────────────────────────────────────────

    def get_capabilities(self) -> list[ProviderDescriptor]:
        return [p.capabilities() for p in self._providers.values()]

    def check_provider_health(self) -> dict[str, bool]:
        return {pid: p.health_check() for pid, p in self._providers.items()}

    def get_quota(self) -> dict[str, Any | None]:
        return {pid: p.quota() for pid, p in self._providers.items()}

    # ── Generation ops with cache-first + failover ───────────────────────

    def _run(self, kind: str, op_name: str, cache_key: str, ext: str,
             invoke: Callable[[MediaProvider], BrokerResult],
             input_path: str | Path | None = None, **cache_kw: Any) -> BrokerResult:
        # Cache-first: identical (prompt, model, seed, input, style, duration,
        # aspect, renderer_version) → same key → zero network calls (§25).
        hit = self.cache.get(cache_key, ext=ext)
        if hit:
            return BrokerResult(path=hit, provider="cache", kind=kind, cached=True,
                                metadata=self.cache.load_metadata(cache_key) or {})
        candidates = [p for p in self._providers.values() if p.kind == kind]
        errors: list[str] = []
        for provider in candidates:
            op = getattr(provider, op_name, None)
            if op is None:
                continue
            try:
                result = invoke(provider)
                self.cache.store_metadata(cache_key, {
                    "provider": provider.id, "kind": kind, **cache_kw,
                })
                # normalise: ensure artifact lives under the deterministic key
                stored = self.cache.store(cache_key, result.path, ext=ext)
                return BrokerResult(path=stored, provider=provider.id, kind=kind,
                                    cached=False, metadata=result.metadata)
            except ProviderError as exc:
                errors.append(f"{provider.id}: {exc}")
                logger.warning("broker failover after %s: %s", provider.id, exc)
            except Exception as exc:  # noqa: BLE001 — §24: failover never collapses
                # Providers raise raw transport errors (urllib HTTPError etc.),
                # not just ProviderError. Before this fix a SiliconFlow 401
                # propagated and pre-empted failover to working providers
                # (observed live 2026-08-30). HTTPError ⊂ URLError ⊂ OSError.
                errors.append(f"{provider.id}: {type(exc).__name__}: {exc}")
                logger.warning("broker failover after %s: %s: %s",
                               provider.id, type(exc).__name__, exc)
        raise ProviderError(
            f"broker: no {kind} provider succeeded for {op_name}; "
            f"attempts: {'; '.join(errors) or 'none configured'}"
        )

    @staticmethod
    def _attempt_records(result: BrokerResult) -> dict[str, Any]:
        """Pull the §7 per-attempt fields off a scheduler result, if any."""
        attempts = result.metadata.get("attempts")
        return {"attempts": attempts} if attempts else {}

    def generate_image(self, prompt: str, *, style: Any = None,
                       aspect: str = "16:9", seed: int = 0,
                       model: str = "", renderer_version: str = "w1") -> BrokerResult:
        key = broker_cache_key(
            prompt=prompt, model=model, seed=seed, style=style, aspect=aspect,
            renderer_version=renderer_version, op="generate_image",
        )
        return self._run(
            "image", "generate_image", key, "png",
            lambda p: p.generate_image(prompt, style=style, aspect=aspect, seed=seed),
            prompt=prompt, model=model, seed=seed, aspect=aspect,
        )

    def generate_video(self, prompt: str, *, duration: float = 5.0,
                       aspect: str = "16:9", seed: int = 0, style: Any = None,
                       model: str = "", renderer_version: str = "w1") -> BrokerResult:
        key = broker_cache_key(
            prompt=prompt, model=model, seed=seed, style=style, duration=duration,
            aspect=aspect, renderer_version=renderer_version, op="generate_video",
        )
        return self._run(
            "video", "generate_video", key, "mp4",
            lambda p: p.generate_video(prompt, duration=duration, aspect=aspect,
                                       seed=seed),
            prompt=prompt, model=model, seed=seed, duration=duration, aspect=aspect,
        )

    def image_to_video(self, image: str | Path, prompt: str, *,
                       duration: float = 5.0, aspect: str = "16:9",
                       seed: int = 0, style: Any = None,
                       renderer_version: str = "w1") -> BrokerResult:
        key = broker_cache_key(
            prompt=prompt, input_path=image, seed=seed, style=style,
            duration=duration, aspect=aspect, renderer_version=renderer_version,
            op="image_to_video",
        )
        return self._run(
            "image_to_video", "image_to_video", key, "mp4",
            lambda p: p.image_to_video(image, prompt, duration=duration,
                                       aspect=aspect, seed=seed),
            prompt=prompt, input_path=image, duration=duration, aspect=aspect,
        )

    def edit_image(self, image: str | Path, instruction: str, *,
                   style: Any = None, seed: int = 0,
                   renderer_version: str = "w1") -> BrokerResult:
        key = broker_cache_key(
            prompt=instruction, input_path=image, seed=seed, style=style,
            renderer_version=renderer_version, op="edit_image",
        )
        return self._run(
            "image", "edit_image", key, "png",
            lambda p: p.edit_image(image, instruction, seed=seed),
            prompt=instruction, input_path=image, seed=seed,
        )

    # ── Stock (§13) ──────────────────────────────────────────────────────

    def search_stock(self, query: str, *, per_page: int = 5,
                     kind: str = "stock") -> list[dict[str, Any]]:
        """Search stock/archival providers in priority order; returns raw
        results with the source provider stamped on each entry."""
        results: list[dict[str, Any]] = []
        for provider in self._providers.values():
            if provider.kind != kind:
                continue
            try:
                for asset in provider.search(query, per_page=per_page):
                    asset["_broker_provider"] = provider.id
                    results.append(asset)
            except ProviderError as exc:
                logger.warning("%s search failed on %s: %s", kind,
                               provider.id, exc)
        if not results:
            raise ProviderError(
                f"broker: no {kind} provider succeeded for {query!r}")
        return results

    def download_stock(self, asset: dict[str, Any]) -> BrokerResult:
        pid = asset.get("_broker_provider")
        provider = self._providers.get(pid)
        if provider is None:
            raise ProviderError(f"broker: unknown stock provider {pid!r}")
        return provider.download(asset)

    # Archival sources are stock semantics with a stricter license gate;
    # dedicated accessors keep the §13 gate visible at call sites.

    def search_archival(self, query: str, *, per_page: int = 5) -> list[dict[str, Any]]:
        return self.search_stock(query, per_page=per_page, kind="archival")

    def download_archival(self, asset: dict[str, Any]) -> BrokerResult:
        return self.download_stock(asset)

    # ── Hero shots (§2C, §9, §26) ────────────────────────────────────────

    def generate_high_value_hero_shot(self, request: HeroShotRequest) -> BrokerResult:
        """High-value narrative moment: full AI video first, then the §24
        degradation chain handled by the renderer router upstream. The broker
        tries AI video, then AI image (for AI_IMAGE+MOTION fallback)."""
        try:
            return self.generate_video(
                request.prompt,
                duration=request.duration_sec,
                aspect=request.aspect,
                seed=request.seed,
                style=request.style,
            )
        except ProviderError as video_exc:
            logger.warning(
                "hero shot %s: AI video unavailable (%s) — degrading to AI image",
                request.shot_id, video_exc,
            )
        image = self.generate_image(
            request.prompt,
            style=request.style,
            aspect=request.aspect,
            seed=request.seed,
        )
        image.metadata["degraded_from"] = "AI_VIDEO"
        return image
