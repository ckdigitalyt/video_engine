"""
llm_telemetry.py — per-call LLM telemetry for the routing experiment.

Every LLM invocation (chain attempts, direct gate calls) records a row:
provider, pipeline stage, latency, success/failure, error class
(403 / 429 / timeout / other), JSON validity, chain position, and
whether the call was answered by the experiment head or fell through
to DeepSeek.

The records are aggregated into a per-provider summary (for run_report)
and appended to a JSONL file under logs/llm_metrics/ for offline
head-to-head analysis (Groq vs Nemotron vs DeepSeek).

Design rules:
- Class-level registry shared across the process (like DeepSeekUsage).
- Stage attribution reuses the existing `_usage_stage` ContextVar set by
  the runners around each pipeline stage.
- Telemetry must NEVER break generation — every hook is try/except.
- The experiment is purely observational: setting LLM_ROUTING_EXPERIMENT
  only changes which provider sits at the chain head; unset leaves the
  production chain untouched.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextvars import ContextVar
from typing import Optional

from .llm_provider import LLMProvider

# Reuse the runner's stage attribution ("research", "script_review", ...).
from .llm_provider import _usage_stage as _stage_ctx  # noqa: F401

_run: str = "default"
_records: list[dict] = []
_lock = threading.Lock()
_OUT_DIR = os.path.join("logs", "llm_metrics")


def set_run(tag: str) -> None:
    """Tag all subsequent records with a run id (slug + timestamp)."""
    global _run
    _run = tag or "default"


def _stage() -> str:
    try:
        return _stage_ctx.get() or "unattributed"
    except Exception:
        return "unattributed"


def classify_error(exc: BaseException) -> str:
    """Map an exception to a coarse error class for the report."""
    s = str(exc or "").lower()
    if "429" in s or "resource_exhausted" in s.replace("_", "") or "quota" in s:
        return "429"
    if "403" in s or "forbidden" in s or "cloudflare" in s:
        return "403"
    if "401" in s or "unauthorized" in s or "invalid api key" in s:
        return "401"
    if "404" in s:
        return "404"
    if "timeout" in s or "timed out" in s:
        return "timeout"
    if "connection" in s or "refused" in s or "unreachable" in s or "resolve" in s:
        return "connection"
    if "500" in s or "502" in s or "503" in s or "504" in s:
        return "5xx"
    return "other"


def record(
    provider: str,
    ok: bool,
    latency_s: float,
    error_class: Optional[str] = None,
    json_ok: Optional[bool] = None,
    chain_pos: Optional[int] = None,
    via_chain: bool = True,
    stage: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """Append one call record (thread-safe, never raises)."""
    try:
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run": _run,
            "stage": stage or _stage(),
            "provider": provider,
            "ok": bool(ok),
            "latency_s": round(float(latency_s or 0.0), 3),
            "error_class": error_class,
            "json_ok": json_ok,
            "chain_pos": chain_pos,
            "via_chain": via_chain,
            "model": model,
        }
        with _lock:
            _records.append(row)
    except Exception:
        pass


def summary() -> dict:
    """Per-provider aggregates for run_report."""
    agg: dict[str, dict] = {}
    with _lock:
        rows = list(_records)
    for r in rows:
        p = r["provider"]
        a = agg.setdefault(p, {
            "calls": 0, "ok": 0, "fail": 0,
            "errors": {}, "latency_s": [], "json_ok": 0, "json_tried": 0,
            "deepseek_gate": 0,
        })
        a["calls"] += 1
        if r["ok"]:
            a["ok"] += 1
        else:
            a["fail"] += 1
            cls = r.get("error_class") or "other"
            a["errors"][cls] = a["errors"].get(cls, 0) + 1
        if r.get("latency_s") is not None:
            a["latency_s"].append(r["latency_s"])
        if r.get("json_ok") is not None:
            a["json_tried"] += 1
            if r["json_ok"]:
                a["json_ok"] += 1
        if not r.get("via_chain", True):
            a["deepseek_gate"] += 1

    out = {}
    for p, a in agg.items():
        lat = sorted(a["latency_s"])
        n = len(lat)
        out[p] = {
            "calls": a["calls"],
            "ok": a["ok"],
            "fail": a["fail"],
            "success_rate": round(a["ok"] / max(1, a["calls"]), 4),
            "errors": a["errors"],
            "avg_latency_s": round(sum(lat) / max(1, n), 2),
            "p50_latency_s": round(lat[n // 2], 2) if n else None,
            "p95_latency_s": round(lat[min(n - 1, int(0.95 * n))], 2) if n else None,
            "json_valid_rate": round(a["json_ok"] / max(1, a["json_tried"]), 4) if a["json_tried"] else None,
            "direct_gate_calls": a["deepseek_gate"],
        }
    return out


def records() -> list[dict]:
    with _lock:
        return list(_records)


def save(path: Optional[str] = None) -> str:
    """Append all records as JSONL. Returns the file path written."""
    try:
        os.makedirs(_OUT_DIR, exist_ok=True)
        path = path or os.path.join(_OUT_DIR, f"{_run or 'run'}.jsonl")
        with _lock:
            rows = list(_records)
        with open(path, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        return path
    except Exception:
        return ""


def reset() -> None:
    global _run
    with _lock:
        _records.clear()
    _run = "default"


class TelemetryWrappedProvider(LLMProvider):
    """Records every call on a DIRECT (non-chain) provider.

    Used for the DeepSeek final gate (claim verification + final
    script-review pass) so those calls are visible in the telemetry
    even though they bypass ChainLLMProvider.
    """

    def __init__(self, inner: LLMProvider, label: Optional[str] = None,
                 stage: Optional[str] = None):
        self._inner = inner
        self._label = label or type(inner).__name__.replace("Provider", "")
        self._stage = stage

    def _emit(self, ok: bool, latency_s: float, error_class: Optional[str],
              json_ok: Optional[bool] = None) -> None:
        record(
            provider=self._label,
            ok=ok,
            latency_s=latency_s,
            error_class=error_class,
            json_ok=json_ok,
            via_chain=False,
            stage=self._stage,
            model=getattr(getattr(self._inner, "_llm", None), "model_name", None),
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        t0 = time.time()
        try:
            out = self._inner.generate_text(prompt, image_path=image_path, **kwargs)
            self._emit(True, time.time() - t0, None)
            return out
        except Exception as e:  # noqa: BLE001
            self._emit(False, time.time() - t0, classify_error(e))
            raise

    def generate_json(self, prompt: str, **kwargs) -> str:
        t0 = time.time()
        try:
            raw = self._inner.generate_text(prompt, **kwargs)
            stripped = raw.replace("```json", "").replace("```", "").strip()
            json_ok = None
            try:
                json.loads(stripped)
                json_ok = True
            except Exception:
                json_ok = False
            self._emit(True, time.time() - t0, None, json_ok=json_ok)
            return stripped
        except Exception as e:  # noqa: BLE001
            self._emit(False, time.time() - t0, classify_error(e))
            raise
