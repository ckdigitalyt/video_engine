"""
test_provider_interfaces.py — Tests for provider abstract bases and mocks.

Verifies that all concrete providers satisfy their ABC interfaces, handle
errors gracefully, and can be instantiated with mocked dependencies.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from abc import ABC, abstractmethod

from src.providers.asset_provider import AssetProvider, PexelsProvider
from src.providers.llm_provider import LLMProvider, DeepSeekProvider, GeminiProvider
from src.providers.tts_provider import TTSProvider, KokoroProvider


# ── Interface compliance ───────────────────────────────────────────────────


class TestInterfaceCompliance:
    """Every concrete provider must implement every abstract method."""

    @pytest.mark.parametrize("provider_cls", [DeepSeekProvider, GeminiProvider])
    def test_llm_providers_have_all_methods(self, provider_cls: type) -> None:
        assert issubclass(provider_cls, LLMProvider)
        assert hasattr(provider_cls, "generate_text")
        assert callable(getattr(provider_cls, "generate_text"))
        # generate_json has a concrete default → should be callable
        assert hasattr(provider_cls, "generate_json")
        assert callable(getattr(provider_cls, "generate_json"))

    def test_asset_provider_has_all_methods(self) -> None:
        assert issubclass(PexelsProvider, AssetProvider)
        assert hasattr(PexelsProvider, "search")
        assert callable(getattr(PexelsProvider, "search"))
        assert hasattr(PexelsProvider, "download")
        assert callable(getattr(PexelsProvider, "download"))

    def test_tts_provider_has_all_methods(self) -> None:
        assert issubclass(KokoroProvider, TTSProvider)
        assert hasattr(KokoroProvider, "generate_voice")
        assert callable(getattr(KokoroProvider, "generate_voice"))

    def test_abc_cannot_be_instantiated(self) -> None:
        """Abstract base classes should raise TypeError."""
        for abc_cls in (LLMProvider, AssetProvider, TTSProvider):
            with pytest.raises(TypeError):
                abc_cls()  # type: ignore


# ── DeepSeekProvider ───────────────────────────────────────────────────────


class TestDeepSeekProvider:
    def test_generate_text_returns_string(self, mock_deepseek_llm: MagicMock) -> None:
        provider = DeepSeekProvider()
        result = provider.generate_text("Hello")
        assert isinstance(result, str)

    def test_generate_text_calls_invoke(self, mock_deepseek_llm: MagicMock) -> None:
        provider = DeepSeekProvider()
        provider.generate_text("test prompt")
        assert mock_deepseek_llm.return_value.invoke.called

    def test_generate_json_strips_fence(self, mock_deepseek_llm: MagicMock) -> None:
        mock_deepseek_llm.return_value.invoke.return_value.content = (
            "```json\n{\"key\": \"value\"}\n```"
        )
        provider = DeepSeekProvider()
        result = provider.generate_json("json prompt")
        assert result == '{"key": "value"}'

    def test_instantiation_without_env_key(self, monkeypatch: pytest.MonkeyPatch, mock_deepseek_llm: MagicMock) -> None:
        """Should not crash when env var is missing (LangChain handles None)."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        try:
            provider = DeepSeekProvider()
            assert provider is not None
        except Exception:
            pytest.fail("DeepSeekProvider should not crash on missing env key")


# ── GeminiProvider ─────────────────────────────────────────────────────────


class TestGeminiProvider:
    def test_generate_text_returns_string(self, mock_gemini_llm: MagicMock) -> None:
        provider = GeminiProvider()
        result = provider.generate_text("Hello")
        assert isinstance(result, str)
        assert result == "APPROVED"

    def test_generate_text_with_image_path(self, mock_gemini_llm: MagicMock, tmp_path: Path) -> None:
        """Should include image in contents when image_path exists."""
        import PIL.Image
        img = tmp_path / "test.png"
        # Create a valid 1x1 PNG
        PIL.Image.new("RGB", (1, 1), color="red").save(str(img))
        provider = GeminiProvider()
        result = provider.generate_text("Describe", image_path=str(img))
        assert result == "APPROVED"
        # The mock's generate_content should have been called
        assert mock_gemini_llm.return_value.generate_content.called

    def test_generate_text_without_image(self, mock_gemini_llm: MagicMock) -> None:
        """No image → only text prompt is sent."""
        provider = GeminiProvider()
        provider.generate_text("Hello")
        call_args = mock_gemini_llm.return_value.generate_content.call_args[0][0]
        assert isinstance(call_args, list)
        assert len(call_args) == 1  # only prompt text

    def test_instantiation_without_env_key(self, monkeypatch: pytest.MonkeyPatch, mock_gemini_llm: MagicMock) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiProvider()
        assert provider is not None


# ── PexelsProvider ─────────────────────────────────────────────────────────


class TestPexelsProvider:
    def test_search_returns_list(self, mock_pexels_api: MagicMock) -> None:
        provider = PexelsProvider()
        results = provider.search("space")
        assert isinstance(results, list)

    def test_cache_miss_calls_api(self, mock_pexels_api: MagicMock) -> None:
        provider = PexelsProvider()
        provider.search("milky way")
        assert mock_pexels_api.called

    def test_search_result_has_link(self, mock_pexels_api: MagicMock) -> None:
        provider = PexelsProvider()
        results = provider.search("space")
        assert len(results) > 0
        assert results[0]["video_files"][0]["link"] == "https://test.pexels.com/video.mp4"

    def test_download_with_existing_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Should skip download if file already exists."""
        f = tmp_path / "exists.mp4"
        f.write_bytes(b"existing content")

        mock_get = MagicMock()
        monkeypatch.setattr("src.providers.asset_provider.requests.get", mock_get)

        provider = PexelsProvider()
        result = provider.download("https://url/v.mp4", str(f))
        assert result == str(f)
        mock_get.assert_not_called()  # no HTTP request

    def test_download_new_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_pexels_api: MagicMock) -> None:
        """Should download and save when file does not exist."""
        f = tmp_path / "new.mp4"
        mock_resp = MagicMock()
        mock_resp.content = b"downloaded content"
        monkeypatch.setattr("src.providers.asset_provider.requests.get", lambda url, **kw: mock_resp)

        provider = PexelsProvider()
        result = provider.download("https://url/v.mp4", str(f))
        assert result == str(f)
        assert f.exists()
        assert f.read_bytes() == b"downloaded content"


# ── KokoroProvider ─────────────────────────────────────────────────────────


class TestKokoroProvider:
    def test_instantiation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KokoroProvider should instantiate without loading the engine."""
        monkeypatch.setattr("src.providers.tts_provider.Kokoro", MagicMock)
        provider = KokoroProvider()
        assert provider._engine is None  # not loaded yet

    def test_lazy_load(self, mock_kokoro_tts: MagicMock) -> None:
        """Calling generate_voice should trigger lazy-loading."""
        provider = KokoroProvider()
        provider.generate_voice("hello", "/tmp/test.wav")
        assert provider._engine is not None

    def test_generate_voice_calls_create(self, mock_kokoro_tts: MagicMock) -> None:
        provider = KokoroProvider()
        provider.generate_voice("hello world", "/tmp/test.wav")
        assert mock_kokoro_tts.return_value.create.called

    def test_generate_voice_writes_file(self, mock_kokoro_tts: MagicMock, tmp_path: Path) -> None:
        from unittest.mock import ANY
        with patch("src.providers.tts_provider.sf.write") as mock_write:
            provider = KokoroProvider()
            provider.generate_voice("test", str(tmp_path / "out.wav"))
            mock_write.assert_called_once_with(ANY, ANY, 44100)

    def test_configured_voice_defaults(self) -> None:
        provider = KokoroProvider()
        assert provider._default_voice == "bm_george"
        assert provider._speed == 1.0
        assert provider._language == "en-gb"


# ── Graceful error handling ───────────────────────────────────────────────


class TestErrorHandling:
    def test_pexels_search_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the API request fails, the error should propagate (caller handles it)."""
        import requests
        def _raise(*a, **kw):
            raise requests.exceptions.ConnectionError("DNS failure")
        monkeypatch.setattr("src.providers.asset_provider.requests.get", _raise)
        provider = PexelsProvider()
        with pytest.raises(requests.exceptions.ConnectionError):
            provider.search("space")

    def test_gemini_api_error(self, mock_gemini_llm: MagicMock) -> None:
        """API errors should propagate from the provider layer."""
        mock_gemini_llm.return_value.generate_content.side_effect = Exception("API Error")
        provider = GeminiProvider()
        with pytest.raises(Exception):
            provider.generate_text("test")
