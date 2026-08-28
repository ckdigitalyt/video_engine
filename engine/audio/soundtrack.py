"""Soundtrack stage (wave-2 audio, glm_review_v3 §4.2).

Music bed + spot SFX, added AFTER voice mastering — the pipeline's first-class
audio timeline (narration → master) gains a soundtrack layer:

  - instrumental bed: synthesized locally (numpy → WAV, no downloads, no
    paid APIs), sidechain-ducked ~18 LUFS under the mastered voice
  - 3–4 spot SFX keyed to beat times from audio_timing.json / visualspec
    beats (pour on the paint fill, pop on formula reveals, sting on the
    end card, whoosh on the hook)

Everything is deterministic and offline: pad chords from stacked detuned
sines with a slow attack, noise sweeps for whoosh/pour, short sine blips
for pop, a decayed triad for the sting.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from engine.audio.timeline import ffmpeg, measure_loudness

BED_UNDER_VO_LUFS = 18.0   # bed sits this many LUFS below the voice
SR = 44100


# ────────────────────────────────────────────────────────────────────────
# Synthesis (local, deterministic)
# ────────────────────────────────────────────────────────────────────────
def _write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mono = np.clip(samples, -1.0, 1.0)
    pcm = (mono * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return path


def _pad_chord(freqs: list[float], dur: float, sr: int = SR) -> np.ndarray:
    """Slow-attack detuned pad chord (calm bed, no rhythm to fight TTS)."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for f in freqs:
        for detune in (-0.4, 0.0, 0.4):  # cents-ish shimmer
            out += 0.12 * np.sin(2 * np.pi * (f + detune) * t)
    # slow attack / long release envelope
    attack = int(min(2.0, dur * 0.25) * sr)
    release = int(min(3.0, dur * 0.35) * sr)
    env = np.ones(n)
    env[:attack] = np.linspace(0.0, 1.0, attack)
    env[n - release:] = np.linspace(1.0, 0.0, release)
    return out * env


def synthesize_music_bed(duration_s: float, out_wav: Path,
                         mood: str = "calm", sr: int = SR) -> Path:
    """Deterministic instrumental bed for `duration_s` seconds.

    Am progression (Am–F–C–G) in a warm low register, ~-20 dBFS pad —
    the bed is quiet by construction and gets its final level from the
    18-LUFS-under-voice duck at mix time.
    """
    dur = max(1.0, float(duration_s))
    progressions = {
        "calm": [110.0, 87.31, 65.41, 98.0],      # A2 F2 C2 G2
        "tension": [110.0, 116.54, 110.0, 103.83],  # A2 Bb2 A2 Ab2
    }
    roots = progressions.get(mood, progressions["calm"])
    chord_dur = max(2.0, dur / 4.0)
    bed = np.zeros(int(dur * sr) + sr)
    tpos = 0.0
    i = 0
    while tpos < dur:
        root = roots[i % len(roots)]
        freqs = [root, root * 1.5, root * 2.0, root * 2.5]  # fifth + octaves
        chord = _pad_chord(freqs, min(chord_dur * 1.05, dur - tpos + 0.5), sr)
        a = int(tpos * sr)
        b = min(a + len(chord), len(bed))
        bed[a:b] += chord[:b - a]
        tpos += chord_dur
        i += 1
    bed = bed[:int(dur * sr)]
    peak = float(np.max(np.abs(bed))) or 1.0
    return _write_wav(out_wav, bed / peak * 0.35, sr)


def synthesize_sfx(kind: str, out_wav: Path, sr: int = SR) -> Path:
    """One-shot spot SFX: whoosh | pour | pop | sting.  Deterministic."""
    rng = np.random.default_rng(42)
    if kind == "whoosh":
        dur = 0.8
        n = int(dur * sr)
        t = np.arange(n) / sr
        noise = rng.standard_normal(n)
        # crude lowpass moving average whose window widens then narrows
        k = 64
        kernel = np.hanning(k)
        noise = np.convolve(noise, kernel / kernel.sum(), mode="same")
        env = np.sin(np.pi * t / dur) ** 2
        sig = noise * env * 0.5
    elif kind == "pour":
        dur = 1.2
        n = int(dur * sr)
        noise = rng.standard_normal(n)
        kernel = np.hanning(24)
        noise = np.convolve(noise, kernel / kernel.sum(), mode="same")
        env = np.minimum(np.linspace(0, 1, n) * 4, 1.0) * \
            np.linspace(1.0, 0.85, n)
        sig = noise * env * 0.4
    elif kind == "pop":
        dur = 0.18
        n = int(dur * sr)
        t = np.arange(n) / sr
        f = np.linspace(880, 440, n)  # downward chirp blip
        sig = 0.5 * np.sin(2 * np.pi * np.cumsum(f) / sr) * \
            np.exp(-t * 28)
    elif kind == "sting":
        dur = 2.2
        n = int(dur * sr)
        t = np.arange(n) / sr
        sig = np.zeros(n)
        for f, amp in ((440.0, 0.22), (554.37, 0.18), (659.25, 0.15)):
            sig += amp * np.sin(2 * np.pi * f * t) * np.exp(-t * 1.8)
        attack = int(0.02 * sr)
        sig[:attack] *= np.linspace(0, 1, attack)
    else:
        raise ValueError(f"unknown sfx kind: {kind!r}")
    peak = float(np.max(np.abs(sig))) or 1.0
    return _write_wav(out_wav, sig / peak * 0.6, sr)


# ────────────────────────────────────────────────────────────────────────
# Beat-keyed cue selection (from audio_timing.json / visualspec beats)
# ────────────────────────────────────────────────────────────────────────
def sfx_cues_from_beats(beats: list[dict],
                        max_cues: int = 4) -> list[dict]:
    """Pick 3–4 spot-SFX moments from beat semantics.

    Priority: hook whoosh → fill/pour → formula-reveal pop → end-card
    sting.  Times are beat starts (seconds; accumulated from durations
    when the spec is not yet time-anchored).  Dedup close moments.
    """
    cues: list[dict] = []
    t = 0.0
    for i, b in enumerate(beats or []):
        start = float(b.get("start", 0.0) or 0.0)
        if start <= 0.0:
            start = t
        t = start + float(b.get("duration", 0.0) or 0.0)
        role = str(b.get("role", "") or b.get("intent", "")).lower()
        actions = " ".join(str(a.get("action", a.get("type", "")))
                           for a in (b.get("semantic_actions", []) or []) +
                           (b.get("transformations", []) or []))
        is_final = i == len(beats) - 1
        kind = None
        if not cues and ("hook" in role or "question" in role):
            kind = "whoosh"
        elif "fill" in actions:
            kind = "pour"
        elif ("measure" in actions or "reveal" in actions) and not is_final:
            kind = "pop"
        elif is_final or "payoff" in role or "close" in role:
            kind = "sting"
        if kind and all(abs(start - c["time"]) > 1.5 for c in cues):
            cues.append({"time": round(start, 3), "type": kind,
                         "volume": 1.0})
    # sting on the final beat even when the role filters missed it
    if beats and not any(c["type"] == "sting" for c in cues):
        last_start = 0.0
        acc = 0.0
        for b in beats:
            last_start = float(b.get("start", 0.0) or 0.0) or acc
            acc = last_start + float(b.get("duration", 0.0) or 0.0)
        cues.append({"time": round(last_start, 3),
                     "type": "sting", "volume": 1.0})
    cues.sort(key=lambda c: c["time"])
    # keep the LAST sting (end card) plus the earliest others
    if len(cues) > max_cues:
        sting = [c for c in cues if c["type"] == "sting"][-1:]
        others = [c for c in cues if c not in sting][:max_cues - len(sting)]
        cues = sorted(others + sting, key=lambda c: c["time"])
    return cues


# ────────────────────────────────────────────────────────────────────────
# Mix: bed (ducked ~18 LUFS under VO) + SFX → soundtrack track
# ────────────────────────────────────────────────────────────────────────
def build_soundtrack(narration_path: Path, cues: list[dict],
                     total_duration: float, out_aac: Path,
                     workdir: Path | None = None,
                     bed_under_lufs: float = BED_UNDER_VO_LUFS) -> Path:
    """Build the full-length soundtrack track and mix it under the voice.

    The bed level is calibrated from the MEASURED narration loudness so
    the bed sits `bed_under_lufs` LU below it (sidechain-free, fully
    deterministic; the voice then masters on top untouched).
    """
    narration_path = Path(narration_path)
    out_aac = Path(out_aac)
    workdir = Path(workdir) if workdir else out_aac.parent
    workdir.mkdir(parents=True, exist_ok=True)
    dur = max(1.0, float(total_duration))

    bed = synthesize_music_bed(dur + 0.5, workdir / "_bed.wav")

    # measure the VO to place the bed exactly N LUFS under it
    vo_lufs = (measure_loudness(narration_path).get("integrated_lufs")
               or -16.0)
    bed_lufs_target = vo_lufs - bed_under_lufs
    bed_meas = measure_loudness(bed).get("integrated_lufs") or -20.0
    gain_db = bed_lufs_target - bed_meas

    # SFX wavs + adelay mixing (mono → stereo at the end)
    inputs: list[str] = ["-i", str(bed)]
    filters: list[str] = [f"[0:a]volume={gain_db:.2f}dB[bed]"]
    mix_ins = "[bed]"
    for i, cue in enumerate(cues, start=1):
        swav = synthesize_sfx(str(cue.get("type", "pop")),
                              workdir / f"_sfx_{i}.wav")
        inputs += ["-i", str(swav)]
        delay_ms = int(max(0.0, float(cue.get("time", 0.0)) * 1000))
        vol = float(cue.get("volume", 1.0))
        filters.append(
            f"[{i}:a]adelay={delay_ms}|{delay_ms},volume={vol:.2f}[s{i}]")
        mix_ins += f"[s{i}]"
    n = len(cues) + 1
    filters.append(
        f"{mix_ins}amix=inputs={n}:duration=longest:normalize=0,"
        "pan=stereo|c0=c0|c1=c0[aux];"
        "[aux]apad=whole_dur=" + f"{dur + 0.5:.2f}[aout]")

    cmd = [ffmpeg(), "-y", *inputs,
           "-filter_complex", ";".join(filters),
           "-map", "[aout]", "-t", f"{dur + 0.2:.2f}",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           str(out_aac)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("soundtrack mix failed: "
                           + proc.stderr[-500:])
    return out_aac


def mix_soundtrack_under_voice(voice_master: Path, soundtrack: Path,
                               out_mix: Path) -> Path:
    """Final stage-after-mastering mux step: voice master + soundtrack.

    The soundtrack is pre-ducked by `build_soundtrack`; this is a plain
    linear mix (voice dominant, soundtrack at its calibrated level).
    """
    out = Path(out_mix)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg(), "-y", "-i", str(voice_master), "-i", str(soundtrack),
        "-filter_complex",
        "[0:a]anull[voice];[1:a]anull[tr];[voice][tr]amix=inputs=2:"
        "duration=first:dropout_transition=2:normalize=0[aout]",
        "-map", "[aout]",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


if __name__ == "__main__":
    print("soundtrack module — local synth only, no external calls")
