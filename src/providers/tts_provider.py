"""
tts_provider.py — Abstract TTS provider and concrete implementations.

Defines the TTSProvider interface, then implements:
- KokoroProvider (local ONNX-based TTS engine — offline fallback)
- EdgeTTSProvider (Microsoft Edge cloud TTS — benchmark candidate)

The pipeline selects a provider by config ``voices.provider``
("kokoro" | "edge") so engines are interchangeable without redesign.
"""

import os
import soundfile as sf
from abc import ABC, abstractmethod

from src.utils.config import get_config


# ── Abstract base ──────────────────────────────────────────────────────────

class TTSProvider(ABC):
    """Interface for text-to-speech generation."""

    name: str = "base"

    @abstractmethod
    def generate_voice(self, text: str, output_path: str) -> None:
        """Synthesize speech from *text* and save audio to *output_path*."""
        ...


# ── Factory ────────────────────────────────────────────────────────────────

def get_tts_provider(name: str | None = None) -> TTSProvider:
    """Resolve the configured TTS provider (config voices.provider)."""
    provider_name = name or get_config("voices.provider", "kokoro")
    if provider_name == "edge":
        return EdgeTTSProvider()
    return KokoroProvider()


# ── Kokoro (offline) ───────────────────────────────────────────────────────

class KokoroProvider(TTSProvider):
    """TTS provider backed by the Kokoro ONNX engine."""

    name = "kokoro"

    def __init__(self):
        from kokoro_onnx import Kokoro
        self._model_path = get_config("voices.kokoro.model", "kokoro-v0_19.onnx")
        self._voices_path = get_config("voices.kokoro.voices_bin", "voices.bin")
        self._default_voice = get_config("voices.kokoro.default_voice", "bm_george")
        self._speed = get_config("voices.kokoro.speed", 1.0)
        self._language = get_config("voices.kokoro.language", "en-gb")
        self._engine: Kokoro | None = None

    def _lazy_load(self):
        if self._engine is None:
            print("Loading Kokoro TTS engine...")
            self._engine = self._Kokoro(self._model_path, self._voices_path)
        return self._engine

    def generate_voice(self, text: str, output_path: str) -> None:
        engine = self._lazy_load()
        print(f"Synthesizing speech (kokoro/{self._default_voice}): '{text[:40]}...'")
        samples, sample_rate = engine.create(
            text,
            voice=self._default_voice,
            speed=self._speed,
            lang=self._language,
        )
        sf.write(output_path, samples, sample_rate)
        print(f"Voice track saved to {output_path}")

    # minor: keep Kokoro class importable at __init__ time for edge cases
    _Kokoro = None
    if _Kokoro is None:
        try:
            from kokoro_onnx import Kokoro as _K
            _Kokoro = _K
        except Exception:
            _Kokoro = None


# ── Edge TTS (cloud, benchmark candidate) ──────────────────────────────────

class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge neural TTS via edge-tts (cloud, ~zero CPU).

    Free, mature, noticeably more natural prosody than Kokoro for many
    voices.  Requires network; kept as the benchmark candidate while
    Kokoro remains the offline fallback.
    """

    name = "edge"

    # Strong documentary narration voices (US + UK male)
    VOICE_OPTIONS = [
        "en-US-ChristopherNeural",   # authoritative US male
        "en-US-GuyNeural",           # deeper US male
        "en-GB-RyanNeural",          # UK male
        "en-GB-ThomasNeural",        # UK male, calm
        "en-US-AndrewNeural",        # conversational US male
    ]

    def __init__(self, voice: str | None = None,
                 rate: str = "+0%", pitch: str = "+0Hz"):
        self._voice = voice or get_config("voices.edge.voice",
                                          "en-US-ChristopherNeural")
        self._rate = get_config("voices.edge.rate", rate)
        self._pitch = get_config("voices.edge.pitch", pitch)

    def generate_voice(self, text: str, output_path: str) -> None:
        import asyncio
        import edge_tts
        print(f"Synthesizing speech (edge/{self._voice}): '{text[:40]}...'")

        async def _run():
            comm = edge_tts.Communicate(
                text, self._voice, rate=self._rate, pitch=self._pitch
            )
            await comm.save(output_path)

        asyncio.run(_run())
        # normalize to WAV (pipeline expects WAV)
        wav = output_path if output_path.endswith(".wav") else output_path.rsplit(".", 1)[0] + ".wav"
        if output_path.endswith(".mp3"):
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", output_path, "-ar", "44100",
                 "-ac", "2", "-c:a", "pcm_s16le", wav],
                capture_output=True, text=True, timeout=60,
            )
            os.replace(wav, output_path)
        print(f"Voice track saved to {output_path}")
