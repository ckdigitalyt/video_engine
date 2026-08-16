"""Centralized configuration — merges YAML configs and the StyleSpec v1.

DeepSeek never invents its own visual aesthetic. Every stage merges against
this spec so all videos feel like one production system (directive §13).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml

ENGINE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ENGINE_ROOT.parent
CONFIG_DIR = ENGINE_ROOT / "config"


class _Config:
    _cache: dict[str, Any] = {}
    _style: Optional[dict] = None

    @classmethod
    def load(cls, reload: bool = False) -> dict:
        if cls._cache and not reload:
            return cls._cache

        merged: dict[str, Any] = {}
        for path in sorted(CONFIG_DIR.glob("*.yaml")):
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            merged[path.stem] = data

        # Normalize: if a config file is itself wrapped under its own key
        # (e.g. style.yaml -> {"style": {...}}), unwrap so dot access works
        # uniformly as get('style.background') -> dict['style']['background'].
        for key, val in list(merged.items()):
            if isinstance(val, dict) and key in val:
                merged[key] = val[key]

        # load legacy style.yaml if it exists at project root (configs/)
        legacy = PROJECT_ROOT / "configs" / "style.yaml"
        if legacy.exists():
            with open(legacy, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            merged.setdefault("style", data.get("style", data))

        cls._cache = merged
        return merged

    @classmethod
    def get(cls, dot_path: str, default: Any = None) -> Any:
        """Dot-notation access, e.g. get('style.background')."""
        data = cls.load()
        cur: Any = data
        for part in dot_path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    @classmethod
    def style(cls) -> dict:
        """Return the StyleSpec as a plain dict (with version tag)."""
        if cls._style is None:
            raw = cls.get("style", {})
            if "version" not in raw:
                raw["version"] = "v1"
            cls._style = raw
        return cls._style

    @classmethod
    def style_json(cls) -> str:
        """StyleSpec serialized for LLM prompts."""
        return json.dumps(cls.style(), indent=2)


def load_config(reload: bool = False) -> dict:
    """Compatibility shim matching the old get_config surface."""
    return _Config.load(reload)


def get_config(dot_path: str, default: Any = None) -> Any:
    return _Config.get(dot_path, default)


def get_style() -> dict:
    return _Config.style()


if __name__ == "__main__":
    print("style keys:", sorted(get_style().keys()))
    print("background:", get_config("style.background"))
