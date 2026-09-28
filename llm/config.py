"""Load + validate configs/llm.yaml (DESIGN §2.2). Fails at startup on unknown stages/providers."""
from __future__ import annotations

from pathlib import Path

import jsonschema
import yaml

REPO = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO / "configs" / "llm.yaml"

STAGES = {
    "topic_ideate", "topic_score", "research_extract", "script_write", "script_critic",
    "fact_check", "metadata_pack", "visual_plan", "plate_qa", "final_judge",
    "text_misc", "vision_misc", "bench_judge",
}
PROVIDER_TYPES = ("claude_cli", "gemini", "openrouter")

_STAGE_ENTRY = {
    "type": "object",
    "properties": {
        "provider": {"type": "string"}, "model": {"type": "string"}, "effort": {"type": "string"},
        "vision": {"type": "boolean"}, "required": {"type": "boolean"}, "pinned": {"type": "boolean"},
        "timeout_s": {"type": "number"}, "max_attempts": {"type": "integer", "minimum": 1},
    },
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "required": ["version", "defaults", "providers", "stages"],
    "properties": {
        "version": {"const": 1},
        "defaults": _STAGE_ENTRY,
        "providers": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["type"],
            "properties": {"type": {"enum": list(PROVIDER_TYPES)}, "enabled": {"type": "boolean"},
                           "bin": {"type": "string"}, "fallback_model": {"type": "string"},
                           "key_env": {"type": "string"}, "model": {"type": "string"}}}},
        "stages": {"type": "object", "additionalProperties": _STAGE_ENTRY},
        "chains": {"type": "object", "additionalProperties": {
            "type": "array", "items": {"type": "string", "pattern": "^[a-z_]+(:[^:\\s]+)?$"}}},
    },
}


class ConfigError(ValueError):
    pass


def load_config(path: Path | None = None) -> dict:
    cfg = yaml.safe_load(Path(path or CONFIG_PATH).read_text())
    try:
        jsonschema.validate(cfg, SCHEMA)
    except jsonschema.ValidationError as e:
        raise ConfigError(f"llm.yaml invalid: {e.message}") from None
    providers = cfg["providers"]
    if cfg["defaults"].get("provider") not in providers:
        raise ConfigError("llm.yaml: defaults.provider is not a declared provider")
    for stage, ent in cfg["stages"].items():
        if stage not in STAGES:
            raise ConfigError(f"llm.yaml: unknown stage {stage!r}")
        if ent.get("provider", cfg["defaults"]["provider"]) not in providers:
            raise ConfigError(f"llm.yaml: stage {stage!r} names an undeclared provider")
        if ent.get("pinned") and not (ent.get("provider") and ent.get("model")):
            raise ConfigError(f"llm.yaml: pinned stage {stage!r} must set provider and model")
    for stage, members in (cfg.get("chains") or {}).items():
        if stage not in STAGES:
            raise ConfigError(f"llm.yaml: chain for unknown stage {stage!r}")
        for m in members:
            if m.split(":")[0] not in providers:
                raise ConfigError(f"llm.yaml: chain {stage!r} member {m!r} is an undeclared provider")
    return cfg


def stage_settings(cfg: dict, stage: str) -> dict:
    """defaults <- stage entry, plus the ordered [(provider, model)] chain."""
    if stage not in STAGES:
        raise ConfigError(f"unknown LLM stage {stage!r}")
    s = {**cfg["defaults"], **cfg["stages"].get(stage, {})}
    chain = [(m.split(":")[0], m.split(":")[1] if ":" in m else s["model"])
             for m in (cfg.get("chains") or {}).get(stage, [])]
    s["chain"] = chain or [(s["provider"], s["model"])]
    return s
