"""V16 WP9 — mood-tagged music library, library SFX, sting wiring, and
beat-snapped cuts (DESIGN.md S9 / 15.2 WP9).

This module never replaces the existing procedural audio in
`engine.procedural_audio` / `engine.v14_assembly` — it only *selects and
prepares* real library assets (when the on-disk library has one for the
story's dominant mood / an event's kind) and hands them to
`engine.v14_assembly`'s existing mix/loudnorm pipeline via the optional
`music["track"]`, `sfx_library` and `sting_audio` plan keys. When the
library has nothing for a mood or a kind, callers get `None`/no entry back
and `v14_assembly` falls through to its unchanged procedural underscore/sfx
(load-bearing fallback, per AGENTS.md — never removed or narrowed).

Layout on disk (repo root):
    assets/music/<mood>/*.{ogg,mp3,wav}   mood in MOODS below
    assets/music/licences.csv             one row per file (mood,file,...)
    assets/sfx/<kind>/*.{ogg,mp3,wav}     kind in {whoosh, tick, pulse}
    assets/sfx/licences.csv               one row per file (kind,file,...)

Every asset file found on disk MUST have a licence row, or loading raises
(fail loud rather than ship an unlicensed asset).
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np

from engine.procedural_audio import SR, load_wav, save_wav

MOODS = ("wonder", "tension", "mystery", "triumph", "calm")
DEFAULT_MOOD = "wonder"

# Coarse per-shot "function" (v15_pipeline.INTENSITY's own vocabulary) ->
# music mood. This IS the "selection from the story arc" (DESIGN.md WP9):
# the mood with the most total shot-duration in a story wins.
FUNCTION_MOOD = {
    "HOOK": "mystery",
    "CURIOSITY": "mystery",
    "EXPLANATION": "calm",
    "ESCALATION": "tension",
    "REVEAL": "wonder",
    "PAYOFF": "triumph",
}

_AUDIO_EXTS = (".ogg", ".mp3", ".wav")


# --------------------------------------------------------------- arc/mood --

def arc_mood_weights(functions: list, durations: list) -> dict:
    """Story-arc -> mood weights, normalised to sum to 1. Unknown/missing
    functions fall back to DEFAULT_MOOD so every story gets a weight."""
    weights = {m: 0.0 for m in MOODS}
    for fn, d in zip(functions, durations):
        mood = FUNCTION_MOOD.get(fn, DEFAULT_MOOD)
        weights[mood] += max(float(d or 0.0), 0.0)
    total = sum(weights.values())
    if total <= 0:
        return {DEFAULT_MOOD: 1.0}
    return {m: w / total for m, w in weights.items() if w > 0}


def dominant_mood(weights: dict) -> str:
    """Highest-weight mood; ties broken alphabetically (deterministic)."""
    return sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


# ------------------------------------------------------------- licence CSV --

def load_licence_rows(csv_path) -> list:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------- music library --

def load_music_library(music_dir) -> dict:
    """mood -> [{"path": Path, "licence": row}], every file licence-checked."""
    music_dir = Path(music_dir)
    rows = load_licence_rows(music_dir / "licences.csv")
    by_file = {r["file"]: r for r in rows}
    library = {m: [] for m in MOODS}
    if not music_dir.is_dir():
        return library
    for mood_dir in sorted(p for p in music_dir.iterdir() if p.is_dir()):
        mood = mood_dir.name
        if mood not in library:
            continue
        for f in sorted(mood_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in _AUDIO_EXTS:
                continue
            rel = f"{mood}/{f.name}"
            if rel not in by_file:
                raise ValueError(
                    f"music asset {rel!r} has no licence row in "
                    f"{music_dir / 'licences.csv'}")
            library[mood].append({"path": f, "licence": by_file[rel]})
    return library


def select_track(mood_weights: dict, library: dict, seed: str = "") -> tuple:
    """(track_or_None, mood). Deterministic pick within the mood's tracks
    via a seed hash, so the same story always gets the same track."""
    mood = dominant_mood(mood_weights)
    tracks = library.get(mood) or []
    if not tracks:
        return None, mood
    idx = int(hashlib.sha256(str(seed).encode()).hexdigest(), 16) % len(tracks)
    return tracks[idx], mood


def select_music_for_story(functions: list, durations: list, music_dir,
                           seed: str = "") -> dict:
    weights = arc_mood_weights(functions, durations)
    library = load_music_library(music_dir)
    track, mood = select_track(weights, library, seed=seed)
    return {"mood": mood, "weights": weights, "track": track}


# ----------------------------------------------------------- sfx library --

def load_sfx_library(sfx_dir) -> dict:
    """kind -> {"path": Path, "licence": row} (first file found per kind,
    every file licence-checked)."""
    sfx_dir = Path(sfx_dir)
    rows = load_licence_rows(sfx_dir / "licences.csv")
    by_file = {r["file"]: r for r in rows}
    library: dict = {}
    if not sfx_dir.is_dir():
        return library
    for kind_dir in sorted(p for p in sfx_dir.iterdir() if p.is_dir()):
        kind = kind_dir.name
        files = sorted(p for p in kind_dir.iterdir()
                       if p.is_file() and p.suffix.lower() in _AUDIO_EXTS)
        if not files:
            continue
        f = files[0]
        rel = f"{kind}/{f.name}"
        if rel not in by_file:
            raise ValueError(
                f"sfx asset {rel!r} has no licence row in "
                f"{sfx_dir / 'licences.csv'}")
        library[kind] = {"path": f, "licence": by_file[rel]}
    return library


def load_sfx_clip(path, gain: float = 0.25) -> np.ndarray:
    """Decode + peak-normalise a library SFX file to the same ~0.25 peak
    convention as engine.procedural_audio.sfx()."""
    y = load_wav(path).astype(np.float32)
    peak = float(np.max(np.abs(y)) or 1.0)
    return (y / peak * gain).astype(np.float32)


# --------------------------------------------------------- bed fit/loop --

def _fit_and_loop(y: np.ndarray, n: int, xfade_s: float = 1.5) -> np.ndarray:
    """Trim to n samples, or loop with an equal-power crossfade at the seam
    so a short track can underscore a longer video without an audible
    click at the repeat point."""
    if len(y) >= n:
        return y[:n]
    if len(y) == 0:
        return np.zeros((n, y.shape[1] if y.ndim == 2 else 1), dtype=np.float32)
    xfade = min(int(xfade_s * SR), len(y) - 1) if len(y) > 1 else 0
    out = y.copy()
    while len(out) < n:
        if xfade > 0:
            head, tail = y[:xfade], out[-xfade:]
            fo = np.linspace(1.0, 0.0, xfade)[:, None]
            fi = np.linspace(0.0, 1.0, xfade)[:, None]
            out = np.concatenate([out[:-xfade], tail * fo + head * fi,
                                  y[xfade:]])
        else:
            out = np.concatenate([out, y])
    return out[:n]


def fit_track_to_length(path, total_s: float, xfade_s: float = 1.5) -> np.ndarray:
    y = load_wav(path).astype(np.float32)
    n = int(round(total_s * SR))
    return _fit_and_loop(y, n, xfade_s=xfade_s)


def build_library_bed(path, total_s: float, gain: float = 0.16) -> np.ndarray:
    y = fit_track_to_length(path, total_s)
    peak = float(np.max(np.abs(y)) or 1.0)
    return (y / peak * gain).astype(np.float32)


# ------------------------------------------------------------------ sting --

def overlay_sting(mix_path, sting_path, out_path):
    """Additive overlay of the brand sting at t=0 of an already-built mix
    (design: sting is an OVERLAY, not a pre-roll — it does not shift the
    timeline). Reuses procedural_audio.load_wav/save_wav (v14 mix/loudnorm
    machinery), never reimplements decode/encode."""
    mix = load_wav(mix_path).astype(np.float32)
    sting = load_wav(sting_path).astype(np.float32)
    m = min(len(sting), len(mix))
    out = mix.copy()
    out[:m] += sting[:m]
    return save_wav(out_path, np.clip(out, -0.98, 0.98))


# ------------------------------------------------------- beat-snapped cuts --

def _onset_envelope(mono: np.ndarray, frame: int = 2048,
                    hop: int = 512) -> np.ndarray:
    """Spectral-flux onset strength, one value per hop (numpy/scipy only —
    no new dependency; not librosa-grade, sufficient for a ±80ms snap
    decision, not for musicological beat tracking)."""
    n_frames = max(0, 1 + (len(mono) - frame) // hop)
    if n_frames <= 1:
        return np.zeros(max(n_frames, 0))
    window = np.hanning(frame)
    mags = np.abs(np.fft.rfft(
        np.stack([mono[i * hop:i * hop + frame] * window
                 for i in range(n_frames)]), axis=1))
    flux = np.maximum(mags[1:] - mags[:-1], 0.0).sum(axis=1)
    return np.concatenate([[0.0], flux])


def _estimate_tempo(env: np.ndarray, hop_s: float,
                    bpm_range: tuple = (60.0, 180.0)) -> float:
    if len(env) < 4:
        return 120.0
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lo = max(1, int(round(60.0 / bpm_range[1] / hop_s)))
    hi = min(len(ac) - 1, int(round(60.0 / bpm_range[0] / hop_s)))
    if hi <= lo:
        return 120.0
    lag = lo + int(np.argmax(ac[lo:hi + 1]))
    period_s = lag * hop_s
    return 60.0 / period_s if period_s > 0 else 120.0


def detect_beats(y: np.ndarray, sr: int = SR, frame: int = 2048,
                 hop: int = 512) -> tuple:
    """(beat_times_s, bpm) for a stereo/mono float array. Naive but
    deterministic fixed-period tracker: estimate tempo from the onset
    envelope's autocorrelation, anchor phase on the strongest onset in the
    first 2s, then locally snap each period-spaced beat to the nearest
    onset peak within +/-60ms."""
    mono = y.mean(axis=1) if y.ndim == 2 else y
    env = _onset_envelope(mono, frame=frame, hop=hop)
    hop_s = hop / sr
    if len(env) == 0:
        return [], 120.0
    bpm = _estimate_tempo(env, hop_s)
    period = 60.0 / bpm
    anchor_end = min(len(env), max(1, int(round(2.0 / hop_s))))
    t = int(np.argmax(env[:anchor_end])) * hop_s
    total_dur = len(env) * hop_s
    search = max(1, int(round(0.06 / hop_s)))
    beats = []
    while t < total_dur:
        idx = int(round(t / hop_s))
        lo_i, hi_i = max(0, idx - search), min(len(env), idx + search + 1)
        t_adj = (lo_i + int(np.argmax(env[lo_i:hi_i]))) * hop_s \
            if hi_i > lo_i else t
        beats.append(round(t_adj, 4))
        t += period
    return beats, bpm


def snap_cuts_to_beats(cuts: list, word_times: list, beats: list,
                       tol: float = 0.08) -> list:
    """DESIGN.md S9: snap a cut to the nearest music beat only where a
    narration word boundary is ALSO within `tol` of that beat — i.e. only
    tighten cuts that were already landing on a word boundary, never move a
    cut that has no narration justification for moving."""
    out = []
    for c in cuts:
        moved = c
        if word_times and beats:
            nearest_word = min(word_times, key=lambda w: abs(w - c))
            if abs(nearest_word - c) <= tol:
                nearest_beat = min(beats, key=lambda b: abs(b - c))
                if abs(nearest_beat - c) <= tol:
                    moved = round(nearest_beat, 4)
        out.append(moved)
    return out


# --------------------------------------------------------------- manifest --

def _bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def manifest_rows(track: dict | None, sfx_used: dict | None,
                  sting_path) -> list:
    """DESIGN.md S11 manifest asset rows for the music/sfx/sting actually
    used in one render (empty list entries are simply omitted, they fall
    back to the existing untracked procedural stems)."""
    rows = []
    if track:
        L = track["licence"]
        rows.append({"kind": "music", "file": str(track["path"]),
                     "title": L.get("title"), "artist": L.get("artist"),
                     "source": L.get("source"), "license": L.get("license"),
                     "commercial_ok": _bool(L.get("commercial_ok")),
                     "attribution_required": _bool(
                         L.get("attribution_required")),
                     "attribution_text": L.get("attribution_text")})
    for kind, entry in (sfx_used or {}).items():
        L = entry["licence"]
        rows.append({"kind": "sfx", "file": str(entry["path"]),
                     "title": L.get("title"), "artist": L.get("artist"),
                     "source": L.get("source"), "license": L.get("license"),
                     "commercial_ok": _bool(L.get("commercial_ok"))})
    if sting_path:
        rows.append({"kind": "sting", "file": str(sting_path),
                     "source": "engine.brand.sting_audio (procedural)",
                     "license": "original, generated in-repo",
                     "commercial_ok": True})
    return rows
