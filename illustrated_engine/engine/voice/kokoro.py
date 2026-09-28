"""Kokoro (local ONNX, Apache-2.0) provider. fp32 model: the int8 build is
2.7x slower on this CPU (RESEARCH §3.3)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

_MODELS: dict = {}


def _load(model: str, voices_bin: str):
    key = (model, voices_bin)
    if key not in _MODELS:
        from kokoro_onnx import Kokoro
        _MODELS[key] = Kokoro(str(Path(model).expanduser()),
                              str(Path(voices_bin).expanduser()))
    return _MODELS[key]


class KokoroProvider:
    name = "kokoro"

    def __init__(self, voice_cfg: dict, lexicon):
        from engine.voice import VoiceUnavailable
        try:
            self.model = _load(voice_cfg["model"], voice_cfg["voices_bin"])
        except Exception as e:
            raise VoiceUnavailable(f"kokoro load failed: {type(e).__name__}"
                                   ) from None
        self.voice = voice_cfg["voice"]
        if self.voice not in self.model.get_voices():
            raise VoiceUnavailable(f"kokoro voice {self.voice!r} not found")
        self.lang = voice_cfg.get("lang", "en-us")
        self.lexicon = lexicon

    def synth(self, text: str, speed: float):
        from engine.voice import Clip
        ph = self.lexicon.to_phonemes(text, self.model.tokenizer.phonemize,
                                      self.lang)
        audio, sr = self.model.create(ph, voice=self.voice, speed=speed,
                                      lang=self.lang, is_phonemes=True)
        return Clip(np.asarray(audio, dtype=np.float32).reshape(-1), sr, None)
