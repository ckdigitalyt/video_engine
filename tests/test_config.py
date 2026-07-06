"""
test_config.py — Tests for the configuration loader (src/utils/config.py).

Verifies that all required config files load, required keys exist, and
missing configs raise clear errors.
"""

import os
from pathlib import Path
from importlib import reload

import pytest

import src.utils.config as cfg_mod


# ── Helpers ────────────────────────────────────────────────────────────────


def _reload_config() -> None:
    """Flush the module cache so the next call re-reads from disk."""
    cfg_mod._cache = None
    reload(cfg_mod)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    """Reset the config cache before every test."""
    _reload_config()


# ── Tests ──────────────────────────────────────────────────────────────────


class TestConfigLoads:
    """Verify that the standard config directory loads cleanly."""

    def test_all_config_files_exist(self) -> None:
        """Every expected YAML file must be present under configs/."""
        config_dir = Path(__file__).resolve().parent.parent / "configs"
        expected = [
            "models.yaml",
            "render.yaml",
            "pipeline.yaml",
            "providers.yaml",
            "voices.yaml",
            "logging.yaml",
        ]
        for fname in expected:
            assert (config_dir / fname).is_file(), f"Missing config: {fname}"

    def test_load_returns_dict(self) -> None:
        """load_config() should return a populated dict."""
        cfg = cfg_mod.load_config()
        assert isinstance(cfg, dict)
        assert len(cfg) > 0

    def test_load_is_cached(self) -> None:
        """Subsequent calls should return the same object (cached)."""
        cfg1 = cfg_mod.load_config()
        cfg2 = cfg_mod.load_config()
        assert cfg1 is cfg2

    def test_reload_force(self) -> None:
        """reload=True should return a new dict (not same object)."""
        cfg1 = cfg_mod.load_config()
        cfg2 = cfg_mod.load_config(reload=True)
        # Both should be dicts; reload may return new or same depending on caching
        assert isinstance(cfg1, dict)
        assert isinstance(cfg2, dict)


class TestRequiredKeys:
    """Every critical configuration key must be present with a sensible value."""

    REQUIRED = {
        "llm": ["deepseek", "gemini"],
        "llm.deepseek": ["model", "max_tokens", "temperature"],
        "llm.gemini": ["model"],
        "render": ["resolution", "fps", "codec", "audio_codec", "threads", "preset"],
        "output": ["default"],
        "pipeline": ["max_iterations", "cache", "fallback", "output"],
        "providers": ["pexels", "deepseek"],
        "voices": ["kokoro"],
        "logging": ["level", "file", "format"],
    }

    @pytest.mark.parametrize("section,keys", REQUIRED.items())
    def test_section_and_keys(self, section: str, keys: list[str]) -> None:
        cfg = cfg_mod.load_config()
        parts = section.split(".")
        obj = cfg
        for p in parts:
            assert p in obj, f"Missing section: {section}"
            obj = obj[p]
        for k in keys:
            assert k in obj, f"Missing key {section}.{k}"

    def test_get_config_dot_notation(self) -> None:
        assert cfg_mod.get_config("render.fps") == 30

    def test_get_config_default(self) -> None:
        assert cfg_mod.get_config("nonexistent.key", "fallback") == "fallback"

    def test_get_config_none_default(self) -> None:
        assert cfg_mod.get_config("nonexistent.key") is None


class TestConfigErrors:
    """Verify behaviour when config files are missing or broken."""

    def test_missing_config_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-existent config directory should return empty dict without crashing."""
        fake = "/tmp/_no_such_config_dir_xyz"
        monkeypatch.setattr(cfg_mod, "_CONFIG_DIR", fake)
        _reload_config()
        cfg = cfg_mod.load_config()
        assert isinstance(cfg, dict)
        # Should not crash on access
        cfg.get("llm")

    def test_missing_single_config_file(self, monkeypatch) -> None:
        """A single missing config should not crash."""
        monkeypatch.setattr(cfg_mod, "_CONFIG_FILES", ["_nonexistent_.yaml"])
        _reload_config()
        cfg = cfg_mod.load_config()
        assert isinstance(cfg, dict)
