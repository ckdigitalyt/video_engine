"""
pacing_engine.py — Comprehension-first pacing (Jade v10, expert recs 1/2/5/11).

Pacing is a core quality metric, not a tuning parameter.  This module
provides:

  * ROLE_PACING   — per-narrative-role targets: speech rate (WPM), energy,
                    pause density.  The hook is energetic but comprehensible;
                    explanatory scenes are deliberately slower with more
                    space after key facts (rec 1/2).
  * comprehension_risk() — a 0-1 risk score per scene from speech density,
                    technical-term density (numbers/units/years) and
                    sentence length (rec 11 "comprehension risk").
  * measure_speech_rate() — actual delivered WPM from audio duration.
  * audit_pacing() — per-scene audit used for run_report + postmortem and
                    to flag "too fast / too dense" scenes for QA (rec 1/11).

Everything is role-driven and topic-free (rec 12): no per-topic branches.
"""

from __future__ import annotations

import re
from typing import Optional

# ── Per-role pacing targets ──────────────────────────────────────────────
# target_wpm: what a skilled documentary narrator should deliver
# min/max_wpm: QA acceptance band (below = too slow/draggy, above = rushed)
# energy: 0..1 vocal energy hint (drives TTS exaggeration, rec 2)
# pause_density: light/medium/heavy — how much space to leave after facts
ROLE_PACING = {
    "hook":        {"target_wpm": 158, "min_wpm": 135, "max_wpm": 182,
                    "energy": 0.85, "pause_density": "light",
                    "desc": "energetic but not hard to follow"},
    "exploration": {"target_wpm": 150, "min_wpm": 128, "max_wpm": 172,
                    "energy": 0.60, "pause_density": "medium",
                    "desc": "steady documentary pace"},
    "explanation": {"target_wpm": 138, "min_wpm": 115, "max_wpm": 160,
                    "energy": 0.40, "pause_density": "heavy",
                    "desc": "slow down for technical clarity"},
    "climax":      {"target_wpm": 152, "min_wpm": 130, "max_wpm": 175,
                    "energy": 0.75, "pause_density": "medium",
                    "desc": "build energy, keep comprehension"},
    "conclusion":  {"target_wpm": 142, "min_wpm": 120, "max_wpm": 165,
                    "energy": 0.50, "pause_density": "heavy",
                    "desc": "measured, give the ending room"},
    "default":     {"target_wpm": 150, "min_wpm": 128, "max_wpm": 172,
                    "energy": 0.55, "pause_density": "medium",
                    "desc": "default documentary pace"},
}

# Words that make a sentence "technical" for comprehension scoring
_TECH_PATTERNS = [
    r"\d+(?:\.\d+)?\s*(?:million|billion|trillion|thousand)\b",
    r"\d+(?:\.\d+)?\s*[a-z]{1,4}\b",      # "23 km", "1.3 s", "722 kg"
    r"\b(?:km|kg|m|s|au|w|mw|hz|ghz|mhz|kbps|mph|°[cf])\b",
    r"\b(?:19|20)\d{2}\b",                 # years
    r"[×x^%°]",                            # math/symbols
]
_TECH_RE = re.compile("|".join(_TECH_PATTERNS), re.IGNORECASE)


def role_for(intent: str = "default") -> str:
    """Normalize an intent/scene-role string into a pacing role key."""
    i = (intent or "default").strip().lower()
    if i in ROLE_PACING:
        return i
    # intent synonyms from the EntitySpec vocabulary
    synonyms = {
        "reveal": "explanation", "scale": "explanation",
        "journey": "exploration", "emotion": "climax",
        "start": "hook", "end": "conclusion",
    }
    return synonyms.get(i, "default")


def target_wpm(intent: str = "default") -> float:
    return ROLE_PACING[role_for(intent)]["target_wpm"]


def measure_speech_rate(text: str, duration_s: float) -> float:
    """Actual delivered words-per-minute from narration + audio duration."""
    words = len((text or "").split())
    if duration_s <= 0 or words == 0:
        return 0.0
    return round(words / (duration_s / 60.0), 1)


def _sentence_lengths(text: str) -> list[int]:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip())
             if s.strip()]
    return [len(s.split()) for s in sents]


def technical_density(text: str) -> float:
    """Fraction of sentences carrying technical terms (numbers/units/years)."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip())
             if s.strip()]
    if not sents:
        return 0.0
    tech = sum(1 for s in sents if _TECH_RE.search(s))
    return tech / len(sents)


def comprehension_risk(text: str, intent: str = "default",
                       actual_wpm: Optional[float] = None) -> dict:
    """Score how hard this narration is to follow (0 = easy .. 1 = risky).

    Signals (rec 11):
      - delivered speech rate vs role band (if actual_wpm given)
      - technical-term density (numbers/units/years per sentence)
      - sentence length (long sentences reduce comprehension)
    Returns a dict with score + contributing signals.
    """
    profile = ROLE_PACING[role_for(intent)]
    signals: dict[str, float] = {}

    # 1) speech rate
    if actual_wpm and actual_wpm > 0:
        if actual_wpm > profile["max_wpm"]:
            signals["speech_rate"] = min(
                1.0, (actual_wpm - profile["max_wpm"]) / 40.0 + 0.35)
        elif actual_wpm < profile["min_wpm"]:
            signals["speech_rate"] = 0.15  # slow is rarely a comprehension risk
        else:
            signals["speech_rate"] = 0.0

    # 2) technical density
    td = technical_density(text)
    signals["technical_density"] = td * 0.55

    # 3) sentence length
    lens = _sentence_lengths(text)
    avg_len = sum(lens) / len(lens) if lens else 0
    # >22 words/sentence becomes progressively harder
    signals["sentence_length"] = max(0.0, (avg_len - 18.0) / 12.0) * 0.5

    score = min(1.0, sum(signals.values()))
    return {
        "score": round(score, 2),
        "signals": {k: round(v, 2) for k, v in signals.items()},
        "wpm": actual_wpm,
        "role": role_for(intent),
        "band": [profile["min_wpm"], profile["max_wpm"]],
        "grade": ("low" if score < 0.25 else
                  "medium" if score < 0.5 else "high"),
    }


def audit_pacing(scenes: list[dict], audio_durations: list[float]) -> dict:
    """Audit every scene's delivered pacing; returns report dict.

    Used by both runners to populate run_report["pacing"] and to flag
    high-risk scenes as degradations (rec 10: never silently keep a
    rushed scene — report it).
    """
    rows = []
    high_risk = []
    for i, s in enumerate(scenes):
        text = s.get("narration") or ""
        dur = audio_durations[i] if i < len(audio_durations) else 0.0
        intent = s.get("intent") or s.get("scene_intent") or "default"
        wpm = measure_speech_rate(text, dur)
        risk = comprehension_risk(text, intent, actual_wpm=wpm or None)
        profile = ROLE_PACING[role_for(intent)]
        flags = []
        if wpm and wpm > profile["max_wpm"]:
            flags.append(f"rushed: {wpm:.0f} wpm > {profile['max_wpm']:.0f}")
        if risk["grade"] == "high":
            flags.append("high comprehension risk")
        if flags:
            high_risk.append({"scene": i, "flags": flags, "risk": risk})
        rows.append({
            "scene": i, "words": len(text.split()), "duration_s": round(dur, 2),
            "wpm": wpm, "intent": intent, "role": role_for(intent),
            "comprehension_risk": risk,
            "flags": flags,
        })
    return {
        "rows": rows,
        "high_risk_scenes": high_risk,
        "avg_wpm": round(
            sum(r["wpm"] for r in rows if r["wpm"]) /
            max(1, sum(1 for r in rows if r["wpm"])), 1),
        "rushed_scene_count": len(high_risk),
    }
