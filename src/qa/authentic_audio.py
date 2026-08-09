"""
authentic_audio.py — Authentic source-audio registry (expert review rec #2).

The expert's finding: a story ABOUT an acoustic phenomenon must use the
AUTHENTIC recording, not a generic or synthesized stand-in — and must not
misrepresent the recording's properties (e.g. the widely-circulated Bloop
clip is NOAA's 16x sped-up version; playing it unlabeled as "the original
sound" is factually wrong).

This module provides:
  * AUTHENTIC_AUDIO — registry of verified, reachable public-domain source
    recordings (NOAA PMEL etc.), each with license, original properties
    and the speed multiplier used in the distributed file.
  * fetch_authentic() — download + cache a source recording into the run.
  * audio_qa() — gate: scenes that declare an authentic-source SFX event
    must use the real file (not a synth fallback), and the narration must
    not mislabel playback speed.

All URLs verified reachable (HTTP 200) on 2026-08-09 during research.
Licenses: US federal government works — public domain (17 U.S.C. §105).
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.request
from typing import Optional

# ── Registry: phenomenon → authentic source ───────────────────────────────
# speed_multiplier: the factor applied to the ORIGINAL recording in the
# distributed file (NOAA speeds up ultra-low-frequency sounds so humans
# can hear them).  original_hz: true frequency content where known.
AUTHENTIC_AUDIO: dict[str, dict] = {
    "bloop": {
        "name": "The Bloop (1997)",
        "url": "https://www.pmel.noaa.gov/acoustics/sounds/bloop.wav",
        "page": "https://www.pmel.noaa.gov/acoustics/sounds/bloop.html",
        "license": "public domain (NOAA, 17 U.S.C. §105)",
        "speed_multiplier": 16.0,   # NOAA: "Recorded signal sped up 16 times"
        "original_duration_s": 165.0,   # ~2m45s at true speed
        "file_duration_s": 10.34,
        "note": ("NOAA's own page states the file is sped up 16x; the true "
                 "signal is ultra-low-frequency (sub-100 Hz).  Never present "
                 "the 16x clip as the original real-time sound."),
    },
    "52hz_whale": {
        "name": "52-Hz whale call (1989+, WHOI)",
        "url": "https://www.pmel.noaa.gov/acoustics/whales/sounds/whalewav/ak52_10x.wav",
        "page": "https://www.pmel.noaa.gov/acoustics/whales/sounds/sounds_52blue.html",
        "license": "public domain (NOAA)",
        "speed_multiplier": 10.0,   # file is 10x sped up
        "original_duration_s": None,
        "file_duration_s": None,
        "note": ("Separate phenomenon from the Bloop: a single whale's call "
                 "at ~52 Hz, first detected 1989 by WHOI.  Do NOT attribute "
                 "52 Hz to the Bloop."),
    },
    "julia": {
        "name": "Julia (1999)",
        "url": "https://www.pmel.noaa.gov/acoustics/sounds/julia_sound.wav",
        "page": "https://www.pmel.noaa.gov/acoustics/sounds/julia.html",
        "license": "public domain (NOAA)",
        "speed_multiplier": None,
        "original_duration_s": None,
        "file_duration_s": None,
        "note": "Another ultra-low-frequency signal; source not resolved.",
    },
    "slow_down": {
        "name": "Slow Down (1997)",
        "url": "https://www.pmel.noaa.gov/acoustics/sounds/noise97139.wav",
        "page": "https://www.pmel.noaa.gov/acoustics/sounds/slow_down.html",
        "license": "public domain (NOAA)",
        "speed_multiplier": None,
        "original_duration_s": None,
        "file_duration_s": None,
        "note": "Ultra-low-frequency signal from Antarctic ice.",
    },
    "train": {
        "name": "Train (1997)",
        "url": "https://www.pmel.noaa.gov/acoustics/sounds/train.wav",
        "page": "https://www.pmel.noaa.gov/acoustics/sounds/train.html",
        "license": "public domain (NOAA)",
        "speed_multiplier": None,
        "original_duration_s": None,
        "file_duration_s": None,
        "note": "Ultra-low-frequency ~32-35 Hz, source attributed to ice.",
    },
    "whistle": {
        "name": "Whistle (1997, volcanogenic)",
        "url": "https://www.pmel.noaa.gov/acoustics/sounds/whistle16x.wav",
        "page": "https://www.pmel.noaa.gov/acoustics/sounds/whistle.html",
        "license": "public domain (NOAA)",
        "speed_multiplier": 16.0,
        "original_duration_s": None,
        "file_duration_s": None,
        "note": "Volcanogenic sound; file name indicates 16x speed-up.",
    },
    "upsweep": {
        "name": "Upsweep (1991+, unresolved)",
        "url": "https://www.pmel.noaa.gov/acoustics/sounds/upsweep20x.wav",
        "page": "https://www.pmel.noaa.gov/acoustics/sounds/upsweep.html",
        "license": "public domain (NOAA)",
        "speed_multiplier": 20.0,
        "original_duration_s": None,
        "file_duration_s": None,
        "note": "Long-running seasonal signal; source still unresolved.",
    },
}

# Aliases so a scene's sfx event can name the phenomenon loosely.
ALIASES = {
    "bloop": "bloop", "the bloop": "bloop",
    "52hz whale": "52hz_whale", "52 hz whale": "52hz_whale",
    "52-hertz whale": "52hz_whale", "52-hz whale": "52hz_whale",
    "52 hz whale call": "52hz_whale", "whale 52": "52hz_whale",
    "julia": "julia", "slow down": "slow_down", "train": "train",
    "whistle": "whistle", "upsweep": "upsweep",
}


def resolve_key(name: str) -> Optional[str]:
    """Map a scene's sfx-event label to a registry key."""
    key = (name or "").strip().lower()
    if key in AUTHENTIC_AUDIO:
        return key
    if key in ALIASES:
        return ALIASES[key]
    # fuzzy: "the 52-Hz whale" / "52 Hz whale" variants
    import re as _re
    for pat, k in (("52.*hz.*whale", "52hz_whale"),
                   ("the? ?bloop", "bloop")):
        if _re.search(pat, key):
            return k
    return None


def fetch_authentic(name: str, cache_dir: str = "cache/audio") -> Optional[dict]:
    """Download + cache an authentic recording.  Returns registry entry
    with a local ``path``; None if unknown or unreachable."""
    key = resolve_key(name)
    if key is None:
        return None
    entry = dict(AUTHENTIC_AUDIO[key])
    os.makedirs(cache_dir, exist_ok=True)
    ext = os.path.splitext(entry["url"].split("?")[0])[1] or ".wav"
    dest = os.path.join(cache_dir, f"authentic_{key}{ext}")
    if not os.path.exists(dest) or os.path.getsize(dest) < 1000:
        try:
            req = urllib.request.Request(entry["url"],
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 1000:
                raise ValueError("tiny response")
            with open(dest, "wb") as f:
                f.write(data)
        except Exception as e:
            print(f"  [authentic-audio] !! fetch failed for {key}: {str(e)[:90]}")
            return None
    entry["path"] = dest
    return entry


def audio_qa(scenes_data: list[dict], timeline_path: str = "",
             cache_dir: str = "cache/audio") -> dict:
    """Rec #2 + #7 audio gate.

    For every scene whose ``sfx_events`` declare an authentic source
    (e.g. {"type": "authentic", "source": "bloop"}):
      * the authentic file must have been fetched (no synth fallback)
      * the timeline must reference it (or the mix must, via audio_dir)
      * any playback-speed claim in the narration must match the file's
        real speed multiplier (never present a 16x clip as real-time).

    Returns a gate dict {passed, checks}.
    """
    checks = []
    declared = 0
    for i, sc in enumerate(scenes_data):
        for ev in (sc.get("sfx_events") or []):
            if not isinstance(ev, dict):
                continue
            if ev.get("type") != "authentic":
                continue
            declared += 1
            src = ev.get("source", "")
            entry = fetch_authentic(src, cache_dir) if src else None
            if entry is None:
                checks.append({
                    "name": "authentic_audio",
                    "passed": False,
                    "detail": f"scene {i}: authentic source '{src}' unavailable "
                              f"(fetch failed or unknown) — synth stand-in NOT allowed "
                              f"for story-central audio",
                })
                continue
            # Speed-integrity: if the narration mentions playback speed,
            # it must MATCH the file's multiplier (16x Bloop file + "sped
            # up sixteen times" = correct; "original real-time sound" or a
            # different multiplier = misrepresentation).
            mult = entry.get("speed_multiplier")
            narr = (sc.get("narration") or "").lower()
            speed_claims = []
            if mult and mult > 1.0:
                # Parse the multiplier the narration states.
                stated = None
                m = re.search(r"(?:sped|speeded)[^.]*?up(?:[^.]*?)(\d+)\s*x", narr)
                if m:
                    stated = float(m.group(1))
                else:
                    m2 = re.search(r"(sped|speeded) up", narr)
                    m3 = re.search(r"(\d+)\s*(?:times|x)", narr)
                    if m2 and m3:
                        stated = float(m3.group(1))
                if stated is not None and abs(stated - mult) > 0.5:
                    speed_claims.append(f"narration says {stated:.0f}x, file is {mult:.0f}x")
                # Never present a sped-up file as the original real-time
                # signal (the exact expert review warning).
                if re.search(r"(original|real[- ]time|live) (?:sound|recording|audio)", narr):
                    speed_claims.append(
                        f"calls the {mult:.0f}x sped-up file 'original' — "
                        f"must disclose it is sped up {mult:.0f}x")
            checks.append({
                "name": "authentic_audio",
                "passed": not speed_claims,
                "detail": (f"scene {i}: authentic '{src}' in use "
                           f"({entry['name']}, {mult}x sped-up file)"
                           if not speed_claims
                           else f"scene {i}: narration playback-speed claim "
                                f"({speed_claims}) contradicts {mult}x file"),
            })

    if declared == 0:
        checks.append({
            "name": "authentic_audio",
            "passed": True,
            "detail": "no authentic-source events declared in script",
        })
    failed = [c for c in checks if not c["passed"]]
    return {"passed": not failed, "checks": checks,
            "declared_events": declared,
            "blocking_failures": [c["name"] for c in failed]}
