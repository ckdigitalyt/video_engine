"""
tts_provider.py — Abstract TTS provider and concrete implementations.

Defines the TTSProvider interface, then implements:
- KokoroProvider (local ONNX-based TTS engine)
"""

import soundfile as sf
from abc import ABC, abstractmethod
from kokoro_onnx import Kokoro

from src.utils.config import get_config


# ── Abstract base ──────────────────────────────────────────────────────────

class TTSProvider(ABC):
    """Interface for text-to-speech generation."""

    @abstractmethod
    def generate_voice(self, text: str, output_path: str) -> None:
        """
        Synthesize speech from *text* and save audio to *output_path*.
        """
        ...


# ── Kokoro ─────────────────────────────────────────────────────────────────

class KokoroProvider(TTSProvider):
    """TTS provider backed by the Kokoro ONNX engine."""

    def __init__(self):
        self._model_path = get_config("voices.kokoro.model", "kokoro-v0_19.onnx")
        self._voices_path = get_config("voices.kokoro.voices_bin", "voices.bin")
        self._default_voice = get_config("voices.kokoro.default_voice", "bm_george")
        self._speed = get_config("voices.kokoro.speed", 1.0)
        self._language = get_config("voices.kokoro.language", "en-gb")
        self._engine: Kokoro | None = None

    def _lazy_load(self) -> Kokoro:
        if self._engine is None:
            print("Loading Kokoro TTS engine...")
            self._engine = Kokoro(self._model_path, self._voices_path)
        return self._engine

    def generate_voice(self, text: str, output_path: str) -> None:
        engine = self._lazy_load()

        print(f"Synthesizing speech: '{text[:40]}...'")
        samples, sample_rate = engine.create(
            text,
            voice=self._default_voice,
            speed=self._speed,
            lang=self._language,
        )
        sf.write(output_path, samples, sample_rate)
        print(f"Voice track saved to {output_path}")
