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

    ``fish`` (primary since 2026-08-09): Fish Audio S2.1 Pro Free,
    "Narrator" by Max N — deep, warm, authoritative American English.
    ``chatterbox``: expressive flow-matching narrator (fallback per
    ckdigital if the Fish API fails).
    Falls back to edge/kokoro when the configured provider is unavailable.
    """
    provider_name = name or get_config("voices.provider", "fish")
    if provider_name == "fish":
        try:
            return FishAudioProvider()
        except Exception as e:  # noqa: BLE001
            print(f"  !! fish unavailable ({e}) — falling back to chatterbox")
            try:
                return ChatterboxProvider()
            except Exception as e2:  # noqa: BLE001
                print(f"  !! chatterbox unavailable ({e2}) — falling back to edge")
                return EdgeTTSProvider()
    if provider_name == "chatterbox":
        try:
            return ChatterboxProvider()
        except Exception as e:  # noqa: BLE001
            print(f"  !! chatterbox unavailable ({e}) — falling back to edge")
            return EdgeTTSProvider()
    if provider_name == "elevenlabs":
        try:
            return ElevenLabsProvider()
        except Exception as e:  # noqa: BLE001
            print(f"  !! elevenlabs unavailable ({e}) — falling back to edge")
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
        # Optional explicit own-voice fallback (free plans cannot use
        # library voices like Declan Sage/David via the API).  When set,
        # this voice is used if the primary + fallback can't synthesize;
        # when empty, the best-scoring synthesizing own voice is picked.
        self._own_voice_fallback = get_config(
            "voices.elevenlabs.own_voice_fallback", "")
        # Resolve + PROBE the narrator ONCE.  Free plans cannot use
        # shared-library voices via the API (HTTP 402 paid_plan_required)
        # even though lookups succeed — so the probe decides the real
        # voice: configured voice if it synthesizes, else the best
        # matching OWN voice (George/Daniel/etc.), else raise so the
        # runner locks ONE consistent fallback for the whole video.
        import urllib.request as _ur
        import json as _j

        def _probe(vid: str) -> bool:
            """Return True if this voice actually synthesizes."""
            _probe_url = (f"https://api.elevenlabs.io/v1/text-to-speech/{vid}")
            _probe = _j.dumps({
                "text": "Test.",
                "model_id": self._model,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8,
                                    "style": 0.0, "use_speaker_boost": False},
            }).encode()
            _req = _ur.Request(
                _probe_url, data=_probe,
                headers={"xi-api-key": self._api_key,
                         "Content-Type": "application/json",
                         "Accept": "audio/mpeg"})
            try:
                with _ur.urlopen(_req, timeout=60) as _r:
                    _d = _r.read()
                return bool(_d) and len(_d) >= 1000
            except Exception:
                return False

        # 1) configured voice (Declan Sage) — may be a library voice
        self.voice_name = self._voice_name
        self.voice_id = self._resolve_voice(self._voice_name)
        if self.voice_id and _probe(self.voice_id):
            self._synthesis_note = f"{self._voice_name} (verified)"
        else:
            if self.voice_id:
                print(f"  !! ElevenLabs '{self._voice_name}' does not "
                      f"synthesize on this plan (library voices need paid "
                      f"subscription) — selecting best OWN voice")
            else:
                print(f"  !! ElevenLabs '{self._voice_name}' not found — "
                      f"selecting best OWN voice")
            # 2) fallback voice (David) if it is an own voice that works
            self.voice_id = self._resolve_voice(self._fallback_voice)
            if self.voice_id and _probe(self.voice_id):
                self.voice_name = self._fallback_voice
                self._synthesis_note = f"{self._fallback_voice} (fallback)"
            else:
                # 3) explicit own-voice fallback (free-plan usable), e.g.
                #    "George - Warm, Captivating Storyteller" — closest to
                #    Declan's male warm-authority direction.
                if self._own_voice_fallback:
                    self.voice_id = self._resolve_voice(self._own_voice_fallback)
                    if self.voice_id and _probe(self.voice_id):
                        self.voice_name = self._own_voice_fallback
                        self._synthesis_note = (
                            f"{self._own_voice_fallback} (own-voice fallback)")
                # 4) auto-pick the best own voice that actually synthesizes
                if not getattr(self, "_synthesis_note", ""):
                    self.voice_id, self.voice_name = self._best_own_voice()
                    if self.voice_id:
                        self._synthesis_note = (
                            f"{self.voice_name} (auto own-voice fallback)")
                    else:
                        raise RuntimeError(
                            "ElevenLabs: no usable voice (configured '"
                            f"{self._voice_name}', fallback '{self._fallback_voice}', "
                            "and own voices all failed synthesis probe) — "
                            "add credits or check the API key")
        print(f"  [elevenlabs] narrator locked: {self._synthesis_note} "
              f"(id={self.voice_id})")

    def is_available(self) -> bool:
        return bool(self._api_key)

    # ── Voice resolution ───────────────────────────────────────────────

    def _best_own_voice(self) -> tuple[str, str]:
        """Pick the account's own voice closest to the narrator direction
        (warm authority, documentary storyteller).  Returns (voice_id,
        display_name) or ('', '') when the account has no own voices.

        Free plans cannot use shared-library voices via the API, but own
        voices work — so when the configured narrator (e.g. Declan Sage)
        is a library voice, this keeps the video on ElevenLabs instead of
        dropping to the edge fallback."""
        import urllib.request
        import json as _json
        headers = {"xi-api-key": self._api_key,
                   "Content-Type": "application/json"}
        try:
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/voices", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = _json.loads(r.read())
            voices = data.get("voices", [])
        except Exception as e:
            print(f"  [elevenlabs] !! own-voices list failed: {str(e)[:80]}")
            return "", ""
        if not voices:
            return "", ""
        # Score by narrator-direction keywords (name + description).
        _WANT = ("warm", "captivat", "storyteller", "documentary",
                 "narrator", "authoritative", "confident", "trustworthy",
                 "wise", "broadcaster", "informative", "engaging",
                 "resonant", "smooth", "steady", "mature", "deep")
        _AVOID = ("warrior", "horror", "trickster", "playful", "quirky",
                  "energetic social", "villain", "aggressive", "whisper")

        def _score(v: dict) -> int:
            blob = f"{v.get('name', '')} {v.get('description', '')}".lower()
            s = sum(2 for w in _WANT if w in blob)
            s -= sum(3 for w in _AVOID if w in blob)
            return s

        # Probe in score order and return the FIRST voice that actually
        # synthesizes.  Some 'own' voices are library-derived clones that
        # still 402 on free plans (observed: Harrison Gale); the account's
        # starter voices (George/Daniel/Eric/Bill) synthesize fine — the
        # probe is the only reliable filter.
        import urllib.request as _ur2
        import json as _j2
        for v in sorted(voices, key=_score, reverse=True):
            _vid = v.get("voice_id", "")
            if not _vid:
                continue
            _probe_url = f"https://api.elevenlabs.io/v1/text-to-speech/{_vid}"
            _probe = _j2.dumps({
                "text": "Test.",
                "model_id": self._model,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8,
                                    "style": 0.0, "use_speaker_boost": False},
            }).encode()
            _req = _ur2.Request(
                _probe_url, data=_probe,
                headers={"xi-api-key": self._api_key,
                         "Content-Type": "application/json",
                         "Accept": "audio/mpeg"})
            try:
                with _ur2.urlopen(_req, timeout=60) as _r:
                    _d = _r.read()
                if _d and len(_d) >= 1000:
                    return _vid, v.get("name", "")
            except Exception:
                continue
        return "", ""

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

        def _match(candidate: str) -> bool:
            """Match the requested voice name against a library candidate.
            Shared-library names carry suffixes ('Declan Sage - Wise and
            Captivating'), so require a PREFIX match on either side, not
            exact equality."""
            c = (candidate or "").strip().lower()
            n = name.strip().lower()
            return c == n or c.startswith(n) or n.startswith(c)

        # 1) own voices
        try:
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/voices", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = _json.loads(r.read())
            for v in data.get("voices", []):
                if _match(v.get("name", "")):
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
                    if _match(v.get("name", "")):
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



# ── Fish Audio S2.1 Pro (cloud, 2026-08-09) — PRIMARY narrator ────────────
# Channel direction 2026-08-09 (ckdigital): Fish Audio S2.1 Pro Free for
# narration.
#   * MODEL: s2.1-pro-free — sent as an HTTP HEADER (model: s2.1-pro-free).
#     A missing/misspelled header silently falls back to the PAID
#     s2.1-pro model — this provider always sets it explicitly.
#   * VOICE: "Narrator" by Max N (reference_id 0327fdb5da9e4fd782899a8058c8ae2b)
#     — deep, warm, authoritative, calm/measured standard American English.
#   * STYLE: S2.1 Pro has NO style/emotion JSON field — delivery is driven
#     by inline natural-language [bracket] tags inside the text ([calm],
#     [measured], [emphasis], [break]...).  Per channel direction we use
#     them SPARINGLY (emphasis/suspense/wonder only), never over-dramatized.
#   * ONE voice per video: reference_id is fixed; the voice lock records
#     every scene so QA blocks any mid-video switch.
#   * Fallback: Chatterbox (per ckdigital) if the Fish API fails.
#
# Free tier (verified 2026-08-09): $0, fair-use, no hard char cap, 5
# concurrent requests, no SLA.  Free window currently ends 2026-08-31.
# COMMERCIAL-USE TERMS: 2026 product pages allow commercial use of
# s2.1-pro-free for smaller businesses (<$1M ARR), but the Aug-2024 ToS
# still says free = personal/non-commercial — an unresolved conflict.
# Confirmed with support before monetizing; see fish_audio_research.md.

FISH_DEFAULT_VOICE_ID = "0327fdb5da9e4fd782899a8058c8ae2b"  # Narrator by Max N
FISH_BACKUP_VOICES = {
    "azeez": "398dcc0108d84aad919e7f299fb04117",       # documentary/historical
    "laim": "eb986eb97d1c45a39d5c1f0453e176a3",        # General American measured
    "daniel": "0eb3061649da44a98bded9163319567c",      # educational/YouTube
}
# Restrained documentary recipe (channel direction): single mild cue per
# sentence at sentence start, NO intensity modifiers, sampling kept calm.
FISH_STYLE_TAGS = {
    "default": "[calm]",          # baseline measured delivery
    "hook": "[measured]",
    "tension": "[measured]",
    "revelation": "[measured]",   # wonder WITHOUT over-dramatization
    "wonder": "[measured]",
    "awe": "[measured]",
    "hopeful": "[calm]",
    "nostalgia": "[calm]",
    "somber": "[calm]",
    "explanation": "[calm]",
    "climax": "[measured]",
    "conclusion": "[calm]",
}


class FishAudioProvider(TTSProvider):
    """Cloud TTS via Fish Audio S2.1 Pro Free (native /v1/tts API)."""

    name = "fish"

    def __init__(self, voice_id: str | None = None,
                 model: str | None = None,
                 api_key: str | None = None):
        from src.utils.config import get_config
        self._voice_id = voice_id or get_config(
            "voices.fish.voice_id", FISH_DEFAULT_VOICE_ID)
        self._model = model or get_config("voices.fish.model", "s2.1-pro-free")
        self._api_key = api_key or os.environ.get("FISH_API_KEY", "")
        if not self._api_key:
            raise RuntimeError("FISH_API_KEY not set — cannot use Fish Audio")
        # v19g (ckdigital direction): PAID tier approved (commercial terms
        # confirmed 2026-08-09).  Guard now only refuses EMPTY/unknown model
        # names — a misspelled header silently bills the paid tier, so we
        # still validate against the known S2.1 model family.  The old
        # free-only refusal is gone.
        if not self._model:
            raise RuntimeError(
                "Fish model is empty — configure voices.fish.model "
                "(e.g. 's2.1-pro').")
        _known = ("s2.1-pro", "s2.1-pro-free", "s2.1-turbo")
        if self._model not in _known:
            raise RuntimeError(
                f"Fish model '{self._model}' is not a known S2.1 model "
                f"({_known}) — refusing to risk billing a wrong tier.")
        # v31 (DeepSeek-validated): log the ACTIVE narrator identity + the
        # free-tier quality cap ONCE so run logs never imply "chatterbox"
        # is the narrator (it is only the FALLBACK when Fish fails).
        if self._model == "s2.1-pro-free":
            print("  [fish] ACTIVE NARRATOR: Fish Audio s2.1-pro-free "
                  "(FREE tier — 128 kbps mp3 cap; 320 kbps + s2.1-pro need "
                  "loaded Fish credit + allow_paid=true)")
        else:
            print(f"  [fish] ACTIVE NARRATOR: Fish Audio {self._model} "
                  "(paid tier — 320 kbps available)")
        self._temperature = float(get_config("voices.fish.temperature", 0.6))
        self._speed = float(get_config("voices.fish.prosody.speed", 1.0))
        self._volume = float(get_config("voices.fish.prosody.volume", 0))
        self._sample_rate = int(get_config("voices.fish.sample_rate", 44100))
        self._format = get_config("voices.fish.format", "mp3")
        self._condition_previous = bool(get_config(
            "voices.fish.condition_on_previous_chunks", True))
        self._reference_audio_path = os.path.join(
            "cache", "audio", "fish_narrator_reference.wav")
        # Verify the voice is reachable (cheap model-metadata GET; no auth
        # needed for public models) so a bad voice_id fails at init, not
        # mid-video.
        self._verify_voice()

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _verify_voice(self) -> None:
        import urllib.request
        import json as _json
        try:
            req = urllib.request.Request(
                f"https://api.fish.audio/model/{self._voice_id}",
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = _json.loads(r.read())
            title = data.get("title", "") or data.get("name", "")
            print(f"  [fish] voice verified: '{title}' "
                  f"(id={self._voice_id})")
        except Exception as e:
            print(f"  [fish] !! voice lookup failed ({str(e)[:80]}) — "
                  f"will rely on synthesis error handling")

    # ── Style/emotion injection (S2.1 natural-language [bracket] tags) ──

    def apply_style(self, text: str, emotion: str = "default",
                    role: str = "exploration") -> str:
        """Inject a SINGLE mild S2.1 style cue at the sentence start —
        restrained documentary delivery, never over-dramatized (channel
        direction 2026-08-09)."""
        cue = FISH_STYLE_TAGS.get(emotion, FISH_STYLE_TAGS["default"])
        # emphasis/wonder cues are used ONLY when the script marks them;
        # we never add intensity modifiers.
        return f"{cue} {text}".strip() if cue else text

    # ── Generation ─────────────────────────────────────────────────────

    def generate_voice(self, text: str, output_path: str) -> None:
        """Synthesize speech via Fish Audio S2.1 Pro Free; save WAV."""
        import urllib.request
        import json as _json
        url = "https://api.fish.audio/v1/tts"
        payload = {
            "text": strip_paralinguistic_tags(text)[:5000],
            "reference_id": self._voice_id,
            "temperature": self._temperature,
            "top_p": 0.9,
            "prosody": {
                "speed": self._speed,
                "volume": self._volume,
                "normalize_loudness": True,
            },
            "format": self._format,
            "sample_rate": self._sample_rate,
            "mp3_bitrate": int(get_config("voices.fish.mp3_bitrate", 320)),
            "latency": "normal",
            "normalize": True,
            "condition_on_previous_chunks": self._condition_previous,
        }
        req = urllib.request.Request(
            url, data=_json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # CRITICAL: model is a HEADER on Fish's API.  Missing or
                # misspelled => silently bills the PAID s2.1-pro tier.
                "model": self._model,
                "User-Agent": "Mozilla/5.0",
            })
        print(f"  [fish] synthesizing (model={self._model}, "
              f"voice={self._voice_id}): '{text[:40]}...'")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
        except Exception as e:
            # Surface the HTTP status (401/402/429/500) for diagnostics.
            code = getattr(e, "code", None)
            detail = str(e)
            if code:
                try:
                    detail = e.read().decode(errors="replace")[:200]
                except Exception:
                    pass
            raise RuntimeError(f"Fish Audio API error {code}: {detail}")
        if not data or len(data) < 1000:
            raise RuntimeError(
                f"Fish Audio returned {len(data) if data else 0} bytes "
                f"(check API key + free-tier availability)")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        tmp = output_path.rsplit(".", 1)[0] + "." + self._format
        with open(tmp, "wb") as f:
            f.write(data)
        # normalize to WAV (pipeline expects 44100 stereo WAV)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", tmp, "-ar", "44100",
             "-ac", "2", "-c:a", "pcm_s16le", output_path],
            capture_output=True, text=True, timeout=120,
        )
        if not os.path.exists(output_path):
            raise RuntimeError("ffmpeg WAV conversion failed")
        if os.path.exists(tmp) and tmp != output_path:
            os.remove(tmp)
        print(f"  [fish] saved {output_path} "
              f"({os.path.getsize(output_path)//1024} KB)")

    def shutdown(self) -> None:
        """No persistent worker to stop (cloud API)."""
        pass
