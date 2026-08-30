"""zerogpu_scheduler.py — Quota-aware ZeroGPU scheduler (directive §8).

Discovers candidate I2V/T2V Gradio Spaces dynamically (configurable list,
probed via ``/gradio_api/info`` — nothing is hardcoded to one Space),
classifies every failure through the §7 taxonomy, and enforces account-level
quota discipline:

* after a QUOTA_EXHAUSTED signal, the session ledger trips and *all* further
  ZeroGPU attempts are refused (quota is account-wide — other Spaces WILL
  refuse too; retrying only burns time and risk);
* "space error: null" is quota-suspicious: after N null errors across
  DISTINCT spaces the session marks the account as *suspected* exhausted;
* Spaces known-good this session are preferred; failures rotate to the next
  Space (retry-on-different-Space);
* every attempt is recorded with the §7 fields (attempted_provider, space_id,
  failure_reason, fallback_reason);
* successful jobs are cached broker-side (unchanged cache-first semantics).

Payload adapters per Space template keep parameter names correct per
``/gradio_api/info`` (verified live 2026-08-30):
* ``ltx_distilled`` — Lightricks/ltx-video-distilled: /text_to_video,
  /image_to_video (13 positional params, mode literal);
* ``ltx2_unified``  — Lightricks/ltx-2-distilled: /generate_video
  (input_image FileData nullable → T2V when None);
* ``wan_i2v_16p``   — Saravutw/WAN2.2_I2V_LIGHTNING_4-8step_custom:
  /generate_video (16 positional params);
* ``wan_fast_b64``  — prithivMLmods/Wan2.2-Fast: /generate_video with the
  image inline as base64 (no upload round-trip).
"""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from engine.broker.cache import BrokerCache, broker_cache_key
from engine.broker.failures import (
    FailureClass,
    SpaceAttempt,
    classify_failure,
    parse_quota_remaining,
)
from engine.broker.providers.base import (
    BrokerResult,
    MediaProvider,
    ProviderDescriptor,
    ProviderError,
)
from engine.broker.providers.hf_zerogpu import HFZeroGPUClient, SpaceInfo

logger = logging.getLogger(__name__)

DEFAULT_NEGATIVE = "blurry, low quality, deformed, watermark, text overlay"

DEFAULT_LTX_NEGATIVE = (
    "blurry, low quality, deformed, distorted, disfigured, bad anatomy, "
    "watermark, text, static, motionless"
)


# ── Space candidate + payload adapters ───────────────────────────────────


@dataclass
class SpaceCandidate:
    space_id: str
    model: str
    template: str  # adapter name below
    t2v_endpoint: str | None = None
    i2v_endpoint: str | None = None
    priority: int = 100  # lower = tried first (within known-good reorder)


@dataclass
class GenRequest:
    kind: str  # t2v | i2v
    prompt: str
    duration: float = 4.0
    seed: int = 0
    aspect: str = "16:9"
    negative: str = ""
    image_path: str | Path | None = None  # i2v local file
    server_path: str | None = None  # i2v uploaded Gradio path


def _ltx_dims(duration: float) -> tuple[int, int]:
    # Small/fast = low quota burn (§8: spend quota wisely).
    return 512, 704  # (height, width)


def _args_ltx_distilled(req: GenRequest, client: HFZeroGPUClient) -> list[Any]:
    h, w = _ltx_dims(req.duration)
    if req.kind == "t2v":
        # /text_to_video(prompt, negative_prompt, input_image_filepath:str,
        #   input_video_filepath:str, height_ui, width_ui, mode,
        #   duration_ui, ui_frames_to_use, seed_ui, randomize_seed,
        #   ui_guidance_scale, improve_texture_flag)
        return [
            req.prompt, req.negative or DEFAULT_LTX_NEGATIVE,
            "", "", h, w,
            "text-to-video", float(req.duration), float(req.duration) + 5.0,
            int(req.seed) if req.seed else 42, False, 3.0, False,
        ]
    if req.server_path is None:
        raise ProviderError("ltx_distilled i2v requires an uploaded image")
    fd = HFZeroGPUClient.file_data(req.server_path)
    # /image_to_video(prompt, negative_prompt, input_image_filepath:FileData, ...)
    return [
        req.prompt, req.negative or DEFAULT_LTX_NEGATIVE,
        fd, "", h, w,
        "image-to-video", float(req.duration), float(req.duration) + 5.0,
        int(req.seed) if req.seed else 42, False, 3.0, False,
    ]


def _args_ltx2_unified(req: GenRequest, client: HFZeroGPUClient) -> list[Any]:
    h, w = _ltx_dims(req.duration)
    fd = HFZeroGPUClient.file_data(req.server_path) if req.server_path else None
    # /generate_video(input_image:FileData|null, prompt, duration,
    #   enhance_prompt, seed, randomize_seed, height, width)
    return [
        fd, req.prompt, float(req.duration), False,
        int(req.seed) if req.seed else 42, False, h, w,
    ]


def _args_wan_i2v_16p(req: GenRequest, client: HFZeroGPUClient) -> list[Any]:
    if req.server_path is None:
        raise ProviderError("wan_i2v_16p requires an uploaded image")
    fd = HFZeroGPUClient.file_data(req.server_path)
    # /generate_video(input_image, last_image, prompt, steps, negative_prompt,
    #   duration_seconds, guidance_scale, guidance_scale_2, seed,
    #   randomize_seed, quality, scheduler, flow_shift, frame_multiplier,
    #   safe_mode, video_component)
    return [
        fd, fd, req.prompt, 4, req.negative or DEFAULT_NEGATIVE,
        float(req.duration), 1, 1,
        int(req.seed) if req.seed else 42, False, 5,
        "UniPCMultistep", 3.0, "16", False, True,
    ]


def _args_wan_fast_b64(req: GenRequest, client: HFZeroGPUClient) -> list[Any]:
    if req.image_path is None:
        raise ProviderError("wan_fast_b64 requires a local image")
    raw = Path(req.image_path).read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"
    # /generate_video(image_b64:str, prompt, steps, negative_prompt,
    #   duration_seconds, guidance_scale, guidance_scale_2, seed,
    #   randomize_seed)
    return [
        data_uri, req.prompt, 4, req.negative or DEFAULT_NEGATIVE,
        float(req.duration), 1.0, 1.0,
        int(req.seed) if req.seed else 42, False,
    ]


ADAPTERS: dict[str, Callable[[GenRequest, HFZeroGPUClient], list[Any]]] = {
    "ltx_distilled": _args_ltx_distilled,
    "ltx2_unified": _args_ltx2_unified,
    "wan_i2v_16p": _args_wan_i2v_16p,
    "wan_fast_b64": _args_wan_fast_b64,
}


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROVIDERS_YAML = PROJECT_ROOT / "configs" / "providers.yaml"


def _load_candidate_spaces_from_config() -> list[SpaceCandidate] | None:
    try:
        import yaml

        with open(PROVIDERS_YAML, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        raw = ((data.get("hf_video") or {}).get("candidate_spaces")) or []
        out = [
            SpaceCandidate(
                space_id=item["space_id"],
                model=item.get("model", item["space_id"]),
                template=item.get("template", "ltx_distilled"),
                t2v_endpoint=item.get("t2v_endpoint"),
                i2v_endpoint=item.get("i2v_endpoint"),
                priority=int(item.get("priority", 100)),
            )
            for item in raw
            if item.get("space_id")
        ]
        return out or None
    except Exception:  # config missing/malformed → built-in defaults
        return None


def default_candidates() -> list[SpaceCandidate]:
    """Candidate pool: configs/providers.yaml hf_video.candidate_spaces when
    present, else the built-in pool (probed live 2026-08-30, all RUNNING)."""
    cfg = _load_candidate_spaces_from_config()
    if cfg:
        return cfg
    return [
        SpaceCandidate(
            space_id="Lightricks/ltx-video-distilled", model="LTX-Video-Distilled",
            template="ltx_distilled",
            t2v_endpoint="text_to_video", i2v_endpoint="image_to_video",
            priority=10,
        ),
        SpaceCandidate(
            space_id="Lightricks/ltx-2-distilled", model="LTX-2-Distilled",
            template="ltx2_unified",
            t2v_endpoint="generate_video", i2v_endpoint="generate_video",
            priority=20,
        ),
        SpaceCandidate(
            space_id="Saravutw/WAN2.2_I2V_LIGHTNING_4-8step_custom",
            model="Wan2.2-I2V-A14B-Lightning", template="wan_i2v_16p",
            i2v_endpoint="generate_video", priority=20,
        ),
        SpaceCandidate(
            space_id="prithivMLmods/Wan2.2-Fast", model="Wan2.2-Fast",
            template="wan_fast_b64",
            i2v_endpoint="generate_video", priority=60,
        ),
    ]


# ── Session quota ledger ─────────────────────────────────────────────────


def _config_null_error_stop_after(default: int = 2) -> int:
    try:
        import yaml

        with open(PROVIDERS_YAML, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return int(((data.get("hf_video") or {}).get("scheduler") or {}).get(
            "null_error_stop_after", default))
    except Exception:
        return default


class QuotaLedger:
    """Account-level ZeroGPU quota state for one scheduler session.

    ZeroGPU free accounts get ~5 GPU-min/day; quota is enforced per ACCOUNT,
    not per Space. A definitive quota error trips the ledger and all further
    ZeroGPU work is refused for the session (§8: stop burning attempts).
    """

    def __init__(self, null_error_stop_after: int = 2) -> None:
        self.exhausted = False
        self.exhausted_reason = ""
        self.suspected_exhausted = False
        self.gpu_sec_left: float | None = None  # parsed from quota errors
        self.retry_in_sec: float | None = None
        self.successes = 0
        self.video_sec_generated = 0.0
        self.null_error_spaces: set[str] = set()
        self.null_error_stop_after = null_error_stop_after

    def mark_success(self, video_sec: float) -> None:
        self.successes += 1
        self.video_sec_generated += max(0.0, float(video_sec))

    def mark_quota_exhausted(self, message: str) -> None:
        self.exhausted = True
        self.exhausted_reason = message[:400]
        info = parse_quota_remaining(message)
        if info.get("gpu_sec_left") is not None:
            self.gpu_sec_left = info["gpu_sec_left"]
        if info.get("retry_in_sec") is not None:
            self.retry_in_sec = info["retry_in_sec"]

    def mark_null_error(self, space_id: str) -> None:
        """'space error: null' on distinct spaces → quota-suspect (dino_v1
        signature: RUNNING Spaces, null errors, account quota drained)."""
        self.null_error_spaces.add(space_id)
        if len(self.null_error_spaces) >= self.null_error_stop_after:
            self.suspected_exhausted = True

    @property
    def blocked(self) -> bool:
        return self.exhausted or self.suspected_exhausted

    def status(self) -> dict[str, Any]:
        return {
            "exhausted": self.exhausted,
            "suspected_exhausted": self.suspected_exhausted,
            "gpu_sec_left": self.gpu_sec_left,
            "retry_in_sec": self.retry_in_sec,
            "successes": self.successes,
            "video_sec_generated": round(self.video_sec_generated, 1),
        }


# ── Scheduler ────────────────────────────────────────────────────────────


@dataclass
class _SpaceState:
    known_good: bool = False
    down: bool = False  # unresponsive/missing API this session
    last_error: str = ""


class ZeroGPUScheduler:
    """Dynamic multi-Space, quota-aware ZeroGPU generation scheduler."""

    provider_id = "hf_zerogpu"

    def __init__(
        self,
        token: str | None = None,
        candidates: list[SpaceCandidate] | None = None,
        ledger: QuotaLedger | None = None,
        cache: BrokerCache | None = None,
        client_factory: Callable[..., HFZeroGPUClient] | None = None,
    ) -> None:
        self._token = token if token is not None else os.environ.get("HF_TOKEN", "")
        self.candidates = candidates if candidates is not None else default_candidates()
        self.ledger = ledger or QuotaLedger(
            null_error_stop_after=_config_null_error_stop_after())
        self.cache = cache or BrokerCache()
        self._client_factory = client_factory or HFZeroGPUClient
        self.attempts: list[SpaceAttempt] = []
        self._profiles: dict[str, SpaceInfo | None] = {}
        self._state: dict[str, _SpaceState] = {
            c.space_id: _SpaceState() for c in self.candidates
        }
        self.probed = False

    # ── discovery ────────────────────────────────────────────────────────

    def probe(self, force: bool = False) -> dict[str, SpaceInfo | None]:
        """Discover candidate Spaces via /gradio_api/info; mark dead ones."""
        if self.probed and not force:
            return self._profiles
        for cand in self.candidates:
            if cand.space_id in self._profiles and not force:
                continue
            client = self._client_factory(cand.space_id, token=self._token)
            try:
                info = client.discover(verbose=False)
                self._profiles[cand.space_id] = info
                logger.info("scheduler: %s probed OK (%d endpoints)",
                            cand.space_id, len(info.endpoints))
            except ProviderError as exc:
                self._profiles[cand.space_id] = None
                self._state[cand.space_id].down = True
                self._state[cand.space_id].last_error = str(exc)
                logger.warning("scheduler: %s probe failed: %s", cand.space_id, exc)
        self.probed = True
        return self._profiles

    def _order(self, kind: str) -> list[SpaceCandidate]:
        """Known-good first, then by priority; skip down/endpointless."""
        def capable(c: SpaceCandidate) -> bool:
            if self._state[c.space_id].down:
                return False
            ep = c.t2v_endpoint if kind == "t2v" else c.i2v_endpoint
            return bool(ep)

        pool = [c for c in self.candidates if capable(c)]
        return sorted(
            pool,
            key=lambda c: (0 if self._state[c.space_id].known_good else 1,
                           c.priority),
        )

    # ── generation ───────────────────────────────────────────────────────

    def generate(self, req: GenRequest, *, poll_timeout: float = 420.0) -> BrokerResult:
        """Try candidate Spaces in quota-aware order until one succeeds."""
        if self.ledger.blocked:
            reason = self.ledger.exhausted_reason or (
                "suspected account quota exhaustion (null errors across "
                "distinct Spaces)")
            raise ProviderError(
                f"hf_zerogpu: session quota blocked — {reason}; refusing "
                "further ZeroGPU attempts this session (§8)")
        self.probe()
        candidates = self._order(req.kind)
        if not candidates:
            raise ProviderError(
                f"hf_zerogpu: no candidate Space supports {req.kind} "
                "(probe failed or endpoints missing)")
        errors: list[str] = []
        last_exc: ProviderError | None = None
        for cand in candidates:
            if self.ledger.exhausted or self.ledger.suspected_exhausted:
                break  # tripped mid-loop — stop burning attempts
            attempt = SpaceAttempt(
                attempted_provider=f"hf_zerogpu::{cand.space_id}",
                space_id=cand.space_id, output_kind=req.kind)
            started = time.monotonic()
            try:
                result = self._attempt(cand, req, poll_timeout)
            except ProviderError as exc:
                elapsed = time.monotonic() - started
                cls = classify_failure(str(exc))
                attempt.elapsed_sec = elapsed
                attempt.failure_reason = str(exc)[:400]
                attempt.classification = cls.value
                if cls is FailureClass.QUOTA_EXHAUSTED:
                    attempt.fallback_reason = (
                        "account-level quota exhausted — stopping all "
                        "ZeroGPU attempts for this session")
                    self.ledger.mark_quota_exhausted(str(exc))
                elif (cls is FailureClass.SPACE_ERROR
                      and "space error: null" in str(exc).lower()):
                    attempt.fallback_reason = "null space error — trying a different Space"
                    self.ledger.mark_null_error(cand.space_id)
                else:
                    attempt.fallback_reason = f"{cls.value} — trying next Space"
                self.attempts.append(attempt)
                self._state[cand.space_id].last_error = str(exc)
                errors.append(
                    f"{cand.space_id} [{cls.value}]: {exc}")
                last_exc = exc
                logger.warning("scheduler attempt failed: %s", attempt.failure_reason)
                continue
            elapsed = time.monotonic() - started
            attempt.elapsed_sec = elapsed
            attempt.success = True
            attempt.output_path = str(result.path)
            self.attempts.append(attempt)
            self._state[cand.space_id].known_good = True
            self.ledger.mark_success(req.duration)
            result.metadata["attempts"] = [a.to_record() for a in self.attempts]
            result.metadata["quota"] = self.ledger.status()
            return result
        # All candidates failed — raise with the full attempt trail.
        self._append_attempt_trail(errors)
        raise ProviderError(
            "hf_zerogpu: all candidate Spaces failed for "
            f"{req.kind}; attempts: {'; '.join(errors)}") from last_exc

    def _append_attempt_trail(self, errors: list[str]) -> None:
        pass  # attempts are kept on self.attempts; error message carries trail

    def _attempt(self, cand: SpaceCandidate, req: GenRequest,
                 poll_timeout: float) -> BrokerResult:
        endpoint = cand.t2v_endpoint if req.kind == "t2v" else cand.i2v_endpoint
        client = self._client_factory(cand.space_id, token=self._token)
        adapter = ADAPTERS[cand.template]
        # i2v: upload the keyframe once (b64 templates skip the upload).
        if req.kind == "i2v" and cand.template != "wan_fast_b64":
            if req.image_path is None:
                raise ProviderError("hf_zerogpu: i2v requires image_path")
            [req.server_path] = client.upload_files([str(req.image_path)])
        data = adapter(req, client)
        payload = client.generate(data, endpoint_name=endpoint, timeout=poll_timeout)
        [blob] = client.download_result(payload)
        key = broker_cache_key(
            prompt=req.prompt, model=cand.model, seed=req.seed,
            duration=req.duration, aspect=req.aspect,
            input_path=req.image_path or "", op=f"zerogpu_{req.kind}",
            renderer_version="v4",
        )
        path = self.cache.store_bytes(key, blob, ext="mp4")
        return BrokerResult(
            path=path,
            provider=f"hf_zerogpu::{cand.space_id}",
            kind="video" if req.kind == "t2v" else "image_to_video",
            metadata={
                "space": cand.space_id,
                "space_template": cand.template,
                "model": cand.model,
                "endpoint": endpoint,
                "seed": req.seed,
                "duration": req.duration,
            },
        )

    def generate_t2v(self, prompt: str, *, duration: float = 4.0,
                     seed: int = 0, aspect: str = "16:9",
                     negative: str = "", **kw: Any) -> BrokerResult:
        return self.generate(GenRequest(
            kind="t2v", prompt=prompt, duration=duration, seed=seed,
            aspect=aspect, negative=negative), **kw)

    def generate_i2v(self, image: str | Path, prompt: str, *,
                     duration: float = 4.0, seed: int = 0,
                     aspect: str = "16:9", negative: str = "",
                     **kw: Any) -> BrokerResult:
        return self.generate(GenRequest(
            kind="i2v", prompt=prompt, duration=duration, seed=seed,
            aspect=aspect, negative=negative, image_path=image), **kw)


# ── Broker-facing provider wrappers ──────────────────────────────────────


class ZeroGPUVideoProvider(MediaProvider):
    """T2V via the quota-aware scheduler (registered as kind="video")."""

    id = "zerogpu_t2v"
    kind = "video"

    def __init__(self, scheduler: ZeroGPUScheduler | None = None) -> None:
        self.scheduler = scheduler or ZeroGPUScheduler()

    def capabilities(self) -> ProviderDescriptor:
        models = sorted({c.model for c in self.scheduler.candidates
                         if c.t2v_endpoint})
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=models,
            enabled=bool(self.scheduler._token),
            priority=15,
            notes="Quota-aware multi-Space T2V scheduler (§8)",
        )

    def health_check(self) -> bool:
        if not self.scheduler._token:
            return False
        try:
            self.scheduler.probe()
            return any(p is not None for p in self.scheduler._profiles.values())
        except ProviderError:
            return False

    def quota(self) -> dict[str, Any] | None:
        return self.scheduler.ledger.status()

    def generate_video(self, prompt: str, *, duration: float = 4.0,
                       aspect: str = "16:9", seed: int = 0,
                       **kw: Any) -> BrokerResult:
        return self.scheduler.generate_t2v(
            prompt, duration=duration, aspect=aspect, seed=seed)


class ZeroGPUI2VProvider(MediaProvider):
    """I2V via the quota-aware scheduler (registered as kind="image_to_video")."""

    id = "zerogpu_i2v"
    kind = "image_to_video"

    def __init__(self, scheduler: ZeroGPUScheduler | None = None) -> None:
        self.scheduler = scheduler or ZeroGPUScheduler()

    def capabilities(self) -> ProviderDescriptor:
        models = sorted({c.model for c in self.scheduler.candidates
                         if c.i2v_endpoint})
        return ProviderDescriptor(
            id=self.id, kind=self.kind, models=models,
            enabled=bool(self.scheduler._token),
            priority=15,
            notes="Quota-aware multi-Space I2V scheduler (§8)",
        )

    def health_check(self) -> bool:
        if not self.scheduler._token:
            return False
        try:
            self.scheduler.probe()
            return any(p is not None for p in self.scheduler._profiles.values())
        except ProviderError:
            return False

    def quota(self) -> dict[str, Any] | None:
        return self.scheduler.ledger.status()

    def image_to_video(self, image: str | Path, prompt: str, *,
                       duration: float = 4.0, aspect: str = "16:9",
                       seed: int = 0, **kw: Any) -> BrokerResult:
        return self.scheduler.generate_i2v(
            image, prompt, duration=duration, aspect=aspect, seed=seed)
