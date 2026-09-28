"""The ONE LLM adapter (DESIGN §2): ask(stage, prompt, ...) -> LLMResult.

Callers name a stage only; provider/model/effort come from configs/llm.yaml.
Retry, one schema-repair round, quota cooldown, cache and usage ledger live here.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema

from llm.env import env_key
from llm.config import REPO, load_config, stage_settings
from llm.jsonutil import extract_json
from llm.providers import make_provider
from llm.types import (LLMResult, LLMSchemaError, LLMUnavailable, RawRequest,
                       RawResponse)

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
BACKOFF_S = (5, 20)                 # transport retries: same provider x2
DEFAULT_COOLDOWN = timedelta(hours=1)

_sleep = time.sleep                 # patched in tests
_cfg: dict | None = None
_providers: dict = {}


def build_dir() -> Path:
    return Path(os.environ.get("LLM_BUILD_DIR") or REPO / "illustrated_engine" / "build")


def reset() -> None:
    """Drop cached config/provider instances (tests, config edits)."""
    global _cfg
    _cfg = None
    _providers.clear()


def _config() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


def _provider(name: str):
    if name not in _providers:
        _providers[name] = make_provider(name, _config()["providers"][name])
    return _providers[name]


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------- state --

def _state_path() -> Path:
    return build_dir() / "llm_state.json"


def _cooldown_until(provider: str) -> datetime | None:
    try:
        ts = json.loads(_state_path().read_text()).get("cooldown", {}).get(provider)
    except Exception:
        return None
    until = datetime.fromisoformat(ts) if ts else None
    return until if until and until > datetime.now(timezone.utc) else None


def _set_cooldown(provider: str, until: datetime) -> None:
    p = _state_path()
    try:
        state = json.loads(p.read_text())
    except Exception:
        state = {}
    state.setdefault("cooldown", {})[provider] = until.isoformat()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1))


def _ledger(row: dict) -> None:
    p = build_dir() / "llm_ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------- cache --

def cache_key(stage: str, prompt_version: str, provider: str, model: str, prompt: str,
              images: list[Path], schema: dict | None, temperature=None) -> str:
    h = hashlib.sha256()
    for part in (stage, prompt_version, provider, model, prompt,
                 json.dumps(schema, sort_keys=True), str(temperature)):
        h.update(part.encode())
        h.update(b"\0")
    for img in images:
        h.update(hashlib.sha256(Path(img).read_bytes()).digest())
    return h.hexdigest()


def _cache_file(key: str) -> Path:
    return build_dir() / "cache" / "llm" / f"{key}.json"


# ------------------------------------------------------------------ ask --

def _validate(schema: dict | None, resp: RawResponse) -> tuple[dict | None, list[str]]:
    """Always re-validate ourselves; never trust the provider's validation alone."""
    if schema is None:
        return None, [] if resp.text.strip() else ["empty response"]
    data = resp.data if isinstance(resp.data, dict) else extract_json(resp.text)
    if not isinstance(data, dict):
        return None, ["output is not a JSON object"]
    errs = sorted(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
                  for e in jsonschema.Draft202012Validator(schema).iter_errors(data))
    return (None, errs[:8]) if errs else (data, [])


def ask(stage: str, prompt: str, *, schema: str | None = None, images: list[Path] = (),
        prompt_version: str = "", cache: bool = True, temperature: float | None = None,
        max_tokens: int | None = None) -> LLMResult:
    cfg = _config()
    s = stage_settings(cfg, stage)
    schema_obj = load_schema(schema) if schema else None
    images = [Path(i) for i in images]
    t0 = time.time()
    attempts = 0
    unavailable: list[LLMUnavailable] = []
    schema_failed = False

    for pname, model in s["chain"]:
        spec = cfg["providers"][pname]
        if not spec.get("enabled", True):
            continue
        until = _cooldown_until(pname)
        if until:
            unavailable.append(LLMUnavailable(f"{pname} in cooldown", "quota", until))
            continue
        key = cache_key(stage, prompt_version, pname, model, prompt, images, schema_obj, temperature)
        if cache and _cache_file(key).exists():
            c = json.loads(_cache_file(key).read_text())
            _ledger({"ts": time.time(), "stage": stage, "provider": pname, "model": model,
                     "cached": True, "attempts": 0, "latency_s": 0.0, "usage": {}})
            return LLMResult(c["data"], c["text"], stage, pname, model, 0, 0.0, True, c.get("usage", {}))

        provider = _provider(pname)
        cur_prompt, repaired = prompt, False
        transport_tries = 0
        while True:
            attempts += 1
            resp = provider.complete(RawRequest(
                system="", prompt=cur_prompt, images=images, schema=schema_obj, model=model,
                effort=s["effort"], timeout_s=s["timeout_s"], temperature=temperature,
                max_tokens=max_tokens))
            if resp.error_kind == "auth":
                _ledger({"ts": time.time(), "stage": stage, "provider": pname, "model": model,
                         "cached": False, "attempts": attempts, "error": "auth"})
                raise LLMUnavailable(f"{pname}: authentication failed ({resp.error[:120]})", "auth")
            if resp.error_kind == "quota":
                until = resp.retry_at or datetime.now(timezone.utc) + DEFAULT_COOLDOWN
                _set_cooldown(pname, until)
                unavailable.append(LLMUnavailable(f"{pname}: quota ({resp.error[:120]})", "quota", until))
                break
            if resp.error_kind == "transport":
                if transport_tries < min(len(BACKOFF_S), s["max_attempts"]):
                    _sleep(BACKOFF_S[transport_tries])
                    transport_tries += 1
                    continue
                unavailable.append(LLMUnavailable(f"{pname}: {resp.error[:120]}", "outage"))
                break
            data, errs = _validate(schema_obj, resp)
            if not errs:
                latency = round(time.time() - t0, 2)
                if cache:
                    _cache_file(key).parent.mkdir(parents=True, exist_ok=True)
                    _cache_file(key).write_text(json.dumps(
                        {"data": data, "text": resp.text, "usage": resp.usage}))
                _ledger({"ts": time.time(), "stage": stage, "provider": pname, "model": model,
                         "cached": False, "attempts": attempts, "latency_s": latency,
                         "usage": resp.usage})
                return LLMResult(data, resp.text, stage, pname, model, attempts, latency,
                                 False, resp.usage)
            schema_failed = True
            if repaired:
                break                       # next chain member
            repaired = True                 # one repair round
            cur_prompt = (f"{prompt}\n\nYour previous output failed validation: "
                          f"{'; '.join(errs)}. Return only the corrected JSON.")

    if schema_failed:
        raise LLMSchemaError(f"stage {stage!r}: output invalid after repair on every provider")
    if not unavailable:
        raise LLMUnavailable(f"stage {stage!r}: no enabled provider in chain", "outage")
    kinds = {u.kind for u in unavailable}
    kind = "quota" if "quota" in kinds else "outage"
    retry_ats = [u.retry_at for u in unavailable if u.retry_at]
    raise LLMUnavailable("; ".join(str(u) for u in unavailable), kind,
                         min(retry_ats) if retry_ats and kind == "quota" else None)


def available(stage: str) -> bool:
    """True if some enabled provider in the stage's chain could be called now."""
    import shutil
    cfg = _config()
    for pname, _model in stage_settings(cfg, stage)["chain"]:
        spec = cfg["providers"][pname]
        if not spec.get("enabled", True) or _cooldown_until(pname):
            continue
        if spec["type"] == "claude_cli":
            if shutil.which(spec.get("bin", "claude")):
                return True
        elif env_key(spec.get("key_env", "")):
            return True
    return False


def warn(msg: str) -> None:
    print(f"[llm] {msg}", file=sys.stderr, flush=True)
