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

V13 M1a (2026-09-20): the interface gains two multi-stage ops with
NotImplemented-safe fallbacks to the existing single-pass text→img:

  - edit_image(prompt, image: str|list[str], aspect, seed)
  - generate_multi_ref(prompt, refs: list[str], aspect, seed)

Implementations behind the SAME interface, existing keys only:
  - gemini_image : Gemini image model — edit (1 ref) + multi-ref (2+ refs)
                   via inline images                      [needs GEMINI_API_KEY]
  - nvidia_nim   : FLUX.1-Kontext-dev edit endpoint (single ref)
  - siliconflow  : Qwen-Image-Edit / FLUX.1-Kontext-dev edit (single ref)
  - pollinations : single-pass fallback only (keyless)

See tools/image_capability_audit.py + docs/v13/PROVIDER_CAPABILITIES.md for
the live-probed capability matrix (key names only, never values).
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.config import get_config


# ═══════════════════════════════════════════════════════════════════════ #
# Deterministic seeds (v35, review 2026-08-13)
# ═══════════════════════════════════════════════════════════════════════ #


def deterministic_seed(prompt: str, salt: int = 0) -> int:
    """Stable seed derived from *prompt* for reproducible A/B prompt tests.

    Same prompt + salt -> same seed on every run/process (crc32 is
    process-independent, unlike ``hash()`` which is salted per process).
    Pass the result as ``seed=`` to any provider so prompt variants can
    be compared on equal footing (identical seed, only the prompt
    differs).
    """
    import zlib
    return zlib.crc32(f"{salt}:{prompt}".encode("utf-8")) % 100000


# v42: sanity guard for provider outputs.  A misconfigured/broken image
# endpoint can return a tiny or corrupt payload that HTTP-succeeds; every
# caller (stage_ai_imagery, FallbackDirector, mission_stills._ai_still)
# treats a written file as success, so a 6 KB error blob used to sail
# straight into the timeline (6174 run: NIM returned 6 KB "images" for
# every prompt and the v41 dedup had to reject them all — the video then
# fell back to stock footage).  Real 2560x1440 images are never < ~15 KB
# and always parse as a non-trivial image.
_MIN_IMAGE_BYTES = 15_000


def _looks_like_image(path: str) -> bool:
    """True when *path* holds a parseable image of sane dimensions."""
    try:
        if not os.path.exists(path) or os.path.getsize(path) < _MIN_IMAGE_BYTES:
            return False
        from PIL import Image
        with Image.open(path) as im:
            im.verify()  # raises on corrupt/truncated files
        return True
    except Exception:
        return False


def _read_data_uri(path: str) -> str:
    """Encode an image file as a data URI for img2img request payloads."""
    mime = "image/png"
    try:
        from PIL import Image
        with Image.open(path) as im:
            mime = Image.MIME.get(im.format, "image/png")
    except Exception:
        pass
    raw = Path(path).read_bytes()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _derived_out(provider: str, op: str, prompt: str,
                 seed: Optional[int]) -> str:
    """Output path for a multi-stage op result under cache/generated/."""
    tag = deterministic_seed(f"{op}:{prompt}", seed or 0)
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"cache/generated/{provider}_{op}_{tag}_{ts}.png"


def _write_verified(raw: bytes, out: str, name: str) -> str:
    """Write *raw* to *out* and run the v42 image sanity guard on it."""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(raw)
    if not _looks_like_image(out):
        try:
            Path(out).unlink()
        except OSError:
            pass
        raise RuntimeError(
            f"{name}: payload failed image sanity check ({len(raw)} bytes)")
    return out


# ═══════════════════════════════════════════════════════════════════════ #
# Interface
# ═══════════════════════════════════════════════════════════════════════ #


def _multipart_post(url: str, fields: dict, *, headers: dict,
                    timeout: int = 120) -> tuple[bytes, str]:
    """POST fields as multipart/form-data; return (body, content_type).

    Used by providers whose endpoint rejects a plain JSON body (WP8: the
    Cloudflare Workers AI flux-2-klein-4b endpoint 400s on JSON with
    "required properties at '/' are 'multipart'" — verified live 2026-09-30).
    """
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
            .encode())
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body,
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


class ImageGenProvider(ABC):
    """Interface for AI image generation providers."""

    name: str = "base"

    # WP8: True for providers the owner has NOT approved for production use
    # (trial/evaluation-only service terms). ImageGenFactory/v15_plates keep
    # the class importable and directly selectable (scripts/benchmark_image_gen.py,
    # tools/image_capability_audit.py) but exclude it from the default chain.
    benchmark_only: bool = False

    @abstractmethod
    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        """Generate an image for *prompt*, save to *output_path*, return path."""
        ...

    def is_available(self) -> bool:
        """Whether this provider has the credentials needed to run."""
        return True

    # ── V13 M1a multi-stage ops (default: unsupported) ───────────────────

    def edit_image(self, prompt: str, image: "str | list[str]",
                   aspect: str = "16:9", seed: Optional[int] = None) -> str:
        """Edit *image* (path or list of paths) per *prompt*; return path.

        Providers without an editing endpoint raise NotImplementedError —
        callers fall back to single-pass text→img (edit_image_with_fallback).
        """
        raise NotImplementedError(
            f"{self.name}: image editing not supported (single-pass text→img only)")

    def generate_multi_ref(self, prompt: str, refs: list[str],
                           aspect: str = "16:9", seed: Optional[int] = None) -> str:
        """Compose an image from *refs* (2+ paths) per *prompt*; return path.

        NotImplementedError → caller falls back to single-pass text→img
        (generate_multi_ref_with_fallback).
        """
        raise NotImplementedError(
            f"{self.name}: multi-reference generation not supported")


# ═══════════════════════════════════════════════════════════════════════ #
# NVIDIA NIM (FLUX family)
# ═══════════════════════════════════════════════════════════════════════ #


class NvidiaNimProvider(ImageGenProvider):
    """NVIDIA NIM hosted FLUX image generation.

    v33: FLUX.2-klein-4b is now the PRIMARY endpoint — same free API key,
    3.3x faster than flux.1-dev (2.5s vs 8.2s @ 1456x720) and measurably
    sharper (laplacian 4.0 vs 0.6; 55k vs 16k unique colors, verified
    2026-08-13).  ``flux.2-klein-4b`` accepts a FIXED aspect-preserving
    pair set (long axis <= 1568); we snap to the nearest pair by aspect
    ratio.  Falls back to ``flux.1-dev`` then ``flux.1-schnell``.
    """

    name = "nvidia_nim"
    # Owner decision (Phase 1, PROGRESS.md 2026-09-27): "NVIDIA NIM: not
    # approved for production" — trial/evaluation terms only. WP8 (DESIGN
    # §6.1/§15.3 item 2) removes it from the default production chain;
    # kept fully implemented for scripts/benchmark_image_gen.py and
    # tools/image_capability_audit.py, which pass the name explicitly.
    benchmark_only = True

    # flux.1-dev valid dimensions (multiples of 64, min 768).  VERIFIED
    # against the live API 2026-08-12: BOTH axes are capped at 1344 — the
    # old list went to 2048, so 2560x1440 snapped to 2048x1408, the API
    # 422'd ("Input should be 768, ..., 1280 or 1344"), every fallback
    # endpoint failed, and the surfaced error was the dead 3rd endpoint's
    # 404.  v30: dims match what the API actually accepts.
    _ALLOWED_DIMS = [768, 832, 896, 960, 1024, 1088, 1152, 1216, 1280,
                     1344]

    # flux.2-klein-4b accepted resolutions (verified 2026-08-13): a fixed
    # aspect-preserving pair set, both orientations, long axis <= 1568.
    _FLUX2_PAIRS = [
        (672, 1568), (688, 1504), (720, 1456), (752, 1392), (800, 1328),
        (832, 1248), (880, 1184), (944, 1104), (1024, 1024),
    ]

    # v30: dropped the dead `nvidia/flux.1-dev` route (404 page not
    # found) — it masked the real 422 dims error on every still.
    # v33: flux.2-klein-4b first (better + faster), flux.1-dev second.
    ENDPOINTS = [
        "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b",
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

    @classmethod
    def _snap_pair(cls, width: int, height: int) -> tuple[int, int]:
        """Snap to the nearest flux.2-klein pair by aspect ratio.

        The API rejects anything outside the fixed pair set (verified
        2026-08-13: a 1456x720 request succeeded, 2560x1440 would 422).
        Compare the request's aspect against BOTH orientations of every
        pair and pick the closest (landscape request -> landscape pair).
        """
        target = width / max(height, 1)
        best = min(
            ((w, h) for p in cls._FLUX2_PAIRS for w, h in (p, (p[1], p[0]))),
            key=lambda wh: abs(wh[0] / wh[1] - target),
        )
        return best

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY not set")
        # v33: flux.2-klein-4b (first endpoint) takes a FIXED pair set;
        # flux.1-dev/schnell take per-axis multiples.  Snap per endpoint.
        _w0, _h0 = width, height
        per_axis = (self._snap(_w0), self._snap(int(round(_h0 * self._snap(_w0) / max(1, _w0)))))
        last_err: Optional[Exception] = None
        for i, url in enumerate(self.ENDPOINTS):
            try:
                if i == 0:
                    width, height = self._snap_pair(_w0, _h0)
                else:
                    width, height = per_axis
                payload = {
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    # v35: honor seed=0; old ``seed or time`` turned an
                    # explicit 0 into a time-based seed (A/B tests pass
                    # deterministic_seed() which can legitimately be 0).
                    "seed": seed if seed is not None else int(time.time()) % 100000,
                }
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
                    # v42: sanity-guard the written file — a broken/misconfigured
                    # NIM endpoint returns tiny error/placeholder payloads that
                    # "succeed" (6174 run: every still came back 6 KB and the
                    # v41 dedup had to reject them all, so the video fell back
                    # to stock).  A real 2560x1440 image is never < ~20 KB or
                    # unparseable; reject and let the caller fail over.
                    if not _looks_like_image(output_path):
                        try:
                            Path(output_path).unlink()
                        except OSError:
                            pass
                        raise RuntimeError(
                            f"NIM returned a non-image payload "
                            f"({Path(output_path).stat().st_size if Path(output_path).exists() else 0} bytes)")
                    return output_path
                img_url = body.get("url") or (body.get("data") or [{}])[0].get("url")
                if img_url:
                    with urllib.request.urlopen(img_url, timeout=120) as r:
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        Path(output_path).write_bytes(r.read())
                    if not _looks_like_image(output_path):
                        try:
                            Path(output_path).unlink()
                        except OSError:
                            pass
                        raise RuntimeError("NIM URL image failed sanity check")
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

    # ── V13 M1a: image editing (FLUX.1-Kontext-dev, hosted NIM) ─────────
    #
    # The text→img FLUX.2 endpoints take no image input; kontext is the
    # NIM-hosted editing model on the same free NVIDIA_API_KEY.  Payload
    # shape per NIM docs: {"prompt", "image": <data-uri>, "seed", "steps"}.
    KONTEXT_ENDPOINT = ("https://ai.api.nvidia.com/v1/genai/"
                        "black-forest-labs/flux.1-kontext-dev")

    def edit_image(self, prompt: str, image: "str | list[str]",
                   aspect: str = "16:9", seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("NVIDIA_API_KEY not set")
        paths = [str(image)] if isinstance(image, (str, Path)) else [str(p) for p in image]
        if len(paths) != 1:
            raise NotImplementedError(
                "nvidia_nim: edit takes exactly one reference image (kontext)")
        payload = {
            "prompt": prompt,
            "image": _read_data_uri(paths[0]),
            "seed": seed if seed is not None else int(time.time()) % 100000,
            "steps": 30,
        }
        req = urllib.request.Request(
            self.KONTEXT_ENDPOINT, data=json.dumps(payload).encode(),
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
            or body.get("image")
            or body.get("images", [None])[0]
        )
        if not b64:
            raise RuntimeError(f"nvidia_nim kontext: unexpected response {list(body)[:5]}")
        raw = base64.b64decode(b64)
        out = _derived_out("nvidia_nim", "edit", prompt, seed)
        return _write_verified(raw, out, self.name)


# ═══════════════════════════════════════════════════════════════════════ #
# SiliconFlow (FLUX family, OpenAI-compatible)
# ═══════════════════════════════════════════════════════════════════════ #


class SiliconFlowProvider(ImageGenProvider):
    """SiliconFlow hosted FLUX image generation (OpenAI-compatible)."""

    name = "siliconflow"
    # WP8/DESIGN §6.1: dead (401 as of RESEARCH.md §5.1) and replaced in the
    # production chain by cloudflare_workers_ai/sdcpp_local. Kept implemented
    # (not deleted) in case the key is ever rotated back to life.
    benchmark_only = True

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

    # ── V13 M1a: image editing on the same generations endpoint ──────────
    # Both edit models accept {"prompt", "image": <data-uri>, "seed"};
    # output follows the input image.  Tried in order, first success wins.
    EDIT_MODELS = ["Qwen/Qwen-Image-Edit", "black-forest-labs/FLUX.1-Kontext-dev"]

    def edit_image(self, prompt: str, image: "str | list[str]",
                   aspect: str = "16:9", seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("SILICONFLOW_API_KEY not set")
        paths = [str(image)] if isinstance(image, (str, Path)) else [str(p) for p in image]
        if len(paths) != 1:
            raise NotImplementedError(
                "siliconflow: edit takes exactly one reference image")
        last_err: Optional[Exception] = None
        for model in self.EDIT_MODELS:
            try:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "image": _read_data_uri(paths[0]),
                    "seed": seed if seed is not None else 0,
                }
                req = urllib.request.Request(
                    self._base_url, data=json.dumps(payload).encode(),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    body = json.loads(resp.read().decode())
                b64 = body.get("data", [{}])[0].get("b64_json")
                if b64:
                    raw = base64.b64decode(b64)
                else:
                    url = body.get("data", [{}])[0].get("url")
                    if not url:
                        raise RuntimeError(f"unexpected response: {list(body)[:5]}")
                    with urllib.request.urlopen(url, timeout=60) as r:
                        raw = r.read()
                out = _derived_out("siliconflow", "edit", prompt, seed)
                return _write_verified(raw, out, self.name)
            except Exception as exc:  # noqa: BLE001 — try the next edit model
                last_err = exc
                continue
        raise RuntimeError(f"siliconflow edit failed: {last_err}")

    def generate_multi_ref(self, prompt: str, refs: list[str],
                           aspect: str = "16:9", seed: Optional[int] = None) -> str:
        """Multi-reference composition via Qwen-Image-Edit-2509.

        The 2509 revision accepts an image LIST (wired 2026-09-20, not yet
        live-probed — see PROVIDER_CAPABILITIES.md).  First ref failure
        falls through to the edit-model chain: single image → kontext.
        """
        if not self._api_key:
            raise RuntimeError("SILICONFLOW_API_KEY not set")
        paths = [str(r) for r in refs]
        if len(paths) < 2:
            raise NotImplementedError(
                "siliconflow: generate_multi_ref needs 2+ reference images")
        payload = {
            "model": "Qwen/Qwen-Image-Edit-2509",
            "prompt": prompt,
            "image": [_read_data_uri(p) for p in paths],
            "seed": seed if seed is not None else 0,
        }
        req = urllib.request.Request(
            self._base_url, data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode())
        b64 = body.get("data", [{}])[0].get("b64_json")
        if b64:
            raw = base64.b64decode(b64)
        else:
            url = body.get("data", [{}])[0].get("url")
            if not url:
                raise RuntimeError(f"unexpected response: {list(body)[:5]}")
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = r.read()
        out = _derived_out("siliconflow", "multiref", prompt, seed)
        return _write_verified(raw, out, self.name)


# ═══════════════════════════════════════════════════════════════════════ #
# Gemini image model (gemini-2.5-flash-image "nano banana")
# ═══════════════════════════════════════════════════════════════════════ #


class GeminiImageProvider(ImageGenProvider):
    """Google Gemini image model — edit AND multi-reference composition.

    One ``generateContent`` endpoint covers all three ops: zero image
    parts → single-pass text→img, one part → edit, 2+ parts →
    multi-reference blend (each reference is a separate Part; the model
    merges them into ONE output image).  Up to 14 reference images.
    The API does not honour a seed (accepted, ignored).
    """

    name = "gemini_image"

    _AR = {"1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4,
           "16:9": 16 / 9, "9:16": 9 / 16, "21:9": 21 / 9}

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model = model or get_config(
            "image_gen.gemini.model", "gemini-2.5-flash-image")

    def is_available(self) -> bool:
        return bool(self._api_key)

    @classmethod
    def _nearest_aspect(cls, width: int, height: int) -> str:
        target = width / max(height, 1)
        return min(cls._AR, key=lambda a: abs(cls._AR[a] - target))

    def _run(self, contents: list, aspect: Optional[str] = None) -> bytes:
        """Call the image model; return the raw image bytes of the reply."""
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=self._api_key)
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect) if aspect else None,
        )
        response = client.models.generate_content(
            model=self._model, contents=contents, config=config)
        cands = list(response.candidates or [])
        for cand in cands:
            for part in (cand.content.parts or []):
                inline = getattr(part, "inline_data", None) \
                    or getattr(part, "inlineData", None)
                if inline is not None and getattr(inline, "data", None):
                    return inline.data
        finish = cands[0].finish_reason if cands else "no-candidates"
        raise RuntimeError(
            f"gemini_image: no image part in response (model={self._model}, "
            f"finish_reason={finish})")

    @staticmethod
    def _load(path: str):
        from PIL import Image
        return Image.open(path)

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        raw = self._run([prompt], self._nearest_aspect(width, height))
        return _write_verified(raw, output_path, self.name)

    def edit_image(self, prompt: str, image: "str | list[str]",
                   aspect: str = "16:9", seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        paths = [str(image)] if isinstance(image, (str, Path)) \
            else [str(p) for p in image]
        if len(paths) != 1:
            raise NotImplementedError(
                "gemini_image: edit takes exactly one reference "
                "(use generate_multi_ref for 2+)")
        raw = self._run([prompt, self._load(paths[0])], aspect)
        out = _derived_out(self.name, "edit", prompt, seed)
        return _write_verified(raw, out, self.name)

    def generate_multi_ref(self, prompt: str, refs: list[str],
                           aspect: str = "16:9", seed: Optional[int] = None) -> str:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        paths = [str(r) for r in refs]
        if len(paths) < 2:
            raise NotImplementedError(
                "gemini_image: multi-ref needs 2+ reference images")
        if len(paths) > 14:
            raise NotImplementedError(
                "gemini_image: at most 14 reference images")
        raw = self._run([prompt] + [self._load(p) for p in paths], aspect)
        out = _derived_out(self.name, "multiref", prompt, seed)
        return _write_verified(raw, out, self.name)


# ═══════════════════════════════════════════════════════════════════════ #
# Hugging Face serverless
# ═══════════════════════════════════════════════════════════════════════ #


class HFServerlessProvider(ImageGenProvider):
    """Hugging Face Inference API (serverless) image generation."""

    name = "hf_serverless"
    # WP8/DESIGN §6.1: dead (410 Gone as of RESEARCH.md §5.1) and replaced in
    # the production chain by cloudflare_workers_ai/sdcpp_local. Kept
    # implemented (not deleted) in case a working endpoint/model returns.
    benchmark_only = True

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

    v35 (review 2026-08-13): the model is now PINNED explicitly instead of
    relying on the endpoint default, which silently shifted to "sana" in
    Aug 2026.  LIVE VERIFIED 2026-08-13: the endpoint currently IGNORES
    the ``model`` param (flux/turbo/sana/'' all returned byte-identical
    JPEGs, Exif manufacturer=sana) — the pin documents intent and takes
    effect if/when the endpoint honors it.
    """

    name = "pollinations"

    def __init__(self, base_url: Optional[str] = None,
                 model: Optional[str] = None):
        self._base_url = base_url or get_config(
            "image_gen.pollinations.base_url",
            "https://image.pollinations.ai/prompt",
        )
        self._model = model or get_config(
            "image_gen.pollinations.model", "flux"
        )

    def is_available(self) -> bool:
        return True  # keyless

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        import urllib.parse
        params = {"width": width, "height": height, "nologo": "true",
                  "model": self._model}
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
        # v42: same sanity guard as NIM — tiny/corrupt payloads must not
        # "succeed" and enter the timeline (see _looks_like_image).
        if not _looks_like_image(output_path):
            try:
                Path(output_path).unlink()
            except OSError:
                pass
            raise RuntimeError(
                f"Pollinations payload failed image sanity check "
                f"({os.path.getsize(output_path) if os.path.exists(output_path) else 0} bytes)")
        return output_path


# ═══════════════════════════════════════════════════════════════════════ #
# Cloudflare Workers AI (FLUX.2-klein-4B) — WP8
# ═══════════════════════════════════════════════════════════════════════ #


class CloudflareWorkersAIProvider(ImageGenProvider):
    """Cloudflare Workers AI, ``@cf/black-forest-labs/flux-2-klein-4b``.

    Same base model as NVIDIA NIM's primary (Apache-2.0), served from a
    Cloudflare Workers AI account with a permanent free daily neuron
    allocation (RESEARCH.md §5.1/§5.4) — the DESIGN §6.1 fast primary of the
    production chain, ahead of nvidia_nim (now ``benchmark_only``).

    Request shape verified LIVE 2026-09-30 (no prior fixture existed —
    DESIGN §6.2 flagged this as [U]): the endpoint 400s on a plain JSON body
    ("required properties at '/' are 'multipart'"); it wants
    ``multipart/form-data`` fields and returns ``{"result": {"image":
    "<base64 jpeg>"}}``. ``width``/``height``/``seed``/``steps`` are all
    honoured as given (confirmed: a 720x1280 request returns an exact
    720x1280 image) — no client-side dimension snapping needed, unlike NIM.
    """

    name = "cloudflare_workers_ai"
    MODEL = "@cf/black-forest-labs/flux-2-klein-4b"

    def __init__(self, account_id: Optional[str] = None,
                 api_token: Optional[str] = None):
        self._account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        self._api_token = api_token or os.environ.get("CLOUDFLARE_API_TOKEN", "")

    def is_available(self) -> bool:
        # DESIGN §6.2: absent creds must skip cleanly, never crash, never
        # prompt for/invent a key — a plain bool check, nothing more.
        return bool(self._account_id and self._api_token)

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        if not self.is_available():
            raise RuntimeError(
                "cloudflare_workers_ai: CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN not set")
        url = (f"https://api.cloudflare.com/client/v4/accounts/"
              f"{self._account_id}/ai/run/{self.MODEL}")
        fields = {"prompt": prompt, "width": width, "height": height}
        if seed is not None:
            fields["seed"] = seed
        body, ctype = _multipart_post(
            url, fields,
            headers={"Authorization": f"Bearer {self._api_token}"},
            timeout=120)
        payload = json.loads(body)
        if not payload.get("success", True) and not payload.get("result"):
            raise RuntimeError(f"cloudflare_workers_ai: {payload.get('errors')}")
        b64 = (payload.get("result") or {}).get("image")
        if not b64:
            raise RuntimeError(
                f"cloudflare_workers_ai: unexpected response shape {list(payload)[:5]}")
        raw = base64.b64decode(b64)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(raw)
        if not _looks_like_image(output_path):
            try:
                Path(output_path).unlink()
            except OSError:
                pass
            raise RuntimeError(
                f"cloudflare_workers_ai returned a non-image payload ({len(raw)} bytes)")
        return output_path


# ═══════════════════════════════════════════════════════════════════════ #
# Local stable-diffusion.cpp (FLUX.2-klein-4B) — WP8, owned floor
# ═══════════════════════════════════════════════════════════════════════ #


class SDCppLocalProvider(ImageGenProvider):
    """Local FLUX.2-klein-4B via ``stable-diffusion.cpp`` (MIT tool,
    Apache-2.0 weights) — the owned emergency floor (DESIGN §6.1 tier 5):
    always available (no account, no network), but slow (RESEARCH.md §5.3
    measured ~1,237 s / image at 576x1024 on this CPU), so callers should
    treat it as a last-resort/budget-capped tier, not a per-shot default.

    Paths default to the layout the RESEARCH.md §5.3 benchmark already
    built under ``~/models`` (built from source, weights downloaded there);
    override via ``configs/images.yaml`` (``image_gen.sdcpp.*``) or the
    constructor for a different machine.
    """

    name = "sdcpp_local"

    def __init__(self, bin_path: Optional[str] = None,
                 diffusion_model: Optional[str] = None,
                 vae: Optional[str] = None, llm: Optional[str] = None,
                 steps: Optional[int] = None, cfg_scale: Optional[float] = None,
                 timeout_s: Optional[int] = None):
        home = str(Path.home())
        self._bin = Path(bin_path or get_config(
            "image_gen.sdcpp.bin", f"{home}/models/sdcpp/build/bin/sd-cli")
            ).expanduser()
        self._diffusion_model = Path(diffusion_model or get_config(
            "image_gen.sdcpp.diffusion_model",
            f"{home}/models/flux2klein/flux-2-klein-4b-Q4_0.gguf")).expanduser()
        self._vae = Path(vae or get_config(
            "image_gen.sdcpp.vae", f"{home}/models/flux2klein/vae.safetensors")
            ).expanduser()
        self._llm = Path(llm or get_config(
            "image_gen.sdcpp.llm",
            f"{home}/models/flux2klein/Qwen3-4B-Q4_K_M.gguf")).expanduser()
        self._steps = steps or get_config("image_gen.sdcpp.steps", 4)
        self._cfg_scale = cfg_scale or get_config("image_gen.sdcpp.cfg_scale", 1.0)
        self._timeout_s = timeout_s or get_config("image_gen.sdcpp.timeout_s", 1800)

    def is_available(self) -> bool:
        return (self._bin.exists() and self._diffusion_model.exists()
                and self._vae.exists() and self._llm.exists())

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        if not self.is_available():
            raise RuntimeError(
                "sdcpp_local: binary or model files not found under "
                f"{self._bin.parent} / {self._diffusion_model.parent} "
                "(see configs/images.yaml image_gen.sdcpp.*)")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = [str(self._bin),
              "--diffusion-model", str(self._diffusion_model),
              "--vae", str(self._vae), "--llm", str(self._llm),
              "-p", prompt,
              "--cfg-scale", str(self._cfg_scale),
              "--steps", str(self._steps),
              "--offload-to-cpu", "--diffusion-fa",
              "-W", str(width), "-H", str(height),
              "-s", str(seed if seed is not None else 42),
              "-o", str(output_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=self._timeout_s)
        if proc.returncode != 0 or not _looks_like_image(output_path):
            raise RuntimeError(
                f"sdcpp_local generation failed (rc={proc.returncode}): "
                f"{proc.stderr[-300:] if proc.stderr else proc.stdout[-300:]}")
        return output_path


# ═══════════════════════════════════════════════════════════════════════ #
# Public-domain / CC0 archive tier — WP8
# ═══════════════════════════════════════════════════════════════════════ #


class ArchiveProvider(ImageGenProvider):
    """Public-domain / CC0 archive search, keyless: NASA Images + the Met
    Open Access API (DESIGN §6.1 tier 2). Only ever returns an item the
    source API itself marks PD/CC0; every other outcome (no query match, no
    cleared item) raises so the chain descends to generation — this NEVER
    silently substitutes an unrelated or unlicensed image.

    DESIGN §6.1 gates this tier on ``shot.kind == "artefact/real object/
    place"``, a classification that does not exist anywhere in the current
    plan/shot schema (`v16_plan.py` has template kinds like HOOK_PLATE, not
    a subject-type field — confirmed by inspection, not assumed). Pending
    that classifier (candidate for a future WP touching `v16_plan.py`), this
    uses a keyword heuristic on the shot SUBJECT clause of the plate prompt
    (the same clause `engine.v15_plates._main_subject`/`plate_qa` already
    extract) as a stand-in: OWNER FLAG, not a full fix.
    """

    name = "archive"

    # Concrete real-object/place nouns worth an archive search. Deliberately
    # narrow (recall over precision doesn't help here: a miss just falls
    # through to generation, exactly as intended) — extend via
    # configs/images.yaml `image_gen.archive.subject_hints` without a code change.
    _DEFAULT_HINTS = (
        "meteorite", "fossil", "skeleton", "specimen", "engraving",
        "photograph", "photo", "artifact", "artefact", "museum",
        "telescope", "spacecraft", "satellite", "instrument", "statue",
        "monument", "manuscript", "mineral", "crater", "ruins", "temple",
        "tomb", "ship", "vessel", "aircraft", "meteor", "comet", "fragment",
        "relic", "coin", "map", "diagram", "painting", "sculpture",
    )

    def __init__(self, max_results: Optional[int] = None,
                 subject_hints: Optional[tuple] = None):
        self._max_results = max_results or get_config(
            "image_gen.archive.max_results", 5)
        self._hints = tuple(subject_hints or get_config(
            "image_gen.archive.subject_hints", self._DEFAULT_HINTS))

    def is_available(self) -> bool:
        return True  # keyless public APIs

    def _subject(self, prompt: str) -> str:
        return prompt.split(". ")[1] if ". " in prompt else prompt

    def _looks_archival(self, subject: str) -> bool:
        low = subject.lower()
        return any(h in low for h in self._hints)

    def _query_terms(self, subject: str) -> str:
        words = [w for w in subject.lower().replace(",", " ").split()
                if w in self._hints or len(w) > 4]
        return " ".join(words[:6]) or subject

    def _search_nasa(self, query: str) -> Optional[str]:
        url = ("https://images-api.nasa.gov/search?media_type=image&q="
              + urllib.parse.quote(query))
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                data = json.loads(resp.read())
        except Exception:
            return None
        for item in (data.get("collection", {}).get("items") or [])[:self._max_results]:
            best = None
            for link in item.get("links") or []:
                if link.get("render") != "image":
                    continue
                if best is None or (link.get("width") or 0) > (best.get("width") or 0):
                    best = link
            if best:
                return best["href"]  # NASA media: not copyrighted (NASA media guidelines)
        return None

    def _search_met(self, query: str) -> Optional[str]:
        search_url = ("https://collectionapi.metmuseum.org/public/collection/"
                     "v1/search?hasImages=true&q=" + urllib.parse.quote(query))
        try:
            with urllib.request.urlopen(search_url, timeout=20) as resp:
                ids = json.loads(resp.read()).get("objectIDs") or []
        except Exception:
            return None
        for oid in ids[:self._max_results]:
            try:
                obj_url = (f"https://collectionapi.metmuseum.org/public/"
                          f"collection/v1/objects/{oid}")
                with urllib.request.urlopen(obj_url, timeout=20) as resp:
                    obj = json.loads(resp.read())
            except Exception:
                continue
            if obj.get("isPublicDomain") and obj.get("primaryImage"):
                return obj["primaryImage"]
        return None

    def generate(self, prompt: str, output_path: str,
                 width: int = 1024, height: int = 576,
                 seed: Optional[int] = None) -> str:
        subject = self._subject(prompt)
        if not self._looks_archival(subject):
            raise RuntimeError(
                f"archive: {subject!r} has no concrete real-object/place "
                "keyword hint (see image_gen.archive.subject_hints)")
        query = self._query_terms(subject)
        url = self._search_nasa(query) or self._search_met(query)
        if not url:
            raise RuntimeError(f"archive: no PD/CC0 match for {query!r}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(raw)
        if not _looks_like_image(output_path):
            try:
                Path(output_path).unlink()
            except OSError:
                pass
            raise RuntimeError(f"archive: downloaded file from {url} failed sanity check")
        return output_path


# ═══════════════════════════════════════════════════════════════════════ #
# Factory
# ═══════════════════════════════════════════════════════════════════════ #

_PROVIDERS: dict[str, type[ImageGenProvider]] = {
    "nvidia_nim": NvidiaNimProvider,
    "siliconflow": SiliconFlowProvider,
    "hf_serverless": HFServerlessProvider,
    "pollinations": PollinationsProvider,
    "gemini_image": GeminiImageProvider,
    "cloudflare_workers_ai": CloudflareWorkersAIProvider,
    "sdcpp_local": SDCppLocalProvider,
    "archive": ArchiveProvider,
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

    def production_available(self) -> list[ImageGenProvider]:
        """Providers with credentials present, excluding benchmark_only
        (WP8: nvidia_nim/siliconflow/hf_serverless — owner decision, not
        approved / dead) — what the live render chain should ever pick."""
        return [p for p in self.available() if not p.benchmark_only]

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
# V13 M1a: graceful degradation — multi-stage op → single-pass text→img
# ═══════════════════════════════════════════════════════════════════════ #

_FALLBACK_SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}


def edit_image_with_fallback(provider: ImageGenProvider, prompt: str,
                             image: "str | list[str]", aspect: str = "16:9",
                             seed: Optional[int] = None) -> "tuple[str, bool]":
    """edit_image, degrading to single-pass text→img when unavailable.

    Returns ``(path, edited)`` so plate stages (M1b) can flag degraded
    output in their sidecar.  Never raises for "op unsupported" or a
    failed endpoint — the factory/callers must keep working.
    """
    try:
        return provider.edit_image(prompt, image, aspect=aspect, seed=seed), True
    except (NotImplementedError, RuntimeError):
        pass
    width, height = _FALLBACK_SIZES.get(aspect, _FALLBACK_SIZES["16:9"])
    out = _derived_out(provider.name, "edit_fallback", prompt, seed)
    return (provider.generate(prompt, out, width=width, height=height,
                              seed=seed), False)


def generate_multi_ref_with_fallback(provider: ImageGenProvider, prompt: str,
                                     refs: list[str], aspect: str = "16:9",
                                     seed: Optional[int] = None) -> "tuple[str, bool]":
    """generate_multi_ref, degrading to single-pass text→img likewise.

    Returns ``(path, composed)``; *composed* is False when the provider
    lacked multi-reference support and a plain generation was produced.
    """
    try:
        return provider.generate_multi_ref(prompt, refs, aspect=aspect,
                                           seed=seed), True
    except (NotImplementedError, RuntimeError):
        pass
    width, height = _FALLBACK_SIZES.get(aspect, _FALLBACK_SIZES["16:9"])
    out = _derived_out(provider.name, "multiref_fallback", prompt, seed)
    return (provider.generate(prompt, out, width=width, height=height,
                              seed=seed), False)


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
