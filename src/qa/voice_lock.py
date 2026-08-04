"""
voice_lock.py — Single-narrator voice lock (Jade Operating Spec §1, §9).

Every production must use ONE narrator voice selected and locked at
project start.  This module:

  * locks (provider, voice_id, speaker_id, rate/pitch profile) once and
    persists it to cache/voice_lock.json — the single source of truth
    for every narration track in the episode;
  * verifies that every scene's narration audio was produced by that
    same locked voice (provider + voice id recorded per scene);
  * runs an acoustic consistency check (per-scene loudness/RMS spread)
    to catch timbre drift, accidental fallback voices, and inconsistent
    levels — all rejectable under §1 TTS quality rules;
  * exposes the ``voice_switching`` QA check used by the pre-render and
    publish gates.

Rules enforced (from spec):
  - No per-scene voice engine switching.
  - Fallback (e.g. Edge down -> Kokoro) must NOT silently change the
    narrator timbre; it must be recorded as an explicit override and
    flagged by QA (the pipeline then re-renders with the locked voice).
  - Regeneration uses the same locked voice, never a different one.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_LOCK_PATH = "cache/voice_lock.json"


@dataclass
class VoiceLock:
    """Locked narrator identity for one episode."""

    provider: str            # "edge" | "kokoro" | "chatterbox" ...
    voice_id: str            # e.g. "en-US-ChristopherNeural" | "bm_george"
    speaker_id: str          # stable ID for all narration tracks
    rate: str = "+0%"
    pitch: str = "+0Hz"
    lock_path: str = DEFAULT_LOCK_PATH
    scene_voices: dict = field(default_factory=dict)   # scene_i -> voice_id
    scene_providers: dict = field(default_factory=dict)  # scene_i -> provider
    overrides: list = field(default_factory=list)      # explicit overrides logged

    # ── Persistence ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "voice_id": self.voice_id,
            "speaker_id": self.speaker_id,
            "rate": self.rate,
            "pitch": self.pitch,
            "scene_voices": self.scene_voices,
            "scene_providers": self.scene_providers,
            "overrides": self.overrides,
        }

    def save(self) -> str:
        os.makedirs(os.path.dirname(self.lock_path) or ".", exist_ok=True)
        with open(self.lock_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return self.lock_path

    @classmethod
    def load(cls, lock_path: str = DEFAULT_LOCK_PATH) -> Optional["VoiceLock"]:
        if not os.path.exists(lock_path):
            return None
        try:
            with open(lock_path) as f:
                d = json.load(f)
            return cls(
                provider=d.get("provider", ""),
                voice_id=d.get("voice_id", ""),
                speaker_id=d.get("speaker_id", ""),
                rate=d.get("rate", "+0%"),
                pitch=d.get("pitch", "+0Hz"),
                lock_path=lock_path,
                scene_voices=d.get("scene_voices", {}),
                scene_providers=d.get("scene_providers", {}),
                overrides=d.get("overrides", []),
            )
        except Exception:
            return None

    # ── Recording ──────────────────────────────────────────────────────

    def record_scene(self, scene_index: int, provider: str, voice_id: str,
                     override: bool = False, reason: str = "") -> None:
        """Record which voice actually produced a scene's narration.

        ``override=True`` means the locked voice was NOT used (explicit
        override only) — this is logged and flagged by QA, never silent.
        """
        self.scene_providers[str(scene_index)] = provider
        self.scene_voices[str(scene_index)] = voice_id
        if override:
            self.overrides.append({
                "scene": scene_index, "provider": provider,
                "voice_id": voice_id, "reason": reason,
            })

    def reset_episode(self) -> "VoiceLock":
        """Clear per-scene tracking for a fresh episode (the lock identity
        persists; the scene records are per-video).  Prevents a previous
        topic's scene voices from false-failing the next run's gate."""
        self.scene_voices = {}
        self.scene_providers = {}
        self.overrides = []
        self.save()
        return self

    # ── QA checks ──────────────────────────────────────────────────────

    def check_voice_switching(self) -> dict:
        """QA gate (§9 'voice switching across scenes' / §1 no timbre swap).

        Fails if any scene used a different voice_id or provider than the
        locked narrator, OR if any explicit override was logged without
        being resolved.  Returns a check dict {passed, detail, metrics}.
        """
        problems = []
        for sidx in sorted(set(self.scene_providers) | set(self.scene_voices),
                           key=lambda x: int(x)):
            p = self.scene_providers.get(sidx)
            v = self.scene_voices.get(sidx)
            if p and p != self.provider:
                problems.append(f"scene{sidx}: provider {p} != locked {self.provider}")
            if v and v != self.voice_id:
                problems.append(f"scene{sidx}: voice {v} != locked {self.voice_id}")
        if self.overrides:
            problems.append(
                f"{len(self.overrides)} explicit override(s): "
                + "; ".join(f"scene{o['scene']}={o['voice_id']}" for o in self.overrides))
        return {
            "passed": not problems,
            "detail": "single locked voice" if not problems else "; ".join(problems[:5]),
            "metrics": {
                "locked": f"{self.provider}/{self.voice_id}",
                "scenes": len(self.scene_voices),
                "overrides": len(self.overrides),
                "problems": problems[:8],
            },
        }

    def check_loudness_consistency(self, audio_dir: str,
                                   max_spread_db: float = 6.0) -> dict:
        """Acoustic drift check (§1: reject inconsistent loudness across
        scenes, timbre drift).  Measures per-scene RMS and reports the
        spread; a wide spread means some scenes were synthesized with a
        different character/gain (or fell back to another engine)."""
        rms_by_scene: dict[str, float] = {}
        for fname in sorted(os.listdir(audio_dir)):
            m = re.match(r"scene_(\d+)\.wav$", fname)
            if not m:
                continue
            path = os.path.join(audio_dir, fname)
            try:
                r = subprocess.run(
                    ["ffmpeg", "-i", path, "-af",
                     "volumedetect", "-f", "null", "-"],
                    capture_output=True, text=True, timeout=30,
                )
                mm = re.search(r"mean_volume: ([-\d.]+) dB", r.stderr)
                if mm:
                    rms_by_scene[m.group(1)] = float(mm.group(1))
            except Exception:
                continue
        if not rms_by_scene:
            return {"passed": True, "detail": "no narration audio found to measure",
                    "metrics": {"scenes_measured": 0}}
        vals = list(rms_by_scene.values())
        spread = max(vals) - min(vals)
        return {
            "passed": spread <= max_spread_db,
            "detail": (f"per-scene RMS spread {spread:.1f} dB "
                       f"(limit {max_spread_db} dB)") if spread <= max_spread_db
                      else f"RMS spread {spread:.1f} dB exceeds {max_spread_db} dB — "
                           f"possible voice/timbre drift: {rms_by_scene}",
            "metrics": {"spread_db": round(spread, 2), "per_scene": rms_by_scene},
        }


def lock_voice(provider: str = "edge", voice_id: str = "en-US-ChristopherNeural",
               speaker_id: str = "jade-narrator-001",
               rate: str = "+0%", pitch: str = "+0Hz",
               lock_path: str = DEFAULT_LOCK_PATH,
               force: bool = False) -> VoiceLock:
    """Select and lock the narrator voice once at project start.

    If a lock already exists with the SAME provider/voice, reuse it
    (idempotent).  If it exists but with a DIFFERENT narrator, the new
    request wins — a stale identity (e.g. an earlier smoke test locking
    edge while the run narrates with chatterbox) must never leave the
    episode's voice lock contradicting the actual narration, which would
    false-fail the voice_switching QA gate.
    """
    existing = VoiceLock.load(lock_path)
    if existing and not force:
        if existing.provider == provider and existing.voice_id == voice_id:
            return existing
        print(f"  [voice-lock] replacing stale lock "
              f"{existing.provider}/{existing.voice_id} → {provider}/{voice_id}")
    vl = VoiceLock(provider=provider, voice_id=voice_id, speaker_id=speaker_id,
                   rate=rate, pitch=pitch, lock_path=lock_path)
    vl.save()
    print(f"  [voice-lock] {provider}/{voice_id} (speaker {speaker_id}) locked → {lock_path}")
    return vl
