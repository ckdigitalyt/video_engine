"""
tts_provider.py — Abstract TTS provider and concrete implementations.

Defines the TTSProvider interface, then implements:
- KokoroProvider (local ONNX-based TTS engine — offline fallback)
- EdgeTTSProvider (Microsoft Edge cloud TTS — benchmark candidate)

The pipeline selects a provider by config ``voices.provider``
("kokoro" | "edge") so engines are interchangeable without redesign.
"""

import json
import os
import select
import subprocess
import sys
import time
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


# ── Chatterbox (Resemble AI, MIT) — primary expressive narrator ───────────
# Runs in an ISOLATED venv (venv-cb) because chatterbox-tts pins
# numpy 1.26.4/torch 2.6.0 while the pipeline venv runs numpy 2.5.1.
# A persistent worker keeps the model loaded (KEEP_MODEL_LOADED
# equivalent) and serves JSON-lines requests (see scripts/chatterbox_worker.py).
# Supports native paralinguistic tags ([laugh], [chuckle], [sigh]...) and
# per-scene emotion control via exaggeration + cfg_weight (expert doc §1.3).

# Emotion -> (exaggeration, cfg_weight) per expert doc §1.3:
# high-energy hook: exaggeration=0.8, cfg_weight=0.3 (lively read);
# somber/factual:   exaggeration=0.4, cfg_weight=0.7 (steady);
# wonder/awe/reveal: mid-high exaggeration, moderate CFG.
# LOCKED narrator band (2026-08-05): Kurzgesagt-style clone from synthetic
# en-GB-ThomasNeural reference (audio_prompt).  Approved variant params
# ex=0.50 / cfg=0.32 — energetic-but-clear, warm and friendly, never
# theatrical.  Emotion/role modulation stays narrow around the lock.
CHATTERBOX_EMOTION_PARAMS = {
    "hook":       (0.52, 0.30),
    "tension":    (0.48, 0.31),
    "revelation": (0.52, 0.30),
    "wonder":     (0.50, 0.32),
    "awe":        (0.52, 0.31),
    "hopeful":    (0.50, 0.32),
    "nostalgia":  (0.46, 0.34),
    "somber":     (0.44, 0.36),
    "explanation": (0.46, 0.35),
    "default":    (0.50, 0.32),
}

# Paralinguistic tags Chatterbox speaks natively (expert doc §1.3).
CHATTERBOX_TAGS = ("[laugh]", "[sigh]", "[cough]", "[chuckle]",
                    "[gasp]", "[whisper]", "[groan]", "[hmm]", "[mm]",
                    "[yawn]", "[sniff]", "[breath]")


def strip_paralinguistic_tags(text: str) -> str:
    """Remove [tag] markers (for engines that would read them literally)."""
    import re
    return re.sub(r"\[[a-zA-Z ]+\]", "", text or "").strip()


class ChatterboxProvider(TTSProvider):
    """Expressive TTS via Resemble AI Chatterbox (isolated worker)."""

    name = "chatterbox"

    def __init__(self, exaggeration: float | None = None,
                 cfg_weight: float | None = None,
                 worker_python: str = "venv-cb/bin/python",
                 worker_script: str = "scripts/chatterbox_worker.py"):
        # Baseline from voices.yaml (calm documentary band: 0.40 / 0.35);
        # explicit constructor args win over config.
        try:
            from src.utils.config import get_config
            self._default_exaggeration = (
                float(get_config("voices.chatterbox.exaggeration", 0.40))
                if exaggeration is None else float(exaggeration))
            self._default_cfg_weight = (
                float(get_config("voices.chatterbox.cfg_weight", 0.35))
                if cfg_weight is None else float(cfg_weight))
        except Exception:
            self._default_exaggeration = 0.40 if exaggeration is None else float(exaggeration)
            self._default_cfg_weight = 0.35 if cfg_weight is None else float(cfg_weight)
        self._worker_python = worker_python
        self._worker_script = worker_script
        self._proc: subprocess.Popen | None = None
        self._req_id = 0

    # ── Worker lifecycle ───────────────────────────────────────────────

    def _ensure_worker(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            print("[chatterbox] starting persistent worker (model load ~17s)...")
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            self._proc = subprocess.Popen(
                [os.path.join(root, self._worker_python),
                 os.path.join(root, self._worker_script)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )
            # wait for readiness (worker prints "model ready" to stderr,
            # which we devnull; poll until stdin accepts or timeout)
            time.sleep(1.0)
        return self._proc

    def _kill_worker(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def shutdown(self):
        self._kill_worker()

    # ── TTSProvider API ────────────────────────────────────────────────

    def generate_voice(self, text: str, output_path: str,
                       exaggeration: float | None = None,
                       cfg_weight: float | None = None,
                       audio_prompt: str | None = None) -> None:
        """Synthesize *text* (whole semantic chunk — NOT sentence-by-
        sentence, per expert §1.2 contextual chunking) to *output_path*.

        audio_prompt: optional path to a 10-30s reference WAV — Chatterbox
        clones that voice's timbre + pacing (voice cloning).  When None the
        model's built-in default voice is used."""
        proc = self._ensure_worker()
        req = {
            "id": self._req_id,
            "text": (text or "").strip(),
            "out": os.path.abspath(output_path),
            "exaggeration": exaggeration if exaggeration is not None
                             else self._default_exaggeration,
            "cfg_weight": cfg_weight if cfg_weight is not None
                          else self._default_cfg_weight,
        }
        if audio_prompt:
            req["audio_prompt"] = os.path.abspath(audio_prompt)
        self._req_id += 1
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            # blocking read with a generous timeout (CPU generation is slow).
            # Robust protocol: skip any non-JSON stray lines (e.g. library
            # log lines the model prints to stdout at load) and only accept
            # a response matching this request id.
            deadline = time.time() + 900
            resp = None
            while time.time() < deadline:
                r, _, _ = select.select([proc.stdout], [], [], 5.0)
                if r:
                    line = proc.stdout.readline()
                    if not line:
                        if proc.poll() is not None:
                            raise RuntimeError("chatterbox worker died")
                        continue
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # stray log line — keep reading
                    if candidate.get("id") == req["id"]:
                        resp = candidate
                        break
                elif proc.poll() is not None:
                    raise RuntimeError("chatterbox worker died")
            if resp is None:
                raise TimeoutError("chatterbox generation timed out")
            if not resp.get("ok"):
                raise RuntimeError(resp.get("error", "generation failed"))
            if not os.path.exists(output_path):
                raise RuntimeError("chatterbox produced no audio file")
            print(f"  [chatterbox] {resp.get('duration_s', 0):.1f}s audio "
                  f"in {resp.get('elapsed_s', 0):.1f}s "
                  f"(ex={req['exaggeration']}, cfg={req['cfg_weight']})")
        except Exception as e:  # noqa: BLE001
            self._kill_worker()
            raise RuntimeError(f"chatterbox TTS failed: {e}") from e


# ── Factory ────────────────────────────────────────────────────────────────

def get_tts_provider(name: str | None = None) -> TTSProvider:
    """Resolve the configured TTS provider (config voices.provider).

    ``elevenlabs`` (primary since 2026-08-09): Declan Sage default voice,
    David fallback — warm authority, clear pacing, global English/US.
    ``chatterbox``: expressive flow-matching narrator (legacy primary).
    Falls back to edge/kokoro when the configured provider is unavailable.
    """
    provider_name = name or get_config("voices.provider", "elevenlabs")
    if provider_name == "elevenlabs":
        try:
            return ElevenLabsProvider()
        except Exception as e:  # noqa: BLE001
            print(f"  !! elevenlabs unavailable ({e}) — falling back to edge")
            return EdgeTTSProvider()
    if provider_name == "chatterbox":
        try:
            return ChatterboxProvider()
        except Exception as e:  # noqa: BLE001
            print(f"  !! chatterbox unavailable ({e}) — falling back to edge")
            return EdgeTTSProvider()
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


# ── ElevenLabs (cloud, 2026-08-09) — PRIMARY narrator ─────────────────────
# Channel direction 2026-08-09 (ckdigital): ElevenLabs for narration.
#   * DEFAULT voice: "Declan Sage" — warm authority, clear pacing, natural
#     pronunciation, tuned for a global English/US audience.
#   * FALLBACK voice: "David" — only when Declan Sage is unavailable.
#   * ONE voice per video: the voice is resolved ONCE at provider init
#     (never per scene), so the narrator can never switch mid-video.
#   * Pacing: pipeline-side pause injection (apply_pacing_pauses) + the
#     pacing gate keep delivery un-rushed; ElevenLabs stability is set
#     high for consistent, measured delivery.
#
# Voice IDs are resolved BY NAME from the ElevenLabs API at init (own
# voices first, then the shared library) and cached in cache/voices, so
# we never hardcode a stale voice_id.  Requires ELEVENLABS_API_KEY.

class ElevenLabsProvider(TTSProvider):
    """Cloud TTS via ElevenLabs (eleven_multilingual_v2)."""

    name = "elevenlabs"

    def __init__(self, voice_name: str | None = None,
                 fallback_voice: str | None = None,
                 api_key: str | None = None):
        from src.utils.config import get_config
        self._voice_name = voice_name or get_config(
            "voices.elevenlabs.voice", "Declan Sage")
        self._fallback_voice = fallback_voice or get_config(
            "voices.elevenlabs.fallback_voice", "David")
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not self._api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY not set — cannot use ElevenLabs narrator")
        self._model = get_config(
            "voices.elevenlabs.model", "eleven_multilingual_v2")
        self._stability = float(get_config(
            "voices.elevenlabs.stability", 0.55))
        self._similarity = float(get_config(
            "voices.elevenlabs.similarity_boost", 0.85))
        self._style = float(get_config("voices.elevenlabs.style", 0.30))
        # Resolve the voice ONCE (own voices → shared library → fallback).
        self.voice_id = self._resolve_voice(self._voice_name)
        if not self.voice_id:
            print(f"  !! ElevenLabs: '{self._voice_name}' not found — "
                  f"falling back to '{self._fallback_voice}'")
            self.voice_id = self._resolve_voice(self._fallback_voice)
        if not self.voice_id:
            raise RuntimeError(
                f"ElevenLabs voices '{self._voice_name}' and "
                f"'{self._fallback_voice}' not found in account/library")
        print(f"  [elevenlabs] narrator locked: '{self._voice_name}' "
              f"(id={self.voice_id})")

    def is_available(self) -> bool:
        return bool(self._api_key)

    # ── Voice resolution ───────────────────────────────────────────────

    def _resolve_voice(self, name: str) -> str:
        """Find a voice_id by name: own voices, then shared library.
        Caches the resolution in cache/voices/elevenlabs_voices.json."""
        import urllib.request
        import json as _json
        cache_path = os.path.join("cache", "voices", "elevenlabs_voices.json")
        cached = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as f:
                    cached = _json.load(f)
            except Exception:
                cached = {}
        if name in cached:
            return cached[name]
        headers = {"xi-api-key": self._api_key,
                   "Content-Type": "application/json"}
        found = ""
        # 1) own voices
        try:
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/voices", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = _json.loads(r.read())
            for v in data.get("voices", []):
                if v.get("name", "").strip().lower() == name.strip().lower():
                    found = v["voice_id"]
                    break
        except Exception as e:
            print(f"  [elevenlabs] !! own-voices lookup failed: {str(e)[:80]}")
        # 2) shared library (search by name)
        if not found:
            try:
                import urllib.parse
                url = ("https://api.elevenlabs.io/v1/shared-voices?page_size=30&"
                       + urllib.parse.urlencode({"search": name}))
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = _json.loads(r.read())
                for v in data.get("voices", []):
                    if v.get("name", "").strip().lower() == name.strip().lower():
                        found = v["voice_id"]
                        break
            except Exception as e:
                print(f"  [elevenlabs] !! shared-voices lookup failed: {str(e)[:80]}")
        if found:
            cached[name] = found
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w") as f:
                _json.dump(cached, f, indent=2)
        return found

    # ── Generation ─────────────────────────────────────────────────────

    def generate_voice(self, text: str, output_path: str) -> None:
        """Synthesize speech via ElevenLabs; save WAV to output_path."""
        import urllib.request
        import json as _json
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        payload = {
            "text": strip_paralinguistic_tags(text)[:5000],
            "model_id": self._model,
            "voice_settings": {
                "stability": self._stability,
                "similarity_boost": self._similarity,
                "style": self._style,
                "use_speaker_boost": True,
            },
        }
        req = urllib.request.Request(
            url, data=_json.dumps(payload).encode(),
            headers={"xi-api-key": self._api_key,
                     "Content-Type": "application/json",
                     "Accept": "audio/mpeg"},
        )
        print(f"  [elevenlabs] synthesizing ({self._voice_name}): "
              f"'{text[:40]}...'")
        mp3 = output_path.rsplit(".", 1)[0] + ".mp3"
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        if not data or len(data) < 1000:
            raise RuntimeError(
                f"ElevenLabs returned {len(data) if data else 0} bytes")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(mp3, "wb") as f:
            f.write(data)
        # normalize to WAV (pipeline expects 44100 stereo WAV)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", mp3, "-ar", "44100",
             "-ac", "2", "-c:a", "pcm_s16le", output_path],
            capture_output=True, text=True, timeout=120,
        )
        if not os.path.exists(output_path):
            raise RuntimeError("ffmpeg WAV conversion failed")
        if os.path.exists(mp3) and mp3 != output_path:
            os.remove(mp3)
        print(f"  [elevenlabs] saved {output_path} "
              f"({os.path.getsize(output_path)//1024} KB)")

    def shutdown(self) -> None:
        """No persistent worker to stop (cloud API)."""
        pass

