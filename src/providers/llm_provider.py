"""
llm_provider.py — Abstract LLM provider and concrete implementations.

Defines the LLMProvider interface, then implements:
- DeepSeekProvider (planning / script generation)
- GeminiProvider (multimodal critic evaluation)
"""

import os
import time
import json
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from google import genai
import PIL.Image

from src.utils.config import get_config


# ── DeepSeek prefix caching (cost optimisation) ─────────────────────────────
# DeepSeek bills cache hits at 1/50th of the miss rate (disk prefix cache,
# TTL hours→days) and matches on EXACT input-prefix equality. The single
# biggest cost lever is therefore a STABLE leading system message: every call
# that starts with the same bytes reuses the cached prefix, so call N+1 in a
# run (and calls on later runs within the TTL) pay the hit rate instead of
# the miss rate for the whole static body. Keep this constant byte-identical
# — no timestamps, no topic, no dynamic content.
DEEPSEEK_SYSTEM_PROMPT = (
    "You are the production engine for ckdigital's documentary video pipeline. "
    "You produce factual, precise, verifiable content for short documentaries. "
    "Hard rules: never invent numbers, sources, or dates; only use facts given "
    "in the request; follow the exact output schema requested; output ONLY valid "
    "JSON without markdown fences when JSON is requested; no commentary outside "
    "the JSON payload."
)

# ── Usage accounting (per-run DeepSeek token/cost measurement) ─────────────
# Class-level so every provider instance (pipeline + reviewer factories)
# accumulates into one registry per process.
# Pricing (deepseek-chat → deepseek-v4-flash, 2026):
#   input cache miss $0.14 / 1M, cache hit $0.0028 / 1M, output $0.28 / 1M
DEEPSEEK_PRICE_INPUT_MISS = 0.14 / 1_000_000
DEEPSEEK_PRICE_INPUT_HIT = 0.0028 / 1_000_000
DEEPSEEK_PRICE_OUTPUT = 0.28 / 1_000_000

# Current pipeline stage, set by the runner around each stage call so usage
# can be attributed ("research", "script_review", "spec_build", ...).
_usage_stage: ContextVar[str] = ContextVar("deepseek_usage_stage", default="")


def set_usage_stage(stage: str) -> None:
    _usage_stage.set(stage)


class DeepSeekUsage:
    """Per-stage DeepSeek usage registry (class-level, shared)."""

    _stages: dict = {}
    _calls: int = 0

    @classmethod
    def record(cls, input_tokens: int, output_tokens: int,
               cached_input_tokens: int = 0) -> None:
        stage = _usage_stage.get() or "unattributed"
        row = cls._stages.setdefault(stage, {"calls": 0, "input": 0, "output": 0,
                                             "cached": 0})
        row["calls"] += 1
        row["input"] += max(0, int(input_tokens))
        row["output"] += max(0, int(output_tokens))
        row["cached"] += max(0, int(cached_input_tokens))
        cls._calls += 1

    @classmethod
    def summary(cls) -> dict:
        tot = {"calls": 0, "input": 0, "output": 0, "cached": 0, "cost_usd": 0.0}
        stages = {}
        for stage, row in sorted(cls._stages.items()):
            r = dict(row)
            billed_input = r["input"] - r["cached"]
            r["cost_usd"] = round(
                billed_input * DEEPSEEK_PRICE_INPUT_MISS
                + r["cached"] * DEEPSEEK_PRICE_INPUT_HIT
                + r["output"] * DEEPSEEK_PRICE_OUTPUT, 6)
            r["hit_rate"] = round(r["cached"] / max(1, r["input"]), 4)
            stages[stage] = r
            for k in ("calls", "input", "output", "cached"):
                tot[k] += r[k]
            tot["cost_usd"] += r["cost_usd"]
        tot["cost_usd"] = round(tot["cost_usd"], 6)
        tot["hit_rate"] = round(tot["cached"] / max(1, tot["input"]), 4)
        return {"stages": stages, "total": tot}

    @classmethod
    def reset(cls) -> None:
        cls._stages = {}
        cls._calls = 0


# ── Abstract base ──────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """Interface for large-language-model providers."""

    @abstractmethod
    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        """
        Send a prompt (and optional image) to the LLM and return the text response.

        Subclasses that do not support images should ignore *image_path*.
        """
        ...

    def generate_json(self, prompt: str, **kwargs) -> str:
        """
        Convenience wrapper: calls generate_text and strips JSON fence markers.

        The default implementation should be sufficient for most providers.
        """
        raw = self.generate_text(prompt, **kwargs)
        return raw.replace("```json", "").replace("```", "").strip()


# ── DeepSeek ───────────────────────────────────────────────────────────────

class DeepSeekProvider(LLMProvider):
    """LLM provider backed by DeepSeek Chat via LangChain's ChatOpenAI."""

    def __init__(self, **kwargs):
        self._llm = ChatOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url=get_config("providers.deepseek.base_url", "https://api.deepseek.com"),
            model=get_config("llm.deepseek.model", "deepseek-chat"),
            max_tokens=get_config("llm.deepseek.max_tokens", 1000),
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        # Stable system prefix first → DeepSeek prefix-cache hits on every call
        # after the first (and across runs within the cache TTL).
        response = self._llm.invoke([
            SystemMessage(content=DEEPSEEK_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        # ── Usage accounting (DeepSeek token/cost measurement) ──────────
        try:
            um = getattr(response, "usage_metadata", None) or {}
            inp = int(um.get("input_tokens", 0) or 0)
            out = int(um.get("output_tokens", 0) or 0)
            cached = 0
            # OpenAI-compatible cached-token detail (DeepSeek returns it on
            # cache hits; absent => assume full cache miss)
            det = um.get("input_token_details") or um.get("prompt_tokens_details") or {}
            if isinstance(det, dict):
                # langchain surfaces DeepSeek's prompt_cache_hit_tokens as
                # input_token_details.cache_read (snake_case); some providers
                # use cached_tokens. Accept both.
                cached = int(det.get("cache_read") or det.get("cached_tokens") or 0)
            DeepSeekUsage.record(inp, out, cached)
        except Exception:
            pass  # accounting must never break generation
        return response.content


class MistralProvider(LLMProvider):
    """LLM provider backed by Mistral's OpenAI-compatible API (free tier).

    Backup #2 in the v12.6 priority chain (after Gemini flash, before
    DeepSeek). Text-only — used for script review/planning fallbacks and
    script-only video review fallback.
    """

    def __init__(self, **kwargs):
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY not set — add it to .env for "
                               "Mistral free-tier fallback")
        self._llm = ChatOpenAI(
            api_key=api_key,
            base_url=get_config("providers.mistral.base_url",
                                "https://api.mistral.ai/v1"),
            model=get_config("llm.mistral.model", "mistral-small-latest"),
            max_tokens=get_config("llm.mistral.max_tokens", 2000),
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        response = self._llm.invoke([HumanMessage(content=prompt)])
        return response.content


# ── Gemini ─────────────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini (used for multimodal critic)."""

    def __init__(self, **kwargs):
        api_key = os.environ.get("GEMINI_API_KEY")
        self._client = genai.Client(api_key=api_key)
        self._model_name = get_config("llm.gemini.model", "gemini-1.5-flash")

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        if image_path and os.path.exists(image_path):
            img = PIL.Image.open(image_path)
            contents = [prompt, img]
        else:
            contents = [prompt]

        response = self._client.models.generate_content(
            model=self._model_name,
            contents=contents,
        )
        return response.text.strip()


# ── Grok (xAI) ─────────────────────────────────────────────────────────────

class GrokProvider(LLMProvider):
    """LLM provider backed by xAI Grok (OpenAI-compatible endpoint).

    Activated by XAI_API_KEY in .env.  Joins the cost chain ahead of
    DeepSeek (ckdigital direction: leverage Gemini + Grok as much as
    possible, DeepSeek as last resort).
    """

    def __init__(self, **kwargs):
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY not set — add it to .env to enable Grok")
        self._llm = ChatOpenAI(
            api_key=api_key,
            base_url=get_config("providers.grok.base_url", "https://api.x.ai/v1"),
            model=get_config("llm.grok.model", "grok-3"),
            max_tokens=get_config("llm.grok.max_tokens", 2000),
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        response = self._llm.invoke([HumanMessage(content=prompt)])
        return response.content


# ── Groq (OpenAI-compatible, free tier) ───────────────────────────────────

class GroqProvider(LLMProvider):
    """LLM provider backed by Groq (LPU inference, free tier).

    Activated by GROQ_API_KEY in .env.  Joins the cost chain ahead of
    DeepSeek (ckdigital direction: leverage free/cheap providers first).
    """

    def __init__(self, **kwargs):
        _key = os.environ.get("GROQ_API_KEY")
        if not _key:
            raise RuntimeError("GROQ_API_KEY not set — add it to .env to enable Groq")
        self._llm = ChatOpenAI(
            api_key=_key,
            base_url=get_config("providers.groq.base_url", "https://api.groq.com/openai/v1"),
            model=get_config("llm.groq.model", "llama-3.3-70b-versatile"),
            max_tokens=get_config("llm.groq.max_tokens", 2000),
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        response = self._llm.invoke([HumanMessage(content=prompt)])
        return response.content



# ── NVIDIA NIM (Nemotron) — OpenAI-compatible, build credits ────────────────

class NemotronProvider(LLMProvider):
    """LLM provider backed by NVIDIA NIM (integrate.api.nvidia.com).

    Activated by NVIDIA_API_KEY in .env.  Model default
    nvidia/nemotron-3-super-120b-a12b (verified working on the audit;
    ~14-20s/call — slow but stable).  Joins the cost chain as an
    experiment head via LLM_ROUTING_EXPERIMENT=nemotron.
    """

    def __init__(self, **kwargs):
        _key = os.environ.get("NVIDIA_API_KEY")
        if not _key:
            raise RuntimeError("NVIDIA_API_KEY not set — add it to .env to enable Nemotron")
        self._llm = ChatOpenAI(
            api_key=_key,
            base_url=get_config("providers.nemotron.base_url",
                                "https://integrate.api.nvidia.com/v1"),
            model=get_config("llm.nemotron.model", "nvidia/nemotron-3-super-120b-a12b"),
            max_tokens=get_config("llm.nemotron.max_tokens", 4000),
            timeout=get_config("llm.nemotron.timeout", 180),
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        response = self._llm.invoke([HumanMessage(content=prompt)])
        return response.content


# ── OpenRouter (aggregator, free models available) ──────────────────────────

class OpenRouterProvider(LLMProvider):
    """LLM provider backed by OpenRouter (model aggregator).

    Activated by OPENROUTER_API_KEY in .env.  Default model is a free
    tier model; override via llm.openrouter.model in models.yaml.
    """

    def __init__(self, **kwargs):
        _key = os.environ.get("OPENROUTER_API_KEY")
        if not _key:
            raise RuntimeError("OPENROUTER_API_KEY not set — add it to .env to enable OpenRouter")
        self._llm = ChatOpenAI(
            api_key=_key,
            base_url=get_config("providers.openrouter.base_url", "https://openrouter.ai/api/v1"),
            model=get_config("llm.openrouter.model", "google/gemma-4-26b-a4b-it:free"),
            max_tokens=get_config("llm.openrouter.max_tokens", 2000),
            default_headers={
                "HTTP-Referer": "https://github.com/ckdigitalyt/video_engine",
                "X-Title": "video_engine",
            },
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        response = self._llm.invoke([HumanMessage(content=prompt)])
        return response.content


# ── Runtime fallback chain ─────────────────────────────────────────────────

class ChainLLMProvider(LLMProvider):
    """Tries providers in order; first success wins.

    Lets the pipeline use free/cheap providers (Gemini, Grok, Mistral)
    as much as possible and only falls through to paid DeepSeek when
    everything else fails (or is missing a key / quota-limited).
    """

    def __init__(self, providers: list[LLMProvider]):
        self._providers = [p for p in providers if p is not None]
        # v19g (ckdigital direction): per-call attribution — record which
        # provider actually ANSWERED each call so the pipeline logs "who
        # wrote what" instead of hiding it inside a silent chain.
        self._usage: dict[str, int] = {}
        self._last_provider: Optional[str] = None

    def _record(self, provider: LLMProvider) -> None:
        name = type(provider).__name__.replace("Provider", "")
        self._usage[name] = self._usage.get(name, 0) + 1
        self._last_provider = name
        print(f"    [chain] answered by {name} (cumulative {dict(self._usage)})",
              flush=True)

    def usage(self) -> dict[str, int]:
        """Per-provider call counts for run_report attribution.

        Returns the LIVE dict so run_report entries written at startup
        reflect the full run's attribution when the report is saved at
        the end.
        """
        return self._usage

    def last_provider(self) -> Optional[str]:
        return self._last_provider

    def _attempt(self, p: LLMProvider, fn, json_mode: bool):
        """Run one provider attempt with telemetry. Returns (out, None) or
        (None, exc).  Never raises for telemetry itself."""
        from src.providers.llm_telemetry import record, classify_error
        name = type(p).__name__.replace("Provider", "")
        t0 = time.time()
        try:
            out = fn(p)
            lat = time.time() - t0
            json_ok = None
            if json_mode:
                try:
                    json.loads(out.replace("```json", "").replace("```", "").strip())
                    json_ok = True
                except Exception:
                    json_ok = False
            record(provider=name, ok=True, latency_s=lat, json_ok=json_ok,
                   chain_pos=self._providers.index(p) + 1,
                   model=getattr(getattr(p, "_llm", None), "model_name", None))
            return out, None
        except Exception as exc:  # noqa: BLE001 — try next provider
            record(provider=name, ok=False, latency_s=time.time() - t0,
                   error_class=classify_error(exc),
                   chain_pos=self._providers.index(p) + 1,
                   model=getattr(getattr(p, "_llm", None), "model_name", None))
            return None, exc

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        last: Optional[Exception] = None
        for p in self._providers:
            out, exc = self._attempt(p,
                                     lambda pp: pp.generate_text(prompt, image_path=image_path, **kwargs),
                                     json_mode=False)
            if exc is None:
                self._record(p)
                return out
            last = exc
        raise RuntimeError(f"ChainLLMProvider: all providers failed ({last})")

    def generate_json(self, prompt: str, **kwargs) -> str:
        last: Optional[Exception] = None
        for p in self._providers:
            out, exc = self._attempt(p,
                                     lambda pp: pp.generate_text(prompt, **kwargs),
                                     json_mode=True)
            if exc is None:
                self._record(p)
                return out.replace("```json", "").replace("```", "").strip()
            last = exc
        raise RuntimeError(f"ChainLLMProvider: all providers failed ({last})")
