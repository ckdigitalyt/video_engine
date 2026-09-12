"""V9 procedural audio engine — synthesizes the two new stems locally with
numpy (no samples, no external services, deterministic seed).

Stems (V9 4-stem mix, engine/audio_mix.py):
  L1 voice      - mastered narration (loudnorm I=-14, done by the mixer)
  L2 underscore - low-key rhythmic documentary bed; per-shot gain pegged to
                  the planv8 intensity tier (0.62 discovery / 0.78 escalation
                  / 0.85 payoff), ducked -16 dB under narration with 250 ms
                  attack / 500 ms release (exact envelope math here, no
                  sidechain guesswork)
  L3 sfx        - existing event-synced whoosh/tick/pulse track (mixer)
  L4 ambience   - low-level room tone selected by story_grammar key:
                  science -> subtle electrical hum, history -> room tone,
                  geography -> atmospheric air, engineering -> mechanical hum

Rollback: the whole layer is gated by V9_AUDIO=0 in engine/flags.py; every
function here is pure synthesis (given the same inputs it returns the same
bytes) so A/B against the V6 mix is trivial.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
_SEED = 42

# Ducking spec (V9): -16 dB under narration, 250 ms attack, 500 ms release
DUCK_DB = 16.0
DUCK_ATTACK_S = 0.25
DUCK_RELEASE_S = 0.50

# Intensity tier mapping (planv8 phases): 0.62 -> 0, 0.85 -> 1
_I_LO, _I_HI = 0.62, 0.85


def _norm_intensity(i: float) -> float:
    try:
        v = (float(i) - _I_LO) / (_I_HI - _I_LO)
    except (TypeError, ValueError):
        return 0.0
    return min(max(v, 0.0), 1.0)


def _fft_bandpass(y: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """FFT brickwall bandpass with soft edges (fine for stationary tones)."""
    n = len(y)
    if n == 0:
        return y
    Y = np.fft.rfft(y)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    mask = np.clip((f - lo) / max(lo * 0.25, 1.0), 0.0, 1.0) * \
        np.clip((hi - f) / max(hi * 0.25, 1.0), 0.0, 1.0)
    return np.fft.irfft(Y * mask, n)


def _fft_lowpass(y: np.ndarray, cutoff: float) -> np.ndarray:
    return _fft_bandpass(y, 0.0, cutoff)


def _t(dur: float) -> np.ndarray:
    return np.arange(int(round(dur * SR))) / SR


def _env_per_shot(gains: list, shot_durs: list, dur: float,
                  ramp: float = 0.6) -> np.ndarray:
    """Piecewise-constant per-shot gains with linear ramps at boundaries."""
    n = int(round(dur * SR))
    if not gains:
        gains = [0.5]
    durs = [float(d) for d in (shot_durs or [])]
    while len(durs) < len(gains):
        durs.append(max(dur - sum(durs), 0.5))
    total = sum(durs) or dur
    durs = [d * dur / total for d in durs]
    kp_t, kp_v = [0.0], [gains[0]]
    t0 = 0.0
    for j, d in enumerate(durs[:len(gains)]):
        b = t0 + d
        kp_t += [max(b - ramp / 2, 0.0), min(b + ramp / 2, dur)]
        kp_v += [gains[j], gains[j + 1] if j + 1 < len(gains) else gains[j]]
        t0 = b
    kp_t, kp_v = kp_t[:len(kp_v)], kp_v[:len(kp_t)]
    return np.interp(np.arange(n) / SR, kp_t, kp_v)


def underscore(dur: float, intensities: list, shot_durs: list) -> np.ndarray:
    """Low-key rhythmic documentary bed (A-minor pad + 68 BPM soft pulse).

    Per-shot gain pegged to the beat's intensity tier: 0.62 -> 0.35,
    0.85 -> 0.80 (linear in between). Returns float32 (n, 2), peak ~0.16.
    """
    rng = np.random.default_rng(_SEED)
    t = _t(dur)
    n = len(t)
    pad = np.zeros(n)
    for f0, amp in ((110.0, 0.50), (164.81, 0.30), (220.0, 0.22)):
        det = 1.0 + 0.0015 * np.sin(2 * np.pi * 0.11 * t + f0 * 0.7)
        ph = 2 * np.pi * f0 * np.cumsum(det) / SR
        trem = 0.78 + 0.22 * np.sin(2 * np.pi * 0.13 * t + f0 * 0.01)
        pad += amp * np.sin(ph) * trem
    pad = _fft_lowpass(pad, 900.0)

    beat = 60.0 / 68.0  # 68 BPM
    pulse = np.zeros(n)
    k = 0
    while k * beat < dur:
        i0 = int(k * beat * SR)
        seg = int(0.28 * SR)
        if i0 + seg > n:
            break
        tt = np.arange(seg) / SR
        # V11 P1b-fix — the thump sits an octave up (110 Hz = the pad root,
        # A2): a 55 Hz fundamental is a tonal sub-bass ring that lands in
        # the 30-80 Hz band the hierarchy QA measures, exactly where the
        # narration pauses are supposed to stay silent. Accent rule: the
        # underscore never places tonal energy in the sub-bass band.
        thump = np.sin(2 * np.pi * 110.0 * tt * (1 + 0.6 * np.exp(-tt * 18)))
        pulse[i0:i0 + seg] += 0.9 * thump * np.exp(-tt * 16)
        if k % 2 == 1:  # faint offbeat air tick
            i1 = i0 + int(0.5 * beat * SR)
            dt = int(0.035 * SR)
            if i1 + dt < n:
                tick = _fft_bandpass(rng.standard_normal(dt), 2500.0, 7000.0)
                tick *= np.hanning(dt) * np.exp(-np.arange(dt) / SR * 60)
                pulse[i1:i1 + dt] += 0.10 * tick
        k += 1

    sig = 0.55 * pad + 0.50 * pulse
    gains = [0.35 + 0.45 * _norm_intensity(i) for i in (intensities or [])]
    sig = sig * _env_per_shot(gains, shot_durs, dur)
    peak = float(np.max(np.abs(sig)) or 1.0)
    sig = sig / peak * 0.16
    # tiny Haas widening (6.5 ms on the right channel)
    d = int(0.0065 * SR)
    right = np.concatenate([np.zeros(d), sig[:-d]])
    return np.stack([sig, 0.9 * right + 0.1 * sig],
                    axis=1).astype(np.float32)


def ambience(dur: float, grammar_key: str) -> np.ndarray:
    """Low-level background room tone by story_grammar key.

    science -> subtle electrical hum; history -> room tone (warm);
    geography -> atmospheric air; engineering -> mechanical hum;
    default -> neutral air. Returns float32 (n, 2), peak ~0.011 (-39 dBFS).
    """
    rng = np.random.default_rng(_SEED + 1)
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    peak = 0.011
    if grammar_key == "science":
        y = 0.50 * np.sin(2 * np.pi * 50 * t) \
            + 0.22 * np.sin(2 * np.pi * 100 * t + 0.7) \
            + 0.10 * np.sin(2 * np.pi * 150 * t + 1.3)
        hiss = _fft_lowpass(rng.standard_normal(n), 1200.0) * 0.25
        mono = y * 0.6 + hiss
        lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.07 * t)
        mono *= lfo
    elif grammar_key == "history":
        brown = np.cumsum(rng.standard_normal(n))
        brown -= np.linspace(brown[0], brown[-1], n)  # detrend
        mono = _fft_lowpass(brown / (np.max(np.abs(brown)) or 1.0), 500.0)
    elif grammar_key == "geography":
        air = _fft_bandpass(rng.standard_normal(n), 150.0, 900.0)
        air /= (np.max(np.abs(air)) or 1.0)
        mono = air * (0.80 + 0.20 * np.sin(2 * np.pi * 0.05 * t))
    elif grammar_key == "engineering":
        y = 0.45 * np.sin(2 * np.pi * 60 * t) \
            + 0.18 * np.sin(2 * np.pi * 120 * t + 0.4)
        mono = y * (0.85 + 0.15 * np.sin(2 * np.pi * 2.0 * t))
    else:
        mono = _fft_lowpass(rng.standard_normal(n), 300.0)
        mono /= (np.max(np.abs(mono)) or 1.0)
    mono = mono / (np.max(np.abs(mono)) or 1.0) * peak
    rl = rng.standard_normal(n)
    rl = _fft_lowpass(rl, 800.0)
    rl /= (np.max(np.abs(rl)) or 1.0)
    return np.stack([mono, mono * 0.92 + 0.08 * rl * peak],
                    axis=1).astype(np.float32)


def load_wav(path) -> np.ndarray:
    """Decode any audio file to float32 (n, 2) at SR via ffmpeg."""
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
         "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(SR), "-ac", "2",
         "-"], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"load_wav {path}: {p.stderr[-300:]}")
    x = np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, 2)
    return x


def save_wav(path, y: np.ndarray) -> Path:
    """Write float32 (n, 2) [or (n,)] as 16-bit PCM wav."""
    path = Path(path)
    y = np.asarray(y)
    if y.ndim == 1:
        y = np.stack([y, y], axis=1)
    y = np.clip(y, -1.0, 1.0)
    pcm = (y * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


def duck_gain(voice: np.ndarray, duck_db: float = DUCK_DB,
              attack: float = DUCK_ATTACK_S,
              release: float = DUCK_RELEASE_S,
              hop_ms: float = 50.0) -> np.ndarray:
    """Sample-rate gain curve: full -duck_db where voice is active, smooth
    attack/release recovery where it is not. Envelope at 50 ms hops:
    RMS -> normalize (92nd pct) -> attack/release smoother."""
    if voice.ndim > 1:
        voice = voice.mean(axis=1)
    n = len(voice)
    hop = max(1, int(SR * hop_ms / 1000.0))
    m = max(n // hop, 1)
    win = voice[:m * hop].reshape(m, hop)
    rms = np.sqrt(np.mean(win * win, axis=1) + 1e-12)
    ref = max(float(np.percentile(rms[rms > 1e-6], 92)), 1e-6) \
        if np.any(rms > 1e-6) else 1.0
    env = np.clip(rms / ref, 0.0, 1.0)
    a_c = float(np.exp(-hop_ms / 1000.0 / max(attack, 1e-3)))
    r_c = float(np.exp(-hop_ms / 1000.0 / max(release, 1e-3)))
    sm = np.zeros_like(env)
    acc = 0.0
    for i, e in enumerate(env):
        c = a_c if e > acc else r_c
        acc = c * acc + (1.0 - c) * e
        sm[i] = acc
    floor = 10.0 ** (-duck_db / 20.0)
    gain = 1.0 - (1.0 - floor) * sm
    return np.interp(np.arange(n),
                     np.arange(m) * hop + hop / 2.0, gain).astype(np.float32)


def duck_under(voice_path, stem_path, out_path, duck_db: float = DUCK_DB,
               attack: float = DUCK_ATTACK_S,
               release: float = DUCK_RELEASE_S) -> Path:
    """Duck `stem_path` by -duck_db under the narration in `voice_path`
    (250 ms attack / 500 ms release). Missing voice -> no duck."""
    stem = load_wav(stem_path)
    try:
        voice = load_wav(voice_path) if voice_path else None
    except RuntimeError:
        voice = None
    if voice is None or len(voice) == 0:
        g = np.ones(len(stem), dtype=np.float32)
    else:
        n = max(len(voice), len(stem))
        v = np.zeros(n, dtype=np.float32)
        v[:len(voice)] = voice[:, 0]
        g = duck_gain(v, duck_db, attack, release)
    out = stem * g[:len(stem), None]
    return save_wav(out_path, out)


def sum_stems(stems: list, total_s: float, out_path) -> Path:
    """Sum (path_or_None, weight) pairs into one float master, clipped.
    Short stems are zero-padded; the master is exactly total_s long."""
    n = int(round(total_s * SR))
    acc = np.zeros((n, 2), dtype=np.float64)
    for item in stems:
        if not item:
            continue
        path, weight = item
        y = load_wav(path)
        m = min(len(y), n)
        acc[:m] += y[:m].astype(np.float64) * float(weight)
    return save_wav(out_path, np.clip(acc, -0.98, 0.98))


def write_underscore(total_s: float, intensities: list, shot_durs: list,
                     out_path) -> Path:
    return save_wav(out_path, underscore(total_s, intensities, shot_durs))


def underscore_accent(dur: float, intensities: list, shot_durs: list,
                      accent_floor: float = 0.78) -> np.ndarray:
    """V11 P1 §9 — the underscore as an ACCENT, not a continuous bed.

    Same signal as underscore(), but the gain envelope is zeroed for every
    shot whose intensity tier sits below `accent_floor` (the escalation
    tier): music supports only the escalation/reveal/payoff phases and
    stays out of the hook/orientation/discovery shots, where narration +
    intentional SFX + deliberate silence carry the mix. Ramps at the shot
    boundaries keep the entries/exits musical."""
    sig = underscore(dur, intensities, shot_durs)
    gains = [1.0 if float(i or 0) >= accent_floor else 0.0
             for i in (intensities or [])]
    if not gains or not any(gains):
        return sig * 0.0
    env = _env_per_shot(gains, shot_durs, dur)
    if sig.ndim == 2:  # underscore() returns stereo (n, 2)
        env = env[:, None]
    return sig * env


def write_underscore_accent(total_s: float, intensities: list, shot_durs: list,
                            out_path, accent_floor: float = 0.78) -> Path:
    return save_wav(out_path, underscore_accent(total_s, intensities,
                                                shot_durs, accent_floor))


def write_ambience(total_s: float, grammar_key: str, out_path) -> Path:
    return save_wav(out_path, ambience(total_s, grammar_key))
