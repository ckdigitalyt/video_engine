"""Audio architecture (directive §16–§22, §28).

Audio is a first-class timeline: NarrationTrack, MusicTrack, SFXTrack,
SubtitleTrack.  The final compositor uses FFmpeg (not MoviePy) for mixing,
ducking, normalization, and muxing.

TTS strategy (§17): local executable TTS preferred.  This module defines the
provider abstraction; concrete providers (Kokoro/Piper/Edge-TTS) plug in
behind it.  Word/sentence timing comes from the provider where available,
else falls back to sentence-level timing (never a mandatory CPU-heavy
Whisper pass per §18).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from engine.validation.schema import validate_audiocue


# ──────────────────────────────────────────────────────────────────────────
# Audio tracks
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class NarrationTrack:
    text: str
    chunks: list[dict] = field(default_factory=list)  # [{text, start, end}]
    provider: str = "local"
    audio_path: Optional[Path] = None

    def duration(self) -> float:
        if self.chunks:
            return max(c["end"] for c in self.chunks)
        return 0.0


@dataclass
class MusicTrack:
    segment: str = "intro"  # intro|build|tension|discovery|reveal|outro
    path: Optional[Path] = None
    ducked: bool = True
    volume: float = 0.35


@dataclass
class SFXTrack:
    cues: list[dict] = field(default_factory=list)  # [{type, time, volume}]

    def validate(self) -> list[str]:
        errs: list[str] = []
        for cue in self.cues:
            cue_doc = {"version": "v1", "cues": [cue]}
            for e in validate_audiocue(cue_doc):
                errs.append(f"cue {cue.get('type')}: {e}")
        return errs


@dataclass
class SubtitleTrack:
    entries: list[dict] = field(default_factory=list)  # [{start, end, text}]


# ──────────────────────────────────────────────────────────────────────────
# TTS provider abstraction (§17, §18)
# ──────────────────────────────────────────────────────────────────────────
class TTSProvider:
    """Provider interface.  Concrete providers must produce a WAV and
    (optionally) word-boundary timings."""
    name = "base"

    def synthesize(self, text: str, out_wav: Path, voice: str = "") -> dict:
        """Return metadata: {duration, words:[{word,start,end}]}."""
        raise NotImplementedError

    def available(self) -> bool:
        return False


class EdgeTTSProvider(TTSProvider):
    """External provider — optional fallback only.  WordBoundary exposure is
    provider-specific metadata, NOT a core dependency (§17)."""
    name = "edge_tts"

    def available(self) -> bool:
        return shutil.which("edge-tts") is not None or _import("edge_tts")

    def synthesize(self, text: str, out_wav: Path, voice: str = "") -> dict:
        import asyncio
        import edge_tts

        async def _run() -> dict:
            communicate = edge_tts.Communicate(text, voice or "en-US-ChristopherNeural")
            word_meta: list[dict] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    out_wav.parent.mkdir(parents=True, exist_ok=True)
                    with open(out_wav, "ab") as f:
                        f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    word_meta.append({
                        "word": chunk["text"],
                        "start": chunk["offset"] / 1e7,  # 100ns ticks -> s
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    })
            if out_wav.exists():
                out_wav.replace(out_wav.with_suffix(".mp3"))  # edge_tts -> mp3
            return {"duration": word_meta[-1]["end"] if word_meta else 0.0,
                    "words": word_meta}

        if out_wav.exists():
            out_wav.unlink()
        meta = asyncio.run(_run())
        return meta


class KokoroProvider(TTSProvider):
    """Local Kokoro — primary target.  Requires kokoro-onnx.  Falls back to
    sentence-level timing when word boundaries are unavailable."""
    name = "kokoro"

    def available(self) -> bool:
        return _import("kokoro_onnx") is not None

    def synthesize(self, text: str, out_wav: Path, voice: str = "") -> dict:
        import kokoro_onnx  # type: ignore
        kokoro = kokoro_onnx.Kokoro("kokoro-v0_19.onnx", "voices.bin")
        # chunk into sentences for coarse timing
        import re
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        words: list[dict] = []
        t = 0.0
        import wave
        with wave.open(str(out_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)  # Kokoro fixed sample rate; set once
            for s in sentences:
                samples, sr = kokoro.create(s, voice=voice or "af_sarah",
                                            speed=1.0, lang="en-us",
                                            is_phonemes=False, trim=True)
                dur = len(samples) / sr
                # sentence-level timing; each word spans the sentence
                for w in s.split():
                    words.append({"word": w, "start": t, "end": t + dur})
                wf.writeframes(_samples_to_pcm(samples))
                t += dur
        return {"duration": t, "words": words}


def _samples_to_pcm(samples) -> bytes:
    import numpy as np
    arr = np.asarray(samples)
    if arr.dtype == np.float32:
        arr = (arr * 32767).astype(np.int16)
    return arr.tobytes()


def _import(mod: str) -> Any:
    try:
        return __import__(mod)
    except ImportError:
        return None


_PROVIDERS: dict[str, TTSProvider] = {
    KokoroProvider.name: KokoroProvider(),   # local primary (§17)
    EdgeTTSProvider.name: EdgeTTSProvider(), # external fallback
}


def get_provider(name: str | None = None) -> TTSProvider:
    """Pick a working provider: local first (Kokoro), then Edge-TTS fallback."""
    if name and name in _PROVIDERS and _PROVIDERS[name].available():
        return _PROVIDERS[name]
    for p in _PROVIDERS.values():
        if p.available():
            return p
    raise RuntimeError("No TTS provider available")


def synthesize_narration(text: str, out_audio: Path, voice: str = "") -> tuple[Path, list[dict]]:
    """Synthesize narration with the best available provider.

    Returns (audio_path, words).  Tries local Kokoro first, falls back to
    Edge-TTS.  Audio extension depends on provider (wav for kokoro, mp3 for
    edge_tts).  Never blocks the architecture on a single provider.
    """
    out_audio = Path(out_audio)
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    for prov in _PROVIDERS.values():
        if not prov.available():
            continue
        try:
            wav = out_audio.with_suffix(".wav")
            meta = prov.synthesize(text, wav, voice=voice)
            if meta.get("duration", 0) > 0 and wav.exists():
                return wav, meta.get("words", [])
            # edge_tts writes mp3 next to the wav path
            mp3 = out_audio.with_suffix(".mp3")
            if meta.get("duration", 0) > 0 and mp3.exists():
                return mp3, meta.get("words", [])
        except Exception as e:  # noqa: BLE001
            print(f"[tts] provider {prov.name} failed: {e}")
            continue
    raise RuntimeError("No TTS provider produced audio")


# ──────────────────────────────────────────────────────────────────────────
# FFmpeg masters (Gate 8 — Audio): LUFS loudness, true peak, clipping
# ──────────────────────────────────────────────────────────────────────────
def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    return exe


def measure_loudness(path: Path) -> dict:
    """Measure integrated LUFS + true peak via FFmpeg ebur128 filter.

    ebur128 reports values on 'I:' (integrated) and 'Peak:' lines that
    follow the 'Integrated loudness:' / 'True peak:' headers.
    """
    cmd = [
        ffmpeg(), "-hide_banner", "-i", str(path),
        "-filter_complex", "ebur128=peak=true",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stderr
    lufs = None
    peak = None
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("I:") and lufs is None:
            try:
                lufs = float(stripped.split("I:")[1].split()[0].strip())
            except (IndexError, ValueError):
                pass
        elif stripped.startswith("Peak:") and peak is None:
            try:
                peak = float(stripped.split("Peak:")[1].split()[0].strip())
            except (IndexError, ValueError):
                pass
    return {"integrated_lufs": lufs, "true_peak_db": peak,
            "clipping": peak is not None and peak > -1.0}


def normalize_to_target(input_path: Path, output_path: Path,
                        target_lufs: float = -14.0) -> Path:
    """Normalize to target loudness with loudnorm (EBU R128).

    Previous test video was ~-29 LUFS — far too quiet.  loudnorm targets
    integrated LUFS AND caps true peak (TP=-1.5), so we never clip while
    reaching delivery loudness.  Static gain is NOT used: it would push
    true peak past 0 dBFS on peaky TTS.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg(), "-y", "-i", str(input_path),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "192k", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def ffmgen() -> str:
    return ffmpeg()


def duck_music_under_narration(narration: Path, music: Path, out_mix: Path,
                               music_volume: float = 0.35,
                               sidechain_threshold: str = "-20dB") -> Path:
    """Mix narration over music with sidechain ducking so the voice stays
    dominant (§21)."""
    out = Path(out_mix)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg(), "-y",
        "-i", str(narration),
        "-i", str(music),
        "-filter_complex",
        # sidechaincompress ducks music when narration is loud
        "[1:a]asplit=2[mus][dup];"
        "[0:a]asplit=2[nar][key];"
        "[dup][key]sidechaincompress=threshold={thr}:ratio=8:attack=20:release=300[duck];"
        "[nar][duck]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
        f"volume={music_volume if music_volume else 0.35}[aout]".format(thr=sidechain_threshold),
        "-map", "[aout]",
        "-c:a", "aac", "-b:a", "192k", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


if __name__ == "__main__":
    print("providers available:",
          {n: p.available() for n, p in _PROVIDERS.items()})
    print("ffmpeg:", ffmpeg())
