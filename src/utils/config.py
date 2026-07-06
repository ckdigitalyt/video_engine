"""
config.py — Centralized configuration loader for the video_engine pipeline.

Loads YAML configuration files from the configs/ directory into a single
nested dictionary. All pipeline modules should import config values from
this module instead of using hard-coded literals.

Usage:
    from src.utils.config import load_config

    cfg = load_config()
    model_name = cfg["llm"]["deepseek"]["model"]
    fps = cfg["render"]["fps"]
"""

import os
import yaml

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "configs")
_CONFIG_DIR = os.path.abspath(_CONFIG_DIR)

_CONFIG_FILES = [
    "models.yaml",
    "render.yaml",
    "pipeline.yaml",
    "providers.yaml",
    "voices.yaml",
    "logging.yaml",
]

_cache = None


def load_config(reload: bool = False) -> dict:
    """
    Load and merge all YAML config files into one dictionary.

    Results are cached after the first call.  Pass reload=True to force
    re-reading from disk.
    """
    global _cache
    if _cache is not None and not reload:
        return _cache

    merged = {}
    for filename in _CONFIG_FILES:
        path = os.path.join(_CONFIG_DIR, filename)
        if os.path.exists(path):
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            if data is not None:
                merged.update(data)
        else:
            print(f"Warning: config file not found: {path}")

    _cache = merged
    return merged


def get_config(key: str, default=None):
    """
    Get a specific config value using dot-separated key notation.

    Example:
        fps = get_config("render.fps", 30)
        model = get_config("llm.deepseek.model")
    """
    cfg = load_config()
    parts = key.split(".")
    val = cfg
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
            if val is None:
                return default
        else:
            return default
    return val
